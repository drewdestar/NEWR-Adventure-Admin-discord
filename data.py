# -*- coding: utf-8 -*-
# NEWR Adventure by NEWR LABS — credit marker, do not remove.
"""Data statis bot admin RPG — disalin dari daftar bot RPG (read-only).

Bot admin TIDAK mengimpor kode bot RPG: daftar ini disalin agar bot admin
tetap jalan sendiri meski folder bot RPG sedang diubah. Kalau bot RPG
menambah item/pet/event baru, sinkronkan daftar ini.
"""
CREDIT = "by NEWR LABS"
TITLE = "NEWR Adventure Admin"

# Warna embed (selaras dengan bot RPG: premium/modern, satu warna per maksud)
COLOR_ADMIN = 0xD946EF    # magenta — panel admin
COLOR_OK = 0x22C55E       # hijau — aksi berhasil
COLOR_GOLD = 0xF59E0B     # emas — ekonomi
COLOR_INFO = 0x3B82F6     # biru — info/daftar
COLOR_ERROR = 0xEF4444    # merah — error / ditolak

# Event yang bisa diatur admin. Tiga pertama adalah event musiman bot RPG
# (di data.py bot RPG: Halloween, Natal, Tahun Baru). Meteor adalah event
# jam 21:00 WIB bot RPG.
EVENTS = ["Halloween", "Natal", "Tahun Baru", "Meteor"]

# Semua item bot RPG (kunci ITEMS di data.py bot RPG).
ITEMS = [
    "pedang kayu", "pedang besi", "pedang baja", "pedang hitam", "pedang naga",
    "tongkat kayu", "tongkat api", "tongkat gelap", "tongkat phoenix",
    "busur kayu", "busur elang", "belati kayu", "belati bayangan",
    "armor kulit", "armor kulit kuat", "armor baja", "armor langit",
    "potion kecil", "potion besar", "elixir",
    "roti", "daging panggang", "air minum", "jus buah", "telur ayam", "susu",
    "kayu", "bijih besi", "kulit monster", "daging", "lendir slime", "tulang",
    "batu lava", "kristal api", "sisik api", "bulu elang", "bulu kelinci",
    "koin goblin", "sayap kelelawar", "jaring laba-laba", "bisa laba-laba",
    "kulit magma", "batu gargoyle", "sisik naga", "bulu phoenix", "awan padat",
    "benih gandum", "benih tomat", "benih labu",
    "kalung pet", "zirah pet", "mahkota pet",
    "jimat keberuntungan", "kristal void", "telur naga",
    "topi labu", "tongkat permen", "lonceng tahun baru",
]

# Spesies pet bot RPG (kunci PETS di data.py bot RPG).
PETS = ["Serigala Api", "Kucing Bayangan", "Naga Mini", "Kelinci Bulan"]

# Default rules shown when the admin has never set custom rules.
DEFAULT_RULES = (
    "1. Play sportsmanlike, no exploit/bug abuse.\n"
    "2. No command spam and don't disturb other players.\n"
    "3. Duel and giveaway results are final.\n"
    "4. Staff decisions are final and cannot be contested.\n"
    "5. Have fun, and respect your fellow players!"
)
