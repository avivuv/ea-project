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
//| Canvas dipakai karena kotak bawaan MT5 tidak bisa transparan dan  |
//| area yang bertumpuk jadi putih (XOR).                             |
//| Hanya tampilan — tidak membuka order apa pun.                     |
//+------------------------------------------------------------------+
#property copyright   "ea-project"
#property version     "2.50"
#property description "Marker POI strategi sendiri (FVG/OB/IFVG M15, armed, CHoCH M5, entry/SL/TP) + area ORB New York + EMA50 H1 bias + Trend MA Cross"
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
input ENUM_TIMEFRAMES InpMacTf = PERIOD_H1;    // TF Trend MA Cross: H1 (XAU_H1_MAC) atau H4 (XAU_H4_MAC)
input bool   InpMacSignal = true;              // tanda sinyal Trend MA Cross (MA5 cross 3 MA + EMA200 searah 10 bar)
input color  InpMacMa5    = C'255,215,0';
input color  InpMacMa13   = C'255,140,0';
input color  InpMacMa21   = C'0,180,220';
input color  InpMacMa34   = C'70,110,255';
input color  InpMacEma    = C'190,120,255';    // EMA200

#define NAME "PROPOI_canvas"
#define EMA_BARS 1000                               // bar H1 yang dihitung (EMA adjust=False konvergen jauh sebelum ini)

datetime g_et[];                                     // waktu buka bar H1 (sudah close), lama → baru
double   g_ev[];                                     // nilai EMA
int      g_eb[];                                     // bias bar itu: 1 BUY, -1 SELL, 0 netral
double   g_eslope = 0;                               // kemiringan EMA bar terakhir (× ATR)

#define MAC_BARS 1500
datetime g_bt[];                                     // waktu buka bar TF Trend MA Cross (sudah close), lama → baru
double   g_bh[], g_bl[];                             // high / low (posisi tanda sinyal)
double   g_bm[5][MAC_BARS];                         // SMA5, SMA13, SMA21, SMA34, EMA200 (0 = belum ada)
int      g_bs[];                                     // sinyal Trend MA Cross di bar itu: 1 BUY, -1 SELL, 0 tidak ada
int      g_bup = 0;                                  // posisi MA5 bar terakhir: 1 di atas 3 MA, -1 di bawah, 0 campur
int      g_bslope = 0;                               // EMA200 vs 10 bar lalu: 1 naik, -1 turun

struct Row { string rec, dir, kind; datetime t1; double p1, p2, p3; int flag; };
Row     g_rows[];
CCanvas g_cv;
int     g_or_min = 15;                              // panjang opening range (dari baris HDR file ORB)

bool IsGold() { return(StringFind(_Symbol, "XAUUSD") >= 0); }

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
  }

//--- Trend MA Cross, identik dengan mac_deep.indicators / live_signal (SMA close, EMA200 ewm adjust=False, slope 10 bar)
void CalcMac()
  {
   ArrayResize(g_bt, 0);
   if(!InpShowMac || !IsGold())
      return;
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = CopyRates(_Symbol, InpMacTf, 1, MAC_BARS, r);   // hanya bar yang sudah close
   if(n < 250)
      return;
   ArrayResize(g_bt, n);
   ArrayResize(g_bh, n);
   ArrayResize(g_bl, n);
   ArrayResize(g_bs, n);
   int per[4] = {5, 13, 21, 34};
   double a = 2.0 / 201.0;
   for(int i = 0; i < n; i++)
     {
      g_bt[i] = r[i].time;
      g_bh[i] = r[i].high;
      g_bl[i] = r[i].low;
      for(int m = 0; m < 4; m++)
        {
         g_bm[m][i] = 0;
         if(i >= per[m] - 1)
           {
            double s = 0;
            for(int j = i - per[m] + 1; j <= i; j++)
               s += r[j].close;
            g_bm[m][i] = s / per[m];
           }
        }
      g_bm[4][i] = i == 0 ? r[i].close : a * r[i].close + (1 - a) * g_bm[4][i - 1];
     }
   int prev = 0;
   for(int i = 0; i < n; i++)
     {
      int up = MacUp(i);
      g_bs[i] = 0;
      if(i > 210 && up != 0 && up != prev && up * (g_bm[4][i] - g_bm[4][i - 10]) > 0)
         g_bs[i] = up;
      prev = up;
     }
   g_bup = MacUp(n - 1);
   double d = g_bm[4][n - 1] - g_bm[4][n - 11];
   g_bslope = d > 0 ? 1 : d < 0 ? -1 : 0;
  }

//--- 1 bila MA5 di atas SMA13/21/34, -1 bila di bawah ketiganya, 0 campur / data belum cukup
int MacUp(int i)
  {
   if(g_bm[3][i] == 0)
      return(0);
   double a = g_bm[0][i];
   if(a > g_bm[1][i] && a > g_bm[2][i] && a > g_bm[3][i])
      return(1);
   if(a < g_bm[1][i] && a < g_bm[2][i] && a < g_bm[3][i])
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
   int n = ArraySize(g_bt);
   if(n < 2)
      return;
   color cl[5];
   cl[0] = InpMacMa5; cl[1] = InpMacMa13; cl[2] = InpMacMa21; cl[3] = InpMacMa34; cl[4] = InpMacEma;
   for(int m = 0; m < 5; m++)
     {
      int px = 0, py = 0;
      bool have = false;
      for(int i = 0; i < n; i++)
        {
         int x, y;
         if(g_bm[m][i] == 0 || !XY(g_bt[i], g_bm[m][i], x, y))
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
   if(InpMacSignal)
      for(int i = 0; i < n; i++)
        {
         if(g_bs[i] == 0)
            continue;
         bool buy = g_bs[i] == 1;
         int x, y;
         if(!XY(g_bt[i], buy ? g_bl[i] : g_bh[i], x, y) || x < 0 || x >= g_w - 60)
            continue;
         color c = buy ? InpBuyColor : InpSellColor;
         g_cv.TextOut(x, buy ? y + 4 : y - 26, buy ? "▲" : "▼", ColorToARGB(c, 255), TA_CENTER);
         g_cv.TextOut(x + 8, buy ? y + 6 : y - 24, buy ? "MA CROSS BUY" : "MA CROSS SELL", ColorToARGB(c, 230));
        }
   string tf = InpMacTf == PERIOD_H4 ? "H4" : InpMacTf == PERIOD_H1 ? "H1" : EnumToString(InpMacTf);
   string pos = g_bup == 1 ? "MA5 di atas 3 MA" : g_bup == -1 ? "MA5 di bawah 3 MA" : "MA5 campur";
   string sl = g_bslope == 1 ? "EMA200 naik" : g_bslope == -1 ? "EMA200 turun" : "EMA200 datar";
   color c = (g_bup != 0 && g_bup == g_bslope) ? (g_bup == 1 ? InpBuyColor : InpSellColor) : InpEmaNeutral;
   g_cv.TextOut(8, 40, "Trend MA Cross " + tf + " (SMA 5/13/21/34 · EMA200) · " + pos + " · " + sl, ColorToARGB(c, 255));
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
