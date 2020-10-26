#!/usr/bin/python
# -*- coding: UTF-8 -*-
import time
from common import update_and_send_message_DOTA2, steam_id_convert_32_to_64
import json
from player import PLAYER_LIST, player
from DBOper import is_player_stored, insert_info, update_DOTA2_match_ID
import DOTA2
import message_sender


def init():
    # 读取配置文件
    try:
        config = json.load(open("config.json", "r", encoding='UTF-8'))
        DOTA2.api_key = config["api_key"]
        message_sender.url = config["mirai_url"]
        message_sender.authKey = config["mirai_auth_key"]
        message_sender.bot_qq = config["bot_qq"]
        message_sender.target = config["qq_group_id"]
        player_list = config["player_list"]
    except Exception:
        print("读取配置文件失败, 请检查配置文件")
        return -1
    # 读取玩家信息
    for i in player_list:
        nickname = i[0]
        short_steamID = i[1]
        print("{}信息读取完毕, ID:{}".format(nickname, short_steamID))
        long_steamID = steam_id_convert_32_to_64(short_steamID)

        try:
            last_DOTA2_match_ID = DOTA2.get_last_match_id_by_short_steamID(short_steamID)
        except DOTA2.DOTA2HTTPError:
            last_DOTA2_match_ID = "-1"

        # 如果数据库中没有这个人的信息, 则进行数据库插入
        if not is_player_stored(short_steamID):
            # 插入数据库
            insert_info(short_steamID, long_steamID, nickname, last_DOTA2_match_ID)
        # 如果有这个人的信息则更新其最新的比赛信息
        else:
            update_DOTA2_match_ID(short_steamID, last_DOTA2_match_ID)
        # 新建一个玩家对象, 放入玩家列表
        temp_player = player(short_steamID=short_steamID,
                             long_steamID=long_steamID,
                             nickname=nickname,
                             last_DOTA2_match_ID=last_DOTA2_match_ID)

        PLAYER_LIST.append(temp_player)


def update(player_num: int):
    update_and_send_message_DOTA2()
    # dota每日请求限制100,000次
    # 每个人假设每次更新都需要请求两次
    # 所以请求间隔可以设置为 (24 * 60 * 60 / (100000 / (2 * player_num)))
    # 10个人的情况下, 会17秒更新一次信息
    time.sleep((24 * 60 * 60) / (100000 / (2 * player_num)))


def main():
    if init() != -1:
        print("初始化完成, 开始更新比赛信息")
        while True:
            player_num = len(PLAYER_LIST)
            if player_num == 0:
                return
            update(player_num=player_num)


if __name__ == '__main__':
    main()
