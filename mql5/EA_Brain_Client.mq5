//+------------------------------------------------------------------+
//|  EA Brain Client — MQL5                                          |
//|  Kirim OHLCV M15 + H1 + H4 ke Python backend                    |
//|  Support: market order (Strategy 1) + pending order (Strategy 2) |
//+------------------------------------------------------------------+
#property strict

input string BackendURL           = "http://127.0.0.1:8000";
input string TradePair            = "";    // kosong = otomatis pakai Symbol()
input double PipValue             = 0;    // 0 = hitung otomatis
input string NewsApiKey           = "";   // opsional
input int    CandleCount          = 880;  // candle M15 (~9 hari)
input int    PendingExpiryCandles = 4;    // cancel pending order setelah N candle M15
input double ProfitTargetUSD      = 0;    // close semua posisi EA jika total floating >= nilai ini (0 = disabled)
input double DailyProfitLimitUSD  = 0; // close all + stop trading jika profit harian (closed+floating) >= nilai ini (0 = disabled)

// ── State ─────────────────────────────────────────────────────────
datetime lastCandleTime      = 0;
bool     tradeOpen           = false;
ulong    currentTicket       = 0;
ulong    pendingTicket       = 0;
int      pendingCandleCount  = 0;

// Daily profit tracking
bool     dailyProfitLimitHit  = false;
double   dailyClosedProfitUSD = 0.0;
int      lastCheckedDay       = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   EventSetTimer(15);
   string pair = (TradePair == "") ? Symbol() : TradePair;

   if(HasOpenPosition(pair))
   {
      tradeOpen = true;
      Print("EA restarted — found open position on ", pair);
   }
   else
   {
      tradeOpen = false;
      Print("EA Brain Client v2 initialized on ", pair);
   }

   // Recovery: cek pending order aktif
   pendingTicket = FindPendingOrder(pair);
   if(pendingTicket > 0)
      Print("EA restarted — found pending order ticket=", pendingTicket);

   // Init daily tracking
   MqlDateTime dtNow;
   TimeToStruct(TimeCurrent(), dtNow);
   lastCheckedDay = dtNow.year * 10000 + dtNow.mon * 100 + dtNow.day;

   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); }

//+------------------------------------------------------------------+
double GetTotalFloatingProfit()
{
   double total = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(PositionGetSymbol(i) != "" && PositionGetInteger(POSITION_MAGIC) == 20250101)
         total += PositionGetDouble(POSITION_PROFIT);
   }
   return total;
}

void CloseAllPositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(PositionGetSymbol(i) == "" || PositionGetInteger(POSITION_MAGIC) != 20250101)
         continue;

      string  sym    = PositionGetString(POSITION_SYMBOL);
      ulong   ticket = PositionGetInteger(POSITION_TICKET);
      double  vol    = PositionGetDouble(POSITION_VOLUME);
      ENUM_POSITION_TYPE ptype = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);

      MqlTradeRequest req = {};
      MqlTradeResult  res = {};
      req.action       = TRADE_ACTION_DEAL;
      req.position     = ticket;
      req.symbol       = sym;
      req.volume       = vol;
      req.type         = (ptype == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
      req.price        = (ptype == POSITION_TYPE_BUY) ? SymbolInfoDouble(sym, SYMBOL_BID)
                                                       : SymbolInfoDouble(sym, SYMBOL_ASK);
      req.deviation    = 20;
      req.magic        = 20250101;
      req.type_filling = GetFillingMode(sym);

      if(!OrderSend(req, res))
         Print("CloseAll FAILED: ", sym, " retcode=", res.retcode);
      else
         Print("CloseAll OK: ", sym, " ticket=", ticket);
   }
   // Reset state semua chart akan handle via OnTradeTransaction
}

//+------------------------------------------------------------------+
void OnTimer()
{
   // Reset daily stats jika hari baru
   MqlDateTime dtNow;
   TimeToStruct(TimeCurrent(), dtNow);
   int todayInt = dtNow.year * 10000 + dtNow.mon * 100 + dtNow.day;
   if(todayInt != lastCheckedDay)
   {
      lastCheckedDay        = todayInt;
      dailyClosedProfitUSD  = 0.0;
      dailyProfitLimitHit   = false;
      Print("Daily stats reset for new day: ", todayInt);
   }

   // Cek daily profit limit (closed + floating)
   if(DailyProfitLimitUSD > 0 && !dailyProfitLimitHit)
   {
      double totalDailyProfit = dailyClosedProfitUSD + GetTotalFloatingProfit();
      if(totalDailyProfit >= DailyProfitLimitUSD)
      {
         Print("Daily profit limit hit: $", DoubleToString(totalDailyProfit, 2),
               " (closed=$", DoubleToString(dailyClosedProfitUSD, 2),
               " + floating=$", DoubleToString(GetTotalFloatingProfit(), 2),
               ") >= $", DoubleToString(DailyProfitLimitUSD, 2), " — closing all and stopping for today");
         CloseAllPositions();
         dailyProfitLimitHit = true;
         NotifyProfitLimitHit();
         return;
      }
   }

   // Stop trading hari ini jika limit sudah tercapai
   if(dailyProfitLimitHit) return;

   // Cek profit target portfolio floating saja (feature lama, tetap dipertahankan)
   if(ProfitTargetUSD > 0)
   {
      double totalProfit = GetTotalFloatingProfit();
      if(totalProfit >= ProfitTargetUSD)
      {
         Print("Portfolio profit target hit: $", DoubleToString(totalProfit, 2),
               " >= $", DoubleToString(ProfitTargetUSD, 2), " — closing all positions");
         CloseAllPositions();
         return;
      }
   }

   string pair = (TradePair == "") ? Symbol() : TradePair;
   datetime currentCandleTime = iTime(Symbol(), PERIOD_M15, 0);

   if(currentCandleTime == lastCandleTime) return;
   lastCandleTime = currentCandleTime;

   Print("New M15 candle — running analysis...");

   // Safety valve: sync tradeOpen dengan kondisi aktual MT5
   if(tradeOpen && !HasOpenPosition(pair))
   {
      tradeOpen = false;
      Print("State sync: tradeOpen reset — no active position found on ", pair);
   }

   // Cek expiry pending order setiap candle baru
   if(pendingTicket > 0)
   {
      if(HasPendingOrder(pair))
      {
         pendingCandleCount++;
         if(pendingCandleCount >= PendingExpiryCandles)
         {
            Print("Pending order expired after ", PendingExpiryCandles, " candles — cancelling ticket=", pendingTicket);
            CancelPendingOrder(pendingTicket, pair);
         }
         return; // Jangan buka order baru selagi pending masih aktif
      }
      else
      {
         // Pending order sudah fill atau hilang
         pendingTicket      = 0;
         pendingCandleCount = 0;
      }
   }

   if(!tradeOpen)
      RunAnalysis();
}

//+------------------------------------------------------------------+
void RunAnalysis()
{
   string pair   = (TradePair == "") ? Symbol() : TradePair;
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double pipVal = (PipValue > 0) ? PipValue : GetPipValue(pair);

   // Candle M15 (main TF — semua strategi)
   string candlesJson = BuildCandlesJSON(pair, CandleCount, PERIOD_M15);
   if(candlesJson == "") { Print("ERROR: failed to build M15 candles"); return; }

   // Candle H1 (HTF confirmation Strategy 1)
   string htfCandlesJson = BuildCandlesJSON(pair, 211, PERIOD_H1);
   if(htfCandlesJson == "") htfCandlesJson = "[]";

   // Candle H4 (S&D zone detection Strategy 2)
   string h4CandlesJson = BuildCandlesJSON(pair, 301, PERIOD_H4);
   if(h4CandlesJson == "") h4CandlesJson = "[]";

   string openTradesVal = tradeOpen ? ("\"" + pair + "\"") : "";
   string payload = "{\"pair\":\"" + pair + "\","
      + "\"equity\":" + DoubleToString(equity, 2) + ","
      + "\"pip_value\":" + DoubleToString(pipVal, 4) + ","
      + "\"candles\":" + candlesJson + ","
      + "\"htf_candles\":" + htfCandlesJson + ","
      + "\"h4_candles\":" + h4CandlesJson + ","
      + "\"open_trades\":[" + openTradesVal + "]}";

   string response = HttpPost(BackendURL + "/analyze", payload);
   if(response == "") { Print("ERROR: no response from backend"); return; }

   Print("Backend response: ", response);
   ProcessResponse(pair, response, equity);
}

//+------------------------------------------------------------------+
void ProcessResponse(string pair, string jsonResponse, double equity)
{
   string action      = JsonGetString(jsonResponse, "action");
   string orderType   = JsonGetString(jsonResponse, "order_type");
   double entryPrice  = JsonGetDouble(jsonResponse, "entry_price");
   double lotSize     = JsonGetDouble(jsonResponse, "lot_size");
   double slPrice     = JsonGetDouble(jsonResponse, "sl_price");
   double tpPrice     = JsonGetDouble(jsonResponse, "tp_price");
   string reason      = JsonGetString(jsonResponse, "reason");
   string strategyId  = JsonGetString(jsonResponse, "strategy_id");
   string aiReasoning = JsonGetString(jsonResponse, "ai_reasoning");

   Print("Action: ", action, " | Strategy: ", strategyId, " | Order: ", orderType, " | Reason: ", reason);
   if(aiReasoning != "") Print("AI: ", aiReasoning);

   if(action == "HOLD") return;
   if(tradeOpen && HasOpenPosition(pair)) return;

   if(orderType == "LIMIT" || orderType == "STOP")
   {
      PlacePendingOrder(pair, action, orderType, entryPrice, lotSize, slPrice, tpPrice, equity, strategyId);
   }
   else
   {
      if(action == "BUY")  OpenTrade(pair, ORDER_TYPE_BUY,  lotSize, slPrice, tpPrice, equity, strategyId);
      if(action == "SELL") OpenTrade(pair, ORDER_TYPE_SELL, lotSize, slPrice, tpPrice, equity, strategyId);
   }
}

//+------------------------------------------------------------------+
ENUM_ORDER_TYPE_FILLING GetFillingMode(string pair)
{
   uint filling = (uint)SymbolInfoInteger(pair, SYMBOL_FILLING_MODE);
   if((filling & SYMBOL_FILLING_FOK) != 0) return ORDER_FILLING_FOK;
   if((filling & SYMBOL_FILLING_IOC) != 0) return ORDER_FILLING_IOC;
   return ORDER_FILLING_RETURN;
}

//+------------------------------------------------------------------+
void OpenTrade(string pair, ENUM_ORDER_TYPE type, double lot, double sl, double tp, double equity, string strategyId = "EMA")
{
   MqlTradeRequest req = {};
   MqlTradeResult  res = {};

   int digits = (int)SymbolInfoInteger(pair, SYMBOL_DIGITS);
   req.action       = TRADE_ACTION_DEAL;
   req.symbol       = pair;
   req.volume       = lot;
   req.type         = type;
   req.price        = (type == ORDER_TYPE_BUY) ? SymbolInfoDouble(pair, SYMBOL_ASK)
                                               : SymbolInfoDouble(pair, SYMBOL_BID);
   req.sl           = NormalizeDouble(sl, digits);
   req.tp           = NormalizeDouble(tp, digits);
   req.deviation    = 10;
   req.magic        = 20250101;
   req.comment      = "EA_Brain_" + strategyId;
   req.type_filling = GetFillingMode(pair);

   if(!OrderSend(req, res))
   {
      Print("OrderSend FAILED: ", res.retcode, " | ", res.comment);
      return;
   }

   Print("Trade OPENED: ", EnumToString(type), " | lot=", lot, " | ticket=", res.order);
   currentTicket = res.order;
   tradeOpen     = true;
   NotifyTradeEvent(pair, "open", 0.0, equity);
}

//+------------------------------------------------------------------+
void PlacePendingOrder(string pair, string action, string orderType,
                       double entryPrice, double lot,
                       double sl, double tp, double equity, string strategyId = "FVG")
{
   MqlTradeRequest req = {};
   MqlTradeResult  res = {};

   ENUM_ORDER_TYPE pendingType;
   if(action == "BUY"  && orderType == "LIMIT") pendingType = ORDER_TYPE_BUY_LIMIT;
   else if(action == "BUY"  && orderType == "STOP")  pendingType = ORDER_TYPE_BUY_STOP;
   else if(action == "SELL" && orderType == "LIMIT") pendingType = ORDER_TYPE_SELL_LIMIT;
   else if(action == "SELL" && orderType == "STOP")  pendingType = ORDER_TYPE_SELL_STOP;
   else { Print("Unknown pending order type: ", action, " ", orderType); return; }

   int    digits  = (int)SymbolInfoInteger(pair, SYMBOL_DIGITS);
   double normPrice = NormalizeDouble(entryPrice, digits);
   double ask       = SymbolInfoDouble(pair, SYMBOL_ASK);
   double bid       = SymbolInfoDouble(pair, SYMBOL_BID);

   // Validasi harga tidak stale (harga pasar sudah melewati entry)
   if(pendingType == ORDER_TYPE_BUY_LIMIT && normPrice >= ask)
   {
      Print("BUY LIMIT skip — entry ", normPrice, " >= ask ", ask, " (price already passed)");
      return;
   }
   if(pendingType == ORDER_TYPE_SELL_LIMIT && normPrice <= bid)
   {
      Print("SELL LIMIT skip — entry ", normPrice, " <= bid ", bid, " (price already passed)");
      return;
   }

   req.action      = TRADE_ACTION_PENDING;
   req.symbol      = pair;
   req.volume      = lot;
   req.type        = pendingType;
   req.price       = normPrice;
   req.sl          = NormalizeDouble(sl, digits);
   req.tp          = NormalizeDouble(tp, digits);
   req.deviation   = 10;
   req.magic       = 20250101;
   req.comment     = "EA_Brain_" + strategyId;
   // Expiry otomatis di broker = PendingExpiryCandles × 15 menit
   req.expiration  = TimeCurrent() + PendingExpiryCandles * 15 * 60;
   req.type_time   = ORDER_TIME_SPECIFIED;

   if(!OrderSend(req, res))
   {
      Print("Pending OrderSend FAILED: ", res.retcode, " | ", res.comment);
      return;
   }

   pendingTicket     = res.order;
   pendingCandleCount = 0;
   Print("Pending order PLACED: ", action, " ", orderType, " | entry=", entryPrice,
         " | sl=", sl, " | tp=", tp, " | ticket=", res.order);
   NotifyTradeEvent(pair, "pending_placed", 0.0, equity);
}

//+------------------------------------------------------------------+
void CancelPendingOrder(ulong ticket, string pair)
{
   MqlTradeRequest req = {};
   MqlTradeResult  res = {};

   req.action = TRADE_ACTION_REMOVE;
   req.order  = ticket;

   if(!OrderSend(req, res))
      Print("Cancel pending FAILED: ", res.retcode);
   else
   {
      Print("Pending order CANCELLED ticket=", ticket);
      pendingTicket      = 0;
      pendingCandleCount = 0;
      NotifyTradeEvent(pair, "pending_cancelled", 0.0, AccountInfoDouble(ACCOUNT_EQUITY));
   }
}

//+------------------------------------------------------------------+
bool HasOpenPosition(string pair)
{
   for(int i = 0; i < PositionsTotal(); i++)
      if(PositionGetSymbol(i) == pair && PositionGetInteger(POSITION_MAGIC) == 20250101)
         return true;
   return false;
}

bool HasPendingOrder(string pair)
{
   return FindPendingOrder(pair) > 0;
}

ulong FindPendingOrder(string pair)
{
   for(int i = 0; i < OrdersTotal(); i++)
   {
      ulong ticket = OrderGetTicket(i);
      if(OrderGetString(ORDER_SYMBOL)  == pair &&
         OrderGetInteger(ORDER_MAGIC)  == 20250101)
         return ticket;
   }
   return 0;
}

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &req,
                        const MqlTradeResult  &res)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   // Hanya proses deal untuk pair chart ini, bukan pair lain
   string currentPair = (TradePair == "") ? Symbol() : TradePair;
   if(trans.symbol != currentPair) return;

   if(!HistoryDealSelect(trans.deal)) return;
   ENUM_DEAL_ENTRY dealEntry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   string pair = trans.symbol;

   if(dealEntry == DEAL_ENTRY_IN)
   {
      tradeOpen          = true;
      pendingTicket      = 0;
      pendingCandleCount = 0;
      Print("Position CONFIRMED open | ticket=", trans.deal);
      NotifyTradeEvent(pair, "open", 0.0, AccountInfoDouble(ACCOUNT_EQUITY));
   }
   else if(dealEntry == DEAL_ENTRY_OUT || dealEntry == DEAL_ENTRY_INOUT)
   {
      double pnl    = HistoryDealGetDouble(trans.deal, DEAL_PROFIT);
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double pnlPct = (equity > 0) ? pnl / equity : 0;
      tradeOpen = false;
      dailyClosedProfitUSD += pnl;
      Print("Position CLOSED | pnl=$", DoubleToString(pnl, 2), " pct=", pnlPct,
            " | daily_closed=$", DoubleToString(dailyClosedProfitUSD, 2));
      NotifyTradeEvent(pair, "close", pnlPct, equity);
   }
}

//+------------------------------------------------------------------+
void NotifyTradeEvent(string pair, string eventType, double pnlPct, double equity)
{
   string payload = StringFormat(
      "{\"pair\":\"%s\",\"event\":\"%s\",\"pnl_pct\":%.6f,\"equity\":%.2f}",
      pair, eventType, pnlPct, equity
   );
   HttpPost(BackendURL + "/trade-event", payload);
}

void NotifyProfitLimitHit()
{
   string pair   = (TradePair == "") ? Symbol() : TradePair;
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   string payload = StringFormat(
      "{\"pair\":\"%s\",\"event\":\"profit_limit_hit\",\"pnl_pct\":0.0,\"equity\":%.2f}",
      pair, equity
   );
   HttpPost(BackendURL + "/trade-event", payload);
}

//+------------------------------------------------------------------+
string BuildCandlesJSON(string pair, int count, ENUM_TIMEFRAMES tf)
{
   int bars = Bars(pair, tf);
   if(bars < 10) { Print("Not enough bars (", bars, ") for TF ", EnumToString(tf)); return ""; }
   int actual = MathMin(bars - 1, count);

   string result = "[";
   for(int i = actual - 1; i >= 1; i--)
   {
      datetime t = iTime(pair, tf, i);
      double   o = iOpen(pair, tf, i);
      double   h = iHigh(pair, tf, i);
      double   l = iLow(pair, tf, i);
      double   c = iClose(pair, tf, i);
      long     v = iVolume(pair, tf, i);

      result += StringFormat(
         "{\"time\":\"%s\",\"open\":%.5f,\"high\":%.5f,\"low\":%.5f,\"close\":%.5f,\"volume\":%d}",
         TimeToString(t, TIME_DATE|TIME_MINUTES), o, h, l, c, v
      );
      if(i > 1) result += ",";
   }
   result += "]";
   return result;
}

//+------------------------------------------------------------------+
double GetPipValue(string pair)
{
   double tickValue = SymbolInfoDouble(pair, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(pair, SYMBOL_TRADE_TICK_SIZE);
   if(tickSize <= 0 || tickValue <= 0) return 1.0;

   double pipSize;
   if(StringFind(pair, "JPY") >= 0)       pipSize = 0.01;
   else if(StringFind(pair, "XAU") >= 0)  pipSize = 0.01;
   else if(StringFind(pair, "XAG") >= 0)  pipSize = 0.001;  // Silver: pip = $0.001/oz
   else if(StringFind(pair, "BTC") >= 0 || StringFind(pair, "ETH") >= 0) pipSize = 1.0;
   else if(StringFind(pair, "US500") >= 0 || StringFind(pair, "SP500") >= 0 ||
           StringFind(pair, "US30")  >= 0 || StringFind(pair, "NAS")   >= 0 ||
           StringFind(pair, "USTEC") >= 0 || StringFind(pair, "TECH")  >= 0 ||
           StringFind(pair, "OIL")   >= 0 || StringFind(pair, "WTI")   >= 0) pipSize = 1.0;
   else                                   pipSize = 0.0001;

   return (pipSize / tickSize) * tickValue;
}

//+------------------------------------------------------------------+
string HttpPost(string url, string body)
{
   char   postData[];
   char   result[];
   string resultHeaders;
   StringToCharArray(body, postData, 0, StringLen(body));

   int timeout = 10000;
   int res = WebRequest("POST", url, "Content-Type: application/json\r\n",
                        timeout, postData, result, resultHeaders);
   if(res < 0) { Print("WebRequest error: ", GetLastError()); return ""; }
   return CharArrayToString(result);
}

//+------------------------------------------------------------------+
string JsonGetString(string json, string key)
{
   string search = "\"" + key + "\":\"";
   int start = StringFind(json, search);
   if(start < 0) return "";
   start += StringLen(search);
   int end = StringFind(json, "\"", start);
   if(end < 0) return "";
   return StringSubstr(json, start, end - start);
}

double JsonGetDouble(string json, string key)
{
   string search = "\"" + key + "\":";
   int start = StringFind(json, search);
   if(start < 0) return 0.0;
   start += StringLen(search);
   int end = start;
   while(end < StringLen(json) &&
         StringSubstr(json, end, 1) != "," &&
         StringSubstr(json, end, 1) != "}") end++;
   return StringToDouble(StringSubstr(json, start, end - start));
}
//+------------------------------------------------------------------+
