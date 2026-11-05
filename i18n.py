# -*- coding: utf-8 -*-
"""Translation layer for NEWR Adventure Admin.

Adapted copy of the main bot's i18n.py (same MyMemory + cache +
offline-fallback chain, same strict English fallback). The admin bot
shares rpg.db, so user_prefs (stored language) is the same table the
main bot reads. The main bot's ID_TABLE is kept, plus ADMIN_ID_TABLE
below for admin-only strings; game-content name protection is a no-op
here (no display.py in the admin folder), which is fine because admin
strings rarely contain display names.

Design (user direction 2026-11-05 02:22 WIB):
  * English is the base language (all bot strings were converted to English).
  * Indonesian ships FULLY OFFLINE for the central paths (see ID_TABLE).
  * Every other Discord locale resolves through: offline table -> cache
    -> online (MyMemory, free, no key) -> English base.
  * A translation failure NEVER breaks a command: it falls back to English.
  * Every user-visible string is translated: the offline table covers the
    central paths, everything else goes through cache -> online (MyMemory)
    with protected placeholders, /commands and game-content names, and
    falls back to the English base when no translation is available.
  * Internal keys/IDs are never translated: this module only maps
    complete user-visible strings, never item/area/monster/pet keys
    (those use display.py).

Usage:
  * Handlers call i18n.set_ctx(interaction, conn) once (need_player does
    this automatically). Afterwards i18n.t(text) translates with the
    caller's language + connection from contextvars.
  * emb() in cogs/common.py calls i18n.t() on title/description.
"""

import contextvars
import re
import html
import json
import sqlite3
import urllib.parse
import urllib.request

DEFAULT_LANG = "en"

# (Discord locale value, human-readable label). Mirrors discord.Locale
# values (discord.py version on this VM); Indonesian ('id') is included
# natively, so no extra entry is needed.
SUPPORTED = [
    ("en-US", "English (US)"),
    ("en-GB", "English (UK)"),
    ("bg", "Bulgarian"),
    ("zh-CN", "Chinese"),
    ("zh-TW", "Chinese (Taiwan)"),
    ("hr", "Croatian"),
    ("cs", "Czech"),
    ("id", "Indonesian"),
    ("da", "Danish"),
    ("nl", "Dutch"),
    ("fi", "Finnish"),
    ("fr", "French"),
    ("de", "German"),
    ("el", "Greek"),
    ("hi", "Hindi"),
    ("hu", "Hungarian"),
    ("it", "Italian"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("es-419", "Spanish (Latin America)"),
    ("lt", "Lithuanian"),
    ("no", "Norwegian"),
    ("pl", "Polish"),
    ("pt-BR", "Portuguese (Brazil)"),
    ("ro", "Romanian"),
    ("ru", "Russian"),
    ("es-ES", "Spanish (Spain)"),
    ("sv-SE", "Swedish"),
    ("th", "Thai"),
    ("tr", "Turkish"),
    ("uk", "Ukrainian"),
    ("vi", "Vietnamese"),
]
SUPPORTED_VALUES = {value for value, _label in SUPPORTED}

# MyMemory language-code mapping for locales whose code differs.
_MYMEMORY_CODE = {
    "es-419": "es",
    "sv-SE": "sv",
    "no": "nb",
}
_ONLINE_TIMEOUT = 5  # seconds; never let a slow API stall a command long
_CACHE_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS translations_cache ("
    "source TEXT NOT NULL, lang TEXT NOT NULL, "
    "translated TEXT NOT NULL, updated_at INTEGER NOT NULL, "
    "PRIMARY KEY (source, lang))"
)

_lang_var = contextvars.ContextVar("i18n_lang", default="en")
_conn_var = contextvars.ContextVar("i18n_conn", default=None)


def current_lang():
    """Language of the current interaction (default English)."""
    return _lang_var.get() or "en"


def set_ctx(interaction, conn):
    """Set language + connection for the current interaction task.

    Call once at the start of a handler (need_player does this). The
    values live in contextvars, so they never leak into other tasks.
    """
    set_ctx_for_user(interaction.user.id, conn)


# ---------------------------------------------------------------- DB ---

def get_lang(conn, user_id):
    """Stored language for a user; 'en' when nothing was chosen."""
    try:
        row = conn.execute(
            "SELECT language FROM user_prefs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    except Exception:
        return "en"
    if row and row[0] in SUPPORTED_VALUES:
        return row[0]
    return "en"


def set_lang(conn, user_id, lang):
    """Store a user's language choice (must be a supported value)."""
    if lang not in SUPPORTED_VALUES:
        raise ValueError(f"unsupported language: {lang!r}")
    conn.execute(
        "INSERT OR REPLACE INTO user_prefs (user_id, language) VALUES (?, ?)",
        (user_id, lang),
    )
    conn.commit()


def _cache_get(conn, text, lang):
    try:
        conn.execute(_CACHE_TABLE_SQL)
        row = conn.execute(
            "SELECT translated FROM translations_cache "
            "WHERE source = ? AND lang = ?",
            (text, lang),
        ).fetchone()
    except Exception:
        return None
    return row[0] if row else None


def _cache_put(conn, text, lang, translated):
    try:
        conn.execute(_CACHE_TABLE_SQL)
        import time as _time
        conn.execute(
            "INSERT OR REPLACE INTO translations_cache "
            "(source, lang, translated, updated_at) VALUES (?, ?, ?, ?)",
            (text, lang, translated, int(_time.time())),
        )
        conn.commit()
    except Exception:
        pass


# ------------------------------------------------------------- online ---

def _online(text, lang):
    """Translate via MyMemory (free, no key). None on any failure."""
    code = _MYMEMORY_CODE.get(lang, lang)
    url = (
        "https://api.mymemory.translated.net/get?q="
        + urllib.parse.quote(text)
        + "&langpair=en|" + urllib.parse.quote(code)
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NEWR-Adventure/1.0"})
        with urllib.request.urlopen(req, timeout=_ONLINE_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        if data.get("responseStatus") != 200:
            return None
        out = (data.get("responseData") or {}).get("translatedText")
        if not out:
            return None
        out = html.unescape(out).strip()
        bad = ("MYMEMORY WARNING", "NO QUERY SPECIFIED", "QUERY LENGTH LIMIT")
        if not out or any(b in out for b in bad):
            return None
        return out
    except Exception:
        return None


# ---------------------------------------------------------- translate ---

# Strong Indonesian markers: if a translation for a NON-Indonesian target
# comes back containing these, it is rejected and English is used instead.
# (Never show Indonesian to a non-Indonesian user.)
_ID_MARKERS = re.compile(
    r"\b(kamu|nggak|tidak|sudah|belum|buat|pakai|dengan|untuk|dari|adalah|"
    r"juga|kalau|saat|ketika|dapat|harus|akan|jika|atau|sangat|semua|"
    r"setiap|antara|oleh|pada|dalam|jangan|silakan|tolong|terima|tolak|"
    r"menang|kalah|banget|lagi|masih|cuma|bisa|boleh|mau|ingin|coba|"
    r"lihat|cek|beli|jual|bayar|kerja|latih|pelihara|tanam|panen|"
    r"bangun|naik|habis|penuh|kosong|baru|besar|kecil|cepat|kuat|lemah)\b",
    re.I)

_TEMPLATE_RES = None


def _template_regexes():
    """Compile ID_TABLE templates into regexes (longest template first).

    A template like 'You bought {item} x{qty}...' matches the formatted
    string 'You bought Small Potion x2...' and yields the captured groups
    in placeholder order. This is what makes translate-template-first work
    for call sites that formatted BEFORE calling emb(): the formatted
    string is matched back to its template, translated, and re-filled.
    """
    global _TEMPLATE_RES
    if _TEMPLATE_RES is not None:
        return _TEMPLATE_RES
    out = []
    for key in sorted(ID_TABLE, key=len, reverse=True):
        names = re.findall(r"\{([^}]+)\}", key)
        pat = re.escape(key)
        pat = re.sub(r"\\\{[^}]+\\\}", r"(.+?)", pat)
        try:
            out.append((re.compile("^" + pat + "$", re.S), names, key))
        except re.error:
            continue
    _TEMPLATE_RES = out
    return out


def _display_pairs():
    """(English display name, Indonesian internal key) pairs, longest first.

    Game content names are canonical terms: they are protected from machine
    translation (a shop item must keep one searchable name) and, for
    Indonesian, rendered with their Indonesian key; for every other
    language they stay in English. Imported lazily so display.py never
    needs to import this module.
    """
    try:
        import display as _disp
    except Exception:
        return []
    pairs = []
    for table in (_disp.ITEM_EN, _disp.AREA_EN, _disp.MONSTER_EN,
                  _disp.PET_EN, _disp.PET_SKILL_EN, _disp.PET_FORM_EN,
                  _disp.SKILL_EN, _disp.JOB_EN, _disp.CROP_EN,
                  _disp.ANIMAL_EN):
        for key, val in table.items():
            if val and val != key:
                pairs.append((val, key))
    for key, (name, _desc, boss) in _disp.EVENT_EN.items():
        if name and name != key:
            pairs.append((name, key))
        if boss and boss != key:
            pairs.append((boss, key))
    pairs.sort(key=lambda kv: -len(kv[0]))
    return pairs


def _protect(text, lang):
    """Replace must-not-translate spans with __TK<n>__ tokens.

    Protected: `code` spans, {placeholders}, /slash commands, URLs, and
    canonical game-content names. Returns (masked, restore_dict) where the
    restore value is the Indonesian key for lang 'id' and the English
    name for every other language.
    """
    tokens = {}

    def _tok(value):
        tok = "__TK%d__" % len(tokens)
        tokens[tok] = value
        return tok

    masked = text
    masked = re.sub(r"`[^`]+`", lambda m: _tok(m.group(0)), masked)
    masked = re.sub(r"\{[^}]+\}", lambda m: _tok(m.group(0)), masked)
    masked = re.sub(r"https?://\S+", lambda m: _tok(m.group(0)), masked)
    masked = re.sub(r"/[a-zA-Z]+(?: [a-zA-Z]+)?", lambda m: _tok(m.group(0)), masked)
    for en_name, id_key in _display_pairs():
        if en_name in masked:
            restore = id_key if lang == "id" else en_name
            masked = re.sub(r"(?<!\w)" + re.escape(en_name) + r"(?!\w)",
                            lambda m, r=restore: _tok(r), masked)
    return masked, tokens


def _restore(text, tokens):
    for tok, value in tokens.items():
        text = text.replace(tok, value)
    return text


def _looks_indonesian(text):
    return bool(_ID_MARKERS.search(text or ""))


def _translate_id_table(text):
    """Exact table hit, else template match with display-name conversion.

    Captured groups that are exactly an English display name are rendered
    with the Indonesian key, so an Indonesian sentence never carries an
    English item/monster name inside it.
    """
    hit = ID_TABLE.get(text)
    if hit is not None:
        return hit
    pairs = dict(_display_pairs())
    for rx, names, key in _template_regexes():
        m = rx.match(text)
        if not m:
            continue
        groups = m.groups()
        mapping = {}
        for name, group in zip(names, groups):
            mapping[name] = pairs.get(group, group)
        try:
            return ID_TABLE[key].format_map(mapping)
        except Exception:
            continue
    return None


def translate(text, lang=None, conn=None):
    """Resolve one user-visible string to the user's language.

    Chain: Indonesian table / template match -> cache -> online
    (MyMemory, protected tokens) -> English base. Only strings in the
    offline table are translated without network; EVERY other string is
    translated through cache/online instead of being silently left in
    English, so a reply is never a mix of two languages. A missing or
    failed translation ALWAYS falls back to the English base -- never to
    Indonesian -- for non-Indonesian users. Never raises.
    """
    if not text:
        return text
    lang = lang or _lang_var.get() or "en"
    if lang == "en" or lang not in SUPPORTED_VALUES:
        return text
    if lang == "id":
        hit = _translate_id_table(text)
        if hit is not None:
            return hit
    c = conn if conn is not None else _conn_var.get()
    if c is not None:
        cached = _cache_get(c, text, lang)
        if cached:
            return cached
    masked, tokens = _protect(text, lang)
    out = _online(masked, lang)
    if out:
        restored = _restore(out, tokens)
        if lang != "id" and _looks_indonesian(restored):
            return text
        if c is not None:
            _cache_put(c, text, lang, restored)
        return restored
    return text


def t(text):
    """translate() using the current interaction's language/connection."""
    return translate(text, _lang_var.get(), _conn_var.get())


def t_fmt(template, **kwargs):
    """Translate-template-first: translate the TEMPLATE, then format it.

    This is the preferred way to build a reply: the template (with
    {placeholders} intact) is what the translation table / cache knows,
    so names, numbers and gold amounts can never break the lookup.
    Command names inside the template are protected and never translated.
    """
    lang = _lang_var.get() or "en"
    out = translate(template, lang, _conn_var.get())
    if lang == "id" and kwargs:
        pairs = dict(_display_pairs())
        kwargs = {k: (pairs.get(v, v) if isinstance(v, str) else v)
                  for k, v in kwargs.items()}
    return out.format(**kwargs)


def set_ctx_for_user(user_id, conn):
    """Set language + connection for a user id (no interaction needed).

    Used by view callbacks and DM builders, which run outside the
    original command interaction and would otherwise fall back to English.
    """
    lang = "en"
    try:
        if conn is not None:
            lang = get_lang(conn, user_id)
    except Exception:
        lang = "en"
    _lang_var.set(lang if lang in SUPPORTED_VALUES else "en")
    _conn_var.set(conn)


# -------------------------------------------------------
# Offline Indonesian table (generated by inverting the
# pre-conversion ID->EN map; EN string -> Indonesian string).
# -------------------------------------------------------
ID_TABLE = {
    '\n\nRequirement: Lv {lv} • Reward: {g} gold + {e} EXP': '\n\nSyarat: Lv {lv} • Hadiah: {g} gold + {e} EXP',
    '\n\nReward: {g} gold + {e} EXP': '\n\nHadiah: {g} gold + {e} EXP',
    '\n\n🎉 BOSS DEFEATED! All participants get gold based on contribution + 300 EXP. Top damage gets a rare item!': '\n\n🎉 BOSS KALAH! Semua peserta dapat gold sesuai kontribusi + 300 EXP. Top damage dapat item langka!',
    '\nContinue the next chapter with `/story next`.': '\nLanjutkan chapter berikutnya pakai `/story next`.',
    '\n🌟 Pet evolved into **{form}**!': '\n🌟 Pet berevolusi jadi **{form}**!',
    ' (old gear {old} returned).': ' (gear lama {old} dikembalikan).',
    ' EXP {exp}/{need}.': ' EXP {exp}/{need}.',
    ' Leveled up {n} levels, now Lv {lv}.': ' Naik {n} level, sekarang Lv {lv}.',
    ' Pet {name} leveled up {n} levels!': ' Pet {name} naik {n} level!',
    ' • dur {d}': ' • dura {d}',
    ' • equipped': ' • terpasang',
    '(refills tomorrow)': '(penuh lagi besok)',
    '**[{qid}] {name}** ({kind}) — {desc} — {status} — reward {gold} gold + {exp} EXP': '**[{qid}] {name}** ({kind}) — {desc} — {status} — hadiah {gold} gold + {exp} EXP',
    '**{a}** challenges **{b}** to a duel!\n{mention}, accept or decline within 2 minutes.': '**{a}** menantang **{b}** duel!\n{mention}, terima atau tolak dalam 2 menit.',
    '**{a}** vs **{b}**!\nThe fight is tallied 1 hour from now based on total member power + guild level. Check the result with `/guildwar info`.': '**{a}** vs **{b}**!\nPertarungan dihitung 1 jam lagi dari kekuatan total anggota + level guild. Cek hasilnya pakai `/guildwar info`.',
    '**{name}** evolved into **{evo}**!\nBonus: +{hp} HP, +{mp} MP, +{atk} ATK, +{dfn} DEF, +{spd} SPD. HP/MP fully restored!': '**{name}** berevolusi jadi **{evo}**!\nBonus: +{hp} HP, +{mp} MP, +{atk} ATK, +{dfn} DEF, +{spd} SPD. HP/MP penuh lagi!',
    '**{name}** is officially founded, led by {leader}! Invite friends to join with `/guild join {name}`.': '**{name}** resmi berdiri, dipimpin {leader}! Ajak teman gabung pakai `/guild join {name}`.',
    '**{name}** — you got {gold} gold + {exp} EXP': '**{name}** — kamu dapat {gold} gold + {exp} EXP',
    '**{name}**: {desc}\nEvent boss: {boss} • Event stock: {shop}': '**{name}**: {desc}\nBoss event: {boss} • Stok event: {shop}',
    '**{w}** beat **{l}**!\n+25 ranking points for the winner, -10 for the loser.': '**{w}** menang lawan **{l}**!\n+25 poin ranking buat pemenang, -10 buat yang kalah.',
    ', leveled up {n} levels!': ', naik {n} level!',
    'A complete RPG bot: create characters, pick classes, evolve jobs, fight monsters, raid bosses with your party, PVP, guild wars, crafting, gacha, pets, house & farm, dungeon puzzles, and story mode.\n\nCredit by NEWR LABS': 'Bot RPG lengkap: daftar karakter, pilih kelas, evolusi job, lawan monster, raid boss bareng party, PVP, guild war, crafting, gacha, pet, rumah & kebun, dungeon puzzle, sampai story mode.\n\nCredit by NEWR LABS',
    'A meteor fell near you and left behind **{item}**!': 'Sebuah meteor jatuh di dekatmu dan meninggalkan **{item}**!',
    'Accept': 'Terima',
    'Adoption needs {cost} gold.': 'Adopsi butuh {cost} gold.',
    'All commands here are slash commands.\n\n**Basics:** `/register` `/profile` `/evolve` `/daily` `/inventory` `/map` `/quest`\n**Battle:** `/fight` `/raid` `/pvp` `/arena` `/guildwar`\n**Economy:** `/shop` `/blackmarket` `/craft` `/gacha` `/trade` `/tradeboard`\n**Pet:** `/pet` `/petgear`\n**Survival:** `/status` `/eat` `/drink` `/repair`\n**Social:** `/guild` `/guildquest` `/guildbuff` `/party`\n**Premium & Event:** `/vip` `/vipgrant` `/ranking` `/event`\n**Fun & Games:** `/casino` `/job` `/house` `/dungeon` `/meteor` `/story`\n\nStart with `/register`, claim `/daily`, then `/fight` to level up!\nNEWR Adventure by NEWR LABS': 'Semua perintah di sini adalah slash command.\n\n**Dasar:** `/register` `/profile` `/evolve` `/daily` `/inventory` `/map` `/quest`\n**Battle:** `/fight` `/raid` `/pvp` `/arena` `/guildwar`\n**Ekonomi:** `/shop` `/blackmarket` `/craft` `/gacha` `/trade` `/tradeboard`\n**Pet:** `/pet` `/petgear`\n**Survival:** `/status` `/eat` `/drink` `/repair`\n**Sosial:** `/guild` `/guildquest` `/guildbuff` `/party`\n**Premium & Event:** `/vip` `/vipgrant` `/ranking` `/event`\n**Seru-seruan:** `/casino` `/job` `/house` `/dungeon` `/meteor` `/story`\n\nMulai dari `/register`, klaim `/daily`, lalu `/fight` buat naik level!\nNEWR Adventure by NEWR LABS',
    'All your gear is still in perfect shape, no repair needed!': 'Semua gear kamu masih mulus, nggak perlu repair!',
    'Animals you can raise: chicken (150 gold), cow (400 gold).': 'Hewan yang bisa dipelihara: ayam (150 gold), sapi (400 gold).',
    "Area '{area}' doesn't exist. Check `/map list`.": "Area '{area}' nggak ada. Cek `/map list`.",
    "Area '{area}' isn't unlocked / doesn't exist. Your areas: {areas}.": "Area '{area}' belum kebuka / nggak ada. Area kamu: {areas}.",
    'Attention': 'Perhatian',
    'Available seeds: Wheat Seeds, Tomato Seeds, Pumpkin Seeds. Buy at `/shop`.': 'Benih yang ada: benih gandum, benih tomat, benih labu. Beli di `/shop`.',
    'Available species: {species}.': 'Spesies yang ada: {species}.',
    'Bets must be 10 to 500 gold.': 'Taruhan minimal 10 gold, maksimal 500 gold ya.',
    'Boss **{boss}** appeared with {hp} HP! Join with `/raid join`, then `/raid hit` together!': 'Boss **{boss}** muncul dengan {hp} HP! Gabung pakai `/raid join`, lalu `/raid hit` bareng-bareng!',
    "Bots can't duel.": 'Bot nggak bisa duel.',
    'Building a house needs 300 gold.': 'Bangun rumah butuh 300 gold.',
    'Buy with `/shop buy <item name> <amount>`.': 'Beli pakai `/shop buy <nama item> <jumlah>`.',
    'CORRECT! Treasure unlocked: {gold} gold + {item}!': 'BENAR! Harta terbuka: {gold} gold + {item}!',
    "Can't evolve yet! {name} needs level {lvl}, you're still Lv {clvl}.": 'Belum bisa evolusi! {name} butuh level {lvl}, kamu masih Lv {clvl}.',
    'Choose an area first, e.g. `/map explore Beginner Forest`.': 'Pilih area dulu, misal `/map explore Beginner Forest`.',
    'Choose an item below to use/equip.': 'Pilih item di bawah buat dipakai/dipasang.',
    'Choose an item...': 'Pilih item...',
    "Coin guess: 'heads' or 'tails'.": "Tebak koin: 'kepala' atau 'ekor'.",
    'Creating a guild needs {cost} gold.': 'Bikin guild butuh {cost} gold.',
    'Crops:\n{crops}\n\nAnimals:\n{animals}': 'Tanaman:\n{crops}\n\nHewan:\n{animals}',
    'Decline': 'Tolak',
    'Duel declined': 'Duel ditolak',
    "Enter (needs 15 stamina), answer the guardian's riddle, and grab treasure of 150-400 gold + a random item. Wrong answer? Try again, no penalty.": 'Masuk (butuh 15 stamina), jawab teka-teki penjaga, dan rebut harta 150-400 gold + item acak. Jawaban salah? Coba lagi, nggak ada penalti.',
    'Equip': 'Pasang',
    'Equipped gear:': 'Gear terpasang:',
    'Garden full! (capacity {slots}, upgrade the house to add slots.)': 'Kebun penuh! (kapasitas {slots}, naikkan level rumah buat nambah slot.)',
    'Gear removed from {name}: {items}.': 'Gear dilepas dari {name}: {items}.',
    'Give the party a name first.': 'Kasih nama party dulu.',
    "Guild '{guild}' not found.": "Guild '{guild}' nggak ketemu.",
    "Guild '{name}' not found.": "Guild '{name}' nggak ketemu.",
    'Guild level {lv} gives: {buff}\nATK/DEF bonuses are active in battle, EXP bonus is active when gaining EXP.\nRaise guild level with member daily claims & guild war wins.': 'Level guild {lv} memberi: {buff}\nBonus ATK/DEF aktif saat bertarung, bonus EXP aktif saat dapat EXP.\nNaikkan level guild dengan klaim daily anggota & menang guild war.',
    'Guild names must be 1-24 characters.': 'Nama guild 1-24 karakter ya.',
    'House Lv 1 built! Now you can plant with `/house plant <seed>` and raise animals with `/house animal <ayam/sapi>`.': 'Rumah Lv 1 dibangun! Sekarang bisa tanam pakai `/house plant <benih>` dan pelihara hewan pakai `/house animal <ayam/sapi>`.',
    'House upgraded to Lv {lv}! Your garden got bigger.': 'Rumah naik ke Lv {lv}! Kebunmu makin luas.',
    'ID {id} — **{name}** ({form}, Lv {lv})\n{expbar}\nSkill: {skill} • ATK Bonus: {atk}': 'ID {id} — **{name}** ({form}, Lv {lv})\n{expbar}\nSkill: {skill} • Bonus ATK: {atk}',
    'ID {id}: {frm} offers {oi} x{oq}, asks {wi} x{wq} from {to}': 'ID {id}: {frm} tawar {oi} x{oq} minta {wi} x{wq} dari {to}',
    'ID {id}: {item} x{qty} — {price} gold (by {seller})': 'ID {id}: {item} x{qty} — {price} gold (oleh {seller})',
    "Item '{item}' is unknown. Check `/inventory list` first.": "Item '{item}' nggak dikenal. Cek `/inventory list` dulu.",
    'Join first with `/raid join`.': 'Gabung dulu pakai `/raid join`.',
    'Leader: {leader}\nGuild level: {lv}\n{expbar}\nBuff: {buff}\nMembers ({n}): {members}': 'Leader: {leader}\nLevel guild: {lv}\n{expbar}\nBuff: {buff}\nAnggota ({n}): {members}',
    'Listing not found.': 'Listing nggak ketemu.',
    'Livestock produce collected: {items}.': 'Hasil ternak dikumpulkan: {items}.',
    "Lost... {detail} You lost {bet} gold. Total lost today: {lost}/2000 gold. Don't go overboard!": 'Kalah... {detail} Kamu kehilangan {bet} gold. Total rugi hari ini: {lost}/2000 gold. Jangan kalap ya!',
    'Members: {members}': 'Anggota: {members}',
    'Missing materials: {missing}.': 'Bahan kurang: {missing}.',
    'Monster **{m}** appeared in {area}! Choose your action:': 'Monster **{m}** muncul di {area}! Pilih aksimu:',
    'Name the opposing guild.': 'Sebutin nama guild lawan.',
    'Need {price} gold to buy {animal}.': 'Butuh {price} gold buat beli {animal}.',
    'No active raid yet. Start one with `/raid start`.': 'Belum ada raid aktif. Mulai pakai `/raid start`.',
    'No animals yet.': 'Belum ada hewan.',
    'No crops are ready to harvest yet.': 'Belum ada tanaman yang siap panen.',
    'No crops yet.': 'Belum ada tanaman.',
    'No gear equipped.': 'Belum ada gear terpasang.',
    'No pending trades.': 'Nggak ada trade pending.',
    'No seasonal event is active right now.\nEvents: **Halloween** (20-31 Oct), **Natal** (20-26 Dec), **Tahun Baru** (30 Dec-2 Jan).\nDuring an active event, the shop gets special stock and event bosses appear in `/raid`.': 'Saat ini tidak ada event musiman aktif.\nEvent yang ada: **Halloween** (20-31 Okt), **Natal** (20-26 Des), **Tahun Baru** (30 Des-2 Jan).\nSaat event aktif, toko dapat stok khusus dan boss event muncul di `/raid`.',
    'No {item} available to equip right now.': '{item} lagi nggak ada yang bisa dipasang.',
    'Nobody has dueled yet. Be the first with `/pvp`!': 'Belum ada yang duel. Jadilah yang pertama pakai `/pvp`!',
    'Nobody has joined yet.': 'Belum ada yang gabung.',
    'Not active': 'Tidak aktif',
    'Not done yet! Progress {prog}/{target}. Ask members to claim `/daily`.': 'Belum selesai! Progress {prog}/{target}. Ajak anggota klaim `/daily`.',
    'Not enough MP! Skills need 20 MP.': 'MP kurang! Butuh 20 MP buat skill.',
    'Not enough gold! Need {gold} for the crafting fee.': 'Gold kurang! Butuh {gold} buat ongkos craft.',
    'Not enough gold! Need {price}.': 'Gold kurang! Butuh {price}.',
    'Not enough gold! Need {total}, you have {gold}.': 'Gold kurang! Butuh {total}, kamu punya {gold}.',
    'Not enough gold! Repair needs {cost} gold, you have {gold}.': 'Gold kurang! Repair butuh {cost} gold, kamu punya {gold}.',
    'Not enough stamina (need 10). Stamina refills tomorrow.': 'Stamina kurang (butuh 10). Stamina penuh lagi besok.',
    'Not enough stamina (need 15).': 'Stamina kurang (butuh 15).',
    'Not enough stamina (need 5).': 'Stamina kurang (butuh 5).',
    'Not finished yet! Progress {prog}/{target}.': 'Belum selesai! Progress {prog}/{target}.',
    'Number guesses must be 1-10.': 'Tebakan angka harus 1-10.',
    'Only server admins can grant VIP.': 'Cuma admin server yang bisa memberi VIP.',
    'Only the challenged player can accept.': 'Cuma yang ditantang yang bisa terima.',
    'Only the challenged player can decline.': 'Cuma yang ditantang yang bisa menolak.',
    'Only the trade recipient can accept.': 'Cuma penerima trade yang bisa terima.',
    'Only the trade recipient can accept/decline.': 'Cuma penerima trade yang bisa terima/tolak.',
    'Only weapons and armor can be equipped.': 'Cuma senjata dan armor yang bisa dipasang.',
    "Party '{name}' not found.": "Party '{name}' nggak ketemu.",
    'Party **{name}** created! Parties with 2+ members get +10% raid damage.': 'Party **{name}** dibuat! Party beranggotakan 2+ orang dapat +10% damage raid.',
    'Pet ID not found. Check `/pet list`.': 'ID pet nggak ketemu. Cek `/pet list`.',
    'Pick another valid player.': 'Pilih pemain lain yang valid.',
    'Price must be > 0 gold.': 'Harga harus > 0 gold.',
    "Psst... don't tell anyone, ok.": 'Psst... jangan bilang-bilang ya.',
    'Quest: all members claim `/daily` a total of {target}x.\n{bar}\nReward per member: {reward} gold (claim with `/guildquest claim`).': 'Quest: semua anggota klaim `/daily` total {target}x.\n{bar}\nHadiah per anggota: {reward} gold (klaim pakai `/guildquest claim`).',
    'Shady deal done: {item} for {price} gold. Gold left: {gold}.': 'Transaksi gelap berhasil: {item} seharga {price} gold. Sisa gold: {gold}.',
    'Streak: **{n} days**\nYou got **{gold} gold** + 1x {item}.\nLonger streaks give bigger gold bonuses (max +200)!': 'Streak: **{n} hari**\nKamu dapat **{gold} gold** + 1x {item}.\nStreak makin panjang, bonus gold makin gede (maks +200)!',
    'Tell me the item name first.': 'Sebutin nama itemnya dulu ya.',
    'That guild name is already taken.': 'Nama guild itu sudah dipakai.',
    "That item doesn't exist / is out of stock today.": 'Item itu nggak ada / stok habis hari ini.',
    "That item isn't equipped / doesn't exist.": 'Item itu nggak terpasang / nggak ada.',
    "That item isn't sold in the shop.": 'Item itu nggak dijual di toko.',
    "That player hasn't registered a character.": 'Pemain itu belum daftar karakter.',
    "That trade doesn't exist / is already done.": 'Trade itu nggak ada / sudah selesai.',
    "That's not food/drink.": 'Itu bukan makanan/minuman.',
    "That's not pet gear. Pet gear: kalung pet, zirah pet, mahkota pet.": 'Itu bukan pet gear. Gear pet: kalung pet, zirah pet, mahkota pet.',
    "That's someone else's bag!": 'Ini tas orang lain!',
    "That's your own listing.": 'Itu listing kamu sendiri.',
    'The board is still empty. Sell an item with `/tradeboard sell`.': 'Papan masih kosong. Jual item pakai `/tradeboard sell`.',
    'The casino die shows **{result}**, your guess was {guess}.': 'Dadu kasino menunjukkan **{result}**, tebakanmu {guess}.',
    'The coin shows **{result}**, your guess was {guess}.': 'Koin menunjukkan **{result}**, tebakanmu {guess}.',
    'The last war was won by **{w}** (score {a} vs {b}).': 'War terakhir dimenangkan **{w}** (skor {a} vs {b}).',
    'The offerer no longer has the item.': 'Penawar sudah nggak punya itemnya lagi.',
    'The sky is still calm (now {now} WIB). Meteor showers only happen 21:00-21:59 WIB!': 'Langit masih tenang (sekarang {now} WIB). Meteor shower cuma jam 21:00-21:59 WIB!',
    'The treasure guardian asks:\n**{q}**\n\nAnswer with `/dungeon answer <answer>`.': 'Penjaga harta bertanya:\n**{q}**\n\nJawab pakai `/dungeon answer <jawaban>`.',
    "There's already an active raid: **{boss}** ({hp}/{maxhp} HP). Just join!": 'Sudah ada raid aktif: **{boss}** ({hp}/{maxhp} HP). Gabung aja!',
    "This chapter needs Lv {lv}, you're still Lv {plv}. Grind first!": 'Chapter ini butuh Lv {lv}, kamu masih Lv {plv}. Grinding dulu!',
    "This is someone else's fight!": 'Ini pertarungan orang lain!',
    'This quest is already claimed.': 'Quest ini sudah diklaim.',
    "This week's top 3 can claim rewards with `/ranking claim`.": 'Top 3 minggu ini bisa klaim hadiah pakai `/ranking claim`.',
    'Tired! Rest first, work again in {left} minutes.': 'Capek! Istirahat dulu, kerja lagi dalam {left} menit.',
    "Today's daily is already claimed, come back tomorrow!": 'Daily hari ini sudah diklaim, balik lagi besok ya!',
    'Trade declined.': 'Trade ditolak.',
    'Training a pet needs 50 gold.': 'Latih pet butuh 50 gold.',
    'Type: {tipe}{bonus} • Shop price: {harga} gold. Choose an action below.': 'Tipe: {tipe}{bonus} • Harga toko: {harga} gold. Pilih aksi di bawah.',
    'Unequip': 'Lepas',
    'Unknown item name.': 'Nama item nggak dikenal.',
    'Unknown item.': 'Item nggak dikenal.',
    'Unknown quest ID. Check `/quest list`.': 'ID quest nggak dikenal. Cek `/quest list`.',
    'Unknown recipe. Available recipes: {recipes}.': 'Resep nggak dikenal. Resep yang ada: {recipes}.',
    'Upgrading the house needs {cost} gold.': 'Naik level rumah butuh {cost} gold.',
    'Use': 'Pakai',
    'VIP granted to **{name}** until {until} (30 days).': 'VIP diberikan ke **{name}** sampai {until} (30 hari).',
    'WIN! {detail} You got {payout} gold (profit {profit}).': 'MENANG! {detail} Kamu dapat {payout} gold (untung {profit}).',
    'War **{a}** vs **{b}** is still running, results come out in {n} more minutes.': 'War **{a}** vs **{b}** masih berjalan, hasil keluar dalam {n} menit lagi.',
    'War against that guild is already declared, wait for the result.': 'War sama guild itu sudah dideklarasi, tunggu hasilnya.',
    'Winner: **{w}**! The winning guild gets +150 guild EXP, all its members +100 gold.': 'Pemenang: **{w}**! Guild pemenang +150 guild EXP, semua anggotanya +100 gold.',
    'Wrong answer, try again! (No penalty.)': 'Jawaban salah, coba lagi! (Nggak ada penalti kok.)',
    'You adopted **{name}** ({species})!\nUnique skill: **{skill}**.\nPets join fights and add damage. Train with `/pet train`.': 'Kamu mengadopsi **{name}** ({species})!\nSkill unik: **{skill}**.\nPet ikut bertarung dan nambah damage. Latih pakai `/pet train`.',
    'You already have a house. Upgrade with `/house upgrade`.': 'Rumah kamu sudah ada. Tingkatkan pakai `/house upgrade`.',
    "You aren't raising any animals yet.": 'Kamu belum pelihara hewan.',
    'You attack: -{dmg} HP!': 'Kamu menyerang: -{dmg} HP!',
    'You bought {item} x{qty} for {price} gold!': 'Kamu beli {item} x{qty} seharga {price} gold!',
    'You bought {item} x{qty} for {total} gold. Gold left: {gold}.': 'Kamu beli {item} x{qty} seharga {total} gold. Sisa gold: {gold}.',
    "You can't duel yourself, bro.": 'Nggak bisa duel sama diri sendiri, bro.',
    "You can't war against your own guild.": 'Nggak bisa perang sama guild sendiri.',
    'You consumed {item}!': 'Kamu konsumsi {item}!',
    "You don't have a character yet! Register first with `/register`.": 'Kamu belum punya karakter! Daftar dulu pakai `/register` ya.',
    "You don't have a house yet. Build one first with `/house build` (300 gold).": 'Kamu belum punya rumah. Bangun dulu pakai `/house build` (300 gold).',
    "You don't have a pet yet.": 'Kamu belum punya pet.',
    "You don't have a pet yet. Adopt with `/pet adopt <species>`.": 'Kamu belum punya pet. Adopsi pakai `/pet adopt <spesies>`.',
    "You don't have any potions! Buy at `/shop`.": 'Kamu nggak punya potion! Beli di `/shop`.',
    "You don't have enough gold for that bet.": 'Gold kamu kurang buat taruhan itu.',
    "You don't have enough of the offered item.": 'Kamu nggak punya cukup item tawaran.',
    "You don't have enough of the requested item.": 'Kamu nggak punya cukup item yang diminta.',
    "You don't have enough stock.": 'Stok kamu kurang.',
    "You don't have that much in stock.": 'Stok kamu kurang dari itu.',
    "You don't have {item}.": 'Kamu nggak punya {item}.',
    'You drank a potion: +{heal} HP!': 'Kamu minum potion: +{heal} HP!',
    'You fled the fight. No rewards, no wounds.': 'Kamu kabur dari pertarungan. Nggak ada hadiah, nggak ada luka.',
    'You found **{item}** lying around in {area}!': 'Kamu nemu **{item}** tergeletak di {area}!',
    'You found an old chest in {area}: **{gold} gold**!': 'Kamu nemu peti tua di {area}: **{gold} gold**!',
    'You got **{item}**.': 'Kamu dapat **{item}**.',
    'You got: {items}.': 'Kamu dapat: {items}.',
    "You haven't entered a dungeon yet. Use `/dungeon enter` first.": 'Kamu belum masuk dungeon. Pakai `/dungeon enter` dulu.',
    "You haven't made this week's top 3 yet. Keep grinding!": 'Kamu belum masuk top 3 minggu ini. Semangat grinding!',
    'You joined guild **{name}**! Active buff: {buff}.': 'Kamu gabung guild **{name}**! Buff aktif: {buff}.',
    'You joined party **{name}**!': 'Kamu gabung party **{name}**!',
    'You joined the **{boss}** raid! Attack with `/raid hit`.': 'Kamu gabung raid **{boss}**! Serang pakai `/raid hit`.',
    'You left the guild.': 'Kamu keluar dari guild.',
    'You left the party.': 'Kamu keluar dari party.',
    'You met **{m}** and fled wounded... -{lost} HP.': 'Kamu ketemu **{m}** dan kabur dengan luka... -{lost} HP.',
    'You met **{m}** and won! +{e} EXP, +{g} gold': 'Kamu ketemu **{m}** dan menang! +{e} EXP, +{g} gold',
    'You pulled {n}x (paid {cost} gold):': 'Kamu tarik {n}x (bayar {cost} gold):',
    'You smashed **{boss}** for {dmg} damage! Boss HP left: {newhp}.': 'Kamu menghantam **{boss}** sebesar {dmg} damage! Sisa HP boss: {newhp}.',
    'You worked as {job}: got {gold} gold + {item} x{qty}!': 'Kamu kerja jadi {job}: dapat {gold} gold + {item} x{qty}!',
    "You're already at the highest evolution, awesome!": 'Kamu sudah di evolusi tertinggi, keren banget!',
    "You're already fighting! Finish it first.": 'Kamu lagi bertarung! Selesaikan dulu.',
    "You're already in a guild.": 'Kamu sudah di guild.',
    "You're already in a guild. Leave first if you want to create a new one.": 'Kamu sudah di guild. Keluar dulu kalau mau bikin baru.',
    "You're already in a party.": 'Kamu sudah di party.',
    "You're not in a guild yet. Create one with `/guild create <name>`.": 'Kamu belum di guild. Buat pakai `/guild create <nama>`.',
    "You're not in a guild yet. Create/join one with `/guild`.": 'Kamu belum masuk guild. Buat/gabung dulu pakai `/guild`.',
    "You're not in a guild.": 'Kamu belum di guild.',
    "You're not in a party yet.": 'Kamu belum di party.',
    "You're not in any guild.": 'Kamu nggak di guild mana-mana.',
    "You're not in any party.": 'Kamu nggak di party mana-mana.',
    "You're out of stamina! Stamina refills tomorrow.": 'Stamina kamu habis! Stamina penuh lagi besok.',
    "You're raising {animal}! Collect its produce with `/house collect`.": 'Kamu memelihara {animal}! Kumpulkan hasilnya pakai `/house collect`.',
    "You're rank #{rank} this week! Reward: {gold} gold + {item}.": 'Kamu peringkat #{rank} minggu ini! Hadiah: {gold} gold + {item}.',
    "You've already caught a meteor today. Come back tomorrow at 21:00 WIB!": 'Kamu sudah menangkap meteor hari ini. Balik lagi besok jam 21:00 WIB!',
    "You've already claimed this week's guild quest reward.": 'Kamu sudah klaim hadiah guild quest minggu ini.',
    "You've already claimed this week's ranking reward.": 'Kamu sudah klaim hadiah ranking minggu ini.',
    "Your HP and MP are already full, don't waste the potion!": 'HP dan MP kamu sudah penuh, sayang potionnya!',
    'Your HP is 0! Use a potion from `/inventory` first.': 'HP kamu 0! Pakai potion dulu dari `/inventory`.',
    "Your VIP isn't active yet.\nVIP benefits: EXP x1.5, gold x1.25, better loot & gacha odds.\nVIP on this server is granted by admins with `/vipgrant` (no payment).": 'VIP kamu belum aktif.\nBenefit VIP: EXP x1.5, gold x1.25, peluang loot & gacha lebih bagus.\nVIP di server ini diberikan admin pakai `/vipgrant` (tanpa pembayaran).',
    "Your animals haven't produced again yet. Check again in 6 hours.": 'Hewan-hewanmu belum menghasilkan lagi. Cek lagi 6 jam lagi ya.',
    'Your bag is empty. Buy something at `/shop` first!': 'Tas kamu kosong. Beli di `/shop` dulu gih!',
    'Your daily loss limit (2000 gold) is almost used up, take a break.': 'Limit rugi harian kamu (2000 gold) sudah mau habis, istirahat dulu ya.',
    'Your guild has never warred. Declare with `/guildwar challenge <guild name>`.': 'Guild kamu belum pernah war. Deklarasi pakai `/guildwar challenge <nama guild>`.',
    'ready to harvest!': 'siap panen!',
    '{crop} planted! Ready to harvest in {n} minutes.': '{crop} ditanam! Siap panen dalam {n} menit.',
    "{item} can't be used directly. Weapons/armor are equipped, seeds are planted at `/house`.": '{item} nggak bisa dipakai langsung. Senjata/armor dipasang, benih ditanam di `/house`.',
    "{item} doesn't quench thirst, that's food.": '{item} nggak menghilangkan haus, itu makanan.',
    '{item} equipped to {name}': '{item} dipasang ke {name}',
    "{item} isn't equipped right now.": '{item} lagi nggak terpasang.',
    "{item} isn't filling, that's a drink.": '{item} nggak mengenyangkan, itu minuman.',
    '{item} unequipped.': '{item} dilepas.',
    '{item} x{qty} listed on the tradeboard for {price} gold (ID {id}).': '{item} x{qty} dipajang di tradeboard seharga {price} gold (ID {id}).',
    '{i}. **{name}** — {points} points (W {w} / L {l})': '{i}. **{name}** — {points} poin (W {w} / L {l})',
    '{match} is still locked! Requires Lv {n}.': '{match} masih terkunci! Butuh Lv {n}.',
    "{mention}, you've been offered a trade!\n**{name}** offers {oi} x{oq} and asks for {wi} x{wq}.\nAccept/decline with the buttons below, or use `/trade accept {tid}`.": '{mention}, kamu ditawari trade!\n**{name}** menawarkan {oi} x{oq} dan meminta {wi} x{wq}.\nTerima/tolak lewat tombol di bawah, atau pakai `/trade accept {tid}`.',
    '{m} strikes back: -{dmg} HP!': '{m} menyerang balik: -{dmg} HP!',
    '{names} fully repaired! Cost {cost} gold. Gold left: {gold}.': '{names} diperbaiki full! Biaya {cost} gold. Sisa gold: {gold}.',
    '{name} declined the duel.': '{name} menolak duel.',
    "{name} isn't wearing any gear right now.": '{name} lagi nggak pakai gear.',
    '{name} trained (+40 EXP)!': '{name} dilatih (+40 EXP)!',
    '{n} more minutes': '{n} menit lagi',
    '☄️ METEOR SHOWER!': '☄️ HUJAN METEOR!',
    '☄️ Meteor': '☄️ Meteor',
    '⚔️ Attack': '⚔️ Serang',
    '⚔️ Duel Challenge!': '⚔️ Tantangan Duel!',
    '⚔️ Duel Result': '⚔️ Hasil Duel',
    '⚔️ Fight Over': '⚔️ Pertarungan selesai',
    '⚔️ Guild War': '⚔️ Guild War',
    '⚔️ Guild War Declared!': '⚔️ Guild War dideklarasi!',
    '⚔️ {item} equipped!': '⚔️ {item} terpasang!',
    "⚠️ Hungry! Eat with `/eat` so your HP doesn't drain.": '⚠️ Lapar! Makan dulu pakai `/eat` biar HP kamu nggak kekuras.',
    '⚠️ Oops!': '⚠️ Ups!',
    "⚠️ Thirsty! Drink with `/drink` so your HP doesn't drain.": '⚠️ Haus! Minum dulu pakai `/drink` biar HP kamu nggak kekuras.',
    '✅ Accept Duel': '✅ Terima Duel',
    '✅ Active until {until}': '✅ Aktif sampai {until}',
    '✅ claimed': '✅ diklaim',
    '✨ EVOLUTION!': '✨ EVOLUSI!',
    '✨ Evolution': '✨ Evolusi',
    '✨ Guild Buff {name}': '✨ Buff Guild {name}',
    '❌ Decline': '❌ Tolak',
    '🌱 Garden': '🌱 Kebun',
    '🌾 Harvest': '🌾 Panen',
    '🍗 Hunger': '🍗 Lapar',
    '🍽️ Eat/Drink': '🍽️ Makan/Minum',
    '🍽️ You ate/drank {item}! Hunger {hunger}/100, Thirst {thirst}/100.': '🍽️ Kamu makan/minum {item}! Lapar {hunger}/100, Haus {thirst}/100.',
    '🎁 ready to claim!': '🎁 siap klaim!',
    '🎉 Active Event!': '🎉 Event Aktif!',
    '🎉 Dungeon Treasure!': '🎉 Harta Dungeon!',
    '🎉 Guild quest reward: {reward} gold for you!': '🎉 Hadiah guild quest: {reward} gold buat kamu!',
    '🎉 Party': '🎉 Party',
    '🎉 Party {name}': '🎉 Party {name}',
    '🎉 Quest Complete!': '🎉 Quest selesai!',
    '🎉 Seasonal Event': '🎉 Event Musiman',
    '🎉 VICTORY! +{e} EXP, +{g} gold': '🎉 MENANG! +{e} EXP, +{g} gold',
    '🎒 Empty Bag': '🎒 Tas kosong',
    '🎒 Inventory': '🎒 Inventory',
    "🎬 You've finished all available chapters! Wait for the next story update.": '🎬 Kamu sudah menamatkan semua chapter yang ada! Tunggu update cerita berikutnya.',
    '🎰 Casino': '🎰 Kasino',
    '🎰 Gacha!': '🎰 Gacha!',
    '🏃 Flee': '🏃 Kabur',
    '🏆 Arena Ranking': '🏆 Arena Ranking',
    '🏆 Guild War Over!': '🏆 Guild War selesai!',
    '🏆 Ranking': '🏆 Ranking',
    '🏆 Top Player Ranking': '🏆 Ranking Top Player',
    '🏠 House': '🏠 Rumah',
    '🏠 House Lv {lv}': '🏠 Rumah Lv {lv}',
    '🏰 Dungeon': '🏰 Dungeon',
    '🏰 Guild': '🏰 Guild',
    '🏰 Guild Created!': '🏰 Guild dibuat!',
    '🏰 Guild Quest': '🏰 Guild Quest',
    '🏰 Guild {name}': '🏰 Guild {name}',
    "🏰 This Week's Guild Quest": '🏰 Guild Quest Minggu Ini',
    '🏰 You enter the dungeon...': '🏰 Kamu masuk dungeon...',
    '🐉 RAID STARTED!': '🐉 RAID DIMULAI!',
    '🐉 Raid': '🐉 Raid',
    '🐔 Livestock': '🐔 Ternak',
    '🐾 New Pet!': '🐾 Pet baru!',
    '🐾 Pet Gear': '🐾 Pet Gear',
    '🐾 Pet Training': '🐾 Latihan Pet',
    '🐾 Your Pets': '🐾 Pet kamu',
    '👑 Your VIP is ACTIVE until {until}.\nBenefits: EXP x1.5, gold x1.25, better loot & gacha odds.': '👑 VIP kamu AKTIF sampai {until}.\nBenefit: EXP x1.5, gold x1.25, peluang loot & gacha lebih bagus.',
    '💀 DEFEAT... {m} is too strong. You lost {lost} gold, HP restored to {hp}.': '💀 KALAH... {m} terlalu kuat. Kamu kehilangan {lost} gold, HP dipulihkan ke {hp}.',
    '💀 Your HP is 0! Use a potion from `/inventory` so you can fight again.': '💀 HP kamu 0! Pakai potion dari `/inventory` biar bisa bertarung lagi.',
    '💚 Status of {name}': '💚 Status {name}',
    '💧 Thirst': '💧 Haus',
    '📋 Tradeboard': '📋 Tradeboard',
    '📖 Chapter {n} complete: {title}': '📖 Chapter {n} selesai: {title}',
    '📖 NEWR Adventure Help': '📖 Bantuan NEWR Adventure',
    '📖 Story': '📖 Story',
    '📖 Story Chapter {n}: {title}': '📖 Story Chapter {n}: {title}',
    '📖 Story chapter: {ch} • 🏠 House Lv {lv}': '📖 Story chapter: {ch} • 🏠 Rumah Lv {lv}',
    '📜 Quests': '📜 Quest',
    '🔄 Pending Trades': '🔄 Trade pending',
    '🔄 Trade': '🔄 Trade',
    '🔄 Trade Offer': '🔄 Tawaran Trade',
    '🔄 Trade successful! You got {item} x{qty}.': '🔄 Trade berhasil! Kamu dapat {item} x{qty}.',
    '🔒 (requires Lv {n})': '🔒 (butuh Lv {n})',
    '🔥 Daily streak: {n} days': '🔥 Streak daily: {n} hari',
    '🔧 Repair': '🔧 Repair',
    '🔨 Craft Successful!': '🔨 Craft berhasil!',
    '🕶️ Black Market (resets daily)': '🕶️ Black Market (reset tiap hari)',
    '🗑️ {item} x{n} discarded.': '🗑️ {item} x{n} dibuang.',
    '🗺️ World Map': '🗺️ Peta Dunia',
    '🛒 Purchase Successful': '🛒 Pembelian berhasil',
    '🛒 Shop': '🛒 Toko',
    '🥚 Livestock': '🥚 Ternak',
    '🧪 You used {item}! HP now {hp}/{maxhp}, MP {mp}/{maxmp}.': '🧪 Kamu pakai {item}! HP sekarang {hp}/{maxhp}, MP {mp}/{maxmp}.',
    '🪓 Work': '🪓 Kerja',
}

# Extra central-path strings added during wiring (English -> ID).
ID_EXTRA = {
    "🎮 Character Created!": "🎮 Karakter dibuat!",
    "Welcome, **{name}** the {cls}!": "Selamat datang, **{name}** si {cls}!",
    "Starter tier: **{tier}** (+{pct}% stats)": "Tier starter: **{tier}** (+{pct}% stat)",
    "Starting skill: **{skill}**": "Skill awal: **{skill}**",
    "Stats: HP {hp} • MP {mp} • ATK {atk} • DEF {df} • SPD {spd}": "Stat: HP {hp} • MP {mp} • ATK {atk} • DEF {df} • SPD {spd}",
    "Starter pack: {pack}": "Kamu dapat starter pack: {pack}",
    "First steps: `/daily` for daily rewards, then `/fight` to hunt!": "Langkah awal: `/daily` buat hadiah harian, lalu `/fight` buat berburu!",
    "You already have a character! Check with `/profile`.": "Kamu sudah punya karakter! Cek dengan `/profile`.",
    "Character names must be 1-24 characters.": "Nama karakter harus 1-24 karakter.",
    "Warning": "Peringatan",
    "🌐 Language set": "🌐 Bahasa diatur",
    "Your replies will now use {label}.": "Balasan untukmu sekarang memakai {label}.",
    "Unknown language. Please pick one from the suggestions.": "Bahasa tidak dikenal. Silakan pilih dari saran yang muncul.",
}
ID_TABLE.update(ID_EXTRA)


# Admin-only strings (English -> Indonesian), offline.
ADMIN_ID_TABLE = {
    "This command is for staff only (server Administrators or granted bot-admins). Regular members cannot use the admin bot.": "Perintah ini hanya untuk staff (Administrator server atau bot-admin yang diberi akses). Anggota biasa tidak bisa memakai bot admin.",
    "This command is for Discord server Administrators only. Bot-admins cannot use it.": "Perintah ini hanya untuk Administrator server Discord. Bot-admin tidak bisa memakainya.",
    "Amount must be filled in and cannot be negative.": "Jumlah harus diisi dan tidak boleh negatif.",
    "Minimum amount is 1.": "Jumlah minimal 1.",
    "Rate must be 1\u20131000 percent (0.01x\u201310x).": "Rate harus 1\u20131000 persen (0.01x\u201310x).",
    "That player hasn't registered for the RPG.": "Pemain itu belum daftar RPG.",
    "That user doesn't have a character yet.": "User itu belum punya karakter.",
    "That user is already a Discord Administrator, so they do not need bot-admin.": "User itu sudah Administrator Discord, jadi tidak perlu bot-admin.",
    "Pick an event first for the start/stop action.": "Pilih event dulu untuk aksi start/stop.",
    "Pick a player first for the gold action.": "Pilih pemain dulu untuk aksi gold.",
    "Failed: player hasn't registered for the RPG, or gold would go negative.": "Gagal: pemain belum daftar RPG, atau gold akan jadi negatif.",
    "Fill in giveaway_id first to draw.": "Isi giveaway_id dulu untuk mengundi.",
    "Giveaway #{id} not found.": "Giveaway #{id} tidak ditemukan.",
    "Giveaway #{id} has already been drawn.": "Giveaway #{id} sudah diundi.",
    "No players can be drawn.": "Tidak ada pemain yang bisa diundi.",
    "Total gold and winners must be \u2265 1.": "Total gold dan pemenang harus \u2265 1.",
    "Tax pool changed mid-draw \u2014 try again.": "Tax pool berubah saat pengundian \u2014 coba lagi.",
    "Reset is permanent. To confirm, fill in confirmation with exactly RESET.": "Reset bersifat permanen. Untuk konfirmasi, isi confirmation dengan tepat RESET.",
    "The bot doesn't have permission to send to that channel.": "Bot tidak punya izin mengirim ke channel itu.",
    "Fill in percent (0-50) for set_rate.": "Isi percent (0-50) untuk set_rate.",
    "Tax percent must be 0-50.": "Persen tax harus 0-50.",
    "Pick a player first for grant/revoke.": "Pilih pemain dulu untuk grant/revoke.",
    "Write the new rules text first.": "Tulis teks rules baru dulu.",
    "Amount, winners, and duration must be \u2265 1.": "Jumlah, pemenang, dan durasi harus \u2265 1.",
    "Prize item name is unknown.": "Nama item hadiah tidak dikenal.",
    "No bot-admins granted yet.": "Belum ada bot-admin yang diberi akses.",
    "No data for this metric yet.": "Belum ada data untuk metrik ini.",
    "No log entries match.": "Tidak ada log yang cocok.",
    "Unknown info topic.": "Topik info tidak dikenal.",
    "\U0001f3aa Event Updated": "\U0001f3aa Event diperbarui",
    "\U0001f4dc RPG Rules": "\U0001f4dc Rules RPG",
    "\U0001f4b0 Gold Updated": "\U0001f4b0 Gold diperbarui",
    "\U0001f381 Item/Pet Given": "\U0001f381 Item/Pet diberikan",
    "\U0001f389 Giveaway Drawn": "\U0001f389 Giveaway diundi",
    "\U0001f4b0 Tax Giveaway Drawn": "\U0001f4b0 Tax giveaway diundi",
    "\u267b\ufe0f Player Reset": "\u267b\ufe0f Pemain di-reset",
    "\U0001f4ca RPG Server Statistics": "\U0001f4ca Statistik server RPG",
    "\U0001f4e2 Announcement Sent": "\U0001f4e2 Pengumuman terkirim",
    "\U0001f4c5 New Season Started": "\U0001f4c5 Season baru dimulai",
    "\U0001f3c6 Achievement Granted": "\U0001f3c6 Achievement diberikan",
    "\U0001f3c6 Achievement Already Owned": "\U0001f3c6 Achievement sudah dimiliki",
    "\U0001f4dc Lifetime Leaderboard": "\U0001f4dc Leaderboard lifetime",
    "\U0001f4b0 Market Tax Rate Stored": "\U0001f4b0 Rate tax market tersimpan",
    "\U0001f4cb Recent Admin Logs": "\U0001f4cb Log admin terbaru",
    "\U0001f6e1\ufe0f Bot-Admins": "\U0001f6e1\ufe0f Bot-admin",
    "\U0001f4cb Admin Logs": "\U0001f4cb Log admin",
}
ID_TABLE.update(ADMIN_ID_TABLE)

KNOWN = set(ID_TABLE)
