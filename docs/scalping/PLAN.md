# Plan — Telegram Signal Scalper (XAUUSD)

Branch: `scalping` · Bahasa: **full Python** · Status: **Tahap 1 (kode selesai, menunggu data grup asli)**

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
- [x] `tests/` — semua contoh di SIGNAL_SPEC jadi test case (24 test lulus)
- [x] `store.py` — skema SQLite (`messages`, `signals`, `signal_events`, `report_lines`)
- [x] `ingest.py` — proses satu pesan → simpan sesuai jenis, tangani edit
- [x] `tg_client.py` — `--list-groups`, `--dump-history`, `--listen` (belum dites, butuh credential)
- [x] Laporan parser: `python -m tg_signal.ingest --stats`
- [ ] (User) Login pertama + dump riwayat grup asli
- [ ] Review pesan gagal parse, tambah pola baru ke SIGNAL_SPEC bila perlu

**Selesai bila:** ≥95% pesan sinyal ter-parse benar; sisanya tercatat untuk review manual.

### Tahap 2 — Backtest & validasi
- [ ] Ambil data M1 XAUUSD dari MT5 untuk rentang tanggal riwayat sinyal
- [ ] `backtest_tg.py` dengan variasi:
  - Entry: tepi zona langsung / FVG / OB / OBIM (FVG+OB)
  - Konfirmasi di M1 vs M5
  - TP: 10 / 20 / 30 pips / partial 50% @10 + BE + sisa @30
  - Spread & slippage realistis
- [ ] Cocokkan hasil simulasi dengan label laporan (ZERO/MID/LAST) → konfirmasi arti label
- [ ] Laporan: win rate, profit factor, max drawdown, expectancy per variasi
- [ ] Dashboard: halaman hasil backtest

**Selesai bila:** ada variasi yang profit setelah spread, dan keputusan terbuka #1–#5 bisa diputuskan.

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

### Masih terbuka (diputuskan setelah Tahap 2)
| # | Topik | Opsi |
|---|---|---|
| O1 | Lot | Tetap 0.01 / berbasis risk % |
| O2 | Aturan TP | 10 / 20 / 30 / partial + BE |
| O3 | Max posisi bersamaan | 1 / 2 / 3 |
| O5 | Arti ZERO/MID/LAST | Dugaan di SIGNAL_SPEC, divalidasi via backtest |
| O6 | Definisi "konfirmasi lemah" | Mis. FVG kecil (< X), OB lama, melawan trend M5 |
| O7 | Entry tanpa konfirmasi di tepi zona? | Karena 13/20 sinyal ZERO-TP, mungkin perlu |

## Catatan risiko
- Rasio SL:TP 30:10 → butuh win rate > 75% hanya untuk impas. Klaim laporan (19/20) wajib diverifikasi.
- Sinyal bisa ~20/hari dengan zona tumpang tindih → aturan duplikat & max posisi penting.
- Latency Telegram → order 1–3 detik; spread XAUUSD saat news bisa melebar.
