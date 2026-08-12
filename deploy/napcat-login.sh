#!/usr/bin/env bash
set -euo pipefail

echo "正在重启 NapCat 并生成新的登录二维码……"
systemctl restart napcat.service
echo "请扫描下面即将出现的二维码；看到登录成功后按 Ctrl+C 退出日志。"
exec journalctl -u napcat.service -f -n 0 --no-pager
