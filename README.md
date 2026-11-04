# NEWR Adventure Admin — bot staff untuk NEWR Adventure

**Credit by NEWR LABS.** Bot staff Discord yang mengelola bot NEWR Adventure
(bot pemain), khusus server NEWR LABS. Semua command slash, semua khusus
Administrator server — member biasa selalu ditolak.

## Hubungan dengan bot NEWR Adventure

- **Satu database, satu ekonomi.** Bot ini memakai file database yang sama
  dengan bot NEWR Adventure: `~/workspace/bots/rpg/rpg.db`. Gold, item, pet, dan
  pemain yang diubah di sini langsung terlihat di bot NEWR Adventure, dan sebaliknya.
  Tidak pernah ada mata uang kedua.
- **Dua bot, dua token, dua proses.** Bot admin dan bot NEWR Adventure adalah aplikasi
  Discord yang berbeda, dengan token masing-masing. Bot ini tidak mengubah
  kode atau skema bot NEWR Adventure.
- **Akses bersama yang aman.** Koneksi memakai WAL + busy timeout 30 detik
  dan transaksi pendek, supaya kedua bot tidak saling mengunci. Jangan
  mengedit `rpg.db` manual selagi salah satu bot jalan.

## Command (semua slash, semua khusus Administrator)

| Command | Fungsi |
|---|---|
| `/admin_help` | Daftar semua command admin |
| `/admin_event` | Lihat / mulai / hentikan event (Halloween, Natal, Tahun Baru, Meteor) |
| `/admin_rules` | Lihat / atur teks peraturan RPG |
| `/admin_currency` | Beri / ambil / set gold pemain; atur rate EXP & gold server |
| `/admin_give` | Beri item atau pet ke pemain |
| `/admin_giveaway` | Buat / undi / lihat giveaway (hadiah gold atau item) |
| `/admin_player` | Lihat / reset / ban / unban pemain |
| `/admin_stats` | Total pemain, total gold beredar, pemain terkaya, giveaway terakhir |
| `/admin_announce` | Kirim pengumuman embed ke channel pilihan |

## Desain UI

Embed dengan warna konsisten per maksud (magenta admin, hijau sukses,
emas ekonomi, biru info, merah error), footer `NEWR Adventure by NEWR LABS`
di semua embed, dan balasan ephemeral untuk semua command admin (kecuali
isi pengumuman yang dikirim ke channel tujuan).

## Batasan jujur (baca SETUP.md)

Bot NEWR Adventure saat ini menentukan event dari tanggal kalender, menghitung
reward tanpa rate server, dan tidak memeriksa tabel ban. Jadi setting
event, rate, dan ban yang dibuat bot ini tersimpan rapi di tabel admin,
tapi baru berlaku penuh di bot NEWR Adventure setelah patch kecil yang didokumentasikan
di SETUP.md. Bot ini sengaja tidak mengubah bot NEWR Adventure sendiri.
