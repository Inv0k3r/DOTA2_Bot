#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import argparse
import json

import requests

import config
import DOTA2
import message_sender
from common import steam_id_convert_32_to_64
from DBOper import get_outbox_counts, get_player_count
from player import Player


def command_status(_args):
    headers = {}
    if config.NAPCAT_ACCESS_TOKEN:
        headers['Authorization'] = 'Bearer {}'.format(config.NAPCAT_ACCESS_TOKEN)
    response = requests.get(
        config.NAPCAT_HTTP_URL + '/get_login_info',
        headers=headers,
        timeout=config.REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    napcat = response.json()
    print(json.dumps({
        'configured_players': len(config.PLAYER_LIST),
        'database_players': get_player_count(),
        'outbox': get_outbox_counts(),
        'napcat': napcat.get('data'),
    }, ensure_ascii=False, indent=2))


def command_players(_args):
    for index, (nickname, account_id) in enumerate(config.PLAYER_LIST, 1):
        print('{:02d}\t{}\t{}'.format(index, nickname, account_id))


def command_test_message(args):
    result = message_sender.message(args.text)
    print(json.dumps(result, ensure_ascii=False))


def command_report(args):
    match_id = args.match_id or DOTA2.get_last_match_id_by_short_steamID(args.account_id)
    tracked = Player(
        nickname=args.nickname,
        short_steamID=args.account_id,
        long_steamID=steam_id_convert_32_to_64(args.account_id),
        last_DOTA2_match_ID=match_id,
    )
    report = DOTA2.generate_match_message(match_id, [tracked])
    print(report)
    if args.send:
        result = message_sender.message(report)
        print('message_id={}'.format((result or {}).get('message_id')))


def build_parser():
    parser = argparse.ArgumentParser(description='DOTA2 Bot 管理工具')
    commands = parser.add_subparsers(dest='command', required=True)

    status = commands.add_parser('status', help='检查数据库与 NapCat 状态')
    status.set_defaults(handler=command_status)

    players = commands.add_parser('players', help='列出当前监控玩家')
    players.set_defaults(handler=command_players)

    test_message = commands.add_parser('test-message', help='发送测试群消息')
    test_message.add_argument('text', nargs='?', default='DOTA2 BOT 管理命令测试成功')
    test_message.set_defaults(handler=command_test_message)

    report = commands.add_parser('report', help='生成或发送单场战报')
    report.add_argument('account_id', type=int)
    report.add_argument('nickname')
    report.add_argument('--match-id', type=int)
    report.add_argument('--send', action='store_true')
    report.set_defaults(handler=command_report)
    return parser


def main():
    args = build_parser().parse_args()
    args.handler(args)


if __name__ == '__main__':
    main()
