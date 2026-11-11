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
