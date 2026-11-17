//+------------------------------------------------------------------+
//|                                              TG_Signal_Layer.mq4 |
//|  Eksekusi sinyal grup Telegram (dibaca oleh tg_signal_reader.py) |
//|  - Sinyal zona  "BUY 71-67"  -> 3 layer (ZERO / MID / LAST)       |
//|  - Sinyal "Buy Now" diabaikan (default), karena hanya pengumuman  |
//|  - SL per entry, BEP + SL naik bertahap, TP maksimal 30 pips     |
//+------------------------------------------------------------------+
#property copyright "TG Signal Layer"
#property version   "1.11"
#property strict

//--- File & simbol
input string SignalFile          = "tg_signals.txt"; // Nama file sinyal (folder Common\Files)
input string TradeSymbol         = "";      // Kosong = simbol chart (XAUUSD / XAUUSDm)
input double PipSize             = 0.10;    // XAUUSD: 1 pip = 0.10 harga
input int    MagicNumber         = 770301;  // Beda dari EA lain

//--- Jenis sinyal
input bool   IgnoreNowSignals    = true;    // Abaikan "Buy/Sell Now" (zona menyusul ~24 detik)

//--- Lot & SL/TP
input double LayerLot            = 0.01;    // Lot per layer (3 layer = 0.03)
input string UseLayers           = "ZML";   // Layer dipakai: Z=ZERO M=MID L=LAST (mis. "Z" = 1 layer)
input double MarketLot           = 0.03;    // Lot sinyal Buy/Sell Now
input double DefaultSLPips       = 30;      // Jarak SL (pips)
input bool   SLFromZoneEnd       = true;    // true = SL semua layer dihitung dari ujung zona (LAST)
input bool   UseSignalSL         = true;    // Pakai SL dari pesan jika ada
input double MaxTPPips           = 30;      // TP maksimal

//--- BEP & trailing
input double BEStartPips         = 10;      // Profit +10 -> SL ke BEP
input double BEOffsetPips        = 5;       // Saat +10: SL dikunci di +5 (0 = persis BEP)
input double TrailStartPips      = 15;      // Profit +15 -> SL dikunci di +10
input double TrailLockPips       = 10;      // Kunci pertama
input double TrailStepPips       = 5;       // Setiap naik 5, SL ikut naik 5

//--- Filter keamanan
input int    PendingExpiryMin    = 60;      // Pending tidak tersentuh dihapus (menit)
input int    MaxSignalAgeSec     = 90;      // Sinyal lebih tua dari ini diabaikan
input double MaxSpreadPips       = 5;       // Batas spread untuk entry market
input double ZoneTolerancePips   = 5;       // Harga boleh lewat ujung zona sejauh ini
input double MaxZoneWidthPips    = 100;     // Zona lebih lebar dari ini = dianggap salah baca
input double MaxZoneDistancePips = 200;     // Zona terlalu jauh dari harga = diabaikan
input int    MaxActiveSignals    = 3;       // Maks sinyal yang punya posisi aktif
input int    SlippagePoints      = 30;
input bool   PushNotification    = false;   // Kirim notifikasi ke HP (MetaQuotes ID)

string gSym;
string gVarName;
double gLastId = 0;
int    gDigits;
double gPoint;

//+------------------------------------------------------------------+
int OnInit()
{
   gSym = (TradeSymbol == "") ? Symbol() : TradeSymbol;
   if(!SymbolSelect(gSym, true))
   {
      Print("Simbol tidak ditemukan: ", gSym);
      return(INIT_FAILED);
   }
   gDigits  = (int)MarketInfo(gSym, MODE_DIGITS);
   gPoint   = MarketInfo(gSym, MODE_POINT);
   gVarName = "TGSL_LastId_" + IntegerToString(MagicNumber);

   if(GlobalVariableCheck(gVarName))
      gLastId = GlobalVariableGet(gVarName);
   else
   {
      ReadSignals(true);   // pertama kali: sinyal lama di file tidak dieksekusi
      GlobalVariableSet(gVarName, gLastId);
   }

   EventSetTimer(1);
   Print("TG Signal Layer aktif di ", gSym, " | sinyal terakhir id ", DoubleToString(gLastId, 0));
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason) { EventKillTimer(); }
void OnTimer()                  { ReadSignals(false); ManageOrders(); }
void OnTick()                   { ManageOrders(); }

//+------------------------------------------------------------------+
void Log(string s, bool push = false)
{
   Print(s);
   if(push && PushNotification) SendNotification("TG EA: " + s);
}

double NormLot(double lot)
{
   double mn = MarketInfo(gSym, MODE_MINLOT);
   double mx = MarketInfo(gSym, MODE_MAXLOT);
   double st = MarketInfo(gSym, MODE_LOTSTEP);
   if(st <= 0) st = 0.01;
   lot = MathFloor(lot / st + 0.5) * st;
   return(NormalizeDouble(MathMax(mn, MathMin(mx, lot)), 2));
}

// Lengkapi "71" menjadi harga penuh terdekat dari harga sekarang (mis. 4071)
double FullPrice(double v, double ref)
{
   if(v >= 100) return(v);
   double base = MathFloor(ref / 100.0) * 100.0;
   double best = base + v;
   double c1 = best - 100, c2 = best + 100;
   if(MathAbs(c1 - ref) < MathAbs(best - ref)) best = c1;
   if(MathAbs(c2 - ref) < MathAbs(best - ref)) best = c2;
   return(best);
}

//+------------------------------------------------------------------+
//| Baca file sinyal: id;unix_time;TYPE;SIDE;a;b;sl;END              |
//+------------------------------------------------------------------+
void ReadSignals(bool initOnly)
{
   int h = FileOpen(SignalFile, FILE_READ | FILE_TXT | FILE_ANSI |
                    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_COMMON);
   if(h == INVALID_HANDLE) return;

   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      if(StringLen(line) < 10) continue;
      string p[];
      if(StringSplit(line, ';', p) < 8) continue;
      if(StringFind(p[7], "END") != 0) continue;   // baris belum lengkap

      double id = StringToDouble(p[0]);
      if(id <= gLastId) continue;
      gLastId = id;
      if(initOnly) continue;

      GlobalVariableSet(gVarName, gLastId);
      ProcessSignal(id, (datetime)StringToInteger(p[1]), p[2], p[3],
                    StringToDouble(p[4]), StringToDouble(p[5]), StringToDouble(p[6]));
   }
   FileClose(h);
}

//+------------------------------------------------------------------+
void ProcessSignal(double id, datetime ts, string type, string side,
                   double a, double b, double slSignal)
{
   string tag = "TG" + DoubleToString(id, 0);
   bool isBuy = (side == "BUY");
   if(!isBuy && side != "SELL") return;

   int age = (int)(TimeGMT() - ts);
   if(age > MaxSignalAgeSec)
   { Log(tag + " diabaikan: sinyal sudah " + IntegerToString(age) + " detik"); return; }

   if(CountActiveSignals() >= MaxActiveSignals)
   { Log(tag + " diabaikan: sudah " + IntegerToString(MaxActiveSignals) + " sinyal aktif"); return; }

   double slPips = (UseSignalSL && slSignal > 0) ? slSignal : DefaultSLPips;

   //--- Buy/Sell Now
   if(type == "NOW" && IgnoreNowSignals)
   { Log(tag + " " + side + " NOW diabaikan (menunggu sinyal zona)"); return; }
   if(type == "NOW")
   {
      Log(tag + " " + side + " NOW", true);
      OpenMarket(isBuy, NormLot(MarketLot), slPips, 0, tag + "-N");
      return;
   }
   if(type != "ZONE") return;

   //--- Zona -> 3 layer
   RefreshRates();
   double ref  = isBuy ? MarketInfo(gSym, MODE_ASK) : MarketInfo(gSym, MODE_BID);
   double zero = FullPrice(a, ref);
   double last;
   if(b >= 100) last = b;
   else
   {
      double d = isBuy ? (a - b) : (b - a);
      if(d < 0) d += 100;
      last = isBuy ? zero - d : zero + d;
   }

   double width = MathAbs(zero - last) / PipSize;
   if(width <= 0 || width > MaxZoneWidthPips)
   { Log(tag + " diabaikan: lebar zona " + DoubleToString(width, 0) + " pips tidak wajar"); return; }
   if(MathAbs(ref - zero) / PipSize > MaxZoneDistancePips)
   { Log(tag + " diabaikan: zona " + DoubleToString(zero, gDigits) + " terlalu jauh dari harga"); return; }

   double tol = ZoneTolerancePips * PipSize;
   if((isBuy && ref < last - tol) || (!isBuy && ref > last + tol))
   { Log(tag + " diabaikan: harga sudah menembus zona"); return; }

   double lv[3];
   lv[0] = zero;
   lv[1] = (zero + last) / 2.0;
   lv[2] = last;
   string nm[3] = {"Z", "M", "L"};

   Log(tag + " " + side + " zona " + DoubleToString(zero, gDigits) + " - " +
       DoubleToString(last, gDigits), true);
   double slZone = 0;
   if(SLFromZoneEnd)
      slZone = NormalizeDouble(isBuy ? last - slPips * PipSize : last + slPips * PipSize, gDigits);
   for(int i = 0; i < 3; i++)
      if(StringFind(UseLayers, nm[i]) >= 0)
         PlaceLayer(isBuy, NormalizeDouble(lv[i], gDigits), slPips, slZone, tag + "-" + nm[i]);
}

//+------------------------------------------------------------------+
//| Satu layer: limit kalau harga belum sampai, market kalau sudah   |
//+------------------------------------------------------------------+
void PlaceLayer(bool isBuy, double level, double slPips, double slPrice, string cmt)
{
   RefreshRates();
   double ask = MarketInfo(gSym, MODE_ASK);
   double bid = MarketInfo(gSym, MODE_BID);
   double stopLvl = MarketInfo(gSym, MODE_STOPLEVEL) * gPoint;
   double lot = NormLot(LayerLot);

   if(isBuy && ask - level > stopLvl + gPoint)
   {
      double sl = (slPrice > 0) ? slPrice : NormalizeDouble(level - slPips * PipSize, gDigits);
      double tp = NormalizeDouble(level + MaxTPPips * PipSize, gDigits);
      SendPending(OP_BUYLIMIT, lot, level, sl, tp, cmt);
   }
   else if(!isBuy && level - bid > stopLvl + gPoint)
   {
      double sl = (slPrice > 0) ? slPrice : NormalizeDouble(level + slPips * PipSize, gDigits);
      double tp = NormalizeDouble(level - MaxTPPips * PipSize, gDigits);
      SendPending(OP_SELLLIMIT, lot, level, sl, tp, cmt);
   }
   else
      OpenMarket(isBuy, lot, slPips, slPrice, cmt);   // harga sudah di dalam zona
}

bool SendPending(int type, double lot, double price, double sl, double tp, string cmt)
{
   color c = (type == OP_BUYLIMIT) ? clrDodgerBlue : clrOrangeRed;
   int ticket = OrderSend(gSym, type, lot, price, 0, sl, tp, cmt, MagicNumber, 0, c);
   if(ticket > 0)
   {
      Log(cmt + " pending " + DoubleToString(price, gDigits) + " SL " +
          DoubleToString(sl, gDigits) + " TP " + DoubleToString(tp, gDigits));
      return(true);
   }
   Log(cmt + " GAGAL pasang pending, error " + IntegerToString(GetLastError()), true);
   return(false);
}

//+------------------------------------------------------------------+
//| Entry market: kirim tanpa SL/TP, lalu pasang dari harga isi asli |
//| (aman untuk akun instant maupun market execution)                |
//+------------------------------------------------------------------+
bool OpenMarket(bool isBuy, double lot, double slPips, double slPrice, string cmt)
{
   for(int attempt = 0; attempt < 3; attempt++)
   {
      RefreshRates();
      double ask = MarketInfo(gSym, MODE_ASK);
      double bid = MarketInfo(gSym, MODE_BID);
      double spread = (ask - bid) / PipSize;
      if(spread > MaxSpreadPips)
      {
         Log(cmt + " batal: spread " + DoubleToString(spread, 1) + " pips", true);
         return(false);
      }
      double price = isBuy ? ask : bid;
      int ticket = OrderSend(gSym, isBuy ? OP_BUY : OP_SELL, lot, NormalizeDouble(price, gDigits),
                             SlippagePoints, 0, 0, cmt, MagicNumber, 0,
                             isBuy ? clrDodgerBlue : clrOrangeRed);
      if(ticket > 0)
      {
         SetSLTP(ticket, slPips, slPrice);
         return(true);
      }
      int err = GetLastError();
      Log(cmt + " gagal entry, error " + IntegerToString(err));
      if(err != 4 && err != 135 && err != 136 && err != 137 && err != 138 && err != 146) break;
      Sleep(500);
   }
   Log(cmt + " GAGAL entry market", true);
   return(false);
}

void SetSLTP(int ticket, double slPips, double slPrice = 0)
{
   if(!OrderSelect(ticket, SELECT_BY_TICKET)) return;
   double op  = OrderOpenPrice();
   bool   buy = (OrderType() == OP_BUY);
   double sl  = (slPrice > 0) ? slPrice
              : NormalizeDouble(buy ? op - slPips * PipSize : op + slPips * PipSize, gDigits);
   double tp  = NormalizeDouble(buy ? op + MaxTPPips * PipSize : op - MaxTPPips * PipSize, gDigits);
   string cmt = OrderComment();

   for(int i = 0; i < 5; i++)
   {
      if(OrderModify(ticket, op, sl, tp, 0, clrNONE))
      {
         Log(cmt + " entry " + DoubleToString(op, gDigits) + " SL " +
             DoubleToString(sl, gDigits) + " TP " + DoubleToString(tp, gDigits), true);
         return;
      }
      Print(cmt, " gagal pasang SL/TP, error ", GetLastError(), ", coba lagi");
      Sleep(300);
      RefreshRates();
   }
   Log("PERINGATAN: " + cmt + " belum punya SL/TP! Cek manual.", true);
}

//+------------------------------------------------------------------+
int CountActiveSignals()
{
   string ids[];
   int n = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderMagicNumber() != MagicNumber || OrderSymbol() != gSym) continue;
      string c = OrderComment();
      int dash = StringFind(c, "-");
      string id = (dash > 0) ? StringSubstr(c, 0, dash) : c;
      bool found = false;
      for(int j = 0; j < n; j++) if(ids[j] == id) { found = true; break; }
      if(!found) { ArrayResize(ids, n + 1); ids[n] = id; n++; }
   }
   return(n);
}

//+------------------------------------------------------------------+
//| Hapus pending kadaluarsa, BEP, dan SL naik bertahap              |
//+------------------------------------------------------------------+
void ManageOrders()
{
   double stopLvl = MarketInfo(gSym, MODE_STOPLEVEL) * gPoint;

   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderMagicNumber() != MagicNumber || OrderSymbol() != gSym) continue;
      int type = OrderType();

      //--- pending kadaluarsa
      if(type == OP_BUYLIMIT || type == OP_SELLLIMIT)
      {
         if(PendingExpiryMin > 0 && TimeCurrent() - OrderOpenTime() > PendingExpiryMin * 60)
         {
            string c = OrderComment();
            if(OrderDelete(OrderTicket())) Log(c + " pending dihapus (kadaluarsa)");
         }
         continue;
      }
      if(type != OP_BUY && type != OP_SELL) continue;

      //--- pengaman: posisi tanpa SL
      if(OrderStopLoss() == 0)
      {
         SetSLTP(OrderTicket(), DefaultSLPips);
         continue;
      }

      double op  = OrderOpenPrice();
      double cur = OrderStopLoss();
      double bid = MarketInfo(gSym, MODE_BID);
      double ask = MarketInfo(gSym, MODE_ASK);
      double profit = (type == OP_BUY) ? (bid - op) / PipSize : (op - ask) / PipSize;

      double lockPips;
      if(profit >= TrailStartPips)
         lockPips = TrailLockPips + MathFloor((profit - TrailStartPips) / TrailStepPips) * TrailStepPips;
      else if(profit >= BEStartPips)
         lockPips = BEOffsetPips;
      else
         continue;

      double newSL = NormalizeDouble(type == OP_BUY ? op + lockPips * PipSize
                                                    : op - lockPips * PipSize, gDigits);
      if(type == OP_BUY)
      {
         if(newSL <= cur + gPoint / 2) continue;      // SL hanya boleh naik
         if(bid - newSL < stopLvl) continue;
      }
      else
      {
         if(newSL >= cur - gPoint / 2) continue;      // SL hanya boleh turun
         if(newSL - ask < stopLvl) continue;
      }

      if(OrderModify(OrderTicket(), op, newSL, OrderTakeProfit(), 0, clrNONE))
         Log(OrderComment() + " SL dikunci di " + (lockPips > 0 ? "+" : "") +
             DoubleToString(lockPips, 0) + " pips");
   }
}
//+------------------------------------------------------------------+
