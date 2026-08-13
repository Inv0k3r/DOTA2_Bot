#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Shared social/gamification features driven by persisted match statistics."""
import hashlib
import time

import config
from DBOper import (
    get_combo_name, get_combo_record, get_match_stats, get_player_alias,
    get_player_streak, get_rivalry, get_today_stats, save_match_stats,
    reward_bound_players, settle_prediction_bets,
)


def _stable_roll(*parts):
    raw = ':'.join(str(part) for part in parts).encode('utf-8')
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], 'big') % 100 + 1


def display_name(account_id, nickname, match_id):
    alias = get_player_alias(config.QQ_GROUP_ID, account_id)
    if alias and _stable_roll('alias', match_id, account_id) <= alias['probability']:
        return '{}「{}」'.format(nickname, alias['alias'])
    return nickname


def persist_and_summarize(match_id, start_time, rows, participant_account_ids=None):
    save_match_stats(match_id, config.QQ_GROUP_ID, start_time, rows)
    lines = []
    risk_events = []
    commissions = []
    settled = settle_prediction_bets(
        config.QQ_GROUP_ID, match_id, start_time, rows,
        participant_account_ids=participant_account_ids,
        risk_events=risk_events, commissions=commissions,
    )
    rewards = reward_bound_players(config.QQ_GROUP_ID, match_id, rows)
    if risk_events:
        lines.extend(['', '🛡️ 竞猜风控'])
        for event in risk_events:
            if event['reason'] == 'loss_streak':
                lines.append(
                    '• {} 已{}连败，暂停竞猜；{}笔未结算下注退回{}点。'.format(
                        event['target_nickname'], event['loss_streak'],
                        event['bet_count'], event['refund'],
                    )
                )
            elif event['reason'] == 'match_participant':
                lines.append(
                    '• 同局参与者不能押 {}；{}笔下注作废并退回{}点。'.format(
                        event['target_nickname'], event['bet_count'], event['refund'],
                    )
                )
    if settled:
        correct = sum(1 for item in settled if item['correct'])
        lines.extend(['', '🎲 竞猜结算｜{} 人参与，{} 人猜中'.format(len(settled), correct)])
        for item in settled[:8]:
            sign = '+' if item['delta'] >= 0 else ''
            lines.append('{} {} {}{}（{}分）'.format(
                '✅' if item['correct'] else '❌', item['user_name'], sign,
                item['delta'], item['score']))
        if len(settled) > 8:
            lines.append('另有 {} 人已结算。'.format(len(settled) - 8))
    if commissions:
        lines.extend(['', '💸 反向提成'])
        lines.extend(
            '• {} 顶住群友看衰，收走押输池 {} 点的提成：+{} 点'.format(
                item['target_nickname'], item['opposition_stake'], item['amount']
            )
            for item in commissions
        )
    if rewards:
        lines.extend(['', '🎮 完赛奖励'])
        lines.extend(
            '• {} {} +{} 点'.format(
                item['user_name'], '获胜' if item['won'] else '落败', item['amount']
            )
            for item in rewards
        )
    if len(rows) >= 2:
        lines.extend(_awards(rows))
        lines.extend(_combo_and_rivalry(rows))
    streak_lines = []
    for row in rows:
        streak = get_player_streak(row['account_id'])
        if streak >= 3:
            streak_lines.append('🔥 {} 已经 {} 连胜，匹配系统还没制裁成功。'.format(row['nickname'], streak))
        elif streak <= -3:
            streak_lines.append('💀 {} 遭遇 {} 连败，系统的个人意见很明确。'.format(row['nickname'], -streak))
    if streak_lines:
        lines.extend(['', *streak_lines])
    return lines


def _awards(rows):
    awarded = set()
    awards = []
    mvp = max(rows, key=lambda r: ((r['kills'] + r['assists']) / max(1, r['deaths']), r['damage']))
    awards.append('🏆 MVP：{}（{}/{}/{}）'.format(mvp['nickname'], mvp['kills'], mvp['deaths'], mvp['assists']))
    awarded.add(mvp['account_id'])
    feeder = max(rows, key=lambda r: r['deaths'])
    if feeder['deaths'] >= 8 and feeder['account_id'] not in awarded:
        awards.append('🏧 移动提款机：{}（死了 {} 次）'.format(feeder['nickname'], feeder['deaths']))
        awarded.add(feeder['account_id'])
    invisible = min(rows, key=lambda r: r['participation'])
    if invisible['participation'] < 40 and invisible['account_id'] not in awarded:
        awards.append('👻 隐身冠军：{}（参战 {:.0f}%）'.format(invisible['nickname'], invisible['participation']))
        awarded.add(invisible['account_id'])
    charity = max(rows, key=lambda r: r['gpm'])
    if charity['gpm'] >= 650 and charity['damage_share'] < 20 and charity['account_id'] not in awarded:
        awards.append('💰 经济慈善家：{}（GPM {}，伤害占比 {:.0f}%）'.format(
            charity['nickname'], charity['gpm'], charity['damage_share']))
    return ['', '🎖 本局奖项', *awards]


def _combo_and_rivalry(rows):
    lines = []
    teams = {}
    for row in rows:
        teams.setdefault(row['team'], []).append(row)
    for members in teams.values():
        if len(members) < 2:
            continue
        ids = [row['account_id'] for row in members]
        combo_name = get_combo_name(config.QQ_GROUP_ID, ids)
        wins, total = get_combo_record(ids)
        if not combo_name and total >= 3:
            auto_names = ('泉水旅游团', '夜魇施工队', '天梯拆迁办', '分数慈善会', '买活研究所')
            combo_name = auto_names[_stable_roll('combo', *ids) % len(auto_names)]
        if combo_name:
            lines.append('👥 “{}”再次集合｜历史 {} 胜 {} 负'.format(combo_name, wins, total - wins))
    if len(teams) > 1:
        first_team, second_team = list(teams.values())[:2]
        rivalries = []
        for first in first_team:
            for second in second_team:
                record = get_rivalry([first['account_id'], second['account_id']])
                if record:
                    total = record['first_wins'] + record['second_wins']
                    rivalries.append((total, first, second, record))
        if rivalries:
            _, first, second, record = max(rivalries, key=lambda item: item[0])
            first_wins = record['first_wins'] if record['first'] == first['account_id'] else record['second_wins']
            second_wins = record['second_wins'] if record['first'] == first['account_id'] else record['first_wins']
            lines.append('⚔️ 宿敌账本：{} {}:{} {}'.format(first['nickname'], first_wins, second_wins, second['nickname']))
    return lines


def roast_player(match_id, nickname=None, salt=0):
    rows = get_match_stats(match_id)
    if not rows:
        return '这条战报没有可用的结构化数据。'
    row = None
    if nickname:
        normalized = nickname.strip().casefold()
        row = next((item for item in rows if item['nickname'].casefold() == normalized), None)
        if not row:
            return '这局没找到玩家：{}'.format(nickname)
    else:
        row = max(rows, key=lambda item: (item['deaths'], -item['participation']))
    options = []
    if row['deaths'] >= 10:
        options.append('{}死了{}次，复活倒计时才是这局真正的主界面。'.format(row['nickname'], row['deaths']))
    if row['participation'] < 40:
        options.append('{}参战率只有{:.0f}%，队友打团时你在地图上办理失踪证明。'.format(row['nickname'], row['participation']))
    if row['gpm'] >= 650 and row['damage_share'] < 20:
        options.append('{}拿着{} GPM只打了{:.0f}%伤害，经济全存定期了。'.format(row['nickname'], row['gpm'], row['damage_share']))
    if row['damage_share'] >= 35 and not row['won']:
        options.append('{}打了全队{:.0f}%伤害，四个队友负责把优势送回去。'.format(row['nickname'], row['damage_share']))
    if not options:
        options = [
            '{}这局普通得像系统填充的假人，骂都找不到重点。'.format(row['nickname']),
            '{}的数据主打一个来过，但没完全来。'.format(row['nickname']),
            '{}成功打完了比赛，这大概是唯一能确定的贡献。'.format(row['nickname']),
        ]
    return options[_stable_roll('roast', match_id, row['account_id'], salt) % len(options)]


def today_leaderboard():
    now = time.localtime()
    since = int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, -1)))
    rows = get_today_stats(config.QQ_GROUP_ID, since)
    if not rows:
        return '今天还没有记录到监控玩家的比赛。'
    for row in rows:
        row['losses'] = row['games'] - row['wins']
        row['kda'] = (row['kills'] + row['assists']) / max(1, row['deaths'])
    red = max(rows, key=lambda row: (row['wins'], row['kda']))
    black = max(rows, key=lambda row: (row['losses'], row['deaths']))
    return ('📊 今日红黑榜\n'
            '🔴 红榜：{}｜{}胜{}负｜KDA {:.1f}\n'
            '⚫ 黑榜：{}｜{}胜{}负｜共死{}次').format(
                red['nickname'], red['wins'], red['losses'], red['kda'],
                black['nickname'], black['wins'], black['losses'], black['deaths'])


def losing_streaks(players):
    rows = []
    for player in players:
        streak = get_player_streak(player.short_steamID)
        if streak <= -2:
            rows.append((-streak, player.nickname))
    if not rows:
        return '目前没人达到 2 连败，群友暂时都还有救。'
    rows.sort(reverse=True)
    return '💀 当前连败榜\n' + '\n'.join(
        '{}. {}｜{} 连败'.format(index, nickname, streak)
        for index, (streak, nickname) in enumerate(rows, 1)
    )
