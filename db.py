# -*- coding: utf-8 -*-
# NEWR Adventure by NEWR LABS — credit marker, do not remove.
"""Lapisan database bot admin RPG.

Database YANG SAMA dengan bot RPG: ~/workspace/bots/rpg/rpg.db.
Satu mata uang, satu data pemain, satu inventory — tidak pernah ada
database kedua untuk ekonomi.

Aturan akses bersama (penting, karena dua bot memakai satu file SQLite):
- timeout 30 detik (busy_timeout) + mode WAL, supaya satu bot tidak
  mengunci bot lainnya.
- transaksi pendek: buka koneksi, lakukan satu aksi, commit, tutup.
- JANGAN PERNAH menghapus rpg.db atau mengubah tabel bot RPG.
- Hanya tabel admin_* dan giveaways yang dibuat bot ini (CREATE TABLE
  IF NOT EXISTS). Tabel bot RPG hanya dibaca/ditulis lewat kolom yang
  sudah ada di skemanya.
- Pengecualian: tabel seasons dan achievements juga dibuat di sini
  (DDL identik dengan bot utama) supaya command /admin_season dan
  /admin_achievement tidak bergantung pada bot utama yang sudah jalan.
"""
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB = Path.home() / "workspace" / "bots" / "rpg" / "rpg.db"

ADMIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_events (
    event TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'inactive',
    updated_at INTEGER NOT NULL DEFAULT 0,
    updated_by INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS admin_rates (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    exp_mult REAL NOT NULL DEFAULT 1.0,
    gold_mult REAL NOT NULL DEFAULT 1.0,
    updated_at INTEGER NOT NULL DEFAULT 0,
    updated_by INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS admin_rules (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    text TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL DEFAULT 0,
    updated_by INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS admin_bans (
    user_id INTEGER PRIMARY KEY,
    reason TEXT NOT NULL DEFAULT '',
    banned_at INTEGER NOT NULL DEFAULT 0,
    banned_by INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS giveaways (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prize_type TEXT NOT NULL,
    prize_name TEXT NOT NULL DEFAULT '',
    prize_gold INTEGER NOT NULL DEFAULT 0,
    winners_count INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'open',
    winners TEXT NOT NULL DEFAULT '',
    created_by INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL DEFAULT 0,
    ends_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id INTEGER PRIMARY KEY,
    language TEXT NOT NULL DEFAULT 'id'
);
CREATE TABLE IF NOT EXISTS achievements (
    user_id INTEGER NOT NULL,
    achievement TEXT NOT NULL,
    granted_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, achievement)
);
CREATE TABLE IF NOT EXISTS seasons (
    number INTEGER PRIMARY KEY,
    starts_at INTEGER NOT NULL,
    ended_at INTEGER
);
CREATE TABLE IF NOT EXISTS tax_pool (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    balance INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tax_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_id INTEGER NOT NULL,
    buyer_guild_id INTEGER,
    seller_guild_id INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    qty INTEGER NOT NULL DEFAULT 0,
    sale_price INTEGER NOT NULL DEFAULT 0,
    tax INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tax_giveaways (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    total_gold INTEGER NOT NULL DEFAULT 0,
    per_winner INTEGER NOT NULL DEFAULT 0,
    winners_count INTEGER NOT NULL DEFAULT 0,
    winners TEXT NOT NULL DEFAULT '',
    created_by INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS bot_admins (
    user_id INTEGER PRIMARY KEY,
    granted_by INTEGER NOT NULL DEFAULT 0,
    granted_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS admin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL,
    executor_id INTEGER NOT NULL,
    target_id INTEGER,
    guild_id INTEGER,
    guild_name TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS admin_tax_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    market_tax_pct INTEGER NOT NULL DEFAULT 10,
    updated_at INTEGER NOT NULL DEFAULT 0,
    updated_by INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS boss_kills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    boss TEXT NOT NULL,
    raid_id INTEGER,
    killer_id INTEGER NOT NULL,
    killer_power INTEGER NOT NULL DEFAULT 0,
    killer_damage INTEGER NOT NULL DEFAULT 0,
    killed_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS guild_bank_deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    item_id TEXT,
    qty INTEGER NOT NULL DEFAULT 0,
    gold INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS personal_bank (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0,
    last_accrual INTEGER NOT NULL DEFAULT 0
);
"""

# Phase 3 defaults.
ADMIN_LOG_RETENTION = 1000  # keep the newest 1000 admin log entries
DEFAULT_MARKET_TAX_PCT = 10  # matches guildbank_db.MARKET_TAX_PCT today
MIN_MARKET_TAX_PCT = 0
MAX_MARKET_TAX_PCT = 50

# Season 1 starts at bot launch day: 2026-11-05 00:00 WIB (UTC+7).
# Must match the main bot's rolesync.SEASON_1_START.
SEASON_1_START = 1793811600


def db_path():
    return os.environ.get("RPG_DB_PATH", str(DEFAULT_DB))


@contextmanager
def connect(path=None):
    """Koneksi singkat ke database bersama (WAL + busy timeout 30 detik)."""
    p = Path(path or db_path())
    if p.parent and str(p.parent):
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.executescript(ADMIN_SCHEMA)
        conn.commit()
        yield conn
    finally:
        conn.close()


def row_to_dict(row):
    return dict(row) if row is not None else None


# ------------------------------------------------------------- pemain
def get_player(conn, user_id):
    row = conn.execute(
        "SELECT * FROM players WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row_to_dict(row)


def is_banned(conn, user_id):
    row = conn.execute(
        "SELECT * FROM admin_bans WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row_to_dict(row)


def adjust_gold(conn, user_id, delta):
    """Tambah/kurang gold. Kembalikan gold baru, atau None kalau pemain
    tidak ada / gold akan negatif."""
    p = get_player(conn, user_id)
    if p is None:
        return None
    new = p["gold"] + delta
    if new < 0:
        return None
    conn.execute(
        "UPDATE players SET gold = ? WHERE user_id = ?", (new, user_id)
    )
    conn.commit()
    return new


def set_gold(conn, user_id, amount):
    p = get_player(conn, user_id)
    if p is None or amount < 0:
        return None
    conn.execute(
        "UPDATE players SET gold = ? WHERE user_id = ?", (amount, user_id)
    )
    conn.commit()
    return amount


# ----------------------------------------------------------- inventory
def add_item(conn, user_id, item_id, qty=1):
    """Tambah item ke inventory (logika tumpuk sama seperti bot RPG)."""
    row = conn.execute(
        "SELECT * FROM inventory WHERE user_id = ? AND item_id = ? "
        "AND equipped = 0 ORDER BY id LIMIT 1",
        (user_id, item_id),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE inventory SET qty = qty + ? WHERE id = ?",
            (qty, row["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO inventory (user_id, item_id, qty, durability) "
            "VALUES (?, ?, ?, 100)",
            (user_id, item_id, qty),
        )
    conn.commit()


def add_pet(conn, user_id, species):
    conn.execute(
        "INSERT INTO pets (user_id, species, name) VALUES (?, ?, ?)",
        (user_id, species, species),
    )
    conn.commit()


# -------------------------------------------------------------- event
def set_event(conn, event, state, by_id):
    now = int(time.time())
    conn.execute(
        "INSERT INTO admin_events (event, state, updated_at, updated_by) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(event) DO UPDATE SET "
        "state = excluded.state, updated_at = excluded.updated_at, "
        "updated_by = excluded.updated_by",
        (event, state, now, by_id),
    )
    conn.commit()


def list_events(conn):
    rows = conn.execute(
        "SELECT * FROM admin_events ORDER BY event"
    ).fetchall()
    return [row_to_dict(r) for r in rows]


# -------------------------------------------------------------- rates
def get_rates(conn):
    row = conn.execute("SELECT * FROM admin_rates WHERE id = 1").fetchone()
    if row is None:
        return {"exp_mult": 1.0, "gold_mult": 1.0}
    return row_to_dict(row)


def set_rates(conn, exp_mult=None, gold_mult=None, by_id=0):
    cur = get_rates(conn)
    exp_mult = cur["exp_mult"] if exp_mult is None else exp_mult
    gold_mult = cur["gold_mult"] if gold_mult is None else gold_mult
    now = int(time.time())
    conn.execute(
        "INSERT INTO admin_rates (id, exp_mult, gold_mult, updated_at, updated_by) "
        "VALUES (1, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
        "exp_mult = excluded.exp_mult, gold_mult = excluded.gold_mult, "
        "updated_at = excluded.updated_at, updated_by = excluded.updated_by",
        (exp_mult, gold_mult, now, by_id),
    )
    conn.commit()
    return {"exp_mult": exp_mult, "gold_mult": gold_mult}


# -------------------------------------------------------------- rules
def get_rules(conn):
    row = conn.execute("SELECT * FROM admin_rules WHERE id = 1").fetchone()
    return row_to_dict(row)


def set_rules(conn, text, by_id):
    now = int(time.time())
    conn.execute(
        "INSERT INTO admin_rules (id, text, updated_at, updated_by) "
        "VALUES (1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
        "text = excluded.text, updated_at = excluded.updated_at, "
        "updated_by = excluded.updated_by",
        (text, now, by_id),
    )
    conn.commit()


# --------------------------------------------------------------- ban
def ban_player(conn, user_id, reason, by_id):
    now = int(time.time())
    conn.execute(
        "INSERT INTO admin_bans (user_id, reason, banned_at, banned_by) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET "
        "reason = excluded.reason, banned_at = excluded.banned_at, "
        "banned_by = excluded.banned_by",
        (user_id, reason, now, by_id),
    )
    conn.commit()


def unban_player(conn, user_id):
    cur = conn.execute(
        "DELETE FROM admin_bans WHERE user_id = ?", (user_id,)
    )
    conn.commit()
    return cur.rowcount > 0


# ------------------------------------------------------------ reset
def reset_player(conn, user_id):
    """Reset progres pemain ke awal (nama & kelas dipertahankan).
    Statistik kembali ke level 1, gold 100, HP/MP penuh, stamina/lapar/
    haus penuh; inventory, pet, progres quest, dan ranking PVP dibersihkan.
    Keanggotaan guild/party dan status VIP TIDAK diubah."""
    p = get_player(conn, user_id)
    if p is None:
        return False
    conn.execute(
        "UPDATE players SET level = 1, exp = 0, evo_stage = 0, gold = 100, "
        "hp = max_hp, mp = max_mp, hunger = 100, thirst = 100, "
        "stamina = 100, kills = 0, wins = 0, gold_earned = 0, crafts = 0, "
        "jobs_done = 0, casino_lost = 0, story_chapter = 0, house_level = 0 "
        "WHERE user_id = ?",
        (user_id,),
    )
    conn.execute("DELETE FROM inventory WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM pets WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM quests_progress WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM pvp_rank WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM crops WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM animals WHERE user_id = ?", (user_id,))
    conn.commit()
    return True


# ----------------------------------------------------------- giveaway
def create_giveaway(conn, prize_type, prize_name, prize_gold,
                    winners_count, created_by, duration_min):
    now = int(time.time())
    cur = conn.execute(
        "INSERT INTO giveaways (prize_type, prize_name, prize_gold, "
        "winners_count, status, created_by, created_at, ends_at) "
        "VALUES (?, ?, ?, ?, 'open', ?, ?, ?)",
        (prize_type, prize_name, prize_gold, winners_count,
         created_by, now, now + duration_min * 60),
    )
    conn.commit()
    return cur.lastrowid


def get_giveaway(conn, gid):
    row = conn.execute(
        "SELECT * FROM giveaways WHERE id = ?", (gid,)
    ).fetchone()
    return row_to_dict(row)


def list_giveaways(conn, limit=5):
    rows = conn.execute(
        "SELECT * FROM giveaways ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def draw_giveaway(conn, gid, winners):
    """Tandai giveaway sudah diundi + simpan pemenang (CSV user_id)."""
    conn.execute(
        "UPDATE giveaways SET status = 'drawn', winners = ? WHERE id = ?",
        (",".join(str(w) for w in winners), gid),
    )
    conn.commit()


# ------------------------------------------------- seasons & achievements
# (shared with the main bot's rolesync module; DDL identical, and the
# Season 1 seed is idempotent, so either bot may create them first.)
def grant_achievement(conn, user_id, key):
    """Record an achievement (idempotent). Returns True if newly granted."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO achievements (user_id, achievement, granted_at)"
        " VALUES (?, ?, ?)", (user_id, key, int(time.time())))
    conn.commit()
    return cur.rowcount > 0


def list_seasons(conn):
    conn.execute(
        "INSERT INTO seasons (number, starts_at, ended_at) "
        "SELECT 1, ?, NULL WHERE NOT EXISTS (SELECT 1 FROM seasons)",
        (SEASON_1_START,))
    conn.commit()
    rows = conn.execute(
        "SELECT * FROM seasons ORDER BY number").fetchall()
    return [row_to_dict(r) for r in rows]


def start_season(conn):
    """Close the current season and open a new one starting now.

    Seasons advance ONLY when an admin starts one, never automatically.
    Returns the new season number.
    """
    now = int(time.time())
    cur = conn.execute(
        "SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
    if cur is None:
        # Table was empty (should not happen: Season 1 is seeded on
        # boot). Seed it and report Season 1 as active.
        conn.execute(
            "INSERT INTO seasons (number, starts_at, ended_at) "
            "VALUES (1, ?, NULL)", (SEASON_1_START,))
        conn.commit()
        return 1
    conn.execute("UPDATE seasons SET ended_at = ? WHERE number = ?",
                 (now, cur["number"]))
    new_number = cur["number"] + 1
    conn.execute(
        "INSERT INTO seasons (number, starts_at, ended_at) "
        "VALUES (?, ?, NULL)", (new_number, now))
    conn.commit()
    return new_number


def eligible_players(conn):
    """Semua pemain yang tidak di-ban (kandidat undian giveaway)."""
    rows = conn.execute(
        "SELECT user_id FROM players WHERE user_id NOT IN "
        "(SELECT user_id FROM admin_bans)"
    ).fetchall()
    return [r["user_id"] for r in rows]


# ------------------------------------------------- tax pool & giveaways
# (shared with the main bot's guildbank_db module; DDL identical, so
# either bot may create these tables first. The pool is funded by the
# 10% tax on every guild market sale; this admin command spends it.)
def tax_pool_balance(conn):
    row = conn.execute(
        "SELECT balance FROM tax_pool WHERE id = 1").fetchone()
    return row["balance"] if row else 0


def take_tax_pool(conn, amount):
    """Remove amount from the pool. Returns False if funds are short."""
    if tax_pool_balance(conn) < amount:
        return False
    conn.execute(
        "UPDATE tax_pool SET balance = balance - ? WHERE id = 1",
        (int(amount),))
    conn.commit()
    return True


def split_prize(total, winners_count):
    """(per_winner, remainder): equal split, remainder stays in the pool."""
    winners_count = max(1, int(winners_count))
    per_winner = int(total) // winners_count
    return per_winner, int(total) - per_winner * winners_count


def record_tax_giveaway(conn, total_gold, per_winner, winners_count,
                        winners, created_by):
    cur = conn.execute(
        "INSERT INTO tax_giveaways (total_gold, per_winner, winners_count, "
        "winners, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (int(total_gold), int(per_winner), int(winners_count),
         ",".join(str(w) for w in winners), created_by, int(time.time())))
    conn.commit()
    return cur.lastrowid


def list_tax_giveaways(conn, limit=5):
    rows = conn.execute(
        "SELECT * FROM tax_giveaways ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()
    return [row_to_dict(r) for r in rows]


# -------------------------------------------------------------- stats
def economy_stats(conn):
    total_players = conn.execute(
        "SELECT COUNT(*) AS c FROM players"
    ).fetchone()["c"]
    total_gold = conn.execute(
        "SELECT COALESCE(SUM(gold), 0) AS s FROM players"
    ).fetchone()["s"]
    richest = conn.execute(
        "SELECT user_id, name, gold FROM players "
        "ORDER BY gold DESC LIMIT 5"
    ).fetchall()
    total_guilds = conn.execute(
        "SELECT COUNT(*) AS c FROM guilds"
    ).fetchone()["c"]
    total_pets = conn.execute(
        "SELECT COUNT(*) AS c FROM pets"
    ).fetchone()["c"]
    banned = conn.execute(
        "SELECT COUNT(*) AS c FROM admin_bans"
    ).fetchone()["c"]
    return {
        "total_players": total_players,
        "total_gold": total_gold,
        "richest": [row_to_dict(r) for r in richest],
        "total_guilds": total_guilds,
        "total_pets": total_pets,
        "banned": banned,
    }


# ------------------------------------------- phase 3: bot admins
def is_bot_admin(conn, user_id):
    row = conn.execute(
        "SELECT 1 FROM bot_admins WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row is not None


def grant_bot_admin(conn, user_id, by_id):
    """Grant bot-admin. Returns True if newly granted, False if already."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO bot_admins (user_id, granted_by, granted_at)"
        " VALUES (?, ?, ?)", (user_id, by_id, int(time.time())))
    conn.commit()
    return cur.rowcount > 0


def revoke_bot_admin(conn, user_id):
    cur = conn.execute(
        "DELETE FROM bot_admins WHERE user_id = ?", (user_id,))
    conn.commit()
    return cur.rowcount > 0


def list_bot_admins(conn):
    rows = conn.execute(
        "SELECT * FROM bot_admins ORDER BY granted_at, user_id").fetchall()
    return [row_to_dict(r) for r in rows]


# ------------------------------------------- phase 3: admin logs
def log_admin(conn, command, executor_id, target_id=None, guild_id=None,
              guild_name="", created_at=None, retain=ADMIN_LOG_RETENTION):
    """Log one authorized admin command execution, then prune to the
    newest `retain` entries (default 1000). Timestamps are Unix seconds;
    WIB formatting (with seconds) happens at display time."""
    now = int(created_at if created_at is not None else time.time())
    cur = conn.execute(
        "INSERT INTO admin_logs (command, executor_id, target_id, guild_id,"
        " guild_name, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (command, executor_id, target_id, guild_id, guild_name or "", now))
    conn.execute(
        "DELETE FROM admin_logs WHERE id NOT IN "
        "(SELECT id FROM admin_logs ORDER BY id DESC LIMIT ?)",
        (int(retain),))
    conn.commit()
    return cur.lastrowid


def list_admin_logs(conn, limit=20, executor_id=None, command=None):
    """Newest first. limit is clamped to 1-50 by the caller; here it is
    only bounded below so pure-function tests can pass any value."""
    limit = max(1, int(limit))
    query = "SELECT * FROM admin_logs"
    params = []
    clauses = []
    if executor_id is not None:
        clauses.append("executor_id = ?")
        params.append(int(executor_id))
    if command:
        clauses.append("command = ? COLLATE NOCASE")
        params.append(str(command))
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [row_to_dict(r) for r in rows]


# ------------------------------------------- phase 3: lifetime stats
def _table_exists(conn, name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,)).fetchone()
    return row is not None


def _scalar(conn, query, params=(), default=0):
    try:
        row = conn.execute(query, params).fetchone()
    except Exception:  # noqa: BLE001 — missing table/column: treat as 0
        return default
    if row is None or row[0] is None:
        return default
    return row[0]


def lifetime_stats(conn, user_id):
    """Per-player lifetime stats. Counters that live on the player row
    (gold_earned, kills, wins) are cleared by /admin_player reset, so
    after a reset they read "since last reset"; boss kills,
    achievements, deposits, and tax paid are never cleared by reset and
    therefore survive it. created_at is never reset either, so the
    "since" date stays the original registration date."""
    p = get_player(conn, user_id)
    if p is None:
        return None
    pvp_wins = _scalar(
        conn, "SELECT wins FROM pvp_rank WHERE user_id = ?", (user_id,))
    pvp_losses = _scalar(
        conn, "SELECT losses FROM pvp_rank WHERE user_id = ?", (user_id,))
    boss_kills = _scalar(
        conn, "SELECT COUNT(*) FROM boss_kills WHERE killer_id = ?",
        (user_id,))
    achievements = _scalar(
        conn, "SELECT COUNT(*) FROM achievements WHERE user_id = ?",
        (user_id,))
    deposits_gold = _scalar(
        conn, "SELECT COALESCE(SUM(gold), 0) FROM guild_bank_deposits"
        " WHERE user_id = ? AND kind = 'gold'", (user_id,))
    deposits_count = _scalar(
        conn, "SELECT COUNT(*) FROM guild_bank_deposits WHERE user_id = ?",
        (user_id,))
    tax_paid = _scalar(
        conn, "SELECT COALESCE(SUM(tax), 0) FROM tax_ledger"
        " WHERE buyer_id = ?", (user_id,))
    banked = _scalar(
        conn, "SELECT balance FROM personal_bank WHERE user_id = ?",
        (user_id,))
    guild_name = None
    if p.get("guild_id"):
        guild_name = _scalar(
            conn, "SELECT name FROM guilds WHERE id = ?",
            (p["guild_id"],), default=None)
    return {
        "user_id": user_id,
        "name": p["name"],
        "class": p["class"],
        "level": p["level"],
        "gold": p["gold"],
        "gold_earned": p["gold_earned"],
        "kills": p["kills"],
        "wins": p["wins"],
        "pvp_wins": pvp_wins,
        "pvp_losses": pvp_losses,
        "boss_kills": boss_kills,
        "achievements": achievements,
        "deposits_gold": deposits_gold,
        "deposits_count": deposits_count,
        "tax_paid": tax_paid,
        "banked_gold": banked,
        "guild_id": p.get("guild_id"),
        "guild_name": guild_name,
        "created_at": p.get("created_at", 0),
    }


def lifetime_leaderboard(conn, metric, limit=10):
    """Top players by one lifetime metric. boss_kills is a per-killer
    count over boss_kills; the rest read player/pvp/tax/deposit rows.
    Returns [(user_id, value), ...] newest-tie order is by user_id."""
    limit = max(1, int(limit))
    if metric == "boss_kills":
        rows = conn.execute(
            "SELECT killer_id AS user_id, COUNT(*) AS v FROM boss_kills"
            " GROUP BY killer_id ORDER BY v DESC, user_id LIMIT ?",
            (limit,)).fetchall()
        return [(r["user_id"], r["v"]) for r in rows]
    if metric == "pvp_wins":
        rows = conn.execute(
            "SELECT user_id, wins AS v FROM pvp_rank ORDER BY v DESC,"
            " user_id LIMIT ?", (limit,)).fetchall()
        return [(r["user_id"], r["v"]) for r in rows]
    if metric == "tax_paid":
        rows = conn.execute(
            "SELECT buyer_id AS user_id, SUM(tax) AS v FROM tax_ledger"
            " GROUP BY buyer_id ORDER BY v DESC, user_id LIMIT ?",
            (limit,)).fetchall()
        return [(r["user_id"], r["v"]) for r in rows]
    if metric == "deposits":
        rows = conn.execute(
            "SELECT user_id, SUM(gold) AS v FROM guild_bank_deposits"
            " WHERE kind = 'gold' GROUP BY user_id ORDER BY v DESC,"
            " user_id LIMIT ?", (limit,)).fetchall()
        return [(r["user_id"], r["v"]) for r in rows]
    column = {"gold_earned": "gold_earned", "kills": "kills"}.get(metric)
    if column is None:
        return []
    rows = conn.execute(
        f"SELECT user_id, {column} AS v FROM players ORDER BY v DESC,"
        " user_id LIMIT ?", (limit,)).fetchall()
    return [(r["user_id"], r["v"]) for r in rows]


# ------------------------------------------- phase 3: tax admin tools
def get_tax_rate(conn):
    row = conn.execute(
        "SELECT market_tax_pct FROM admin_tax_settings WHERE id = 1"
    ).fetchone()
    return row["market_tax_pct"] if row else DEFAULT_MARKET_TAX_PCT


def set_tax_rate(conn, pct, by_id=0):
    """Store the market tax percent. Returns the stored value, or None
    if out of the 0-50 range. NOTE: this is stored-only for now — the
    main bot's market code still uses its fixed 10% constant, exactly
    like admin_rates/admin_events before it (see SETUP.md)."""
    pct = int(pct)
    if pct < MIN_MARKET_TAX_PCT or pct > MAX_MARKET_TAX_PCT:
        return None
    now = int(time.time())
    conn.execute(
        "INSERT INTO admin_tax_settings (id, market_tax_pct, updated_at,"
        " updated_by) VALUES (1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET"
        " market_tax_pct = excluded.market_tax_pct,"
        " updated_at = excluded.updated_at,"
        " updated_by = excluded.updated_by",
        (pct, now, by_id))
    conn.commit()
    return pct


def tax_totals(conn):
    return {
        "pool": tax_pool_balance(conn),
        "collected": _scalar(
            conn, "SELECT COALESCE(SUM(tax), 0) FROM tax_ledger"),
        "given_away": _scalar(
            conn, "SELECT COALESCE(SUM(total_gold), 0) FROM tax_giveaways"),
        "sales": _scalar(conn, "SELECT COUNT(*) FROM tax_ledger"),
    }


def tax_ledger_recent(conn, limit=10):
    rows = conn.execute(
        "SELECT * FROM tax_ledger ORDER BY id DESC LIMIT ?",
        (max(1, int(limit)),)).fetchall()
    return [row_to_dict(r) for r in rows]


def top_tax_players(conn, limit=5):
    rows = conn.execute(
        "SELECT buyer_id, SUM(tax) AS total FROM tax_ledger"
        " GROUP BY buyer_id ORDER BY total DESC LIMIT ?",
        (limit,)).fetchall()
    return [(r["buyer_id"], r["total"]) for r in rows]


def top_tax_guilds(conn, limit=5):
    rows = conn.execute(
        "SELECT buyer_guild_id, SUM(tax) AS total FROM tax_ledger"
        " WHERE buyer_guild_id IS NOT NULL GROUP BY buyer_guild_id"
        " ORDER BY total DESC LIMIT ?",
        (limit,)).fetchall()
    return [(r["buyer_guild_id"], r["total"]) for r in rows]


def top_depositors(conn, limit=5):
    rows = conn.execute(
        "SELECT user_id, SUM(gold) AS total FROM guild_bank_deposits"
        " WHERE kind = 'gold' GROUP BY user_id ORDER BY total DESC"
        " LIMIT ?", (limit,)).fetchall()
    return [(r["user_id"], r["total"]) for r in rows]


# -------------------------------------------------------- gate murni
def is_staff(member):
    """Gate Administrator murni (bisa dites tanpa Discord).
    `member` cukup punya atribut guild_permissions.administrator."""
    try:
        return bool(member.guild_permissions.administrator)
    except AttributeError:
        return False
