#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Handle the small, administrator-only command surface for group management."""
import logging
import re
import shlex
import time
from urllib.parse import urlparse

import config
import DOTA2
import common
from DBOper import (
    add_comment_rule,
    bind_prediction_player,
    claim_prediction_daily_checkin,
    create_prediction_loan,
    delete_comment_rule,
    delete_player_alias,
    delete_player_data,
    get_comment_rules,
    get_enabled_players,
    get_match_id_by_message_id,
    get_open_prediction_bets,
    get_prediction_leaderboard,
    get_prediction_odds,
    get_prediction_loan_status,
    get_prediction_score,
    place_prediction_bet,
    repay_prediction_loan,
    save_comment_vote,
    set_combo_name,
    set_player_alias,
    set_comment_rule_enabled,
    upsert_player,
    unbind_prediction_player,
)
from comment_rules import format_condition, format_rule, parse_add_rule
from message_sender import message as send
from player import PLAYER_LIST, Player
from game_features import losing_streaks, roast_player, today_leaderboard

logger = logging.getLogger(__name__)
STEAM_ID64_BASE = 76561197960265728


def _plain_text(event):
    message = event.get('message', '')
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, list):
        return ''.join(
            str(segment.get('data', {}).get('text', ''))
            for segment in message
            if segment.get('type') == 'text'
        ).strip()
    return ''


def _was_at_bot(event):
    bot_id = str(event.get('self_id', ''))
    message = event.get('message', '')
    if isinstance(message, list):
        return any(
            segment.get('type') == 'at'
            and str(segment.get('data', {}).get('qq', '')) == bot_id
            for segment in message
        )
    return bool(bot_id and re.search(r'\[CQ:at,qq={}\]'.format(re.escape(bot_id)), str(message)))


def _reply_message_id(event):
    message = event.get('message', '')
    if isinstance(message, list):
        for segment in message:
            if segment.get('type') == 'reply':
                value = segment.get('data', {}).get('id')
                return int(value) if value is not None else None
    match = re.search(r'\[CQ:reply,id=(-?\d+)\]', str(message))
    return int(match.group(1)) if match else None


def _is_admin(event):
    user_id = int(event.get('user_id', 0) or 0)
    role = (event.get('sender') or {}).get('role')
    return user_id in config.ADMIN_QQ_IDS or role in ('owner', 'admin')


def _resolve_identifier(value):
    value = value.strip().rstrip('/')
    parsed = urlparse(value)
    if parsed.netloc:
        parts = [part for part in parsed.path.split('/') if part]
        if len(parts) >= 2 and parts[-2] == 'profiles':
            value = parts[-1]
        elif len(parts) >= 2 and parts[-2] == 'id':
            result = DOTA2._request_json(
                'https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/',
                params={'key': config.API_KEY, 'vanityurl': parts[-1]},
                provider='Steam vanity URL',
            ).get('response', {})
            if result.get('success') != 1 or not result.get('steamid'):
                raise ValueError('这个 Steam 个性域名无法解析')
            value = result['steamid']

    if not re.fullmatch(r'\d{1,20}', value):
        raise ValueError('请提供 Steam 个人主页、SteamID64 或 Account ID')
    numeric = int(value)
    if numeric >= STEAM_ID64_BASE:
        return numeric - STEAM_ID64_BASE, numeric
    if numeric <= 0 or numeric > 0xFFFFFFFF:
        raise ValueError('Steam ID 数值不合法')
    return numeric, numeric + STEAM_ID64_BASE


def _find_player(value):
    normalized = value.strip().casefold()
    for tracked in PLAYER_LIST:
        if normalized in {
            tracked.nickname.casefold(),
            str(tracked.short_steamID),
            str(tracked.long_steamID),
        }:
            return tracked
    return None


def _add_player(arguments):
    parts = arguments.split()
    if len(parts) < 2:
        return '用法：添加监控 <Steam链接或ID> <群内昵称>'

    identifier_index = next(
        (index for index, part in enumerate(parts)
         if part.isdigit() or 'steamcommunity.com/' in part.lower()),
        None,
    )
    if identifier_index is None:
        return '没有找到 Steam 链接或 ID。\n用法：添加监控 <Steam链接或ID> <群内昵称>'
    identifier = parts.pop(identifier_index)
    nickname = ' '.join(parts).strip()
    if not nickname:
        return '请同时提供群内昵称'

    try:
        account_id, steam_id64 = _resolve_identifier(identifier)
        existing = _find_player(str(account_id))
        if existing:
            existing.nickname = nickname
            upsert_player(account_id, steam_id64, nickname, existing.last_DOTA2_match_ID)
            return '已更新监控：{}（{}）'.format(nickname, account_id)

        latest_match = DOTA2.get_last_match_id_by_short_steamID(account_id)
        cursor = upsert_player(account_id, steam_id64, nickname, latest_match)
        PLAYER_LIST.append(Player(nickname, account_id, steam_id64, cursor))
        return '已添加监控：{}（{}）\n从下一场新比赛开始推送。'.format(nickname, account_id)
    except (ValueError, DOTA2.DOTA2HTTPError) as exc:
        return '添加失败：{}'.format(exc)


def _remove_player(arguments):
    if not arguments.strip():
        return '用法：删除监控 <昵称或Steam ID>'
    tracked = _find_player(arguments)
    if not tracked:
        return '没有找到这个监控玩家：{}'.format(arguments.strip())
    result = delete_player_data(tracked.short_steamID)
    PLAYER_LIST.remove(tracked)
    common.forget_player(tracked.short_steamID)
    suffix = ''
    if result['refunded_bets']:
        suffix = '\n已撤销 {} 笔未结算竞猜并退还 {} 点。'.format(
            result['refunded_bets'], result['refunded_score']
        )
    return '已删除监控及全部相关信息：{}{}'.format(tracked.nickname, suffix)


def _list_players():
    rows = get_enabled_players()
    if not rows:
        return '当前没有监控玩家。'
    lines = ['当前监控 {} 人：'.format(len(rows))]
    lines.extend(
        '{:02d}. {}（{}）'.format(index, row['nickname'], row['short_steamID'])
        for index, row in enumerate(rows, 1)
    )
    return '\n'.join(lines)


def _add_comment(arguments, event):
    try:
        conditions, probability, text = parse_add_rule(arguments)
        rule_id = add_comment_rule(
            config.QQ_GROUP_ID, conditions, probability, text, event.get('user_id', 0)
        )
        return '锐评 #{} 已添加：\n{}\n{}%｜{}'.format(
            rule_id, ' '.join(format_condition(item) for item in conditions),
            probability, text
        )
    except ValueError as exc:
        return '添加失败：{}'.format(exc)


def _list_comments():
    rules = get_comment_rules(config.QQ_GROUP_ID)
    if not rules:
        return '还没有自定义锐评。\n示例：@bot 加锐评 死亡>=10 60% 文案'
    lines = ['自定义锐评（{}条）：'.format(len(rules))]
    lines.extend(format_rule(rule) for rule in rules[:30])
    if len(rules) > 30:
        lines.append('只显示最近 30 条。')
    return '\n'.join(lines)


def _change_comment(command, arguments):
    try:
        rule_id = int(arguments.strip())
    except ValueError:
        return '格式：{} <编号>'.format(command)
    if command == '开锐评':
        changed = set_comment_rule_enabled(config.QQ_GROUP_ID, rule_id, True)
        action = '启用'
    elif command == '停锐评':
        changed = set_comment_rule_enabled(config.QQ_GROUP_ID, rule_id, False)
        action = '停用'
    else:
        changed = delete_comment_rule(config.QQ_GROUP_ID, rule_id)
        action = '删除'
    return '已{}锐评 #{}'.format(action, rule_id) if changed else '没找到锐评 #{}'.format(rule_id)


def _set_alias(arguments, event):
    try:
        parts = shlex.split(arguments)
    except ValueError as exc:
        return '外号格式有误：{}'.format(exc)
    if len(parts) < 2:
        return '格式：加外号 <玩家> <外号> [概率%]'
    probability = 35
    if parts[-1].endswith('%') and parts[-1][:-1].isdigit():
        probability = int(parts.pop()[:-1])
    if not 1 <= probability <= 100:
        return '概率必须是 1% 到 100%'
    tracked = _find_player(parts[0])
    if not tracked:
        return '没找到玩家：{}'.format(parts[0])
    alias = ' '.join(parts[1:]).strip()
    if not alias or len(alias) > 20:
        return '外号长度必须是 1 到 20 个字符'
    set_player_alias(config.QQ_GROUP_ID, tracked.short_steamID, alias, probability,
                     event.get('user_id', 0))
    return '已给 {} 设置外号「{}」，{}% 概率出现。'.format(tracked.nickname, alias, probability)


def _delete_alias(arguments):
    tracked = _find_player(arguments)
    if not tracked:
        return '没找到玩家：{}'.format(arguments)
    changed = delete_player_alias(config.QQ_GROUP_ID, tracked.short_steamID)
    return '已删除 {} 的外号。'.format(tracked.nickname) if changed else '{} 还没有外号。'.format(tracked.nickname)


def _set_combo(arguments, event):
    parts = arguments.split(None, 1)
    if len(parts) != 2:
        return '格式：组合名 玩家1+玩家2 <组合名称>'
    player_names = [value.strip() for value in parts[0].split('+') if value.strip()]
    if not 2 <= len(player_names) <= 5:
        return '组合需要 2 到 5 名玩家，用 + 连接'
    players = [_find_player(name) for name in player_names]
    if any(player is None for player in players):
        missing = player_names[players.index(None)]
        return '没找到玩家：{}'.format(missing)
    name = parts[1].strip()
    if not 1 <= len(name) <= 20:
        return '组合名称长度必须是 1 到 20 个字符'
    set_combo_name(config.QQ_GROUP_ID, [player.short_steamID for player in players],
                   name, event.get('user_id', 0))
    return '组合命名成功：{}「{}」'.format('、'.join(player.nickname for player in players), name)


def _sender_name(event):
    sender = event.get('sender') or {}
    return (sender.get('card') or sender.get('nickname') or str(event.get('user_id', 0)))[:40]


def _mentioned_user(event):
    bot_id = str(event.get('self_id', ''))
    message = event.get('message', '')
    if isinstance(message, list):
        for segment in message:
            if segment.get('type') == 'at':
                value = str(segment.get('data', {}).get('qq', ''))
                if value and value != bot_id and value.isdigit():
                    return int(value)
    values = re.findall(r'\[CQ:at,qq=(\d+)\]', str(message))
    return next((int(value) for value in values if value != bot_id), None)


def _place_prediction(arguments, event):
    parts = arguments.rsplit(None, 2)
    if len(parts) != 3 or parts[1] not in ('赢', '输') or not parts[2].isdigit():
        return '格式：竞猜 <玩家> 赢/输 <点数>\n示例：@bot 竞猜 椒吉米 赢 100'
    stake = int(parts[2])
    if not 1 <= stake <= 100000:
        return '下注点数必须在 1 到 100000 之间。'
    tracked = _find_player(parts[0])
    if not tracked:
        return '没找到监控玩家：{}'.format(parts[0])
    currently_in_dota = common.is_player_currently_in_dota(tracked.short_steamID)
    odds = get_prediction_odds(config.QQ_GROUP_ID, tracked.short_steamID)
    locked_odds = odds['win'] if parts[1] == '赢' else odds['lose']
    try:
        result = place_prediction_bet(
            config.QQ_GROUP_ID, event.get('user_id', 0), _sender_name(event),
            tracked.short_steamID, tracked.nickname, parts[1] == '赢', stake,
            locked_odds, int(tracked.last_DOTA2_match_ID),
        )
    except ValueError as exc:
        return '下注失败：{}'.format(exc)
    action = '已改押' if result['changed'] else '下注成功'
    timing_note = (
        '{} 当前正在游戏：本次自动押正在进行这局之后的下一盘。'.format(
            tracked.nickname
        )
        if currently_in_dota else
        '只结算下注时间之后开始的比赛；已经开打的对局不会追认。'
    )
    return ('{}：{} 下一场{} {}点｜赔率 {:.2f}｜潜在返还 {}点｜余额 {}点\n'
            '{}').format(
        action, tracked.nickname, parts[1], stake, locked_odds,
        int(round(stake * locked_odds)), result['balance'], timing_note)


def _my_predictions(event):
    bets = get_open_prediction_bets(config.QQ_GROUP_ID, event.get('user_id', 0))
    if not bets:
        return '你目前没有待结算竞猜。\n格式：@bot 竞猜 <玩家> 赢/输 <点数>'
    lines = ['你的待结算竞猜：']
    lines.extend('• {} 下一场{}｜{}点 × {:.2f}｜潜在返还{}点'.format(
                     item['target_nickname'], '赢' if item['prediction'] else '输',
                     item['stake'], item['odds'], int(round(item['stake'] * item['odds'])))
                 for item in bets)
    return '\n'.join(lines)


def _prediction_score(event):
    score = get_prediction_score(config.QQ_GROUP_ID, event.get('user_id', 0))
    total = score['wins'] + score['losses']
    rate = 100 * score['wins'] / total if total else 0
    net = score['returned'] - score['wagered']
    return ('🎲 {}｜余额 {}点｜{}胜{}负｜命中率 {:.0f}%\n'
            '累计下注 {}｜累计返还 {}｜竞猜净收益 {:+d}\n'
            '签到奖励 {}｜完赛奖励 {}｜反向提成 {}').format(
        score['user_name'], score['score'], score['wins'], score['losses'], rate,
        score['wagered'], score['returned'], net, score.get('checkin_earned', 0),
        score['game_earned'], score.get('commission_earned', 0))


def _daily_checkin(event):
    result = claim_prediction_daily_checkin(
        config.QQ_GROUP_ID, event.get('user_id', 0), _sender_name(event)
    )
    if result['claimed']:
        return '📅 签到成功｜竞猜积分 +{}｜当前余额 {}点'.format(
            result['amount'], result['balance']
        )
    return '📅 今天已经签过到了｜当前余额 {}点，明天再来。'.format(
        result['balance']
    )


def _prediction_board():
    rows = get_prediction_leaderboard(config.QQ_GROUP_ID)
    if not rows:
        return '竞猜榜还是空的，发送 @bot 竞猜 <玩家> 赢/输 <点数> 抢个榜一。'
    lines = ['🎲 竞猜积分榜']
    for index, row in enumerate(rows, 1):
        total = row['wins'] + row['losses']
        rate = 100 * row['wins'] / total if total else 0
        net = row['returned'] - row['wagered']
        lines.append('{}. {}｜{}点｜{}胜{}负｜{:.0f}%｜净收益{:+d}'.format(
            index, row['user_name'], row['score'], row['wins'], row['losses'], rate, net))
    return '\n'.join(lines)


def _prediction_odds(arguments):
    tracked = _find_player(arguments)
    if not tracked:
        return '没找到监控玩家：{}'.format(arguments)
    odds = get_prediction_odds(config.QQ_GROUP_ID, tracked.short_steamID)
    record = '{}胜{}负'.format(odds['wins'], odds['games'] - odds['wins']) if odds['games'] else '暂无历史'
    message = '🎲 {}｜历史 {}｜赢 {:.2f} / 输 {:.2f}'.format(
        tracked.nickname, record, odds['win'], odds['lose'])
    if odds.get('locked'):
        message += '\n🛡️ 已{}连败，竞猜暂时锁定；赢一场后自动恢复。'.format(
            odds['loss_streak']
        )
    return message


def _create_loan(arguments, event):
    if not re.fullmatch(r'\d+', arguments.strip()):
        return '格式：@bot 贷款 <点数>\n额度 {}–{} 点'.format(
            config.PREDICTION_LOAN_MIN, config.PREDICTION_LOAN_MAX
        )
    try:
        result = create_prediction_loan(
            config.QQ_GROUP_ID, event.get('user_id', 0), _sender_name(event),
            int(arguments.strip()),
        )
    except ValueError as exc:
        return '贷款失败：{}'.format(exc)
    due = time.strftime('%m-%d %H:%M', time.localtime(result['due_at']))
    return ('🏦 放款成功｜到账 {} 点｜应还 {} 点（利息 {}）｜{} 前还款\n'
            '当前余额 {} 点；逾期将死亡 3 天。').format(
        result['principal'], result['total_due'], result['interest'], due,
        result['balance'],
    )


def _repay_loan(event):
    try:
        result = repay_prediction_loan(config.QQ_GROUP_ID, event.get('user_id', 0))
    except ValueError as exc:
        return '还款失败：{}'.format(exc)
    return '🏦 还款成功｜已扣 {} 点｜剩余 {} 点'.format(
        result['paid'], result['balance']
    )


def _loan_status(event):
    status = get_prediction_loan_status(config.QQ_GROUP_ID, event.get('user_id', 0))
    if status['death']:
        remaining = max(0, status['death']['death_until'] - status['now'])
        days, remainder = divmod(remaining, 86400)
        hours = remainder // 3600
        remaining_text = '{}天{}小时'.format(days, hours) if days else '{}小时'.format(max(1, hours))
        return '💀 竞猜账号死亡中｜约 {} 后自动复活'.format(remaining_text)
    loan = status['loan']
    if not loan or loan['status'] != 'open':
        return '你目前没有待还贷款。\n格式：@bot 贷款 <点数>'
    due = time.strftime('%m-%d %H:%M', time.localtime(loan['due_at']))
    return '🏦 待还 {} 点｜本金 {} + 利息 {}｜到期 {}'.format(
        loan['total_due'], loan['principal'], loan['interest'], due
    )


def _bind_prediction_player(arguments, event):
    user_id = _mentioned_user(event)
    if user_id is None:
        return '格式：绑定玩家 @群友 <监控玩家>'
    tracked = _find_player(arguments)
    if not tracked:
        return '没找到监控玩家：{}'.format(arguments)
    try:
        refunded = bind_prediction_player(
            config.QQ_GROUP_ID, user_id, str(user_id),
            tracked.short_steamID, tracked.nickname
        )
    except ValueError as exc:
        return '绑定失败：{}'.format(exc)
    message = ('已绑定：QQ {} ↔ {}。每个 QQ 和游戏账号都只能绑定一次；'
               '获胜奖励 {} 点，落败奖励 {} 点。').format(
        user_id, tracked.nickname, config.PREDICTION_GAME_WIN_REWARD,
        config.PREDICTION_GAME_LOSS_REWARD)
    if refunded:
        message += '\n已自动撤销其竞猜自己的未结算下注，并退回 {} 点。'.format(refunded)
    return message


def _unbind_prediction_player(arguments, event):
    mentioned = _mentioned_user(event)
    tracked = _find_player(arguments) if arguments else None
    if mentioned is None and not tracked:
        return '格式：取消绑定 @群友\n或：取消绑定 <监控玩家>'
    link = unbind_prediction_player(
        config.QQ_GROUP_ID,
        user_id=mentioned,
        account_id=tracked.short_steamID if tracked else None,
    )
    if not link:
        return '没有找到对应的竞猜绑定。'
    return '已取消绑定：QQ {} ↔ {}。'.format(link['user_id'], link['nickname'])


def _reply_interaction(text, event):
    reply_id = _reply_message_id(event)
    if reply_id is None:
        return '请回复一条机器人战报再使用这个命令。'
    match_id = get_match_id_by_message_id(reply_id)
    if match_id is None:
        return '找不到这条消息对应的战报，可能是旧版或手动发送的。'
    if text.startswith('鞭尸'):
        nickname = text[len('鞭尸'):].strip() or None
        from DBOper import increment_interaction
        if not increment_interaction(config.QQ_GROUP_ID, match_id, 'roast', 3):
            return '这局已经鞭尸三次了，再打尸体都要报警了。'
        return roast_player(match_id, nickname, salt=3)
    if text == '再骂一句':
        from DBOper import increment_interaction
        if not increment_interaction(config.QQ_GROUP_ID, match_id, 'reroll', 3):
            return '这局已经补刀三次了，给尸体留点尊严。'
        return roast_player(match_id, salt=9)
    votes = {'锐评太轻': 'light', '锐评合适': 'good', '锐评过头': 'heavy'}
    vote = votes[text]
    save_comment_vote(config.QQ_GROUP_ID, match_id, event.get('user_id', 0), vote)
    return {'light': '收到，后续锐评会往更狠的方向调。',
            'good': '收到，这个火候记下了。',
            'heavy': '收到，后续会稍微收着点骂。'}[vote]


def _help_text():
    return (
        'DOTA2 BOT 帮助\n'
        '监控：\n'
        '@bot 添加监控 <Steam链接或ID> <昵称>\n'
        '@bot 删除监控 <昵称或ID>\n'
        '@bot 监控列表\n\n'
        '锐评：\n'
        '@bot 加锐评 <条件> <概率> <文案>\n'
        '@bot 锐评列表\n'
        '@bot 开锐评/停锐评/删锐评 <编号>\n\n'
        '娱乐：\n'
        '@bot 加外号 <玩家> <外号> [概率%]\n'
        '@bot 删外号 <玩家>\n'
        '@bot 组合名 玩家1+玩家2 <名称>\n'
        '@bot 今日红黑榜\n'
        '@bot 谁在连败\n'
        '@bot 竞猜 <玩家> 赢/输 <点数>\n'
        '@bot 赔率 <玩家>\n'
        '@bot 签到（每日 +{} 竞猜积分）\n'
        '@bot 我的竞猜 / 我的积分 / 竞猜榜\n'
        '@bot 贷款 <点数>（{}–{}，24小时利息10%）\n'
        '@bot 还款 / 我的贷款\n'
        '管理员：@bot 绑定玩家 @群友 <监控玩家> / 取消绑定 @群友\n'
        '回复战报并 @bot 鞭尸 [玩家] / 再骂一句 / 锐评太轻\n\n'
        '示例：\n'
        '@bot 加锐评 死亡>=10 60% 泉水通勤大师。\n'
        '@bot 加锐评 胜负=负 伤害占比>=40% 100% 这锅轮不到你。\n\n'
        '字段：击杀 死亡 助攻 KDA GPM XPM 补刀 伤害 '
        '伤害占比 参战率 死亡占比 胜负'
    ).format(config.PREDICTION_DAILY_CHECKIN_REWARD,
             config.PREDICTION_LOAN_MIN, config.PREDICTION_LOAN_MAX)


def handle_event(event):
    """Return True when the event was recognized as a bot command."""
    if event.get('post_type') != 'message' or event.get('message_type') != 'group':
        return False
    if int(event.get('group_id', 0) or 0) != config.QQ_GROUP_ID:
        return False

    text = _plain_text(event).lstrip('/').strip()
    if not text and _was_at_bot(event):
        send('我可以管理监控名单和自定义锐评。\n发送 @bot 帮助 查看全部功能。',
             group_id=config.QQ_GROUP_ID)
        return True

    if text in ('帮助', 'help', '菜单'):
        if not _was_at_bot(event):
            return False
        send(_help_text(), group_id=config.QQ_GROUP_ID)
        return True

    if _was_at_bot(event) and (text.startswith('鞭尸') or text == '再骂一句'
                               or text in ('锐评太轻', '锐评合适', '锐评过头')):
        send(_reply_interaction(text, event), group_id=config.QQ_GROUP_ID)
        return True
    if _was_at_bot(event) and text == '今日红黑榜':
        send(today_leaderboard(), group_id=config.QQ_GROUP_ID)
        return True
    if _was_at_bot(event) and text == '谁在连败':
        send(losing_streaks(PLAYER_LIST), group_id=config.QQ_GROUP_ID)
        return True
    if _was_at_bot(event) and text == '签到':
        send(_daily_checkin(event), group_id=config.QQ_GROUP_ID)
        return True
    if _was_at_bot(event) and (text == '贷款' or text.startswith('贷款 ')):
        send(_create_loan(text[len('贷款'):].strip(), event), group_id=config.QQ_GROUP_ID)
        return True
    if _was_at_bot(event) and text == '还款':
        send(_repay_loan(event), group_id=config.QQ_GROUP_ID)
        return True
    if _was_at_bot(event) and text in ('我的贷款', '贷款状态'):
        send(_loan_status(event), group_id=config.QQ_GROUP_ID)
        return True
    if _was_at_bot(event) and (text == '竞猜' or text.startswith('竞猜 ')):
        send(_place_prediction(text[len('竞猜'):].strip(), event), group_id=config.QQ_GROUP_ID)
        return True
    if _was_at_bot(event) and text == '我的竞猜':
        send(_my_predictions(event), group_id=config.QQ_GROUP_ID)
        return True
    if _was_at_bot(event) and text in ('我的积分', '竞猜积分'):
        send(_prediction_score(event), group_id=config.QQ_GROUP_ID)
        return True
    if _was_at_bot(event) and text in ('竞猜榜', '竞猜排行'):
        send(_prediction_board(), group_id=config.QQ_GROUP_ID)
        return True
    if _was_at_bot(event) and (text == '赔率' or text.startswith('赔率 ')):
        send(_prediction_odds(text[len('赔率'):].strip()), group_id=config.QQ_GROUP_ID)
        return True
    if _was_at_bot(event) and (text == '绑定玩家' or text.startswith('绑定玩家 ')):
        if not _is_admin(event):
            send('只有群主或管理员能绑定玩家。', group_id=config.QQ_GROUP_ID)
            return True
        send(_bind_prediction_player(text[len('绑定玩家'):].strip(), event),
             group_id=config.QQ_GROUP_ID)
        return True
    if _was_at_bot(event) and (text == '取消绑定' or text.startswith('取消绑定 ')):
        if not _is_admin(event):
            send('只有群主或管理员能取消玩家绑定。', group_id=config.QQ_GROUP_ID)
            return True
        send(_unbind_prediction_player(text[len('取消绑定'):].strip(), event),
             group_id=config.QQ_GROUP_ID)
        return True

    social_commands = ('加外号', '删外号', '组合名')
    for prefix in social_commands:
        if text == prefix or text.startswith(prefix + ' '):
            if not _was_at_bot(event):
                return False
            if not _is_admin(event):
                send('只有群主或管理员能修改外号和组合名。', group_id=config.QQ_GROUP_ID)
                return True
            arguments = text[len(prefix):].strip()
            if prefix == '加外号':
                response = _set_alias(arguments, event)
            elif prefix == '删外号':
                response = _delete_alias(arguments)
            else:
                response = _set_combo(arguments, event)
            send(response, group_id=config.QQ_GROUP_ID)
            return True

    comment_prefixes = ('加锐评', '开锐评', '停锐评', '删锐评')
    is_comment_command = text == '锐评列表' or any(
        text == prefix or text.startswith(prefix + ' ') for prefix in comment_prefixes
    )
    if is_comment_command:
        if not _was_at_bot(event):
            return False
        if text == '锐评列表':
            send(_list_comments(), group_id=config.QQ_GROUP_ID)
            return True
        prefix = next(prefix for prefix in comment_prefixes
                      if text == prefix or text.startswith(prefix + ' '))
        if not _is_admin(event):
            send('只有群主或管理员能修改锐评。', group_id=config.QQ_GROUP_ID)
            return True
        arguments = text[len(prefix):].strip()
        response = _add_comment(arguments, event) if prefix == '加锐评' else _change_comment(prefix, arguments)
        send(response, group_id=config.QQ_GROUP_ID)
        return True

    commands = (
        ('添加监控', _add_player),
        ('监控添加', _add_player),
        ('删除监控', _remove_player),
        ('监控删除', _remove_player),
    )
    if text in ('监控列表', '查看监控'):
        if not _is_admin(event):
            return True
        send(_list_players(), group_id=config.QQ_GROUP_ID)
        return True

    for prefix, handler in commands:
        if text == prefix or text.startswith(prefix + ' '):
            if not _is_admin(event):
                logger.warning('QQ %s 尝试执行管理员命令 %s', event.get('user_id'), prefix)
                return True
            response = handler(text[len(prefix):].strip())
            send(response, group_id=config.QQ_GROUP_ID)
            return True
    return False
