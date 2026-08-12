#!/usr/bin/python
# -*- coding: UTF-8 -*-
from dataclasses import dataclass
from typing import List, Union


@dataclass
class Player:
    nickname: str
    short_steamID: int
    long_steamID: int
    last_DOTA2_match_ID: Union[int, str]
    DOTA2_score: str = ''
    dota2_kill: int = 0
    dota2_death: int = 0
    dota2_assist: int = 0
    dota2_team: int = 1
    kda: float = 0
    gpm: int = 0
    xpm: int = 0
    hero: int = 0
    last_hit: int = 0
    damage: int = 0


# 兼容旧模块的导入名称，后续代码统一使用 Player。
player = Player
PLAYER_LIST: List[Player] = []
