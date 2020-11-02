#!/usr/bin/python
# -*- coding: UTF-8 -*-
import DOTA2
from DBOper import update_DOTA2_match_ID
from player import PLAYER_LIST
from typing import List, Dict
from message_sender import message as send

def steam_id_convert_32_to_64(short_steamID: int) -> int:
    return short_steamID + 76561197960265728


def steam_id_convert_64_to_32(long_steamID: int) -> int:
    return long_steamID - 76561197960265728


# 返回一个最新比赛变化过的字典
# 格式: { match_id1: [player1, player2, player3], match_id2: [player1, player2]}
def update_DOTA2() -> Dict:
    result = {}
    for i in PLAYER_LIST:
        try:
            match_id = DOTA2.get_last_match_id_by_short_steamID(i.short_steamID)
        except DOTA2.DOTA2HTTPError:
            continue
        if match_id != i.last_DOTA2_match_ID:

            if result.get(match_id, 0) != 0:
                result[match_id].append(i)
            else:
                result.update({match_id: [i]})
            # 更新数据库的last_DOTA2_match_id字段
            update_DOTA2_match_ID(i.short_steamID, match_id)
            # 更新列表
            i.last_DOTA2_match_ID = match_id

    return result


def update_and_send_message_DOTA2():
    # 格式: { match_id1: [player1, player2, player3], match_id2: [player1, player2]}
    result = update_DOTA2()
    for match_id in result:
        msg = DOTA2.generate_match_message(
            match_id=match_id,
            player_list=result[match_id]
        )
        if isinstance(msg, str):
            send(msg)
