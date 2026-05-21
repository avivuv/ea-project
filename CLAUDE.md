# EA Trading Project

Sistem trading otomatis (Expert Advisor) berbasis Python backend + MQL5 client dengan AI filter menggunakan Gemini 2.5 Flash.

## Struktur Project

```
ea-project/
├── backend/
│   ├── main.py              # FastAPI server, port 8000
│   ├── config.py            # Semua parameter (pairs, risk, indikator)
│   ├── technical_signal.py  # Kalkulasi EMA/RSI/ATR via library ta
│   ├── risk_manager.py      # Position sizing, circuit breaker, session filter
│   ├── ai_filter.py         # Gemini 2.5 Flash integration + cache 4 jam
│   ├── .env                 # GEMINI_API_KEY (jangan di-commit)
│   ├── state/               # Risk state harian (JSON, auto-generated)
│   └── logs/                # Log semua keputusan EA
└── mql5/
    └── EA_Brain_Client.mq5  # EA script untuk MetaTrader 5
```

## Menjalankan Backend

```powershell
cd c:\laragon\www\ea-project\backend
python main.py
# Server berjalan di http://0.0.0.0:8000
```

## Environment

- Python 3.10.6 (Laragon)
- Dependencies: `pip install -r requirements.txt`
- AI: Gemini 2.5 Flash via Google AI Studio API key

## Endpoints

- `GET  /health`       — cek server hidup
- `POST /analyze`      — terima OHLCV dari MT5, return BUY/SELL/HOLD + lot/SL/TP
- `POST /trade-event`  — MT5 lapor open/close trade untuk update risk state

## Strategi

Trend-Following H4/D1, 4-gate validation:
1. Session filter (London + NY hours GMT)
2. Technical signal: EMA50 > EMA200, RSI 45-65, close > EMA50
3. AI fundamental filter: Gemini 2.5 Flash sebagai veto
4. Risk check: 1% risk/trade, max 2 posisi, daily loss limit 3%

## Parameter Utama (config.py)

- Pairs: EURUSD, GBPUSD, USDJPY
- SL: 1.5 × ATR | TP: 2.5 × ATR | Trailing: 1 × ATR
- Max drawdown: 12% → EA pause otomatis
