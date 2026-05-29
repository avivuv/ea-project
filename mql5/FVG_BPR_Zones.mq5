//+------------------------------------------------------------------+
//|  FVG_BPR_Zones.mq5                                               |
//|  Indicator: visualisasi semua zona FVG + BPR di chart M15        |
//+------------------------------------------------------------------+
//
//  Cara pasang: kompilasi di MetaEditor, lalu drag ke chart M15.
//  Zona digambar ulang otomatis setiap candle baru terbentuk.
//
//  DUA jenis zona FVG ditampilkan, masing-masing sesuai strategi:
//
//  [FVG] — Standard Fair Value Gap  (sesuai StrategyFVG Python)
//    · Tanpa filter displacement C2
//    · Mitigated = price menyentuh TEPI zona (edge), sesuai backend
//    · Warna lebih pucat, label "FVG"
//
//  [FVG+] — Quality FVG for BPR     (sesuai StrategyBPR Python)
//    · C2 body >= InpDisplacement × range (displacement filter)
//    · Mitigated = price melewati MIDPOINT 50% zona
//    · Warna lebih kuat, label "FVG+"
//
//  [BPR] — Balanced Price Range
//    · Irisan FVG+ Bullish × FVG+ Bearish yang saling overlap
//    · Zona emas, label "BPR [BUY/SELL]"
//    · Setup entry paling high-confluence
//+------------------------------------------------------------------+
#property copyright "EA Trading Project"
#property description "FVG (Standard + Quality) & BPR Zone Visualizer"
#property indicator_chart_window
#property indicator_plots 0
#property strict

//── Inputs ───────────────────────────────────────────────────────────
input group  "=== Umum ==="
input int    InpLookback         = 80;               // Candle lookback scan
input int    InpATRPeriod        = 14;               // ATR period
input double InpMinGapATR        = 0.3;              // Min gap FVG (N × ATR)
input bool   InpFreshOnly        = true;             // Sembunyikan FVG mitigated
input bool   InpShowMidline      = true;             // Garis tengah zona (midpoint)
input bool   InpShowLabels       = true;             // Label teks
input int    InpExtendBars       = 50;               // Perpanjang zona ke kanan

input group  "=== Standard FVG (StrategyFVG) ==="
input bool   InpShowStdFVG       = true;             // Tampilkan Standard FVG
input color  InpStdBullColor     = C'160,210,255';   // Standard Bullish FVG
input color  InpStdBearColor     = C'255,165,150';   // Standard Bearish FVG

input group  "=== Quality FVG + BPR (StrategyBPR) ==="
input bool   InpShowQualFVG      = true;             // Tampilkan Quality FVG (BPR-grade)
input double InpDisplacement     = 0.5;              // Min body/range C2 (0 = off)
input bool   InpShowBPR          = true;             // Tampilkan zona BPR
input color  InpQualBullColor    = C'60,150,255';    // Quality Bullish FVG
input color  InpQualBearColor    = C'255,80,60';     // Quality Bearish FVG
input color  InpBPRColor         = C'255,200,30';    // BPR zona overlap

input group  "=== Mitigated ==="
input color  InpMitColor         = C'150,150,150';   // FVG sudah terisi

#define PREFIX "FVGBPR_"

//── Data structure ───────────────────────────────────────────────────
struct FVGZone
{
   int    bar_idx;   // series index c3 (0=current, 1=prev, ...)
   double top;
   double bottom;
   double mid;
   bool   bullish;
   bool   fresh;
};

FVGZone g_std_zones[];    // Standard FVG (StrategyFVG)
FVGZone g_qual_zones[];   // Quality FVG (StrategyBPR — dengan displacement filter)

int g_prev_bars  = 0;
int g_atr_handle = INVALID_HANDLE;

//+------------------------------------------------------------------+
int OnInit()
{
   g_atr_handle = iATR(_Symbol, PERIOD_CURRENT, InpATRPeriod);
   if(g_atr_handle == INVALID_HANDLE)
   {
      Print("[FVG_BPR] ERROR: gagal membuat ATR handle");
      return INIT_FAILED;
   }
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   DeleteAllObjects();
   if(g_atr_handle != INVALID_HANDLE)
      IndicatorRelease(g_atr_handle);
}

//+------------------------------------------------------------------+
int OnCalculate(
   const int      rates_total,
   const int      prev_calculated,
   const datetime &time[],
   const double   &open[],
   const double   &high[],
   const double   &low[],
   const double   &close[],
   const long     &tick_volume[],
   const long     &volume[],
   const int      &spread[]
)
{
   if(rates_total < InpLookback + 20) return rates_total;
   if(rates_total == g_prev_bars)     return rates_total;
   g_prev_bars = rates_total;

   double atr_buf[];
   ArraySetAsSeries(atr_buf, true);
   if(CopyBuffer(g_atr_handle, 0, 0, InpATRPeriod + 5, atr_buf) <= 0)
      return rates_total;

   double atr = atr_buf[1];
   if(atr <= 0 || atr == EMPTY_VALUE) return rates_total;

   double min_gap = InpMinGapATR * atr;

   DeleteAllObjects();
   ArrayFree(g_std_zones);
   ArrayFree(g_qual_zones);

   // ── Scan 1: Standard FVG (StrategyFVG) ───────────────────────────
   // Tanpa displacement filter, mitigasi di TEPI zona (edge)
   if(InpShowStdFVG)
      ScanFVG(min_gap, false, g_std_zones);

   // ── Scan 2: Quality FVG (StrategyBPR) ────────────────────────────
   // Dengan displacement filter, mitigasi di MIDPOINT 50%
   if(InpShowQualFVG || InpShowBPR)
      ScanFVG(min_gap, true, g_qual_zones);

   // ── Gambar: Standard FVG (lebih pucat, di belakang) ──────────────
   if(InpShowStdFVG)
      for(int i = 0; i < ArraySize(g_std_zones); i++)
         DrawFVGZone(g_std_zones[i], "STD", InpStdBullColor, InpStdBearColor, false);

   // ── Gambar: Quality FVG (lebih kuat, di depan STD) ───────────────
   if(InpShowQualFVG)
      for(int i = 0; i < ArraySize(g_qual_zones); i++)
         DrawFVGZone(g_qual_zones[i], "QUAL", InpQualBullColor, InpQualBearColor, true);

   // ── Deteksi dan gambar BPR dari zona Quality FVG ─────────────────
   if(InpShowBPR)
      DetectAndDrawBPR();

   ChartRedraw();
   return rates_total;
}

//+------------------------------------------------------------------+
//  Scan FVG ke dalam array target.
//  use_displacement = true  → filter C2 + mitigasi midpoint  (Quality / BPR)
//  use_displacement = false → no filter + mitigasi edge       (Standard)
//+------------------------------------------------------------------+
void ScanFVG(double min_gap, bool use_displacement, FVGZone &arr[])
{
   for(int i = 1; i <= InpLookback; i++)
   {
      int c1 = i + 2;
      int c2 = i + 1;
      int c3 = i;

      if(c1 >= Bars(_Symbol, PERIOD_CURRENT)) break;

      double c1_high = iHigh (_Symbol, PERIOD_CURRENT, c1);
      double c1_low  = iLow  (_Symbol, PERIOD_CURRENT, c1);
      double c2_high = iHigh (_Symbol, PERIOD_CURRENT, c2);
      double c2_low  = iLow  (_Symbol, PERIOD_CURRENT, c2);
      double c2_open = iOpen (_Symbol, PERIOD_CURRENT, c2);
      double c2_cls  = iClose(_Symbol, PERIOD_CURRENT, c2);
      double c3_high = iHigh (_Symbol, PERIOD_CURRENT, c3);
      double c3_low  = iLow  (_Symbol, PERIOD_CURRENT, c3);

      // ── Displacement filter (hanya untuk Quality scan) ────────────
      if(use_displacement && InpDisplacement > 0)
      {
         double rng = c2_high - c2_low;
         if(rng <= 0) continue;
         if(MathAbs(c2_cls - c2_open) / rng < InpDisplacement) continue;
      }

      // ── Tipe FVG ──────────────────────────────────────────────────
      double gap_top = 0, gap_bottom = 0;
      bool   bullish = false;

      if(c3_low > c1_high)
      {
         gap_bottom = c1_high;
         gap_top    = c3_low;
         bullish    = true;
      }
      else if(c3_high < c1_low)
      {
         gap_bottom = c3_high;
         gap_top    = c1_low;
         bullish    = false;
      }
      else continue;

      if(gap_top - gap_bottom < min_gap) continue;

      double mid = (gap_top + gap_bottom) / 2.0;

      // ── Mitigasi: edge (Standard) vs midpoint (Quality) ───────────
      bool mitigated = false;
      for(int k = 0; k < i; k++)
      {
         if(use_displacement)
         {
            // Quality: mitigated jika low/high melewati midpoint
            if(bullish  && iLow (_Symbol, PERIOD_CURRENT, k) <= mid) { mitigated = true; break; }
            if(!bullish && iHigh(_Symbol, PERIOD_CURRENT, k) >= mid) { mitigated = true; break; }
         }
         else
         {
            // Standard: mitigated jika low/high menyentuh tepi zona
            if(bullish  && iLow (_Symbol, PERIOD_CURRENT, k) <= gap_top)    { mitigated = true; break; }
            if(!bullish && iHigh(_Symbol, PERIOD_CURRENT, k) >= gap_bottom) { mitigated = true; break; }
         }
      }

      if(mitigated && InpFreshOnly) continue;

      int n = ArraySize(arr);
      ArrayResize(arr, n + 1);
      arr[n].bar_idx = i;
      arr[n].top     = gap_top;
      arr[n].bottom  = gap_bottom;
      arr[n].mid     = mid;
      arr[n].bullish = bullish;
      arr[n].fresh   = !mitigated;
   }
}

//+------------------------------------------------------------------+
//  Gambar satu zona FVG
//  type_tag = "STD" atau "QUAL" (dipakai untuk prefix nama objek + label)
//  is_quality = true → label "FVG+", false → label "FVG"
//+------------------------------------------------------------------+
void DrawFVGZone(
   const FVGZone &z,
   string         type_tag,
   color          bull_col,
   color          bear_col,
   bool           is_quality
)
{
   datetime t_left  = iTime(_Symbol, PERIOD_CURRENT, z.bar_idx + 2);
   datetime t_right = iTime(_Symbol, PERIOD_CURRENT, MathMax(0, z.bar_idx - InpExtendBars));
   color    col     = z.fresh ? (z.bullish ? bull_col : bear_col) : InpMitColor;
   string   pfx     = PREFIX + type_tag + "_" + (z.bullish ? "B_" : "S_") + (string)z.bar_idx;

   // Rectangle
   string rname = pfx + "_R";
   if(ObjectCreate(0, rname, OBJ_RECTANGLE, 0, t_left, z.top, t_right, z.bottom))
   {
      ObjectSetInteger(0, rname, OBJPROP_COLOR,      col);
      ObjectSetInteger(0, rname, OBJPROP_FILL,       true);
      ObjectSetInteger(0, rname, OBJPROP_BACK,       true);
      ObjectSetInteger(0, rname, OBJPROP_WIDTH,      is_quality ? 1 : 1);
      ObjectSetInteger(0, rname, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, rname, OBJPROP_HIDDEN,     false);
   }

   // Midline
   if(InpShowMidline)
   {
      string mname = pfx + "_M";
      if(ObjectCreate(0, mname, OBJ_TREND, 0, t_left, z.mid, t_right, z.mid))
      {
         ObjectSetInteger(0, mname, OBJPROP_COLOR,      col);
         ObjectSetInteger(0, mname, OBJPROP_STYLE,      STYLE_DOT);
         ObjectSetInteger(0, mname, OBJPROP_WIDTH,      1);
         ObjectSetInteger(0, mname, OBJPROP_RAY_RIGHT,  false);
         ObjectSetInteger(0, mname, OBJPROP_BACK,       true);
         ObjectSetInteger(0, mname, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, mname, OBJPROP_HIDDEN,     false);
      }
   }

   // Label
   if(InpShowLabels)
   {
      string lname = pfx + "_T";
      string ltext = (z.bullish ? "B" : "S") + (string)(is_quality ? "FVG+" : "FVG");
      if(!z.fresh) ltext += "(mit)";

      if(ObjectCreate(0, lname, OBJ_TEXT, 0, t_right, z.mid))
      {
         ObjectSetString (0, lname, OBJPROP_TEXT,       ltext);
         ObjectSetInteger(0, lname, OBJPROP_COLOR,      col);
         ObjectSetInteger(0, lname, OBJPROP_FONTSIZE,   7);
         ObjectSetInteger(0, lname, OBJPROP_ANCHOR,     ANCHOR_RIGHT_LOWER);
         ObjectSetInteger(0, lname, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, lname, OBJPROP_HIDDEN,     false);
         ObjectSetInteger(0, lname, OBJPROP_BACK,       true);
      }
   }
}

//+------------------------------------------------------------------+
//  Deteksi BPR dari pasangan Quality FVG yang overlap
//+------------------------------------------------------------------+
void DetectAndDrawBPR()
{
   int n = ArraySize(g_qual_zones);

   for(int i = 0; i < n; i++)
   {
      if(!g_qual_zones[i].bullish || !g_qual_zones[i].fresh) continue;

      for(int j = 0; j < n; j++)
      {
         if(g_qual_zones[j].bullish || !g_qual_zones[j].fresh) continue;

         FVGZone bull = g_qual_zones[i];
         FVGZone bear = g_qual_zones[j];

         double ov_top    = MathMin(bull.top,    bear.top);
         double ov_bottom = MathMax(bull.bottom, bear.bottom);

         if(ov_top <= ov_bottom) continue;

         double ov_mid     = (ov_top + ov_bottom) / 2.0;
         bool   bpr_bull   = (bull.bar_idx <= bear.bar_idx);
         int    newer_bar  = MathMin(bull.bar_idx, bear.bar_idx);
         int    older_bar  = MathMax(bull.bar_idx, bear.bar_idx);

         // Freshness BPR: midpoint belum tersentuh sejak FVG baru terbentuk
         bool bpr_fresh = true;
         for(int k = 0; k < newer_bar; k++)
         {
            if( bpr_bull && iLow (_Symbol, PERIOD_CURRENT, k) <= ov_mid) { bpr_fresh = false; break; }
            if(!bpr_bull && iHigh(_Symbol, PERIOD_CURRENT, k) >= ov_mid) { bpr_fresh = false; break; }
         }
         if(!bpr_fresh) continue;

         DrawBPRZone(i, j, ov_top, ov_bottom, ov_mid, bpr_bull, newer_bar, older_bar);
      }
   }
}

//+------------------------------------------------------------------+
void DrawBPRZone(
   int    bull_i, int bear_j,
   double top,    double bottom, double mid,
   bool   bullish,
   int    newer_bar, int older_bar
)
{
   string pfx     = PREFIX + "BPR_" + (string)bull_i + "_" + (string)bear_j;
   datetime t_left  = iTime(_Symbol, PERIOD_CURRENT, older_bar + 2);
   datetime t_right = iTime(_Symbol, PERIOD_CURRENT, MathMax(0, newer_bar - InpExtendBars));

   string rname = pfx + "_R";
   if(ObjectCreate(0, rname, OBJ_RECTANGLE, 0, t_left, top, t_right, bottom))
   {
      ObjectSetInteger(0, rname, OBJPROP_COLOR,      InpBPRColor);
      ObjectSetInteger(0, rname, OBJPROP_FILL,       true);
      ObjectSetInteger(0, rname, OBJPROP_BACK,       true);
      ObjectSetInteger(0, rname, OBJPROP_WIDTH,      2);
      ObjectSetInteger(0, rname, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, rname, OBJPROP_HIDDEN,     false);
   }

   if(InpShowMidline)
   {
      string mname = pfx + "_M";
      if(ObjectCreate(0, mname, OBJ_TREND, 0, t_left, mid, t_right, mid))
      {
         ObjectSetInteger(0, mname, OBJPROP_COLOR,      InpBPRColor);
         ObjectSetInteger(0, mname, OBJPROP_STYLE,      STYLE_DASH);
         ObjectSetInteger(0, mname, OBJPROP_WIDTH,      1);
         ObjectSetInteger(0, mname, OBJPROP_RAY_RIGHT,  false);
         ObjectSetInteger(0, mname, OBJPROP_BACK,       true);
         ObjectSetInteger(0, mname, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, mname, OBJPROP_HIDDEN,     false);
      }
   }

   if(InpShowLabels)
   {
      string lname = pfx + "_T";
      string ltext = "BPR [" + (bullish ? "BUY" : "SELL") + "]";

      if(ObjectCreate(0, lname, OBJ_TEXT, 0, t_right, mid))
      {
         ObjectSetString (0, lname, OBJPROP_TEXT,       ltext);
         ObjectSetInteger(0, lname, OBJPROP_COLOR,      InpBPRColor);
         ObjectSetInteger(0, lname, OBJPROP_FONTSIZE,   8);
         ObjectSetString (0, lname, OBJPROP_FONT,       "Arial Bold");
         ObjectSetInteger(0, lname, OBJPROP_ANCHOR,     ANCHOR_RIGHT_LOWER);
         ObjectSetInteger(0, lname, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, lname, OBJPROP_HIDDEN,     false);
         ObjectSetInteger(0, lname, OBJPROP_BACK,       true);
      }
   }
}

//+------------------------------------------------------------------+
void DeleteAllObjects()
{
   for(int i = ObjectsTotal(0, 0, -1) - 1; i >= 0; i--)
   {
      string name = ObjectName(0, i, 0, -1);
      if(StringFind(name, PREFIX) == 0)
         ObjectDelete(0, name);
   }
}
//+------------------------------------------------------------------+
