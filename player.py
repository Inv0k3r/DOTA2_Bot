#!/usr/bin/python
# -*- coding: UTF-8 -*-


class player:
    # 基本属性
    short_steamID = 0
    long_steamID = 0
    nickname = ''
    DOTA2_score = ''
    last_DOTA2_match_ID = ''

    # 玩家在最新的一场比赛中的数据
    # dota2专属
    dota2_kill = 0
    dota2_death = 0
    dota2_assist = 0
    # 1为天辉, 2为夜魇
    dota2_team = 1
    kda = 0
    gpm = 0
    xpm = 0
    hero = ''
    last_hit = 0
    damage = 0

    def __init__(self, nickname, short_steamID, long_steamID, last_DOTA2_match_ID):
        self.nickname = nickname
        self.short_steamID = short_steamID
        self.long_steamID = long_steamID
        self.last_DOTA2_match_ID = last_DOTA2_match_ID


PLAYER_LIST = []
