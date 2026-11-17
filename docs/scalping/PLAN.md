# Plan — Telegram Signal Scalper (XAUUSD)

Branch: `scalping` · Bahasa: **full Python** · Status: **Tahap 2 — backtest negatif, menunggu keputusan arah**

Program yang membaca sinyal scalping XAUUSD dari grup Telegram, menunggu konfirmasi
FVG/OB di M1/M5, lalu mengeksekusi order di MT5 — dengan dashboard web untuk monitoring.

Dokumen terkait:
- [SIGNAL_SPEC.md](SIGNAL_SPEC.md) — format pesan, aturan parsing, konversi harga
- [RULES.md](RULES.md) — aturan trading, risk, keamanan, dan coding
- [../../backend/tg_signal/CLAUDE.md](../../backend/tg_signal/CLAUDE.md) — panduan modul

---

## Arsitektur

```
Grup Telegram ──► tg_client (Telethon) ──► parser ──► price_resolver ──► store (SQLite)
                                                                            │
                     MT5 (lib MetaTrader5) ◄── executor ◄── signal_manager ◄┘
                          │  data M1/M5                       │ confirmation (FVG/OB)
                          └──────────────────────────────────►│
                                                              ▼
                                               dashboard (NiceGUI di atas FastAPI)
```

## Stack

| Kebutuhan | Library |
|---|---|
| Baca Telegram (akun user, member grup) | `telethon` |
| Data harga + eksekusi order | `MetaTrader5` |
| Dashboard web real-time | `nicegui` |
| Penyimpanan | `sqlite3` (bawaan) |
| Analisis / backtest | `pandas` (sudah ada) |
| Test | `pytest` |

## Struktur modul

```
backend/tg_signal/
├── CLAUDE.md
├── settings.py         # Parameter modul (override via backend/.env)
├── tg_client.py        # Login, ambil riwayat grup, listen pesan baru
├── parser.py           # Parse pesan sinyal & laporan harian
├── price_resolver.py   # 2 digit → harga penuh
├── ingest.py           # Pesan → Store sesuai jenis; --stats
├── store.py            # SQLite: messages, signals, trades, reports
├── detectors/          # fvg.py, order_block.py, news_calendar.py (dipindah dari master)
├── confirmation.py     # Cek FVG / OB di M1-M5 (pakai detectors/)
├── signal_manager.py   # State machine per sinyal
├── executor.py         # order_send, SL/TP, BE, close
├── backtest_tg.py      # Replay riwayat sinyal vs data M1
├── dashboard.py        # NiceGUI pages
├── run_live.py         # Entry point (mode LOG / DEMO / LIVE)
├── data/               # SQLite + session Telethon (gitignored)
└── tests/              # pytest
```

---

## Tahapan

### Tahap 0 — Persiapan
- [x] Buat branch `scalping`
- [x] Dokumen: PLAN, SIGNAL_SPEC, RULES, CLAUDE.md modul
- [ ] (User) `TG_API_ID`, `TG_API_HASH` dari https://my.telegram.org → `backend/.env`
- [ ] (User) Nama / username / ID grup sinyal → `backend/.env` (`TG_GROUP`)
- [ ] (User) MT5 login di PC ini, histori M1 XAUUSD tersedia
- [ ] Catat detail broker: digits XAUUSD, spread rata-rata, contract size

### Tahap 1 — Parser & pengambilan data
- [x] `parser.py` — sinyal + laporan, sesuai SIGNAL_SPEC
- [x] `price_resolver.py` — termasuk kasus lintas ratusan (`02-98`)
- [x] `tests/` — semua contoh di SIGNAL_SPEC jadi test case (50 test lulus)
- [x] `store.py` — skema SQLite (`messages`, `signals`, `signal_events`, `report_lines`)
- [x] `ingest.py` — proses satu pesan → simpan sesuai jenis, tangani edit; `--reparse`
- [x] `tg_client.py` — `--list-groups`, `--dump-history`, `--listen`; filter topik forum
- [x] Laporan parser: `python -m tg_signal.ingest --stats`
- [x] Login + dump riwayat topik Scalping (43.966 pesan, Jun 2025 – Nov 2026)
- [x] Review pesan gagal parse → variasi format ditambahkan ke SIGNAL_SPEC

**Selesai bila:** ≥95% pesan sinyal ter-parse benar; sisanya tercatat untuk review manual.
✅ **Selesai** — sisa ~38 pesan mirip sinyal tidak ter-parse (typo berat), <0,4%.

**Hasil data (Okt 2025 – 11 Nov 2026):**
- 11.022 pesan sinyal → **9.551 sinyal unik** (dedup arah+zona ≤5 menit), rata-rata **~35 sinyal/hari**
- Jumlah sinyal unik per hari cocok dengan jumlah baris laporan (selisih 0–1)
- Laporan tersedia 26 Nov 2025 – 11 Nov 2026 (236 hari). Klaim provider:
  ZERO-TP 51,4% · MID-TP 27,6% · LAST-TP 10,0% · LAST-SL 11,0% → **win 89%**
- Topik hanya diisi admin bertanda tangan (Admin 1/2/3/2+1/4) — tidak perlu filter pengirim

### Tahap 2 — Backtest & validasi
- [~] Ambil data M1 XAUUSD dari MT5 — `market_data.py`; baru tersedia 31 Jul – 11 Nov 2026
- [ ] (User) Unduh histori M1 Okt 2025 – Jul 2026 di MT5, lalu jalankan ulang backtest
- [x] `backtest_tg.py` dengan variasi:
  - Entry: limit ZERO / MID / LAST / layer 3, konfirmasi FVG / OB / OBIM
  - Konfirmasi di M1 (M5 via `--m5`; hampir tidak pernah terpicu)
  - TP: 10 / 20 / 30 pips; SL dari entry vs dari ujung zona
  - Spread per bar asli + opsi `--spread-pips`
  - [ ] partial 50% @10 + BE + sisa @30 (belum)
- [x] Cocokkan simulasi dengan label laporan → hanya ~64% cocok (TP provider tidak tetap)
- [x] Laporan: [BACKTEST_2026-11.md](BACKTEST_2026-11.md)
- [ ] Dashboard: halaman hasil backtest

**Selesai bila:** ada variasi yang profit setelah spread, dan keputusan terbuka #1–#5 bisa diputuskan.
⚠️ **Belum terpenuhi** — semua variasi negatif di data Agu–Nov 2026, bahkan tanpa spread.
Tahap 3 ditahan sampai ada keputusan arah (lihat BACKTEST_2026-11.md).

### Tahap 3 — Live, mode LOG (paper trade)
- [ ] `tg_client.py` listen real-time
- [ ] `signal_manager.py` + `confirmation.py` jalan dengan data live, **tanpa order**
- [ ] Dashboard: feed Telegram, sinyal aktif, chart M1/M5 + zona
- [ ] Jalan 1–2 minggu, bandingkan dengan laporan harian dosen

**Selesai bila:** hasil paper trade konsisten dengan backtest.

### Tahap 4 — Mode DEMO
- [ ] `executor.py` aktif di akun demo (dicek otomatis: akun harus demo)
- [ ] Pengaman: max posisi, daily loss, duplikat zona, max spread, news filter
- [ ] Dashboard: kontrol (pause/resume, close all), riwayat trade
- [ ] Login dashboard + akses via Tailscale (opsional)

**Selesai bila:** ≥2 minggu demo, hasil sesuai ekspektasi backtest.

### Tahap 5 — Mode LIVE
- [ ] Lot minimum, pengaman paling ketat
- [ ] Review mingguan

---

## Keputusan

### Sudah diputuskan
| # | Topik | Keputusan |
|---|---|---|
| D1 | Bahasa | Full Python (tanpa EA MQL5 untuk eksekusi) |
| D2 | Eksekusi | Library `MetaTrader5`, MT5 di PC yang sama |
| D3 | Dashboard | NiceGUI di atas FastAPI |
| D4 | Pip | 1 pip = $0.10 harga. 30 pips = $3.00 (≈ $3 per 0.01 lot) |
| D5 | SL | 30 pips dari **harga entry aktual kita** |
| D6 | Konfirmasi | FVG **atau** OB; bila lemah wajib keduanya (OBIM) |
| D7 | Sumber | Grup Telegram dosen, dibaca via Telethon (akun user member) |
| D8 | Masa berlaku sinyal | Valid sampai sinyal hit TP/SL (dari zona); setelah itu tidak dipakai lagi. Tanpa timeout waktu, tanpa re-entry |
| D9 | Entry live (12 Nov 2026) | `TG_ENTRY_MODE=ZONE`: ikuti harga sinyal. Saat sinyal datang harga sudah di zona → market; belum → pending limit di ZERO. SL = LAST ∓ 30 pips, TP = entry ± 30 pips. Pending hangus bila harga sampai ZERO ± 30 pips tanpa fill; sinyal baru menggantikan pending lama. Dipilih user walau backtest no. 11 lebih buruk dari market — dievaluasi di demo |
| D10 | Entry live POI (13 Nov 2026) | `TG_ENTRY_MODE=POI` (default): detektor FVG/OB/IFVG (`detectors/poi.py`, bar `TG_POI_TF`=M1) mencari POI di zona sinyal ± $0.5. Harga sudah di zona → market; belum → pending di tepi POI terdekat (tanpa POI → di ZERO). SL/TP 30 pips dari harga entry. Tiap bar baru pending dipindah bila POI gagal/muncul POI lebih dekat; batal bila harga lewat LAST ∓ SL atau sampai ZERO ± TP tanpa fill. Diminta user walau backtest 2511 sinyal: semua varian POI PF < 1 (lihat `poi_backtest.py`) — dievaluasi di demo |
| D11 | POI tanpa fallback (13 Nov 2026) | `TG_POI_FALLBACK=NONE`: tidak ada POI di zona → sinyal WAITING, dicek ulang tiap bar M1 sampai POI terbentuk (lalu pending) atau sinyal selesai (EXPIRED). Juga saat harga sudah di zona tanpa POI. POI gagal tanpa pengganti → pending dibatalkan, kembali WAITING. Alasan: backtest sinyal tanpa POI di ZERO ±−2250 pips; MID/LAST tidak konsisten. Prinsip user: sedikit order tapi presisi |
| D12 | TP admin (13 Nov 2026) | `TG_ADMIN_TP_PIPS=20`: harga sampai ZERO ± 10 pips (TP versi admin) tapi posisi belum TP → TP diturunkan ke entry ± 20 pips (sudah lewat → tutup, outcome TP_ADMIN). Pemicu harga, bukan pesan (pesan "tp" telat; "mid"/"last" = info kedalaman). Backtest `admin_tp_study.py`: −2700/−1120 → −1202/−693 pips (Agu–Sep/Okt–Nov) |
| D13 | Semua sinyal diproses (16 Nov 2026) | `TG_DUPLICATE_WINDOW_SEC=0`: sinyal arah+zona sama tidak lagi ditolak DUPLICATE. `TG_POI_REPLACE_PENDING=0`: sinyal baru tidak membatalkan pending/WAITING lama, tiap sinyal jalan sendiri ke POI. Catatan: admin kadang kirim pesan pendek lalu pesan lengkap untuk sinyal yang sama → bisa jadi 2 order. Batas tetap: `TG_MAX_TRADES_DAY`, daily loss/profit, spread |
| D14 | Admin TP dari Report (16 Nov 2026) | `TG_ADMIN_TP_SOURCE=BOTH`: selain pemicu harga (D12), baris baru `✅ …-TP` di pesan Report admin juga memicu admin TP untuk posisi sinyal yang cocok (arah + level, sinyal terbaru). `PRICE`/`REPORT` untuk salah satu saja. Perbaikan (16 Nov): pending/WAITING kini hangus di ZERO ± `TG_EXPIRE_TP_PIPS` (10, sama dengan backtest POI), bukan ± `TG_TP_PIPS` (30); Report TP juga membatalkan pending/WAITING sinyal itu |
| D15 | Admin TP dari pesan singkat (16 Nov 2026) | Pesan admin `TP`/`HIT TP`/`ZERO`/`MID`/`LAST`/`MID TP`/`INSTAN` (≤ 40 karakter, bukan `SL`) → sinyal yang di-reply, atau sinyal aktif paling baru, dinyatakan TP: pending/WAITING dibatalkan, posisi terbuka TP digeser ke entry ± `TG_ADMIN_TP_PIPS`. Ikut `TG_ADMIN_TP_SOURCE` (REPORT/BOTH) |
| D16 | Pending hangus hanya via chat admin (16 Nov 2026) | Pending/WAITING live tidak lagi hangus saat harga sampai ZERO ± `TG_EXPIRE_TP_PIPS`; tetap dipertahankan sampai terisi, lewat LAST ∓ SL, diganti sinyal baru, atau admin bilang TP (Report / pesan singkat, D14–D15). Butuh `TG_ADMIN_TP_SOURCE` REPORT/BOTH dan `TG_ADMIN_TP_PIPS` > 0. Admin TP untuk posisi terbuka (D12) & backtest tidak berubah |
| D17 | Admin TP posisi hanya via chat admin (16 Nov 2026) | Default `TG_ADMIN_TP_SOURCE=REPORT`: "sudah TP" murni dari chat admin Telegram (Report `✅ …-TP` / pesan singkat, D14–D15). Pemicu harga ZERO ± 10 pips (D12) tidak dipakai lagi untuk posisi terbuka — kasus BUY 36-32 16 Nov: TP diturunkan ke +20 oleh harga 50 dtk sebelum admin kirim "TP". `PRICE`/`BOTH` masih bisa via `.env` |

### Masih terbuka (diputuskan setelah Tahap 2)
| # | Topik | Opsi |
|---|---|---|
| O1 | Lot | Tetap 0.01 / berbasis risk % |
| O2 | Aturan TP | 10 / 20 / 30 / partial + BE |
| O3 | Max posisi bersamaan | Tanpa batas (13 Nov 2026) — semua sinyal dieksekusi; `TG_MAX_POSITIONS` = 0 |
| O5 | Arti ZERO/MID/LAST | Dugaan di SIGNAL_SPEC, divalidasi via backtest |
| O6 | Definisi "konfirmasi lemah" | Mis. FVG kecil (< X), OB lama, melawan trend M5 |
| O7 | Entry tanpa konfirmasi di tepi zona? | Karena 13/20 sinyal ZERO-TP, mungkin perlu |

## Catatan risiko
- Rasio SL:TP 30:10 → butuh win rate > 75% hanya untuk impas. Klaim laporan (19/20) wajib diverifikasi.
- Sinyal bisa ~20/hari dengan zona tumpang tindih → aturan duplikat & max posisi penting.
- Latency Telegram → order 1–3 detik; spread XAUUSD saat news bisa melebar.

## Catatan: kandidat aturan (belum dipakai di EA)
Dicatat 11 Nov 2026 — **dievaluasi saat analisa hasil demo, tanpa mengubah EA** (uji maju).
1. **Filter FVG M5** — entry hanya bila saat sinyal masuk sudah ada FVG M5 searah di zona
   (SELL ↔ bearish, BUY ↔ bullish), lebih baik yang masih *open*, dan tidak ada FVG M1 berlawanan
   yang masih terbuka di jalur harga → TP. Backtest: +1,5 / +1,4 pips/trade (TP30) di Agu–Sep / Okt–Nov
   vs −2,1 / −1,0 untuk semua sinyal; efek searah di periode lama. Lihat BACKTEST_2026-11.md.
   Kode: `fvg_context.py` (FVGIndex.context), `fvg_study.py`.
2. **Jarak ke zona** (`dist_to_zero`) — harga yang belum masuk zona saat sinyal masuk lebih jarang
   sampai LAST. Efek lemah.
3. **TP lebih kecil (15–20)** — bandingkan dengan TP30 pada sinyal demo yang sama.
4. **CHoCH + FVG (pengamatan salah satu admin, tapi BUKAN dari topik Scalping; contoh 11 Nov 2026, chart 3m)** — range 16:30–16:55 WIB (±4048.3–4051),
   sweep ke ±4046.5, lalu ±16:58–17:05 impuls bullish tembus high range (CHoCH) meninggalkan FVG,
   puncak ±4055.9, retest ±4048–4049 jam 17:10–17:20. Admin baru kirim **BUY 49-45 jam 17:22** tepat
   di retest → EA entry 4048.97, TP 17:31 (+30 pips). Dua ide untuk diuji:
   - **A. Filter**: ambil sinyal admin hanya bila didahului CHoCH searah + FVG (M3/M5).
   - **B. Sinyal sendiri (fokus utama, strategi terpisah dari sinyal Telegram)**: EA deteksi CHoCH + FVG sendiri, entry saat retest ke FVG, SL di bawah
     swing low (contoh: entry 4049.16, SL 4046.53, TP 4054.60 ≈ 2R). Basis kode CHoCH:
     `detectors/order_block.py` (`detect_choch`, perlu disesuaikan ke M3/M5).
5. **SL berbasis struktur di LAST** (contoh SELL 51-55, 11 Nov 2026 17:50 WIB) — EA entry 4050.99,
   SL 30 pips = 4053.99 kena 18:06 (bid tertinggi 4053.93, ask ±4054.10 karena spread). LAST 4055
   belum tersentuh. Di sekitar LAST ada area supply: FVG bearish M5 4053.99–4054.72 (16:15) dan swing
   high ±4055.9 (17:05) → SL kita persis di bawah area itu. Ide: SL sedikit di atas struktur terdekat
   di/di atas LAST (FVG/swing high) + buffer spread, bukan jarak tetap 30 pips. Catatan: versi kasar
   "SL = LAST ± 30 pips" sudah diuji dan lebih buruk (MARKET TP30: −2,51 vs −1,67 pips/trade) karena
   risiko ±70 pips; versi presisi di atas struktur belum diuji.
6. **Tren TF besar → fast entry atau tunggu** (ide user, diuji cepat 11 Nov 2026; TP30/SL30, M1 Agu–Nov).
   Tren = EMA20 vs EMA50 bar TF yang sudah close. Avg pips/trade, latih Agu–Sep | uji Okt–Nov:
   - M15 searah → FAST: −2,08 | −0,37 · M15 lawan → FAST: −2,21 | −1,53 (searah sedikit lebih baik, konsisten)
   - Aturan "M15 searah = FAST, lawan = skip": −2,08 | −0,37 (vs semua −2,14 | −0,96) — membaik kecil, masih negatif
   - "lawan = tunggu MID/LAST": tidak lebih baik dari skip
   - H1 dan H4: **tidak konsisten** (H4 searah lebih baik di Agu–Sep, terbalik di Okt–Nov)
   Kesimpulan: tren M15 searah hanya sedikit membantu; H1/H4 tidak bisa dipakai sebagai aturan fast/tunggu.
   Bisa dikombinasikan dengan filter FVG M5 (no. 1) saat evaluasi demo.
7. **Perbedaan feed harga** (SELL 51-55, 11 Nov 2026): di Exness harga tertinggi 4054.36 (18:07 WIB), LAST 4055
   tidak tersentuh, padahal di chart user (feed lain) tampak sampai LAST. Feed bisa beda $0,3–0,6.
   Bila memakai limit di LAST/MID, pasang sedikit sebelum level (mis. −5 pips) agar tidak meleset.
8. **TP dinamis menurut tren besar** (ide user, diuji 11 Nov 2026; entry langsung, SL 30). Avg pips/trade
   (rata-rata Agu–Sep & Okt–Nov): TP tetap 30 = −1,55 · TP tetap 20 = −1,63 · M15 searah 30/lawan 20 = −1,61 ·
   H1 searah 30/lawan 20 = −1,74 · H4 searah 30/lawan 20 = −1,70. Kontrol terbalik (searah 20/lawan 30)
   −1,43 s/d −1,56 → selisih antar aturan hanya noise. **TP dinamis berdasarkan tren tidak membantu**;
   besar TP (10–30) sendiri hampir tidak mengubah hasil. Yang lebih berpengaruh: sinyal mana yang diambil
   (filter FVG M5, no. 1) dan posisi SL (no. 5).
9. **Entry MID/LAST menurut volatilitas atau saat lawan tren** (ide user, diuji 12 Nov 2026; M1 Agu–Nov, TP/SL 30).
   Limit MID ter-fill 26–36%, LAST 14–20%; ±80% sinyal yang tak sampai LAST justru TP dari ZERO. Trade yang
   ter-fill di LAST rugi lebih besar per trade (seleksi buruk: harga sampai LAST karena ditembus kuat).
   "ATR14 M1 tinggi → LAST": −1,77 | −1,53 vs market −2,16 | −1,11 (lebih buruk di periode uji).
   "BUY saat tren turun → MID/LAST": tidak konsisten di M15/H1/H4. **Tidak dipakai.**
10. **Pencarian filter sinyal** (12 Nov 2026; entry market, SL 30, max 1 posisi). Grid 2.659 kombinasi
    (sesi × tren M15/H1 × momentum 3 candle M5 × FVG M5 / blocker M1 × stop harian 2–3 SL × TP 15/20/30) di M1
    Agu–Nov: 6,8% positif di kedua paruh vs 4,3% untuk filter acak → sebagian besar kebetulan. Kandidat terbaik
    diuji di data baru Okt 2025–Jul 2026 (bar M5; simulasi M5 ±2,3 pips/trade lebih buruk dari M1 sebagai
    kalibrasi). Avg pips/trade (M1 Agu–Nov | M5 Agu–Nov | M5 Okt25–Jul, bulan positif):
    baseline −1,62 | −3,97 | −3,54 (1/13) · **pullback ≥2 candle M5 + FVG M5 searah** +1,34 | −1,15 | −2,45 (3/12) ·
    + jam 14–21 WIB +3,38 | +0,57 | −3,89 · jam 19–21 + H1 searah + FVG M5 +9,07 | −1,43 | −3,06 ·
    jam 14–18 + close M5 bukan di ujung lawan + stop 2 SL +1,59 | −0,11 | −2,44 · FVG M5 saja +0,25 | −1,53 | −3,24.
    Kesimpulan: filter jam tidak bertahan. "Pullback + FVG M5" dan "close bukan di ujung lawan" konsisten
    memperbaiki ±1 pip/trade dibanding baseline di kedua data, tapi setelah kalibrasi hanya ≈ impas — **belum ada
    filter yang profit konsisten**. Script uji: scratchpad sesi (filter_search.py, filter_eval.py, oos_eval.py).
11. **Limit di ZERO + SL di bawah LAST vs market** (diuji 12 Nov 2026; M1 31 Jul–12 Nov, 2.468 sinyal,
    split 21 Sep). Avg pips/trade ALL | paruh 1 | paruh 2, TP30: MARKET SLentry −1,69 | −1,87 | −1,51 ·
    LIMIT_ZERO SLzone −3,37 | −3,36 | −3,37 · LIMIT_ZERO SLentry −2,87 · MARKET SLzone −2,58. TP20 sama polanya.
    ZERO hampir selalu tersentuh (hanya 23 tidak), jadi limit tidak menyaring sinyal, hanya mengubah harga entry
    dan memperlebar risiko. **Market entry + SL 30 dari entry tetap yang terbaik (walau tetap negatif).**
    User tetap memilih entry sesuai zona sinyal (D9) untuk dievaluasi di demo.
