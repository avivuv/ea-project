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
//| Canvas dipakai karena kotak bawaan MT5 tidak bisa transparan dan  |
//| area yang bertumpuk jadi putih (XOR).                             |
//| Hanya tampilan — tidak membuka order apa pun.                     |
//+------------------------------------------------------------------+
#property copyright   "ea-project"
#property version     "2.30"
#property description "Marker POI strategi sendiri (FVG/OB/IFVG M15, armed, CHoCH M5, entry/SL/TP) + area ORB New York"
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

#define NAME "PROPOI_canvas"

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
