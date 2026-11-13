//+------------------------------------------------------------------+
//| ProPOI.mq5 — marker POI strategi sendiri (tg_signal/pro_live.py) |
//| Membaca Common\Files\pro_poi.csv (ditulis pro_live tiap bar M5)  |
//| dan menggambar di canvas transparan (ARGB):                       |
//|   kotak POI M15 (FVG/OB/IFVG), POI "armed" (tunggu CHoCH M5),     |
//|   garis entry / SL / TP order.                                    |
//| Canvas dipakai karena kotak bawaan MT5 tidak bisa transparan dan  |
//| area yang bertumpuk jadi putih (XOR).                             |
//| Hanya tampilan — tidak membuka order apa pun.                     |
//+------------------------------------------------------------------+
#property copyright   "ea-project"
#property version     "2.00"
#property description "Marker POI strategi sendiri: kotak transparan FVG/OB/IFVG M15, POI armed, entry/SL/TP"
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
input color  InpEntryColor = C'30,120,255';
input color  InpSLColor    = C'230,60,60';
input color  InpTPColor    = C'20,170,60';
input color  InpTextColor  = C'110,110,110';

#define NAME "PROPOI_canvas"

struct Row { string rec, dir, kind; datetime t1; double p1, p2, p3; int flag; };
Row     g_rows[];
CCanvas g_cv;
int     g_w = 0, g_h = 0;

int OnInit()
  {
   EventSetTimer(5);
   ReadFile();
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
   ReadFile();
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

//--- baca file CSV (8 kolom per baris)
void ReadFile()
  {
   if(StringFind(_Symbol, "XAUUSD") < 0)
      return;
   int h = FileOpen(InpFile, FILE_READ | FILE_CSV | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE, ',');
   if(h == INVALID_HANDLE)
      return;
   ArrayResize(g_rows, 0);
   int k = 0;
   while(!FileIsEnding(h) && k < 500)
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
      if(r.rec == "POI" || r.rec == "ARMED" || r.rec == "ORDER")
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
   if(StringFind(_Symbol, "XAUUSD") < 0)
      return;
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
      else if(r.rec == "ORDER")
        {
         string what = r.kind == "pending" ? "LIMIT" : "POSISI";
         HLine(r.t1, r.p1, InpEntryColor, r.dir + " " + what + " " + DoubleToString(r.p1, _Digits));
         HLine(r.t1, r.p2, InpSLColor, "SL " + DoubleToString(r.p2, _Digits));
         HLine(r.t1, r.p3, InpTPColor, "TP " + DoubleToString(r.p3, _Digits) + " (1:3)");
        }
     }
   g_cv.Update();
  }
//+------------------------------------------------------------------+
