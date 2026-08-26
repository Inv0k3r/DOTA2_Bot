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
STEAM_STATUS_INTERVAL = float(os.getenv("STEAM_STATUS_INTERVAL", "60"))
ACTIVE_MATCH_POLL_INTERVAL = float(os.getenv("ACTIVE_MATCH_POLL_INTERVAL", "60"))
INACTIVE_MATCH_POLL_INTERVAL = float(os.getenv("INACTIVE_MATCH_POLL_INTERVAL", "900"))
ACTIVE_MATCH_GRACE = float(os.getenv("ACTIVE_MATCH_GRACE", "10800"))
POST_MATCH_POLL_COOLDOWN = max(
    0.0, float(os.getenv("POST_MATCH_POLL_COOLDOWN", "600"))
)
ERROR_BACKOFF_BASE = float(os.getenv("ERROR_BACKOFF_BASE", "60"))
ERROR_BACKOFF_MAX = float(os.getenv("ERROR_BACKOFF_MAX", "1800"))
ERROR_BACKOFF_JITTER = min(0.5, max(0.0, float(os.getenv("ERROR_BACKOFF_JITTER", "0.20"))))
STEAM_HISTORY_CIRCUIT_THRESHOLD = max(
    1, int(os.getenv("STEAM_HISTORY_CIRCUIT_THRESHOLD", "3"))
)
STEAM_HISTORY_CIRCUIT_COOLDOWN = max(
    30.0, float(os.getenv("STEAM_HISTORY_CIRCUIT_COOLDOWN", "300"))
)
OPENDOTA_RATE_LIMIT_BACKOFF = float(os.getenv("OPENDOTA_RATE_LIMIT_BACKOFF", "300"))
PREDICTION_ODDS_HISTORY_MATCHES = max(
    1, int(os.getenv("PREDICTION_ODDS_HISTORY_MATCHES", "20"))
)
PREDICTION_ODDS_RECENCY_DECAY = min(
    0.99, max(0.50, float(os.getenv("PREDICTION_ODDS_RECENCY_DECAY", "0.82")))
)
PREDICTION_ODDS_PRIOR_WEIGHT = max(
    0.1, float(os.getenv("PREDICTION_ODDS_PRIOR_WEIGHT", "2.0"))
)
PREDICTION_ODDS_PROBABILITY_FLOOR = min(
    0.40, max(0.01, float(os.getenv("PREDICTION_ODDS_PROBABILITY_FLOOR", "0.10")))
)
PREDICTION_MARKET_LIQUIDITY = max(
    1, int(os.getenv("PREDICTION_MARKET_LIQUIDITY", "5000"))
)
PREDICTION_MARKET_PAYOUT_RATE = min(
    1.0, max(0.5, float(os.getenv("PREDICTION_MARKET_PAYOUT_RATE", "1.00")))
)
PREDICTION_MARKET_MAX_POOL_INFLUENCE = min(
    0.49, max(0.0, float(os.getenv("PREDICTION_MARKET_MAX_POOL_INFLUENCE", "0.10")))
)
PREDICTION_MARKET_MIN_ODDS = min(
    2.0, max(1.01, float(os.getenv("PREDICTION_MARKET_MIN_ODDS", "1.30")))
)
PREDICTION_MARKET_MAX_ODDS = max(
    PREDICTION_MARKET_MIN_ODDS,
    min(20.0, float(os.getenv("PREDICTION_MARKET_MAX_ODDS", "8.00"))),
)
PREDICTION_DAILY_CHECKIN_REWARD = max(
    1, int(os.getenv("PREDICTION_DAILY_CHECKIN_REWARD", "100"))
)
PREDICTION_GAME_WIN_REWARD = max(
    0, int(os.getenv("PREDICTION_GAME_WIN_REWARD", "100"))
)
PREDICTION_GAME_LOSS_REWARD = max(
    0, int(os.getenv("PREDICTION_GAME_LOSS_REWARD", "50"))
)
PREDICTION_UPSET_COMMISSION_RATE = min(
    1.0, max(0.0, float(os.getenv("PREDICTION_UPSET_COMMISSION_RATE", "0.10")))
)
PREDICTION_LOAN_MIN = max(1, int(os.getenv("PREDICTION_LOAN_MIN", "100")))
PREDICTION_LOAN_MAX = max(
    PREDICTION_LOAN_MIN, int(os.getenv("PREDICTION_LOAN_MAX", "2000"))
)
PREDICTION_LOAN_INTEREST_RATE = max(
    0.0, float(os.getenv("PREDICTION_LOAN_INTEREST_RATE", "0.10"))
)
PREDICTION_LOAN_TERM_SECONDS = max(
    60, int(os.getenv("PREDICTION_LOAN_TERM_SECONDS", "86400"))
)
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
