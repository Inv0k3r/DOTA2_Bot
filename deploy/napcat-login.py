#!/usr/bin/env python3
"""Interactive NapCat QR login with a fresh DOTA report baseline."""
import json
import os
import re
import select
import shlex
import subprocess
import sys
import time
import urllib.request


NAPCAT_SERVICE = "napcat.service"
DOTA_SERVICE = "dota2-bot.service"
ENV_PATH = "/etc/dota2-bot.env"
LOGIN_TIMEOUT = 600
QR_PATTERN = re.compile(r"二维码解码URL:\s*(https://\S+)")


def load_onebot_config():
    values = {}
    with open(ENV_PATH, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key not in {"NAPCAT_HTTP_URL", "NAPCAT_ACCESS_TOKEN"}:
                continue
            parsed = shlex.split(value, comments=True)
            values[key] = parsed[0] if parsed else ""
    return values.get("NAPCAT_HTTP_URL", "http://127.0.0.1:3000"), values.get(
        "NAPCAT_ACCESS_TOKEN", ""
    )


def onebot_online(url, token):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        url.rstrip("/") + "/get_status",
        data=b"{}",
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.load(response)
        return bool((payload.get("data") or {}).get("online"))
    except (OSError, ValueError):
        return False


def draw_qrcode(url):
    print("\033[2J\033[H", end="", flush=True)
    print("请使用手机 QQ 扫描下面的二维码：\n", flush=True)
    subprocess.run(["qrencode", "-t", "ANSIUTF8", "-m", "2", url], check=True)
    print(
        "\n扫码后请在手机上确认。二维码更新时这里会自动重画，请不要扫描旧截图。",
        flush=True,
    )


def restart_dota_bot_with_fresh_baseline():
    subprocess.run(["systemctl", "restart", DOTA_SERVICE], check=True)
    subprocess.run(["systemctl", "is-active", "--quiet", DOTA_SERVICE], check=True)


def main():
    onebot_url, onebot_token = load_onebot_config()
    if onebot_online(onebot_url, onebot_token):
        print("NapCat QQ 当前在线，无需重新登录。")
        return 0

    started_at = time.time() - 1
    journal = subprocess.Popen(
        [
            "journalctl", "-u", NAPCAT_SERVICE,
            "--since", "@{:.3f}".format(started_at),
            "-f", "-o", "cat", "--no-pager",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    try:
        print("正在重启 NapCat 并申请全新二维码……", flush=True)
        subprocess.run(["systemctl", "restart", NAPCAT_SERVICE], check=True)
        deadline = time.monotonic() + LOGIN_TIMEOUT
        last_status_check = 0.0
        displayed_url = ""
        qr_wait_notice_at = time.monotonic() + 20
        journal_buffer = b""

        while time.monotonic() < deadline:
            readable, _, _ = select.select([journal.stdout], [], [], 1)
            if readable:
                chunk = os.read(journal.stdout.fileno(), 65536)
                journal_buffer += chunk
                lines = journal_buffer.split(b"\n")
                journal_buffer = lines.pop()
                for raw_line in lines:
                    line = raw_line.decode("utf-8", errors="replace")
                    match = QR_PATTERN.search(line)
                    if match:
                        url = match.group(1).split("\x1b", 1)[0]
                        if url != displayed_url:
                            displayed_url = url
                            draw_qrcode(url)

            now = time.monotonic()
            if now - last_status_check >= 2:
                last_status_check = now
                if onebot_online(onebot_url, onebot_token):
                    restart_dota_bot_with_fresh_baseline()
                    print(
                        "\n登录成功。已建立新的战报基线；未发送的积压战报不会重试，"
                        "只推送本次登录后新开始的比赛。",
                        flush=True,
                    )
                    return 0
            if not displayed_url and now >= qr_wait_notice_at:
                print("仍在等待 QQ 返回二维码，请稍候……", flush=True)
                qr_wait_notice_at = now + 20

        print("\n等待登录超时，请重新运行 napcat-login。", flush=True)
        return 1
    finally:
        journal.terminate()
        try:
            journal.wait(timeout=2)
        except subprocess.TimeoutExpired:
            journal.kill()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已取消。")
        raise SystemExit(130)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print("登录脚本失败：{}".format(exc), file=sys.stderr)
        raise SystemExit(1)
