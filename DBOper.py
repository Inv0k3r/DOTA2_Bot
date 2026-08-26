#!/usr/bin/python
# -*- coding: UTF-8 -*-
import json
import math
import os
import sqlite3
import time
from pathlib import Path

import config
from player import Player, PLAYER_LIST


def _next_local_midnight(timestamp):
    """Return the first local 00:00 strictly after timestamp's calendar day."""
    local = time.localtime(int(timestamp))
    return int(time.mktime((
        local.tm_year, local.tm_mon, local.tm_mday + 1,
        0, 0, 0, 0, 0, -1,
    )))

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
    """CREATE TABLE IF NOT EXISTS removed_players (
        short_steamID INTEGER PRIMARY KEY,
        deleted_at INTEGER NOT NULL
    )"""
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
        cancel_reason TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        settled_at INTEGER
    )"""
)
c.execute("DROP INDEX IF EXISTS idx_prediction_bets_open")
c.execute(
    "CREATE INDEX IF NOT EXISTS idx_prediction_bets_user_status "
    "ON prediction_bets(group_id,user_id,target_account_id,status)"
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
        checkin_earned INTEGER NOT NULL DEFAULT 0,
        commission_earned INTEGER NOT NULL DEFAULT 0,
        transfer_sent INTEGER NOT NULL DEFAULT 0,
        transfer_received INTEGER NOT NULL DEFAULT 0,
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
    """CREATE TABLE IF NOT EXISTS prediction_daily_checkins (
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        checkin_date TEXT NOT NULL,
        amount INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (group_id,user_id,checkin_date)
    )"""
)
c.execute(
    """CREATE TABLE IF NOT EXISTS prediction_commissions (
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        account_id INTEGER NOT NULL,
        match_id INTEGER NOT NULL,
        opposition_stake INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (group_id,user_id,match_id,account_id)
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
c.execute(
    """CREATE TABLE IF NOT EXISTS prediction_loans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        user_name TEXT NOT NULL,
        principal INTEGER NOT NULL,
        interest INTEGER NOT NULL,
        total_due INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        borrowed_at INTEGER NOT NULL,
        due_at INTEGER NOT NULL,
        repaid_at INTEGER,
        defaulted_at INTEGER
    )"""
)
c.execute(
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_prediction_loans_open "
    "ON prediction_loans(group_id,user_id) WHERE status='open'"
)
c.execute(
    "CREATE INDEX IF NOT EXISTS idx_prediction_loans_due "
    "ON prediction_loans(status,due_at)"
)
c.execute(
    """CREATE TABLE IF NOT EXISTS prediction_deaths (
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        death_until INTEGER NOT NULL,
        reason TEXT NOT NULL,
        loan_id INTEGER,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (group_id,user_id)
    )"""
)
c.execute(
    """CREATE TABLE IF NOT EXISTS prediction_revival_notifications (
        loan_id INTEGER PRIMARY KEY,
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        user_name TEXT NOT NULL,
        revive_at INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        created_at INTEGER NOT NULL,
        sent_at INTEGER
    )"""
)
c.execute(
    """CREATE TABLE IF NOT EXISTS prediction_transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        sender_name TEXT NOT NULL,
        recipient_id INTEGER NOT NULL,
        recipient_name TEXT NOT NULL,
        amount INTEGER NOT NULL,
        source_message_id INTEGER,
        created_at INTEGER NOT NULL
    )"""
)
c.execute(
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_prediction_transfer_message "
    "ON prediction_transfers(group_id,source_message_id) WHERE source_message_id IS NOT NULL"
)
c.execute(
    "CREATE INDEX IF NOT EXISTS idx_prediction_revival_due "
    "ON prediction_revival_notifications(status,revive_at,next_attempt_at)"
)
# Migrate already-active three-day deaths to the first midnight after their
# original loan deadline, and give them the same durable notification path.
legacy_deaths = c.execute(
    """SELECT d.group_id,d.user_id,d.loan_id,d.death_until,d.created_at,
              COALESCE(l.user_name,s.user_name,CAST(d.user_id AS TEXT)),l.due_at
       FROM prediction_deaths d
       LEFT JOIN prediction_loans l ON l.id=d.loan_id
       LEFT JOIN prediction_scores s ON s.group_id=d.group_id AND s.user_id=d.user_id"""
).fetchall()
for group_id, user_id, loan_id, old_until, created_at, user_name, due_at in legacy_deaths:
    if loan_id is None:
        continue
    midnight = _next_local_midnight(due_at if due_at is not None else created_at)
    revive_at = min(int(old_until), midnight)
    c.execute(
        "UPDATE prediction_deaths SET death_until=? WHERE group_id=? AND user_id=?",
        (revive_at, int(group_id), int(user_id)),
    )
    c.execute(
        """INSERT OR IGNORE INTO prediction_revival_notifications
           (loan_id,group_id,user_id,user_name,revive_at,status,created_at)
           VALUES (?,?,?,?,?,'pending',?)""",
        (int(loan_id), int(group_id), int(user_id), user_name,
         revive_at, int(created_at)),
    )
c.execute(
    """DELETE FROM prediction_game_rewards WHERE rowid NOT IN (
           SELECT MAX(rowid) FROM prediction_game_rewards
           GROUP BY group_id,account_id,match_id
       )"""
)
c.execute(
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_prediction_game_reward_account
       ON prediction_game_rewards(group_id,account_id,match_id)"""
)
bet_columns = {row[1] for row in c.execute("PRAGMA table_info(prediction_bets)").fetchall()}
if 'stake' not in bet_columns:
    c.execute("ALTER TABLE prediction_bets ADD COLUMN stake INTEGER NOT NULL DEFAULT 0")
if 'odds' not in bet_columns:
    c.execute("ALTER TABLE prediction_bets ADD COLUMN odds REAL NOT NULL DEFAULT 2.0")
if 'cancel_reason' not in bet_columns:
    c.execute("ALTER TABLE prediction_bets ADD COLUMN cancel_reason TEXT")
score_columns = {row[1] for row in c.execute("PRAGMA table_info(prediction_scores)").fetchall()}
for column in ('wagered', 'returned', 'game_earned', 'checkin_earned',
               'commission_earned', 'transfer_sent', 'transfer_received'):
    if column not in score_columns:
        c.execute("ALTER TABLE prediction_scores ADD COLUMN {} INTEGER NOT NULL DEFAULT 0".format(column))
link_columns = {
    row[1] for row in c.execute("PRAGMA table_info(prediction_player_links)").fetchall()
}
if link_columns:
    # Old experimental databases did not always have the one-to-one constraints.
    # Keep the newest binding on each side before creating durable unique indexes.
    c.execute(
        """DELETE FROM prediction_player_links WHERE rowid NOT IN (
               SELECT MAX(rowid) FROM prediction_player_links GROUP BY group_id,user_id
           )"""
    )
    c.execute(
        """DELETE FROM prediction_player_links WHERE rowid NOT IN (
               SELECT MAX(rowid) FROM prediction_player_links GROUP BY group_id,account_id
           )"""
    )
    c.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_prediction_links_user
           ON prediction_player_links(group_id,user_id)"""
    )
    c.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_prediction_links_account
           ON prediction_player_links(group_id,account_id)"""
    )
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
    # A deletion tombstone prevents PLAYER_LIST_JSON defaults from silently
    # recreating a player on the next service restart.
    return c.execute(
        """SELECT 1 FROM playerInfo WHERE short_steamID=?
           UNION ALL
           SELECT 1 FROM removed_players WHERE short_steamID=? LIMIT 1""",
        (int(short_steamID), int(short_steamID)),
    ).fetchone() is not None

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
    with conn:
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
        c.execute(
            "DELETE FROM removed_players WHERE short_steamID=?",
            (int(short_steamID),),
        )
    return row[0] if row else last_DOTA2_match_ID


def disable_player(short_steamID):
    c.execute(
        "UPDATE playerInfo SET enabled=0 WHERE short_steamID=?",
        (short_steamID,),
    )
    changed = c.rowcount > 0
    conn.commit()
    return changed


def delete_player_data(short_steamID):
    """Permanently remove data keyed to one tracked Steam account.

    Open bets are refunded before their rows are removed. Pending reports that
    mention the player are discarded so the next poll can rebuild them for any
    remaining participants. Sent shared outbox rows keep their delivery marker,
    but no longer retain the deleted account ID.
    """
    account_id = int(short_steamID)
    now = int(time.time())
    refunded = []
    deleted = {}
    with conn:
        groups_with_open_bets = c.execute(
            """SELECT DISTINCT group_id FROM prediction_bets
               WHERE target_account_id=? AND status='open'""",
            (account_id,),
        ).fetchall()
        for (group_id,) in groups_with_open_bets:
            refunded.extend(_cancel_open_prediction_bets(
                group_id, account_id, 'player_removed', now=now,
            ))

        for table, column in (
            ('match_stats', 'account_id'),
            ('player_aliases', 'account_id'),
            ('prediction_bets', 'target_account_id'),
            ('prediction_player_links', 'account_id'),
            ('prediction_commissions', 'account_id'),
            ('prediction_game_rewards', 'account_id'),
        ):
            c.execute(
                'DELETE FROM {} WHERE {}=?'.format(table, column),
                (account_id,),
            )
            deleted[table] = c.rowcount

        combo_rows = c.execute(
            "SELECT group_id,player_ids FROM combo_names"
        ).fetchall()
        combo_keys = []
        for group_id, player_ids in combo_rows:
            try:
                contains_player = account_id in {
                    int(value) for value in json.loads(player_ids)
                }
            except (TypeError, ValueError, json.JSONDecodeError):
                contains_player = False
            if contains_player:
                combo_keys.append((int(group_id), player_ids))
        c.executemany(
            "DELETE FROM combo_names WHERE group_id=? AND player_ids=?",
            combo_keys,
        )
        deleted['combo_names'] = len(combo_keys)

        outbox_rows = c.execute(
            "SELECT match_id,player_ids,status FROM match_outbox"
        ).fetchall()
        touched_outbox = 0
        for match_id, player_ids, status in outbox_rows:
            try:
                ids = [int(value) for value in json.loads(player_ids)]
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if account_id not in ids:
                continue
            remaining = [value for value in ids if value != account_id]
            if status == 'pending' or not remaining:
                c.execute("DELETE FROM match_outbox WHERE match_id=?", (match_id,))
            else:
                c.execute(
                    "UPDATE match_outbox SET player_ids=?,updated_at=? WHERE match_id=?",
                    (json.dumps(sorted(set(remaining))), now, int(match_id)),
                )
            touched_outbox += 1
        deleted['match_outbox'] = touched_outbox

        c.execute("DELETE FROM playerInfo WHERE short_steamID=?", (account_id,))
        deleted['playerInfo'] = c.rowcount
        c.execute(
            "INSERT OR REPLACE INTO removed_players(short_steamID,deleted_at) VALUES (?,?)",
            (account_id, now),
        )
    return {
        'deleted': deleted,
        'refunded_bets': len(refunded),
        'refunded_score': sum(item['stake'] for item in refunded),
    }


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


def _prediction_recent_form(group_id, target_account_id, exclude_match_id=None):
    conditions = ['group_id=?', 'account_id=?']
    params = [int(group_id), int(target_account_id)]
    if exclude_match_id is not None:
        conditions.append('match_id<>?')
        params.append(int(exclude_match_id))
    params.append(int(config.PREDICTION_ODDS_HISTORY_MATCHES))
    results = c.execute(
        """SELECT won FROM match_stats WHERE {}
           ORDER BY start_time DESC,match_id DESC LIMIT ?""".format(
            ' AND '.join(conditions)
        ),
        tuple(params),
    ).fetchall()
    # This is deliberately an entertainment-oriented line: the newest games
    # matter much more, while only a light 50/50 prior tempers tiny samples.
    weighted_wins = 0.0
    total_weight = 0.0
    for index, (won,) in enumerate(results):
        weight = config.PREDICTION_ODDS_RECENCY_DECAY ** index
        total_weight += weight
        weighted_wins += weight * (1 if won else 0)
    prior_weight = config.PREDICTION_ODDS_PRIOR_WEIGHT
    probability = (prior_weight * 0.5 + weighted_wins) / (
        prior_weight + total_weight
    )
    return {
        'games': len(results),
        'wins': sum(1 for (won,) in results if won),
        'win_probability': min(
            1.0 - config.PREDICTION_ODDS_PROBABILITY_FLOOR,
            max(config.PREDICTION_ODDS_PROBABILITY_FLOOR, probability),
        ),
    }


def _prediction_market(group_id, target_account_id, bets=None,
                       exclude_match_id=None):
    form = _prediction_recent_form(
        group_id, target_account_id, exclude_match_id=exclude_match_id,
    )
    if bets is None:
        bets = c.execute(
            """SELECT prediction,stake FROM prediction_bets
               WHERE group_id=? AND target_account_id=? AND status='open'""",
            (int(group_id), int(target_account_id)),
        ).fetchall()
    win_pool = sum(int(stake) for prediction, stake in bets if int(prediction))
    lose_pool = sum(int(stake) for prediction, stake in bets if not int(prediction))
    liquidity = float(config.PREDICTION_MARKET_LIQUIDITY)
    pool_total = win_pool + lose_pool
    if pool_total:
        # Stakes only tilt the recent-form price. Even a very large one-sided
        # pool cannot outweigh the player's actual recent performance.
        natural_influence = pool_total / (liquidity + pool_total)
        pool_influence = min(
            config.PREDICTION_MARKET_MAX_POOL_INFLUENCE, natural_influence
        )
        pool_win_probability = win_pool / pool_total
        market_win_probability = (
            form['win_probability'] * (1.0 - pool_influence)
            + pool_win_probability * pool_influence
        )
    else:
        market_win_probability = form['win_probability']
    market_win_probability = min(0.95, max(0.05, market_win_probability))

    def offered(probability):
        raw = config.PREDICTION_MARKET_PAYOUT_RATE / probability
        return round(min(
            config.PREDICTION_MARKET_MAX_ODDS,
            max(config.PREDICTION_MARKET_MIN_ODDS, raw),
        ), 2)

    return {
        'games': form['games'], 'wins': form['wins'],
        'base_win_probability': form['win_probability'],
        'pool_influence': pool_influence if pool_total else 0.0,
        'win_pool': win_pool, 'lose_pool': lose_pool,
        'market_active': bool(win_pool or lose_pool),
        'win': offered(market_win_probability),
        'lose': offered(1.0 - market_win_probability),
    }


def get_prediction_odds(group_id, target_account_id):
    return _prediction_market(group_id, target_account_id)


def place_prediction_bet(group_id, user_id, user_name, target_account_id,
                         target_nickname, prediction, stake, odds, after_match_id):
    """Create an independent bet and permanently lock the offered odds."""
    now = int(time.time())
    group_id = int(group_id)
    user_id = int(user_id)
    target_account_id = int(target_account_id)
    prediction = 1 if prediction else 0
    stake = int(stake)
    odds = float(odds)
    if stake <= 0:
        raise ValueError('下注点数必须大于 0')
    if not 1.0 <= odds <= 100.0:
        raise ValueError('赔率无效，请重新查询后下注')
    enforce_prediction_loan_for_user(group_id, user_id, now)
    with conn:
        _raise_if_prediction_dead(group_id, user_id, now)
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
        balance = c.execute(
            "SELECT score FROM prediction_scores WHERE group_id=? AND user_id=?",
            (group_id, user_id),
        ).fetchone()[0]
        if balance < stake:
            raise ValueError('余额不足：当前可用 {} 点'.format(balance))
        c.execute(
            """INSERT INTO prediction_bets
               (group_id,user_id,user_name,target_account_id,target_nickname,prediction,
                stake,odds,after_match_id,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,'open',?,?)""",
            (group_id, user_id, user_name, target_account_id,
             target_nickname, prediction, stake, odds, int(after_match_id), now, now),
        )
        bet_id = c.lastrowid
        c.execute(
            """UPDATE prediction_scores
               SET score=?,wagered=wagered+?,updated_at=?
               WHERE group_id=? AND user_id=?""",
            (balance - stake, stake, now, group_id, user_id),
        )
        market = _prediction_market(group_id, target_account_id)
    return {
        'id': bet_id, 'balance': balance - stake,
        'odds': odds,
        'market': market,
    }


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
        """SELECT user_name,score,wins,losses,wagered,returned,game_earned,
                  checkin_earned,commission_earned,transfer_sent,transfer_received
           FROM prediction_scores
           WHERE group_id=? AND user_id=?""",
        (int(group_id), int(user_id)),
    ).fetchone()
    keys = ('user_name','score','wins','losses','wagered','returned','game_earned',
            'checkin_earned','commission_earned','transfer_sent','transfer_received')
    return dict(zip(keys, row)) if row else {
        'user_name': str(user_id), 'score': 1000, 'wins': 0, 'losses': 0,
        'wagered': 0, 'returned': 0, 'game_earned': 0, 'checkin_earned': 0,
        'commission_earned': 0, 'transfer_sent': 0, 'transfer_received': 0,
    }


def transfer_prediction_score(group_id, sender_id, sender_name, recipient_id,
                              amount, source_message_id=None, now=None):
    """Atomically transfer ordinary prediction points with event deduplication."""
    now = int(time.time()) if now is None else int(now)
    group_id = int(group_id)
    sender_id = int(sender_id)
    recipient_id = int(recipient_id)
    amount = int(amount)
    source_message_id = (
        int(source_message_id) if source_message_id is not None else None
    )
    if sender_id == recipient_id:
        raise ValueError('不能给自己赠送积分')
    if amount <= 0 or amount > int(config.PREDICTION_TRANSFER_MAX):
        raise ValueError('赠送点数必须在 1 到 {} 之间'.format(
            config.PREDICTION_TRANSFER_MAX
        ))
    enforce_prediction_loan_for_user(group_id, sender_id, now)
    with conn:
        _raise_if_prediction_dead(group_id, sender_id, now)
        if c.execute(
            """SELECT 1 FROM prediction_loans
               WHERE group_id=? AND user_id=? AND status='open' LIMIT 1""",
            (group_id, sender_id),
        ).fetchone():
            raise ValueError('有贷款未还时不能赠送积分，请先还款')
        if source_message_id is not None:
            existing = c.execute(
                """SELECT id,recipient_id,recipient_name,amount
                   FROM prediction_transfers
                   WHERE group_id=? AND source_message_id=?""",
                (group_id, source_message_id),
            ).fetchone()
            if existing:
                balance = get_prediction_score(group_id, sender_id)['score']
                return {
                    'id': int(existing[0]), 'recipient_id': int(existing[1]),
                    'recipient_name': existing[2], 'amount': int(existing[3]),
                    'balance': int(balance), 'duplicate': True,
                }
        c.execute(
            """INSERT INTO prediction_scores(group_id,user_id,user_name,score,updated_at)
               VALUES (?,?,?,1000,?) ON CONFLICT(group_id,user_id) DO UPDATE SET
               user_name=excluded.user_name,updated_at=excluded.updated_at""",
            (group_id, sender_id, sender_name, now),
        )
        sender_balance = c.execute(
            "SELECT score FROM prediction_scores WHERE group_id=? AND user_id=?",
            (group_id, sender_id),
        ).fetchone()[0]
        if int(sender_balance) < amount:
            raise ValueError('余额不足：当前可用 {} 点'.format(sender_balance))
        recipient_row = c.execute(
            """SELECT user_name,score FROM prediction_scores
               WHERE group_id=? AND user_id=?""",
            (group_id, recipient_id),
        ).fetchone()
        recipient_name = recipient_row[0] if recipient_row else str(recipient_id)
        c.execute(
            """UPDATE prediction_scores SET score=score-?,transfer_sent=transfer_sent+?,
               updated_at=? WHERE group_id=? AND user_id=?""",
            (amount, amount, now, group_id, sender_id),
        )
        c.execute(
            """INSERT INTO prediction_scores
               (group_id,user_id,user_name,score,transfer_received,updated_at)
               VALUES (?,?,?,1000+?,?,?)
               ON CONFLICT(group_id,user_id) DO UPDATE SET
                 score=prediction_scores.score+?,
                 transfer_received=prediction_scores.transfer_received+?,
                 updated_at=excluded.updated_at""",
            (group_id, recipient_id, recipient_name, amount, amount, now,
             amount, amount),
        )
        c.execute(
            """INSERT INTO prediction_transfers
               (group_id,sender_id,sender_name,recipient_id,recipient_name,
                amount,source_message_id,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (group_id, sender_id, sender_name, recipient_id, recipient_name,
             amount, source_message_id, now),
        )
        transfer_id = c.lastrowid
        recipient_balance = get_prediction_score(group_id, recipient_id)['score']
    return {
        'id': int(transfer_id), 'recipient_id': recipient_id,
        'recipient_name': recipient_name, 'amount': amount,
        'balance': int(sender_balance) - amount,
        'recipient_balance': int(recipient_balance), 'duplicate': False,
    }


def _format_remaining(seconds):
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = (remainder + 59) // 60
    if days:
        return '{}天{}小时'.format(days, hours)
    if hours:
        return '{}小时{}分钟'.format(hours, minutes)
    return '{}分钟'.format(max(1, minutes))


def _active_prediction_death(group_id, user_id, now):
    row = c.execute(
        "SELECT death_until,reason,loan_id FROM prediction_deaths WHERE group_id=? AND user_id=?",
        (int(group_id), int(user_id)),
    ).fetchone()
    if not row:
        return None
    if int(row[0]) <= int(now):
        c.execute(
            "DELETE FROM prediction_deaths WHERE group_id=? AND user_id=?",
            (int(group_id), int(user_id)),
        )
        return None
    return {'death_until': int(row[0]), 'reason': row[1], 'loan_id': row[2]}


def _raise_if_prediction_dead(group_id, user_id, now):
    death = _active_prediction_death(group_id, user_id, now)
    if death:
        raise ValueError(
            '竞猜账号已死亡，{}后自动复活'.format(
                _format_remaining(death['death_until'] - int(now))
            )
        )


def _cancel_user_open_bets_for_default(group_id, user_id, loan_id, now):
    """Cancel all staked assets before bankruptcy, without returning them."""
    rows = c.execute(
        "SELECT id FROM prediction_bets WHERE group_id=? AND user_id=? AND status='open'",
        (int(group_id), int(user_id)),
    ).fetchall()
    for (bet_id,) in rows:
        c.execute(
            """UPDATE prediction_bets SET status='cancelled',score_delta=0,
               cancel_reason=?,settled_at=?,updated_at=? WHERE id=? AND status='open'""",
            ('loan_default:{}'.format(int(loan_id)), int(now), int(now), int(bet_id)),
        )
    return len(rows)


def _enforce_prediction_loan_default(group_id, user_id, now):
    row = c.execute(
        """SELECT id,user_name,principal,interest,total_due,due_at
           FROM prediction_loans WHERE group_id=? AND user_id=? AND status='open'
           LIMIT 1""",
        (int(group_id), int(user_id)),
    ).fetchone()
    if not row or int(row[5]) > int(now):
        return None
    loan_id = int(row[0])
    c.execute(
        """UPDATE prediction_loans SET status='defaulted',defaulted_at=?
           WHERE id=? AND status='open'""",
        (int(now), loan_id),
    )
    if not c.rowcount:
        return None
    cancelled = _cancel_user_open_bets_for_default(group_id, user_id, loan_id, now)
    c.execute(
        """UPDATE prediction_scores SET score=0,updated_at=?
           WHERE group_id=? AND user_id=?""",
        (int(now), int(group_id), int(user_id)),
    )
    death_until = _next_local_midnight(row[5])
    c.execute(
        """INSERT INTO prediction_deaths
           (group_id,user_id,death_until,reason,loan_id,created_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(group_id,user_id) DO UPDATE SET
             death_until=MAX(prediction_deaths.death_until,excluded.death_until),
             reason=excluded.reason,loan_id=excluded.loan_id,created_at=excluded.created_at""",
        (int(group_id), int(user_id), death_until, 'loan_default', loan_id, int(now)),
    )
    c.execute(
        """INSERT OR IGNORE INTO prediction_revival_notifications
           (loan_id,group_id,user_id,user_name,revive_at,status,created_at)
           VALUES (?,?,?,?,?,'pending',?)""",
        (loan_id, int(group_id), int(user_id), row[1], death_until, int(now)),
    )
    return {
        'loan_id': loan_id, 'user_id': int(user_id), 'user_name': row[1],
        'principal': int(row[2]), 'interest': int(row[3]),
        'total_due': int(row[4]), 'death_until': death_until,
        'cancelled_bets': cancelled,
    }


def enforce_overdue_prediction_loans(now=None):
    """Apply overdue defaults globally; each loan can transition only once."""
    now = int(time.time()) if now is None else int(now)
    rows = c.execute(
        "SELECT group_id,user_id FROM prediction_loans WHERE status='open' AND due_at<=?",
        (now,),
    ).fetchall()
    events = []
    with conn:
        for group_id, user_id in rows:
            event = _enforce_prediction_loan_default(group_id, user_id, now)
            if event:
                events.append(event)
    return events


def get_due_prediction_revivals(now=None, limit=20):
    now = int(time.time()) if now is None else int(now)
    rows = c.execute(
        """SELECT loan_id,group_id,user_id,user_name,revive_at,attempts
           FROM prediction_revival_notifications
           WHERE status='pending' AND revive_at<=? AND next_attempt_at<=?
           ORDER BY revive_at,loan_id LIMIT ?""",
        (now, now, int(limit)),
    ).fetchall()
    keys = ('loan_id','group_id','user_id','user_name','revive_at','attempts')
    return [dict(zip(keys, row)) for row in rows]


def mark_prediction_revival_sent(loan_id, now=None):
    now = int(time.time()) if now is None else int(now)
    with conn:
        c.execute(
            """UPDATE prediction_revival_notifications
               SET status='sent',sent_at=?,last_error=NULL
               WHERE loan_id=? AND status='pending'""",
            (now, int(loan_id)),
        )
        changed = bool(c.rowcount)
        if changed:
            c.execute(
                "DELETE FROM prediction_deaths WHERE loan_id=? AND death_until<=?",
                (int(loan_id), now),
            )
        return changed


def mark_prediction_revival_failed(loan_id, error, now=None):
    now = int(time.time()) if now is None else int(now)
    row = c.execute(
        "SELECT attempts FROM prediction_revival_notifications WHERE loan_id=? AND status='pending'",
        (int(loan_id),),
    ).fetchone()
    if not row:
        return False
    attempts = int(row[0]) + 1
    delay = min(3600, 30 * (2 ** min(attempts - 1, 7)))
    with conn:
        c.execute(
            """UPDATE prediction_revival_notifications
               SET attempts=?,next_attempt_at=?,last_error=?
               WHERE loan_id=? AND status='pending'""",
            (attempts, now + delay, str(error)[:500], int(loan_id)),
        )
        return bool(c.rowcount)


def enforce_prediction_loan_for_user(group_id, user_id, now=None):
    now = int(time.time()) if now is None else int(now)
    with conn:
        return _enforce_prediction_loan_default(group_id, user_id, now)


def create_prediction_loan(group_id, user_id, user_name, principal, now=None):
    now = int(time.time()) if now is None else int(now)
    principal = int(principal)
    if principal < config.PREDICTION_LOAN_MIN or principal > config.PREDICTION_LOAN_MAX:
        raise ValueError(
            '贷款额度必须在 {}–{} 点之间'.format(
                config.PREDICTION_LOAN_MIN, config.PREDICTION_LOAN_MAX
            )
        )
    enforce_prediction_loan_for_user(group_id, user_id, now)
    with conn:
        _raise_if_prediction_dead(group_id, user_id, now)
        if c.execute(
            "SELECT 1 FROM prediction_loans WHERE group_id=? AND user_id=? AND status='open'",
            (int(group_id), int(user_id)),
        ).fetchone():
            raise ValueError('你还有一笔贷款未还，请先发送 @bot 还款')
        interest = int(math.ceil(principal * config.PREDICTION_LOAN_INTEREST_RATE))
        total_due = principal + interest
        due_at = now + int(config.PREDICTION_LOAN_TERM_SECONDS)
        c.execute(
            """INSERT INTO prediction_loans
               (group_id,user_id,user_name,principal,interest,total_due,status,borrowed_at,due_at)
               VALUES (?,?,?,?,?,?,'open',?,?)""",
            (int(group_id), int(user_id), user_name, principal, interest,
             total_due, now, due_at),
        )
        loan_id = c.lastrowid
        c.execute(
            """INSERT INTO prediction_scores(group_id,user_id,user_name,score,updated_at)
               VALUES (?,?,?,1000+?,?) ON CONFLICT(group_id,user_id) DO UPDATE SET
               user_name=excluded.user_name,score=prediction_scores.score+?,updated_at=?""",
            (int(group_id), int(user_id), user_name, principal, now, principal, now),
        )
        balance = get_prediction_score(group_id, user_id)['score']
    return {'id': loan_id, 'principal': principal, 'interest': interest,
            'total_due': total_due, 'due_at': due_at, 'balance': int(balance)}


def repay_prediction_loan(group_id, user_id, now=None):
    now = int(time.time()) if now is None else int(now)
    enforce_prediction_loan_for_user(group_id, user_id, now)
    with conn:
        _raise_if_prediction_dead(group_id, user_id, now)
        row = c.execute(
            """SELECT id,total_due FROM prediction_loans
               WHERE group_id=? AND user_id=? AND status='open' LIMIT 1""",
            (int(group_id), int(user_id)),
        ).fetchone()
        if not row:
            raise ValueError('你目前没有待还贷款')
        balance = get_prediction_score(group_id, user_id)['score']
        if int(balance) < int(row[1]):
            raise ValueError('余额不足：需还 {} 点，当前只有 {} 点'.format(row[1], balance))
        c.execute(
            "UPDATE prediction_loans SET status='repaid',repaid_at=? WHERE id=? AND status='open'",
            (now, int(row[0])),
        )
        c.execute(
            "UPDATE prediction_scores SET score=score-?,updated_at=? WHERE group_id=? AND user_id=?",
            (int(row[1]), now, int(group_id), int(user_id)),
        )
        remaining = int(balance) - int(row[1])
    return {'id': int(row[0]), 'paid': int(row[1]), 'balance': remaining}


def get_prediction_loan_status(group_id, user_id, now=None):
    now = int(time.time()) if now is None else int(now)
    with conn:
        _enforce_prediction_loan_default(group_id, user_id, now)
        death = _active_prediction_death(group_id, user_id, now)
        row = c.execute(
            """SELECT id,principal,interest,total_due,borrowed_at,due_at,status
               FROM prediction_loans WHERE group_id=? AND user_id=?
               ORDER BY id DESC LIMIT 1""",
            (int(group_id), int(user_id)),
        ).fetchone()
    keys = ('id','principal','interest','total_due','borrowed_at','due_at','status')
    return {'loan': dict(zip(keys, row)) if row else None, 'death': death,
            'now': now}


def get_prediction_leaderboard(group_id, limit=10):
    rows = c.execute(
        """SELECT user_id,user_name,score,wins,losses,wagered,returned,game_earned,
                  checkin_earned,commission_earned
           FROM prediction_scores
           WHERE group_id=? ORDER BY score DESC,wins DESC,updated_at ASC LIMIT ?""",
        (int(group_id), int(limit)),
    ).fetchall()
    keys = ('user_id','user_name','score','wins','losses','wagered','returned',
            'game_earned','checkin_earned','commission_earned')
    return [dict(zip(keys, row)) for row in rows]


def claim_prediction_daily_checkin(group_id, user_id, user_name, now=None):
    """Award the ordinary prediction balance once per local calendar day."""
    now = int(time.time()) if now is None else int(now)
    checkin_date = time.strftime('%Y-%m-%d', time.localtime(now))
    amount = int(config.PREDICTION_DAILY_CHECKIN_REWARD)
    enforce_prediction_loan_for_user(group_id, user_id, now)
    with conn:
        _raise_if_prediction_dead(group_id, user_id, now)
        c.execute(
            """INSERT OR IGNORE INTO prediction_daily_checkins
               (group_id,user_id,checkin_date,amount,created_at) VALUES (?,?,?,?,?)""",
            (int(group_id), int(user_id), checkin_date, amount, now),
        )
        claimed = bool(c.rowcount)
        if claimed:
            c.execute(
                """INSERT INTO prediction_scores
                   (group_id,user_id,user_name,score,checkin_earned,updated_at)
                   VALUES (?,?,?,1000+?,?,?)
                   ON CONFLICT(group_id,user_id) DO UPDATE SET
                     user_name=excluded.user_name,
                     score=prediction_scores.score+?,
                     checkin_earned=prediction_scores.checkin_earned+?,
                     updated_at=excluded.updated_at""",
                (int(group_id), int(user_id), user_name, amount, amount, now,
                 amount, amount),
            )
        balance = get_prediction_score(group_id, user_id)['score']
    return {
        'claimed': claimed, 'amount': amount if claimed else 0,
        'balance': int(balance), 'date': checkin_date,
    }


def _cancel_open_prediction_bets(group_id, account_id, reason, now=None,
                                 user_id=None, before_match_id=None,
                                 created_before=None, settled_match_id=None):
    """Atomically cancel matching open bets and refund every accepted cancellation."""
    now = int(time.time()) if now is None else int(now)
    group_id = int(group_id)
    account_id = int(account_id)
    conditions = ["group_id=?", "target_account_id=?", "status='open'"]
    params = [group_id, account_id]
    if user_id is not None:
        conditions.append('user_id=?')
        params.append(int(user_id))
    if before_match_id is not None:
        conditions.append('after_match_id<?')
        params.append(int(before_match_id))
    if created_before is not None:
        conditions.append('created_at<=?')
        params.append(int(created_before))
    rows = c.execute(
        "SELECT id,user_id,user_name,stake FROM prediction_bets WHERE {} ORDER BY id".format(
            ' AND '.join(conditions)
        ),
        tuple(params),
    ).fetchall()
    cancelled = []
    for bet_id, bettor_id, user_name, stake in rows:
        c.execute(
            """UPDATE prediction_bets SET status='cancelled',settled_match_id=?,
               score_delta=0,cancel_reason=?,settled_at=?,updated_at=?
               WHERE id=? AND status='open'""",
            (int(settled_match_id) if settled_match_id is not None else None,
             reason, now, now, int(bet_id)),
        )
        if not c.rowcount:
            continue
        stake = int(stake)
        c.execute(
            """UPDATE prediction_scores SET score=score+?,returned=returned+?,updated_at=?
               WHERE group_id=? AND user_id=?""",
            (stake, stake, now, group_id, int(bettor_id)),
        )
        cancelled.append({
            'bet_id': int(bet_id), 'user_id': int(bettor_id),
            'user_name': user_name, 'stake': stake,
        })
    return cancelled


def _cancel_open_self_bets(group_id, user_id, account_id, now=None):
    """Cancel and refund open bets made by a user on their linked player."""
    cancelled = _cancel_open_prediction_bets(
        group_id, account_id, 'self_bet', now=now, user_id=user_id
    )
    return sum(item['stake'] for item in cancelled)


def _enforce_prediction_risk_controls(group_id, match_id, match_start_time,
                                      match_rows, participant_account_ids, now):
    """Void bets made by users whose bound account played in the same match."""
    group_id = int(group_id)
    match_id = int(match_id)
    participant_ids = {
        int(account_id) for account_id in (
            participant_account_ids
            if participant_account_ids is not None
            else [row['account_id'] for row in match_rows]
        )
    }
    participant_links = []
    if participant_ids:
        placeholders = ','.join('?' for _ in participant_ids)
        participant_links = c.execute(
            """SELECT user_id,account_id FROM prediction_player_links
               WHERE group_id=? AND account_id IN ({})""".format(placeholders),
            (group_id,) + tuple(sorted(participant_ids)),
        ).fetchall()

    events = []
    for match_row in match_rows:
        account_id = int(match_row['account_id'])
        nickname = match_row['nickname']
        cancelled = []
        for bettor_id, _bettor_account_id in participant_links:
            cancelled.extend(_cancel_open_prediction_bets(
                group_id, account_id, 'match_participant', now=now,
                user_id=bettor_id, before_match_id=match_id,
                created_before=match_start_time, settled_match_id=match_id,
            ))
        if cancelled:
            events.append({
                'reason': 'match_participant', 'target_account_id': account_id,
                'target_nickname': nickname, 'bet_count': len(cancelled),
                'refund': sum(item['stake'] for item in cancelled),
            })
    return events


def settle_prediction_bets(group_id, match_id, match_start_time, match_rows,
                           participant_account_ids=None, risk_events=None,
                           commissions=None):
    """Settle eligible next-match bets once; returns a summary safe for report output."""
    now = int(time.time())
    settled = []
    with conn:
        detected_risks = _enforce_prediction_risk_controls(
            group_id, match_id, match_start_time, match_rows,
            participant_account_ids, now,
        )
        if risk_events is not None:
            risk_events.extend(detected_risks)
        for match_row in match_rows:
            account_id = int(match_row['account_id'])
            actual_won = 1 if match_row['won'] else 0
            opposition_stake = 0
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
                    """UPDATE prediction_bets SET status='settled',settled_match_id=?,
                       actual_won=?,score_delta=?,cancel_reason=NULL,
                       settled_at=?,updated_at=?
                       WHERE id=? AND status='open'""",
                    (int(match_id), actual_won, profit, now, now, bet_id),
                )
                if not c.rowcount:
                    continue
                c.execute(
                    """UPDATE prediction_scores SET user_name=?,score=score+?,
                       wins=wins+?,losses=losses+?,returned=returned+?,updated_at=?
                       WHERE group_id=? AND user_id=?""",
                    (user_name, payout, 1 if correct else 0, 0 if correct else 1,
                     payout, now, int(group_id), int(user_id)),
                )
                if actual_won and not int(prediction):
                    opposition_stake += int(stake)
                settled.append({
                    'bet_id': bet_id, 'user_id': user_id, 'user_name': user_name,
                    'target_nickname': match_row['nickname'], 'prediction': prediction,
                    'actual_won': actual_won, 'correct': correct, 'stake': stake,
                    'odds': odds, 'payout': payout, 'delta': profit,
                    'score': current_score + payout,
                })
            commission_amount = int(round(
                opposition_stake * config.PREDICTION_UPSET_COMMISSION_RATE
            ))
            if not actual_won or opposition_stake <= 0 or commission_amount <= 0:
                continue
            link = c.execute(
                """SELECT user_id,user_name FROM prediction_player_links
                   WHERE group_id=? AND account_id=?""",
                (int(group_id), account_id),
            ).fetchone()
            if not link:
                continue
            linked_user_id, linked_user_name = int(link[0]), link[1]
            c.execute(
                """INSERT OR IGNORE INTO prediction_commissions
                   (group_id,user_id,account_id,match_id,opposition_stake,amount,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (int(group_id), linked_user_id, account_id, int(match_id),
                 opposition_stake, commission_amount, now),
            )
            if not c.rowcount:
                continue
            c.execute(
                """INSERT INTO prediction_scores
                   (group_id,user_id,user_name,score,commission_earned,updated_at)
                   VALUES (?,?,?,1000+?,?,?)
                   ON CONFLICT(group_id,user_id) DO UPDATE SET
                     user_name=excluded.user_name,
                     score=prediction_scores.score+?,
                     commission_earned=prediction_scores.commission_earned+?,
                     updated_at=excluded.updated_at""",
                (int(group_id), linked_user_id, linked_user_name,
                 commission_amount, commission_amount, now,
                 commission_amount, commission_amount),
            )
            if commissions is not None:
                commissions.append({
                    'user_id': linked_user_id, 'user_name': linked_user_name,
                    'target_account_id': account_id,
                    'target_nickname': match_row['nickname'],
                    'opposition_stake': opposition_stake,
                    'amount': commission_amount,
                })
    return settled


def bind_prediction_player(group_id, user_id, user_name, account_id, nickname):
    now = int(time.time())
    group_id = int(group_id)
    user_id = int(user_id)
    account_id = int(account_id)
    with conn:
        user_link = c.execute(
            """SELECT account_id,nickname FROM prediction_player_links
               WHERE group_id=? AND user_id=?""",
            (group_id, user_id),
        ).fetchone()
        if user_link and int(user_link[0]) != account_id:
            raise ValueError(
                '该 QQ 已绑定 {}，请先由管理员取消绑定'.format(user_link[1])
            )
        account_link = c.execute(
            """SELECT user_id,user_name FROM prediction_player_links
               WHERE group_id=? AND account_id=?""",
            (group_id, account_id),
        ).fetchone()
        if account_link and int(account_link[0]) != user_id:
            raise ValueError(
                '{} 已被 QQ {} 绑定，请先取消原绑定'.format(
                    nickname, account_link[0]
                )
            )
        refunded = _cancel_open_self_bets(group_id, user_id, account_id, now)
        c.execute(
            """INSERT INTO prediction_player_links
               (group_id,user_id,user_name,account_id,nickname,updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(group_id,user_id) DO UPDATE SET
                 user_name=excluded.user_name,nickname=excluded.nickname,
                 updated_at=excluded.updated_at""",
            (group_id, user_id, user_name, account_id, nickname, now),
        )
    return refunded


def unbind_prediction_player(group_id, user_id=None, account_id=None):
    if user_id is None and account_id is None:
        raise ValueError('必须指定 QQ 或游戏账号')
    conditions = ['group_id=?']
    params = [int(group_id)]
    if user_id is not None:
        conditions.append('user_id=?')
        params.append(int(user_id))
    if account_id is not None:
        conditions.append('account_id=?')
        params.append(int(account_id))
    with conn:
        row = c.execute(
            """SELECT user_id,user_name,account_id,nickname
               FROM prediction_player_links WHERE {} LIMIT 1""".format(
                ' AND '.join(conditions)
            ),
            tuple(params),
        ).fetchone()
        if not row:
            return None
        c.execute(
            """DELETE FROM prediction_player_links
               WHERE group_id=? AND user_id=? AND account_id=?""",
            (int(group_id), int(row[0]), int(row[2])),
        )
    return dict(zip(('user_id','user_name','account_id','nickname'), row))


def reward_bound_players(group_id, match_id, match_rows):
    now = int(time.time())
    rewards = []
    with conn:
        for row in match_rows:
            amount = (
                config.PREDICTION_GAME_WIN_REWARD if row.get('won')
                else config.PREDICTION_GAME_LOSS_REWARD
            )
            amount = int(amount)
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
            rewards.append({
                'user_id': user_id, 'user_name': user_name, 'amount': amount,
                'won': bool(row.get('won')),
            })
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


def enqueue_match_addendum(match_id, payload, player_ids):
    """Reopen a sent outbox row for newly discovered tracked players only."""
    now = int(time.time())
    row = c.execute(
        "SELECT status, player_ids FROM match_outbox WHERE match_id=?",
        (int(match_id),),
    ).fetchone()
    if not row or row[0] != 'sent':
        return False
    existing_ids = {int(value) for value in json.loads(row[1])}
    new_ids = {int(value) for value in player_ids} - existing_ids
    if not new_ids:
        return False
    merged_ids = sorted(existing_ids.union(new_ids))
    with conn:
        c.execute(
            """UPDATE match_outbox
               SET payload=?,player_ids=?,status='pending',attempts=0,
                   last_error=NULL,next_attempt_at=0,updated_at=?
               WHERE match_id=? AND status='sent'""",
            (payload, json.dumps(merged_ids), now, int(match_id)),
        )
    return bool(c.rowcount)


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
