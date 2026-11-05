# -*- coding: utf-8 -*-
# NEWR Adventure by NEWR LABS — credit marker, do not remove.
"""Cog admin/staff bot RPG — semua command khusus Administrator.

Bot ini MENGELOLA bot NEWR Adventure, bukan memainkannya: event, peraturan, mata
uang, give item/pet, giveaway, data pemain, statistik ekonomi, dan
pengumuman. Semua command slash, semua balasan ephemeral (kecuali isi
pengumuman yang dikirim ke channel tujuan), semua embed dengan footer
by NEWR LABS.

Gate: SETIAP command memeriksa Discord Administrator. Bukan admin server
= ditolak dengan pesan jelas. Tidak ada pengecualian.
"""
import random
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

import db as adb
from data import (COLOR_ADMIN, COLOR_ERROR, COLOR_GOLD, COLOR_INFO,
                  COLOR_OK, CREDIT, DEFAULT_RULES, EVENTS, ITEMS, PETS,
                  TITLE)

def emb(title, desc="", color=COLOR_ADMIN):
    # Admin bot is English-only (no /language here). Footer credit
    # stays "NEWR Adventure by NEWR LABS" (footer only, no author link).
    e = discord.Embed(title=title, description=desc, color=color)
    e.set_footer(text=f"NEWR Adventure {CREDIT}")
    return e


def err(msg):
    return emb('⚠️ Oops!', msg, color=COLOR_ERROR)


def _command_name(interaction):
    """Name of the slash command being run (for the admin log)."""
    cmd = getattr(interaction, "command", None)
    name = getattr(cmd, "name", None) if cmd is not None else None
    return name or "admin_command"


def _log_execution(interaction, target_id=None):
    """Log one authorized admin command execution. Denied attempts are
    NOT logged as executions (they never ran); the gate message is the
    only record for those."""
    try:
        with adb.connect() as conn:
            adb.log_admin(
                conn, _command_name(interaction), interaction.user.id,
                target_id=target_id,
                guild_id=interaction.guild.id if interaction.guild else None,
                guild_name=interaction.guild.name if interaction.guild else "")
    except Exception:  # noqa: BLE001 — logging must never block the command
        pass


async def require_staff(interaction, target_id=None):
    """Gate: Discord Administrator OR granted bot-admin. Return True on
    pass (and log the execution), else False + a message (including
    DMs, where there is no server permission)."""
    if interaction.guild is None:
        await interaction.response.send_message(
            embed=err("This command is for staff only (server Administrators "
                      "or granted bot-admins). Regular members cannot use "
                      "the admin bot."),
            ephemeral=True,
        )
        return False
    staff = adb.is_staff(interaction.user)
    if not staff:
        try:
            with adb.connect() as conn:
                staff = adb.is_bot_admin(conn, interaction.user.id)
        except Exception:  # noqa: BLE001 — DB error = deny, safely
            staff = False
    if not staff:
        await interaction.response.send_message(
            embed=err("This command is for staff only (server Administrators "
                      "or granted bot-admins). Regular members cannot use "
                      "the admin bot."),
            ephemeral=True,
        )
        return False
    _log_execution(interaction, target_id=target_id)
    return True


async def require_discord_admin(interaction, target_id=None):
    """Gate: Discord Administrator ONLY. Bot-admins may NOT pass this
    gate — in particular they may never grant bot-admin to anyone.
    Grant/revoke of bot-admin go through this gate only."""
    if interaction.guild is None or not adb.is_staff(interaction.user):
        await interaction.response.send_message(
            embed=err("This command is for Discord server Administrators "
                      "only. Bot-admins cannot use it."),
            ephemeral=True,
        )
        return False
    _log_execution(interaction, target_id=target_id)
    return True


def canon_item(name):
    """Cocokkan nama item ke daftar resmi (tidak peduli kapital)."""
    low = name.strip().lower()
    for it in ITEMS:
        if it.lower() == low:
            return it
    return None


def _wib(ts):
    return datetime.fromtimestamp(
        ts, tz=timezone(timedelta(hours=7))).strftime("%d %b %Y %H:%M WIB")


def _wib_s(ts):
    """WIB timestamp down to seconds, for admin logs."""
    return datetime.fromtimestamp(
        ts, tz=timezone(timedelta(hours=7))).strftime("%d %b %Y %H:%M:%S WIB")


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ------------------------------------------------------------ help
    @app_commands.command(name="admin_help",
                          description="List all admin/staff bot commands")
    async def admin_help(self, interaction: discord.Interaction):
        if not await require_staff(interaction):
            return
        e = emb('🛡️ RPG Admin Panel','All commands below are for server Administrators only. The admin bot shares its database with the RPG bot: same gold, items, and players.', COLOR_ADMIN)
        e.add_field(name="/admin_event",
                    value='View / start / stop seasonal & meteor events.',
                    inline=False)
        e.add_field(name="/admin_rules",
                    value='View / set the RPG rules text.',
                    inline=False)
        e.add_field(name="/admin_currency",
                    value='Give / take / set player gold, and set server EXP & gold rates.',
                    inline=False)
        e.add_field(name="/admin_give",
                    value='Give an item or pet to a player.',
                    inline=False)
        e.add_field(name="/admin_giveaway",
                    value='Create giveaways, draw winners, view history.',
                    inline=False)
        e.add_field(name="/admin_taxgiveaway",
                    value='Giveaways paid from the bot tax pool (10% of guild market sales): view pool, run a draw, view history.',
                    inline=False)
        e.add_field(name="/admin_player",
                    value='View / reset / ban / unban players.',
                    inline=False)
        e.add_field(name="/admin_stats",
                    value='Server economy summary: players, gold in circulation, richest players, latest giveaways.',
                    inline=False)
        e.add_field(name="/admin_announce",
                    value='Send an embed announcement to a chosen channel.',
                    inline=False)
        e.add_field(name="/admin_lifetime",
                    value='Per-player lifetime stats since registration: gold earned, kills, PvP wins/losses, boss kills.',
                    inline=False)
        e.add_field(name="/admin_lifetimeboard",
                    value='Top 10 players by a lifetime metric (gold earned, kills, PvP wins, boss kills, tax paid, deposits).',
                    inline=False)
        e.add_field(name="/admin_tax",
                    value='Tax pool tools: pool balance & totals, recent sales ledger, top taxpayers/depositors, stored market tax rate.',
                    inline=False)
        e.add_field(name="/admin_botadmin",
                    value='Grant / revoke / list bot-admins (Discord Administrators only). Bot-admins can run admin commands without Discord Administrator permission, but can never grant bot-admin.',
                    inline=False)
        e.add_field(name="/admin_logs",
                    value='View recent admin command logs (command, executor, target, server, WIB timestamp to the second), filterable by executor or command.',
                    inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ----------------------------------------------------------- event
    @app_commands.command(name="admin_event",
                          description="Manage RPG seasonal & meteor events")
    @app_commands.describe(aksi="view = list events, start/stop = change status",
                           event="Event name (not needed for view)")
    @app_commands.rename(aksi="action")
    @app_commands.choices(
        aksi=[app_commands.Choice(name="view", value="lihat"),
              app_commands.Choice(name="start", value="mulai"),
              app_commands.Choice(name="stop", value="berhenti")],
        # Display names are English; values stay the internal event keys.
        event=[app_commands.Choice(name=n, value=v) for n, v in
               [("Halloween", "Halloween"), ("Christmas", "Natal"),
                ("New Year", "Tahun Baru"), ("Meteor", "Meteor")]],
    )
    async def admin_event(self, interaction: discord.Interaction,
                          aksi: str, event: str = None):
        if not await require_staff(interaction):
            return
        with adb.connect() as conn:
            if aksi == "lihat":
                rows = adb.list_events(conn)
                state = {r["event"]: r["state"] for r in rows}
                lines = [f"{'🟢' if state.get(e) == 'active' else '⚪'} "
                         f"{e}: {state.get(e, 'inactive')}"
                         for e in EVENTS]
                await interaction.response.send_message(
                    embed=emb('🎪 Event Status', "\n".join(lines),
                              COLOR_INFO),
                    ephemeral=True)
                return
            if event is None:
                await interaction.response.send_message(
                    embed=err("Pick an event first for the start/stop action."),
                    ephemeral=True)
                return
            adb.set_event(conn, event,
                          "active" if aksi == "mulai" else "inactive",
                          interaction.user.id)
        note = ("\n\n📌 Honest note: the RPG bot currently decides events "
                "from the calendar date only, so this admin table is not "
                "read by the RPG bot yet. For this setting to actually "
                "apply, the RPG bot needs a small patch (read admin_events) "
                "— see SETUP.md. The admin setting is still saved here.")
        status = "ACTIVE 🟢" if aksi == "mulai" else "INACTIVE ⚪"
        await interaction.response.send_message(
            embed=emb('🎪 Event Updated',
                      'Event **{event}** is now {status}.'.format(event=event,status=status)
                      + note, COLOR_OK),
            ephemeral=True)

    # ----------------------------------------------------------- rules
    @app_commands.command(name="admin_rules",
                          description="View / set the RPG rules text")
    @app_commands.describe(aksi="view = show rules, set = replace text",
                           teks="New rules text (required for set)")
    @app_commands.rename(aksi="action", teks="text")
    @app_commands.choices(
        aksi=[app_commands.Choice(name="view", value="lihat"),
              app_commands.Choice(name="set", value="atur")],
    )
    async def admin_rules(self, interaction: discord.Interaction,
                          aksi: str, teks: str = None):
        if not await require_staff(interaction):
            return
        with adb.connect() as conn:
            if aksi == "atur":
                if not teks or not teks.strip():
                    await interaction.response.send_message(
                        embed=err("Write the new rules text first."),
                        ephemeral=True)
                    return
                adb.set_rules(conn, teks.strip(), interaction.user.id)
                await interaction.response.send_message(
                    embed=emb('📜 Rules Updated','The RPG rules text has been changed.',
                              COLOR_OK),
                    ephemeral=True)
                return
            row = adb.get_rules(conn)
            text = row["text"] if row and row["text"] else DEFAULT_RULES
        await interaction.response.send_message(
            embed=emb('📜 RPG Rules', text, COLOR_INFO),
            ephemeral=True)

    # -------------------------------------------------------- currency
    @app_commands.command(name="admin_currency",
                          description="Manage player gold & server rates")
    @app_commands.describe(
        aksi="give/take/set = player gold; rate_exp/rate_gold = server rate",
        pemain="Target player: mention or user ID (not needed for rates)",
        jumlah="Gold (give/take/set) or rate percent (100 = 1.0x)")
    @app_commands.rename(aksi="action", pemain="player", jumlah="amount")
    @app_commands.choices(
        aksi=[app_commands.Choice(name="give", value="beri"),
              app_commands.Choice(name="take", value="ambil"),
              app_commands.Choice(name="set", value="set"),
              app_commands.Choice(name="rate_exp", value="rate_exp"),
              app_commands.Choice(name="rate_gold", value="rate_gold")],
    )
    async def admin_currency(self, interaction: discord.Interaction,
                             aksi: str, pemain: discord.User = None,
                             jumlah: int = None):
        if not await require_staff(interaction, target_id=pemain.id if pemain else None):
            return
        if jumlah is None or jumlah < 0:
            await interaction.response.send_message(
                embed=err("Amount must be filled in and cannot be negative."),
                ephemeral=True)
            return
        with adb.connect() as conn:
            if aksi in ("rate_exp", "rate_gold"):
                mult = jumlah / 100.0
                if mult <= 0 or mult > 10:
                    await interaction.response.send_message(
                        embed=err("Rate must be 1–1000 percent (0.01x–10x)."),
                        ephemeral=True)
                    return
                rates = adb.set_rates(
                    conn,
                    exp_mult=mult if aksi == "rate_exp" else None,
                    gold_mult=mult if aksi == "rate_gold" else None,
                    by_id=interaction.user.id)
                note = ("\n\n📌 Note: this rate is stored in the "
                        "admin_rates table. The RPG bot needs a small patch "
                        "to read it (see SETUP.md).")
                await interaction.response.send_message(
                    embed=emb('💰 Server Rates Updated',
                              'EXP rate: {exp}x\nGold rate: {gold}x{note}'.format(exp=rates['exp_mult'],gold=rates['gold_mult'],note=note),
                              COLOR_GOLD),
                    ephemeral=True)
                return
            if pemain is None:
                await interaction.response.send_message(
                    embed=err("Pick a player first for the gold action."),
                    ephemeral=True)
                return
            if aksi == "beri":
                new = adb.adjust_gold(conn, pemain.id, jumlah)
            elif aksi == "ambil":
                new = adb.adjust_gold(conn, pemain.id, -jumlah)
            else:
                new = adb.set_gold(conn, pemain.id, jumlah)
            if new is None:
                await interaction.response.send_message(
                    embed=err("Failed: player hasn't registered for the RPG, "
                              "or gold would go negative."),
                    ephemeral=True)
                return
        await interaction.response.send_message(
            embed=emb('💰 Gold Updated',
                      'Player <@{id}> now has **{new} gold**.'.format(id=pemain.id,new=new), COLOR_GOLD),
            ephemeral=True)

    # ------------------------------------------------------------ give
    @app_commands.command(name="admin_give",
                          description="Give an item or pet to a player")
    @app_commands.describe(pemain="Receiving player (mention or user ID)",
                           jenis="item or pet",
                           nama="Item name / pet species",
                           jumlah="Item amount (ignored for pets)")
    @app_commands.rename(pemain="player", jenis="type", nama="name",
                         jumlah="amount")
    @app_commands.choices(
        jenis=[app_commands.Choice(name="item", value="item"),
               app_commands.Choice(name="pet", value="pet")],
    )
    async def admin_give(self, interaction: discord.Interaction,
                         pemain: discord.User, jenis: str, nama: str,
                         jumlah: int = 1):
        if not await require_staff(interaction, target_id=pemain.id):
            return
        if jumlah < 1:
            await interaction.response.send_message(
                embed=err("Minimum amount is 1."), ephemeral=True)
            return
        with adb.connect() as conn:
            if adb.get_player(conn, pemain.id) is None:
                await interaction.response.send_message(
                    embed=err("That player hasn't registered for the RPG."),
                    ephemeral=True)
                return
            if jenis == "item":
                item = canon_item(nama)
                if item is None:
                    await interaction.response.send_message(
                        embed=err("Item '{nama}' is unknown. Check the name again (e.g. pedang besi, potion kecil).".format(nama=nama)),
                        ephemeral=True)
                    return
                adb.add_item(conn, pemain.id, item, jumlah)
                desc = '<@{id}> received **{jumlah}x {item}**.'.format(id=pemain.id,jumlah=jumlah,item=item)
            else:
                pet = next((p for p in PETS
                            if p.lower() == nama.strip().lower()), None)
                if pet is None:
                    await interaction.response.send_message(
                        embed=err("Pet '{nama}' is unknown. Options: {pets}.".format(nama=nama,pets=", ".join(PETS))),
                        ephemeral=True)
                    return
                adb.add_pet(conn, pemain.id, pet)
                desc = '<@{id}> received pet **{pet}**.'.format(id=pemain.id,pet=pet)
        await interaction.response.send_message(
            embed=emb('🎁 Item/Pet Given', desc, COLOR_OK),
            ephemeral=True)

    # -------------------------------------------------------- giveaway
    @app_commands.command(name="admin_giveaway",
                          description="Create, draw, or view RPG giveaways")
    @app_commands.describe(
        aksi="create = new giveaway, draw = pick winners, list = history",
        jenis_hadiah="gold or item (for create)",
        nama_item="Prize item name (for item prizes)",
        jumlah="Prize gold / item amount",
        pemenang="Number of winners",
        durasi_menit="Giveaway duration in minutes",
        giveaway_id="Giveaway ID (for draw)")
    @app_commands.rename(aksi="action", jenis_hadiah="prize_type",
                         nama_item="item_name", jumlah="amount",
                         pemenang="winners", durasi_menit="duration_minutes")
    @app_commands.choices(
        aksi=[app_commands.Choice(name="create", value="buat"),
              app_commands.Choice(name="draw", value="undi"),
              app_commands.Choice(name="list", value="list")],
        jenis_hadiah=[app_commands.Choice(name="gold", value="gold"),
                      app_commands.Choice(name="item", value="item")],
    )
    async def admin_giveaway(self, interaction: discord.Interaction,
                             aksi: str, jenis_hadiah: str = "gold",
                             nama_item: str = None, jumlah: int = 100,
                             pemenang: int = 1, durasi_menit: int = 60,
                             giveaway_id: int = None):
        if not await require_staff(interaction):
            return
        with adb.connect() as conn:
            if aksi == "list":
                rows = adb.list_giveaways(conn)
                if not rows:
                    await interaction.response.send_message(
                        embed=emb('🎉 Giveaway','No giveaways yet.', COLOR_INFO),
                        ephemeral=True)
                    return
                lines = []
                for g in rows:
                    hadiah = (f"{g['prize_gold']} gold"
                              if g["prize_type"] == "gold"
                              else f"{g['prize_gold']}x {g['prize_name']}")
                    lines.append('#{id} • {hadiah} • {n} winners • {status}'.format(id=g['id'],hadiah=hadiah,n=g['winners_count'],status=g['status']))
                await interaction.response.send_message(
                    embed=emb('🎉 Latest Giveaways', "\n".join(lines),
                              COLOR_INFO),
                    ephemeral=True)
                return
            if aksi == "buat":
                if jumlah < 1 or pemenang < 1 or durasi_menit < 1:
                    await interaction.response.send_message(
                        embed=err("Amount, winners, and duration must be ≥ 1."),
                        ephemeral=True)
                    return
                item = None
                if jenis_hadiah == "item":
                    item = canon_item(nama_item or "")
                    if item is None:
                        await interaction.response.send_message(
                            embed=err("Prize item name is unknown."),
                            ephemeral=True)
                        return
                gid = adb.create_giveaway(
                    conn, jenis_hadiah, item or "", jumlah, pemenang,
                    interaction.user.id, durasi_menit)
                hadiah = (f"{jumlah} gold" if jenis_hadiah == "gold"
                          else f"{jumlah}x {item}")
                await interaction.response.send_message(
                    embed=emb('🎉 Giveaway Created',
                              'ID: **#{gid}**\nPrize: {hadiah}\nWinners: {n} people\nDuration: {d} minutes\nDraw with /admin_giveaway action:draw giveaway_id:{gid}.'.format(gid=gid,hadiah=hadiah,n=pemenang,d=durasi_menit),
                              COLOR_OK),
                    ephemeral=True)
                return
            # aksi == undi
            if giveaway_id is None:
                await interaction.response.send_message(
                    embed=err("Fill in giveaway_id first to draw."),
                    ephemeral=True)
                return
            g = adb.get_giveaway(conn, giveaway_id)
            if g is None:
                await interaction.response.send_message(
                    embed=err('Giveaway #{id} not found.'.format(id=giveaway_id)),
                    ephemeral=True)
                return
            if g["status"] != "open":
                await interaction.response.send_message(
                    embed=err('Giveaway #{id} has already been drawn.'.format(id=giveaway_id)),
                    ephemeral=True)
                return
            eligible = adb.eligible_players(conn)
            if not eligible:
                await interaction.response.send_message(
                    embed=err("No players can be drawn."),
                    ephemeral=True)
                return
            winners = random.sample(
                eligible, min(g["winners_count"], len(eligible)))
            for w in winners:
                if g["prize_type"] == "gold":
                    adb.adjust_gold(conn, w, g["prize_gold"])
                else:
                    adb.add_item(conn, w, g["prize_name"], g["prize_gold"])
            adb.draw_giveaway(conn, giveaway_id, winners)
        mentions = ", ".join(f"<@{w}>" for w in winners)
        await interaction.response.send_message(
            embed=emb('🎉 Giveaway Drawn',
                      'Giveaway #{id} was won by: {mentions}'.format(id=giveaway_id,mentions=mentions), COLOR_OK),
            ephemeral=True)

    # ------------------------------------------------- tax giveaway
    @app_commands.command(name="admin_taxgiveaway",
                          description="Giveaways paid from the bot tax pool (funded by market tax)")
    @app_commands.describe(
        aksi="pool = view tax pool balance, run = draw winners now, list = history",
        jumlah="Total gold to give away (for run; must fit the pool)",
        pemenang="Number of winners (for run)")
    @app_commands.rename(aksi="action", jumlah="total_gold",
                         pemenang="winners")
    @app_commands.choices(
        aksi=[app_commands.Choice(name="pool", value="pool"),
              app_commands.Choice(name="run", value="run"),
              app_commands.Choice(name="list", value="list")],
    )
    async def admin_taxgiveaway(self, interaction: discord.Interaction,
                                aksi: str, jumlah: int = 0, pemenang: int = 1):
        if not await require_staff(interaction):
            return
        with adb.connect() as conn:
            if aksi == "pool":
                await interaction.response.send_message(
                    embed=emb('💰 Bot Tax Pool',
                              'Current pool balance: **{bal} gold**.\n'
                              'The pool grows by 10% of every guild market sale. '
                              'Run a draw with /admin_taxgiveaway action:run '
                              'total_gold:<amount> winners:<count>.'.format(bal=adb.tax_pool_balance(conn)),
                              COLOR_INFO),
                    ephemeral=True)
                return
            if aksi == "list":
                rows = adb.list_tax_giveaways(conn)
                if not rows:
                    await interaction.response.send_message(
                        embed=emb('💰 Tax Giveaways', 'No tax giveaways yet.', COLOR_INFO),
                        ephemeral=True)
                    return
                lines = []
                for g in rows:
                    winners = g["winners"].split(",") if g["winners"] else []
                    mentions = ", ".join(f"<@{w}>" for w in winners)
                    lines.append('#{id} • {total} gold total ({per} each) • {n} winners • {mentions}'.format(
                        id=g["id"], total=g["total_gold"], per=g["per_winner"],
                        n=g["winners_count"], mentions=mentions))
                await interaction.response.send_message(
                    embed=emb('💰 Latest Tax Giveaways', "\n".join(lines),
                              COLOR_INFO),
                    ephemeral=True)
                return
            # aksi == run
            if jumlah < 1 or pemenang < 1:
                await interaction.response.send_message(
                    embed=err("Total gold and winners must be ≥ 1."),
                    ephemeral=True)
                return
            pool = adb.tax_pool_balance(conn)
            if jumlah > pool:
                await interaction.response.send_message(
                    embed=err("Tax pool holds only {pool} gold — the prize total must fit the pool.".format(pool=pool)),
                    ephemeral=True)
                return
            eligible = adb.eligible_players(conn)
            if not eligible:
                await interaction.response.send_message(
                    embed=err("No players can be drawn."),
                    ephemeral=True)
                return
            winners = random.sample(eligible, min(pemenang, len(eligible)))
            per_winner, _remainder = adb.split_prize(jumlah, len(winners))
            # The remainder of an uneven split stays in the pool; only
            # per_winner * len(winners) leaves it.
            spent = per_winner * len(winners)
            if not adb.take_tax_pool(conn, spent):
                await interaction.response.send_message(
                    embed=err("Tax pool changed mid-draw — try again."),
                    ephemeral=True)
                return
            for w in winners:
                adb.adjust_gold(conn, w, per_winner)
            gid = adb.record_tax_giveaway(
                conn, spent, per_winner, len(winners), winners,
                interaction.user.id)
        mentions = ", ".join(f"<@{w}>" for w in winners)
        await interaction.response.send_message(
            embed=emb('💰 Tax Giveaway Drawn',
                      'Tax giveaway #{id}: **{per} gold** each to: {mentions}\n'
                      'Paid from the bot tax pool (pool left: {left} gold).'.format(
                          id=gid, per=per_winner, mentions=mentions,
                          left=pool - spent),
                      COLOR_OK),
            ephemeral=True)

    # ---------------------------------------------------------- player
    @app_commands.command(name="admin_player",
                          description="View / reset / ban / unban an RPG player")
    @app_commands.describe(
        aksi="view, reset, ban, or unban",
        pemain="Target player (mention or user ID)",
        alasan="Ban reason (for ban)",
        konfirmasi="Write RESET for the reset action (safety)")
    @app_commands.rename(aksi="action", pemain="player", alasan="reason",
                         konfirmasi="confirmation")
    @app_commands.choices(
        aksi=[app_commands.Choice(name="view", value="lihat"),
              app_commands.Choice(name="reset", value="reset"),
              app_commands.Choice(name="ban", value="ban"),
              app_commands.Choice(name="unban", value="unban")],
    )
    async def admin_player(self, interaction: discord.Interaction,
                           aksi: str, pemain: discord.User,
                           alasan: str = "", konfirmasi: str = ""):
        if not await require_staff(interaction, target_id=pemain.id):
            return
        with adb.connect() as conn:
            p = adb.get_player(conn, pemain.id)
            if aksi == "lihat":
                if p is None:
                    await interaction.response.send_message(
                        embed=err("That player hasn't registered for the RPG."),
                        ephemeral=True)
                    return
                ban = adb.is_banned(conn, pemain.id)
                vip_txt = 'yes' if p['vip'] else 'no'
                ban_txt = ('BANNED ({reason})'.format(reason=ban['reason'])
                           if ban else 'clean')
                e = emb(f"👤 {p['name']}",
                        "Class: {cls} (evo {stage})\n"
                        "Level {lvl} • EXP {exp}\n"
                        "HP {hp}/{maxhp} • MP {mp}/{maxmp}\n"
                        "ATK {atk} • DEF {dfn} • SPD {spd}\n"
                        "Gold: {gold} • VIP: {vip}\n"
                        "Guild ID: {gid}\n"
                        "Ban status: {ban}".format(
                        cls=p['class'], stage=p['evo_stage'], lvl=p['level'],
                        exp=p['exp'], hp=p['hp'], maxhp=p['max_hp'],
                        mp=p['mp'], maxmp=p['max_mp'], atk=p['atk'],
                        dfn=p['def'], spd=p['spd'], gold=p['gold'],
                        vip=vip_txt, gid=p['guild_id'] or '-', ban=ban_txt),
                        COLOR_INFO)
                await interaction.response.send_message(embed=e,
                                                        ephemeral=True)
                return
            if aksi == "ban":
                if p is None:
                    await interaction.response.send_message(
                        embed=err("That player hasn't registered for the RPG."),
                        ephemeral=True)
                    return
                adb.ban_player(conn, pemain.id, alasan or "-",
                               interaction.user.id)
                note = ("\n\n📌 Honest note: the RPG bot does not check "
                        "this ban table yet, so a ban only takes full "
                        "effect after the RPG bot gains one check "
                        "(see SETUP.md). The ban data is already saved.")
                await interaction.response.send_message(
                    embed=emb('🔨 Player Banned',
                              '<@{id}> is banned. Reason: {alasan}.{note}'.format(id=pemain.id,alasan=alasan or '-',note=note), COLOR_OK),
                    ephemeral=True)
                return
            if aksi == "unban":
                ok = adb.unban_player(conn, pemain.id)
                msg = ('is no longer banned.'
                       if ok else 'is not currently banned.')
                await interaction.response.send_message(
                    embed=emb('🔓 Player Unbanned',
                              '<@{id}> {msg}'.format(id=pemain.id,msg=msg),
                              COLOR_OK),
                    ephemeral=True)
                return
            # aksi == reset
            if konfirmasi != "RESET":
                await interaction.response.send_message(
                    embed=err("Reset is permanent. To confirm, fill in "
                              "confirmation with exactly RESET."),
                    ephemeral=True)
                return
            if not adb.reset_player(conn, pemain.id):
                await interaction.response.send_message(
                    embed=err("That player hasn't registered for the RPG."),
                    ephemeral=True)
                return
        await interaction.response.send_message(
            embed=emb('♻️ Player Reset',
                      '<@{id}> is back to level 1, 100 gold, inventory/pets/quests cleared. Name, class, guild, and VIP are unchanged.'.format(id=pemain.id), COLOR_OK),
            ephemeral=True)

    # ----------------------------------------------------------- stats
    @app_commands.command(name="admin_stats",
                          description="RPG server economy & player summary")
    async def admin_stats(self, interaction: discord.Interaction):
        if not await require_staff(interaction):
            return
        with adb.connect() as conn:
            s = adb.economy_stats(conn)
            rates = adb.get_rates(conn)
            gws = adb.list_giveaways(conn, limit=3)
        lines = ['👥 Total players: {n}'.format(n=s['total_players']),
                 '💰 Total gold in circulation: {n}'.format(n=s['total_gold']),
                 '🏰 Total guilds: {n}'.format(n=s['total_guilds']),
                 '🐾 Total pets: {n}'.format(n=s['total_pets']),
                 '🔨 Banned players: {n}'.format(n=s['banned']),
                 '⚡ Rates: EXP {e}x • gold {g}x'.format(e=rates['exp_mult'],g=rates['gold_mult'])]
        if s["richest"]:
            lines.append("")
            lines.append('🏆 Richest:')
            for i, r in enumerate(s["richest"], 1):
                lines.append(f"{i}. {r['name']} — {r['gold']} gold")
        if gws:
            lines.append("")
            lines.append('🎉 Latest giveaways:')
            for g in gws:
                hadiah = (f"{g['prize_gold']} gold"
                          if g["prize_type"] == "gold"
                          else f"{g['prize_gold']}x {g['prize_name']}")
                lines.append('#{id} • {hadiah} • {status}'.format(id=g['id'],hadiah=hadiah,status=g['status']))
        await interaction.response.send_message(
            embed=emb('📊 RPG Server Statistics', "\n".join(lines),
                      COLOR_GOLD),
            ephemeral=True)

    # -------------------------------------------------------- announce
    @app_commands.command(name="admin_announce",
                          description="Send an embed announcement to a channel")
    @app_commands.describe(channel="Target channel",
                           judul="Announcement title",
                           pesan="Announcement body")
    @app_commands.rename(judul="title", pesan="message")
    async def admin_announce(self, interaction: discord.Interaction,
                             channel: discord.TextChannel,
                             judul: str, pesan: str):
        if not await require_staff(interaction):
            return
        e = emb(f"📢 {judul}", pesan, COLOR_ADMIN)
        e.add_field(name='From',
                    value='RPG Staff', inline=False)
        try:
            await channel.send(embed=e)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=err("The bot doesn't have permission to send to that channel."),
                ephemeral=True)
            return
        await interaction.response.send_message(
            embed=emb('📢 Announcement Sent',
                      'Announcement sent to <#{id}>.'.format(id=channel.id),
                      COLOR_OK),
            ephemeral=True)

    @app_commands.command(name="admin_season",
                          description="List seasons or start a new season")
    @app_commands.describe(aksi="list = show seasons, start = open a new season now")
    @app_commands.rename(aksi="action")
    @app_commands.choices(
        aksi=[app_commands.Choice(name="list", value="list"),
              app_commands.Choice(name="start", value="start")])
    async def admin_season(self, interaction: discord.Interaction,
                           aksi: str):
        if not await require_staff(interaction):
            return
        with adb.connect() as conn:
            if aksi == "list":
                seasons = adb.list_seasons(conn)
                lines = []
                for s in seasons:
                    end = _wib(s["ended_at"]) if s["ended_at"] else "Active"
                    lines.append(
                        f"Season S{s['number']}: {_wib(s['starts_at'])} → {end}")
                await interaction.response.send_message(
                    embed=emb('📅 Seasons',
                              "\n".join(lines) if lines else "No seasons yet.",
                              COLOR_INFO),
                    ephemeral=True)
                return
            new_number = adb.start_season(conn)
        await interaction.response.send_message(
            embed=emb('📅 New Season Started',
                      f"Season S{new_number} is now active. Players who "
                      f"register from now on get the Season S{new_number} "
                      f"role; existing players keep their season role.",
                      COLOR_OK),
            ephemeral=True)

    @app_commands.command(name="admin_achievement",
                          description="Grant an achievement to a player")
    @app_commands.describe(pemain="Receiving player (mention or user ID)",
                           nama="Achievement name (e.g. Boss Slayer, War Champion)")
    @app_commands.rename(pemain="player", nama="name")
    async def admin_achievement(self, interaction: discord.Interaction,
                                pemain: discord.User, nama: str):
        if not await require_staff(interaction, target_id=pemain.id):
            return
        nama = nama.strip()
        if not nama or len(nama) > 32:
            await interaction.response.send_message(
                embed=err("Achievement names must be 1-32 characters."),
                ephemeral=True)
            return
        with adb.connect() as conn:
            if adb.get_player(conn, pemain.id) is None:
                await interaction.response.send_message(
                    embed=err("That user doesn't have a character yet."),
                    ephemeral=True)
                return
            new = adb.grant_achievement(conn, pemain.id, nama)
        await interaction.response.send_message(
            embed=emb('🏆 Achievement Granted' if new
                      else '🏆 Achievement Already Owned',
                      f"**{nama}** {'granted to' if new else 'already owned by'} "
                      f"{pemain.mention}. The matching Discord role is "
                      f"applied by the main bot's role reconciler within "
                      f"10 minutes.",
                      COLOR_OK),
            ephemeral=True)


    # ------------------------------------------- phase 3: lifetime
    @app_commands.command(name="admin_lifetime",
                          description="Per-player lifetime stats since registration")
    @app_commands.describe(pemain="Target player (mention or user ID)")
    @app_commands.rename(pemain="player")
    async def admin_lifetime(self, interaction: discord.Interaction,
                             pemain: discord.User):
        if not await require_staff(interaction, target_id=pemain.id):
            return
        with adb.connect() as conn:
            s = adb.lifetime_stats(conn, pemain.id)
        if s is None:
            await interaction.response.send_message(
                embed=err("That player hasn't registered for the RPG."),
                ephemeral=True)
            return
        since = _wib(s["created_at"]) if s["created_at"] else "unknown"
        guild_txt = (f"{s['guild_name']} (ID {s['guild_id']})"
                     if s["guild_id"] else "-")
        e = emb(f"📜 Lifetime Stats — {s['name']}",
                f"Class: {s['class']} • Level {s['level']}\n"
                f"Registered: {since}\n"
                f"Guild: {guild_txt}\n\n"
                f"💰 Total gold earned: {s['gold_earned']}\n"
                f"💰 Current carried gold: {s['gold']}\n"
                f"🏦 Banked gold: {s['banked_gold']}\n"
                f"⚔️ Monster kills: {s['kills']}\n"
                f"🥊 PvP: {s['pvp_wins']} wins / {s['pvp_losses']} losses\n"
                f"👹 Boss kills (killing blow): {s['boss_kills']}\n"
                f"🏆 Achievements: {s['achievements']}\n"
                f"🏰 Guild deposits: {s['deposits_gold']} gold "
                f"({s['deposits_count']} deposits)\n"
                f"💸 Tax paid on market buys: {s['tax_paid']} gold\n\n"
                f"📌 Note: gold earned / kills / PvP wins on the player "
                f"row reset if the player was ever reset with "
                f"/admin_player, so after a reset those three read "
                f"'since last reset'. Boss kills, achievements, "
                f"deposits, and tax paid are never cleared by reset.",
                COLOR_INFO)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="admin_lifetimeboard",
                          description="Top 10 players by a lifetime metric")
    @app_commands.describe(metrik="Metric to rank by")
    @app_commands.rename(metrik="metric")
    @app_commands.choices(
        metrik=[app_commands.Choice(name="Gold earned", value="gold_earned"),
                app_commands.Choice(name="Monster kills", value="kills"),
                app_commands.Choice(name="PvP wins", value="pvp_wins"),
                app_commands.Choice(name="Boss kills", value="boss_kills"),
                app_commands.Choice(name="Tax paid", value="tax_paid"),
                app_commands.Choice(name="Guild deposits", value="deposits")],
    )
    async def admin_lifetimeboard(self, interaction: discord.Interaction,
                                  metrik: str):
        if not await require_staff(interaction):
            return
        with adb.connect() as conn:
            rows = adb.lifetime_leaderboard(conn, metrik, limit=10)
        if not rows:
            await interaction.response.send_message(
                embed=emb('📜 Lifetime Leaderboard',
                          'No data for this metric yet.', COLOR_INFO),
                ephemeral=True)
            return
        lines = [f"{i}. <@{uid}> — {val}"
                 for i, (uid, val) in enumerate(rows, 1)]
        await interaction.response.send_message(
            embed=emb(f"📜 Lifetime Leaderboard — {metrik}",
                      "\n".join(lines), COLOR_GOLD),
            ephemeral=True)

    # ------------------------------------------- phase 3: tax tools
    @app_commands.command(name="admin_tax",
                          description="Tax pool tools: pool, ledger, tops, rate")
    @app_commands.describe(
        aksi="pool = balance & totals, ledger = recent sales, tops = top taxpayers/depositors, set_rate = stored market tax percent",
        persen="Market tax percent for set_rate (0-50, default live rate is 10)")
    @app_commands.rename(aksi="action", persen="percent")
    @app_commands.choices(
        aksi=[app_commands.Choice(name="pool", value="pool"),
              app_commands.Choice(name="ledger", value="ledger"),
              app_commands.Choice(name="tops", value="tops"),
              app_commands.Choice(name="set_rate", value="set_rate")],
    )
    async def admin_tax(self, interaction: discord.Interaction,
                        aksi: str, persen: int = None):
        if not await require_staff(interaction):
            return
        with adb.connect() as conn:
            if aksi == "pool":
                t = adb.tax_totals(conn)
                rate = adb.get_tax_rate(conn)
                desc = (f"💰 Pool balance: **{t['pool']} gold**\n"
                        f"💸 Total tax collected: {t['collected']} gold "
                        f"({t['sales']} sales)\n"
                        f"🎉 Total given away from pool: {t['given_away']} gold\n"
                        f"📊 Stored market tax rate: {rate}% "
                        f"(live market rate is 10% until the main bot "
                        f"reads this setting — see /admin_tax set_rate note).")
                await interaction.response.send_message(
                    embed=emb('💰 Bot Tax Pool', desc, COLOR_INFO),
                    ephemeral=True)
                return
            if aksi == "ledger":
                rows = adb.tax_ledger_recent(conn, limit=10)
                if not rows:
                    await interaction.response.send_message(
                        embed=emb('💰 Tax Ledger', 'No market sales yet.',
                                  COLOR_INFO),
                        ephemeral=True)
                    return
                lines = []
                for r in rows:
                    lines.append(
                        f"#{r['id']} • buyer <@{r['buyer_id']}> • "
                        f"{r['item_id']} x{r['qty']} • price {r['sale_price']} "
                        f"• tax {r['tax']} • {_wib_s(r['created_at'])}")
                await interaction.response.send_message(
                    embed=emb('💰 Recent Tax Ledger', "\n".join(lines),
                              COLOR_INFO),
                    ephemeral=True)
                return
            if aksi == "tops":
                players = adb.top_tax_players(conn, limit=5)
                guilds = adb.top_tax_guilds(conn, limit=5)
                deps = adb.top_depositors(conn, limit=5)
                lines = ["💸 Top taxpayers (players):"]
                lines += ([f"{i}. <@{u}> — {v} gold"
                           for i, (u, v) in enumerate(players, 1)]
                          or ["- none yet -"])
                lines.append("")
                lines.append("💸 Top taxpayers (guilds, by buyer guild):")
                lines += ([f"{i}. Guild ID {g} — {v} gold"
                           for i, (g, v) in enumerate(guilds, 1)]
                          or ["- none yet -"])
                lines.append("")
                lines.append("🏰 Top depositors (gold to guild banks):")
                lines += ([f"{i}. <@{u}> — {v} gold"
                           for i, (u, v) in enumerate(deps, 1)]
                          or ["- none yet -"])
                await interaction.response.send_message(
                    embed=emb('💰 Tax & Donation Leaderboards',
                              "\n".join(lines), COLOR_GOLD),
                    ephemeral=True)
                return
            # aksi == set_rate
            if persen is None:
                await interaction.response.send_message(
                    embed=err("Fill in percent (0-50) for set_rate."),
                    ephemeral=True)
                return
            new = adb.set_tax_rate(conn, persen, interaction.user.id)
            if new is None:
                await interaction.response.send_message(
                    embed=err("Tax percent must be 0-50."),
                    ephemeral=True)
                return
        await interaction.response.send_message(
            embed=emb('💰 Market Tax Rate Stored',
                      f"Stored market tax rate is now **{new}%**.\n\n"
                      f"📌 Honest note: this is stored-only for now. The "
                      f"main bot's market code still applies its fixed "
                      f"10% tax, exactly like admin_rates and "
                      f"admin_events before it — applying a stored rate "
                      f"needs a small main-bot patch (see SETUP.md). "
                      f"The stored value is already saved here.",
                      COLOR_OK),
            ephemeral=True)

    # ------------------------------------------- phase 3: bot admins
    @app_commands.command(name="admin_botadmin",
                          description="Grant / revoke / list bot-admins (Discord Administrators only)")
    @app_commands.describe(
        aksi="grant = give bot-admin, revoke = remove it, list = show bot-admins",
        pemain="Target player (mention or user ID; not needed for list)")
    @app_commands.rename(aksi="action", pemain="player")
    @app_commands.choices(
        aksi=[app_commands.Choice(name="grant", value="grant"),
              app_commands.Choice(name="revoke", value="revoke"),
              app_commands.Choice(name="list", value="list")],
    )
    async def admin_botadmin(self, interaction: discord.Interaction,
                             aksi: str, pemain: discord.User = None):
        if not await require_discord_admin(
                interaction, target_id=pemain.id if pemain else None):
            return
        with adb.connect() as conn:
            if aksi == "list":
                rows = adb.list_bot_admins(conn)
                if not rows:
                    await interaction.response.send_message(
                        embed=emb('🛡️ Bot-Admins', 'No bot-admins granted yet.',
                                  COLOR_INFO),
                        ephemeral=True)
                    return
                lines = [f"<@{r['user_id']}> • granted by "
                         f"<@{r['granted_by']}> • {_wib(r['granted_at'])}"
                         for r in rows]
                await interaction.response.send_message(
                    embed=emb('🛡️ Bot-Admins', "\n".join(lines), COLOR_INFO),
                    ephemeral=True)
                return
            if pemain is None:
                await interaction.response.send_message(
                    embed=err("Pick a player first for grant/revoke."),
                    ephemeral=True)
                return
            if aksi == "grant":
                member = (interaction.guild.get_member(pemain.id)
                          if interaction.guild else None)
                if member is not None and adb.is_staff(member):
                    await interaction.response.send_message(
                        embed=err("That user is already a Discord "
                                  "Administrator, so they do not need "
                                  "bot-admin."),
                        ephemeral=True)
                    return
                new = adb.grant_bot_admin(conn, pemain.id,
                                          interaction.user.id)
                msg = ('is now a bot-admin and can run admin commands '
                       'without Discord Administrator permission.'
                       if new else 'is already a bot-admin.')
                await interaction.response.send_message(
                    embed=emb('🛡️ Bot-Admin Granted',
                              f"<@{pemain.id}> {msg}\n\n"
                              f"📌 Bot-admins can never grant bot-admin "
                              f"to anyone else — granting stays "
                              f"Discord-Administrator-only.",
                              COLOR_OK),
                    ephemeral=True)
                return
            # aksi == revoke
            ok = adb.revoke_bot_admin(conn, pemain.id)
            msg = ('is no longer a bot-admin.'
                   if ok else 'is not a bot-admin.')
            await interaction.response.send_message(
                embed=emb('🛡️ Bot-Admin Revoked',
                          f"<@{pemain.id}> {msg}", COLOR_OK),
                ephemeral=True)

    # ------------------------------------------- phase 3: admin logs
    @app_commands.command(name="admin_logs",
                          description="View recent admin command logs")
    @app_commands.describe(
        pelaksana="Filter by executor (mention or user ID, optional)",
        perintah="Filter by command name, e.g. admin_player (optional)",
        batas="How many entries to show (1-50, default 20)")
    @app_commands.rename(pelaksana="executor", perintah="command",
                         batas="limit")
    async def admin_logs(self, interaction: discord.Interaction,
                         pelaksana: discord.User = None,
                         perintah: str = None, batas: int = 20):
        if not await require_staff(interaction):
            return
        batas = max(1, min(50, batas))
        with adb.connect() as conn:
            rows = adb.list_admin_logs(
                conn, limit=batas,
                executor_id=pelaksana.id if pelaksana else None,
                command=perintah.strip() if perintah else None)
        if not rows:
            await interaction.response.send_message(
                embed=emb('📋 Admin Logs', 'No log entries match.',
                          COLOR_INFO),
                ephemeral=True)
            return
        lines = []
        for r in rows:
            target = f"<@{r['target_id']}>" if r["target_id"] else "-"
            guild = (f"{r['guild_name']} ({r['guild_id']})"
                     if r["guild_id"] else "-")
            lines.append(
                f"{_wib_s(r['created_at'])} • `{r['command']}` • "
                f"by <@{r['executor_id']}> • target {target} • {guild}")
        await interaction.response.send_message(
            embed=emb('📋 Recent Admin Logs', "\n".join(lines), COLOR_INFO),
            ephemeral=True)


async def setup(bot):
    await bot.add_cog(Admin(bot))
