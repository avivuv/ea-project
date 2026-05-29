//+------------------------------------------------------------------+
//|  OB_Zones.mq5                                                    |
//|  Indicator: visualisasi Order Block (OB) dari H4 dan M15        |
//|  Sesuai dengan logika StrategyOBConfirm di Python backend        |
//+------------------------------------------------------------------+
//
//  Cara pasang: kompilasi di MetaEditor, drag ke chart M15.
//  Pasang bersama FVG_BPR_Zones.mq5 untuk melihat semua zona aktif.
//
//  Warna default:
//    Hijau solid   = H4 Bullish OB (demand zone — utama)
//    Merah solid   = H4 Bearish OB (supply zone — utama)
//    Hijau tipis   = M15 Bullish OB (entry zone)
//    Merah tipis   = M15 Bearish OB (entry zone)
//    Abu-abu zig   = OB "touched" (wick sudah masuk zona, belum mitigated)
//
//  Definisi OB (sesuai backend Python, SMC standar):
//    BUY  OB = candle BEARISH terakhir sebelum impulse bullish kuat
//    SELL OB = candle BULLISH terakhir sebelum impulse bearish kuat
//    Zona OB = HIGH ke LOW candle OB (full range, SMC standar)
//             → fallback ke BODY (open–close) jika body < InpWickThreshold × range
//               (candle ekor panjang / pin bar — jaga RR tetap efisien)
//    Mitigated  = close subsequent melewati batas BODY OB (level kritis)
//    Touched    = price menembus ke ≥50% zona (bukan sekadar menyentuh wick)
//+------------------------------------------------------------------+
#property copyright "EA Trading Project"
#property description "Order Block (OB) Zones — H4 & M15"
#property indicator_chart_window
#property indicator_plots 0
#property strict

//── Inputs ────────────────────────────────────────────────────────────
input bool   InpShowH4OB        = true;             // Tampilkan H4 Order Block
input bool   InpShowM15OB       = true;             // Tampilkan M15 Order Block
input int    InpH4Lookback      = 30;               // H4 candle lookback
input int    InpM15Lookback     = 80;               // M15 candle lookback
input int    InpATRPeriod       = 14;               // ATR period
input double InpImpulseATR      = 1.5;              // Min impulse after OB (N × ATR)
input double InpWickThreshold   = 0.35;             // Body/range min → pakai High-Low; di bawahnya → body saja
input bool   InpFreshOnly       = true;             // Sembunyikan OB mitigated
input bool   InpShowTouched     = true;             // Tampilkan OB yang sudah ditest >50% zona
input bool   InpShowLabels      = true;             // Label teks
input bool   InpShowOBMidline   = true;             // Garis tengah OB (midpoint entry)
input int    InpExtendBars      = 50;               // Perpanjang zona ke kanan
input color  InpH4BuyColor      = C'50,180,100';    // H4 Bullish OB — demand kuat
input color  InpH4SellColor     = C'200,60,60';     // H4 Bearish OB — supply kuat
input color  InpM15BuyColor     = C'150,230,170';   // M15 Bullish OB — entry level
input color  InpM15SellColor    = C'240,150,140';   // M15 Bearish OB — entry level
input color  InpTouchedColor    = C'160,160,160';   // OB touched (dilemahkan)

#define PREFIX "OBZONE_"

//── Data structures ──────────────────────────────────────────────────
struct OBZone
{
   int    bar_idx;   // series index OB candle (0=current)
   double top;       // zona top  (High jika body normal, Close/Open jika wick panjang)
   double bottom;    // zona bottom (Low jika body normal, Open/Close jika wick panjang)
   double mid;       // midpoint zona (50% — level entry ideal)
   bool   bullish;   // true = BUY OB, false = SELL OB
   bool   fresh;     // belum dilewati close subsequent melewati body OB
   bool   touched;   // price sudah menembus ke >50% zona (masih fresh, belum mitigated)
   bool   is_h4;     // true = H4 OB, false = M15 OB
};

OBZone g_obs[];
int    g_prev_bars   = 0;
int    g_h4_atr      = INVALID_HANDLE;
int    g_m15_atr     = INVALID_HANDLE;

//+------------------------------------------------------------------+
int OnInit()
{
   g_h4_atr  = iATR(_Symbol, PERIOD_H4,           InpATRPeriod);
   g_m15_atr = iATR(_Symbol, PERIOD_CURRENT,      InpATRPeriod);

   if(g_h4_atr == INVALID_HANDLE || g_m15_atr == INVALID_HANDLE)
   {
      Print("[OB_Zones] ERROR: gagal membuat ATR handle");
      return INIT_FAILED;
   }
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   DeleteAllObjects();
   if(g_h4_atr  != INVALID_HANDLE) IndicatorRelease(g_h4_atr);
   if(g_m15_atr != INVALID_HANDLE) IndicatorRelease(g_m15_atr);
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
   if(rates_total < InpM15Lookback + 20) return rates_total;
   if(rates_total == g_prev_bars)        return rates_total;
   g_prev_bars = rates_total;

   // ── Ambil ATR H4 ──────────────────────────────────────────────────
   double h4_atr_buf[];
   ArraySetAsSeries(h4_atr_buf, true);
   if(CopyBuffer(g_h4_atr, 0, 0, InpATRPeriod + 5, h4_atr_buf) <= 0)
      return rates_total;
   double h4_atr = h4_atr_buf[1];

   // ── Ambil ATR M15 ──────────────────────────────────────────────────
   double m15_atr_buf[];
   ArraySetAsSeries(m15_atr_buf, true);
   if(CopyBuffer(g_m15_atr, 0, 0, InpATRPeriod + 5, m15_atr_buf) <= 0)
      return rates_total;
   double m15_atr = m15_atr_buf[1];

   if(h4_atr <= 0 || m15_atr <= 0) return rates_total;

   DeleteAllObjects();
   ArrayFree(g_obs);

   // ── Scan H4 OB ────────────────────────────────────────────────────
   if(InpShowH4OB)
      ScanOB(PERIOD_H4, InpH4Lookback, h4_atr, true);

   // ── Scan M15 OB ───────────────────────────────────────────────────
   if(InpShowM15OB)
      ScanOB(PERIOD_CURRENT, InpM15Lookback, m15_atr, false);

   // ── Gambar semua OB ───────────────────────────────────────────────
   int n = ArraySize(g_obs);
   for(int i = 0; i < n; i++)
      DrawOBZone(g_obs[i]);

   ChartRedraw();
   return rates_total;
}

//+------------------------------------------------------------------+
//  Scan satu timeframe untuk OB pattern
//  OB = candle C (bearish/bullish) diikuti impulse N × ATR
//+------------------------------------------------------------------+
void ScanOB(ENUM_TIMEFRAMES tf, int lookback, double atr, bool is_h4)
{
   // bars_in_tf: jumlah bar yang tersedia di timeframe ini
   int bars_in_tf = Bars(_Symbol, tf);
   if(bars_in_tf < lookback + 5) return;

   double impulse_min = InpImpulseATR * atr;

   // Scan: series index i=1 (prev confirmed) hingga lookback
   // c = candle OB (di index i+1), impulse = candle setelahnya (index i, i-1)
   for(int i = 1; i <= lookback; i++)
   {
      int c_idx   = i + 1;   // OB candle
      int nxt1    = i;       // candle impulse pertama
      int nxt2    = i - 1;   // candle impulse kedua (optional)

      if(c_idx >= bars_in_tf) break;

      double c_open  = iOpen (_Symbol, tf, c_idx);
      double c_close = iClose(_Symbol, tf, c_idx);
      double c_high  = iHigh (_Symbol, tf, c_idx);
      double c_low   = iLow  (_Symbol, tf, c_idx);

      double n1_open  = iOpen (_Symbol, tf, nxt1);
      double n1_close = iClose(_Symbol, tf, nxt1);
      double n1_high  = iHigh (_Symbol, tf, nxt1);
      double n1_low   = iLow  (_Symbol, tf, nxt1);

      bool   c_is_bearish = c_close < c_open;
      bool   c_is_bullish = c_close > c_open;
      double c_body       = MathAbs(c_close - c_open);
      if(c_body <= 0) continue;

      // ── Tentukan zona OB: High-Low atau Body sesuai threshold ──────
      double body_top    = MathMax(c_open, c_close);
      double body_bottom = MathMin(c_open, c_close);
      double c_range     = c_high - c_low;
      double body_ratio  = (c_range > 0) ? c_body / c_range : 0.0;

      double ob_top, ob_bottom;
      if(body_ratio >= InpWickThreshold)
      {
         ob_top    = c_high;    // SMC standar: full High ke Low
         ob_bottom = c_low;
      }
      else
      {
         ob_top    = body_top;  // wick terlalu panjang → pakai body saja
         ob_bottom = body_bottom;
      }
      double ob_mid = (ob_top + ob_bottom) / 2.0;

      bool is_buy_ob  = false;
      bool is_sell_ob = false;

      // ── BUY OB: candle bearish diikuti bullish impulse ─────────────
      if(c_is_bearish)
      {
         double move = n1_close - n1_open;   // bullish body impulse
         if(nxt2 >= 0 && nxt2 < bars_in_tf)
         {
            double n2_high = iHigh(_Symbol, tf, nxt2);
            move = MathMax(move, n2_high - c_low);
         }
         if(move >= impulse_min) is_buy_ob = true;
      }

      // ── SELL OB: candle bullish diikuti bearish impulse ────────────
      else if(c_is_bullish)
      {
         double move = n1_open - n1_close;   // bearish body impulse
         if(nxt2 >= 0 && nxt2 < bars_in_tf)
         {
            double n2_low = iLow(_Symbol, tf, nxt2);
            move = MathMax(move, c_high - n2_low);
         }
         if(move >= impulse_min) is_sell_ob = true;
      }

      if(!is_buy_ob && !is_sell_ob) continue;

      // ── Freshness + Touched check ──────────────────────────────────
      // Cek candle subsequent: bar k = i-1 down to 0 (candle setelah OB terbentuk)
      bool fresh   = true;
      bool touched = false;

      for(int k = 0; k < i; k++)
      {
         double k_close = iClose(_Symbol, tf, k);
         double k_high  = iHigh (_Symbol, tf, k);
         double k_low   = iLow  (_Symbol, tf, k);

         if(is_buy_ob)
         {
            // Mitigated: close di bawah body_bottom (level kritis, bukan wick)
            if(k_close < body_bottom) { fresh = false; break; }
            // Touched: price menembus ke ≥50% zona (bukan sekadar menyentuh wick)
            if(!touched && k_low <= ob_mid) touched = true;
         }
         else
         {
            // Mitigated: close di atas body_top (level kritis, bukan wick)
            if(k_close > body_top)    { fresh = false; break; }
            // Touched: price menembus ke ≥50% zona
            if(!touched && k_high >= ob_mid) touched = true;
         }
      }

      // Filter sesuai setting
      if(!fresh && InpFreshOnly) continue;
      if(touched && !InpShowTouched && fresh) continue;

      // Append ke array
      int n_arr = ArraySize(g_obs);
      ArrayResize(g_obs, n_arr + 1);
      g_obs[n_arr].bar_idx = c_idx;
      g_obs[n_arr].top     = ob_top;
      g_obs[n_arr].bottom  = ob_bottom;
      g_obs[n_arr].mid     = ob_mid;
      g_obs[n_arr].bullish = is_buy_ob;
      g_obs[n_arr].fresh   = fresh;
      g_obs[n_arr].touched = touched;
      g_obs[n_arr].is_h4   = is_h4;
   }
}

//+------------------------------------------------------------------+
//  Gambar satu zona OB (rectangle + midline + label)
//+------------------------------------------------------------------+
void DrawOBZone(const OBZone &ob)
{
   ENUM_TIMEFRAMES tf = ob.is_h4 ? PERIOD_H4 : PERIOD_CURRENT;

   datetime t_left  = iTime(_Symbol, tf, ob.bar_idx);
   datetime t_right = iTime(_Symbol, PERIOD_CURRENT, MathMax(0, 0 - InpExtendBars));

   // Pilih warna sesuai jenis dan kondisi
   color col;
   if(!ob.fresh)
      col = InpTouchedColor;
   else if(ob.touched)
      col = InpTouchedColor;
   else if(ob.is_h4)
      col = ob.bullish ? InpH4BuyColor : InpH4SellColor;
   else
      col = ob.bullish ? InpM15BuyColor : InpM15SellColor;

   // Lebar border: H4 lebih tebal dari M15
   int line_width = ob.is_h4 ? 2 : 1;

   string tf_tag = ob.is_h4 ? "H4" : "M15";
   string pfx    = PREFIX + tf_tag + "_" + (ob.bullish ? "B_" : "S_") + (string)ob.bar_idx;

   // Rectangle body OB
   string rname = pfx + "_R";
   if(ObjectCreate(0, rname, OBJ_RECTANGLE, 0, t_left, ob.top, t_right, ob.bottom))
   {
      ObjectSetInteger(0, rname, OBJPROP_COLOR,      col);
      ObjectSetInteger(0, rname, OBJPROP_FILL,       !ob.touched);  // touched = outline only
      ObjectSetInteger(0, rname, OBJPROP_BACK,       true);
      ObjectSetInteger(0, rname, OBJPROP_WIDTH,      line_width);
      ObjectSetInteger(0, rname, OBJPROP_STYLE,      ob.touched ? STYLE_DASH : STYLE_SOLID);
      ObjectSetInteger(0, rname, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, rname, OBJPROP_HIDDEN,     false);
   }

   // Midline OB (titik entry ideal — 50% zona High-Low atau body)
   if(InpShowOBMidline && ob.fresh)
   {
      string mname = pfx + "_M";
      if(ObjectCreate(0, mname, OBJ_TREND, 0, t_left, ob.mid, t_right, ob.mid))
      {
         ObjectSetInteger(0, mname, OBJPROP_COLOR,     col);
         ObjectSetInteger(0, mname, OBJPROP_STYLE,     STYLE_DOT);
         ObjectSetInteger(0, mname, OBJPROP_WIDTH,     1);
         ObjectSetInteger(0, mname, OBJPROP_RAY_RIGHT, false);
         ObjectSetInteger(0, mname, OBJPROP_BACK,      true);
         ObjectSetInteger(0, mname, OBJPROP_SELECTABLE,false);
         ObjectSetInteger(0, mname, OBJPROP_HIDDEN,    false);
      }
   }

   // Label
   if(InpShowLabels)
   {
      string lname  = pfx + "_T";
      string dir    = ob.bullish ? "BUY" : "SELL";
      string status = !ob.fresh ? "(mit)" : ob.touched ? "(touched)" : "";
      string ltext  = tf_tag + " OB " + dir + " " + status;

      if(ObjectCreate(0, lname, OBJ_TEXT, 0, t_right, ob.mid))
      {
         ObjectSetString (0, lname, OBJPROP_TEXT,       ltext);
         ObjectSetInteger(0, lname, OBJPROP_COLOR,      col);
         ObjectSetInteger(0, lname, OBJPROP_FONTSIZE,   ob.is_h4 ? 8 : 7);
         ObjectSetString (0, lname, OBJPROP_FONT,       ob.is_h4 ? "Arial Bold" : "Arial");
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
