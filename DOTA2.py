#!/usr/bin/python
# -*- coding: UTF-8 -*-
import requests
from DOTA2_dicts import *
from player import Player
import random
import time
from typing import Dict, List
from config import (
    API_KEY,
    DEFAULT_NAME_ONLY,
    ENABLE_URL,
    OPENDOTA_API_URL,
    OPENDOTA_RATE_LIMIT_BACKOFF,
    REQUEST_TIMEOUT,
)


# 异常处理
class DOTA2HTTPError(Exception):
    pass


_HERO_NAMES_CACHE = {}
_HERO_NAMES_LOADED = False
_CONSTANTS_CACHE = {}
_opendota_retry_at = 0.0
_opendota_parse_requested = set()


def _request_json(url: str, params=None, provider="API"):
    global _opendota_retry_at
    is_opendota = provider.startswith("OpenDota")
    if is_opendota and time.monotonic() < _opendota_retry_at:
        remaining = max(1, int(_opendota_retry_at - time.monotonic()))
        raise DOTA2HTTPError("OpenDota rate limit cooldown ({}s remaining)".format(remaining))
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        if is_opendota and status_code == 429:
            retry_after = exc.response.headers.get("Retry-After", "")
            try:
                delay = max(float(retry_after), OPENDOTA_RATE_LIMIT_BACKOFF)
            except (TypeError, ValueError):
                delay = OPENDOTA_RATE_LIMIT_BACKOFF
            _opendota_retry_at = time.monotonic() + delay
        raise DOTA2HTTPError(
            "{} returned HTTP {}".format(provider, status_code)
        ) from exc
    except requests.RequestException as exc:
        raise DOTA2HTTPError(
            "{} request failed: {}".format(provider, type(exc).__name__)
        ) from exc
    except ValueError as exc:
        raise DOTA2HTTPError("{} returned invalid JSON".format(provider)) from exc


# 根据slot判断队伍, 返回1为天辉, 2为夜魇
def get_team_by_slot(slot: int) -> int:
    if slot < 128:
        return 1
    else:
        return 2


def get_last_match_id_by_short_steamID(short_steamID: int) -> int:
    match = _request_json(
        'https://api.steampowered.com/IDOTA2Match_570/GetMatchHistory/v001/',
        params={
            'key': API_KEY,
            'account_id': short_steamID,
            'matches_requested': 1,
        },
        provider="Steam match history",
    )
    try:
        match_id = match["result"]["matches"][0]["match_id"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DOTA2HTTPError("Steam match history contains no visible match") from exc
    return match_id


def get_active_dota_account_ids(players: List[Player]) -> List[int]:
    """Return tracked account IDs whose public Steam status currently shows DOTA 2."""
    if not players:
        return []
    summaries = _request_json(
        'https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/',
        params={
            'key': API_KEY,
            'steamids': ','.join(str(player.long_steamID) for player in players),
        },
        provider="Steam player summaries",
    )
    active = []
    for summary in summaries.get('response', {}).get('players', []):
        game_id = str(summary.get('gameid', ''))
        game_name = summary.get('gameextrainfo', '') or ''
        if game_id == '570' or 'dota 2' in game_name.lower():
            active.append(int(summary['steamid']) - 76561197960265728)
    return active


def get_recent_match_ids_by_short_steamID(short_steamID: int, limit: int = 20) -> List[int]:
    """Return recent matches newest first from the keyed Steam history API."""
    result = _request_json(
        'https://api.steampowered.com/IDOTA2Match_570/GetMatchHistory/v001/',
        params={'key': API_KEY, 'account_id': short_steamID, 'matches_requested': limit},
        provider="Steam match history",
    )
    ids = [int(item['match_id']) for item in result.get('result', {}).get('matches', [])]
    if not ids:
        raise DOTA2HTTPError('Steam match history contains no visible match')
    return ids


def _get_match_detail_from_opendota(match_id: int) -> Dict:
    match = _request_json(
        '{}/matches/{}'.format(OPENDOTA_API_URL, match_id),
        provider="OpenDota match details",
    )
    if match.get('match_id') != match_id or not isinstance(match.get('players'), list):
        raise DOTA2HTTPError("OpenDota returned incomplete match details")
    return match


def _get_match_detail_from_steam(match_id: int) -> Dict:
    match = _request_json(
        'https://api.steampowered.com/IDOTA2Match_570/GetMatchDetails/v001/',
        params={'key': API_KEY, 'match_id': match_id},
        provider="Steam match details",
    )
    result = match.get('result')
    if not isinstance(result, dict) or not isinstance(result.get('players'), list):
        raise DOTA2HTTPError("Steam returned incomplete match details")
    return result


def request_opendota_match_parse(match_id: int) -> bool:
    """Submit one OpenDota parse job per match for the lifetime of this process."""
    global _opendota_retry_at
    match_id = int(match_id)
    if match_id in _opendota_parse_requested:
        return False
    if time.monotonic() < _opendota_retry_at:
        raise DOTA2HTTPError("OpenDota rate limit cooldown")
    try:
        response = requests.post(
            '{}/request/{}'.format(OPENDOTA_API_URL, match_id),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get('job'), dict):
            raise DOTA2HTTPError("OpenDota parse request returned invalid response")
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        if status_code == 429:
            _opendota_retry_at = time.monotonic() + OPENDOTA_RATE_LIMIT_BACKOFF
        raise DOTA2HTTPError(
            "OpenDota parse request returned HTTP {}".format(status_code)
        ) from exc
    except requests.RequestException as exc:
        raise DOTA2HTTPError(
            "OpenDota parse request failed: {}".format(type(exc).__name__)
        ) from exc
    except ValueError as exc:
        raise DOTA2HTTPError("OpenDota parse request returned invalid JSON") from exc
    _opendota_parse_requested.add(match_id)
    return True


def get_match_detail_info(match_id: int) -> Dict:
    """Prefer OpenDota for current match details and fall back to Steam."""
    errors = []
    try:
        return _get_match_detail_from_opendota(match_id)
    except DOTA2HTTPError as exc:
        errors.append(str(exc))
        if "OpenDota match details returned HTTP 404" in str(exc):
            try:
                submitted = request_opendota_match_parse(match_id)
                errors.append(
                    "OpenDota parse requested" if submitted
                    else "OpenDota parse pending"
                )
            except DOTA2HTTPError as parse_exc:
                errors.append(str(parse_exc))
    try:
        return _get_match_detail_from_steam(match_id)
    except DOTA2HTTPError as exc:
        errors.append(str(exc))
    raise DOTA2HTTPError("; ".join(errors))


def _get_current_hero_name(hero_id: int) -> str:
    global _HERO_NAMES_LOADED
    if not _HERO_NAMES_LOADED:
        try:
            heroes = _request_json(
                '{}/constants/heroes'.format(OPENDOTA_API_URL),
                provider="OpenDota hero constants",
            )
            _HERO_NAMES_CACHE.update({
                int(item['id']): item.get('localized_name', item.get('name', '未知英雄'))
                for item in heroes.values()
                if isinstance(item, dict) and item.get('id') is not None
            })
        except DOTA2HTTPError:
            pass
        _HERO_NAMES_LOADED = True
    return _HERO_NAMES_CACHE.get(hero_id, '未知英雄')


def _get_current_constant_name(constant_type: str, value: int) -> str:
    if constant_type not in _CONSTANTS_CACHE:
        try:
            constants = _request_json(
                '{}/constants/{}'.format(OPENDOTA_API_URL, constant_type),
                provider="OpenDota {} constants".format(constant_type),
            )
        except DOTA2HTTPError:
            constants = {}
        _CONSTANTS_CACHE[constant_type] = constants

    constants = _CONSTANTS_CACHE[constant_type]
    item = constants.get(str(value), {}) if isinstance(constants, dict) else {}
    if not isinstance(item, dict):
        return '未知'
    name = item.get('localized_name') or item.get('name')
    if not name:
        return '未知'
    for prefix in ('game_mode_', 'lobby_type_'):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name.replace('_', ' ')


# 接收某局比赛的玩家列表, 生成比赛战报
# 参数为玩家对象列表和比赛ID
def _legacy_generate_match_message(match_id: int, player_list: List[Player]):
    match = get_match_detail_info(match_id=match_id)

    start_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(match['start_time']))
    duration = match['duration']

    # 比赛模式
    mode_id = match.get("game_mode", 0)
    mode = GAME_MODE.get(mode_id) or _get_current_constant_name('game_mode', mode_id)

    lobby_id = match.get('lobby_type', -1)
    lobby = LOBBY.get(lobby_id) or _get_current_constant_name('lobby_type', lobby_id)

    player_num = len(player_list)
    nicknames = '，'.join([player_list[i].nickname for i in range(-player_num, -1)])
    if nicknames:
        nicknames += '和'
    nicknames += player_list[-1].nickname

    # 更新玩家对象的比赛信息
    found_players = set()
    for i in player_list:
        for j in match['players']:
            if i.short_steamID == j.get('account_id'):
                i.dota2_kill = j.get('kills', 0) or 0
                i.dota2_death = j.get('deaths', 0) or 0
                i.dota2_assist = j.get('assists', 0) or 0
                i.kda = ((1. * i.dota2_kill + i.dota2_assist) / i.dota2_death) \
                    if i.dota2_death != 0 else (1. * i.dota2_kill + i.dota2_assist)

                i.dota2_team = get_team_by_slot(j.get('player_slot', 255))
                i.hero = j.get('hero_id', 0) or 0
                i.last_hit = j.get('last_hits', 0) or 0
                i.damage = j.get('hero_damage', 0) or 0
                i.gpm = j.get('gold_per_min', 0) or 0
                i.xpm = j.get('xp_per_min', 0) or 0
                found_players.add(i.short_steamID)
                break

    missing_players = [
        i.nickname for i in player_list if i.short_steamID not in found_players
    ]
    if missing_players:
        raise DOTA2HTTPError(
            "Match details do not contain tracked players: {}".format(', '.join(missing_players))
        )

    team = player_list[0].dota2_team
    win = match['radiant_win'] == (team == 1)

    if mode_id in (15, 19):  # 各种活动模式仅简单通报
        return '{}玩了一把[{}/{}]，开始于{}，持续{}分{}秒，看起来好像是{}了。'.format(
            nicknames, mode, lobby, start_time, duration // 60, duration % 60, "赢" if win else "输"
        )
    # 队伍信息
    team_damage = 0
    team_kills = 0
    team_deaths = 0
    for i in match['players']:
        if get_team_by_slot(i.get('player_slot', 255)) == team:
            team_damage += i.get('hero_damage', 0) or 0
            team_kills += i.get('kills', 0) or 0
            team_deaths += i.get('deaths', 0) or 0

    top_kda = 0
    for i in player_list:
        if i.kda > top_kda:
            top_kda = i.kda

    if (win and top_kda > 10) or (not win and top_kda > 6):
        postive = True
    elif (win and top_kda < 4) or (not win and top_kda < 1):
        postive = False
    else:
        if random.randint(0, 1) == 0:
            postive = True
        else:
            postive = False

    tosend = []
    if win and postive:
        tosend.append(random.choice(WIN_POSTIVE_PARTY).format(nicknames))
    elif win and not postive:
        tosend.append(random.choice(WIN_NEGATIVE_PARTY).format(nicknames))
    elif not win and postive:
        tosend.append(random.choice(LOSE_POSTIVE_PARTY).format(nicknames))
    else:
        tosend.append(random.choice(LOSE_NEGATIVE_PARTY).format(nicknames))

    tosend.append('开始时间: {}'.format(start_time))
    tosend.append('持续时间: {}分{}秒'.format(duration // 60, duration % 60))
    tosend.append('游戏模式: [{}/{}]'.format(mode, lobby))

    for i in player_list:
        nickname = i.nickname
        if i.hero in HEROES_LIST_CHINESE:
            if DEFAULT_NAME_ONLY:
                hero = HEROES_LIST_CHINESE[i.hero][0]
            else:
                hero = random.choice(HEROES_LIST_CHINESE[i.hero])
        else:
            hero = _get_current_hero_name(i.hero)
        kda = i.kda
        last_hits = i.last_hit
        damage = i.damage
        kills, deaths, assists = i.dota2_kill, i.dota2_death, i.dota2_assist
        gpm, xpm = i.gpm, i.xpm

        damage_rate = 0 if team_damage == 0 else (100 * (float(damage) / team_damage))
        participation = 0 if team_kills == 0 else (100 * float(kills + assists) / team_kills)
        deaths_rate = 0 if team_deaths == 0 else (100 * float(deaths) / team_deaths)

        tosend.append(
            '{}使用{}, KDA: {:.2f}[{}/{}/{}], GPM/XPM: {}/{}, ' \
            '补刀数: {}, 总伤害: {}({:.2f}%), 参战率: {:.2f}%, 参葬率: {:.2f}%' \
                .format(nickname, hero, kda, kills, deaths, assists, gpm, xpm, last_hits,
                        damage, damage_rate, participation, deaths_rate)
        )

    if ENABLE_URL:
        tosend.append('战绩详情: https://zh.dotabuff.com/matches/{}'.format(match_id))

    return '\n'.join(tosend)


def get_tracked_players_in_match(match: Dict, tracked_players: List[Player]):
    """Return tracked players whose public account ID appears in match details."""
    account_ids = {
        int(raw['account_id']) for raw in (match.get('players') or [])
        if raw.get('account_id') is not None
    }
    return [
        tracked for tracked in tracked_players
        if tracked.short_steamID in account_ids
    ]


def generate_match_message(match_id: int, player_list: List[Player], match=None):
    """Generate one merged report for all tracked players in a match."""
    from report_builder import build_match_report

    match = match or get_match_detail_info(match_id=match_id)
    try:
        return build_match_report(
            match_id, player_list, match,
            _get_current_hero_name, _get_current_constant_name,
        )
    except ValueError as exc:
        raise DOTA2HTTPError(str(exc)) from exc
