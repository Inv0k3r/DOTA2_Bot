#!/usr/bin/python
# -*- coding: UTF-8 -*-
import logging
import random
import time

import config
from player import PLAYER_LIST, Player
from DBOper import (
    enforce_overdue_prediction_loans, get_enabled_players, is_player_stored, insert_info,
    refresh_all_prediction_markets,
)
from common import refresh_match_poll_priorities, steam_id_convert_32_to_64, update_and_send_message_DOTA2
from event_receiver import process_pending_events, start_event_server
from message_sender import message as send
import DOTA2

logger = logging.getLogger(__name__)


def init():
    # 环境变量只负责导入新增玩家，之后由数据库保存启用状态。
    for i in config.PLAYER_LIST:
        nickname = i[0]
        short_steamID = i[1]
        logger.info("读取玩家 %s，Account ID: %s", nickname, short_steamID)
        long_steamID = steam_id_convert_32_to_64(short_steamID)

        # 如果数据库中没有这个人的信息, 则进行数据库插入
        if not is_player_stored(short_steamID):
            try:
                last_DOTA2_match_ID = DOTA2.get_last_match_id_by_short_steamID(short_steamID)
            except DOTA2.DOTA2HTTPError as exc:
                logger.warning("初始化 %s 的比赛状态失败: %s", nickname, exc)
                last_DOTA2_match_ID = -1
            insert_info(short_steamID, long_steamID, nickname, last_DOTA2_match_ID)
    PLAYER_LIST.clear()
    for row in get_enabled_players():
        PLAYER_LIST.append(Player(**row))
    refreshed_markets = refresh_all_prediction_markets()
    if refreshed_markets:
        logger.info("启动时已按实时奖池刷新 %s 个竞猜盘口", refreshed_markets)
    defaults = enforce_overdue_prediction_loans()
    if defaults:
        logger.warning("启动时处理了 %s 笔逾期竞猜贷款", len(defaults))


def update(player_num: int):
    defaults = enforce_overdue_prediction_loans()
    for item in defaults:
        logger.warning("竞猜贷款逾期：QQ %s，死亡至 %s", item['user_id'], item['death_until'])
    refresh_match_poll_priorities()
    update_and_send_message_DOTA2()
    # dota每日请求限制100,000次
    # 每个人假设每次更新都需要请求两次
    # 所以请求间隔可以设置为 (24 * 60 * 60 / (100000 / (2 * player_num)))
    # 10个人的情况下, 会17秒更新一次信息
    # 但是其实每分钟更新一次即可保证及时
    quota_interval = (24 * 60 * 60) / (100000 / (2 * player_num))
    interval = max(config.POLL_INTERVAL, quota_interval if player_num >= 30 else 0)
    # 等待期间每秒处理一次群命令，避免管理操作卡一个轮询周期。
    deadline = time.monotonic() + interval * random.uniform(0.9, 1.1)
    while time.monotonic() < deadline:
        process_pending_events()
        time.sleep(min(1, max(0, deadline - time.monotonic())))


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if init() != -1:
        start_event_server()
        logger.info("初始化完成，开始更新比赛信息")
        while True:
            player_num = len(PLAYER_LIST)
            if player_num == 0:
                enforce_overdue_prediction_loans()
                process_pending_events()
                time.sleep(1)
                continue
            update(player_num=player_num)


if __name__ == '__main__':
    main()
