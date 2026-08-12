import os
import json


# 推荐通过环境变量提供敏感配置；这里的默认值仅用于本地示例。
API_KEY = os.getenv("STEAM_API_KEY", "xxxxxx")
QQ_GROUP_ID = int(os.getenv("QQ_GROUP_ID", "10000"))

# NapCatQQ WebUI -> 网络配置 -> HTTP 服务端中配置的地址和 token。
NAPCAT_HTTP_URL = os.getenv("NAPCAT_HTTP_URL", "http://127.0.0.1:3000").rstrip("/")
NAPCAT_ACCESS_TOKEN = os.getenv("NAPCAT_ACCESS_TOKEN", "")
OPENDOTA_API_URL = os.getenv("OPENDOTA_API_URL", "https://api.opendota.com/api").rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10"))
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "60"))
POLL_WORKERS = int(os.getenv("POLL_WORKERS", "6"))
ERROR_BACKOFF_BASE = float(os.getenv("ERROR_BACKOFF_BASE", "60"))
ERROR_BACKOFF_MAX = float(os.getenv("ERROR_BACKOFF_MAX", "1800"))
EVENT_HOST = os.getenv("EVENT_HOST", "127.0.0.1")
EVENT_PORT = int(os.getenv("EVENT_PORT", "3010"))
EVENT_SECRET = os.getenv("EVENT_SECRET", "")
ADMIN_QQ_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_QQ_IDS", "").split(",")
    if value.strip()
}
DEFAULT_PLAYER_LIST = [
    ["枫哥", 90045009],
    ["甲哥", 113705693],
    ["翔哥", 104744847]
]
PLAYER_LIST = json.loads(
    os.getenv("PLAYER_LIST_JSON", json.dumps(DEFAULT_PLAYER_LIST, ensure_ascii=False))
)

# 是否在战报中附带链接（带链接的消息可能因风控发不出去）
ENABLE_URL = False

# 是否仅使用英雄默认名字
DEFAULT_NAME_ONLY = False

# 是否启用Steam游戏状态监视
ENABLE_STEAM_WATCHER = os.getenv("ENABLE_STEAM_WATCHER", "false").lower() in ("1", "true", "yes")
