# EA Project — branch `scalping`: Telegram Signal Scalper (XAUUSD)

Full Python. Membaca sinyal scalping XAUUSD dari topik **Scalping** di grup forum Telegram
(Telethon, hanya baca), menunggu konfirmasi FVG/OB di M1/M5, eksekusi via library `MetaTrader5`,
monitoring lewat dashboard NiceGUI.

> Branch `master` berisi project lama (FastAPI + EA MQL5 + strategi H4/D1). File-file itu
> sengaja dihapus dari branch ini; lihat `git show master:<path>` bila perlu referensi.

## Dokumen
- [docs/scalping/PLAN.md](docs/scalping/PLAN.md) — tahapan, status, keputusan
- [docs/scalping/SIGNAL_SPEC.md](docs/scalping/SIGNAL_SPEC.md) — format pesan & konversi harga
- [docs/scalping/RULES.md](docs/scalping/RULES.md) — mode, state machine, risk, keamanan, coding
- [backend/tg_signal/CLAUDE.md](backend/tg_signal/CLAUDE.md) — panduan modul & perintah

## Struktur
```
ea-project/
├── docs/scalping/           # PLAN, SIGNAL_SPEC, RULES
└── backend/
    ├── .env                 # credential Telegram (jangan di-commit / dibaca)
    ├── requirements.txt
    └── tg_signal/           # seluruh kode
        ├── detectors/       # fvg.py, order_block.py, news_calendar.py
        ├── data/            # SQLite + session Telethon (gitignored)
        └── tests/
```

## Environment
- **Python 3.10 Laragon**: `C:\laragon\bin\python\python-3.10\python.exe`
  (`python` di PATH = 3.14, jangan dipakai)
- `pip install -r backend/requirements.txt`

## Aturan penting
- Komunikasi dalam Bahasa Indonesia.
- Mode default `LOG` (tanpa order). Jangan pernah eksekusi di akun LIVE.
- Jangan baca/tampilkan/commit `.env`, `*.session`, atau isi `tg_signal/data/`.
