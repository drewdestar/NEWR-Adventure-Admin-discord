# -*- coding: utf-8 -*-
"""Tes offline bot admin RPG — TANPA Discord, TANPA menyentuh rpg.db asli.

Database tes dibuat dari salinan schema.sql bot RPG (dibaca saja) +
tabel admin, di file sementara. Menguji: gold beri/ambil/set (+ pengaman
negatif), event mulai/berhenti, rules simpan/baca, giveaway buat/undi
(+ hadiah benar-benar masuk ke pemain), dan gate Administrator.
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "cogs"))

import db as adb  # noqa: E402

RPG_SCHEMA = Path.home() / "workspace" / "bots" / "rpg" / "schema.sql"

CHECKS = []


def check(name, cond, info=""):
    CHECKS.append((name, bool(cond)))
    print(f"[{'OK ' if cond else 'GAGAL'}] {name} {info}")


class FakePerms:
    def __init__(self, admin):
        self.administrator = admin


class FakeMember:
    def __init__(self, admin):
        self.guild_permissions = FakePerms(admin)


class NoPerms:
    pass


def main():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    dbfile = tmp.name
    conn = sqlite3.connect(dbfile)
    conn.row_factory = sqlite3.Row
    # schema.sql hasil export mengandung baris sqlite_sequence (tabel
    # internal SQLite) yang tidak boleh dibuat ulang — buang baris itu.
    schema_text = "\n".join(
        line for line in RPG_SCHEMA.read_text().splitlines()
        if "sqlite_sequence" not in line
    )
    conn.executescript(schema_text)
    conn.executescript(adb.ADMIN_SCHEMA)
    conn.commit()

    # Pemain tes (kolom sesuai skema bot RPG).
    conn.execute(
        "INSERT INTO players (user_id, name, class, hp, max_hp, mp, max_mp,"
        " atk, def, spd, gold) VALUES (1, 'Tester', 'Warrior', 120, 120,"
        " 50, 50, 14, 10, 8, 100)"
    )
    conn.execute(
        "INSERT INTO players (user_id, name, class, hp, max_hp, mp, max_mp,"
        " atk, def, spd, gold) VALUES (2, 'Tester2', 'Mage', 100, 100,"
        " 80, 80, 12, 8, 10, 50)"
    )
    conn.commit()

    # --- gold: beri / ambil / set / pengaman negatif
    check("gold beri", adb.adjust_gold(conn, 1, 50) == 150)
    check("gold ambil", adb.adjust_gold(conn, 1, -30) == 120)
    check("gold ambil berlebih ditolak",
          adb.adjust_gold(conn, 1, -999) is None
          and adb.get_player(conn, 1)["gold"] == 120)
    check("gold set", adb.set_gold(conn, 1, 500) == 500)
    check("gold pemain tak ada ditolak",
          adb.adjust_gold(conn, 999, 10) is None)

    # --- event mulai / berhenti / daftar
    adb.set_event(conn, "Halloween", "active", 9)
    adb.set_event(conn, "Meteor", "inactive", 9)
    states = {r["event"]: r["state"] for r in adb.list_events(conn)}
    check("event mulai tersimpan", states.get("Halloween") == "active")
    check("event berhenti tersimpan", states.get("Meteor") == "inactive")
    adb.set_event(conn, "Halloween", "inactive", 9)
    states = {r["event"]: r["state"] for r in adb.list_events(conn)}
    check("event diubah ke berhenti", states.get("Halloween") == "inactive")

    # --- rules simpan / baca
    adb.set_rules(conn, "Aturan tes: jangan curang.", 9)
    row = adb.get_rules(conn)
    check("rules tersimpan & terbaca",
          row is not None and row["text"] == "Aturan tes: jangan curang.")

    # --- rates simpan / baca
    rates = adb.set_rates(conn, exp_mult=2.0, gold_mult=1.5, by_id=9)
    check("rates tersimpan",
          rates["exp_mult"] == 2.0 and rates["gold_mult"] == 1.5)
    check("rates terbaca", adb.get_rates(conn)["exp_mult"] == 2.0)

    # --- give item & pet
    adb.add_item(conn, 1, "pedang besi", 2)
    qty = conn.execute(
        "SELECT COALESCE(SUM(qty), 0) AS q FROM inventory "
        "WHERE user_id = 1 AND item_id = 'pedang besi'"
    ).fetchone()["q"]
    check("item masuk inventory", qty == 2)
    adb.add_pet(conn, 1, "Naga Mini")
    pets = conn.execute(
        "SELECT COUNT(*) AS c FROM pets WHERE user_id = 1"
    ).fetchone()["c"]
    check("pet masuk", pets == 1)

    # --- giveaway buat / undi (hadiah gold + item)
    gid = adb.create_giveaway(conn, "gold", "", 200, 1, 9, 60)
    g = adb.get_giveaway(conn, gid)
    check("giveaway dibuat", g is not None and g["status"] == "open")
    winners = [1]
    for w in winners:
        adb.adjust_gold(conn, w, g["prize_gold"])
    adb.draw_giveaway(conn, gid, winners)
    g = adb.get_giveaway(conn, gid)
    check("giveaway diundi + pemenang tersimpan",
          g["status"] == "drawn" and g["winners"] == "1")
    check("hadiah gold diterima pemenang",
          adb.get_player(conn, 1)["gold"] == 700)
    gid2 = adb.create_giveaway(conn, "item", "potion kecil", 3, 1, 9, 60)
    g2 = adb.get_giveaway(conn, gid2)
    adb.add_item(conn, 2, g2["prize_name"], g2["prize_gold"])
    adb.draw_giveaway(conn, gid2, [2])
    qty = conn.execute(
        "SELECT COALESCE(SUM(qty), 0) AS q FROM inventory "
        "WHERE user_id = 2 AND item_id = 'potion kecil'"
    ).fetchone()["q"]
    check("hadiah item diterima pemenang", qty == 3)

    # --- ban / unban / eligible
    adb.ban_player(conn, 2, "tes ban", 9)
    check("ban tersimpan", adb.is_banned(conn, 2) is not None)
    check("pemain di-ban tidak eligible undian",
          2 not in adb.eligible_players(conn)
          and 1 in adb.eligible_players(conn))
    check("unban berhasil", adb.unban_player(conn, 2) is True
          and adb.is_banned(conn, 2) is None)

    # --- reset pemain
    adb.add_item(conn, 1, "kayu", 5)
    check("reset berhasil", adb.reset_player(conn, 1) is True)
    p = adb.get_player(conn, 1)
    inv = conn.execute(
        "SELECT COUNT(*) AS c FROM inventory WHERE user_id = 1"
    ).fetchone()["c"]
    check("reset kembalikan level/gold & bersihkan inventory",
          p["level"] == 1 and p["gold"] == 100 and inv == 0)
    check("reset pemain tak ada ditolak",
          adb.reset_player(conn, 999) is False)

    # --- statistik
    s = adb.economy_stats(conn)
    check("statistik total pemain", s["total_players"] == 2)
    check("statistik total gold",
          s["total_gold"] == adb.get_player(conn, 1)["gold"]
          + adb.get_player(conn, 2)["gold"])

    # --- seasons & achievements (admin helpers)
    seasons = adb.list_seasons(conn)
    check("season 1 seeded",
          len(seasons) == 1 and seasons[0]["number"] == 1
          and seasons[0]["ended_at"] is None)
    check("start season -> S2", adb.start_season(conn) == 2)
    seasons = adb.list_seasons(conn)
    check("season lama tertutup, S2 aktif",
          len(seasons) == 2 and seasons[0]["ended_at"] is not None
          and seasons[1]["ended_at"] is None)
    check("grant achievement baru",
          adb.grant_achievement(conn, 1, "Boss Slayer") is True)
    check("grant achievement idempotent",
          adb.grant_achievement(conn, 1, "Boss Slayer") is False)

    # --- gate Administrator (fungsi murni)
    check("gate: admin lolos", adb.is_staff(FakeMember(True)) is True)
    check("gate: non-admin ditolak",
          adb.is_staff(FakeMember(False)) is False)
    check("gate: tanpa permission ditolak",
          adb.is_staff(NoPerms()) is False)

    # --- tax pool & tax giveaways (phase 2)
    check("pool pajak mulai 0", adb.tax_pool_balance(conn) == 0)
    conn.execute("INSERT INTO tax_pool (id, balance) VALUES (1, 250)")
    conn.commit()
    check("pool pajak terbaca", adb.tax_pool_balance(conn) == 250)
    check("tarik pool melebihi saldo ditolak",
          adb.take_tax_pool(conn, 251) is False
          and adb.tax_pool_balance(conn) == 250)
    check("split hadiah pajak", adb.split_prize(100, 3) == (33, 1))
    check("tarik pool berhasil",
          adb.take_tax_pool(conn, 99) is True
          and adb.tax_pool_balance(conn) == 151)
    gid3 = adb.record_tax_giveaway(conn, 99, 33, 3, [1, 2, 1], 9)
    rows = adb.list_tax_giveaways(conn)
    check("tax giveaway tercatat",
          rows and rows[0]["id"] == gid3 and rows[0]["total_gold"] == 99)

    # --- phase 3: bot admins (grant/revoke/list, idempotent)
    check("bot-admin awal tidak ada", adb.is_bot_admin(conn, 7) is False)
    check("grant bot-admin baru",
          adb.grant_bot_admin(conn, 7, 9) is True
          and adb.is_bot_admin(conn, 7) is True)
    check("grant bot-admin idempotent",
          adb.grant_bot_admin(conn, 7, 9) is False)
    check("list bot-admin",
          [r["user_id"] for r in adb.list_bot_admins(conn)] == [7])
    check("revoke bot-admin",
          adb.revoke_bot_admin(conn, 7) is True
          and adb.is_bot_admin(conn, 7) is False)
    check("revoke bot-admin tak ada ditolak",
          adb.revoke_bot_admin(conn, 7) is False)

    # --- phase 3: admin logs (isi, filter, retensi)
    adb.log_admin(conn, "admin_player", 9, target_id=1,
                  guild_id=1465422166790242377, guild_name="NEWR LABS",
                  created_at=1793811600)
    adb.log_admin(conn, "admin_currency", 9, target_id=2,
                  guild_id=1465422166790242377, guild_name="NEWR LABS",
                  created_at=1793811601)
    adb.log_admin(conn, "admin_player", 7, target_id=1,
                  guild_id=1465422166790242377, guild_name="NEWR LABS",
                  created_at=1793811602)
    logs = adb.list_admin_logs(conn)
    check("log admin tersimpan & terbaru dulu",
          len(logs) == 3 and logs[0]["command"] == "admin_player"
          and logs[0]["executor_id"] == 7
          and logs[0]["target_id"] == 1
          and logs[0]["guild_id"] == 1465422166790242377
          and logs[0]["guild_name"] == "NEWR LABS")
    check("log filter executor",
          len(adb.list_admin_logs(conn, executor_id=9)) == 2)
    check("log filter command",
          len(adb.list_admin_logs(conn, command="admin_player")) == 2)
    check("log filter command case-insensitive",
          len(adb.list_admin_logs(conn, command="ADMIN_PLAYER")) == 2)
    for i in range(5):
        adb.log_admin(conn, "admin_stats", 9, retain=3)
    check("retensi log 1000 default, prune kecil bekerja",
          len(adb.list_admin_logs(conn, limit=50)) == 3)

    # --- phase 3: lifetime stats
    conn.execute(
        "INSERT INTO players (user_id, name, class, hp, max_hp, mp, max_mp,"
        " atk, def, spd, gold, gold_earned, kills, wins, created_at)"
        " VALUES (3, 'Lifer', 'Archer', 95, 95, 60, 60, 15, 7, 12, 250,"
        " 5000, 42, 9, 1793811600)"
    )
    conn.execute(
        "INSERT INTO pvp_rank (user_id, points, wins, losses)"
        " VALUES (3, 1100, 6, 2)"
    )
    conn.execute(
        "INSERT INTO boss_kills (boss, raid_id, killer_id, killer_power,"
        " killer_damage, killed_at) VALUES ('Raja Slime', 1, 3, 900, 50,"
        " 1793811700)"
    )
    conn.execute(
        "INSERT INTO boss_kills (boss, raid_id, killer_id, killer_power,"
        " killer_damage, killed_at) VALUES ('Raja Slime', 2, 3, 950, 60,"
        " 1793811800)"
    )
    conn.execute(
        "INSERT INTO achievements (user_id, achievement, granted_at)"
        " VALUES (3, 'Boss Slayer', 1793811700)"
    )
    conn.execute(
        "INSERT INTO guild_bank_deposits (guild_id, user_id, kind, gold,"
        " created_at) VALUES (1, 3, 'gold', 800, 1793811700)"
    )
    conn.execute(
        "INSERT INTO tax_ledger (buyer_id, buyer_guild_id, seller_guild_id,"
        " item_id, qty, sale_price, tax, created_at)"
        " VALUES (3, 1, 2, 'potion kecil', 1, 1000, 100, 1793811700)"
    )
    conn.execute(
        "INSERT INTO personal_bank (user_id, balance, last_accrual)"
        " VALUES (3, 400, 1793811700)"
    )
    conn.commit()
    s = adb.lifetime_stats(conn, 3)
    check("lifetime stats lengkap",
          s is not None and s["gold_earned"] == 5000
          and s["kills"] == 42 and s["pvp_wins"] == 6
          and s["pvp_losses"] == 2 and s["boss_kills"] == 2
          and s["achievements"] == 1 and s["deposits_gold"] == 800
          and s["tax_paid"] == 100 and s["banked_gold"] == 400
          and s["created_at"] == 1793811600)
    check("lifetime stats pemain tak ada",
          adb.lifetime_stats(conn, 999) is None)
    check("lifetime board boss_kills",
          adb.lifetime_leaderboard(conn, "boss_kills") == [(3, 2)])
    check("lifetime board gold_earned urut",
          adb.lifetime_leaderboard(conn, "gold_earned")[0] == (3, 5000))
    check("lifetime board metrik tak dikenal kosong",
          adb.lifetime_leaderboard(conn, "nope") == [])

    # --- phase 3: tax admin tools
    check("tax rate default 10", adb.get_tax_rate(conn) == 10)
    check("tax rate set 15", adb.set_tax_rate(conn, 15, 9) == 15
          and adb.get_tax_rate(conn) == 15)
    check("tax rate di luar 0-50 ditolak",
          adb.set_tax_rate(conn, 51, 9) is None
          and adb.get_tax_rate(conn) == 15)
    t = adb.tax_totals(conn)
    check("tax totals",
          t["collected"] == 100 and t["sales"] == 1)
    check("tax ledger recent",
          len(adb.tax_ledger_recent(conn)) == 1
          and adb.tax_ledger_recent(conn)[0]["tax"] == 100)
    check("top tax players",
          adb.top_tax_players(conn) == [(3, 100)])
    check("top depositors",
          adb.top_depositors(conn) == [(3, 800)])

    conn.close()
    failed = [n for n, ok in CHECKS if not ok]
    print()
    if failed:
        print(f"GAGAL: {len(failed)} cek: {', '.join(failed)}")
        return 1
    print("SEMUA CEK LOLOS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
