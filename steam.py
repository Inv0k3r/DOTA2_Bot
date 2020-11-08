import json
import requests
from datetime import datetime
from config import API_KEY, PLAYER_LIST
from DBOper import get_playing_game, update_playing_game

def gaming_status_watcher():
    replys = []
    status_changed = False
    sids = ','.join(str(p[1] + 76561197960265728) for p in PLAYER_LIST)
    r = requests.get(f'http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={API_KEY}&steamids={sids}')
    j = json.loads(r.content)
    for p in j['response']['players']:
        sid = int(p['steamid'])
        pname = p['personaname']
        cur_game = p.get('gameextrainfo', '')
        pre_game, last_update = get_playing_game(sid)

        # 游戏状态更新
        if cur_game != pre_game:
            status_changed = True
            now = int(datetime.now().timestamp())
            minutes = (now - last_update) // 60
            if cur_game:
                if pre_game:
                    replys.append(f'{pname}玩了{minutes}分钟{pre_game}后，玩起了{cur_game}')
                else:
                    replys.append(f'{pname}启动了{cur_game}')
            else:
                replys.append(f'{pname}退出了{pre_game}，本次游戏时长{minutes}分钟')
            update_playing_game(sid, cur_game, now)

    return '\n'.join(replys) if replys else None