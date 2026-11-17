# tg_signal — Telegram Signal Scalper (XAUUSD)

Modul di branch `scalping`. Membaca sinyal scalping XAUUSD dari grup Telegram,
menunggu konfirmasi FVG/OB di M1/M5, eksekusi via library `MetaTrader5`, monitoring via NiceGUI.
Full Python — tidak ada EA MQL5 untuk eksekusi.

## Baca dulu
- [docs/scalping/PLAN.md](../../docs/scalping/PLAN.md) — tahapan, status, keputusan
- [docs/scalping/SIGNAL_SPEC.md](../../docs/scalping/SIGNAL_SPEC.md) — format pesan & konversi harga (kontrak parser)
- [docs/scalping/RULES.md](../../docs/scalping/RULES.md) — mode, state machine, risk, keamanan, coding

## Aturan untuk Claude
- Komunikasi dalam Bahasa Indonesia.
- Cek status tahap di PLAN.md sebelum mengerjakan; update checklist setelah selesai.
- Jangan pernah menjalankan kode yang membuka order di akun LIVE. Uji eksekusi hanya mode `DEMO`.
- Jangan membaca, menampilkan, atau commit isi `.env`, `*.session`, atau database SQLite di `data/`.
  Log (`data/*.log`, mis. `live.log`) dan CSV boleh dibaca untuk analisa (izin user 16 Nov 2026); jangan di-commit.
- Jangan kirim isi pesan grup ke layanan luar.
- Perubahan format/aturan parsing: update SIGNAL_SPEC.md dulu, lalu test, lalu kode.
- Keputusan baru (O1–O7 di PLAN) dicatat di tabel "Sudah diputuskan".

## Fakta penting
- 2 digit sinyal = 2 digit terakhir bagian bulat harga (`62-58` @4165 → 4162/4158), resolve per angka ke kandidat terdekat.
- 1 pip = $0.10 harga; SL 30 pips = $3.00 dari entry aktual.
- Laporan harian (ZERO/MID/LAST-TP/SL): rekap kumulatif; baris baru `✅ …-TP` memicu admin TP (PLAN D14).
- Sinyal valid sampai hit TP/SL (dihitung dari zona); setelah itu tidak dipakai lagi — tanpa timeout, tanpa re-entry.

## Menjalankan
`python` di PATH adalah 3.14 — **pakai Python 3.10 Laragon** (MetaTrader5 & dependency terpasang di sana):
```powershell
cd c:\laragon\www\ea-project\backend
$py = "C:\laragon\bin\python\python-3.10\python.exe"
& $py -m pip install -r requirements.txt
& $py -m pytest tg_signal/tests
& $py -m tg_signal.tg_client --list-groups     # cari ID grup → TG_GROUP
& $py -m tg_signal.tg_client --dump-history    # Tahap 1: riwayat → SQLite
& $py -m tg_signal.ingest --stats              # hasil parse + kandidat gagal
& $py -m tg_signal.tg_client --listen          # pesan baru real-time (log saja)
& $py -m tg_signal.backtest_tg               # backtest (lihat docs/scalping/BACKTEST_2026-11.md)
& $py -m tg_signal.executor --check         # cek akun demo, Algo Trading, harga
& $py -m tg_signal.run_live --mode DEMO     # live di akun demo: entry market (TG_ENTRY_MODE=ZONE → market/pending limit)
& $py -m tg_signal.bumi_live --once        # runner BUMI 4 MA XAU H4+H1 (demo); tanpa --once = jalan terus
& $py -m tg_signal.dashboard               # monitoring http://127.0.0.1:8080
```

## Env (`backend/.env`)
`TG_API_ID`, `TG_API_HASH`, `TG_GROUP`, `TG_MODE` (LOG|DEMO|LIVE), `TG_LIVE_CONFIRM`, `TG_DASH_PASSWORD`
