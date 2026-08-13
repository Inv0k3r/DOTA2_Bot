# DOTA2 处刑 BOT（NapCatQQ 版）

监控指定玩家的 DOTA2 比赛和 Steam 游戏状态，并通过 NapCatQQ 向 QQ 群发送战报。

## 工作方式

1. 通过 OpenDota/Steam 查询玩家最近 20 场比赛，按顺序补齐游标后的全部新对局。
2. 发现新的比赛 ID 后通过 OpenDota 获取比赛详情；OpenDota 不可用时回退 Valve。
3. 通过 NapCatQQ 的 OneBot 11 HTTP API `send_group_msg` 发送群消息。
4. 使用本地 SQLite 数据库记录玩家状态、可靠消息队列和互动统计，避免漏发或重复播报。

新比赛会先写入本地待发队列。只有 NapCatQQ 确认发送成功后，程序才会推进玩家比赛位置；网络失败会自动退避重试。

## 环境要求

- Python 3.8+
- 已登录 QQ 的 [NapCatQQ](https://github.com/NapNeko/NapCatQQ)
- Steam Web API Key

OpenDota 的公开 API 无需 Key。本项目只在发现新比赛时请求比赛详情，不会用它轮询玩家状态。

安装 Python 依赖：

```bash
python -m pip install -r requirements.txt
```

## 配置 NapCatQQ

进入 NapCatQQ WebUI，在“网络配置”中新建并启用一个 **HTTP 服务端**：

- Host：仅本机使用时建议 `127.0.0.1`
- Port：例如 `3000`
- Token：建议设置一个随机值，公网环境必须设置

注意：这里使用的是 OneBot HTTP 服务端端口，不是默认的 WebUI 端口 `6099`。

如需使用群内监控管理，再新建一个 **HTTP 客户端**用于事件上报：

- URL：`http://127.0.0.1:3010/onebot/<EVENT_SECRET>`
- 消息格式：`array`
- 上报自身消息：关闭

事件接收器默认只监听回环地址，并校验 URL 中的随机 `EVENT_SECRET`。

## 配置机器人

推荐使用环境变量保存密钥：

```bash
export STEAM_API_KEY="你的 Steam API Key"
export QQ_GROUP_ID="目标群号"
export NAPCAT_HTTP_URL="http://127.0.0.1:3000"
export NAPCAT_ACCESS_TOKEN="NapCat HTTP 服务端 Token"
export PLAYER_LIST_JSON='[["玩家昵称",90045009]]'
export EVENT_SECRET="一段足够长的随机字符串"
```

PowerShell：

```powershell
$env:STEAM_API_KEY = "你的 Steam API Key"
$env:QQ_GROUP_ID = "目标群号"
$env:NAPCAT_HTTP_URL = "http://127.0.0.1:3000"
$env:NAPCAT_ACCESS_TOKEN = "NapCat HTTP 服务端 Token"
$env:PLAYER_LIST_JSON = '[["玩家昵称",90045009]]'
$env:EVENT_SECRET = "一段足够长的随机字符串"
```

也可以直接修改 `config.py` 中的 `DEFAULT_PLAYER_LIST`。每项格式为：

```python
["显示昵称", Steam 32位 Account ID]
```

## 启动

确保 NapCatQQ 已登录且 HTTP 服务端已启用，然后运行：

```bash
python run.py
```

轮询默认使用最多 6 个并发请求。连续失败的玩家会从 1 分钟开始指数退避，最长 30 分钟，避免私密账号持续消耗请求额度。

Linux 也可以使用：

```bash
bash go.sh
```

## 测试 NapCat 连接

可先用下面的请求验证 NapCatQQ 配置。设置了 Token 时需保留 `Authorization` 请求头：

```bash
curl -X POST http://127.0.0.1:3000/send_group_msg \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 你的Token" \
  -d '{"group_id":123456789,"message":"DOTA2 BOT 连接测试"}'
```

成功响应应包含 `"status":"ok"` 和 `"retcode":0`。

## 管理命令

以下命令需要使用和服务相同的环境变量：

```bash
# 查看 NapCat、玩家数量和待发队列
python manage.py status

# 查看监控名单
python manage.py players

# 发送测试消息
python manage.py test-message "DOTA2 BOT 测试"

# 预览指定玩家最新一场战报
python manage.py report 90045009 "示例玩家"

# 生成并发送指定比赛
python manage.py report 90045009 "示例玩家" --match-id 1234567890 --send
```

### 群内管理监控名单

群主、群管理员以及 `ADMIN_QQ_IDS` 中配置的 QQ 可以执行：

```text
添加监控 <Steam个人主页、SteamID64或Account ID> <群内昵称>
删除监控 <群内昵称或Steam ID>
监控列表
```

例如：

```text
添加监控 https://steamcommunity.com/profiles/76561198000000000 示例玩家
删除监控 示例玩家
```

名单变更即时生效并持久化到数据库，不需要重启服务。`PLAYER_LIST_JSON`
只用于导入尚不存在的新玩家，不会重新启用已经在群内删除的玩家。

### 群内自定义锐评

必须先 `@机器人`，群主、管理员或 `ADMIN_QQ_IDS` 白名单用户可以使用：

```text
@bot 加锐评 死亡>=10 60% 这死亡数是在泉水和战场之间跑滴滴？
@bot 加锐评 死亡>=10 KDA<1 80% 纯正人形经验包。
@bot 锐评列表
@bot 停锐评 12
@bot 开锐评 12
@bot 删锐评 12
```

概率支持 `60%`、`60％`、`概率60%` 或 `概率=60%`；全角符号及运算符两侧的空格也会自动兼容。例如：

```text
@bot 加锐评 伤害占比 >= 40％ 概率=75％ 这把确实尽力了。
```

任何群成员都可以发送 `@bot 帮助` 查看精简命令说明。

其它娱乐命令：

```text
@bot 加外号 玩家甲 泉水质检员 40%
@bot 删外号 玩家甲
@bot 组合名 玩家甲+玩家乙+玩家丙 泉水旅游团
@bot 今日红黑榜
@bot 谁在连败
```

回复一条机器人战报后可以发送 `@bot 鞭尸 [玩家]`、`@bot 再骂一句`，或用
`@bot 锐评太轻`、`@bot 锐评合适`、`@bot 锐评过头`反馈火候。

支持字段：`击杀`、`死亡`、`助攻`、`KDA`、`GPM`、`XPM`、`补刀`、
`伤害`、`伤害占比`、`参战率`、`死亡占比`、`胜负`。多个条件之间表示“并且”；
胜负写作 `胜负=胜` 或 `胜负=负`。自定义规则命中后优先于内置锐评，同一局的概率结果固定。

## 战报内容

- 同一场比赛中的监控玩家合并为一条消息。
- 同阵营多人会标记为“组队开黑”，不同阵营会标记为“同局撞车”。
- 分别展示胜负、英雄、K/D/A、GPM/XPM、补刀、伤害占比和参战率。
- 根据稳定的数据规则生成趣味评价，不调用大模型。
- 多人对局追加赛后奖项、组合战绩、宿敌比分和连胜/连败信息。
- 回复战报可鞭尸、补充锐评或评价锐评火候。
- 外号、自定义组合名、自定义锐评和统计数据均持久化在 SQLite。

## 下一场竞猜

群成员可以竞猜某位监控玩家下一场公开比赛的胜负：

```text
@bot 竞猜 椒吉米 赢 100
@bot 竞猜 椒吉米 输 50
@bot 赔率 椒吉米
@bot 我的竞猜
@bot 我的积分
@bot 竞猜榜
```

- 每位群成员首次使用时获得 1000 点；下注立即扣除点数，余额不足时不能下注。
- 可以同时竞猜不同玩家；同一目标在结算前再次下注会退回旧本金并改押。
- 已绑定的群成员不能竞猜自己；绑定前已有的自押会自动撤销并退回本金，结算时也会再次校验。
- 目标默认达到 3 连败后暂停竞猜，所有未结算下注自动退还；赢一场后自动恢复。可用 `PREDICTION_LOSS_STREAK_LIMIT` 调整阈值。
- 赛后若发现下注者绑定的 Steam 账号也在该局中，这笔下注作废并退回本金；不依赖可能缺失的开黑/队伍标记。
- 赔率根据目标玩家的历史胜率动态计算：加入 5 胜 5 负的平滑先验，按 90% 返还率定价，并限制在 1.20–4.00；下注时锁定赔率。
- 猜中返还“下注额 × 锁定赔率”，猜错损失本金。
- 下注只会结算下注后开始的下一场比赛；比赛开始后的下注自动顺延到下一场。
- 管理员可用 `@bot 绑定玩家 @群友 <监控玩家>` 绑定 QQ；被绑定玩家每完成一场被战报识别的比赛可获得 50 点，且每场只奖励一次。
- `@bot 竞猜榜` 按可用点数排行，并显示胜负、命中率和竞猜净收益。
- 结算直接复用战报已经获取的比赛数据，不会增加 Steam 或 OpenDota API 请求。
- 竞猜和积分保存在 SQLite 中，服务重启或战报重试不会重复结算。

可通过环境变量调整轮询：

- `POLL_INTERVAL`：基础轮询间隔，默认 60 秒。
- `POLL_WORKERS`：最大并发请求数，默认 6。
- `STEAM_STATUS_INTERVAL`：批量检查玩家 Steam 在线状态的间隔，默认 60 秒。
- `ACTIVE_MATCH_POLL_INTERVAL`：正在运行 DOTA2 的玩家比赛历史轮询间隔，默认 60 秒。
- `INACTIVE_MATCH_POLL_INTERVAL`：非活跃玩家比赛历史兜底轮询间隔，默认 900 秒。
- `ACTIVE_MATCH_GRACE`：玩家离开 DOTA2 后保持高频轮询的时间，默认 10800 秒。
- `ERROR_BACKOFF_BASE`：首次失败退避秒数，默认 60。
- `ERROR_BACKOFF_MAX`：最长退避秒数，默认 1800。
- `OPENDOTA_RATE_LIMIT_BACKOFF`：OpenDota 返回限流响应后的全局冷却秒数，默认 300。
- `PREDICTION_LOSS_STREAK_LIMIT`：连续失败多少场后暂停该玩家的竞猜，默认 3。

## 安全提示

- 不要把 Steam API Key 或 NapCat Token 提交到 Git。
- 不要提交运行中的 SQLite 数据库；仓库已默认忽略 `*.db`、`*.sqlite*`。
- 生产环境建议用 `deploy/dota2-bot.env.example` 复制出独立环境文件，并设置为 `600` 权限。
- 不需要公网访问时，让 NapCat HTTP 服务端只监听本机。
- 如果机器人和 NapCat 位于不同机器，请使用防火墙限制来源地址并启用 Token。
