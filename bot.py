# -*- coding: utf-8 -*-
# NEWR Adventure by NEWR LABS — credit marker, do not remove.
"""NEWR Adventure Admin — bot staff Discord untuk mengelola bot NEWR Adventure.

Credit by NEWR LABS. Bot ini sepenuhnya terpisah dari bot NEWR lainnya
dan dari bot RPG pemain: kode, database admin, dan tokennya sendiri.
Database pemain/ekonomi DIBAGI dengan bot RPG (file rpg.db yang sama),
tapi bot ini tidak pernah mengubah kode atau skema bot RPG.

Semua command slash, semua khusus Administrator server.
Token dibaca dari environment DISCORD_TOKEN (dimuat dari .env oleh
run-rpg-admin.sh atau dari environment). Kalau token tidak ada, bot
berhenti dengan pesan error yang jelas (bukan crash misterius).
Jangan pernah menulis nilai token ke kode, log, atau README.
"""
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands

BOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BOT_DIR))

import credit_guard  # noqa: E402 — marker-only check, no other code hash

try:
    from dotenv import load_dotenv
    load_dotenv(BOT_DIR / ".env")
except ImportError:
    pass

GUILD_ID = os.environ.get("GUILD_ID", "1465422166790242377")


class AdminBot(commands.Bot):
    async def setup_hook(self):
        await self.load_extension("cogs.admin")

    async def on_ready(self):
        print(f"NEWR Adventure Admin login sebagai {self.user} (by NEWR LABS)")
        try:
            if GUILD_ID:
                guild = discord.Object(id=int(GUILD_ID))
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                print(f"Slash command tersinkron ke guild {GUILD_ID}: "
                      f"{len(synced)} command")
            else:
                synced = await self.tree.sync()
                print(f"Slash command tersinkron global: {len(synced)}")
        except Exception as exc:  # noqa: BLE001 — tampilkan, jangan crash
            print(f"Gagal sinkron slash command: {exc}")
        await self.change_presence(
            activity=discord.Game("NEWR Adventure Admin by NEWR LABS | /admin_help"))


def _proxy_kwargs() -> dict:
    """VM egress goes through an HTTP proxy; direct TLS to Discord fails
    here (SSL WRONG_VERSION_NUMBER), while aiohttp with trust_env works.
    discord.py does not read proxy env vars itself, so pass them explicitly.
    Credentials stay in the environment, never in code or logs."""
    from urllib.parse import unquote, urlparse

    raw = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
    if not raw:
        return {}
    parsed = urlparse(raw)
    proxy = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 3128}"
    kwargs: dict = {"proxy": proxy}
    if parsed.username:
        import aiohttp

        kwargs["proxy_auth"] = aiohttp.BasicAuth(
            unquote(parsed.username),
            unquote(parsed.password or ""))
    return kwargs


def main():
    # Credit guard runs FIRST, before any token/network use. It checks
    # credit markers only — any other code change passes it.
    credit_guard.enforce_credit_markers(BOT_DIR)
    token = os.environ.get("DISCORD_TOKEN", "")
    if not token or token.startswith("<") or "YOUR_" in token or "EXAMPLE" in token:
        print(
            "ERROR: DISCORD_TOKEN tidak ditemukan atau masih placeholder.\n"
            "Salin .env.example menjadi .env, isi DISCORD_TOKEN dengan token bot "
            "Discord yang asli, lalu jalankan lagi via "
            "~/workspace/bots/ops/run-rpg-admin.sh.\n"
            "Token TIDAK BOLEH ditulis di chat, kode, atau file lain selain .env.",
            file=sys.stderr,
        )
        sys.exit(1)

    intents = discord.Intents.default()
    bot = AdminBot(command_prefix="!", intents=intents, **_proxy_kwargs())
    bot.run(token)


if __name__ == "__main__":
    main()
