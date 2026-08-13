#!/usr/bin/python
# -*- coding: UTF-8 -*-
import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict

import config
import DOTA2
from DBOper import (
    acknowledge_sent_match,
    enqueue_match,
    get_match_outbox,
    get_pending_matches,
    mark_match_attempt,
    mark_match_failed,
    mark_match_sent,
)
from message_sender import MessageSendError
from message_sender import message as send
from player import PLAYER_LIST, Player

logger = logging.getLogger(__name__)

_poll_failures = {}
_next_poll_at = {}
_match_detail_failures = {}
_next_match_detail_at = {}
_priority_poll_until = {}
_next_status_refresh_at = 0.0
_active_dota_account_ids = set()
_active_status_updated_at = 0.0
_steam_history_failures = 0
_steam_history_retry_at = 0.0


def _is_transient_steam_history_failure(exc: Exception):
    message = str(exc)
    status = re.search(r"Steam match history returned HTTP (\d+)", message)
    if status:
        return int(status.group(1)) == 429 or int(status.group(1)) >= 500
    return "Steam match history request failed:" in message


def _open_steam_history_circuit(now, reason):
    global _steam_history_failures, _steam_history_retry_at
    cooldown = config.STEAM_HISTORY_CIRCUIT_COOLDOWN
    _steam_history_retry_at = max(_steam_history_retry_at, now + cooldown)
    _steam_history_failures = 0
    for player in PLAYER_LIST:
        spread = random.uniform(1.0, 1.0 + config.ERROR_BACKOFF_JITTER)
        retry_at = now + cooldown * spread
        _next_poll_at[player.short_steamID] = max(
            _next_poll_at.get(player.short_steamID, 0), retry_at,
        )
    logger.warning(
        "Steam 比赛历史全局熔断 %.0f 秒，恢复后将错峰重试: %s", cooldown, reason,
    )


def _record_steam_history_result(exc=None, now=None):
    global _steam_history_failures
    now = time.monotonic() if now is None else now
    if exc is None:
        _steam_history_failures = 0
        return
    if not _is_transient_steam_history_failure(exc):
        return
    if now < _steam_history_retry_at:
        return
    _steam_history_failures += 1
    if "returned HTTP 429" in str(exc) or (
        _steam_history_failures >= config.STEAM_HISTORY_CIRCUIT_THRESHOLD
    ):
        _open_steam_history_circuit(now, exc)


def steam_id_convert_32_to_64(short_steamID: int) -> int:
    return short_steamID + 76561197960265728


def steam_id_convert_64_to_32(long_steamID: int) -> int:
    return long_steamID - 76561197960265728


def _fetch_latest_match(tracked_player: Player):
    return DOTA2.get_recent_match_ids_by_short_steamID(tracked_player.short_steamID)


def _record_poll_failure(tracked_player: Player, exc: Exception):
    account_id = tracked_player.short_steamID
    failures = _poll_failures.get(account_id, 0) + 1
    _poll_failures[account_id] = failures
    base_delay = min(
        config.ERROR_BACKOFF_MAX,
        config.ERROR_BACKOFF_BASE * (2 ** min(failures - 1, 5)),
    )
    delay = min(
        config.ERROR_BACKOFF_MAX,
        base_delay * random.uniform(
            1.0 - config.ERROR_BACKOFF_JITTER,
            1.0 + config.ERROR_BACKOFF_JITTER,
        ),
    )
    _next_poll_at[account_id] = time.monotonic() + delay
    _record_steam_history_result(exc)
    logger.warning(
        "读取 %s 的最新比赛失败，第 %s 次；%.0f 秒后重试: %s",
        tracked_player.nickname,
        failures,
        delay,
        exc,
    )


def _record_poll_success(tracked_player: Player, now=None):
    _poll_failures.pop(tracked_player.short_steamID, None)
    now = time.monotonic() if now is None else now
    _record_steam_history_result(now=now)
    interval = (
        config.ACTIVE_MATCH_POLL_INTERVAL
        if now < _priority_poll_until.get(tracked_player.short_steamID, 0)
        else config.INACTIVE_MATCH_POLL_INTERVAL
    )
    _next_poll_at[tracked_player.short_steamID] = now + interval


def refresh_match_poll_priorities():
    """Use one batched Steam status call to prioritize likely-active players."""
    global _next_status_refresh_at, _active_dota_account_ids, _active_status_updated_at
    now = time.monotonic()
    if now < _next_status_refresh_at:
        return
    _next_status_refresh_at = now + config.STEAM_STATUS_INTERVAL
    try:
        active_ids = DOTA2.get_active_dota_account_ids(PLAYER_LIST)
    except DOTA2.DOTA2HTTPError as exc:
        logger.warning("Steam 在线状态批量检查失败，将按原计划轮询: %s", exc)
        return
    _active_dota_account_ids = {int(account_id) for account_id in active_ids}
    _active_status_updated_at = now
    for account_id in active_ids:
        _priority_poll_until[account_id] = now + config.ACTIVE_MATCH_GRACE
        _next_poll_at[account_id] = min(_next_poll_at.get(account_id, now), now)


def is_player_currently_in_dota(account_id, now=None):
    """Return True only for a recent Steam presence snapshot showing DOTA 2."""
    now = time.monotonic() if now is None else float(now)
    freshness = max(120.0, float(config.STEAM_STATUS_INTERVAL) * 2.5)
    return (
        _active_status_updated_at > 0
        and now - _active_status_updated_at <= freshness
        and int(account_id) in _active_dota_account_ids
    )


def _record_match_detail_failure(match_id: int):
    failures = _match_detail_failures.get(match_id, 0) + 1
    _match_detail_failures[match_id] = failures
    delay = min(
        config.ERROR_BACKOFF_MAX,
        config.ERROR_BACKOFF_BASE * (2 ** min(failures - 1, 5)),
    )
    _next_match_detail_at[match_id] = time.monotonic() + delay
    return failures, delay


def _record_match_detail_success(match_id: int):
    _match_detail_failures.pop(match_id, None)
    _next_match_detail_at.pop(match_id, None)


def update_DOTA2() -> Dict:
    """Concurrently find new matches without marking them processed."""
    now = time.monotonic()
    if now < _steam_history_retry_at:
        return {}
    eligible = [
        tracked_player
        for tracked_player in PLAYER_LIST
        if now >= _next_poll_at.get(tracked_player.short_steamID, 0)
    ]
    result = {}
    if not eligible:
        return result

    worker_count = max(1, min(config.POLL_WORKERS, len(eligible)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(_fetch_latest_match, tracked_player): tracked_player
            for tracked_player in eligible
        }
        for future in as_completed(futures):
            tracked_player = futures[future]
            try:
                match_ids = future.result()
            except Exception as exc:
                _record_poll_failure(tracked_player, exc)
                continue

            _record_poll_success(tracked_player, now=time.monotonic())
            try:
                cursor_index = match_ids.index(int(tracked_player.last_DOTA2_match_ID))
                unseen = match_ids[:cursor_index]
            except (ValueError, TypeError):
                # Unknown cursors can happen on first import or when history visibility changes.
                # Preserve the old behavior by reporting only the newest match in that case.
                unseen = match_ids[:1]
            for match_id in reversed(unseen):
                result.setdefault(match_id, []).append(tracked_player)

    return result


def _players_by_ids(player_ids):
    wanted = set(int(player_id) for player_id in player_ids)
    return [
        tracked_player
        for tracked_player in PLAYER_LIST
        if tracked_player.short_steamID in wanted
    ]


def _sync_player_objects(player_ids, match_id):
    wanted = set(int(player_id) for player_id in player_ids)
    for tracked_player in PLAYER_LIST:
        if tracked_player.short_steamID in wanted:
            tracked_player.last_DOTA2_match_ID = match_id


def _queue_detected_matches(detected_matches):
    for match_id, detected_players in detected_matches.items():
        if time.monotonic() < _next_match_detail_at.get(match_id, 0):
            continue
        entry = get_match_outbox(match_id)
        detected_ids = [player.short_steamID for player in detected_players]

        if entry and entry['status'] == 'sent':
            acknowledge_sent_match(match_id, detected_ids)
            _sync_player_objects(detected_ids, match_id)
            logger.info("比赛 %s 已发送，仅同步新增玩家状态", match_id)
            continue

        all_ids = set(detected_ids)
        if entry:
            all_ids.update(entry['player_ids'])
            if entry['status'] == 'pending' and all_ids == set(entry['player_ids']):
                # 已持久化的战报由待发队列按退避时间处理，无需重复生成详情。
                continue
        report_players = _players_by_ids(all_ids)

        try:
            payload = DOTA2.generate_match_message(match_id, report_players)
            enqueue_match(match_id, payload, all_ids)
            _record_match_detail_success(match_id)
            logger.info("比赛 %s 已进入待发队列，玩家数: %s", match_id, len(all_ids))
        except DOTA2.DOTA2HTTPError as exc:
            failures, delay = _record_match_detail_failure(match_id)
            logger.warning(
                "比赛 %s 详情尚未就绪，第 %s 次；%.0f 秒后重试: %s",
                match_id,
                failures,
                delay,
                exc,
            )
        except Exception:
            failures, delay = _record_match_detail_failure(match_id)
            logger.exception("比赛 %s 战报生成异常，下轮重试", match_id)


def _deliver_pending_matches():
    for item in get_pending_matches():
        match_id = item['match_id']
        mark_match_attempt(match_id)
        try:
            result = send(item['payload']) or {}
            message_id = result.get('message_id')
        except MessageSendError as exc:
            mark_match_failed(match_id, exc)
            logger.warning("比赛 %s 发送失败，已安排重试: %s", match_id, exc)
            continue
        except Exception as exc:
            mark_match_failed(match_id, exc)
            logger.exception("比赛 %s 发送异常，已安排重试", match_id)
            continue

        player_ids = mark_match_sent(match_id, message_id)
        _sync_player_objects(player_ids, match_id)
        logger.info("比赛 %s 战报发送成功，消息 ID: %s", match_id, message_id)


def update_and_send_message_DOTA2():
    detected_matches = update_DOTA2()
    _queue_detected_matches(detected_matches)
    _deliver_pending_matches()
