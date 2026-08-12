#!/usr/bin/env python3
"""Backfill recent public match summaries without sending QQ messages."""
import os
import sys
import time

with open('/etc/dota2-bot.env', encoding='utf-8') as env_file:
    for line in env_file:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ.setdefault(key, value.strip("'\""))
sys.path.insert(0, '/opt/dota2-bot')

import requests
import config
from DBOper import get_enabled_players, save_match_stats


def request_matches(account_id):
    url = '{}/players/{}/recentMatches'.format(config.OPENDOTA_API_URL, account_id)
    for attempt in range(5):
        response = requests.get(url, timeout=config.REQUEST_TIMEOUT)
        if response.status_code != 429:
            response.raise_for_status()
            return response.json()
        time.sleep(10 * (attempt + 1))
    response.raise_for_status()


saved = 0
for player in get_enabled_players():
    try:
        matches = request_matches(player['short_steamID'])
    except Exception as exc:
        print('skip {}: {}'.format(player['nickname'], exc))
        continue
    for match in matches if isinstance(matches, list) else []:
        team = 1 if int(match.get('player_slot', 255)) < 128 else 2
        radiant_win = bool(match.get('radiant_win'))
        won = radiant_win == (team == 1)
        team_kills = int(match.get('radiant_score' if team == 1 else 'dire_score', 0) or 0)
        kills = int(match.get('kills', 0) or 0)
        assists = int(match.get('assists', 0) or 0)
        participation = 100 * (kills + assists) / max(1, team_kills)
        save_match_stats(match['match_id'], config.QQ_GROUP_ID, match.get('start_time', 0), [{
            'account_id': player['short_steamID'], 'nickname': player['nickname'],
            'won': won, 'team': team, 'hero_id': match.get('hero_id', 0),
            'kills': kills, 'deaths': match.get('deaths', 0), 'assists': assists,
            'gpm': match.get('gold_per_min', 0), 'xpm': match.get('xp_per_min', 0),
            'last_hits': match.get('last_hits', 0), 'damage': match.get('hero_damage', 0),
            'damage_share': 0, 'participation': participation,
        }])
        saved += 1
    print('backfilled {} ({})'.format(player['nickname'], len(matches)))
    time.sleep(1)
print('saved_rows={}'.format(saved))
