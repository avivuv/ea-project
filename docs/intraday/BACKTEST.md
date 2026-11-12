# Backtest Intraday XAUUSD — 11 Nov 2026

Branch `intraday`. Kode: `backend/intraday/backtest.py` (`python -m intraday.backtest`).
Data: bar M5 Exness **1 Okt 2025 – 11 Nov 2026** (13 bulan; harga 3864 → 4055).
Latih: Okt 2025 – Apr 2026 · Uji: Mei – Nov 2026. Hasil dalam **R** (kelipatan risiko per trade;
dengan risiko 1%/trade, 1R ≈ 1% saldo). Eksekusi konservatif, spread per bar asli.

## Strategi yang diuji (42 variasi)
- **S1 Sweep + CHoCH M5**: sweep high/low Asia dan/atau hari sebelumnya di jam 07–16 UTC (14–23 WIB),
  lalu CHoCH berlawanan ≤ 2 jam, entry limit di FVG kaki balik, SL di luar ekstrem sweep, TP 2R/3R/range seberang.
- **S2 Opening Range Breakout**: range 15/30 menit pertama London (07:00 UTC) atau NY (13:30 UTC),
  entry saat close M5 di luar range, SL sisi seberang/tengah range, TP 1,5R/2R/tahan sampai akhir sesi.

## Hasil utama
6 dari 42 variasi positif di latih dan uji.

| Variasi | Latih (trade, avg R) | Uji (trade, avg R) | Bulan positif | Catatan |
|---|---|---|---|---|
| ORB London 15m, SL tengah range, tahan s/d 16:00 UTC | 119, +0,28 | 135, +0,40 | 9/14 | WR 11–13%, DD 43R; 5 trade terbaik = 137R dari total 87R |
| ORB London 15m, SL seberang range, tahan | 119, +0,16 | 135, +0,32 | 9/14 | WR 18–24%, DD 38R; 5 trade terbaik = 81R dari total 62R |
| S1 Sweep Asia, entry tengah FVG, 2R | 19, +0,74 | 23, +0,04 | 7/14 | hanya ±3 trade/bulan; uji ≈ 0 |
| S1 Sweep Asia, entry tepi FVG, 2R | 21, +0,71 | 24, 0,00 | — | uji = 0 |

Pemeriksaan ketahanan:
- **ORB London: untung hanya dari sisi SELL** (+122R / +78R); sisi BUY rugi (−35R / −16R), padahal emas naik ±5%.
- **ORB London bergantung pada sedikit hari tren besar** — tanpa 5 trade terbaik, hasilnya negatif.
- ORB "tahan sampai akhir sesi" tidak sensitif resolusi bar: hasil eksekusi M1 = M5 di Agu–Nov.
- S1 (sweep + CHoCH): kedua arah positif dan R per trade terbatas (maks 2R), tapi sampel kecil (42 trade
  dalam 13 bulan) dan periode uji ≈ impas.
- Level hari sebelumnya (PDH/PDL) untuk S1 jelek di semua variasi; level Asia lebih baik.

## Kesimpulan
Belum ada strategi yang cukup meyakinkan. ORB London 15m menarik (positif di dua periode, 9/14 bulan),
tapi rapuh: bergantung pada beberapa hari tren dan hanya sisi SELL. 13 bulan data terlalu pendek untuk
strategi berfrekuensi ±20 trade/bulan dengan hasil "ekor gemuk".

## Langkah lanjut yang disarankan
1. Ambil data historis multi-tahun (mis. Dukascopy XAUUSD M1/M5 2019–2025) dan uji ulang
   ORB London 15m + S1 Sweep Asia dengan aturan yang sama persis (tanpa disetel ulang).
2. Bila tetap positif dan stabil per tahun → uji demo dengan lot berbasis risiko 0,5–1%.

## Uji multi-tahun (`multiyear.py`) — bar M15 Exness Sep 2022 – Nov 2026
Datafeed Dukascopy (`datafeed.dukascopy.com`) timeout dari jaringan ini; pengunduh tetap tersedia di
`intraday/dukascopy.py`. Exness MT5 menyediakan M15 sejak Sep 2022 (M30 sejak 2018, H1 sejak 2015),
M5 hanya sejak Jun 2025. ORB diuji ulang di M15 dengan aturan sama (kalibrasi Jun 2025 – Nov 2026:
M15 sedikit lebih pesimis dari M5, arah sama).

| Variasi ORB (M15) | Trade | WR | avg R | 2022* | 2023 | 2024 | 2025 | 2026 | Tahun + |
|---|---|---|---|---|---|---|---|---|---|
| London 15m, SL tengah, tahan s/d sesi | 970 | 17% | +0,07 | +9,9 | −0,9 | −5,0 | −19,8 | +84,1 | 2/5 |
| London 15m, SL seberang, tahan | 970 | 24% | +0,03 | −11,7 | −1,2 | −2,6 | −0,7 | +48,0 | 1/5 |
| **NY 15m, SL seberang, TP 1,5R** | 864 | 47% | +0,06 | +5,8 | +18,0 | +4,8 | +19,9 | +2,5 | **5/5** |
| NY 30m, SL seberang, TP 1,5R | 711 | 49% | +0,05 | −0,8 | +31,8 | +1,3 | +12,4 | −9,3 | 3/5 |
*2022 = Sep–Des.

- **ORB London (kandidat dari uji 13 bulan) ternyata hanya untung di 2026** — 2023–2025 rugi → kebetulan periode.
- **ORB NY 15m SL seberang TP 1,5R positif di 5/5 tahun**, tapi edge kecil (+0,06R/trade, DD maks 19,7R)
  dan merupakan 1 dari 24 variasi. NY buka 13:30 UTC = jam rilis data AS → slippage nyata bisa
  menghapus edge sekecil ini. Kandidat untuk diuji dengan spread/slippage lebih besar, belum siap demo.

## Catatan dari topik lain grup (dibaca 11 Nov 2026, isi grup tidak disalin ke repo)
Aturan entry yang disebut admin secara eksplisit (topik Edukasi):
- Area/zona sinyal scalping: perhatikan **OBIM** (Order Block + Imbalance) dan **Breaker Block**
  di start / mid / last zone.
- "**Candle terjepit**" (TF M15/M5/M3) sebagai area pantulan: candle searah di tengah, diapit
  2 candle berlawanan sebelum dan 2 sesudah; area = high–low candle tengah.
  Konfirmasi entry di **M1**: candle rejection (sumbu ≥ **61,8%** ukuran candle), engulfing, atau OBIM.
- Sinyal scalping berasal dari indikator berbayar "POI" (konfirmasi: Apache, rejection, FVG/IFVG,
  engulfing, RSI) — tidak tersedia untuk kita.
- Sinyal ambigu: ikuti notifikasi pertama. "Tidak semua sinyal harus diikuti" (ada diskresi).
Kandidat uji berikutnya: strategi **candle terjepit + konfirmasi M1 (rejection 61,8% / engulfing / OBIM)**,
dan filter sinyal grup memakai rejection 61,8% (sebelumnya diuji dengan 50%).

## Swing / trend-following H1–D1 (`swing.py`, `seasonality.py`) — 12 Nov 2026
Data H1 Exness Jan 2014 – Nov 2026 (13 tahun). Latih 2014–2019, uji 2020–2026. Hasil dalam R, spread bar
(min 2 pips) + slip 0,5 pip/sisi, SL & TP di bar sama = SL, 1 posisi per metode, **swap belum dihitung**.
77 variasi: Donchian breakout D1/H4 (n20/55), pullback RSI di tren EMA50/200, NR7 breakout, EMA cross;
exit 2R/3R/trailing chandelier 3–4 ATR; filter tren D1 (close vs EMA200 D1).

- XAUUSD: **32/32 variasi Donchian positif** (tidak sensitif parameter). Uji entry acak (arah & jumlah
  sama, 200×): Donchian di persentil 96–100 → timing breakout memberi edge, bukan sekadar ikut tren naik emas.
  | Variasi XAUUSD | n | WR | avgR | latih/uji avgR | long/short R | tahun+ | DD | hold |
  |---|---|---|---|---|---|---|---|---|
  | Donchian D1 n20, SL 2ATR, trail 3ATR, filter D1 | 102 | 48% | +0,45 | +0,35 / +0,54 | +40 / +6 | 12/13 | 8,8R | 14 hr |
  | Donchian D1 n55, trail 3ATR, filter D1 | 68 | 53% | +0,64 | +0,30 / +0,92 | +42 / +1 | 10/13 | 4,7R | 16 hr |
  | Donchian H4 n55, trail 4ATR, filter D1 | 248 | 33% | +0,29 | +0,26 / +0,31 | +68 / +3 | 9/13 | 19,4R | 4 hr |
  | Donchian H4 n20, TP 2R, tanpa filter | 749 | 38% | +0,13 | +0,13 / +0,13 | +94 / +2 | 8/13 | 18,4R | 3 hr |
- Pola jam/hari (seasonality): jendela jam terbaik di latih gagal di uji setelah biaya → **tidak dipakai**.
- Pair lain, aturan sama tanpa setel ulang (avgR): Donchian H4 n55 trail4 filter D1 → XAG +0,04 · EURUSD −0,06 ·
  USDJPY +0,09 · US500 (sejak 2022) +0,06 · BTC +0,13. Emas jauh paling kuat; perak & EURUSD lemah.
- Portofolio (risiko 0,5%/trade, tanpa compounding):
  emas 2 metode (D1 n20 + H4 n55) = +4,5%/thn, 10/13 tahun, DD 13% ·
  + BTC H4 n55 = +5,9%/thn, 9/13, DD 11% · + USDJPY + BTC = +6,7%/thn, 10/13, DD 15%.
- Catatan: edge emas sebagian besar dari sisi long (short ≈ impas). Hold D1 ±2 minggu → swap bisa
  signifikan bila akun tidak swap-free. Kandidat demo: Donchian D1 n20 trail3 filter D1 + H4 n55 trail4 filter D1 di XAUUSD.
