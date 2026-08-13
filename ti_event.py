#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""The International event schedule, separate points, bets and settlement."""
import logging
import re
import time
from collections import defaultdict

import requests

import config
import DBOper

logger = logging.getLogger(__name__)
conn = DBOper.conn
c = DBOper.c
_next_refresh_at = 0.0


class TIEventError(RuntimeError):
    pass


def _init_schema():
    with conn:
        c.execute(
            """CREATE TABLE IF NOT EXISTS ti_series (
                league_id INTEGER NOT NULL,
                node_id INTEGER NOT NULL,
                node_group_id INTEGER NOT NULL,
                group_name TEXT NOT NULL,
                node_name TEXT NOT NULL,
                scheduled_time INTEGER NOT NULL DEFAULT 0,
                actual_time INTEGER NOT NULL DEFAULT 0,
                series_id INTEGER NOT NULL DEFAULT 0,
                team_1_id INTEGER NOT NULL DEFAULT 0,
                team_1_name TEXT NOT NULL DEFAULT '',
                team_1_tag TEXT NOT NULL DEFAULT '',
                team_1_abbr TEXT NOT NULL DEFAULT '',
                team_2_id INTEGER NOT NULL DEFAULT 0,
                team_2_name TEXT NOT NULL DEFAULT '',
                team_2_tag TEXT NOT NULL DEFAULT '',
                team_2_abbr TEXT NOT NULL DEFAULT '',
                team_1_wins INTEGER NOT NULL DEFAULT 0,
                team_2_wins INTEGER NOT NULL DEFAULT 0,
                has_started INTEGER NOT NULL DEFAULT 0,
                is_completed INTEGER NOT NULL DEFAULT 0,
                winner_team_id INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                locked_at INTEGER,
                result_signature TEXT NOT NULL DEFAULT '',
                result_confirmations INTEGER NOT NULL DEFAULT 0,
                completed_seen_at INTEGER,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (league_id,node_group_id,node_id)
            )"""
        )
        series_columns = {
            row[1] for row in c.execute('PRAGMA table_info(ti_series)').fetchall()
        }
        for column, definition in (
            ('status', "TEXT NOT NULL DEFAULT 'pending'"),
            ('locked_at', 'INTEGER'),
            ('result_signature', "TEXT NOT NULL DEFAULT ''"),
            ('result_confirmations', 'INTEGER NOT NULL DEFAULT 0'),
            ('completed_seen_at', 'INTEGER'),
        ):
            if column not in series_columns:
                c.execute('ALTER TABLE ti_series ADD COLUMN {} {}'.format(
                    column, definition
                ))
        c.execute(
            """CREATE TABLE IF NOT EXISTS ti_scores (
                group_id INTEGER NOT NULL,
                league_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                score INTEGER NOT NULL,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                wagered INTEGER NOT NULL DEFAULT 0,
                returned INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (group_id,league_id,user_id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS ti_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                league_id INTEGER NOT NULL,
                node_group_id INTEGER NOT NULL,
                node_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                selected_team_id INTEGER NOT NULL,
                selected_team_name TEXT NOT NULL,
                stake INTEGER NOT NULL,
                odds REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                payout INTEGER,
                score_delta INTEGER,
                cancel_reason TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                settled_at INTEGER
            )"""
        )
        c.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_ti_bets_open
               ON ti_bets(group_id,league_id,node_group_id,node_id,user_id)
               WHERE status='open'"""
        )
        c.execute(
            """CREATE INDEX IF NOT EXISTS idx_ti_bets_series_status
               ON ti_bets(league_id,node_group_id,node_id,status)"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS ti_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedupe_key TEXT NOT NULL UNIQUE,
                group_id INTEGER NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at INTEGER NOT NULL,
                sent_at INTEGER
            )"""
        )


_init_schema()


def _collect_teams(groups, teams):
    for group in groups or []:
        for team in group.get('team_standings') or []:
            team_id = int(team.get('team_id') or 0)
            if not team_id:
                continue
            teams[team_id] = {
                'id': team_id,
                'name': str(team.get('team_name') or team.get('team_tag') or team_id).strip(),
                'tag': str(team.get('team_tag') or '').strip(),
                'abbr': str(team.get('team_abbreviation') or '').strip(),
            }
        _collect_teams(group.get('node_groups') or [], teams)


def _collect_nodes(groups, teams, nodes):
    for group in groups or []:
        for node in group.get('nodes') or []:
            node_id = int(node.get('node_id') or 0)
            if not node_id:
                continue
            team_1_id = int(node.get('team_id_1') or 0)
            team_2_id = int(node.get('team_id_2') or 0)
            team_1 = teams.get(team_1_id, {'id': team_1_id, 'name': '', 'tag': '', 'abbr': ''})
            team_2 = teams.get(team_2_id, {'id': team_2_id, 'name': '', 'tag': '', 'abbr': ''})
            team_1_wins = int(node.get('team_1_wins') or 0)
            team_2_wins = int(node.get('team_2_wins') or 0)
            completed = bool(node.get('is_completed'))
            winner_team_id = 0
            result_conflict = False
            matches = node.get('matches') or []
            if completed:
                match_winners = [int(match.get('winning_team_id') or 0) for match in matches]
                if not team_1_id or not team_2_id or team_1_id == team_2_id:
                    result_conflict = True
                elif team_1_wins == team_2_wins:
                    # Valve can briefly mark a node completed before its score
                    # and per-map list arrive. A bare 0:0 is not a final result.
                    result_conflict = bool(matches) or bool(team_1_wins)
                elif matches and all(match_winners):
                    valid_winners = all(
                        winner in (team_1_id, team_2_id) for winner in match_winners
                    )
                    counts_match = (
                        match_winners.count(team_1_id) == team_1_wins
                        and match_winners.count(team_2_id) == team_2_wins
                    )
                    if valid_winners and counts_match:
                        winner_team_id = (
                            team_1_id if team_1_wins > team_2_wins else team_2_id
                        )
                    else:
                        result_conflict = True
            nodes.append({
                'node_id': node_id,
                'node_group_id': int(node.get('node_group_id') or group.get('node_group_id') or 0),
                'group_name': str(group.get('name') or 'TI').strip(),
                'node_name': str(node.get('name') or '').strip(),
                'scheduled_time': int(node.get('scheduled_time') or 0),
                'actual_time': int(node.get('actual_time') or 0),
                'series_id': int(node.get('series_id') or 0),
                'team_1_id': team_1_id,
                'team_1_name': team_1['name'],
                'team_1_tag': team_1['tag'],
                'team_1_abbr': team_1['abbr'],
                'team_2_id': team_2_id,
                'team_2_name': team_2['name'],
                'team_2_tag': team_2['tag'],
                'team_2_abbr': team_2['abbr'],
                'team_1_wins': team_1_wins,
                'team_2_wins': team_2_wins,
                'has_started': 1 if node.get('has_started') else 0,
                'is_completed': 1 if completed else 0,
                'winner_team_id': winner_team_id,
                'result_conflict': result_conflict,
            })
        _collect_nodes(group.get('node_groups') or [], teams, nodes)


def parse_league_data(data):
    """Flatten Valve's recursive league node data into bettable series."""
    if not isinstance(data, dict) or not isinstance(data.get('info'), dict):
        raise TIEventError('Valve 返回了无效的 TI 联赛数据')
    league_id = int(data['info'].get('league_id') or 0)
    if not league_id:
        raise TIEventError('TI 联赛数据缺少 league_id')
    teams = {}
    nodes = []
    _collect_teams(data.get('node_groups') or [], teams)
    _collect_nodes(data.get('node_groups') or [], teams, nodes)
    for node in nodes:
        node['league_id'] = league_id
    return nodes


def _score_row(group_id, league_id, user_id, user_name, now):
    c.execute(
        """INSERT INTO ti_scores(group_id,league_id,user_id,user_name,score,updated_at)
           VALUES (?,?,?,?,?,?) ON CONFLICT(group_id,league_id,user_id) DO UPDATE SET
           user_name=excluded.user_name,updated_at=excluded.updated_at""",
        (int(group_id), int(league_id), int(user_id), user_name,
         config.TI_STARTING_POINTS, int(now)),
    )


def _queue_notification(group_id, dedupe_key, payload, now):
    c.execute(
        """INSERT OR IGNORE INTO ti_notifications
           (dedupe_key,group_id,payload,status,created_at) VALUES (?,?,?,'pending',?)""",
        (dedupe_key, int(group_id), payload, int(now)),
    )


def _cancel_series_bets(league_id, node_group_id, node_id, reason, now):
    rows = c.execute(
        """SELECT id,group_id,user_id,user_name,stake FROM ti_bets
           WHERE league_id=? AND node_group_id=? AND node_id=?
             AND status='open' ORDER BY id""",
        (int(league_id), int(node_group_id), int(node_id)),
    ).fetchall()
    cancelled = defaultdict(list)
    for bet_id, group_id, user_id, user_name, stake in rows:
        c.execute(
            """UPDATE ti_bets SET status='cancelled',payout=?,score_delta=0,
               cancel_reason=?,updated_at=?,settled_at=? WHERE id=? AND status='open'""",
            (int(stake), reason, int(now), int(now), int(bet_id)),
        )
        if not c.rowcount:
            continue
        c.execute(
            """UPDATE ti_scores SET score=score+?,returned=returned+?,updated_at=?
               WHERE group_id=? AND league_id=? AND user_id=?""",
            (int(stake), int(stake), int(now), int(group_id), int(league_id), int(user_id)),
        )
        cancelled[int(group_id)].append({
            'user_id': int(user_id), 'user_name': user_name, 'stake': int(stake),
        })
    return cancelled


def _cancel_market(series, reason, message, now):
    """Atomically void a market, refund every open bet and queue summaries."""
    cancelled = _cancel_series_bets(
        series['league_id'], series['node_group_id'], series['node_id'], reason, now
    )
    c.execute(
        """UPDATE ti_series SET status='cancelled',updated_at=?
           WHERE league_id=? AND node_group_id=? AND node_id=?
             AND status<>'settled'""",
        (int(now), int(series['league_id']), int(series['node_group_id']),
         int(series['node_id'])),
    )
    for group_id, bets in cancelled.items():
        refund = sum(item['stake'] for item in bets)
        _queue_notification(
            group_id,
            'ti-cancel:{}:{}:{}:{}:{}'.format(
                series['league_id'], series['node_group_id'], series['node_id'],
                group_id, reason,
            ),
            '🏆 TI竞猜｜#{} {}，{}笔下注已退回{}点。'.format(
                series['node_id'], message, len(bets), refund
            ),
            now,
        )
    return sum(len(bets) for bets in cancelled.values())


def _series_title(row):
    return '#{} {} vs {}'.format(row['node_id'], row['team_1_name'], row['team_2_name'])


def _settle_series(series, now):
    league_id = int(series['league_id'])
    node_group_id = int(series['node_group_id'])
    node_id = int(series['node_id'])
    winner_team_id = int(series['winner_team_id'])
    if not winner_team_id or int(series['result_confirmations']) < 2:
        # Valve sometimes publishes is_completed before the per-map winners.
        # Keep the market locked and retry on the next refresh instead of guessing.
        return 0

    bets = c.execute(
        """SELECT id,group_id,user_id,user_name,selected_team_id,stake,odds
           FROM ti_bets WHERE league_id=? AND node_group_id=? AND node_id=?
             AND status='open' ORDER BY id""",
        (league_id, node_group_id, node_id),
    ).fetchall()
    summaries = defaultdict(list)
    for bet_id, group_id, user_id, user_name, selected_team_id, stake, odds in bets:
        correct = int(selected_team_id) == winner_team_id
        payout = int(round(int(stake) * float(odds))) if correct else 0
        delta = payout - int(stake)
        c.execute(
            """UPDATE ti_bets SET status='settled',payout=?,score_delta=?,
               cancel_reason=NULL,updated_at=?,settled_at=? WHERE id=? AND status='open'""",
            (payout, delta, int(now), int(now), int(bet_id)),
        )
        if not c.rowcount:
            continue
        c.execute(
            """UPDATE ti_scores SET score=score+?,wins=wins+?,losses=losses+?,
               returned=returned+?,updated_at=?
               WHERE group_id=? AND league_id=? AND user_id=?""",
            (payout, 1 if correct else 0, 0 if correct else 1, payout, int(now),
             int(group_id), league_id, int(user_id)),
        )
        score = c.execute(
            """SELECT score FROM ti_scores
               WHERE group_id=? AND league_id=? AND user_id=?""",
            (int(group_id), league_id, int(user_id)),
        ).fetchone()[0]
        summaries[int(group_id)].append({
            'user_name': user_name, 'correct': correct, 'delta': delta, 'score': int(score),
        })

    winner_name = (
        series['team_1_name'] if winner_team_id == int(series['team_1_id'])
        else series['team_2_name']
    )
    for group_id, items in summaries.items():
        lines = [
            '🏆 TI竞猜结算｜{}'.format(_series_title(series)),
            '{} {}:{} {}｜胜者：{}'.format(
                series['team_1_name'], series['team_1_wins'],
                series['team_2_wins'], series['team_2_name'], winner_name,
            ),
        ]
        for item in items[:10]:
            lines.append('{} {} {:+d}（{}分）'.format(
                '✅' if item['correct'] else '❌', item['user_name'],
                item['delta'], item['score'],
            ))
        if len(items) > 10:
            lines.append('另有 {} 人已结算。'.format(len(items) - 10))
        _queue_notification(
            group_id, 'ti-settle:{}:{}:{}:{}'.format(
                league_id, node_group_id, node_id, group_id
            ),
            '\n'.join(lines), now,
        )
    c.execute(
        """UPDATE ti_series SET status='settled',updated_at=?
           WHERE league_id=? AND node_group_id=? AND node_id=?
             AND status<>'settled'""",
        (int(now), league_id, node_group_id, node_id),
    )
    return len(bets)


def _upsert_series(node, now):
    old = get_ti_series(node['node_id'], node['league_id'], node['node_group_id'])
    old_teams = (
        (int(old['team_1_id']), int(old['team_2_id'])) if old else None
    )
    new_teams = (int(node['team_1_id']), int(node['team_2_id']))
    old_status = old['status'] if old else None
    old_locked_at = old['locked_at'] if old else None

    # Settled accounting is immutable. Upstream corrections are surfaced in
    # logs instead of silently desynchronizing the displayed result and points.
    if old_status == 'settled':
        incoming_winner = int(node['winner_team_id'])
        if (incoming_winner and int(old['winner_team_id'])
                and incoming_winner != int(old['winner_team_id'])):
            logger.critical('TI 已结算结果发生变化：league=%s group=%s node=%s',
                            node['league_id'], node['node_group_id'], node['node_id'])
        if old_teams and all(new_teams) and set(old_teams) != set(new_teams):
            logger.critical('TI 已结算盘口对阵发生变化：league=%s group=%s node=%s',
                            node['league_id'], node['node_group_id'], node['node_id'])
        return

    # A partial Valve response must never erase a known matchup. It temporarily
    # closes an open market; once a complete response returns, normal change
    # detection can safely refund or reopen it.
    if old:
        for side in (1, 2):
            if (int(node['team_{}_id'.format(side)])
                    == int(old['team_{}_id'.format(side)])):
                for suffix in ('name', 'tag', 'abbr'):
                    key = 'team_{}_{}'.format(side, suffix)
                    if not node[key]:
                        node[key] = old[key]
    source_complete = (
        all(new_teams) and bool(node['team_1_name']) and bool(node['team_2_name'])
        and int(node['scheduled_time']) > 0
    )
    old_complete = bool(
        old and all(old_teams) and old['team_1_name'] and old['team_2_name']
        and int(old['scheduled_time']) > 0
    )
    if old_complete and not source_complete:
        completed_seen_at = old['completed_seen_at']
        if node['is_completed'] and not completed_seen_at:
            completed_seen_at = int(now)
        if (node['is_completed'] and completed_seen_at
                and int(now) - int(completed_seen_at) >= config.TI_RESULT_GRACE_SECONDS):
            _cancel_market(old, 'incomplete_result', '官方结果迟迟不完整，盘口作废', now)
            return
        if old_status in ('locked', 'review', 'cancelled'):
            status = old_status
        elif node['has_started'] or node['is_completed'] or node['actual_time']:
            status = 'locked'
        else:
            status = 'pending'
        c.execute(
            """UPDATE ti_series SET status=?,completed_seen_at=?,updated_at=?
               WHERE league_id=? AND node_group_id=? AND node_id=?""",
            (status, completed_seen_at, int(now), int(node['league_id']),
             int(node['node_group_id']), int(node['node_id'])),
        )
        return
    teams_changed = (
        old_teams and all(old_teams) and all(new_teams)
        and set(old_teams) != set(new_teams)
    )
    if teams_changed and old_status in ('locked', 'review'):
        _cancel_market(old, 'matchup_changed_after_lock',
                       '封盘后官方对阵发生调整，盘口作废', now)
        return
    if teams_changed:
        cancelled = _cancel_series_bets(
            node['league_id'], node['node_group_id'], node['node_id'],
            'matchup_changed', now
        )
        for group_id, bets in cancelled.items():
            refund = sum(item['stake'] for item in bets)
            _queue_notification(
                group_id,
                'ti-change:{}:{}:{}:{}:{}'.format(
                    node['league_id'], node['node_group_id'], node['node_id'],
                    group_id, int(now)
                ),
                '🏆 TI竞猜｜#{} 对阵发生调整，{}笔下注已退回{}点。'.format(
                    node['node_id'], len(bets), refund
                ), now,
            )
    bettable = source_complete
    lock_due = (
        bool(node['has_started']) or bool(node['actual_time'])
        or (bettable and int(now) >= int(node['scheduled_time']) - config.TI_BET_CLOSE_SECONDS)
    )
    if node.get('result_conflict') and old:
        _cancel_market(old, 'conflicting_result', '官方赛果存在冲突，盘口作废', now)
        return
    if node.get('result_conflict'):
        status = 'cancelled'
    elif old_status in ('locked', 'review'):
        status = 'locked'
    elif old_status == 'cancelled':
        status = old_status
    elif node['is_completed']:
        status = 'locked'
    elif lock_due:
        status = 'locked'
    elif bettable:
        status = 'open'
    else:
        status = 'pending'
    locked_at = old_locked_at
    if status == 'locked' and not locked_at:
        locked_at = int(now)
    completed_seen_at = old['completed_seen_at'] if old else None
    if node['is_completed'] and not completed_seen_at:
        completed_seen_at = int(now)
    result_signature = ''
    result_confirmations = 0
    if node['winner_team_id']:
        result_signature = '{}:{}:{}'.format(
            node['winner_team_id'], node['team_1_wins'], node['team_2_wins']
        )
        if old and old['result_signature'] == result_signature:
            result_confirmations = min(2, int(old['result_confirmations']) + 1)
        else:
            result_confirmations = 1
    elif (node['is_completed'] and completed_seen_at and old
          and int(now) - int(completed_seen_at) >= config.TI_RESULT_GRACE_SECONDS):
        _cancel_market(old, 'unresolved_result', '官方赛果超时未确认，盘口作废', now)
        return
    values = (
        int(node['league_id']), int(node['node_id']), int(node['node_group_id']),
        node['group_name'], node['node_name'], int(node['scheduled_time']),
        int(node['actual_time']), int(node['series_id']), int(node['team_1_id']),
        node['team_1_name'], node['team_1_tag'], node['team_1_abbr'],
        int(node['team_2_id']), node['team_2_name'], node['team_2_tag'],
        node['team_2_abbr'], int(node['team_1_wins']), int(node['team_2_wins']),
        int(node['has_started']), int(node['is_completed']),
        int(node['winner_team_id']), status, locked_at, result_signature,
        result_confirmations, completed_seen_at, int(now),
    )
    c.execute(
        """INSERT INTO ti_series
           (league_id,node_id,node_group_id,group_name,node_name,scheduled_time,
            actual_time,series_id,team_1_id,team_1_name,team_1_tag,team_1_abbr,
            team_2_id,team_2_name,team_2_tag,team_2_abbr,team_1_wins,
            team_2_wins,has_started,is_completed,winner_team_id,status,locked_at,
            result_signature,result_confirmations,completed_seen_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(league_id,node_group_id,node_id) DO UPDATE SET
           node_group_id=excluded.node_group_id,group_name=excluded.group_name,
           node_name=excluded.node_name,scheduled_time=excluded.scheduled_time,
           actual_time=excluded.actual_time,series_id=excluded.series_id,
           team_1_id=excluded.team_1_id,team_1_name=excluded.team_1_name,
           team_1_tag=excluded.team_1_tag,team_1_abbr=excluded.team_1_abbr,
           team_2_id=excluded.team_2_id,team_2_name=excluded.team_2_name,
           team_2_tag=excluded.team_2_tag,team_2_abbr=excluded.team_2_abbr,
           team_1_wins=excluded.team_1_wins,team_2_wins=excluded.team_2_wins,
           has_started=excluded.has_started,is_completed=excluded.is_completed,
            winner_team_id=excluded.winner_team_id,status=excluded.status,
            locked_at=excluded.locked_at,result_signature=excluded.result_signature,
            result_confirmations=excluded.result_confirmations,
            completed_seen_at=excluded.completed_seen_at,updated_at=excluded.updated_at""",
        values,
    )


def _cancel_abandoned_markets(seen_keys, now):
    """Release stakes when Valve drops a market or never publishes a finish."""
    rows = c.execute(
        """SELECT league_id,node_id,node_group_id,group_name,node_name,scheduled_time,
                  actual_time,series_id,team_1_id,team_1_name,team_1_tag,team_1_abbr,
                  team_2_id,team_2_name,team_2_tag,team_2_abbr,team_1_wins,
                  team_2_wins,has_started,is_completed,winner_team_id,status,
                  locked_at,result_signature,result_confirmations,completed_seen_at,
                  updated_at
           FROM ti_series WHERE league_id=? AND status IN ('open','locked','review')""",
        (int(config.TI_LEAGUE_ID),),
    ).fetchall()
    cancelled = 0
    for row in rows:
        series = _dict_series(row)
        key = (
            int(series['league_id']), int(series['node_group_id']),
            int(series['node_id']),
        )
        vanished = key not in seen_keys and now - int(series['updated_at']) >= 3600
        overdue = (
            int(series['scheduled_time']) > 0
            and now - int(series['scheduled_time']) >= config.TI_MARKET_MAX_AGE
        )
        if vanished or overdue:
            reason = 'source_missing' if vanished else 'market_timeout'
            message = (
                '官方赛程已移除该场，盘口作废' if vanished
                else '比赛长期未公布有效结果，盘口作废'
            )
            cancelled += _cancel_market(series, reason, message, now)
    return cancelled


def refresh_ti_event(force=False, now=None):
    """Refresh Valve's official TI bracket and settle newly completed series."""
    global _next_refresh_at
    if not config.TI_EVENT_ENABLED:
        return {'enabled': False, 'series': 0, 'settled_bets': 0}
    monotonic_now = time.monotonic()
    if not force and monotonic_now < _next_refresh_at:
        return {'enabled': True, 'skipped': True, 'series': 0, 'settled_bets': 0}
    _next_refresh_at = monotonic_now + config.TI_REFRESH_INTERVAL
    try:
        response = requests.get(
            config.TI_LEAGUE_DATA_URL,
            params={'league_id': config.TI_LEAGUE_ID, 'delay_seconds': 0},
            timeout=config.REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        nodes = parse_league_data(data)
    except (requests.RequestException, ValueError, TIEventError) as exc:
        raise TIEventError('刷新 TI 官方赛程失败：{}'.format(exc)) from exc
    if int(data['info']['league_id']) != config.TI_LEAGUE_ID:
        raise TIEventError('TI 联赛编号不匹配')
    now = int(time.time()) if now is None else int(now)
    settled_bets = 0
    with conn:
        for node in nodes:
            _upsert_series(node, now)
        _cancel_abandoned_markets({
            (int(node['league_id']), int(node['node_group_id']), int(node['node_id']))
            for node in nodes
        }, now)
        for node in nodes:
            if node['is_completed']:
                stored = get_ti_series(
                    node['node_id'], node['league_id'], node['node_group_id']
                )
                if stored and stored['status'] == 'locked':
                    settled_bets += _settle_series(stored, now)
    logger.info('TI 赛程刷新完成：%s 个系列，结算 %s 笔', len(nodes), settled_bets)
    return {'enabled': True, 'series': len(nodes), 'settled_bets': settled_bets}


_SERIES_KEYS = (
    'league_id', 'node_id', 'node_group_id', 'group_name', 'node_name',
    'scheduled_time', 'actual_time', 'series_id',
    'team_1_id', 'team_1_name', 'team_1_tag', 'team_1_abbr',
    'team_2_id', 'team_2_name', 'team_2_tag', 'team_2_abbr',
    'team_1_wins', 'team_2_wins', 'has_started', 'is_completed',
    'winner_team_id', 'status', 'locked_at', 'result_signature',
    'result_confirmations', 'completed_seen_at', 'updated_at',
)


def _dict_series(row):
    return dict(zip(_SERIES_KEYS, row)) if row else None


def get_ti_series(node_id, league_id=None, node_group_id=None):
    row = c.execute(
        """SELECT league_id,node_id,node_group_id,group_name,node_name,scheduled_time,
                  actual_time,series_id,team_1_id,team_1_name,team_1_tag,team_1_abbr,
                   team_2_id,team_2_name,team_2_tag,team_2_abbr,team_1_wins,
                   team_2_wins,has_started,is_completed,winner_team_id,status,
                   locked_at,result_signature,result_confirmations,completed_seen_at,
                   updated_at
           FROM ti_series WHERE league_id=? AND node_id=?
             AND (? IS NULL OR node_group_id=?)
           ORDER BY scheduled_time DESC LIMIT 1""",
        (int(league_id or config.TI_LEAGUE_ID), int(node_id),
         int(node_group_id) if node_group_id is not None else None,
         int(node_group_id) if node_group_id is not None else None),
    ).fetchone()
    return _dict_series(row)


def get_ti_schedule(limit=10, now=None, league_id=None):
    now = int(time.time()) if now is None else int(now)
    rows = c.execute(
        """SELECT league_id,node_id,node_group_id,group_name,node_name,scheduled_time,
                  actual_time,series_id,team_1_id,team_1_name,team_1_tag,team_1_abbr,
                   team_2_id,team_2_name,team_2_tag,team_2_abbr,team_1_wins,
                   team_2_wins,has_started,is_completed,winner_team_id,status,
                   locked_at,result_signature,result_confirmations,completed_seen_at,
                   updated_at
           FROM ti_series WHERE league_id=? AND team_1_id<>0 AND team_2_id<>0
             AND is_completed=0 AND scheduled_time>=?
           ORDER BY scheduled_time,node_id LIMIT ?""",
        (int(league_id or config.TI_LEAGUE_ID), now - 6 * 3600, int(limit)),
    ).fetchall()
    return [_dict_series(row) for row in rows]


def _normalize_team(value):
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]+', '', str(value).casefold())


def resolve_ti_team(series, value):
    normalized = _normalize_team(value)
    choices = []
    for side in (1, 2):
        aliases = {
            str(side), str(series['team_{}_id'.format(side)]),
            series['team_{}_name'.format(side)], series['team_{}_tag'.format(side)],
            series['team_{}_abbr'.format(side)],
        }
        if normalized and normalized in {_normalize_team(alias) for alias in aliases if alias}:
            choices.append({
                'id': int(series['team_{}_id'.format(side)]),
                'name': series['team_{}_name'.format(side)],
            })
    return choices[0] if len(choices) == 1 else None


def place_ti_bet(group_id, user_id, user_name, node_id, selected_team_id,
                 selected_team_name, stake, now=None):
    now = int(time.time()) if now is None else int(now)
    stake = int(stake)
    if not 1 <= stake <= config.TI_MAX_STAKE:
        raise ValueError('TI下注点数必须在 1 到 {} 之间'.format(config.TI_MAX_STAKE))
    group_id = int(group_id)
    user_id = int(user_id)
    league_id = int(config.TI_LEAGUE_ID)
    with conn:
        series = get_ti_series(node_id, league_id)
        if not series:
            raise ValueError('没有找到 TI 对局 #{}'.format(node_id))
        if int(selected_team_id) not in (int(series['team_1_id']), int(series['team_2_id'])):
            raise ValueError('所选队伍不在这场对阵中')
        if now - int(series['updated_at']) > config.TI_DATA_MAX_AGE:
            raise ValueError('TI 官方赛程数据已过期，请稍后重试')
        close_at = int(series['scheduled_time']) - config.TI_BET_CLOSE_SECONDS
        if (series['status'] != 'open' or series['is_completed']
                or series['has_started'] or series['actual_time']
                or not series['scheduled_time'] or now >= close_at):
            raise ValueError('该场已封盘（开赛前 {} 分钟停止下注）'.format(
                config.TI_BET_CLOSE_SECONDS // 60
            ))
        _score_row(group_id, league_id, user_id, user_name, now)
        old = c.execute(
            """SELECT id,stake FROM ti_bets WHERE group_id=? AND league_id=?
               AND node_group_id=? AND node_id=? AND user_id=? AND status='open'""",
            (group_id, league_id, int(series['node_group_id']), int(node_id), user_id),
        ).fetchone()
        refundable = int(old[1]) if old else 0
        balance = c.execute(
            """SELECT score FROM ti_scores
               WHERE group_id=? AND league_id=? AND user_id=?""",
            (group_id, league_id, user_id),
        ).fetchone()[0] + refundable
        if balance < stake:
            raise ValueError('TI积分不足：当前可用 {} 点'.format(balance))
        if old:
            c.execute(
                """UPDATE ti_bets SET user_name=?,selected_team_id=?,selected_team_name=?,
                   stake=?,odds=?,updated_at=? WHERE id=?""",
                (user_name, int(selected_team_id), selected_team_name, stake,
                 config.TI_BET_ODDS, now, int(old[0])),
            )
            bet_id, changed = int(old[0]), True
        else:
            c.execute(
                """INSERT INTO ti_bets
                   (group_id,league_id,node_group_id,node_id,user_id,user_name,selected_team_id,
                    selected_team_name,stake,odds,status,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,'open',?,?)""",
                (group_id, league_id, int(series['node_group_id']), int(node_id), user_id, user_name,
                 int(selected_team_id), selected_team_name, stake,
                 config.TI_BET_ODDS, now, now),
            )
            bet_id, changed = int(c.lastrowid), False
        c.execute(
            """UPDATE ti_scores SET score=?,wagered=wagered+?,returned=returned+?,
               updated_at=? WHERE group_id=? AND league_id=? AND user_id=?""",
            (balance - stake, stake, refundable, now, group_id, league_id, user_id),
        )
    return {
        'id': bet_id, 'changed': changed, 'balance': balance - stake,
        'odds': config.TI_BET_ODDS,
    }


def cancel_ti_market(node_id, now=None, league_id=None):
    """Administrator safety valve for an upstream result that cannot settle."""
    now = int(time.time()) if now is None else int(now)
    with conn:
        series = get_ti_series(node_id, league_id or config.TI_LEAGUE_ID)
        if not series:
            raise ValueError('没有找到 TI 对局 #{}'.format(node_id))
        if series['status'] == 'settled':
            raise ValueError('该场已经结算，不能直接作废')
        if series['status'] == 'cancelled':
            return 0
        return _cancel_market(
            series, 'admin_cancel', '管理员已作废盘口', now
        )


def get_open_ti_bets(group_id, user_id, league_id=None):
    rows = c.execute(
        """SELECT b.node_id,b.selected_team_name,b.stake,b.odds,s.scheduled_time,
                  s.team_1_name,s.team_2_name
           FROM ti_bets b JOIN ti_series s
             ON s.league_id=b.league_id AND s.node_group_id=b.node_group_id
            AND s.node_id=b.node_id
           WHERE b.group_id=? AND b.league_id=? AND b.user_id=? AND b.status='open'
           ORDER BY s.scheduled_time,b.node_id""",
        (int(group_id), int(league_id or config.TI_LEAGUE_ID), int(user_id)),
    ).fetchall()
    keys = ('node_id', 'selected_team_name', 'stake', 'odds', 'scheduled_time',
            'team_1_name', 'team_2_name')
    return [dict(zip(keys, row)) for row in rows]


def get_ti_score(group_id, user_id, league_id=None):
    row = c.execute(
        """SELECT user_name,score,wins,losses,wagered,returned FROM ti_scores
           WHERE group_id=? AND league_id=? AND user_id=?""",
        (int(group_id), int(league_id or config.TI_LEAGUE_ID), int(user_id)),
    ).fetchone()
    if not row:
        return {
            'user_name': str(user_id), 'score': config.TI_STARTING_POINTS,
            'wins': 0, 'losses': 0, 'wagered': 0, 'returned': 0,
        }
    return dict(zip(('user_name', 'score', 'wins', 'losses', 'wagered', 'returned'), row))


def get_ti_leaderboard(group_id, limit=10, league_id=None):
    rows = c.execute(
        """SELECT user_id,user_name,score,wins,losses,wagered,returned FROM ti_scores
           WHERE group_id=? AND league_id=?
           ORDER BY score DESC,wins DESC,updated_at ASC LIMIT ?""",
        (int(group_id), int(league_id or config.TI_LEAGUE_ID), int(limit)),
    ).fetchall()
    keys = ('user_id', 'user_name', 'score', 'wins', 'losses', 'wagered', 'returned')
    return [dict(zip(keys, row)) for row in rows]


def deliver_ti_notifications(send_func, limit=10, now=None):
    now = int(time.time()) if now is None else int(now)
    rows = c.execute(
        """SELECT id,group_id,payload,attempts FROM ti_notifications
           WHERE status='pending' AND next_attempt_at<=? ORDER BY id LIMIT ?""",
        (now, int(limit)),
    ).fetchall()
    delivered = 0
    for notification_id, group_id, payload, attempts in rows:
        try:
            send_func(payload, group_id=int(group_id))
        except Exception as exc:
            attempts = int(attempts) + 1
            delay = min(1800, 30 * (2 ** min(attempts - 1, 5)))
            with conn:
                c.execute(
                    """UPDATE ti_notifications SET attempts=?,next_attempt_at=?,last_error=?
                       WHERE id=? AND status='pending'""",
                    (attempts, now + delay, str(exc)[:500], int(notification_id)),
                )
            logger.warning('TI 结算通知发送失败，%s 秒后重试: %s', delay, exc)
            continue
        with conn:
            c.execute(
                """UPDATE ti_notifications SET status='sent',sent_at=?,last_error=NULL
                   WHERE id=? AND status='pending'""",
                (now, int(notification_id)),
            )
        delivered += 1
    return delivered
