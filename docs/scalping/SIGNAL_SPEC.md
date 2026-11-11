# Signal Spec — Format Pesan & Aturan Parsing

Semua aturan di sini adalah **kontrak** untuk `parser.py` dan `price_resolver.py`.
Setiap contoh di dokumen ini wajib menjadi test case di `backend/tg_signal/tests/`.

---

## 1. Pesan sinyal

### Contoh asli
```
BUY 62-58

Entry tunggu konfirmasi di area yang diberikan
Cek Konfirmasi di M1 atau M5

Entry bisa di OBIM ( Order Block + Imbalance / FVG )

Atau pakai konfirmasi lain seperti yg ada di bagian edukasi

SL 30 pips
TP 10 pips boleh, 20 pips boleh, 30 juga boleh, lebih juga boleh, bebas sesuka hati kalian..

Karena ini scalping, maka target gak bisa jauh

Cek Pesan yg di-PIN ya gaesss... DYOR
```

### Field yang diambil
| Field | Sumber | Wajib | Default |
|---|---|---|---|
| `direction` | `BUY` / `SELL` di awal baris | ya | — |
| `level_first` | angka pertama (`62`) | ya | — |
| `level_last` | angka kedua (`58`) | ya | — |
| `sl_pips` | `SL 30 pips` | tidak | `30` |
| TP | diabaikan — provider membebaskan; TP ditentukan aturan kita | — | — |

Simbol selalu **XAUUSD** (grup ini khusus gold). Teks lain diabaikan.

### Variasi yang ditemukan di riwayat grup (Okt 2025 – Nov 2026)
Pengirim selalu admin bertanda tangan (`Admin 1`, `Admin 2`, `Admin 3`, `Admin 2+1`, `Admin 4`).
Format 2-digit dipakai sejak **Oktober 2025**; sebelumnya format bebas (diabaikan).

| Bentuk baris pertama | Contoh |
|---|---|
| standar | `BUY 62-58` |
| prefix simbol | `GOLD BUY 62-58`, `GOL BUY 62-58`, `XAUUSD BUY ...`, `BOLEH BUY LAGI 62-58` |
| simbol/kata setelah arah | `BUY GOLD 62-58`, `SELL ZONE 60-64`, `BUY GOLD ZONE 62-58`, `SELL NOW 62-66`, `SELL LAGI ...` |
| typo arah | `BBUY`, `BBBUY`, `SELLL`, `SELLN` |
| harga penuh 4 digit | `BUY 4162-4158` → dipakai apa adanya |
| typo 3 digit | `SELL 62-666` → ambil 2 digit terakhir + flag `LEVEL_TYPO` |

Sering ada **pesan pendek lalu pesan lengkap** dengan zona sama ±1 menit
(`GOLD BUY 95-91` lalu `GOLD BUY 95-91 + teks`) → ditangani aturan duplikat di bawah.

### Regex acuan
```python
PREFIX = r"(?:(?:GOLD|GOL|XAU|XAUUSD|BOLEH|ENTRY)\s+)*"
DIRECTION = r"(B+U+Y+|S+E+L+N?)"                 # dinormalisasi lewat huruf pertama
MIDWORD = r"(?:(?:GOLD|GOL|XAU|XAUUSD|ZONE|ZONA|NOW|LAGI)\s+)*"
SIGNAL_RE = re.compile(rf"^\s*{PREFIX}{DIRECTION}\s+{MIDWORD}(\d{{1,4}})\s*[-–]\s*(\d{{1,4}})\b", re.I | re.M)
SL_RE     = re.compile(r"\bSL\s*:?\s*(\d+)\s*pips?\b", re.I)
```

Level 1–2 digit = 2 digit terakhir (di-resolve). Level 4 digit = harga penuh.
Level 3 digit = typo → `n % 100` + flag `LEVEL_TYPO`.

### Validasi
| Aturan | Jika gagal |
|---|---|
| BUY: `level_first > level_last` setelah resolve (zona dari atas ke bawah) | flag `ZONE_ORDER_SUSPECT`, tetap simpan |
| SELL: `level_first < level_last` setelah resolve | flag `ZONE_ORDER_SUSPECT`, tetap simpan |
| Lebar zona 1–10 (normalnya 4) | flag `ZONE_WIDTH_SUSPECT` |
| Jarak zona dari harga sekarang ≤ `TG_MAX_ZONE_DISTANCE` ($15) | status `REJECTED` |
| Pesan diedit (Telegram edit event) | update sinyal bila status masih `WAITING`; bila sudah `OPEN` → log saja |
| Pesan sama terkirim ulang (zona & arah sama, < 5 menit) | abaikan sebagai duplikat |

---

## 2. Konversi 2 digit → harga penuh (`price_resolver`)

Angka di sinyal = **2 digit terakhir bagian bulat** harga XAUUSD.
Contoh: harga 4165.30, sinyal `62-58` → zona **4162 – 4158**.

### Algoritma
Setiap angka di-resolve **sendiri-sendiri** ke kandidat terdekat dari harga saat pesan diterima (`ref` = bid):

```python
def resolve(n: int, ref: float) -> float:
    base = math.floor(ref / 100) * 100
    candidates = [base - 100 + n, base + n, base + 100 + n]
    return min(candidates, key=lambda c: abs(c - ref))
```

Untuk backtest, `ref` = close candle M1 pada timestamp pesan.

### Test case
| ref | sinyal | hasil |
|---|---|---|
| 4165.30 | BUY 62-58 | 4162 / 4158 |
| 4199.50 | BUY 02-98 | 4202 / 4198 |
| 4201.20 | SELL 98-02 | 4198 / 4202 |
| 4148.00 | SELL 42-46 | 4142 / 4146 |
| 4103.00 | BUY 05-01 | 4105 / 4101 |
| 4097.00 | SELL 99-03 | 4099 / 4103 |
| 4130.00 | BUY 62-58 → 4162 / 4158, jarak > $15 | `REJECTED` |

---

## 3. Level dalam zona

Dugaan (akan divalidasi di Tahap 2, lihat O5 di PLAN):
**angka pertama = tepi zona yang disentuh harga lebih dulu**, angka kedua = ujung terdalam.

```
BUY 62-58  (harga datang dari atas)      SELL 42-46  (harga datang dari bawah)
  4162 ── ZERO                              4146 ── LAST
  4160 ── MID                               4144 ── MID
  4158 ── LAST                              4142 ── ZERO
```

| Level | Nilai |
|---|---|
| `zero` | `level_first` |
| `mid`  | `(level_first + level_last) / 2` |
| `last` | `level_last` |

---

## 4. Pesan laporan harian

### Contoh asli
```
Report Rabu (11-11-2026)
1. SELL 42-46 ✅ ZERO-TP
2. BUY 34-30 ✅ ZERO-TP
...
6. SELL 45-49 ❌ LAST-SL
...
20. SELL 59-63 ✅ MID-TP
```

### Regex acuan
```python
REPORT_HEADER_RE = re.compile(
    r"^\s*Report\s+[\w'’]+\s*\((\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{4})\)", re.I | re.M)
REPORT_LINE_RE   = re.compile(
    r"^\s*(\d+)\.\s*(BUY|SELL)\s+(\d{1,4})(?:\s*[-–]\s*(\d{1,4}))?\s*(✅|❌)?\s*(ZERO|MID|LAST)\s*-\s*(TP|SL)",
    re.I | re.M,
)
```
Variasi yang didukung: tanggal `D-M-YYYY` atau `DD-MM-YYYY`, hari `Jum'at`, titik dua di akhir header,
`ZERO - TP` / `ZERO -TP`, dan baris satu angka (`BUY 62 ✅ ZERO-TP` → `level_last` kosong).

### Field per baris
`no`, `direction`, `level_first`, `level_last` (boleh kosong), `win` (✅/❌), `depth` (ZERO/MID/LAST), `outcome` (TP/SL).

### Laporan bersifat kumulatif
Admin mengirim ulang laporan hari yang sama setelah setiap sinyal selesai (mis. 20–45 pesan
`Report` per tanggal, tiap kali bertambah satu baris). Yang dipakai: **pesan laporan terakhir per tanggal**.

### Kegunaan
- **Bukan** sinyal penutupan — hanya rekap.
- Dipakai untuk mencocokkan sinyal: baris ke-N laporan ↔ sinyal ke-N di tanggal itu
  (cek arah + 2 digit sama). Bila tidak cocok → flag `REPORT_MISMATCH`.
- Dipakai sebagai "ground truth" provider untuk dibandingkan dengan hasil kita.

---

## 5. Pesan update singkat dari admin

Ditemukan di riwayat (jumlah kira-kira), dikirim sebelum/sesudah sinyal lengkap:

| Pesan | Arti (dugaan) | Jumlah |
|---|---|---|
| `BUY NOW` / `SELL NOW` / `GOLD BUY NOW` / `XAU SELL NOW` | aba-aba sinyal akan/baru dikirim | ~8.000 |
| `TP`, `HIT TP`, `TP YAA`, `DONE TP` | sinyal terakhir hit TP | ~3.900 |
| `ZERO`, `MID`, `LAST`, `MID TP`, `LAST TP`, `TP DI LAST YAA` | TP tercapai, entry dari level itu | ~2.000 |
| `SL`, `LAST SL` | sinyal kena SL | ~540 |
| `INSTAN`, `INSTAN TP` | langsung TP tanpa masuk zona dalam | ~340 |

Belum dipakai di Tahap 1 (tetap `OTHER`). Kandidat untuk menandai sinyal selesai secara live (Tahap 3).

---

## 6. Pesan lain

Pesan yang tidak cocok dengan pola sinyal/laporan tetap **disimpan mentah** (`messages`)
dengan `kind = "OTHER"` agar bisa dianalisis — misalnya pengumuman, edukasi,
atau update seperti "SL BE" / "cancel" yang mungkin perlu didukung nanti.

Jika ditemukan pola update baru, tambahkan ke dokumen ini **sebelum** mengubah parser.
