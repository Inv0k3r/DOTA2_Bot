#!/usr/bin/python
# -*- coding: UTF-8 -*-
import json
import os
import sqlite3
import time
from pathlib import Path
from player import Player, PLAYER_LIST

DATABASE_PATH = Path(
    os.getenv('DATABASE_PATH', str(Path(__file__).resolve().with_name('playerInfo.db')))
)
conn = sqlite3.connect(str(DATABASE_PATH))
c = conn.cursor()
c.execute(
    """CREATE TABLE IF NOT EXISTS playerInfo (
        short_steamID INTEGER PRIMARY KEY,
        long_steamID INTEGER,
        nickname TEXT,
        DOTA2_SCORE INTEGER,
        last_DOTA2_match_ID INTEGER,
        gamename TEXT,
        last_update INTEGER
    )"""
)
c.execute(
    """CREATE TABLE IF NOT EXISTS match_outbox (
        match_id INTEGER PRIMARY KEY,
        payload TEXT NOT NULL,
        player_ids TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        message_id INTEGER,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        sent_at INTEGER
    )"""
)
c.execute(
    "CREATE INDEX IF NOT EXISTS idx_match_outbox_status_updated "
    "ON match_outbox(status, updated_at)"
)
c.execute(
    """CREATE TABLE IF NOT EXISTS comment_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        conditions_json TEXT NOT NULL,
        probability INTEGER NOT NULL,
        text TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        deleted INTEGER NOT NULL DEFAULT 0,
        creator_qq INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )"""
)
c.execute(
    "CREATE INDEX IF NOT EXISTS idx_comment_rules_group_enabled "
    "ON comment_rules(group_id, enabled, deleted)"
)
c.execute(
    """CREATE TABLE IF NOT EXISTS match_stats (
        match_id INTEGER NOT NULL,
        account_id INTEGER NOT NULL,
        group_id INTEGER NOT NULL,
        nickname TEXT NOT NULL,
        start_time INTEGER NOT NULL,
        won INTEGER NOT NULL,
        team INTEGER NOT NULL,
        hero_id INTEGER NOT NULL,
        kills INTEGER NOT NULL,
        deaths INTEGER NOT NULL,
        assists INTEGER NOT NULL,
        gpm INTEGER NOT NULL,
        xpm INTEGER NOT NULL,
        last_hits INTEGER NOT NULL,
        damage INTEGER NOT NULL,
        damage_share REAL NOT NULL,
        participation REAL NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (match_id, account_id)
    )"""
)
c.execute("CREATE INDEX IF NOT EXISTS idx_match_stats_account_time ON match_stats(account_id, start_time DESC)")
c.execute("CREATE INDEX IF NOT EXISTS idx_match_stats_group_time ON match_stats(group_id, start_time DESC)")
c.execute(
    """CREATE TABLE IF NOT EXISTS player_aliases (
        group_id INTEGER NOT NULL,
        account_id INTEGER NOT NULL,
        alias TEXT NOT NULL,
        probability INTEGER NOT NULL DEFAULT 35,
        creator_qq INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        PRIMARY KEY (group_id, account_id)
    )"""
)
c.execute(
    """CREATE TABLE IF NOT EXISTS combo_names (
        group_id INTEGER NOT NULL,
        player_ids TEXT NOT NULL,
        name TEXT NOT NULL,
        creator_qq INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        PRIMARY KEY (group_id, player_ids)
    )"""
)
c.execute(
    """CREATE TABLE IF NOT EXISTS comment_votes (
        group_id INTEGER NOT NULL,
        match_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        vote TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (group_id, match_id, user_id)
    )"""
)
c.execute(
    """CREATE TABLE IF NOT EXISTS interaction_limits (
        group_id INTEGER NOT NULL,
        match_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        count INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL,
        PRIMARY KEY (group_id, match_id, action)
    )"""
)
c.execute(
    """CREATE TABLE IF NOT EXISTS prediction_bets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        user_name TEXT NOT NULL,
        target_account_id INTEGER NOT NULL,
        target_nickname TEXT NOT NULL,
        prediction INTEGER NOT NULL,
        stake INTEGER NOT NULL DEFAULT 0,
        odds REAL NOT NULL DEFAULT 2.0,
        after_match_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        settled_match_id INTEGER,
        actual_won INTEGER,
        score_delta INTEGER,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        settled_at INTEGER
    )"""
)
c.execute(
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_prediction_bets_open "
    "ON prediction_bets(group_id,user_id,target_account_id) WHERE status='open'"
)
c.execute(
    "CREATE INDEX IF NOT EXISTS idx_prediction_bets_target_status "
    "ON prediction_bets(group_id,target_account_id,status)"
)
c.execute(
    """CREATE TABLE IF NOT EXISTS prediction_scores (
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        user_name TEXT NOT NULL,
        score INTEGER NOT NULL DEFAULT 1000,
        wins INTEGER NOT NULL DEFAULT 0,
        losses INTEGER NOT NULL DEFAULT 0,
        wagered INTEGER NOT NULL DEFAULT 0,
        returned INTEGER NOT NULL DEFAULT 0,
        game_earned INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL,
        PRIMARY KEY (group_id,user_id)
    )"""
)
c.execute(
    """CREATE TABLE IF NOT EXISTS prediction_player_links (
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        user_name TEXT NOT NULL,
        account_id INTEGER NOT NULL,
        nickname TEXT NOT NULL,
        updated_at INTEGER NOT NULL,
        PRIMARY KEY (group_id,user_id),
        UNIQUE (group_id,account_id)
    )"""
)
c.execute(
    """CREATE TABLE IF NOT EXISTS prediction_game_rewards (
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        account_id INTEGER NOT NULL,
        match_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (group_id,user_id,match_id)
    )"""
)
bet_columns = {row[1] for row in c.execute("PRAGMA table_info(prediction_bets)").fetchall()}
if 'stake' not in bet_columns:
    c.execute("ALTER TABLE prediction_bets ADD COLUMN stake INTEGER NOT NULL DEFAULT 0")
if 'odds' not in bet_columns:
    c.execute("ALTER TABLE prediction_bets ADD COLUMN odds REAL NOT NULL DEFAULT 2.0")
score_columns = {row[1] for row in c.execute("PRAGMA table_info(prediction_scores)").fetchall()}
for column in ('wagered', 'returned', 'game_earned'):
    if column not in score_columns:
        c.execute("ALTER TABLE prediction_scores ADD COLUMN {} INTEGER NOT NULL DEFAULT 0".format(column))
outbox_columns = {
    row[1] for row in c.execute("PRAGMA table_info(match_outbox)").fetchall()
}
if 'next_attempt_at' not in outbox_columns:
    c.execute(
        "ALTER TABLE match_outbox ADD COLUMN next_attempt_at INTEGER NOT NULL DEFAULT 0"
    )
player_columns = {
    row[1] for row in c.execute("PRAGMA table_info(playerInfo)").fetchall()
}
if 'enabled' not in player_columns:
    c.execute(
        "ALTER TABLE playerInfo ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1"
    )
conn.commit()


def init():
    cursor = c.execute("SELECT * from playerInfo")
    for row in cursor:
        player_obj = Player(short_steamID=row[0],
                            long_steamID=row[1],
                            nickname=row[2],
                            last_DOTA2_match_ID=row[4])
        player_obj.DOTA2_score = row[4]
        PLAYER_LIST.append(player_obj)


def update_DOTA2_match_ID(short_steamID, last_DOTA2_match_ID):
    c.execute(
        "UPDATE playerInfo SET last_DOTA2_match_ID=? WHERE short_steamID=?",
        (last_DOTA2_match_ID, short_steamID)
    )
    conn.commit()


def insert_info(short_steamID, long_steamID, nickname, last_DOTA2_match_ID):
    c.execute(
        "INSERT INTO playerInfo "
        "(short_steamID, long_steamID, nickname, last_DOTA2_match_ID) VALUES (?, ?, ?, ?)",
        (short_steamID, long_steamID, nickname, last_DOTA2_match_ID)
    )
    conn.commit()


def is_player_stored(short_steamID: int) -> bool:
    c.execute("SELECT 1 FROM playerInfo WHERE short_steamID=?", (short_steamID,))
    if len(c.fetchall()) == 0:
        return False
    return True

def get_playing_game(short_steamID):
    ret = c.execute(
        "SELECT gamename, last_update FROM playerInfo WHERE short_steamID=?",
        (short_steamID,)
    ).fetchone()
    return ((ret[0] or ''), (ret[1] or 0)) if ret else ('', 0)

def update_playing_game(short_steamID, gamename, timestamp):
    c.execute(
        "UPDATE playerInfo SET gamename=?, last_update=? WHERE short_steamID=?",
        (gamename, timestamp, short_steamID)
    )
    conn.commit()


def upsert_player(short_steamID, long_steamID, nickname, last_DOTA2_match_ID):
    """Create or re-enable a player without losing an existing match cursor."""
    row = c.execute(
        "SELECT last_DOTA2_match_ID FROM playerInfo WHERE short_steamID=?",
        (short_steamID,),
    ).fetchone()
    if row:
        c.execute(
            "UPDATE playerInfo SET long_steamID=?, nickname=?, enabled=1 "
            "WHERE short_steamID=?",
            (long_steamID, nickname, short_steamID),
        )
    else:
        c.execute(
            "INSERT INTO playerInfo "
            "(short_steamID, long_steamID, nickname, last_DOTA2_match_ID, enabled) "
            "VALUES (?, ?, ?, ?, 1)",
            (short_steamID, long_steamID, nickname, last_DOTA2_match_ID),
        )
    conn.commit()
    return row[0] if row else last_DOTA2_match_ID


def disable_player(short_steamID):
    c.execute(
        "UPDATE playerInfo SET enabled=0 WHERE short_steamID=?",
        (short_steamID,),
    )
    changed = c.rowcount > 0
    conn.commit()
    return changed


def get_enabled_players():
    return [
        {
            'short_steamID': row[0],
            'long_steamID': row[1],
            'nickname': row[2],
            'last_DOTA2_match_ID': row[3],
        }
        for row in c.execute(
            "SELECT short_steamID, long_steamID, nickname, last_DOTA2_match_ID "
            "FROM playerInfo WHERE enabled=1 ORDER BY rowid"
        ).fetchall()
    ]


def add_comment_rule(group_id, conditions, probability, text, creator_qq):
    active_count = c.execute(
        "SELECT COUNT(*) FROM comment_rules WHERE group_id=? AND deleted=0",
        (int(group_id),),
    ).fetchone()[0]
    if active_count >= 100:
        raise ValueError('本群最多保存 100 条锐评规则')
    now = int(time.time())
    c.execute(
        """INSERT INTO comment_rules
           (group_id, conditions_json, probability, text, creator_qq, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (int(group_id), json.dumps(conditions, ensure_ascii=False), int(probability),
         text, int(creator_qq), now, now),
    )
    conn.commit()
    return c.lastrowid


def get_comment_rules(group_id, include_disabled=True):
    enabled_filter = '' if include_disabled else ' AND enabled=1'
    rows = c.execute(
        """SELECT id, conditions_json, probability, text, enabled, creator_qq
           FROM comment_rules WHERE group_id=? AND deleted=0{} ORDER BY id DESC""".format(
            enabled_filter
        ),
        (int(group_id),),
    ).fetchall()
    return [
        {
            'id': row[0],
            'conditions': json.loads(row[1]),
            'probability': row[2],
            'text': row[3],
            'enabled': bool(row[4]),
            'creator_qq': row[5],
        }
        for row in rows
    ]


def set_comment_rule_enabled(group_id, rule_id, enabled):
    c.execute(
        """UPDATE comment_rules SET enabled=?, updated_at=?
           WHERE id=? AND group_id=? AND deleted=0""",
        (1 if enabled else 0, int(time.time()), int(rule_id), int(group_id)),
    )
    changed = c.rowcount > 0
    conn.commit()
    return changed


def delete_comment_rule(group_id, rule_id):
    c.execute(
        """UPDATE comment_rules SET deleted=1, enabled=0, updated_at=?
           WHERE id=? AND group_id=? AND deleted=0""",
        (int(time.time()), int(rule_id), int(group_id)),
    )
    changed = c.rowcount > 0
    conn.commit()
    return changed


def save_match_stats(match_id, group_id, start_time, rows):
    now = int(time.time())
    with conn:
        c.executemany(
            """INSERT OR REPLACE INTO match_stats
               (match_id, account_id, group_id, nickname, start_time, won, team,
                hero_id, kills, deaths, assists, gpm, xpm, last_hits, damage,
                damage_share, participation, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(int(match_id), int(row['account_id']), int(group_id), row['nickname'],
              int(start_time), 1 if row['won'] else 0, int(row['team']), int(row['hero_id']),
              int(row['kills']), int(row['deaths']), int(row['assists']), int(row['gpm']),
              int(row['xpm']), int(row['last_hits']), int(row['damage']),
              float(row['damage_share']), float(row['participation']), now)
             for row in rows],
        )


def get_match_stats(match_id):
    rows = c.execute(
        """SELECT account_id,nickname,start_time,won,team,hero_id,kills,deaths,assists,
                  gpm,xpm,last_hits,damage,damage_share,participation
           FROM match_stats WHERE match_id=? ORDER BY team,nickname""",
        (int(match_id),),
    ).fetchall()
    keys = ('account_id','nickname','start_time','won','team','hero_id','kills','deaths',
            'assists','gpm','xpm','last_hits','damage','damage_share','participation')
    return [dict(zip(keys, row)) for row in rows]


def get_match_id_by_message_id(message_id):
    row = c.execute("SELECT match_id FROM match_outbox WHERE message_id=?", (int(message_id),)).fetchone()
    return row[0] if row else None


def get_player_streak(account_id):
    results = [row[0] for row in c.execute(
        "SELECT won FROM match_stats WHERE account_id=? ORDER BY start_time DESC,match_id DESC LIMIT 20",
        (int(account_id),),
    ).fetchall()]
    if not results:
        return 0
    length = 0
    first = results[0]
    for result in results:
        if result != first:
            break
        length += 1
    return length if first else -length


def get_rivalry(account_ids):
    ids = sorted(int(value) for value in account_ids)
    if len(ids) != 2:
        return None
    rows = c.execute(
        """SELECT a.won, COUNT(*) FROM match_stats a JOIN match_stats b ON a.match_id=b.match_id
           WHERE a.account_id=? AND b.account_id=? AND a.team<>b.team GROUP BY a.won""",
        (ids[0], ids[1]),
    ).fetchall()
    counts = dict(rows)
    return {'first': ids[0], 'first_wins': counts.get(1, 0), 'second_wins': counts.get(0, 0)}


def set_player_alias(group_id, account_id, alias, probability, creator_qq):
    c.execute(
        "INSERT OR REPLACE INTO player_aliases VALUES (?,?,?,?,?,?)",
        (int(group_id), int(account_id), alias, int(probability), int(creator_qq), int(time.time())),
    )
    conn.commit()


def delete_player_alias(group_id, account_id):
    c.execute("DELETE FROM player_aliases WHERE group_id=? AND account_id=?", (int(group_id), int(account_id)))
    changed = c.rowcount > 0
    conn.commit()
    return changed


def get_player_alias(group_id, account_id):
    row = c.execute("SELECT alias,probability FROM player_aliases WHERE group_id=? AND account_id=?",
                    (int(group_id), int(account_id))).fetchone()
    return {'alias': row[0], 'probability': row[1]} if row else None


def set_combo_name(group_id, player_ids, name, creator_qq):
    key = json.dumps(sorted(int(value) for value in player_ids))
    c.execute("INSERT OR REPLACE INTO combo_names VALUES (?,?,?,?,?)",
              (int(group_id), key, name, int(creator_qq), int(time.time())))
    conn.commit()


def get_combo_name(group_id, player_ids):
    key = json.dumps(sorted(int(value) for value in player_ids))
    row = c.execute("SELECT name FROM combo_names WHERE group_id=? AND player_ids=?", (int(group_id), key)).fetchone()
    return row[0] if row else None


def get_combo_record(player_ids):
    ids = sorted(int(value) for value in player_ids)
    if len(ids) < 2:
        return (0, 0)
    placeholders = ','.join('?' for _ in ids)
    rows = c.execute(
        """SELECT match_id, MIN(won), MAX(won), COUNT(DISTINCT account_id)
           FROM match_stats WHERE account_id IN ({}) GROUP BY match_id
           HAVING COUNT(DISTINCT account_id)=? AND MIN(team)=MAX(team)""".format(placeholders),
        tuple(ids) + (len(ids),),
    ).fetchall()
    return (sum(1 for row in rows if row[1] == 1), len(rows))


def save_comment_vote(group_id, match_id, user_id, vote):
    c.execute("INSERT OR REPLACE INTO comment_votes VALUES (?,?,?,?,?)",
              (int(group_id), int(match_id), int(user_id), vote, int(time.time())))
    conn.commit()


def get_comment_vote_summary(group_id):
    return dict(c.execute(
        "SELECT vote,COUNT(*) FROM comment_votes WHERE group_id=? GROUP BY vote",
        (int(group_id),),
    ).fetchall())


def increment_interaction(group_id, match_id, action, limit):
    row = c.execute("SELECT count FROM interaction_limits WHERE group_id=? AND match_id=? AND action=?",
                    (int(group_id), int(match_id), action)).fetchone()
    count = row[0] if row else 0
    if count >= limit:
        return False
    c.execute("INSERT OR REPLACE INTO interaction_limits VALUES (?,?,?,?,?)",
              (int(group_id), int(match_id), action, count + 1, int(time.time())))
    conn.commit()
    return True


def get_today_stats(group_id, since_timestamp):
    rows = c.execute(
        """SELECT account_id,nickname,COUNT(*),SUM(won),SUM(kills),SUM(deaths),SUM(assists)
           FROM match_stats WHERE group_id=? AND start_time>=? GROUP BY account_id,nickname""",
        (int(group_id), int(since_timestamp)),
    ).fetchall()
    keys = ('account_id','nickname','games','wins','kills','deaths','assists')
    return [dict(zip(keys, row)) for row in rows]


def get_prediction_odds(group_id, target_account_id):
    row = c.execute(
        """SELECT COUNT(*),COALESCE(SUM(won),0) FROM match_stats
           WHERE group_id=? AND account_id=?""",
        (int(group_id), int(target_account_id)),
    ).fetchone()
    games, wins = int(row[0]), int(row[1])
    win_probability = (wins + 5.0) / (games + 10.0)
    win_probability = min(0.8, max(0.2, win_probability))
    def offered(probability):
        return round(min(4.0, max(1.2, 0.90 / probability)), 2)
    return {
        'games': games, 'wins': wins,
        'win': offered(win_probability),
        'lose': offered(1.0 - win_probability),
    }


def place_prediction_bet(group_id, user_id, user_name, target_account_id,
                         target_nickname, prediction, stake, odds, after_match_id):
    """Create or change one user's open bet for a tracked player's next match."""
    now = int(time.time())
    group_id = int(group_id)
    user_id = int(user_id)
    target_account_id = int(target_account_id)
    prediction = 1 if prediction else 0
    stake = int(stake)
    if stake <= 0:
        raise ValueError('下注点数必须大于 0')
    with conn:
        linked_player = c.execute(
            """SELECT nickname FROM prediction_player_links
               WHERE group_id=? AND user_id=? AND account_id=?""",
            (group_id, user_id, target_account_id),
        ).fetchone()
        if linked_player:
            raise ValueError('不能竞猜自己（你已绑定为 {}）'.format(linked_player[0]))
        c.execute(
            """INSERT INTO prediction_scores(group_id,user_id,user_name,score,updated_at)
               VALUES (?,?,?,1000,?) ON CONFLICT(group_id,user_id) DO UPDATE SET
               user_name=excluded.user_name,updated_at=excluded.updated_at""",
            (group_id, user_id, user_name, now),
        )
        row = c.execute(
            """SELECT id,stake FROM prediction_bets
               WHERE group_id=? AND user_id=? AND target_account_id=? AND status='open'""",
            (group_id, user_id, target_account_id),
        ).fetchone()
        refundable = int(row[1]) if row else 0
        balance = c.execute(
            "SELECT score FROM prediction_scores WHERE group_id=? AND user_id=?",
            (group_id, user_id),
        ).fetchone()[0] + refundable
        if balance < stake:
            raise ValueError('余额不足：当前可用 {} 点'.format(balance))
        if row:
            c.execute(
                """UPDATE prediction_bets
                   SET user_name=?,target_nickname=?,prediction=?,stake=?,odds=?,
                       after_match_id=?,updated_at=?
                   WHERE id=?""",
                (user_name, target_nickname, prediction, stake, float(odds),
                 int(after_match_id), now, row[0]),
            )
            bet_id, changed = row[0], True
        else:
            c.execute(
                """INSERT INTO prediction_bets
                   (group_id,user_id,user_name,target_account_id,target_nickname,prediction,
                    stake,odds,after_match_id,status,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,'open',?,?)""",
                (group_id, user_id, user_name, target_account_id,
                 target_nickname, prediction, stake, float(odds), int(after_match_id), now, now),
            )
            bet_id, changed = c.lastrowid, False
        c.execute(
            """UPDATE prediction_scores
               SET score=?,wagered=wagered+?,returned=returned+?,updated_at=?
               WHERE group_id=? AND user_id=?""",
            (balance - stake, stake, refundable, now, group_id, user_id),
        )
    return {'id': bet_id, 'changed': changed, 'balance': balance - stake}


def get_open_prediction_bets(group_id, user_id):
    rows = c.execute(
        """SELECT id,target_account_id,target_nickname,prediction,stake,odds,
                  after_match_id,created_at
           FROM prediction_bets WHERE group_id=? AND user_id=? AND status='open'
           ORDER BY created_at,id""",
        (int(group_id), int(user_id)),
    ).fetchall()
    keys = ('id','target_account_id','target_nickname','prediction','stake','odds',
            'after_match_id','created_at')
    return [dict(zip(keys, row)) for row in rows]


def get_prediction_score(group_id, user_id):
    row = c.execute(
        """SELECT user_name,score,wins,losses,wagered,returned,game_earned
           FROM prediction_scores
           WHERE group_id=? AND user_id=?""",
        (int(group_id), int(user_id)),
    ).fetchone()
    return dict(zip(('user_name','score','wins','losses','wagered','returned','game_earned'), row)) if row else {
        'user_name': str(user_id), 'score': 1000, 'wins': 0, 'losses': 0,
        'wagered': 0, 'returned': 0, 'game_earned': 0,
    }


def get_prediction_leaderboard(group_id, limit=10):
    rows = c.execute(
        """SELECT user_id,user_name,score,wins,losses,wagered,returned,game_earned
           FROM prediction_scores
           WHERE group_id=? ORDER BY score DESC,wins DESC,updated_at ASC LIMIT ?""",
        (int(group_id), int(limit)),
    ).fetchall()
    keys = ('user_id','user_name','score','wins','losses','wagered','returned','game_earned')
    return [dict(zip(keys, row)) for row in rows]


def settle_prediction_bets(group_id, match_id, match_start_time, match_rows):
    """Settle eligible next-match bets once; returns a summary safe for report output."""
    now = int(time.time())
    settled = []
    with conn:
        for match_row in match_rows:
            account_id = int(match_row['account_id'])
            actual_won = 1 if match_row['won'] else 0
            bets = c.execute(
                """SELECT id,user_id,user_name,prediction,stake,odds FROM prediction_bets
                   WHERE group_id=? AND target_account_id=? AND status='open'
                     AND after_match_id<? AND created_at<=? ORDER BY id""",
                (int(group_id), account_id, int(match_id), int(match_start_time)),
            ).fetchall()
            for bet_id, user_id, user_name, prediction, stake, odds in bets:
                linked_to_target = c.execute(
                    """SELECT 1 FROM prediction_player_links
                       WHERE group_id=? AND user_id=? AND account_id=?""",
                    (int(group_id), int(user_id), account_id),
                ).fetchone()
                if linked_to_target:
                    _cancel_open_self_bets(group_id, user_id, account_id, now)
                    continue
                correct = int(prediction) == actual_won
                score_row = c.execute(
                    """SELECT score FROM prediction_scores WHERE group_id=? AND user_id=?""",
                    (int(group_id), int(user_id)),
                ).fetchone()
                current_score = score_row[0] if score_row else 0
                payout = int(round(int(stake) * float(odds))) if correct else 0
                profit = payout - int(stake)
                c.execute(
                    """UPDATE prediction_scores SET user_name=?,score=score+?,
                       wins=wins+?,losses=losses+?,returned=returned+?,updated_at=?
                       WHERE group_id=? AND user_id=?""",
                    (user_name, payout, 1 if correct else 0, 0 if correct else 1,
                     payout, now, int(group_id), int(user_id)),
                )
                c.execute(
                    """UPDATE prediction_bets SET status='settled',settled_match_id=?,
                       actual_won=?,score_delta=?,settled_at=?,updated_at=?
                       WHERE id=? AND status='open'""",
                    (int(match_id), actual_won, profit, now, now, bet_id),
                )
                if c.rowcount:
                    settled.append({
                        'bet_id': bet_id, 'user_id': user_id, 'user_name': user_name,
                        'target_nickname': match_row['nickname'], 'prediction': prediction,
                        'actual_won': actual_won, 'correct': correct, 'stake': stake,
                        'odds': odds, 'payout': payout, 'delta': profit,
                        'score': current_score + payout,
                    })
    return settled


def _cancel_open_self_bets(group_id, user_id, account_id, now=None):
    """Cancel and refund open bets made by a user on their linked player."""
    now = int(time.time()) if now is None else int(now)
    group_id = int(group_id)
    user_id = int(user_id)
    account_id = int(account_id)
    rows = c.execute(
        """SELECT id,stake FROM prediction_bets
           WHERE group_id=? AND user_id=? AND target_account_id=? AND status='open'""",
        (group_id, user_id, account_id),
    ).fetchall()
    if not rows:
        return 0
    refund = sum(int(row[1]) for row in rows)
    c.execute(
        """UPDATE prediction_scores SET score=score+?,returned=returned+?,updated_at=?
           WHERE group_id=? AND user_id=?""",
        (refund, refund, now, group_id, user_id),
    )
    c.execute(
        """UPDATE prediction_bets SET status='cancelled',score_delta=0,
           settled_at=?,updated_at=?
           WHERE group_id=? AND user_id=? AND target_account_id=? AND status='open'""",
        (now, now, group_id, user_id, account_id),
    )
    return refund


def bind_prediction_player(group_id, user_id, user_name, account_id, nickname):
    now = int(time.time())
    with conn:
        refunded = _cancel_open_self_bets(group_id, user_id, account_id, now)
        c.execute("DELETE FROM prediction_player_links WHERE group_id=? AND (user_id=? OR account_id=?)",
                  (int(group_id), int(user_id), int(account_id)))
        c.execute("INSERT INTO prediction_player_links VALUES (?,?,?,?,?,?)",
                  (int(group_id), int(user_id), user_name, int(account_id), nickname, now))
    return refunded


def reward_bound_players(group_id, match_id, match_rows, amount=50):
    now = int(time.time())
    rewards = []
    with conn:
        for row in match_rows:
            link = c.execute(
                """SELECT user_id,user_name FROM prediction_player_links
                   WHERE group_id=? AND account_id=?""",
                (int(group_id), int(row['account_id'])),
            ).fetchone()
            if not link:
                continue
            user_id, user_name = link
            c.execute(
                """INSERT OR IGNORE INTO prediction_game_rewards VALUES (?,?,?,?,?,?)""",
                (int(group_id), int(user_id), int(row['account_id']), int(match_id), int(amount), now),
            )
            if not c.rowcount:
                continue
            c.execute(
                """INSERT INTO prediction_scores
                   (group_id,user_id,user_name,score,game_earned,updated_at)
                   VALUES (?,?,?,1000+?,?,?)
                   ON CONFLICT(group_id,user_id) DO UPDATE SET
                     user_name=excluded.user_name,score=prediction_scores.score+?,
                     game_earned=prediction_scores.game_earned+?,updated_at=excluded.updated_at""",
                (int(group_id), int(user_id), user_name, int(amount), int(amount), now,
                 int(amount), int(amount)),
            )
            rewards.append({'user_id': user_id, 'user_name': user_name, 'amount': int(amount)})
    return rewards


def get_match_outbox_status(match_id):
    row = c.execute(
        "SELECT status FROM match_outbox WHERE match_id=?",
        (match_id,)
    ).fetchone()
    return row[0] if row else None


def get_match_outbox(match_id):
    row = c.execute(
        "SELECT status, payload, player_ids FROM match_outbox WHERE match_id=?",
        (match_id,)
    ).fetchone()
    if not row:
        return None
    return {
        'status': row[0],
        'payload': row[1],
        'player_ids': json.loads(row[2]),
    }


def enqueue_match(match_id, payload, player_ids):
    """Insert or refresh a pending match while preserving all known players."""
    now = int(time.time())
    row = c.execute(
        "SELECT status, player_ids FROM match_outbox WHERE match_id=?",
        (match_id,)
    ).fetchone()
    if row and row[0] == 'sent':
        return False

    existing_ids = json.loads(row[1]) if row else []
    merged_ids = sorted(set(existing_ids).union(int(i) for i in player_ids))
    if row:
        c.execute(
            """UPDATE match_outbox
               SET payload=?, player_ids=?, status='pending', last_error=NULL,
                   updated_at=?
               WHERE match_id=?""",
            (payload, json.dumps(merged_ids), now, match_id)
        )
    else:
        c.execute(
            """INSERT INTO match_outbox
               (match_id, payload, player_ids, status, created_at, updated_at)
               VALUES (?, ?, ?, 'pending', ?, ?)""",
            (match_id, payload, json.dumps(merged_ids), now, now)
        )
    conn.commit()
    return True


def get_pending_matches(limit=20):
    rows = c.execute(
        """SELECT match_id, payload, player_ids, attempts
           FROM match_outbox
           WHERE status='pending' AND next_attempt_at<=?
           ORDER BY created_at ASC
           LIMIT ?""",
        (int(time.time()), limit)
    ).fetchall()
    return [
        {
            'match_id': row[0],
            'payload': row[1],
            'player_ids': json.loads(row[2]),
            'attempts': row[3],
        }
        for row in rows
    ]


def mark_match_attempt(match_id):
    now = int(time.time())
    c.execute(
        "UPDATE match_outbox SET attempts=attempts+1, updated_at=? WHERE match_id=?",
        (now, match_id)
    )
    conn.commit()


def mark_match_failed(match_id, error):
    now = int(time.time())
    row = c.execute(
        "SELECT attempts FROM match_outbox WHERE match_id=?",
        (match_id,)
    ).fetchone()
    attempts = row[0] if row else 1
    retry_delay = min(300, 15 * (2 ** min(attempts - 1, 5)))
    c.execute(
        """UPDATE match_outbox
           SET status='pending', last_error=?, next_attempt_at=?, updated_at=?
           WHERE match_id=?""",
        (str(error)[:1000], now + retry_delay, now, match_id)
    )
    conn.commit()


def mark_match_sent(match_id, message_id):
    """Atomically mark delivery complete and advance all associated players."""
    row = c.execute(
        "SELECT player_ids FROM match_outbox WHERE match_id=?",
        (match_id,)
    ).fetchone()
    if not row:
        return []

    player_ids = json.loads(row[0])
    now = int(time.time())
    with conn:
        c.execute(
            """UPDATE match_outbox
               SET status='sent', message_id=?, last_error=NULL, updated_at=?, sent_at=?
               WHERE match_id=?""",
            (message_id, now, now, match_id)
        )
        for player_id in player_ids:
            current = c.execute(
                "SELECT last_DOTA2_match_ID FROM playerInfo WHERE short_steamID=?",
                (player_id,),
            ).fetchone()
            if not current or current[0] is None or int(match_id) > int(current[0]):
                c.execute(
                    "UPDATE playerInfo SET last_DOTA2_match_ID=? WHERE short_steamID=?",
                    (match_id, player_id),
                )
    return player_ids


def acknowledge_sent_match(match_id, player_ids):
    with conn:
        for player_id in player_ids:
            current = c.execute(
                "SELECT last_DOTA2_match_ID FROM playerInfo WHERE short_steamID=?",
                (int(player_id),),
            ).fetchone()
            if not current or current[0] is None or int(match_id) > int(current[0]):
                c.execute(
                    "UPDATE playerInfo SET last_DOTA2_match_ID=? WHERE short_steamID=?",
                    (match_id, int(player_id)),
                )


def get_outbox_counts():
    return dict(c.execute(
        "SELECT status, COUNT(*) FROM match_outbox GROUP BY status"
    ).fetchall())


def get_player_count():
    return c.execute("SELECT COUNT(*) FROM playerInfo").fetchone()[0]


def get_DOTA2_match_ID(short_steamID):
    row = c.execute(
        "SELECT last_DOTA2_match_ID FROM playerInfo WHERE short_steamID=?",
        (short_steamID,)
    ).fetchone()
    return row[0] if row else None
