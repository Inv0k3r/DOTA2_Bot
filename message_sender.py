#!/usr/bin/python
# -*- coding: UTF-8 -*-
import json
import requests
import config

url = config.MIRAI_URL
# 群号
target = config.QQ_GROUP_ID
# bot的QQ号
bot_qq = config.BOT_QQ
# mirai http的auth key
authKey = config.MIRAI_AUTH_KEY


def message(m: str):
    # Authorize
    auth_key = {"authKey": authKey}
    r = requests.post(url + "/auth", json.dumps(auth_key))
    if json.loads(r.text).get('code') != 0:
        print("ERROR@auth")
        print(r.text)
        exit(1)
    # Verify
    session_key = json.loads(r.text).get('session')
    session = {"sessionKey": session_key, "qq": bot_qq}
    r = requests.post(url + "/verify", json.dumps(session))
    if json.loads(r.text).get('code') != 0:
        print("ERROR@verify")
        print(r.text)
        exit(2)
    data = {
            "sessionKey": session_key,
            "target": target,
            "messageChain": [
                {"type": "Plain", "text": m}
            ]
        }
    r = requests.post(url + "/sendGroupMessage", json.dumps(data))
    # release
    data = {
            "sessionKey": session_key,
            "qq": bot_qq
        }
    r = requests.post(url + "/release", json.dumps(data))
    # print(r.text)
