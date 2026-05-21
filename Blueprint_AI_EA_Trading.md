# Blueprint Teknis: AI-Integrated Expert Advisor (EA)
**Versi 2.0 — Revisi: Fokus Low Risk, Trend-Following, AI sebagai Filter**

Dokumen ini merangkum arsitektur dan strategi untuk membangun sistem trading otomatis (Expert Advisor) yang menggabungkan analisis teknikal multi-konfirmasi dengan AI cloud (Gemini/Claude) sebagai filter fundamental.

---

## 1. Strategi Inti: Trend-Following Multi-Konfirmasi (H4/D1)

**Filosofi:** Satu strategi yang dieksekusi dengan disiplin lebih baik dari empat strategi yang dilaksanakan setengah-setengah. EA ini hanya mengambil trade ketika teknikal dan fundamental **sama-sama setuju**.

### Mengapa Trend-Following H4/D1?
- Timeframe tinggi menyaring noise intraday secara alami
- Signal lebih sedikit → kualitas lebih tinggi → WR lebih konsisten
- Cocok untuk kondisi pasar volatile (ATR-based SL menyesuaikan otomatis)
- Dengan RRR 1:2.5, hanya butuh WR **40% untuk breakeven**, WR 50% sudah profitabel

### Target Pair yang Direkomendasikan
Fokus pada **3-4 pair mayor** dengan likuiditas tinggi dan spread kecil:
- `EURUSD` — paling liquid, spread kecil
- `GBPUSD` — volatilitas baik untuk trend
- `USDJPY` — sensitif suku bunga, cocok dengan analisis AI
- `XAUUSD` (Opsional, fase lanjut) — trend kuat, hindari dulu di awal

### Aturan Entry

| Kondisi | BUY | SELL |
|---------|-----|------|
| Trend Filter | EMA 50 > EMA 200 (Golden Cross area) | EMA 50 < EMA 200 (Death Cross area) |
| Momentum | RSI(14) antara 45–65 | RSI(14) antara 35–55 |
| Konfirmasi Candle | Close H4 di atas EMA 50 | Close H4 di bawah EMA 50 |
| Volatilitas | ATR(14) > threshold minimum (pasar bergerak) | ATR(14) > threshold minimum |
| AI Filter | Sentimen fundamental tidak negatif/bearish | Sentimen fundamental tidak positif/bullish |

**Jika salah satu kondisi tidak terpenuhi → HOLD, tidak ada trade.**

### Kalkulasi SL & TP
```
Stop Loss  : Entry ± (1.5 × ATR_14)      → dinamis, sesuai volatilitas saat ini
Take Profit: Entry ± (2.5 × ATR_14)      → RRR minimal 1:2.5 (bisa disesuaikan 1:2 atau 1:3)
Trailing SL: Aktif setelah floating profit > 1 × ATR (lock profit)
```

---

## 2. Risk Management (Wajib Diimplementasikan)

Ini adalah komponen paling kritis. EA tanpa risk management yang ketat = bom waktu.

### Position Sizing (Per Trade)
```
Risk per trade   : 1% dari account equity (konservatif, direkomendasikan)
                   maksimum 2% (agresif, tidak dianjurkan di awal)

Formula lot size : Lot = (Equity × Risk%) / (SL_pips × Pip_Value)

Contoh           : Equity $1000, Risk 1% = $10 risiko
                   SL = 30 pips, Pip Value EURUSD = $1/pip (micro lot)
                   Lot = $10 / (30 × $1) = 0.33 micro lot
```

### Circuit Breaker (Perlindungan Otomatis)
```
Daily Loss Limit : -3% dari equity → EA stop trading hari itu, resume besok
Max Drawdown     : -12% dari equity peak → EA pause, butuh manual review
Max Open Trades  : 2 trade simultan (hindari over-exposure)
Correlation Lock : Tidak buka EURUSD dan GBPUSD bersamaan di arah yang sama
                   (keduanya berkorelasi tinggi = double risk)
```

### Session Filter
```
Trading diizinkan  : London Session (07:00–16:00 GMT)
                     New York Session (13:00–22:00 GMT)
                     Overlap London-NY (13:00–16:00 GMT) ← paling optimal
Trading diblokir   : Asian Session (volatilitas rendah, spread lebih lebar)
                     30 menit sebelum/sesudah rilis berita high-impact
```

---

## 3. Arsitektur Sistem: "Brain & Brawn" (Revisi)

```
┌─────────────────────────────────────────────────────────┐
│                    ALUR KEPUTUSAN                        │
│                                                          │
│  MT5 (setiap close candle H4)                           │
│       │                                                  │
│       ▼                                                  │
│  [GATE 1: Session & News Filter]                        │
│       │ Lolos? Lanjut. Tidak? → HOLD                    │
│       ▼                                                  │
│  [GATE 2: Teknikal Signal Engine (Python/Pandas)]       │
│       │ Ada signal EMA + RSI + ATR? Lanjut. Tidak? HOLD │
│       ▼                                                  │
│  [GATE 3: AI Fundamental Filter (Gemini/Claude API)]    │
│       │ Sentimen setuju dengan arah signal? Lanjut.     │
│       │ Tidak setuju / netral kuat? → HOLD              │
│       ▼                                                  │
│  [GATE 4: Risk Check (Python)]                          │
│       │ Daily limit & drawdown OK? Lanjut. Tidak? HOLD  │
│       ▼                                                  │
│  [EKSEKUSI] → kirim order ke MT5                        │
└─────────────────────────────────────────────────────────┘
```

### A. The Brawn — MetaTrader 5 (MQL5)
- **Peran:** Eksekutor order + pengumpul data OHLCV real-time
- **Fungsi:**
  - Polling ke FastAPI backend setiap penutupan candle H4
  - Mengirim payload: symbol, OHLCV terbaru, equity saat ini, posisi open
  - Menerima instruksi JSON: `action`, `lot_size`, `sl`, `tp`
  - Mengeksekusi order dan mengelola trailing stop
- **Catatan:** MQL5 tidak melakukan kalkulasi sinyal apapun, murni eksekutor

### B. The Brain — Python / FastAPI Backend
- **Peran:** Pengambil keputusan pusat dengan 4-gate validation
- **Teknologi:**
  - `FastAPI` — endpoint async untuk menerima request dari MT5
  - `pandas` + `pandas-ta` — kalkulasi EMA, RSI, ATR
  - `httpx` — async HTTP client untuk call Gemini/Claude API
  - `sqlite3` / `json file` — menyimpan state harian (daily loss, drawdown tracking)

### C. The Intelligence — Gemini / Claude API (Bukan Local LLM)
- **Mengapa Cloud API vs Local LLM:**
  - Response time: Cloud API ~1-3 detik vs Local LLM ~15-60 detik
  - Kualitas reasoning: Gemini 1.5 Pro / Claude Sonnet jauh lebih superior
  - Cost: Dengan H4 timeframe + 3 pair → estimasi **< 50-100 request/hari**
  - Biaya sangat terjangkau dengan akun Pro, tidak masalah
- **Pilihan API:**
  - `Gemini 2.5 Flash` ← **yang dipakai** — reasoning kuat, gratis di free tier, response ~1-2 detik
- **Peran AI:** Bukan pengambil keputusan, tapi **filter/veto** — AI hanya ditanya setelah sinyal teknikal valid

---

## 4. Prompt Engineering untuk AI Filter

### System Prompt (Tetap/Statis)
```
You are a conservative quantitative risk analyst for a forex trading system.
Your role is NOT to predict price direction. Your role is to assess whether
the CURRENT FUNDAMENTAL ENVIRONMENT supports or contradicts a given technical signal.

Rules:
- Be conservative. When in doubt, output VETO.
- Focus only on: central bank stance, recent economic data surprises, geopolitical risk.
- Ignore short-term noise and social media sentiment.
- Always respond in valid JSON only.
```

### User Payload (Dinamis, dikirim setiap request)
```json
{
  "signal": {
    "pair": "EURUSD",
    "direction": "BUY",
    "timeframe": "H4",
    "technical_summary": {
      "ema_trend": "BULLISH (EMA50 > EMA200)",
      "rsi": 52,
      "atr": 0.0085,
      "price_vs_ema50": "ABOVE"
    }
  },
  "context": {
    "latest_news_summary": "[diisi ringkasan 3-5 berita terbaru dari News API]",
    "upcoming_events_24h": "[event high-impact dalam 24 jam ke depan]"
  },
  "question": "Does the current fundamental environment SUPPORT or CONTRADICT a BUY on EURUSD?"
}
```

### Expected Output (JSON Structured)
```json
{
  "reasoning": "ECB recently signaled hawkish stance supporting EUR strength. No major risk events in 24h. USD slightly weakened after softer CPI.",
  "fundamental_bias": "BULLISH_EUR",
  "contradicts_signal": false,
  "veto": false,
  "confidence": 72,
  "warning": null
}
```

### Logic Filter di Python
```python
# AI hanya di-call jika teknikal valid
if not technical_signal_valid:
    return {"action": "HOLD", "reason": "no_technical_signal"}

ai_response = await call_ai_api(payload)

# Veto check
if ai_response["veto"] == True:
    return {"action": "HOLD", "reason": "ai_fundamental_veto"}

# Confidence terlalu rendah = abstain
if ai_response["confidence"] < 60:
    return {"action": "HOLD", "reason": "ai_low_confidence"}

# Semua gate lolos → hitung position size dan eksekusi
lot_size = calculate_lot_size(equity, risk_pct=0.01, sl_pips, pip_value)
return {"action": signal_direction, "lot_size": lot_size, "sl": sl_price, "tp": tp_price}
```

---

## 5. Roadmap Implementasi (Bertahap, Low Risk)

### Fase 1 — Fondasi Backend (Minggu 1-2)
- [ ] Setup Python project + FastAPI + dependensi
- [ ] Buat endpoint `/analyze` yang menerima payload dari MT5
- [ ] Implementasi kalkulasi teknikal: EMA 50/200, RSI(14), ATR(14)
- [ ] Implementasi session filter (London/NY hours)
- [ ] Implementasi risk state tracker (daily loss, drawdown monitor)
- [ ] Unit test semua logika tanpa MT5

### Fase 2 — Validasi Teknikal (Minggu 2-3)
- [ ] Buat MQL5 EA client: polling setiap close H4, kirim OHLCV ke API
- [ ] Test koneksi MT5 ↔ FastAPI di **akun demo**
- [ ] Backtest manual: cek apakah signal EMA+RSI+ATR masuk akal secara historis
- [ ] Validasi position sizing dan SL/TP calculation
- [ ] Target: teknikal bekerja dengan benar 100% sebelum lanjut ke Fase 3

### Fase 3 — Integrasi AI Filter (Minggu 3-4)
- [ ] Setup Gemini API atau Claude API key
- [ ] Integrasikan News API (NewsAPI.org atau Finnhub) untuk context berita
- [ ] Implementasi AI filter dengan prompt yang sudah dirancang
- [ ] Test respons AI: apakah reasoning masuk akal?
- [ ] Implementasi caching AI response (1 response per pair per 4 jam, hemat request)

### Fase 4 — Forward Testing Demo (Bulan 2)
- [ ] Jalankan EA di akun demo selama **minimum 4 minggu**
- [ ] Log semua trade: entry reason, AI reasoning, outcome
- [ ] Evaluasi metrik: WR, average RRR, max drawdown, Sharpe ratio
- [ ] Identifikasi false positive patterns dan fine-tune filter
- [ ] Go/No-Go decision untuk live trading

### Fase 5 — Live Trading (Bulan 3+)
- [ ] Mulai dengan lot sangat kecil (0.01) dan akun $500-1000
- [ ] Monitor ketat 2 minggu pertama
- [ ] Scale up bertahap hanya jika forward test konsisten

---

## 6. Stack Teknologi Final

| Komponen | Teknologi | Keterangan |
|----------|-----------|------------|
| EA Client | MQL5 | Sudah tersedia di MT5 |
| Backend | Python 3.11+ / FastAPI | Ringan, async |
| Indikator | pandas-ta | Kalkulasi EMA, RSI, ATR |
| AI Filter | Gemini 2.5 Flash | Cloud API, gratis, < 100 req/hari |
| Berita | NewsAPI.org / Finnhub Free Tier | Context fundamental |
| State Storage | SQLite | Track daily loss, equity curve |
| Hosting | Lokal / VPS Ubuntu minimal | Harus selalu online |
| Logging | Python logging + CSV | Audit trail semua keputusan |

---

## 7. Metrik Keberhasilan

| Metrik | Target Minimum | Target Ideal |
|--------|----------------|--------------|
| Win Rate | > 45% | > 55% |
| Risk/Reward Ratio | 1:2 | 1:2.5 |
| Max Drawdown | < 15% | < 10% |
| Profit Factor | > 1.3 | > 1.6 |
| Rata-rata trade/bulan | 15-25 | 20-30 |

---

*Blueprint v2.0 — Revisi berdasarkan analisa komprehensif. Fokus: satu strategi, risk management ketat, AI sebagai filter bukan decision maker.*
