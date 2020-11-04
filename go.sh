#!/bin/bash

sudo apt install screen
pip install json
pip install requests

qq=$(python -c "import config; print config.BOT_QQ")
pass=$(python -c "import config; print config.BOT_PASSWORD")

chmod +x ./miraibot/miraiOK_linux_amd64

cd miraibot

screen_name=$"bot"
screen -dmS $screen_name

cmd=$"./miraiOK_linux_amd64";
screen -x -S $screen_name -p 0 -X stuff "$cmd"
screen -x -S $screen_name -p 0 -X stuff $'\n'
screen -x -S $screen_name -p 0 -X stuff "$cmd"
screen -x -S $screen_name -p 0 -X stuff $'\n'
cmd=$"login ${qq} ${pass}"
screen -x -S $screen_name -p 0 -X stuff "$cmd"
screen -x -S $screen_name -p 0 -X stuff $'\n'
echo "启动MiraiOK成功"

screen_name=$"watcher"
screen -dmS $screen_name
cmd=$"python3 ../run.py";
screen -x -S $screen_name -p 0 -X stuff "$cmd"
screen -x -S $screen_name -p 0 -X stuff $'\n'
echo "偷窥机器人启动成功"