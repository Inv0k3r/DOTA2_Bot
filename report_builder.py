#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Deterministic, compact DOTA 2 group report formatting."""
import time

import config
from comment_rules import choose_custom_comment
from game_features import display_name, persist_and_summarize
from DOTA2_dicts import GAME_MODE, HEROES_LIST_CHINESE, LOBBY


def _team(slot):
    return 1 if int(slot or 0) < 128 else 2


def _hero_name(hero_id, current_name):
    names = HEROES_LIST_CHINESE.get(hero_id)
    return names[0] if names else current_name(hero_id)


def _pick(options, seed):
    return options[int(seed) % len(options)]


def _comment(stats, won, seed=0):
    kills, deaths, assists = stats['kills'], stats['deaths'], stats['assists']
    kda, participation = stats['kda'], stats['participation']
    damage_share, death_share, gpm = stats['damage_share'], stats['death_share'], stats['gpm']
    damage, last_hits = stats['damage'], stats['last_hits']
    if deaths == 0 and kills + assists >= 8:
        return _pick([
            '零死下班，对面五个人连你的买活钱都没资格看。',
            '全身而退，把对面遛得像五个刚装游戏的。',
            '一条命打完整局，对面想杀你只能去录像里做梦。',
        ], seed)
    if kills >= 15 and kda >= 5:
        return _pick([
            '这不是打比赛，是拿对面五个人刷今日任务。',
            '杀得对面户口本都快翻页了，纯纯单方面屠宰。',
            '对面泉水门口建议给你立个收费站。',
        ], seed)
    if won and kda >= 8 and damage_share >= 25:
        return _pick([
            '又能杀又死不掉，四个队友负责点开始游戏就行。',
            '这局不是你在带队，是你拖着四个行李箱冲线。',
            '对面处理不了你，队友也理解不了你，纯降维打击。',
        ], seed)
    if not won and (damage_share >= 35 or (kda >= 5 and participation >= 60)):
        return _pick([
            '一个人把活全干了，剩下四个像来现场参观的。',
            '这都能输，建议查查四个队友是不是对面请的演员。',
            '你在拼命抬棺，四个队友轮流往棺材里躺。',
        ], seed)
    if participation >= 75:
        return _pick([
            '哪里打架哪里就有你，闻着人头味就冲过来了。',
            '团战出勤率拉满，队友放个屁你都得过去接应。',
            '全地图到处擦屁股，这局保姆费记得找队友结一下。',
        ], seed)
    if damage_share >= 40:
        return _pick([
            '全队输出全压你身上，另外四个键盘像是没插电。',
            '一个人打了快半队伤害，队友输出得像在给对面按摩。',
            '伤害柱子独自撑天，剩下四根只能算地板装饰。',
        ], seed)
    if deaths >= 12 and kda < 1:
        return _pick([
            '死得像移动提款机，对面见你一次领一次低保。',
            '这死亡数不是战绩，是泉水到战场的通勤打卡。',
            '复活倒计时看得比游戏画面都久，纯正人形经验包。',
        ], seed)
    if deaths >= 10 or death_share >= 40:
        return _pick([
            '承伤全靠脸接，命硬不硬不知道，送得是真勤快。',
            '对面技能一个没空，你的脸一个没落，全接住了。',
            '死亡份额遥遥领先，团灭里有你一半股份。',
        ], seed)
    if gpm >= 700 and damage_share < 18:
        return _pick([
            '钱全刷自己卡里，打团却像个没充值的体验账号。',
            '经济吃得像土匪，输出打得像慈善家。',
            '这么肥只打这点伤害，装备建议原价退回商店。',
        ], seed)
    if kills == 0 and assists < 8:
        return _pick([
            '杀人键是被扣了？混完整局连个人头味都没闻到。',
            '零杀低助攻，十个人开游戏就你像没加载进去。',
            '人头没有，助攻也不熟，存在感薄得像张厕纸。',
        ], seed)
    if participation < 30 and kills + assists < 8:
        return _pick([
            '队友打团你逛街，这参战率属于失踪人口统计。',
            '全场最大的贡献，是让服务器知道你还在线。',
            '打架永远慢半拍，不知道的还以为延迟两万毫秒。',
        ], seed)
    if damage < 6000 and last_hits >= 80:
        return _pick([
            '补刀补得挺认真，打英雄时怎么突然开始尊重生命了？',
            '兵没少吃，伤害没打出，资源进了胃里没进战斗力。',
            '对小兵重拳出击，对英雄唯唯诺诺。',
        ], seed)
    if won and kda < 2 and participation < 40:
        return _pick([
            '躺得角度相当专业，四个队友抬你过终点都没闪到腰。',
            '这胜利跟你关系不大，但加分的时候你倒是一个没少拿。',
            '人在局里，作用在局外，胜利全靠队友自力更生。',
        ], seed)
    if won:
        return _pick([
            '赢是赢了，数据普通得像系统随机生成的路人甲。',
            '顺利混到胜利，至少没给队友制造太大麻烦。',
            '表现不算亮眼，好在对面更像一群饭桶。',
        ], seed)
    return _pick([
        '输得没什么悬念，数据也找不到替你嘴硬的角度。',
        '这局打得像把脑子落在选英雄界面了。',
        '没赢也没尽力，属于赛后连借口都很难编的水平。',
    ], seed)


def build_match_report(match_id, tracked_players, match, current_hero_name, current_constant_name):
    raw_players = match.get('players') or []
    by_account = {int(p['account_id']): p for p in raw_players if p.get('account_id') is not None}
    missing = [p.nickname for p in tracked_players if p.short_steamID not in by_account]
    if missing:
        raise ValueError('比赛详情中找不到监控玩家：{}'.format('、'.join(missing)))

    totals = {1: {'kills': 0, 'deaths': 0, 'damage': 0}, 2: {'kills': 0, 'deaths': 0, 'damage': 0}}
    for raw in raw_players:
        side = _team(raw.get('player_slot', 255))
        for source, target in (('kills', 'kills'), ('deaths', 'deaths'), ('hero_damage', 'damage')):
            totals[side][target] += int(raw.get(source, 0) or 0)

    radiant_win = bool(match.get('radiant_win'))
    mode_id = int(match.get('game_mode', 0) or 0)
    lobby_id = int(match.get('lobby_type', -1) if match.get('lobby_type') is not None else -1)
    mode = GAME_MODE.get(mode_id) or current_constant_name('game_mode', mode_id)
    lobby = LOBBY.get(lobby_id) or current_constant_name('lobby_type', lobby_id)
    duration = int(match.get('duration', 0) or 0)
    start_timestamp = int(match.get('start_time', 0) or 0)
    started = time.strftime('%Y-%m-%d %H:%M', time.localtime(start_timestamp))
    winner = '天辉' if radiant_win else '夜魇'
    lines = [
        '{} {}胜利｜{} / {}'.format('🟢' if radiant_win else '🔴', winner, mode, lobby),
        '⏱ {}｜{}分{:02d}秒'.format(started, duration // 60, duration % 60),
    ]

    teams = {_team(by_account[p.short_steamID].get('player_slot', 255)) for p in tracked_players}
    if len(tracked_players) >= 2:
        names = '、'.join(p.nickname for p in tracked_players)
        party_ids = [by_account[p.short_steamID].get('party_id') for p in tracked_players]
        same_party = (
            len(teams) == 1 and party_ids[0] not in (None, 0)
            and all(party_id == party_ids[0] for party_id in party_ids)
        )
        label = (
            '组队开黑' if same_party else
            '同队同局' if len(teams) == 1 else
            '同局撞车'
        )
        lines.append('{} 发现{}人{}：{}'.format(
            '👥' if len(teams) == 1 else '⚔️', len(tracked_players), label, names
        ))

    ordered = sorted(tracked_players, key=lambda p: (_team(by_account[p.short_steamID].get('player_slot', 255)), p.nickname))
    last_side = None
    persisted_rows = []
    for tracked in ordered:
        raw = by_account[tracked.short_steamID]
        side = _team(raw.get('player_slot', 255))
        if len(teams) > 1 and side != last_side:
            lines.append('—— {} ——'.format('天辉' if side == 1 else '夜魇'))
            last_side = side
        kills, deaths, assists = (int(raw.get(k, 0) or 0) for k in ('kills', 'deaths', 'assists'))
        damage = int(raw.get('hero_damage', 0) or 0)
        gpm, xpm = int(raw.get('gold_per_min', 0) or 0), int(raw.get('xp_per_min', 0) or 0)
        last_hits, hero_id = int(raw.get('last_hits', 0) or 0), int(raw.get('hero_id', 0) or 0)
        kda = (kills + assists) / max(1, deaths)
        team_totals = totals[side]
        damage_share = 100 * damage / max(1, team_totals['damage'])
        participation = 100 * (kills + assists) / max(1, team_totals['kills'])
        death_share = 100 * deaths / max(1, team_totals['deaths'])
        won = radiant_win == (side == 1)

        tracked.dota2_kill, tracked.dota2_death, tracked.dota2_assist = kills, deaths, assists
        tracked.dota2_team, tracked.hero, tracked.last_hit = side, hero_id, last_hits
        tracked.damage, tracked.gpm, tracked.xpm, tracked.kda = damage, gpm, xpm, kda
        stats = dict(kills=kills, deaths=deaths, assists=assists, kda=kda, gpm=gpm,
                     xpm=xpm, damage=damage, last_hits=last_hits, won=won,
                     damage_share=damage_share, participation=participation,
                     death_share=death_share)
        comment = choose_custom_comment(
            config.QQ_GROUP_ID, match_id, tracked.short_steamID, stats
        ) or _comment(stats, won, match_id + tracked.short_steamID)
        persisted_rows.append({
            'account_id': tracked.short_steamID, 'nickname': tracked.nickname,
            'won': won, 'team': side, 'hero_id': hero_id, 'kills': kills,
            'deaths': deaths, 'assists': assists, 'gpm': gpm, 'xpm': xpm,
            'last_hits': last_hits, 'damage': damage, 'damage_share': damage_share,
            'participation': participation,
        })
        lines.extend([
            '',
            '{} {}｜{}'.format('✅' if won else '❌',
                              display_name(tracked.short_steamID, tracked.nickname, match_id),
                              _hero_name(hero_id, current_hero_name)),
            'K/D/A {}/{}/{}｜GPM/XPM {}/{}'.format(kills, deaths, assists, gpm, xpm),
            '补刀 {}｜伤害 {:,}（{:.1f}%）｜参战 {:.1f}%'.format(last_hits, damage, damage_share, participation),
            '💬 {}'.format(comment),
        ])
    participant_account_ids = {
        int(raw['account_id']) for raw in raw_players
        if raw.get('account_id') is not None
    }
    lines.extend(persist_and_summarize(
        match_id, start_timestamp, persisted_rows,
        participant_account_ids=participant_account_ids,
    ))
    if config.ENABLE_URL:
        lines.extend(['', '详情：https://zh.dotabuff.com/matches/{}'.format(match_id)])
    return '\n'.join(lines)
