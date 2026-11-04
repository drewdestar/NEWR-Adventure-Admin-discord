# SETUP — NEWR Adventure Admin (bot staff NEWR Adventure)

Bot admin ini mengelola bot pemain **NEWR Adventure** di server NEWR LABS
(guild ID 1465422166790242377). Credit: by NEWR LABS. Bot admin adalah
aplikasi Discord KEDUA yang terpisah — jangan pakai token bot NEWR Adventure
untuk bot ini, dan sebaliknya.

## 1. Buat aplikasi Discord kedua

1. Buka https://discord.com/developers/applications → New Application,
   misal namanya `NEWR Adventure Admin`.
2. Catat Application ID (= CLIENT_ID untuk link invite).
3. Menu Bot → Add Bot → salin tokennya. **Jangan pernah tempel token di
   chat, kode, atau file lain selain `.env`.**

## 2. Isi token di VM

```bash
cp ~/workspace/bots/rpg-admin/.env.example ~/workspace/bots/rpg-admin/.env
chmod 600 ~/workspace/bots/rpg-admin/.env
# di dalam .env: DISCORD_TOKEN=<token bot admin yang asli>
# GUILD_ID sudah berisi 1465422166790242377 (NEWR LABS)
```

## 3. Invite ke NEWR LABS

Buka di browser (ganti CLIENT_ID dengan Application ID bot admin):

```
https://discord.com/oauth2/authorize?client_id=CLIENT_ID&permissions=84032&scope=bot%20applications.commands&guild_id=1465422166790242377
```

Pilih server NEWR LABS, authorize. Bot admin tidak butuh role khusus:
semua command-nya memeriksa permission Administrator Discord milik pemakai,
jadi member biasa otomatis ditolak.

## 4. Jalankan

```bash
bash ~/workspace/bots/ops/run-rpg-admin.sh
```

Lalu tes di NEWR LABS dari akun Administrator: `/admin_help`,
`/admin_stats`. Tanpa token, bot berhenti bersih dengan pesan error
(exit 1) — itu normal, bukan crash.

## 5. Akses: Administrator saja (bukan role kustom)

Semua command memeriksa `guild_permissions.administrator`. Kalau nanti
diinginkan gate berbasis role (mis. role Staff), tambahkan pengecekan role
di fungsi `require_staff` di `cogs/admin.py` — tidak perlu mengubah
command lain.

## 6. Patch integrasi (PENTING, jujur) — supaya setting admin benar-benar berlaku di bot NEWR Adventure

Bot admin ini sengaja TIDAK mengubah bot NEWR Adventure. Tabel-tabel
admin sudah dibuat di database bersama (`rpg.db`): `admin_events`,
`admin_rates`, `admin_rules`, `admin_bans`, `giveaways`. Tapi bot
NEWR Adventure saat ini belum membacanya:

- **Event (`admin_events`).** Bot NEWR Adventure menentukan event dari
  tanggal kalender (`logic.active_events`). Patch: di `active_events`,
  tambahkan juga event yang `state='active'` di `admin_events`, dan
  abaikan event kalender yang `state='inactive'` di `admin_events`.
- **Rate (`admin_rates`).** Bot NEWR Adventure menghitung reward tanpa
  rate. Patch: di `cogs/common.py` fungsi `reward`, kalikan gold dan EXP
  dengan `gold_mult` / `exp_mult` dari `admin_rates` (id=1).
- **Ban (`admin_bans`).** Bot NEWR Adventure tidak memeriksa ban. Patch:
  di `cogs/common.py` fungsi `need_player`, tolak pemain yang ada di
  `admin_bans` dengan pesan "akun kamu di-ban".
- **Rules (`admin_rules`).** Bot NEWR Adventure belum punya command baca
  rules. Patch opsional: tambah command pemain `/rules` yang membaca
  `admin_rules` (atau tampilkan teks default kalau kosong).
- **Giveaway & currency & give item/pet.** Sudah berlaku penuh tanpa
  patch, karena langsung menulis tabel pemain/inventory/pet yang sama.

Sampai patch di atas diterapkan ke bot NEWR Adventure, panel admin tetap
berguna sebagai pencatat setting + eksekutor (gold, item, pet, giveaway,
reset, statistik, pengumuman), dan pesan catatan jujur ini juga muncul di
balasan command yang bersangkutan.

## 7. GitHub

Belum di-push, sesuai permintaan user ("nanti"). Proyek ini git-ready
(`.gitignore` mengecualikan `.env` dan log). Yang masuk repo nanti hanya
kode bot admin — TIDAK PERNAH file `rpg.db` live (berisi data pemain).

## 8. Berbagi satu database — aturan

- Jangan edit `rpg.db` manual selagi salah satu bot jalan.
- Jangan jalankan dua proses bot admin sekaligus (perebutan lock).
- Kalau bot NEWR Adventure dan bot admin jalan bersamaan, itu normal:
  keduanya memakai WAL + busy timeout 30 detik dan transaksi pendek.
