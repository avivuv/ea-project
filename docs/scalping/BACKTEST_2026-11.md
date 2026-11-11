# Hasil Backtest Tahap 2 — Nov 2026

Data: M1 XAUUSD Exness (demo), **31 Jul – 11 Nov 2026** (histori M1 yang tersedia di terminal).
Sinyal: **2.458 sinyal unik** dari topik Scalping di rentang itu (~33/hari).
Reproduksi: `python -m tg_signal.backtest_tg` (opsi `--spread-pips`, `--validate`, `--check-offset`).

## Validasi data
- Offset jam server MT5 = **UTC+0** (median jarak harga→zona saat pesan: $0,68 vs ≥$7,6 di offset lain).
- Label laporan provider hanya bisa ditiru **~64%** (terbaik: TP 15–20 pips dihitung dari ZERO).
  TP provider tampaknya tidak tetap ("TP bebas"), jadi label tidak bisa direplikasi persis.

## Temuan utama
1. **Zona lebih lebar dari SL.** Zona `62-58` = $4 (40 pips), SL 30 pips = $3.
   Entry di ZERO dengan SL dari entry kena SL sebelum harga mencapai LAST.
   Provider tampaknya menghitung SL dari **LAST − 30 pips** (= 70 pips dari ZERO).
2. **Win rate 89% provider ≈ efek matematis TP kecil vs SL besar.** Dengan TP 10 dan SL 70 pips,
   pergerakan acak pun menang ~87,5%. Breakeven butuh WR > 87,5% (sebelum spread).
3. **Semua variasi negatif** dengan spread asli (median 1,7 pips):

| Variasi (entry / TP / SL) | Trade/hari | WR | Avg pips | Total pips | USD @0.01 |
|---|---|---|---|---|---|
| Limit ZERO / TP10 / SL dari entry | 33,3 | 64,4% | −4,25 | −10.350 | −$1.035 |
| Limit ZERO / TP10 / SL dari zona | 33,3 | 81,8% | −3,76 | −9.155 | −$915 |
| Limit ZERO / TP20 / SL dari zona | 33,3 | 73,9% | −2,58 | −6.265 | −$627 |
| Limit MID / TP30 / SL dari entry | 10,5 | 46,7% | −1,96 | −1.500 | −$150 |
| Layer 3 (Z/M/L) / TP10 / SL zona | 33,3 | 80,0% | −4,90 | −11.932 | −$1.193 |
| Konfirmasi OB M1 / TP10 / SL zona | 3,6 | 82,7% | −1,69 | −450 | −$45 |
| Konfirmasi FVG M1 / TP10 / SL zona | 2,1 | 79,5% | −3,26 | −492 | −$49 |

4. **Tanpa spread pun tidak ada edge.** Spread 0: Limit ZERO TP10 SL zona = −2,40 pips/trade;
   variasi terbaik ≈ impas (OB M1 TP10 SL zona −0,16; Limit MID TP30 SL entry +0,79 dari 762 trade).
5. Konsisten negatif di **semua admin, kedua arah, dan tiap bulan** (Agu, Sep, Okt, Nov).
   Variasi per jam terlihat acak (sampel kecil).
6. Konfirmasi FVG/OB membuat ~90% sinyal hangus sebelum entry (aturan D8): harga sudah
   +10 pips dari ZERO sebelum pola konfirmasi selesai. Konfirmasi M5 hampir tidak pernah terpicu.

## Keterbatasan
- Hanya ~3,5 bulan data; histori Okt 2025 – Jul 2026 belum terunduh di terminal.
- Spread/feed Exness bisa beda dengan broker yang dipakai provider.
- Asumsi konservatif: SL & TP di bar yang sama dihitung SL; bar fill limit hanya cek SL.
- Sinyal disimulasikan independen (tanpa batas posisi bersamaan).
- Definisi FVG/OB sederhana (pola 3 candle); konfirmasi "diskresi" admin tidak bisa ditiru.

## Tambahan: periode Okt 2025 – Jul 2026 (bar M5)
Server Exness hanya menyediakan ~100 ribu bar M1 terakhir (mulai 31 Jul 2026), walau
"Max bars in chart" = Unlimited. M5 tersedia sejak 1 Okt 2025, jadi periode lama diuji di M5.

M5 jauh lebih pesimis daripada M1 (dalam satu bar M5, urutan sentuh SL/TP tidak diketahui dan
dihitung SL), jadi **angka absolutnya tidak dipakai**. Yang dipakai adalah perbandingan periode
dengan bar yang sama:

| Variasi (bar M5) | Agu–Nov 2026 (kalibrasi) | Okt 2025 – Jul 2026 |
|---|---|---|
| Limit ZERO / TP10 / SL zona | −10,17 pips/trade | −10,20 |
| Limit ZERO / TP30 / SL zona | −5,73 | −5,37 |
| Limit MID / TP30 / SL zona | −4,87 | −4,73 |
| Limit LAST / TP30 / SL zona | −4,35 | −4,68 |

Periode lama (7.093 sinyal, ~36/hari) berperilaku hampir sama persis dengan periode yang diuji di M1.
Kesimpulan negatif dari data M1 kemungkinan besar berlaku untuk seluruh 13 bulan.
Reproduksi: `python -m tg_signal.market_data --fetch --tf M5` lalu
`python -m tg_signal.backtest_tg --bars M5 --start 2025-10-01 --end 2026-08-01`.
