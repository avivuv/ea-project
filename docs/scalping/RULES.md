# Rules — Telegram Signal Scalper

Aturan yang **wajib** dipatuhi oleh kode (dan oleh siapa pun yang mengubahnya).
Angka default disimpan di `backend/tg_signal/settings.py` (bisa di-override via `.env`), bukan di-hardcode.

---

## 1. Mode operasi

| Mode | Order | Syarat |
|---|---|---|
| `LOG` (default) | tidak ada — paper trade saja | — |
| `DEMO` | order sungguhan | `mt5.account_info().trade_mode` harus DEMO, jika tidak → tolak start |
| `LIVE` | order sungguhan | `TG_MODE=LIVE` **dan** `TG_LIVE_CONFIRM=YES` di `.env` |

- Mode default selalu `LOG`. Tidak boleh ada jalur kode yang membuka order di mode `LOG`.
- Pergantian mode dari dashboard hanya `LOG ↔ DEMO`. `LIVE` hanya via `.env` + restart.

## 2. Siklus sinyal (state machine)

```
NEW ─► WAITING ─► IN_ZONE ─► OPEN ─► CLOSED
         │           │
         └─► EXPIRED ◄┘        REJECTED (dari NEW, gagal validasi)
```

| Transisi | Kondisi |
|---|---|
| NEW → REJECTED | gagal parse/validasi, jarak zona > `TG_MAX_ZONE_DISTANCE`, di luar jam trading, pause aktif |
| NEW → WAITING | lolos validasi |
| WAITING → IN_ZONE | harga menyentuh level `zero` |
| IN_ZONE → OPEN | konfirmasi FVG/OB valid (lihat §3) **dan** lolos risk check (§5) |
| IN_ZONE → EXPIRED | sinyal provider sudah selesai sebelum kita entry — salah satu: harga bergerak `TG_EXPIRE_TP_PIPS` (10) pips dari `zero` ke arah TP (= ZERO-TP versi provider) · harga melewati `last` sejauh `TG_SL_PIPS` (30) pips ke arah SL (= LAST-SL) |
| OPEN → CLOSED | TP / SL / BE / close manual / close-all |

**Masa berlaku sinyal = sampai sinyal itu hit TP atau SL.** Tidak ada timeout waktu
dan tidak hangus karena ganti hari. Sinyal yang sudah `EXPIRED` atau `CLOSED`
**tidak pernah dipakai lagi** — tidak ada re-entry walaupun harga kembali ke zona.

Setiap transisi **dicatat** di SQLite dengan timestamp dan alasan.

## 3. Entry & konfirmasi

- Timeframe konfirmasi: M1 atau M5 (`TG_CONFIRM_TF`).
- Konfirmasi = FVG **searah** sinyal **atau** Order Block searah, terbentuk di dalam / menyentuh zona.
- Bila konfirmasi dinilai lemah (definisi O6 di PLAN) → wajib keduanya (OBIM).
- Evaluasi hanya pada **candle yang sudah close** — tidak boleh pakai candle berjalan.
- Entry = market order di harga saat konfirmasi (atau limit di FVG mid — diputuskan Tahap 2).
- Mode entry live `TG_ENTRY_MODE`: `MARKET` | `ZONE` | `POI` (default, PLAN D10). Mode POI: pending di POI
  (FVG/OB/IFVG) terdekat di dalam zona, harga sudah di zona → market, pending dipindah tiap bar baru.

## 4. SL / TP

- 1 pip XAUUSD = **$0.10 harga**. Konversi pip ↔ harga hanya lewat satu helper (`pips_to_price`).
- SL = `TG_SL_PIPS` (30) pips dari **harga entry aktual** (bukan dari zona).
- TP = aturan kita (`TG_TP_MODE`), bukan dari provider. Default sementara: 10 pips.
- SL & TP **wajib** dikirim bersama order (`order_send` dengan `sl`/`tp`). Order tanpa SL dilarang.
- Opsi BE: setelah +`TG_BE_TRIGGER_PIPS`, geser SL ke entry + spread.

## 5. Risk check (sebelum setiap order)

| Aturan | Default |
|---|---|
| Lot | `TG_LOT` = 0.01 (atau risk-based bila O1 diputuskan begitu) |
| Max posisi bersamaan | `TG_MAX_POSITIONS` = 0 (tanpa batas, keputusan user 13 Nov 2026; isi >0 untuk membatasi) |
| Max trade per hari | `TG_MAX_TRADES_DAY` = 10 |
| Daily loss limit | `TG_DAILY_LOSS_USD` (mis. $10 untuk lot 0.01) → pause sampai hari berikut |
| Daily profit target | `TG_DAILY_PROFIT_USD` (default $100 — praktis jaring pengaman saja; 0 = off; backtest Agu–Nov 2026: target $10 malah −$416 vs −$381 tanpa target) → profit tertutup + floating hari ini ≥ target → semua posisi ditutup market (outcome `TARGET`), pending dibatalkan, stop buka order sampai hari berikut (WIB) |
| Max spread | `TG_MAX_SPREAD_PIPS` = 5 → skip entry |
| Duplikat zona | sinyal baru dengan arah sama & zona overlap posisi terbuka → REJECTED |
| News | pause ±`TG_NEWS_PAUSE_MIN` menit di sekitar high-impact USD (`detectors/news_calendar.py`) |
| Kill switch | file `backend/tg_signal/data/PAUSE` ada → tidak buka order baru |

Bila MT5 terputus atau data harga basi (> 10 detik): tidak buka order baru, tetap pantau posisi.

## 6. Keamanan & privasi

- **Jangan commit**: `.env`, file session Telethon (`*.session`), database SQLite, dump pesan grup.
- Telethon dipakai **hanya untuk membaca**. Tidak ada kirim pesan, join/leave otomatis, atau scraping grup lain.
- Isi pesan grup bersifat pribadi milik grup — jangan dikirim ke layanan luar
  (termasuk API AI) kecuali diputuskan eksplisit.
- Dashboard: default bind `127.0.0.1`. Akses dari luar hanya via Tailscale + password (`TG_DASH_PASSWORD`).
- Tombol aksi di dashboard (close-all, ganti mode) butuh konfirmasi.

## 7. Coding

- Bahasa: Python 3.10 (Laragon). Type hints + `from __future__ import annotations`.
- Komentar & docstring Bahasa Indonesia, konsisten dengan kode yang sudah ada.
- Logika murni (parser, resolver, state machine, konfirmasi) **tidak boleh** import `MetaTrader5`/`telethon`
  — supaya bisa dites dan dipakai backtest. I/O hanya di `tg_client.py`, `executor.py`, `store.py`.
- Reuse `tg_signal/detectors/` (`fvg.py`, `order_block.py`); jangan duplikasi deteksi FVG/OB.
- Waktu disimpan dalam **UTC**; konversi ke waktu server MT5 / WIB hanya untuk tampilan.
- Setiap perubahan parser wajib disertai test case dari pesan asli.
- Jalankan `pytest backend/tg_signal/tests` sebelum commit.
