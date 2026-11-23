//+------------------------------------------------------------------+
//| ProPOI.mq5 — marker POI strategi sendiri (tg_signal/pro_live.py) |
//| Membaca Common\Files\pro_poi.csv (ditulis pro_live tiap bar M5)  |
//| dan menggambar di canvas transparan (ARGB):                       |
//|   kotak POI M15 (FVG/OB/IFVG), POI "armed" (tunggu CHoCH M5),     |
//|   tanda CHoCH M5 (garis swing → bar break + label) dan level      |
//|   CHoCH yang sedang ditunggu (garis putus), garis entry/SL/TP.    |
//| + area ORB New York (tg_signal/orb_live.py → orb_area.csv):       |
//|   kotak opening range 15 mnt, garis level breakout, panah         |
//|   breakout, entry / SL / TP posisi ORB. Chart non-XAU (mis.       |
//|   ETHUSD) hanya menggambar ORB dari orb_area_<simbol>.csv.        |
//| + garis EMA50 H1 (filter bias Pro & ORB XAU), dihitung langsung   |
//|   dari bar H1: hijau = bias BUY (close > EMA & EMA naik > 0.1 ATR  |
//|   / 3 bar), merah = bias SELL, abu-abu = netral; label bias kini.  |
//| + Trend MA Cross (tg_signal/mac_live.py) di TF pilihan (H1/H4): SMA|
//|   5/13/21/34 + EMA200, tanda sinyal (MA5 cross 3 MA + EMA200       |
//|   searah vs 10 bar lalu) dan label status.                        |
//| + Swing Donchian (intraday/swing_live.py): XAU D1 20 & H4 55,     |
//|   BTC H4 55 — channel, breakout searah tren D1 EMA200, level bar  |
//|   berjalan, posisi swing + SL trailing. Metode XAU (POI, EMA50,   |
//|   MAC) tidak digambar di BTC karena tidak dipakai di sana.        |
//| Trend MA Cross: sinyal & status H1 + H4; garis MA satu TF.        |
//| Canvas dipakai karena kotak bawaan MT5 tidak bisa transparan dan  |
//| area yang bertumpuk jadi putih (XOR).                             |
//| Hanya tampilan — tidak membuka order apa pun.                     |
//+------------------------------------------------------------------+
#property copyright   "ea-project"
#property version     "2.70"
#property description "Marker POI strategi sendiri (FVG/OB/IFVG M15, armed, CHoCH M5, entry/SL/TP) + area ORB New York + EMA50 H1 bias + Trend MA Cross H1/H4 + Swing Donchian (XAU D1/H4, BTC H4)"
#property indicator_chart_window
#property indicator_plots 0

#include <Canvas\Canvas.mqh>

input string InpFile       = "pro_poi.csv";     // file di folder Common\Files
input uchar  InpAlpha      = 40;                // transparansi isi kotak (0 = tembus, 255 = pekat)
input uchar  InpBorderAlpha = 140;              // transparansi garis tepi
input bool   InpShowOff    = true;              // tampilkan POI arah yang bias-nya tidak aktif
input color  InpBuyColor   = C'0,150,80';       // demand (bias BUY aktif)
input color  InpSellColor  = C'215,45,45';      // supply (bias SELL aktif)
input color  InpOffColor   = C'130,130,130';    // POI tanpa bias
input color  InpArmedColor = C'230,170,0';      // POI yang sedang disentuh, tunggu CHoCH
input bool   InpShowChoch  = true;              // tampilkan tanda CHoCH M5 & level CHoCH yang ditunggu
input color  InpChochBuy   = C'0,170,120';      // CHoCH bullish (close di atas swing high)
input color  InpChochSell  = C'235,80,140';     // CHoCH bearish (close di bawah swing low)
input color  InpEntryColor = C'30,120,255';
input color  InpSLColor    = C'230,60,60';
input color  InpTPColor    = C'20,170,60';
input color  InpTextColor  = C'110,110,110';
input bool   InpShowOrb    = true;              // tampilkan area ORB New York
input string InpFileOrb    = "orb_area.csv";    // file ORB XAUUSD (simbol lain: orb_area_<simbol>.csv)
input color  InpOrbColor   = C'150,90,230';     // kotak opening range ORB
input int    InpOrbHoldMin = 360;               // panjang garis level ORB (menit sejak NY buka)
input bool   InpShowEma    = true;              // tampilkan EMA50 H1 + status bias (hanya chart XAU)
input int    InpEmaSpan    = 50;                // = EMA_SPAN pro_live / orb.h1_bias
input double InpEmaSlope   = 0.1;               // = MIN_SLOPE (× ATR14 H1, kemiringan EMA dalam 3 bar)
input int    InpEmaWidth   = 2;                 // tebal garis EMA (px)
input color  InpEmaNeutral = C'150,150,150';    // EMA saat bias netral
input bool   InpShowMac   = true;              // tampilkan Trend MA Cross (SMA 5/13/21/34 + EMA200) — hanya chart XAU
input ENUM_TIMEFRAMES InpMacTf = PERIOD_H1;    // TF garis MA yang digambar: H1 atau H4 (sinyal & status: H1 + H4)
input bool   InpMacSignal = true;              // tanda sinyal Trend MA Cross H1 + H4 (MA5 cross 3 MA + EMA200 searah 10 bar)
input color  InpMacMa5    = C'255,215,0';
input color  InpMacMa13   = C'255,140,0';
input color  InpMacMa21   = C'0,180,220';
input color  InpMacMa34   = C'70,110,255';
input color  InpMacEma    = C'190,120,255';    // EMA200
input bool   InpShowDon   = true;              // Swing Donchian + tren D1 (XAU: D1 20 & H4 55 · BTC: H4 55)
input color  InpDonColor  = C'0,150,200';      // channel Donchian H4 55
input color  InpDonD1Color = C'200,120,0';     // channel Donchian D1 20 (XAU)
input color  InpDonSlColor = C'230,60,60';     // SL trailing posisi swing

#define NAME "PROPOI_canvas"
#define EMA_BARS 1000                               // bar H1 yang dihitung (EMA adjust=False konvergen jauh sebelum ini)

datetime g_et[];                                     // waktu buka bar H1 (sudah close), lama → baru
double   g_ev[];                                     // nilai EMA
int      g_eb[];                                     // bias bar itu: 1 BUY, -1 SELL, 0 netral
double   g_eslope = 0;                               // kemiringan EMA bar terakhir (× ATR)

#define MAC_BARS 1500
// indeks k: 0 = H1 (XAU_H1_MAC), 1 = H4 (XAU_H4_MAC) — mac_live menjalankan keduanya
int      g_bn[2];                                    // jumlah bar per TF
datetime g_bt[2][MAC_BARS];                          // waktu buka bar (sudah close), lama → baru
double   g_bh[2][MAC_BARS], g_bl[2][MAC_BARS];       // high / low (posisi tanda sinyal)
double   g_bm[2][5][MAC_BARS];                       // SMA5, SMA13, SMA21, SMA34, EMA200 (0 = belum ada)
int      g_bs[2][MAC_BARS];                          // sinyal di bar itu: 1 BUY, -1 SELL, 0 tidak ada
int      g_bup[2];                                   // posisi MA5 bar terakhir: 1 di atas 3 MA, -1 di bawah, 0 campur
int      g_bslope[2];                                // EMA200 vs 10 bar lalu: 1 naik, -1 turun

struct Row { string rec, dir, kind; datetime t1; double p1, p2, p3; int flag; };
Row     g_rows[];
CCanvas g_cv;
int     g_or_min = 15;                              // panjang opening range (dari baris HDR file ORB)

bool IsGold() { return(StringFind(_Symbol, "XAUUSD") >= 0); }
bool IsBtc()  { return(StringFind(_Symbol, "BTCUSD") >= 0); }

//--- Swing Donchian (intraday/swing.py + swing_live.py): bar H4 & D1 di-resample dari H1 dengan batas jam UTC
//    (sama dengan pandas resample), channel = high/low n bar TF sebelumnya, sinyal = close TF di luar channel
//    DAN searah tren D1 (close D1 vs EMA200 D1, berlaku setelah D1 close). Metode = swing_live.METHODS.
#define DON_H1  20000                               // = H1_BARS swing_live
#define DON_MAX 2                                   // metode per simbol
int      g_dm = 0;                                  // jumlah metode Donchian simbol ini
string   g_dmid[DON_MAX], g_dmex[DON_MAX];          // id metode, keterangan exit
int      g_dmtf[DON_MAX], g_dmn[DON_MAX];           // TF (detik), periode
long     g_dmmg[DON_MAX];                           // magic
color    g_dmc[DON_MAX];
datetime g_dt[];                                    // waktu buka bin (jam server), hanya bin lengkap, per metode berurutan
double   g_dh[], g_dl[], g_dc[];                    // level channel (high/low n bin sebelumnya; 0 = belum ada), close
int      g_ds[], g_dmi[];                           // 1/-1 sinyal searah tren · 2/-2 tren D1 berlawanan · indeks metode
double   g_dnh[DON_MAX], g_dnl[DON_MAX];            // channel untuk bin yang sedang berjalan
datetime g_dnt[DON_MAX];                            // waktu buka bin yang sedang berjalan
int      g_dtr = 0;                                 // tren D1 kini: 1 / -1 / 0
double   g_dema = 0;                                // EMA200 D1 kini
datetime g_dbar = 0;                                // bar H1 terakhir yang sudah dihitung

void DonAdd(string id, int tf, int n, long magic, string ex, color c)
  {
   g_dmid[g_dm] = id;
   g_dmtf[g_dm] = tf;
   g_dmn[g_dm] = n;
   g_dmmg[g_dm] = magic;
   g_dmex[g_dm] = ex;
   g_dmc[g_dm] = c;
   g_dm++;
  }

//--- bin lengkap TF `tf` (detik, batas UTC) dari bar H1; return jumlah bin
int DonBins(const MqlRates &r[], int n, long off, int tf, datetime cur, datetime &st[], double &hh[], double &ll[],
            double &cc[])
  {
   int nb = 0, rsv = n / (tf / 3600) + 2;
   long last = -1;
   for(int i = 0; i < n; i++)
     {
      long k = ((long)r[i].time - off) / tf;
      datetime t = (datetime)(k * tf + off);
      if(t + tf > cur)
         break;                                       // bin yang sedang berjalan
      if(k != last)
        {
         nb++;
         ArrayResize(st, nb, rsv);
         ArrayResize(hh, nb, rsv);
         ArrayResize(ll, nb, rsv);
         ArrayResize(cc, nb, rsv);
         st[nb - 1] = t;
         hh[nb - 1] = r[i].high;
         ll[nb - 1] = r[i].low;
         last = k;
        }
      hh[nb - 1] = MathMax(hh[nb - 1], r[i].high);
      ll[nb - 1] = MathMin(ll[nb - 1], r[i].low);
      cc[nb - 1] = r[i].close;
     }
   return(nb);
  }

void CalcDon()
  {
   g_dm = 0;
   if(InpShowDon && IsGold())
     {
      DonAdd("XAU_D1_DON20", 86400, 20, 26111201, "trailing 3×ATR D1", InpDonD1Color);
      DonAdd("XAU_H4_DON55", 14400, 55, 26111202, "BE 1R + trailing 5×ATR H4", InpDonColor);
     }
   else if(InpShowDon && IsBtc())
      DonAdd("BTC_H4_DON55", 14400, 55, 26111203, "trailing 6×ATR H4", InpDonColor);
   if(g_dm == 0)
     {
      ArrayResize(g_dt, 0);
      return;
     }
   datetime cur = iTime(_Symbol, PERIOD_H1, 0);      // bar H1 berjalan (= now_bar swing_live)
   if(cur == 0 || cur == g_dbar)
      return;
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = CopyRates(_Symbol, PERIOD_H1, 1, DON_H1 - 1, r);   // = h1() swing_live: 20000 bar − bar berjalan
   if(n < 24 * 60)
      return;
   g_dbar = cur;
   long off = (long)MathRound((double)(TimeTradeServer() - TimeGMT()) / 3600.0) * 3600;   // server − UTC
   //--- tren D1: close D1 vs EMA200 D1 (bin D1 lengkap)
   datetime d_t[];
   double   d_h[], d_l[], d_c[], d_tr[];
   int nd = DonBins(r, n, off, 86400, cur, d_t, d_h, d_l, d_c);
   ArrayResize(d_tr, nd);
   double ema = nd > 0 ? d_c[0] : 0, al = 2.0 / 201.0;
   for(int j = 0; j < nd; j++)
     {
      if(j > 0)
         ema = al * d_c[j] + (1 - al) * ema;
      d_tr[j] = d_c[j] > ema ? 1 : d_c[j] < ema ? -1 : 0;
     }
   g_dema = ema;
   g_dtr = nd > 0 ? (int)d_tr[nd - 1] : 0;
   //--- per metode
   ArrayResize(g_dt, 0);
   int tot = 0;
   for(int q = 0; q < g_dm; q++)
     {
      int tf = g_dmtf[q], N = g_dmn[q];
      datetime st[];
      double hh[], ll[], cc[];
      int nb = DonBins(r, n, off, tf, cur, st, hh, ll, cc);
      ArrayResize(g_dt, tot + nb);
      ArrayResize(g_dh, tot + nb);
      ArrayResize(g_dl, tot + nb);
      ArrayResize(g_dc, tot + nb);
      ArrayResize(g_ds, tot + nb);
      ArrayResize(g_dmi, tot + nb);
      int jd = -1;
      for(int i = 0; i < nb; i++)
        {
         int o = tot + i;
         g_dt[o] = st[i];
         g_dc[o] = cc[i];
         g_dmi[o] = q;
         g_dh[o] = 0;
         g_dl[o] = 0;
         g_ds[o] = 0;
         if(i < N)
            continue;
         double hi = hh[i - N], lo = ll[i - N];
         for(int m = i - N + 1; m < i; m++)
           {
            hi = MathMax(hi, hh[m]);
            lo = MathMin(lo, ll[m]);
           }
         g_dh[o] = hi;
         g_dl[o] = lo;
         int d = cc[i] > hi ? 1 : cc[i] < lo ? -1 : 0;
         if(d == 0)
            continue;
         datetime tc = st[i] + tf;                    // sinyal berlaku saat bin close
         while(jd + 1 < nd && d_t[jd + 1] + 86400 <= tc)
            jd++;
         int tr = jd >= 0 ? (int)d_tr[jd] : 0;
         g_ds[o] = tr == d ? d : 2 * d;
        }
      tot += nb;
      //--- channel untuk bin berjalan = N bin lengkap terakhir
      g_dnh[q] = 0;
      g_dnl[q] = 0;
      g_dnt[q] = nb > 0 ? st[nb - 1] + tf : 0;
      if(nb >= N)
        {
         g_dnh[q] = hh[nb - N];
         g_dnl[q] = ll[nb - N];
         for(int m = nb - N + 1; m < nb; m++)
           {
            g_dnh[q] = MathMax(g_dnh[q], hh[m]);
            g_dnl[q] = MathMin(g_dnl[q], ll[m]);
           }
        }
     }
  }

string OrbFile()
  {
   if(IsGold())
      return(InpFileOrb);
   string s = _Symbol;
   StringToLower(s);
   return("orb_area_" + s + ".csv");
  }
int     g_w = 0, g_h = 0;

void ReadAll()
  {
   ArrayResize(g_rows, 0);
   if(IsGold())
      ReadFile(InpFile);
   if(InpShowOrb)
      ReadFile(OrbFile());
   CalcEma();
   CalcMac();
   CalcDon();
  }

//--- Trend MA Cross, identik dengan mac_deep.indicators / live_signal (SMA close, EMA200 ewm adjust=False, slope 10 bar)
void CalcMac()
  {
   g_bn[0] = 0;
   g_bn[1] = 0;
   if(!InpShowMac || !IsGold())
      return;
   CalcMacTf(0, PERIOD_H1);
   CalcMacTf(1, PERIOD_H4);
  }

void CalcMacTf(int k, ENUM_TIMEFRAMES tf)
  {
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = CopyRates(_Symbol, tf, 1, MAC_BARS, r);   // hanya bar yang sudah close
   if(n < 250)
      return;
   int per[4] = {5, 13, 21, 34};
   double a = 2.0 / 201.0;
   for(int i = 0; i < n; i++)
     {
      g_bt[k][i] = r[i].time;
      g_bh[k][i] = r[i].high;
      g_bl[k][i] = r[i].low;
      for(int m = 0; m < 4; m++)
        {
         g_bm[k][m][i] = 0;
         if(i >= per[m] - 1)
           {
            double s = 0;
            for(int j = i - per[m] + 1; j <= i; j++)
               s += r[j].close;
            g_bm[k][m][i] = s / per[m];
           }
        }
      g_bm[k][4][i] = i == 0 ? r[i].close : a * r[i].close + (1 - a) * g_bm[k][4][i - 1];
     }
   int prev = 0;
   for(int i = 0; i < n; i++)
     {
      int up = MacUp(k, i);
      g_bs[k][i] = 0;
      if(i > 210 && up != 0 && up != prev && up * (g_bm[k][4][i] - g_bm[k][4][i - 10]) > 0)
         g_bs[k][i] = up;
      prev = up;
     }
   g_bup[k] = MacUp(k, n - 1);
   double d = g_bm[k][4][n - 1] - g_bm[k][4][n - 11];
   g_bslope[k] = d > 0 ? 1 : d < 0 ? -1 : 0;
   g_bn[k] = n;
  }

//--- 1 bila MA5 di atas SMA13/21/34, -1 bila di bawah ketiganya, 0 campur / data belum cukup
int MacUp(int k, int i)
  {
   if(g_bm[k][3][i] == 0)
      return(0);
   double a = g_bm[k][0][i];
   if(a > g_bm[k][1][i] && a > g_bm[k][2][i] && a > g_bm[k][3][i])
      return(1);
   if(a < g_bm[k][1][i] && a < g_bm[k][2][i] && a < g_bm[k][3][i])
      return(-1);
   return(0);
  }

//--- garis antar dua titik, dipotong di tepi skala harga
void LineSeg(int xa, int ya, int xb, int yb, color c, int width, uchar alpha)
  {
   int xr = g_w - 60;
   if(xb < 0 || xa >= xr || xb == xa)
      return;
   if(xb > xr)
     {
      yb = ya + (int)MathRound((double)(yb - ya) * (xr - xa) / (double)(xb - xa));
      xb = xr;
     }
   if(width > 1)
      g_cv.LineThick(xa, ya, xb, yb, ColorToARGB(c, alpha), width, STYLE_SOLID, LINE_END_ROUND);
   else
      g_cv.LineAA(xa, ya, xb, yb, ColorToARGB(c, alpha));
  }

void DrawMac()
  {
   int kl = InpMacTf == PERIOD_H4 ? 1 : 0;            // TF garis MA
   int n = g_bn[kl];
   color cl[5];
   cl[0] = InpMacMa5; cl[1] = InpMacMa13; cl[2] = InpMacMa21; cl[3] = InpMacMa34; cl[4] = InpMacEma;
   for(int m = 0; m < 5 && n >= 2; m++)
     {
      int px = 0, py = 0;
      bool have = false;
      for(int i = 0; i < n; i++)
        {
         int x, y;
         if(g_bm[kl][m][i] == 0 || !XY(g_bt[kl][i], g_bm[kl][m][i], x, y))
           {
            have = false;
            continue;
           }
         if(have)
            LineSeg(px, py, x, y, cl[m], m == 4 ? 2 : 1, 210);
         px = x;
         py = y;
         have = true;
        }
     }
   string tfs[2] = {"H1", "H4"};
   for(int k = 0; k < 2; k++)
     {
      int nk = g_bn[k];
      if(nk < 2)
         continue;
      if(InpMacSignal)
         for(int i = 0; i < nk; i++)
           {
            if(g_bs[k][i] == 0)
               continue;
            bool buy = g_bs[k][i] == 1;
            int x, y;
            if(!XY(g_bt[k][i], buy ? g_bl[k][i] : g_bh[k][i], x, y) || x < 0 || x >= g_w - 60)
               continue;
            color c = buy ? InpBuyColor : InpSellColor;
            int dy = k == 1 ? 16 : 0;                  // H4 sedikit lebih jauh agar tidak menumpuk dengan H1
            g_cv.TextOut(x, buy ? y + 4 + dy : y - 26 - dy, buy ? "▲" : "▼", ColorToARGB(c, 255), TA_CENTER);
            g_cv.TextOut(x + 8, buy ? y + 6 + dy : y - 24 - dy, "MA CROSS " + tfs[k] + (buy ? " BUY" : " SELL"),
                         ColorToARGB(c, 230));
           }
      int up = g_bup[k], sl = g_bslope[k];
      string pos = up == 1 ? "MA5 di atas 3 MA" : up == -1 ? "MA5 di bawah 3 MA" : "MA5 campur";
      string sls = sl == 1 ? "EMA200 naik" : sl == -1 ? "EMA200 turun" : "EMA200 datar";
      color c = (up != 0 && up == sl) ? (up == 1 ? InpBuyColor : InpSellColor) : InpEmaNeutral;
      g_cv.TextOut(8, 40 + 16 * k, "Trend MA Cross " + tfs[k] + (k == kl ? " (garis)" : "") + " · " + pos + " · " + sls,
                   ColorToARGB(c, 255));
     }
  }

//--- EMA50 H1 + bias, identik dengan orb.h1_bias / pro_strategy.Market (ewm adjust=False, ATR = rata2 high-low 14)
void CalcEma()
  {
   ArrayResize(g_et, 0);
   if(!InpShowEma || !IsGold())
      return;
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = CopyRates(_Symbol, PERIOD_H1, 1, EMA_BARS, r);   // mulai shift 1 → hanya bar yang sudah close
   if(n < InpEmaSpan + 20)
      return;
   ArrayResize(g_et, n);
   ArrayResize(g_ev, n);
   ArrayResize(g_eb, n);
   double a = 2.0 / (InpEmaSpan + 1.0), sum_rng = 0;
   double rng[];
   ArrayResize(rng, n);
   for(int i = 0; i < n; i++)
     {
      g_et[i] = r[i].time;
      g_ev[i] = i == 0 ? r[i].close : a * r[i].close + (1 - a) * g_ev[i - 1];
      rng[i] = r[i].high - r[i].low;
      sum_rng += rng[i];
      if(i >= 14)
         sum_rng -= rng[i - 14];
      g_eb[i] = 0;
      if(i >= 13 && i >= 3)
        {
         double atr = sum_rng / 14.0, slope = g_ev[i] - g_ev[i - 3];
         if(r[i].close > g_ev[i] && slope > InpEmaSlope * atr)
            g_eb[i] = 1;
         else if(r[i].close < g_ev[i] && slope < -InpEmaSlope * atr)
            g_eb[i] = -1;
         if(i == n - 1 && atr > 0)
            g_eslope = slope / atr;
        }
     }
  }

void DrawEma()
  {
   int n = ArraySize(g_et);
   if(n < 2)
      return;
   int xr = g_w - 60;
   int px = 0, py = 0;
   bool have = false;
   for(int i = 0; i < n; i++)
     {
      int x, y;
      if(!XY(g_et[i], g_ev[i], x, y))
        {
         have = false;
         continue;
        }
      if(have && x >= 0 && px < xr && x != px)
        {
         color c = g_eb[i] == 1 ? InpBuyColor : g_eb[i] == -1 ? InpSellColor : InpEmaNeutral;
         int xa = px, ya = py, xb = x, yb = y;
         if(xb > xr)                                 // potong di tepi skala harga
           {
            yb = ya + (int)MathRound((double)(yb - ya) * (xr - xa) / (double)(xb - xa));
            xb = xr;
           }
         if(InpEmaWidth > 1)
            g_cv.LineThick(xa, ya, xb, yb, ColorToARGB(c, 220), InpEmaWidth, STYLE_SOLID, LINE_END_ROUND);
         else
            g_cv.LineAA(xa, ya, xb, yb, ColorToARGB(c, 220));
        }
      px = x;
      py = y;
      have = true;
     }
   //--- label status bias bar H1 terakhir yang sudah close
   int b = g_eb[n - 1];
   color c = b == 1 ? InpBuyColor : b == -1 ? InpSellColor : InpEmaNeutral;
   string st = b == 1 ? "bias BUY" : b == -1 ? "bias SELL" : "netral";
   string txt = "EMA" + IntegerToString(InpEmaSpan) + " H1 " + DoubleToString(g_ev[n - 1], _Digits) + " · " + st +
                " · slope " + DoubleToString(g_eslope, 2) + " ATR (min " + DoubleToString(InpEmaSlope, 2) + ")";
   g_cv.TextOut(8, 24, txt, ColorToARGB(c, 255));   // di bawah teks simbol/OHLC bawaan chart
  }

int OnInit()
  {
   EventSetTimer(5);
   ReadAll();
   Render();
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   g_cv.Destroy();
   ObjectsDeleteAll(0, "PROPOI_");
   ChartRedraw();
  }

void OnTimer()
  {
   ReadAll();
   Render();
  }

void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
  {
   if(id == CHARTEVENT_CHART_CHANGE)
      Render();                                   // geser / zoom / ganti TF → gambar ulang
  }

int OnCalculate(const int rates_total, const int prev_calculated, const int begin, const double &price[])
  {
   return(rates_total);
  }

//--- baca file CSV (8 kolom per baris), ditambahkan ke g_rows
void ReadFile(const string file)
  {
   int h = FileOpen(file, FILE_READ | FILE_CSV | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE, ',');
   if(h == INVALID_HANDLE)
      return;
   int k = ArraySize(g_rows);
   while(!FileIsEnding(h) && k < 1000)
     {
      Row r;
      r.rec  = FileReadString(h);
      r.dir  = FileReadString(h);
      r.kind = FileReadString(h);
      r.t1   = (datetime)StringToInteger(FileReadString(h));
      r.p1   = StringToDouble(FileReadString(h));
      r.p2   = StringToDouble(FileReadString(h));
      r.p3   = StringToDouble(FileReadString(h));
      r.flag = (int)StringToInteger(FileReadString(h));
      if(r.rec == "HDR" && r.kind != "")
         g_or_min = (int)StringToInteger(r.kind);
      if(r.rec == "POI" || r.rec == "ARMED" || r.rec == "ORDER" || r.rec == "ORB" || r.rec == "ORBBRK" ||
         r.rec == "ORBORD" || r.rec == "CHOCH")
        {
         ArrayResize(g_rows, k + 1);
         g_rows[k++] = r;
        }
     }
   FileClose(h);
  }

//--- konversi waktu/harga → piksel
bool XY(datetime t, double p, int &x, int &y)
  {
   if(!ChartTimePriceToXY(0, 0, t, p, x, y))
      return(false);
   return(true);
  }

int ClampX(int x) { return(MathMax(0, MathMin(g_w - 1, x))); }

void Box(datetime t1, double lo, double hi, color c, uchar fill_a, uchar line_a, int width)
  {
   int x1, y1, x2, y2;
   if(!XY(t1, hi, x1, y1) || !XY(t1, lo, x2, y2))
      return;
   x1 = ClampX(x1);
   int xr = g_w - 60;                              // sampai dekat skala harga kanan
   if(xr <= x1)
      return;
   if(fill_a > 0)
      g_cv.FillRectangle(x1, y1, xr, y2, ColorToARGB(c, fill_a));
   for(int i = 0; i < width; i++)
      g_cv.Rectangle(x1 + i, y1 + i, xr - i, y2 - i, ColorToARGB(c, line_a));
  }

void Label(datetime t, double p, const string txt, color c, uchar a = 255)
  {
   int x, y;
   if(!XY(t, p, x, y))
      return;
   g_cv.TextOut(ClampX(x) + 3, y - 13, txt, ColorToARGB(c, a));
  }

//--- kotak dengan batas waktu kiri-kanan (area ORB)
void Box2(datetime t1, datetime t2, double lo, double hi, color c, uchar fill_a, uchar line_a)
  {
   int x1, y1, x2, y2;
   if(!XY(t1, hi, x1, y1) || !XY(t2, lo, x2, y2))
      return;
   if(x2 < 0 || x1 > g_w - 60)
      return;
   x1 = ClampX(x1);
   x2 = MathMin(ClampX(x2), g_w - 60);
   if(x2 <= x1)
      x2 = x1 + 2;
   g_cv.FillRectangle(x1, y1, x2, y2, ColorToARGB(c, fill_a));
   g_cv.Rectangle(x1, y1, x2, y2, ColorToARGB(c, line_a));
  }

//--- garis horizontal terbatas waktu
void Seg(datetime t1, datetime t2, double p, color c, uchar a)
  {
   int x1, y1, x2, y2;
   if(!XY(t1, p, x1, y1) || !XY(t2, p, x2, y2))
      return;
   if(x2 < 0 || x1 > g_w - 60)
      return;
   g_cv.LineHorizontal(ClampX(x1), MathMin(ClampX(x2), g_w - 60), y1, ColorToARGB(c, a));
  }

//--- garis horizontal putus-putus dari t1 ke tepi kanan
void DashRight(datetime t1, double p, color c, uchar a)
  {
   int x, y;
   if(!XY(t1, p, x, y))
      return;
   int xr = g_w - 60;
   for(int xs = ClampX(x); xs < xr; xs += 9)
      g_cv.LineHorizontal(xs, MathMin(xs + 5, xr), y, ColorToARGB(c, a));
  }

//--- tanda CHoCH: garis dari swing ke bar break, label di tengah, titik di bar break
void Choch(const Row &r)
  {
   bool buy = (r.dir == "BUY");
   if(r.flag == 0)
     {
      DashRight(r.t1, r.p1, InpArmedColor, 230);
      int x, y;
      if(XY(r.t1, r.p1, x, y))
         g_cv.TextOut(g_w - 64, buy ? y - 14 : y + 2,
                      "level CHoCH M5 " + DoubleToString(r.p1, _Digits) +
                      (buy ? " · tunggu close di atas" : " · tunggu close di bawah"),
                      ColorToARGB(InpArmedColor, 255), TA_RIGHT);
      return;
     }
   color c = buy ? InpChochBuy : InpChochSell;
   int x1, y1, x2, y2;
   if(!XY(r.t1, r.p1, x1, y1) || !XY((datetime)r.p2, r.p1, x2, y2))
      return;
   if(x2 < 0 || x1 > g_w - 60)
      return;
   int xa = ClampX(x1), xb = MathMin(ClampX(x2), g_w - 60);
   g_cv.LineHorizontal(xa, xb, y1, ColorToARGB(c, 240));
   g_cv.LineHorizontal(xa, xb, y1 + (buy ? -1 : 1), ColorToARGB(c, 120));
   if(x2 >= 0 && x2 < g_w - 60)
      g_cv.FillCircle(x2, y1, 3, ColorToARGB(c, 255));
   g_cv.TextOut((xa + xb) / 2, buy ? y1 - 14 : y1 + 2, (buy ? "CHoCH ▲" : "CHoCH ▼"), ColorToARGB(c, 255), TA_CENTER);
  }

void HLine(datetime t1, double p, color c, const string txt)
  {
   int x, y;
   if(!XY(t1, p, x, y))
      return;
   x = ClampX(x);
   int xr = g_w - 60;
   g_cv.LineHorizontal(x, xr, y, ColorToARGB(c, 230));
   g_cv.TextOut(xr - 4, y - 13, txt, ColorToARGB(c, 255), TA_RIGHT);
  }

//--- Swing Donchian: channel per bin, tanda breakout pertama tiap rangkaian, level bin berjalan,
//    posisi swing (magic metode) + SL trailing, label status tren D1
string DonName(int q) { return("DON " + (g_dmtf[q] == 86400 ? "D1 " : "H4 ") + IntegerToString(g_dmn[q])); }

void DrawDon()
  {
   int nb = ArraySize(g_dt);
   if(nb == 0 || g_dm == 0)
      return;
   int prev = 0, pm = -1;
   for(int i = 0; i < nb; i++)
     {
      int q = g_dmi[i], tf = g_dmtf[q];
      if(q != pm)
         prev = 0;
      pm = q;
      color mc = g_dmc[q];
      if(g_dh[i] > 0)
        {
         Seg(g_dt[i], g_dt[i] + tf, g_dh[i], mc, 170);
         Seg(g_dt[i], g_dt[i] + tf, g_dl[i], mc, 170);
        }
      int s = g_ds[i], d = s > 0 ? 1 : s < 0 ? -1 : 0;
      if(d != 0 && d != prev)
        {
         int x, y;
         if(XY(g_dt[i] + tf, g_dc[i], x, y) && x >= 0 && x < g_w - 60)
           {
            bool buy = d > 0, ok = (s == d);
            color c = ok ? (buy ? InpBuyColor : InpSellColor) : InpOffColor;
            int dy = 32 * q;                           // metode kedua sedikit lebih jauh agar tidak menumpuk
            g_cv.TextOut(x, buy ? y + 4 + dy : y - 26 - dy, buy ? "▲" : "▼", ColorToARGB(c, 255), TA_CENTER);
            g_cv.TextOut(x + 8, buy ? y + 6 + dy : y - 24 - dy, DonName(q) + (buy ? " BUY" : " SELL") +
                         (ok ? "" : " (tren D1 ✗)"), ColorToARGB(c, 230));
           }
        }
      prev = d;
     }
   for(int q = 0; q < g_dm; q++)
     {
      if(g_dnh[q] <= 0)
         continue;
      DashRight(g_dnt[q], g_dnh[q], g_dmc[q], 230);
      DashRight(g_dnt[q], g_dnl[q], g_dmc[q], 230);
      int x, y;
      if(XY(g_dnt[q], g_dnh[q], x, y))
         g_cv.TextOut(g_w - 64, y - 14, DonName(q) + " high " + DoubleToString(g_dnh[q], _Digits) +
                      (g_dtr == 1 ? " · BUY bila close di atas" : " · tren D1 bukan BUY"),
                      ColorToARGB(g_dtr == 1 ? InpBuyColor : InpTextColor, 255), TA_RIGHT);
      if(XY(g_dnt[q], g_dnl[q], x, y))
         g_cv.TextOut(g_w - 64, y + 2, DonName(q) + " low " + DoubleToString(g_dnl[q], _Digits) +
                      (g_dtr == -1 ? " · SELL bila close di bawah" : " · tren D1 bukan SELL"),
                      ColorToARGB(g_dtr == -1 ? InpSellColor : InpTextColor, 255), TA_RIGHT);
     }
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(PositionGetTicket(i) == 0 || PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      long mg = PositionGetInteger(POSITION_MAGIC);
      int q = -1;
      for(int j = 0; j < g_dm; j++)
         if(g_dmmg[j] == mg)
            q = j;
      if(q < 0)
         continue;
      bool buy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
      datetime t = (datetime)PositionGetInteger(POSITION_TIME);
      double pr = PositionGetDouble(POSITION_PRICE_OPEN), sl = PositionGetDouble(POSITION_SL);
      HLine(t, pr, InpEntryColor, "SWING " + g_dmid[q] + (buy ? " BUY " : " SELL ") +
            DoubleToString(PositionGetDouble(POSITION_VOLUME), 2) + " @ " + DoubleToString(pr, _Digits));
      if(sl > 0)
         HLine(t, sl, InpDonSlColor, "SL " + g_dmid[q] + " " + g_dmex[q] + " " + DoubleToString(sl, _Digits));
     }
   int y0 = IsGold() ? 72 : 24;                        // XAU: di bawah label EMA50 & Trend MA Cross H1/H4
   string trs = g_dtr == 1 ? "BUY" : g_dtr == -1 ? "SELL" : "netral";
   string ids = "";
   for(int q = 0; q < g_dm; q++)
      ids += (q > 0 ? ", " : "") + g_dmid[q];
   color c = g_dtr == 1 ? InpBuyColor : g_dtr == -1 ? InpSellColor : InpEmaNeutral;
   g_cv.TextOut(8, y0, "Swing Donchian (" + ids + ") · tren D1 " + trs + " (EMA200 D1 " +
                DoubleToString(g_dema, _Digits) + ")", ColorToARGB(c, 255));
  }

//--- gambar ulang semua
void Render()
  {
   int w = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   int h = (int)ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   if(w <= 0 || h <= 0)
      return;
   if(w != g_w || h != g_h || ObjectFind(0, NAME) < 0)
     {
      g_cv.Destroy();
      if(!g_cv.CreateBitmapLabel(0, 0, NAME, 0, 0, w, h, COLOR_FORMAT_ARGB_NORMALIZE))
         return;
      ObjectSetInteger(0, NAME, OBJPROP_BACK, true);          // di belakang candle
      ObjectSetInteger(0, NAME, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, NAME, OBJPROP_HIDDEN, true);
      g_w = w;
      g_h = h;
     }
   g_cv.Erase(0x00000000);
   g_cv.FontSet("Segoe UI", -80);
   DrawMac();
   DrawEma();
   DrawDon();
   int n = ArraySize(g_rows);
   for(int i = 0; i < n; i++)
     {
      Row r = g_rows[i];
      bool buy = (r.dir == "BUY");
      if(r.rec == "POI")
        {
         if(r.flag == 0 && !InpShowOff)
            continue;
         color c = r.flag == 1 ? (buy ? InpBuyColor : InpSellColor) : InpOffColor;
         uchar fa = r.flag == 1 ? InpAlpha : (uchar)(InpAlpha / 2);
         Box(r.t1, r.p1, r.p2, c, fa, r.flag == 1 ? InpBorderAlpha : (uchar)(InpBorderAlpha / 2), 1);
         Label(r.t1, r.p2, r.kind + (buy ? " ▲" : " ▼"), r.flag == 1 ? c : InpTextColor, (uchar)(r.flag == 1 ? 255 : 160));
        }
      else if(r.rec == "ARMED")
        {
         Box(r.t1, r.p1, r.p2, InpArmedColor, 0, 255, 2);
         int x, y;
         if(XY(r.t1, r.p2, x, y))
            g_cv.TextOut(g_w - 64, y - 13, "ARMED " + r.dir + " · tunggu CHoCH M5", ColorToARGB(InpArmedColor, 255),
                         TA_RIGHT);
        }
      else if(r.rec == "CHOCH")
        {
         if(InpShowChoch)
            Choch(r);
        }
      else if(r.rec == "ORDER")
        {
         string what = r.kind == "pending" ? "LIMIT" : "POSISI";
         HLine(r.t1, r.p1, InpEntryColor, r.dir + " " + what + " " + DoubleToString(r.p1, _Digits));
         HLine(r.t1, r.p2, InpSLColor, "SL " + DoubleToString(r.p2, _Digits));
         HLine(r.t1, r.p3, InpTPColor, "TP " + DoubleToString(r.p3, _Digits) + " (1:3)");
        }
      else if(r.rec == "ORB")
        {
         // flag: 0 bentuk range · 1 tunggu breakout · 2 tanpa breakout · 3 breakout → order · 4 bias ✗
         datetime t_or = r.t1 + g_or_min * 60;
         datetime t_hold = r.t1 + InpOrbHoldMin * 60;
         Box2(r.t1, r.flag == 0 ? (datetime)r.p3 : t_or, r.p1, r.p2, InpOrbColor, InpAlpha,
              InpBorderAlpha);
         if(r.flag > 0)
           {
            uchar la = (uchar)(r.flag == 1 ? 220 : 120);
            Seg(t_or, r.flag == 1 ? (datetime)r.p3 : t_hold, r.p2, InpOrbColor, la);
            Seg(t_or, r.flag == 1 ? (datetime)r.p3 : t_hold, r.p1, InpOrbColor, la);
           }
         string st = r.flag == 0 ? "membentuk range" : r.flag == 1 ? "tunggu breakout" :
                     r.flag == 2 ? "tanpa breakout" : r.flag == 3 ? "breakout" : "breakout, bias tidak searah";
         Label(r.t1, r.p2, "ORB NY · " + st, InpOrbColor);
        }
      else if(r.rec == "ORBBRK")
        {
         int x, y;
         if(XY(r.t1, r.p1, x, y) && x >= 0 && x < g_w - 60)
           {
            color c = r.flag == 1 ? (buy ? InpBuyColor : InpSellColor) : InpOffColor;
            g_cv.TextOut(x, buy ? y + 4 : y - 26, buy ? "▲" : "▼", ColorToARGB(c, 255), TA_CENTER);
            g_cv.TextOut(x + 8, buy ? y + 6 : y - 24, "ORB " + r.dir + (r.flag == 1 ? "" : " (bias ✗)"),
                         ColorToARGB(c, 230));
           }
        }
      else if(r.rec == "ORBORD")
        {
         HLine(r.t1, r.p1, InpEntryColor, "ORB " + r.dir + " " + DoubleToString(r.p1, _Digits));
         HLine(r.t1, r.p2, InpSLColor, "ORB SL " + DoubleToString(r.p2, _Digits));
         HLine(r.t1, r.p3, InpTPColor, "ORB TP " + DoubleToString(r.p3, _Digits) + " (1:2)");
        }
     }
   g_cv.Update();
  }
//+------------------------------------------------------------------+
