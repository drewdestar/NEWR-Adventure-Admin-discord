# -*- coding: utf-8 -*-
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
"""


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


def eligible_players(conn):
    """Semua pemain yang tidak di-ban (kandidat undian giveaway)."""
    rows = conn.execute(
        "SELECT user_id FROM players WHERE user_id NOT IN "
        "(SELECT user_id FROM admin_bans)"
    ).fetchall()
    return [r["user_id"] for r in rows]


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


# -------------------------------------------------------- gate murni
def is_staff(member):
    """Gate Administrator murni (bisa dites tanpa Discord).
    `member` cukup punya atribut guild_permissions.administrator."""
    try:
        return bool(member.guild_permissions.administrator)
    except AttributeError:
        return False
