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
- M1 hanya ~3,5 bulan (batas server Exness); periode Okt 2025 – Jul 2026 diuji di M5 (lihat bawah).
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

## Tambahan: konfirmasi 1 candle (rejection / pin bar) — M1, Agu–Nov 2026
Candle searah sinyal dengan sumbu ≥ 50% range yang menyentuh zona (`REJ`).

| Variasi | Trade/hari | WR | Avg pips | Avg pips tanpa spread |
|---|---|---|---|---|
| REJ / TP10 / SL entry (hangus +10) | 5,2 | 66,5% | −3,40 | −1,62 |
| REJ / TP10 / SL zona (hangus +10) | 5,2 | 79,1% | −4,23 | −2,45 |
| REJ / TP10 / SL entry (tanpa batas hangus) | 24,8 | 66,4% | −3,45 | — |

Juga negatif, bahkan tanpa spread. Melonggarkan batas hangus hanya menambah jumlah trade rugi.

## Tambahan: entry market saat sinyal diterima (admin posting SETELAH pasang posisi)
Info dari user: admin mengirim sinyal setelah ia sendiri entry. Hari 11 Nov 2026 mendukung ini —
10 dari 22 sinyal sudah bergerak ≥10 pips searah sinyal sebelum menyentuh zona, dan dilaporkan TP/"INSTAN".

| Variasi `MARKET` (M1, Agu–Nov 2026, 2.457 trade) | WR | Avg pips | Tanpa spread |
|---|---|---|---|
| TP10 / SL zona | 85,8% | −2,12 | −0,56 |
| TP10 / SL 30 dari entry | 69,8% | −2,10 | −0,73 |
| TP30 / SL 30 dari entry | 47,2% | −1,67 | +0,18 |

- Hari 11 Nov: MARKET TP10 SL zona = **21 TP / 1 SL, +143 pips** — tapi dari 73 hari, hanya 30 positif;
  median −78 pips/hari. Hari terburuk −615 pips (24 Agu).
- M5 Okt 2025 – Jul 2026: sama negatifnya dengan periode kalibrasi.
- Scan fitur saat sinyal (`features.py`: jarak ke zona, momentum 5/15 menit, posisi vs EMA20 M1,
  tren EMA20/50 M5, RSI, ATR, warna candle terakhir, jam): **tidak ada yang positif konsisten tiap bulan.**
  Jam 10, 13, 14 WIB terlihat positif secara total tapi negatif di salah satu bulan → kemungkinan kebetulan.
- Catatan: entry admin terjadi *sebelum* pesan dikirim, di harga yang lebih baik dari yang bisa kita dapat.

## Studi pola (`pattern_study.py`) — 11 Nov 2026
Entry market langsung, SL 30 dari entry, TP 10/15/20/30. Latih: Agu–Sep 2026 (1.484 sinyal),
uji: 1 Okt – 11 Nov 2026 (973 sinyal), harga M1. Fitur hanya dari informasi saat pesan diterima
(25 fitur: jarak ke zona, return 1/5/15/60 menit, ATR M1/M5, posisi dalam range 60 menit & harian,
EMA M5/H1, RSI M1/M5, candle terakhir, jam, hari, admin, jarak dari sinyal sebelumnya, urutan sinyal,
hasil sinyal sebelumnya yang sudah diketahui, ada/tidaknya aba-aba "NOW").

| Target | Model | AUC uji (0,5 = acak) |
|---|---|---|
| TP20 tercapai sebelum SL30 | logistic / gradient boosting | 0,488 / 0,478 |
| Label laporan admin = LAST | logistic / gradient boosting | 0,536 / 0,507 |

- Tidak ada fitur yang hubungannya konsisten di latih & uji untuk hasil TP/SL.
- Satu-satunya fitur konsisten (lemah) untuk label LAST: **`dist_to_zero`** — makin jauh harga
  dari tepi zona saat sinyal masuk (belum masuk zona), makin kecil peluang sampai LAST
  (korelasi −0,095 latih / −0,067 uji). Terlalu lemah untuk filter; dicatat sebagai hipotesis uji maju.
- Filter dari model tidak memperbaiki hasil secara konsisten (logistic TP20 −0,69 → +0,19 pips,
  gradient boosting −0,69 → −0,99) → kemungkinan kebetulan.
- Basis periode uji (Okt–Nov) lebih baik dari latih: TP10 −0,81, TP30 −0,96 pips/trade (vs −2,9 / −2,1).

Kesimpulan: dengan data harga + konteks sinyal, **belum ada pola yang bisa memilih sinyal TP**.
Langkah lanjut: kumpulkan data demo live, uji maju hipotesis `dist_to_zero` tanpa mengubah EA.

## Studi FVG sebagai filter kondisi (`fvg_context.py`, `fvg_study.py`) — 11 Nov 2026
Ide dari user (sinyal SELL 51-55 jam 17:50 tepat di FVG bearish M5 4051.14–4053.20):
entry langsung **hanya bila saat sinyal masuk sudah ada FVG searah di zona** (bukan menunggu konfirmasi).
Entry market, SL 30 dari entry. Angka = pips/trade.

| Aturan | TP30 Agu–Sep | TP30 Okt–Nov | TP20 Agu–Sep | TP20 Okt–Nov |
|---|---|---|---|---|
| Semua sinyal (EA sekarang) | −2,14 (1.484) | −0,96 (973) | −2,24 | −1,02 |
| FVG M5 searah di zona | −0,24 (371) | +0,61 (245) | −0,75 | −0,41 |
| FVG M5 searah, masih OPEN | +0,70 (172) | +1,50 (120) | −1,80 | +0,83 |
| **FVG M5 searah + tanpa FVG M1 berlawanan di jalur TP** | **+1,49 (202)** | **+1,38 (130)** | +0,45 | +0,77 |
| Tanpa FVG M5 searah | −2,78 | −1,48 | −2,73 | −1,22 |

Validasi periode lama Okt 2025 – Jul 2026 (bar M5, angka absolut pesimis ±2,3 pips; lihat kalibrasi di atas):

| Aturan | n | TP30 avg | vs semua |
|---|---|---|---|
| Semua sinyal | 7.052 | −3,72 | — |
| FVG M5 searah di zona | 2.234 | −3,28 | +0,44 |
| FVG M5 searah, masih OPEN | 1.293 | −2,90 | +0,82 |
| Tanpa FVG M5 searah | 4.818 | −3,92 | −0,20 |

Kesimpulan sementara:
- Arah efeknya **konsisten di 3 periode**: sinyal dengan FVG M5 searah di zona lebih baik daripada tanpa.
- Besarnya efek sedang (+0,4 s/d +1,5 pips/trade); di Agu–Nov 2026 cukup untuk positif, di periode lama
  (setelah koreksi pesimisme M5) masih sekitar −0,6 s/d −1,0.
- Sampel per aturan 120–200 trade per periode → masih bisa kebetulan; 11 aturan × 4 TP diuji.
- Kandidat aturan terkuat: **FVG M5 searah di zona (masih open) + tanpa FVG M1 berlawanan di jalur TP**.
  Perlu uji maju di data demo (dihitung ulang dari data M1, tanpa mengubah EA).

## Strategi sendiri: CHoCH + FVG + entry retest (`smc_strategy.py`) — 11 Nov 2026
Ide dari pengamatan admin (di luar topik Scalping). 48 variasi: TF M3/M5 × CHoCH (struktur berlawanan
dulu) / BOS biasa × entry tepi/tengah FVG × 1,5R/2R/3R × semua jam / London+NY. SL di bawah kaki impuls
(median ±40–55 pips), 1 setup aktif pada satu waktu, eksekusi bar M1 dengan spread asli.

| Variasi | Latih Agu–Sep (trade, WR, avg R) | Uji Okt–Nov (trade, WR, avg R) |
|---|---|---|
| M3 CHoCH, entry tepi FVG, 2R | 120, 35,8%, +0,08 | 84, 34,5%, **+0,04** |
| M3 CHoCH, entry tengah FVG, 2R | 106, 34,9%, +0,08 | 71, 33,8%, **+0,01** |
| M3 BOS, entry tepi, 2R (terbaik #2 di latih) | 208, 38,0%, +0,14 | 142, 28,9%, −0,13 |
| M5 CHoCH, tengah, 1,5R (terbaik #1 di latih) | 32, 50,0%, +0,25 | 32, 28,1%, −0,30 |

- Hanya **2 dari 48** variasi positif di latih dan uji, keduanya ±0 (+0,01 s/d +0,04 R/trade).
- Variasi terbaik di latih (M3 BOS, M5 CHoCH) **berbalik negatif** di uji → kebetulan.
- CHoCH (syarat struktur berlawanan) konsisten lebih baik daripada BOS biasa di M3.
- Periode lama (M5, Okt 2025 – Jul 2026): variasi terbaik lain lagi (M5 BOS mid 2R London/NY +0,07 R),
  sebagian besar sekitar 0 s/d −0,08 R → tidak konsisten antar periode.

Kesimpulan: versi mekanis CHoCH + FVG ≈ **impas, belum ada edge**. Penilaian admin (konteks, sweep
likuiditas, bias TF besar, kualitas impuls) kemungkinan yang membuat setup manualnya bagus.
Langkah lanjut yang masuk akal: kumpulkan contoh setup asli admin (dari topik lain di grup) untuk
mengkalibrasi definisi, lalu uji tambahan syarat sweep likuiditas & bias H1 — dengan risiko overfitting.

## Verifikasi sistem "TG Signal Layer" (folder `backend/CT Tele`, milik user) — 11 Nov 2026
Sistem itu: entry pending di ZERO (market bila harga sudah di zona), SL = LAST ± 30 pips,
**kunci SL +5 saat profit +10**, trailing (Akun1: TP30, trail mulai +15 step 5; Akun2: TP100, trail mulai +40 step 20).
Panduannya: backtest 12 Okt – 10 Nov 2026, spread 0,8 pips → Akun1 +$19, Akun2 +$132 (skenario terburuk).
Kode verifikasi: `tg_signal/managed_backtest.py` (M1, per sinyal independen, 0,01 lot).

**Jebakan simulasi**: versi pertama kami memicu kunci +10 dari high bar fill yang bisa terjadi SEBELUM
limit terisi → Akun1 tampak +$1.374 (Agu–Nov). Setelah diperbaiki (bar fill tidak memicu kunci; gap
melewati SL keluar di open) → **−$615**. Aturan kunci sangat sensitif terhadap urutan harga di dalam candle.

| Periode / spread | Akun1 TP30 kunci+trail | Akun2 TP100 trail40 | TP30 tanpa kunci | TP100 tanpa kunci |
|---|---|---|---|---|
| 12 Okt–10 Nov, spread 0,8 (= panduan) | +$22 | **+$126** | −$13 | −$157 |
| 12 Okt–10 Nov, spread asli 1,7 | −$15 | +$91 | −$87 | −$216 |
| Agu–Nov (2.274 trade), spread asli: paruh 1 / paruh 2 | −$503 / −$112 | −$406 / **+$73** | −$483 / −$315 | −$807 / −$651 |
| Agu–Nov total, spread asli | −$615 | **−$333** | −$798 | −$1.459 |

- Angka panduan **tereplikasi** di periodenya (Akun2 +$126 vs +$132) — tapi periode itu memang periode terbaik.
- Di 3,5 bulan dengan spread asli, semua varian negatif; **aturan kunci + trailing konsisten memperbaiki**
  dibanding SL/TP tetap (Akun2 vs TP100 tanpa kunci: −$406 vs −$807 dan +$73 vs −$651).
- Spread sangat menentukan: 0,8 vs 1,7 pips ≈ selisih $35–40 per 660 trade.
- Entry di pesan "Buy/Sell Now": diuji di panduan → lebih buruk (harga entry lebih jelek).

## Resep konfirmasi admin (topik Edukasi): rejection ≥61,8% / engulfing / OBIM di M1 — 11 Nov 2026
Konfirmasi dievaluasi di M1 setelah harga menyentuh zona; entry di open bar berikutnya. Agu–Nov 2026, spread asli.
Avg pips/trade (trade):

| Konfirmasi | TP30 SL entry (hangus +10) | TP30 SL entry (tanpa batas hangus) | TP10 SL zona (hangus +10) |
|---|---|---|---|
| Tanpa konfirmasi (EA sekarang) | −1,67 (2.457) | −1,67 | — |
| Rejection ≥ 61,8% | **−1,32** (410) | −1,46 (1.850) | −2,77 (410) |
| Engulfing | −4,94 (249) | −2,09 (1.608) | −2,49 (249) |
| Salah satu (rejection 61,8% / engulfing / OBIM) | −3,10 (493) | −1,83 (2.060) | −2,64 (493) |

Kesimpulan: versi mekanis resep konfirmasi admin **tidak membuat sinyal menguntungkan**; rejection 61,8%
hanya sedikit lebih baik dari entry langsung. Yang sejauh ini paling memperbaiki hasil adalah
pengelolaan posisi (kunci +10 → +5 + trailing), bukan konfirmasi entry.
