from datetime import datetime

import requests

import time

from config import API_KEY, REQUEST_TIMEOUT
from DBOper import get_playing_game, update_playing_game
from DBOper import get_combo_name, get_combo_record
from player import PLAYER_LIST

_last_prediction_key = None
_last_prediction_at = 0


def gaming_status_watcher():
    global _last_prediction_key, _last_prediction_at
    replys = []
    if not PLAYER_LIST:
        return None
    sids = ','.join(str(p.long_steamID) for p in PLAYER_LIST)
    r = requests.get(
        'https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/',
        params={'key': API_KEY, 'steamids': sids},
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    j = r.json()
    active_dota = []
    nickname_by_id = {p.short_steamID: p.nickname for p in PLAYER_LIST}
    for p in j['response']['players']:
        sid = int(p['steamid'])
        short_sid = sid - 76561197960265728
        pname = p['personaname']
        cur_game = p.get('gameextrainfo', '')
        game_id = str(p.get('gameid', ''))
        pre_game, _last_update = get_playing_game(short_sid)

        # 游戏状态更新
        if cur_game != pre_game:
            now = int(datetime.now().timestamp())
            update_playing_game(short_sid, cur_game, now)

        if game_id == '570' or 'dota 2' in cur_game.lower():
            active_dota.append(short_sid)

    active_dota.sort()
    prediction_key = tuple(active_dota)
    now = int(time.time())
    if len(active_dota) >= 2 and (
            prediction_key != _last_prediction_key or now - _last_prediction_at >= 4 * 3600):
        _last_prediction_key = prediction_key
        _last_prediction_at = now
        wins, total = get_combo_record(active_dota)
        combo_name = get_combo_name(__import__('config').QQ_GROUP_ID, active_dota)
        names = '、'.join(nickname_by_id.get(account_id, str(account_id)) for account_id in active_dota)
        title = '“{}”'.format(combo_name) if combo_name else names
        if total:
            rate = 100 * wins / total
            verdict = ('这把看起来能赢，除非有人突然想做慈善。' if rate >= 60 else
                       '五五开，意思是有五成概率被对面当人机。' if rate >= 40 else
                       '历史数据不太乐观，对面已经提前开始加分了。')
            replys.append('🔮 开黑预测\n{} 已进入 DOTA2\n历史 {} 胜 {} 负（{:.0f}%）\n{}'.format(
                title, wins, total - wins, rate, verdict))
        else:
            replys.append('🔮 开黑预测\n{} 已进入 DOTA2\n首次记录这个组合，祝他们别把友谊打没。'.format(title))
    elif len(active_dota) < 2:
        _last_prediction_key = None

    return '\n'.join(replys) if replys else None
