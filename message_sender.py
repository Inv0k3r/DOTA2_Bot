#!/usr/bin/python
# -*- coding: UTF-8 -*-
import requests

import config


class MessageSendError(RuntimeError):
    """NapCatQQ 拒绝消息或返回了无法解析的响应。"""


def message(m: str, group_id=None):
    """通过 NapCatQQ 的 OneBot 11 HTTP API 发送群消息。"""
    headers = {}
    if config.NAPCAT_ACCESS_TOKEN:
        headers["Authorization"] = "Bearer {}".format(config.NAPCAT_ACCESS_TOKEN)

    try:
        response = requests.post(
            config.NAPCAT_HTTP_URL + "/send_group_msg",
            json={"group_id": group_id or config.QQ_GROUP_ID, "message": m},
            headers=headers,
            timeout=config.REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise MessageSendError("无法连接 NapCatQQ: {}".format(exc)) from exc

    if result.get("status") != "ok" or result.get("retcode") != 0:
        raise MessageSendError("NapCatQQ 发送失败: {}".format(result))
    return result.get("data")
