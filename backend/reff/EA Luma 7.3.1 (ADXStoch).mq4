//+------------------------------------------------------------------+
//|                                                    EA Luma 7.3.1 |
//|                                                        ADX-Stoch |
//+------------------------------------------------------------------+
#property copyright "Luma 7.3.1 - ADX-Stoch"
#property link      ""
#property description   "Ex-Barokah EA - ADX SPIKE with SMC CONFIRMATION"
#property description   "DISARANKAN AKUN RAW SPREAD"
#property description   "EA BUKAN JAMINAN PASTI PROFIT, GUNAKAN DENGAN BIJAK"
#property version   "7.3"
#property strict

//=====================================================================================

//═══════════════════════════════════════════════════════════════════════════════════
// ENUM DEFINITIONS
//═══════════════════════════════════════════════════════════════════════════════════

enum LotModeEnum {
   MANUAL = 1,
   RISK_BASED = 0
};

enum LotCalculationModeEnum {
   FIXED_LOT = 0,
   SCALING_LOT = 1
};

enum EquityStopTypeEnum {
   PERCENT_BY_BALANCE = 0,  // % dari Balance
   FIXED_USD_AMOUNT = 1     // Nilai USD tetap
};

enum EquityResetTypeEnum {
   RESET_MANUAL = 0,     // Manual 
   RESET_AUTO = 1,       // Auto 
   RESET_DAILY = 2       // Daily
};

enum SLTPModeEnum {
   SLTP_BY_PIPS = 0,    // Menggunakan pips
   SLTP_BY_RR = 1       // Menggunakan Risk Reward Ratio
};

enum SLTPUnitEnum {
   SLTP_IN_PIPS = 0,      // Stop Loss dalam pips
   SLTP_IN_DOLLAR = 1     // Stop Loss dalam dolar
};

enum ADXEntryModeEnum {
   ADX_TREND_MODE = 0,      // Mode Trend (Default) - ADX Spike + DMI Direction
   ADX_REVERSAL_MODE = 1    // Mode Reversal (Sideway) - ADX Spike + DMI Crossover
};

enum HTFConfirmModeEnum {
   HTF_CONFIRM_OFF = 0,        // Nonaktif
   HTF_CONFIRM_TREND = 1,      // Konfirmasi arah dari HTF (DMI)
   HTF_CONFIRM_ADX_LEVEL = 2   // Konfirmasi ADX level minimum dari HTF
};

enum AggressiveModeStatusEnum {
   AGGRESSIVE_WAITING = 0,           // Menunggu lonjakan candle 0
   AGGRESSIVE_DETECTED = 1,          // Lonjakan terdeteksi, akan pasang pending
   AGGRESSIVE_WAITING_EXECUTION = 2, // Pending order terpasang, menunggu eksekusi
   AGGRESSIVE_EXECUTED = 3,          // Order tereksekusi
   AGGRESSIVE_FAILED = 4,            // Gagal
   AGGRESSIVE_INACTIVE = 5           // Tidak aktif
};

enum StochasticConfirmModeEnum {
   STOC_OFF = 0,               // (0) Nonaktif - tanpa konfirmasi Stochastic
   STOC_EXIT_OBOS = 1,         // (1) Exit OB/OS - keluar dari OB untuk SELL, keluar OS untuk BUY
   STOC_CROSS_EXIT = 2,        // (2) Cross Exit - crossing %K & %D keluar dari OB/OS
   STOC_CROSS_EXTREME = 3      // (3) Cross Extreme - DMI cross + Stochastic crossing keluar OB/OS
};

//═══════════════════════════════════════════════════════════════════════════════════
// 1. TIME SETTING
//═══════════════════════════════════════════════════════════════════════════════════
extern string        _T1              = "══════ TIME SETTING ══════";
extern int           Open_Hour        = 8;
extern int           Close_Hour       = 20;
extern string        _T1a             = "  └─ Day Filters";
extern bool          TradeOnThursday  = true;
extern int           Thursday_Hour    = 20;
extern bool          TradeOnFriday    = true;
extern int           Friday_Hour      = 20;
extern bool          TradeOnSaturday  = true;
extern int           Saturday_Hour    = 23;
extern bool          TradeOnSunday    = true;
extern int           Sunday_Hour      = 23;

extern string        _SP1             = "";                              // Spasi

//═══════════════════════════════════════════════════════════════════════════════════
// 2. TARGET SETTING
//═══════════════════════════════════════════════════════════════════════════════════
extern string        _T2              = "══════ TARGET SETTING ══════";
extern bool          Use_Daily_Target = false;
extern double        Daily_Target     = 100;

extern string        _SP2             = "";                              // Spasi

//═══════════════════════════════════════════════════════════════════════════════════
// 3. LOT SETTING
//═══════════════════════════════════════════════════════════════════════════════════
extern string        _T3              = "══════ LOT SETTING ══════";
extern LotModeEnum   LotMode          = MANUAL;
extern double        Lot              = 0.04;
extern LotCalculationModeEnum LotCalculationMode = FIXED_LOT;
extern double        RiskPercentFactor = 1;

extern string        _SP3             = "";                              // Spasi

//═══════════════════════════════════════════════════════════════════════════════════
// 4. STOP LOSS & TAKE PROFIT
//═══════════════════════════════════════════════════════════════════════════════════
extern string        _T4              = "══════ SL/TP SETTING ══════";
extern SLTPModeEnum  SLTPMode         = SLTP_BY_PIPS;
extern SLTPUnitEnum  SLTPUnit         = SLTP_IN_PIPS;
extern double        StopLossPips     = 20;
extern double        StopLossDollar   = 10;
extern double        TakeProfitPips   = 35;
extern double        RiskRewardRatio  = 1.5;
extern bool          UseBreakEven     = false;
extern double        BreakEvenPips    = 15;

extern string        _SP4             = "";                              // Spasi

//═══════════════════════════════════════════════════════════════════════════════════
// 5. TRAILING STOP
//═══════════════════════════════════════════════════════════════════════════════════
extern string        _T5              = "══════ TRAILING STOP ══════";
extern int           TrailingActivationPips = 30;
extern int           TrailingStepPips = 20;

extern string        _SP5             = "";                              // Spasi

//═══════════════════════════════════════════════════════════════════════════════════
// 6. ADX SPIKE SETTING
//═══════════════════════════════════════════════════════════════════════════════════
extern string        _T6                        = "══════ ADX SPIKE SETTING ══════";
extern ADXEntryModeEnum ADXEntryMode            = ADX_TREND_MODE;   // Mode Entry ADX (Trend/Reversal)
extern ENUM_TIMEFRAMES ADXSpikeTimeframe        = PERIOD_M5;
extern int           ADXPeriod                  = 14;
extern int           ADXSpikePeriod             = 5;
extern double        ADXSpikeMinIncrease        = 10.0;
extern double        ADXSpikeMinPercentIncrease = 30.0;
extern double        ADXMinLevel                = 25;
extern bool          ADXSpikeCloseReverse       = true;
extern int           ADXSpikeCooldownMinutes    = 15;

extern string        _SP6                       = "";                              // Spasi

//═══════════════════════════════════════════════════════════════════════════════════
// 7. MULTI TIMEFRAME ADX SETTINGS
//═══════════════════════════════════════════════════════════════════════════════════
extern string        _T7              = "══════ MULTI TIMEFRAME ADX SETTINGS ══════";
extern HTFConfirmModeEnum HTFConfirmMode            = HTF_CONFIRM_OFF;  // Mode Konfirmasi HTF
extern ENUM_TIMEFRAMES    HTFTimeframe              = PERIOD_M30;       // Higher Timeframe
extern double             HTFMinADXLevel            = 25;               // Min ADX di HTF
extern bool               HTFRequireSameDirection   = true;             // Wajib arah DMI sama
extern bool               HTFReversalRequireSideway = true;            // Mode Reversal: wajib HTF sideway

//═══════════════════════════════════════════════════════════════════════════════════
// 8. OTHER CONFIRMATION
//═══════════════════════════════════════════════════════════════════════════════════
extern string        _T8                              = "══════ SMC CONFIRMATION ══════";
extern bool          UseSMCConfirm                    = true;
extern int           SMCSwingPeriod                   = 20;
extern double        SMCConfirmMinDistancePips        = 10.0;
extern bool          RequireBOSConfirm                = true;
extern bool          AllowEntryOnCHoCH                = false;
extern string        _T8b                             = "══════ STOCHASTIC CONFIRMATION ══════";
extern StochasticConfirmModeEnum UseStochasticConfirm = STOC_OFF;
extern ENUM_TIMEFRAMES StochasticTimeframe            = PERIOD_M5;
extern int           StochasticKPeriod                = 5;
extern int           StochasticDPeriod                = 3;
extern int           StochasticSlowing                = 3;
extern double        OverboughtLevel                  = 80.0;
extern double        OversoldLevel                    = 20.0;

extern string        _SP8             = "";                              // Spasi

//═══════════════════════════════════════════════════════════════════════════════════
// 9. EQUITY STOP
//═══════════════════════════════════════════════════════════════════════════════════
extern string        _T9              = "══════ EQUITY STOP ══════";
extern bool          UseEquityStop    = true;
extern EquityStopTypeEnum EquityStopType = PERCENT_BY_BALANCE;
extern double        TotalEquityRisk  = 30;

extern string        _SP9             = "";                              // Spasi

//═══════════════════════════════════════════════════════════════════════════════════
// 10. RESET SETTINGS
//═══════════════════════════════════════════════════════════════════════════════════
extern string        _T10              = "══════ RESET SETTINGS ══════";
extern EquityResetTypeEnum EquityResetType = RESET_MANUAL;
extern int           DailyResetHour   = 0;
extern bool          SendResetNotification = true;

extern string        _SP10             = "";                              // Spasi

//═══════════════════════════════════════════════════════════════════════════════════
// 11. NEWS FILTER
//═══════════════════════════════════════════════════════════════════════════════════
extern string        _T11                 = "══════ NEWS FILTER ══════";
extern bool          UseNewsFilter        = true;
extern int           MinutesBeforeNews    = 480;
extern int           MinutesAfterNews     = 240;
extern string        _T11a                = "  └─ Impact Filters";
extern bool          FilterHighNews       = true;
extern bool          FilterMediumNews     = true;
extern bool          FilterLowNews        = false;
extern bool          AffectedCurrencyOnly = true;
extern string        _T11b                = "  └─ Download Settings";
extern int           downloadNewsInterval = 60;
extern int           readNewsInterval     = 5;
extern bool          IsDownloader         = true;

extern string        _SP11                = "";                              // Spasi

//═══════════════════════════════════════════════════════════════════════════════════
// 12. PROTECTION SETTINGS
//═══════════════════════════════════════════════════════════════════════════════════
extern string        _T12               = "══════ PROTECTION SETTINGS ══════";
extern double        MaxAllowedSpread   = 5.0;
extern int           ManualBrokerOffset = 0;

extern string        _SP12              = "";                              // Spasi

//═══════════════════════════════════════════════════════════════════════════════════
// 13. AGGRESSIVE NEWS TRADING
//═══════════════════════════════════════════════════════════════════════════════════
extern string        _T13                          = "══════ AGGRESSIVE NEWS TRADING ══════";
extern bool          UseAggressiveNewsEntry        = true;              
extern double        AdaptiveDistanceATRMult       = 0.4;               
extern double        MinDistancePips               = 8.0;               
extern double        MaxDistancePips               = 40.0;              
extern bool          UseHighImpactBuffer           = true;              
extern double        HighImpactBufferMult          = 1.3;               
extern int           PendingOrderLifetimeSeconds   = 90;                
extern string        _T13a                         = "  └─ Aggressive Trailing News";
extern bool          UseAggressiveTrailing         = true;              
extern int           AggressiveTrailDistancePips   = 5;                 
extern int           AggressiveTrailStepPips       = 3;                 
extern string        _T13b                         = "  └─ Spike Detection";
extern double        AggressiveMinSpikePips        = 15.0;               // Minimal lonjakan candle 0 (pips)
extern int           AggressiveMaxDetectionSeconds = 60;                // Maksimal waktu deteksi lonjakan (detik)

//═══════════════════════════════════════════════════════════════════════════════════
// END OF PARAMETERS
//═══════════════════════════════════════════════════════════════════════════════════

//=== GLOBAL VARIABLES ===
int MagicNumber;
double slippage = 3;
string EAName = "Luma 7.3.1 ADX-Stoch";

string nextNewsTimeString = "";      
string nextNewsTitleShort = "";      
string nextNewsFullTitle = "";       

// Trailing Stop
bool isTrailingActive = false;
string trailingStatus = "";

// Equity Stop Variables
double highestEquity = 0;
bool equityStopTriggered = false;
double equityStopLevel = 0;
double equityStopPercent = 0;

// Cooldown tracking variables
datetime stopTriggeredTime = 0;
int remainingCooldown = 0;

// Reset Variables
int lastResetDay = -1;
datetime lastResetTime = 0;
bool dailyResetPerformed = false;
bool autoResetCooldown = false;
datetime lastAutoResetTime = 0;

// Max Drawdown Tracking
double maxDrawdownPercent = 0;
double maxDrawdownAmount = 0;
datetime maxDDTime = 0;

// SMC Structure Tracking
double lastSwingHighSMC = 0;      // Swing high terakhir untuk struktur
double lastSwingLowSMC = 0;       // Swing low terakhir untuk struktur
double higherHigh = 0;            // Higher High terakhir
double higherLow = 0;             // Higher Low terakhir
double lowerHigh = 0;             // Lower High terakhir
double lowerLow = 0;              // Lower Low terakhir
string currentStructure = "NEUTRAL"; // BULLISH / BEARISH / NEUTRAL
datetime lastStructureChange = 0;

// ADX Spike Entry Mode
datetime adxSpikeActivationTime = 0;
datetime adxSpikeDeactivationTime = 0;
bool adxSpikeEntryExecuted = false;
datetime adxSpikeLastSignalTime = 0;

// News Variables
datetime lastDownloadNews = 0;
datetime lastCheckNews = 0;
bool isIncomingNews = false;
string newsMessage = "";
datetime nextNewsTime = 0;
string nextNewsImpact = "";
string nextNewsTitle = "";

// News Windows Alert
datetime activeNewsTime = 0;      
datetime windowEndTime = 0;       
string activeNewsImpact = "";     

// Struktur untuk Pre-News Levels
struct PreNewsLevels {
   double highLevel;
   double lowLevel;
   datetime candleTime;
   bool isValid;
};

// Struktur untuk Spike Levels
struct SpikeLevels {
   double highLevel;
   double lowLevel;
   datetime spikeTime;
   double spikeMovePips;
   bool isActive;
};

// Struktur untuk Tracker Posisi Agresif
struct AggressivePositionTracker {
   int ticket;
   int orderType;
   double openPrice;
   double highestPrice;      // Harga tertinggi (untuk BUY)
   double lowestPrice;       // Harga terendah (untuk SELL)
   datetime entryTime;
   double peakProfitPips;
};

// Global Variables untuk Aggressive Mode
PreNewsLevels preNews;
SpikeLevels currentSpike;
AggressivePositionTracker aggressivePos;
int buyStopTicket = -1;
int sellStopTicket = -1;
datetime pendingOrderPlacedTime = 0;
datetime aggressiveCheckStartTime = 0;
bool aggressiveAttemptDone = false;
bool aggressiveEntryExecuted = false;

AggressiveModeStatusEnum aggressiveStatus = AGGRESSIVE_WAITING;

// Struktur News Data
struct NewsData {
   string title;
   string impact;
   datetime releaseTime;
   bool hasExecuted;
};

NewsData currentNews;

// Original EA Variables
double initialAccountBalance = 0;
double baseLotSize = 0;
int OrderCycleState = 0;
bool IsEntryAllowed = false;
double LastBuyOpenPrice = 0;
double LastSellOpenPrice = 0;
bool HasBuyPosition = false;
bool HasSellPosition = false;
double SumPriceLots = 0;
double TotalLots = 0;
datetime lastTradeTime = 0;
bool I_b_16 = false;

// Dashboard variables
color panelBgColor = C'30,30,30';
color panelBorderColor = C'60,60,60';
color titleColor = C'255,165,0';
color textColor = C'220,220,220';
color profitColor = C'0,255,0';
color lossColor = C'255,50,50';
color warningColor = C'255,255,0';
color neutralColor = C'220,220,220';

// Peak equity tracking
double peakEquity = 0;
datetime lastPeakTime = 0;

// Cek order
bool IsMyOrder() {
return (StringCompare(OrderSymbol(), Symbol(), false) == 0 && 
        OrderMagicNumber() == MagicNumber);
}

// Profit/Loss per Pair
double GetPairFloatingProfit() {
   double profit = 0;
   for (int i = 0; i < OrdersTotal(); i++) {
      if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) {
         if (OrderSymbol() == Symbol() && OrderMagicNumber() == MagicNumber) {
            profit += OrderProfit() + OrderSwap() + OrderCommission();
         }
      }
   }
   return profit;
}

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit() {
   Print("=== " + EAName + " INITIALIZATION ===");
   
   // Set Magic Number
   MagicNumber = 101108;
   if (_Symbol == "EURCHF") MagicNumber = 101108;
   else if (_Symbol == "EURUSD") MagicNumber = 101111;
   else if (_Symbol == "GBPUSD") MagicNumber = 101114;
   else if (_Symbol == "USDJPY") MagicNumber = 101118;
   else if (_Symbol == "CADAUD") MagicNumber = 101122;
   else if (_Symbol == "CADNZD") MagicNumber = 101124;
   else if (_Symbol == "XAUUSD") MagicNumber = 101150;  
   else if (_Symbol == "BTCUSD") MagicNumber = 101160;  
   else if (_Symbol == "USDCHF") MagicNumber = 101170;  
   else MagicNumber = 999999;
   
   initialAccountBalance = AccountBalance();
   if (LotMode == MANUAL) {
      baseLotSize = Lot;
   } else {
      baseLotSize = ((AccountBalance() * RiskPercentFactor) / 100) / 1000;
   }
   
   // Initialize equity stop
   if (UseEquityStop) {
      if (EquityStopType == PERCENT_BY_BALANCE) {
         equityStopPercent = TotalEquityRisk;
         equityStopLevel = AccountBalance() * (1 - (TotalEquityRisk / 100));
      } else {
         equityStopLevel = AccountBalance() - TotalEquityRisk;
         equityStopPercent = (TotalEquityRisk / AccountBalance()) * 100;
      }
      highestEquity = AccountEquity();
   }
   
   Print("=== METODE ENTRY ===");
   Print("Entry Mode: ADX SPIKE ONLY with SMC CONFIRMATION");
   Print("ADX Spike: ACTIVE");
   Print("   ADX Timeframe: ", EnumToString(ADXSpikeTimeframe));
   Print("   ADX Period: ", ADXPeriod);
   Print("   Spike Lookback: ", ADXSpikePeriod);
   Print("   Min Increase: ", DoubleToString(ADXSpikeMinIncrease,1), " points");
   Print("   Min Percent: ", DoubleToString(ADXSpikeMinPercentIncrease,1), "%");
   Print("   Min ADX Level: ", DoubleToString(ADXMinLevel,1));
   Print("   Close & Reverse: ", ADXSpikeCloseReverse ? "YES" : "NO");
   Print("   Cooldown: ", ADXSpikeCooldownMinutes, " menit");
   Print("   Entry Mode: ", (ADXEntryMode == ADX_TREND_MODE ? "TREND (Ikuti DMI)" : "REVERSAL (Crossover Sideway)"));
   Print("Multi TF Confirmation: ", (HTFConfirmMode == HTF_CONFIRM_OFF ? "OFF" : 
         (HTFConfirmMode == HTF_CONFIRM_TREND ? "TREND CONFIRM on " + EnumToString(HTFTimeframe) : 
         "ADX LEVEL CONFIRM on " + EnumToString(HTFTimeframe))));
      if (HTFConfirmMode != HTF_CONFIRM_OFF) {
         Print("   HTF ADX Level: ", DoubleToString(HTFMinADXLevel,1));
         Print("   Require Same Direction: ", HTFRequireSameDirection ? "YES" : "NO");
      if (ADXEntryMode == ADX_REVERSAL_MODE) {
         Print("   HTF Reversal Require Sideway: ", HTFReversalRequireSideway ? "YES" : "NO");
         }
   }
   Print("SMC Confirmation: ", UseSMCConfirm ? "ACTIVE" : "OFF");
   if(UseSMCConfirm) {
      Print("   SMC Swing Period: ", SMCSwingPeriod);
      Print("   Require BOS Confirm: ", RequireBOSConfirm ? "YES" : "NO");
      Print("   Allow Entry on CHoCH: ", AllowEntryOnCHoCH ? "YES" : "NO");
   }
   
   Print("Stochastic Confirmation: ", 
      (UseStochasticConfirm == STOC_OFF ? "OFF" :
       UseStochasticConfirm == STOC_EXIT_OBOS ? "EXIT OB/OS" :
       UseStochasticConfirm == STOC_CROSS_EXIT ? "CROSS EXIT" : "CROSS EXTREME"));
   
   // Initialize news filter
   if (UseNewsFilter && IsDownloader) {
      FileDelete("forex_news.xml");
      Sleep(1000);
      CheckNews();
   }
   
   // Inisialisasi SMC variables
   currentStructure = "NEUTRAL";
   lastSwingHighSMC = 0;
   lastSwingLowSMC = 0;
   higherHigh = 0;
   higherLow = 0;
   lowerHigh = 0;
   lowerLow = 0;
   lastStructureChange = 0;
   
   peakEquity = AccountEquity();
   lastPeakTime = TimeCurrent();
   Print("📈 Peak equity initialized: $", DoubleToString(peakEquity, 2));
   
   // Hitung max drawdown dari history
   maxDrawdownAmount = 0;
   maxDrawdownPercent = 0;
   
   for (int i = OrdersHistoryTotal() - 1; i >= 0; i--) {
      if (OrderSelect(i, SELECT_BY_POS, MODE_HISTORY)) {
         if (OrderSymbol() == Symbol() && OrderMagicNumber() == MagicNumber) {
            double loss = 0;
            double profit = OrderProfit() + OrderSwap() + OrderCommission();
            if (profit < 0) {
               loss = MathAbs(profit);
               if (loss > maxDrawdownAmount) {
                  maxDrawdownAmount = loss;
               }
            }
         }
      }
   }
   
   if (maxDrawdownAmount > 0) {
      maxDrawdownPercent = (maxDrawdownAmount / peakEquity) * 100.0;
      Print("📊 Max drawdown dari history: $", DoubleToString(maxDrawdownAmount, 2), 
            " (", DoubleToString(maxDrawdownPercent, 1), "%)");
   } else {
      Print("📊 Tidak ada history loss untuk pair ini");
   }
   
   CreateDashboard();
      
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Create Dashboard Panel                                           |
//+------------------------------------------------------------------+
void CreateDashboard() {
   ObjectsDeleteAll(0, "VENUS_");
   
   // Panel Background
   ObjectCreate(0, "VENUS_BG", OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, "VENUS_BG", OBJPROP_XDISTANCE, 10);
   ObjectSetInteger(0, "VENUS_BG", OBJPROP_YDISTANCE, 20);
   ObjectSetInteger(0, "VENUS_BG", OBJPROP_XSIZE, 390);
   ObjectSetInteger(0, "VENUS_BG", OBJPROP_YSIZE, 310);
   ObjectSetInteger(0, "VENUS_BG", OBJPROP_BGCOLOR, panelBgColor);
   ObjectSetInteger(0, "VENUS_BG", OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, "VENUS_BG", OBJPROP_BORDER_COLOR, panelBorderColor);
   
   // Title
   ObjectCreate(0, "VENUS_TITLE", OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, "VENUS_TITLE", OBJPROP_XDISTANCE, 20);
   ObjectSetInteger(0, "VENUS_TITLE", OBJPROP_YDISTANCE, 25);
   ObjectSetString(0, "VENUS_TITLE", OBJPROP_TEXT, "Luma EA v7.3.1 ADX-Stoch");
   ObjectSetInteger(0, "VENUS_TITLE", OBJPROP_COLOR, titleColor);
   ObjectSetInteger(0, "VENUS_TITLE", OBJPROP_FONTSIZE, 12);
   ObjectSetString(0, "VENUS_TITLE", OBJPROP_FONT, "Arial Bold");
   
   // Separator
   ObjectCreate(0, "VENUS_SEP1", OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, "VENUS_SEP1", OBJPROP_XDISTANCE, 15);
   ObjectSetInteger(0, "VENUS_SEP1", OBJPROP_YDISTANCE, 50);
   ObjectSetInteger(0, "VENUS_SEP1", OBJPROP_XSIZE, 370);
   ObjectSetInteger(0, "VENUS_SEP1", OBJPROP_YSIZE, 1);
   ObjectSetInteger(0, "VENUS_SEP1", OBJPROP_BGCOLOR, panelBorderColor);
   
   CreateInfoLabels();
}

//+------------------------------------------------------------------+
//| Create Information Labels                                        |
//+------------------------------------------------------------------+
void CreateInfoLabels() {
   int yPos = 60;
   int lineHeight = 22;
   
   string labels[] = {
      "Account:",
      "Symbol/Spread:",      
      "Balance/Equity:",
      "Free Margin:",
      "Open Positions:",
      "Daily P/L:",
      "Drawdown $:",
      "Equity Stop:",
      "News Filter:",     
      "Trading Hours:",      
      "Status:"           
   };
   
   for(int i = 0; i < ArraySize(labels); i++) {
      string labelName = "VENUS_LABEL_" + IntegerToString(i);
      ObjectCreate(0, labelName, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, labelName, OBJPROP_XDISTANCE, 20);
      ObjectSetInteger(0, labelName, OBJPROP_YDISTANCE, yPos);
      ObjectSetString(0, labelName, OBJPROP_TEXT, labels[i]);
      ObjectSetInteger(0, labelName, OBJPROP_COLOR, textColor);
      ObjectSetInteger(0, labelName, OBJPROP_FONTSIZE, 9);
      
      string valueName = "VENUS_VALUE_" + IntegerToString(i);
      ObjectCreate(0, valueName, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, valueName, OBJPROP_XDISTANCE, 180);
      ObjectSetInteger(0, valueName, OBJPROP_YDISTANCE, yPos);
      ObjectSetString(0, valueName, OBJPROP_TEXT, "-");
      ObjectSetInteger(0, valueName, OBJPROP_COLOR, textColor);
      ObjectSetInteger(0, valueName, OBJPROP_FONTSIZE, 9);
      ObjectSetString(0, valueName, OBJPROP_FONT, "Consolas");
      
   yPos += lineHeight;
   }
   
   int newsTitleY = 60 + (8 * lineHeight) + lineHeight;

   ObjectCreate(0, "VENUS_NEWS_TITLE", OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, "VENUS_NEWS_TITLE", OBJPROP_XDISTANCE, 180);
   ObjectSetInteger(0, "VENUS_NEWS_TITLE", OBJPROP_YDISTANCE, newsTitleY);
   ObjectSetString(0, "VENUS_NEWS_TITLE", OBJPROP_TEXT, "");
   ObjectSetInteger(0, "VENUS_NEWS_TITLE", OBJPROP_COLOR, textColor);
   ObjectSetInteger(0, "VENUS_NEWS_TITLE", OBJPROP_FONTSIZE, 8);
   ObjectSetString(0, "VENUS_NEWS_TITLE", OBJPROP_FONT, "Consolas");

   int tradingHoursY = newsTitleY + lineHeight;
   int statusY = tradingHoursY + lineHeight;

   if (ObjectFind(0, "VENUS_LABEL_9") >= 0) {
      ObjectSetInteger(0, "VENUS_LABEL_9", OBJPROP_YDISTANCE, tradingHoursY);
      ObjectSetInteger(0, "VENUS_VALUE_9", OBJPROP_YDISTANCE, tradingHoursY);
   }
   if (ObjectFind(0, "VENUS_LABEL_10") >= 0) {
      ObjectSetInteger(0, "VENUS_LABEL_10", OBJPROP_YDISTANCE, statusY);
      ObjectSetInteger(0, "VENUS_VALUE_10", OBJPROP_YDISTANCE, statusY);
   }
   
   int signalY = statusY + lineHeight + 15;
   ObjectCreate(0, "VENUS_SIGNAL", OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, "VENUS_SIGNAL", OBJPROP_XDISTANCE, 20);
   ObjectSetInteger(0, "VENUS_SIGNAL", OBJPROP_YDISTANCE, signalY);
   ObjectSetString(0, "VENUS_SIGNAL", OBJPROP_TEXT, "Signal: WAITING");
   ObjectSetInteger(0, "VENUS_SIGNAL", OBJPROP_COLOR, textColor);
   ObjectSetInteger(0, "VENUS_SIGNAL", OBJPROP_FONTSIZE, 10);
   ObjectSetString(0, "VENUS_SIGNAL", OBJPROP_FONT, "Arial Bold");
}

//+------------------------------------------------------------------+
//| Update Dashboard                                                 |
//+------------------------------------------------------------------+
void UpdateDashboard() {
   static datetime lastUpdate = 0;
   if (TimeCurrent() - lastUpdate < 1) return;
   lastUpdate = TimeCurrent();
   
   static datetime lastNewsCheck = 0;
   if (UseNewsFilter && (TimeCurrent() - lastNewsCheck > 10)) {
      CheckNews();
      lastNewsCheck = TimeCurrent();
   }
   
   if (EquityResetType == RESET_DAILY) CheckDailyReset();
   if (EquityResetType == RESET_AUTO && equityStopTriggered) CheckAutoReset();
   
   UpdateAccountInfo();
   UpdateTradeInfo();
   UpdateRiskInfo();
   UpdateSignalInfo();
   
   ChartRedraw();
}

//+------------------------------------------------------------------+
//| Update Account Information                                       |
//+------------------------------------------------------------------+
void UpdateAccountInfo() {
   ObjectSetString(0, "VENUS_VALUE_0", OBJPROP_TEXT, 
                   IntegerToString(AccountNumber()));
   
   double currentSpread = (Ask - Bid) / Point;
   string spreadText = Symbol() + " (" + DoubleToString(currentSpread, 1) + " pts)";
   
   color spreadColor = textColor;
   if (currentSpread > MaxAllowedSpread * 0.8) {
      spreadColor = warningColor;  
   }
   if (currentSpread > MaxAllowedSpread) {
      spreadColor = lossColor;     
   }
   
   ObjectSetString(0, "VENUS_VALUE_1", OBJPROP_TEXT, spreadText);
   ObjectSetInteger(0, "VENUS_VALUE_1", OBJPROP_COLOR, spreadColor);
   
   ObjectSetString(0, "VENUS_VALUE_2", OBJPROP_TEXT, 
                   "$" + DoubleToString(AccountBalance(), 0) + 
                   " / $" + DoubleToString(AccountEquity(), 0));
   
   double marginLevel = (AccountMargin() > 0) ? (AccountEquity() / AccountMargin() * 100) : 0;
   ObjectSetString(0, "VENUS_VALUE_3", OBJPROP_TEXT, 
                   "$" + DoubleToString(AccountFreeMargin(), 0) + 
                   " (" + DoubleToString(marginLevel, 1) + "%)");
}

//+------------------------------------------------------------------+
//| Update Trade Information                                         |
//+------------------------------------------------------------------+
void UpdateTradeInfo() {
   int buyCount = 0, sellCount = 0;
   double floatingPL = 0;
   
   for(int i = 0; i < OrdersTotal(); i++) {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) {
         if(IsMyOrder()) {
            if(OrderType() == OP_BUY) buyCount++;
            if(OrderType() == OP_SELL) sellCount++;
            floatingPL += OrderProfit() + OrderSwap() + OrderCommission();
         }
      }
   }
   
   int totalPositions = buyCount + sellCount;
   
   if (ObjectFind(0, "VENUS_VALUE_4") >= 0) {
      ObjectSetString(0, "VENUS_VALUE_4", OBJPROP_TEXT, 
                      IntegerToString(totalPositions) + 
                      " (B:" + IntegerToString(buyCount) + 
                      " S:" + IntegerToString(sellCount) + ")");
   }
   
   double dailyRealized = CalculateDailyRealizedProfit();
   double dailyFloating = CalculateDailyFloatingProfit();
   double dailyTotal = dailyRealized + dailyFloating;
   
   color dailyColor = (dailyTotal >= 0) ? profitColor : lossColor;
   
   string dailyText = "$" + DoubleToString(dailyTotal, 2);
   if(Use_Daily_Target) {
      dailyText += " / $" + DoubleToString(Daily_Target, 0);
   }
   
   if (ObjectFind(0, "VENUS_VALUE_5") >= 0) {
      ObjectSetString(0, "VENUS_VALUE_5", OBJPROP_TEXT, dailyText);
      ObjectSetInteger(0, "VENUS_VALUE_5", OBJPROP_COLOR, dailyColor);
   }
   
   UpdateMaxDrawdown();
   
   string floatingText = "";
   string maxDDText = "$" + DoubleToString(maxDrawdownAmount, 2);
   color floatingColor = neutralColor;
   
   if (totalPositions > 0) {
      if (floatingPL > 0) {
         floatingText = "+$" + DoubleToString(floatingPL, 2);
         floatingColor = profitColor;
      } else if (floatingPL < 0) {
         floatingText = "-$" + DoubleToString(MathAbs(floatingPL), 2);
         floatingColor = lossColor;
      } else {
         floatingText = "$0.00";
         floatingColor = neutralColor;
      }
   } else {
      floatingText = "$0.00";
   }
   
   string floatingDDText = floatingText + " / " + maxDDText;
   
   if (ObjectFind(0, "VENUS_VALUE_6") >= 0) {
      ObjectSetString(0, "VENUS_VALUE_6", OBJPROP_TEXT, floatingDDText);
      ObjectSetInteger(0, "VENUS_VALUE_6", OBJPROP_COLOR, floatingColor);
   }
   
   if (ObjectFind(0, "VENUS_LABEL_6") >= 0) {
      ObjectSetString(0, "VENUS_LABEL_6", OBJPROP_TEXT, "Floating/DD:");
   }
}

//+------------------------------------------------------------------+
//| Update Risk Information                                          |
//+------------------------------------------------------------------+
void UpdateRiskInfo() {
   string equityStopText = UseEquityStop ? 
      (EquityStopType == PERCENT_BY_BALANCE ? 
      DoubleToString(TotalEquityRisk, 1) + "%" : 
      "$" + DoubleToString(TotalEquityRisk, 0)) : "OFF";

   int activeTradesLocal = CountOpenTrades();
   if (activeTradesLocal > 0) {
      if (isTrailingActive) {
         equityStopText += " / Trl ACTIVE";
      } else {
         if (trailingStatus != "" && StringFind(trailingStatus, "Waiting") >= 0) {
            equityStopText += " / " + trailingStatus;
         }
      }
   } else {
      equityStopText += " / No Pos";
   }

   color equityColor = textColor;
   if (UseEquityStop && equityStopTriggered) {
      equityColor = lossColor;
   } else if (UseEquityStop) {
      equityColor = warningColor;
   }

   ObjectSetString(0, "VENUS_VALUE_7", OBJPROP_TEXT, equityStopText);
   ObjectSetInteger(0, "VENUS_VALUE_7", OBJPROP_COLOR, equityColor);
   
   string newsFilterText = "";
   color newsFilterColor = textColor;
   
   if (UseNewsFilter) {
      if (nextNewsTime > 0) {
         datetime now = TimeCurrent();
         double secondsDiff = (double)(nextNewsTime - now);
         int hoursLeft = (int)(secondsDiff / 3600.0);
         int minutesLeft = (int)((secondsDiff / 60.0)) % 60;
         
         string upperImpact = ToUpper(nextNewsImpact);
         if (StringFind(upperImpact, "HIGH") != -1) {
            newsFilterColor = C'255,80,80';
         } else if (StringFind(upperImpact, "MEDIUM") != -1) {
            newsFilterColor = C'255,165,0';
         } else if (StringFind(upperImpact, "LOW") != -1) {
            newsFilterColor = C'255,255,0';
         } else {
            newsFilterColor = textColor;
         }
         
         string countdownText = "";
         if (hoursLeft > 24) {
            int daysLeft = hoursLeft / 24;
            countdownText = "(-" + IntegerToString(daysLeft) + "d)";
         } else if (hoursLeft > 0) {
            countdownText = "(-" + IntegerToString(hoursLeft) + "h " + IntegerToString(minutesLeft) + "m)";
         } else if (minutesLeft > 0) {
            countdownText = "(-" + IntegerToString(minutesLeft) + "m)";
         } else if (secondsDiff > 0) {
            countdownText = "(<1m)";
         } else {
            countdownText = "(NOW)";
         }
         
         newsFilterText = nextNewsTimeString + " " + countdownText;
         
      } else {
         newsFilterText = "CLEAR";
         newsFilterColor = C'100,255,100';
      }
   } else {
      newsFilterText = "OFF";
   }
   
   if (ObjectFind(0, "VENUS_VALUE_8") >= 0) {
      ObjectSetString(0, "VENUS_VALUE_8", OBJPROP_TEXT, newsFilterText);
      ObjectSetInteger(0, "VENUS_VALUE_8", OBJPROP_COLOR, newsFilterColor);
   }
   if (ObjectFind(0, "VENUS_NEWS_TITLE") >= 0) {
      if (nextNewsTitle != "") {
         string shortTitle = nextNewsTitle;
         if (StringLen(shortTitle) > 45) {
            shortTitle = StringSubstr(shortTitle, 0, 42) + "...";
         }
         ObjectSetString(0, "VENUS_NEWS_TITLE", OBJPROP_TEXT, "📰 " + shortTitle);
         ObjectSetInteger(0, "VENUS_NEWS_TITLE", OBJPROP_COLOR, newsFilterColor);
      } else {
         ObjectSetString(0, "VENUS_NEWS_TITLE", OBJPROP_TEXT, "");
      }
   }
   
   string tradingHoursText = GetTradingHoursInWIB();
   ObjectSetString(0, "VENUS_VALUE_9", OBJPROP_TEXT, tradingHoursText);
   
   string statusText = "";
   color statusColor = textColor;
   
   int totalPositions = CountOpenTrades();
   
   if (equityStopTriggered) {
      if (EquityResetType == RESET_AUTO && remainingCooldown > 0) {
         statusText = "COOLDOWN: " + IntegerToString(remainingCooldown) + "s";
         statusColor = warningColor;
      } else if (EquityResetType == RESET_MANUAL) {
         statusText = "STOP (Manual)";
         statusColor = lossColor;
      } else if (EquityResetType == RESET_DAILY) {
         statusText = "STOP (Daily Reset)";
         statusColor = warningColor;
      } else {
         statusText = "WAITING RESET";
         statusColor = warningColor;
      }
   } 
   else if (isIncomingNews) {
      datetime now = TimeCurrent();
      int secondsLeft = (int)(windowEndTime - now);
      if (secondsLeft < 0) secondsLeft = 0;
      
      statusText = "NEWS ALERT (" + FormatCountdown(secondsLeft) + ")";
      
      string upperImpact = ToUpper(activeNewsImpact);
      if (StringFind(upperImpact, "HIGH") != -1) {
         statusColor = C'255,80,80';
      } else if (StringFind(upperImpact, "MEDIUM") != -1) {
         statusColor = C'255,165,0';
      } else if (StringFind(upperImpact, "LOW") != -1) {
         statusColor = C'255,255,0';
      } else {
         statusColor = warningColor;
      }
   }
   else if (totalPositions > 0) {
      statusText = "TRADING (" + IntegerToString(totalPositions) + ")";
      statusColor = profitColor;
   } else {
      statusText = "WAITING";
   }
   
   if (ObjectFind(0, "VENUS_VALUE_10") >= 0) {
      ObjectSetString(0, "VENUS_VALUE_10", OBJPROP_TEXT, statusText);
      ObjectSetInteger(0, "VENUS_VALUE_10", OBJPROP_COLOR, statusColor);
   }
}

//+------------------------------------------------------------------+
//| Update Signal Information                                        |
//+------------------------------------------------------------------+
void UpdateSignalInfo() {
   string signalText = "";
   color signalColor = textColor;
   
   int totalPositions = CountOpenTrades();
   
   if(totalPositions == 0) {
      int adxSignal = -1;
      if (CheckADXSpikeEntry(adxSignal)) {
         signalText = (adxSignal == OP_BUY ? "ADX_BUY SIGNAL" : "ADX_SELL SIGNAL");
         signalColor = (adxSignal == OP_BUY) ? profitColor : lossColor;
      } else {
         signalText = "NO SIGNAL";
      }
   } else {
      CheckActivePositions();
      if(HasBuyPosition && HasSellPosition) {
         signalText = "HEDGING";
         signalColor = warningColor;
      } else if(HasBuyPosition) {
         signalText = "ACTIVE BUY (" + IntegerToString(totalPositions) + ")";
         signalColor = profitColor;
      } else if(HasSellPosition) {
         signalText = "ACTIVE SELL (" + IntegerToString(totalPositions) + ")";
         signalColor = lossColor;
      }
   }
   
   if (ObjectFind(0, "VENUS_SIGNAL") >= 0) {
      ObjectSetString(0, "VENUS_SIGNAL", OBJPROP_TEXT, "Signal: " + signalText);
      ObjectSetInteger(0, "VENUS_SIGNAL", OBJPROP_COLOR, signalColor);
   }
}

//+------------------------------------------------------------------+
//| Get Peak Equity                                                  |
//+------------------------------------------------------------------+
double GetPeakEquity() {
   double currentEquity = AccountEquity();
   if (currentEquity > peakEquity) {
      peakEquity = currentEquity;
      lastPeakTime = TimeCurrent();
      Print("📈 Peak equity meningkat: $", DoubleToString(peakEquity, 2));
   }
   return peakEquity;
}

//+------------------------------------------------------------------+
//| Update Max Drawdown                                              |
//+------------------------------------------------------------------+
void UpdateMaxDrawdown() {
   double currentEquity = AccountEquity();
   
   if (peakEquity == 0) {
      peakEquity = currentEquity;
      lastPeakTime = TimeCurrent();
   }
   
   if (currentEquity > peakEquity) {
      peakEquity = currentEquity;
      lastPeakTime = TimeCurrent();
   }
   
   double currentDrawdown = 0;
   if (peakEquity > currentEquity) {
      currentDrawdown = peakEquity - currentEquity;
   }
   
   if (currentDrawdown > maxDrawdownAmount) {
      maxDrawdownAmount = currentDrawdown;
      maxDrawdownPercent = (maxDrawdownAmount / peakEquity) * 100.0;
      maxDDTime = TimeCurrent();
      
      Print("📊 Max Drawdown: $", DoubleToString(maxDrawdownAmount, 2), 
            " (", DoubleToString(maxDrawdownPercent, 1), "%)");
   }
   
   if (CountOpenTrades() == 0) {
      peakEquity = currentEquity;
   }
}

//+------------------------------------------------------------------+
//| Count Open Trades                                                |
//+------------------------------------------------------------------+
int CountOpenTrades() {
   int count = 0;
   for (int i = 0; i < OrdersTotal(); i++) {
      if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) {
         if (IsMyOrder() && (OrderType() == OP_BUY || OrderType() == OP_SELL)) {
            count++;
         }
      }
   }
   return count;
}

//+------------------------------------------------------------------+
//| Dapatkan nilai 1 pip untuk pair yang berbeda                     |
//+------------------------------------------------------------------+
double GetPipValue() {
   string symbol = Symbol();
   
   if (symbol == "XAUUSD" || symbol == "GOLD") {
      return 0.10;
   }
   
   if (symbol == "BTCUSD" || symbol == "BTC") {
      return 1.00;
   }
   
   if (StringFind(symbol, "JPY") >= 0) {
      return 0.01;
   }
   
   if (symbol == "GBPUSD" || symbol == "EURUSD" || symbol == "AUDUSD" || 
       symbol == "NZDUSD" || symbol == "USDCAD") {
      return 0.0001;
   }
   
   return Point * 10;
}

//+------------------------------------------------------------------+
//| Cari Swing High untuk SMC                                        |
//+------------------------------------------------------------------+
double FindSwingHighSMC(int period, int &swingBarIndex, double minDistancePips = 0) {
   double swingHigh = 0;
   swingBarIndex = -1;
   double pipValue = GetPipValue();
   
   for (int i = 2; i <= period; i++) {
      double high = iHigh(Symbol(), ADXSpikeTimeframe, i);
      double highPrev = iHigh(Symbol(), ADXSpikeTimeframe, i+1);
      double highNext = iHigh(Symbol(), ADXSpikeTimeframe, i-1);
      
      if (high > highPrev && high > highNext) {
         if (minDistancePips > 0 && swingHigh > 0) {
            double distancePips = (high - swingHigh) / pipValue;
            if (distancePips < minDistancePips) continue;
         }
         if (swingHigh == 0 || high > swingHigh) {
            swingHigh = high;
            swingBarIndex = i;
         }
      }
   }
   return swingHigh;
}

//+------------------------------------------------------------------+
//| Cari Swing Low untuk SMC                                         |
//+------------------------------------------------------------------+
double FindSwingLowSMC(int period, int &swingBarIndex, double minDistancePips = 0) {
   double swingLow = 0;
   swingBarIndex = -1;
   double pipValue = GetPipValue();
   
   for (int i = 2; i <= period; i++) {
      double low = iLow(Symbol(), ADXSpikeTimeframe, i);
      double lowPrev = iLow(Symbol(), ADXSpikeTimeframe, i+1);
      double lowNext = iLow(Symbol(), ADXSpikeTimeframe, i-1);
      
      if (low < lowPrev && low < lowNext) {
         if (minDistancePips > 0 && swingLow > 0) {
            double distancePips = (swingLow - low) / pipValue;
            if (distancePips < minDistancePips) continue;
         }
         if (swingLow == 0 || low < swingLow) {
            swingLow = low;
            swingBarIndex = i;
         }
      }
   }
   return swingLow;
}

//+------------------------------------------------------------------+
//| Update Market Structure (BOS / CHoCH)                            |
//+------------------------------------------------------------------+
void UpdateMarketStructure() {
   int swingBarHigh = -1, swingBarLow = -1;
   double newSwingHigh = FindSwingHighSMC(SMCSwingPeriod, swingBarHigh, SMCConfirmMinDistancePips);
   double newSwingLow = FindSwingLowSMC(SMCSwingPeriod, swingBarLow, SMCConfirmMinDistancePips);
   
   if (newSwingHigh == 0 || newSwingLow == 0) return;
   
   if (newSwingHigh > 0 && newSwingHigh != lastSwingHighSMC) {
      lastSwingHighSMC = newSwingHigh;
   }
   if (newSwingLow > 0 && newSwingLow != lastSwingLowSMC) {
      lastSwingLowSMC = newSwingLow;
   }
   
   if (currentStructure == "NEUTRAL" || currentStructure == "BULLISH") {
      if (newSwingHigh > higherHigh) {
         higherHigh = newSwingHigh;
         Print("SMC: Higher High baru di ", DoubleToString(higherHigh, Digits));
      }
      if (newSwingLow > higherLow) {
         higherLow = newSwingLow;
         Print("SMC: Higher Low baru di ", DoubleToString(higherLow, Digits));
      }
      
      if (higherLow > 0 && newSwingLow < higherLow) {
         Print("⚠️ SMC: CHoCH detected! Bullish -> Bearish (Higher Low broken)");
         currentStructure = "BEARISH";
         lastStructureChange = TimeCurrent();
         higherHigh = 0;
         higherLow = 0;
         lowerHigh = newSwingHigh;
         lowerLow = newSwingLow;
      }
   }
   
   if (currentStructure == "NEUTRAL" || currentStructure == "BEARISH") {
      if (newSwingLow < lowerLow || lowerLow == 0) {
         lowerLow = newSwingLow;
         Print("SMC: Lower Low baru di ", DoubleToString(lowerLow, Digits));
      }
      if (newSwingHigh < lowerHigh || lowerHigh == 0) {
         lowerHigh = newSwingHigh;
         Print("SMC: Lower High baru di ", DoubleToString(lowerHigh, Digits));
      }
      
      if (lowerHigh > 0 && newSwingHigh > lowerHigh) {
         Print("⚠️ SMC: CHoCH detected! Bearish -> Bullish (Lower High broken)");
         currentStructure = "BULLISH";
         lastStructureChange = TimeCurrent();
         higherHigh = newSwingHigh;
         higherLow = newSwingLow;
         lowerHigh = 0;
         lowerLow = 0;
      }
   }
   
   if (currentStructure == "BULLISH") {
      if (newSwingHigh > higherHigh) {
         Print("✅ SMC: Bullish BOS detected! (New Higher High)");
      }
   } else if (currentStructure == "BEARISH") {
      if (newSwingLow < lowerLow) {
         Print("✅ SMC: Bearish BOS detected! (New Lower Low)");
      }
   }
}

//+------------------------------------------------------------------+
//| Dapatkan sinyal SMC (BOS/CHoCH)                                  |
//+------------------------------------------------------------------+
int GetSMCSignal() {
   if (!UseSMCConfirm) return -1;
   
   UpdateMarketStructure();
   
   if (currentStructure == "NEUTRAL") {
      return -1;
   }
   
   if (RequireBOSConfirm) {
      if (currentStructure == "BULLISH") {
         int swingBar;
         double currentSwingHigh = FindSwingHighSMC(5, swingBar, 0);
         if (currentSwingHigh > higherHigh && higherHigh > 0) {
            Print("✅ SMC: Bullish BOS confirmed! Harga siap naik");
            return OP_BUY;
         }
      } else if (currentStructure == "BEARISH") {
         int swingBar;
         double currentSwingLow = FindSwingLowSMC(5, swingBar, 0);
         if (currentSwingLow < lowerLow && lowerLow > 0) {
            Print("✅ SMC: Bearish BOS confirmed! Harga siap turun");
            return OP_SELL;
         }
      }
   }
   
   if (AllowEntryOnCHoCH) {
      if (TimeCurrent() - lastStructureChange < 180) {
         if (currentStructure == "BULLISH") {
            Print("🔄 SMC: Bullish CHoCH detected! Potensi pembalikan ke atas");
            return OP_BUY;
         } else if (currentStructure == "BEARISH") {
            Print("🔄 SMC: Bearish CHoCH detected! Potensi pembalikan ke bawah");
            return OP_SELL;
         }
      }
   }
   
   return -1;
}

//+------------------------------------------------------------------+
//| Konfirmasi Stochastic (4 Mode)                                   |
//+------------------------------------------------------------------+
bool ConfirmStochastic(int entryDirection) {
   if(UseStochasticConfirm == STOC_OFF) return true;
   
   // Ambil nilai Stochastic current (bar 1) dan previous (bar 2)
   double mainNow = iStochastic(Symbol(), StochasticTimeframe, 
                                 StochasticKPeriod, StochasticDPeriod, StochasticSlowing,
                                 MODE_SMA, 0, MODE_MAIN, 1);
   double mainPrev = iStochastic(Symbol(), StochasticTimeframe,
                                 StochasticKPeriod, StochasticDPeriod, StochasticSlowing,
                                 MODE_SMA, 0, MODE_MAIN, 2);
   
   double signalNow = iStochastic(Symbol(), StochasticTimeframe,
                                  StochasticKPeriod, StochasticDPeriod, StochasticSlowing,
                                  MODE_SMA, 0, MODE_SIGNAL, 1);
   double signalPrev = iStochastic(Symbol(), StochasticTimeframe,
                                   StochasticKPeriod, StochasticDPeriod, StochasticSlowing,
                                   MODE_SMA, 0, MODE_SIGNAL, 2);
   
   if(mainNow == 0 || mainPrev == 0) return true; // data tidak tersedia
   
   bool confirm = false;
   
   // ===== MODE 1: EXIT OB/OS (Sederhana) =====
   if(UseStochasticConfirm == STOC_EXIT_OBOS) {
      if(entryDirection == OP_BUY) {
         // BUY: Stochastic tidak boleh di atas Overbought
         confirm = (mainNow <= OverboughtLevel);
         if(!confirm) Print("❌ Stoch EXIT OB/OS: overbought (", DoubleToString(mainNow,1), "), tolak BUY");
      } else {
         // SELL: Stochastic tidak boleh di bawah Oversold
         confirm = (mainNow >= OversoldLevel);
         if(!confirm) Print("❌ Stoch EXIT OB/OS: oversold (", DoubleToString(mainNow,1), "), tolak SELL");
      }
   }
   
   // ===== MODE 2: CROSS EXIT (Crossing %K dan %D keluar dari OB/OS) =====
   else if(UseStochasticConfirm == STOC_CROSS_EXIT) {
      if(entryDirection == OP_BUY) {
         // BUY: sebelumnya oversold, sekarang golden cross (%K > %D)
         bool wasOversold = (mainPrev < OversoldLevel && signalPrev < OversoldLevel);
         bool goldenCross = (mainNow > signalNow && mainPrev <= signalPrev);
         confirm = (wasOversold && goldenCross);
         if(!confirm) {
            if(!wasOversold) Print("❌ Stoch CROSS EXIT: sebelumnya tidak oversold (prev=", DoubleToString(mainPrev,1), ")");
            else Print("❌ Stoch CROSS EXIT: tidak terjadi golden cross");
         }
      } else {
         // SELL: sebelumnya overbought, sekarang dead cross (%K < %D)
         bool wasOverbought = (mainPrev > OverboughtLevel && signalPrev > OverboughtLevel);
         bool deadCross = (mainNow < signalNow && mainPrev >= signalPrev);
         confirm = (wasOverbought && deadCross);
         if(!confirm) {
            if(!wasOverbought) Print("❌ Stoch CROSS EXIT: sebelumnya tidak overbought (prev=", DoubleToString(mainPrev,1), ")");
            else Print("❌ Stoch CROSS EXIT: tidak terjadi dead cross");
         }
      }
   }
   
   // ===== MODE 3: CROSS EXTREME (DMI direction + Stochastic Crossing keluar OB/OS) =====
   else if(UseStochasticConfirm == STOC_CROSS_EXTREME) {
   // Ambil nilai DMI untuk cek arah (BUKAN hanya crossover)
   double diPlusNow = iADX(Symbol(), ADXSpikeTimeframe, ADXPeriod, PRICE_CLOSE, MODE_PLUSDI, 1);
   double diMinusNow = iADX(Symbol(), ADXSpikeTimeframe, ADXPeriod, PRICE_CLOSE, MODE_MINUSDI, 1);
   
   if(diPlusNow == 0 || diMinusNow == 0) return true;
   
   if(entryDirection == OP_BUY) {
      // BUY: DMI bullish (bukan hanya cross) + Stochastic oversold + golden cross
      bool dmiBullish = (diPlusNow > diMinusNow);  // ← DIUBAH: tidak wajib cross, cukup arah
      bool wasOversold = (mainPrev < OversoldLevel && signalPrev < OversoldLevel);
      bool goldenCross = (mainNow > signalNow && mainPrev <= signalPrev);
      confirm = (dmiBullish && wasOversold && goldenCross);
      if(!confirm) {
         Print("❌ Stoch CROSS EXTREME BUY: kondisi tidak terpenuhi");
         if(!dmiBullish) Print("   - DMI tidak bullish (", DoubleToString(diPlusNow,1), " < ", DoubleToString(diMinusNow,1), ")");
         if(!wasOversold) Print("   - Sebelumnya tidak oversold (prev=", DoubleToString(mainPrev,1), ")");
         if(!goldenCross) Print("   - Tidak terjadi golden cross");
      }
   } else {
      // SELL: DMI bearish (bukan hanya cross) + Stochastic overbought + dead cross
      bool dmiBearish = (diMinusNow > diPlusNow);  // ← DIUBAH: tidak wajib cross, cukup arah
      bool wasOverbought = (mainPrev > OverboughtLevel && signalPrev > OverboughtLevel);
      bool deadCross = (mainNow < signalNow && mainPrev >= signalPrev);
      confirm = (dmiBearish && wasOverbought && deadCross);
      if(!confirm) {
         Print("❌ Stoch CROSS EXTREME SELL: kondisi tidak terpenuhi");
         if(!dmiBearish) Print("   - DMI tidak bearish (", DoubleToString(diMinusNow,1), " < ", DoubleToString(diPlusNow,1), ")");
         if(!wasOverbought) Print("   - Sebelumnya tidak overbought (prev=", DoubleToString(mainPrev,1), ")");
         if(!deadCross) Print("   - Tidak terjadi dead cross");
         }
      }
   }
   
   return confirm;
}

//+------------------------------------------------------------------+
//| Cek apakah ADX mengalami lonjakan (spike) dan arah DMI          |
//+------------------------------------------------------------------+
bool IsADXSpike(int &dmiDirection, bool &isReversalSignal) {
   double adxNow  = iADX(Symbol(), ADXSpikeTimeframe, ADXPeriod, PRICE_CLOSE, MODE_MAIN, 1);
   double adxPrev = iADX(Symbol(), ADXSpikeTimeframe, ADXPeriod, PRICE_CLOSE, MODE_MAIN, 1 + ADXSpikePeriod);
   
   if (adxNow == 0 || adxPrev == 0) return false;
   
   // Cek ADX minimal
   if (adxNow < ADXMinLevel) return false;
   
   double increase = adxNow - adxPrev;
   double percentIncrease = (increase / adxPrev) * 100.0;
   
   bool spike = false;
   if (ADXSpikeMinIncrease > 0 && increase >= ADXSpikeMinIncrease)
      spike = true;
   if (ADXSpikeMinPercentIncrease > 0 && percentIncrease >= ADXSpikeMinPercentIncrease)
      spike = true;
   
   if (!spike) return false;
   
   // Ambil nilai DMI
   double diPlusNow = iADX(Symbol(), ADXSpikeTimeframe, ADXPeriod, PRICE_CLOSE, MODE_PLUSDI, 1);
   double diMinusNow = iADX(Symbol(), ADXSpikeTimeframe, ADXPeriod, PRICE_CLOSE, MODE_MINUSDI, 1);
   double diPlusPrev = iADX(Symbol(), ADXSpikeTimeframe, ADXPeriod, PRICE_CLOSE, MODE_PLUSDI, 2);
   double diMinusPrev = iADX(Symbol(), ADXSpikeTimeframe, ADXPeriod, PRICE_CLOSE, MODE_MINUSDI, 2);
   
   isReversalSignal = false;
   
   // ===== TREND MODE =====
   if (ADXEntryMode == ADX_TREND_MODE) {
      if (diPlusNow > diMinusNow) dmiDirection = OP_BUY;
      else if (diMinusNow > diPlusNow) dmiDirection = OP_SELL;
      else dmiDirection = -1;
      
      Print("ADX Spike (TREND MODE): ADX=", DoubleToString(adxNow,1),
            " | +DI=", DoubleToString(diPlusNow,1),
            " | -DI=", DoubleToString(diMinusNow,1),
            " | Direction: ", (dmiDirection == OP_BUY ? "BUY" : dmiDirection == OP_SELL ? "SELL" : "NEUTRAL"));
   }
   
   // ===== REVERSAL MODE =====
   else if (ADXEntryMode == ADX_REVERSAL_MODE) {
      // Deteksi crossover
      bool bullishCrossover = (diPlusNow > diMinusNow && diPlusPrev <= diMinusPrev);
      bool bearishCrossover = (diMinusNow > diPlusNow && diMinusPrev <= diPlusPrev);
      
      // Cek kondisi sideway di timeframe entry
      bool isSideway = (adxNow < 30);
      
      if (bullishCrossover && isSideway) {
         dmiDirection = OP_BUY;
         isReversalSignal = true;
         Print("🔁 ADX Spike (REVERSAL MODE - BULLISH CROSSOVER): ADX=", DoubleToString(adxNow,1),
               " | +DI: ", DoubleToString(diPlusPrev,1), "->", DoubleToString(diPlusNow,1),
               " | -DI: ", DoubleToString(diMinusPrev,1), "->", DoubleToString(diMinusNow,1));
      }
      else if (bearishCrossover && isSideway) {
         dmiDirection = OP_SELL;
         isReversalSignal = true;
         Print("🔁 ADX Spike (REVERSAL MODE - BEARISH CROSSOVER): ADX=", DoubleToString(adxNow,1),
               " | +DI: ", DoubleToString(diPlusPrev,1), "->", DoubleToString(diPlusNow,1),
               " | -DI: ", DoubleToString(diMinusPrev,1), "->", DoubleToString(diMinusNow,1));
      }
      else {
         dmiDirection = -1;
         if (!isSideway) {
            Print("ADX Spike detected but IGNORED (REVERSAL MODE): ADX too high (", 
                  DoubleToString(adxNow,1), " >= 30) - Market trending, not sideway");
         }
      }
   }
   
   return (dmiDirection != -1);
}

//+------------------------------------------------------------------+
//| Cek Konfirmasi dari Higher Timeframe (Support Reversal Mode)     |
//+------------------------------------------------------------------+
bool CheckHTFConfirmation(int entryDirection, bool isReversalMode = false) {
   if (HTFConfirmMode == HTF_CONFIRM_OFF) return true;
   
   // Ambil nilai ADX dan DMI dari HTF
   double htfADX = iADX(Symbol(), HTFTimeframe, ADXPeriod, PRICE_CLOSE, MODE_MAIN, 1);
   double htfDIplus = iADX(Symbol(), HTFTimeframe, ADXPeriod, PRICE_CLOSE, MODE_PLUSDI, 1);
   double htfDIminus = iADX(Symbol(), HTFTimeframe, ADXPeriod, PRICE_CLOSE, MODE_MINUSDI, 1);
   
   if (htfADX == 0) return true; // Data tidak tersedia
   
   // ===== MODE REVERSAL: Cek kondisi sideway di HTF =====
   if (isReversalMode && HTFReversalRequireSideway) {
      bool htfSideway = (htfADX < 30); // ADX < 30 = sideway
      if (!htfSideway) {
         Print("❌ REVERSAL MODE: HTF sedang TRENDING (ADX=", DoubleToString(htfADX,1), 
               "), tidak ideal untuk reversal. Entry ditolak.");
         return false;
      }
      Print("✅ REVERSAL MODE: HTF SIDEWAY (ADX=", DoubleToString(htfADX,1), "), siap untuk reversal");
   }
   
   // ===== KONFIRMASI BERDASARKAN MODE =====
   
   // Mode 1: Konfirmasi arah tren dari HTF (DMI)
   if (HTFConfirmMode == HTF_CONFIRM_TREND) {
      int htfDirection = -1;
      if (htfDIplus > htfDIminus) htfDirection = OP_BUY;
      else if (htfDIminus > htfDIplus) htfDirection = OP_SELL;
      
      if (htfDirection == -1) {
         Print("⚠️ HTF Confirmation: DMI netral di ", EnumToString(HTFTimeframe));
         return false;
      }
      
      if (HTFRequireSameDirection && htfDirection != entryDirection) {
         Print("❌ HTF Confirmation FAILED: HTF arah ", (htfDirection == OP_BUY ? "BUY" : "SELL"),
               " vs Entry arah ", (entryDirection == OP_BUY ? "BUY" : "SELL"));
         return false;
      }
      
      Print("✅ HTF TREND Confirmation: HTF (", EnumToString(HTFTimeframe), ") arah ",
            (htfDirection == OP_BUY ? "BUY" : "SELL"),
            " | ADX=", DoubleToString(htfADX,1));
      return true;
   }
   
   // Mode 2: Konfirmasi ADX level minimum dari HTF
   if (HTFConfirmMode == HTF_CONFIRM_ADX_LEVEL) {
      if (htfADX < HTFMinADXLevel) {
         Print("❌ HTF ADX Confirmation FAILED: HTF ADX = ", DoubleToString(htfADX,1),
               " < ", DoubleToString(HTFMinADXLevel,1));
         return false;
      }
      
      Print("✅ HTF ADX Confirmation: HTF ADX = ", DoubleToString(htfADX,1),
            " >= ", DoubleToString(HTFMinADXLevel,1));
      return true;
   }
   
   return true;
}

//+------------------------------------------------------------------+
//| Cek ADX Spike sebagai mode entry standalone                      |
//+------------------------------------------------------------------+
bool CheckADXSpikeEntry(int &signalDirection) {
   // CEK COOLDOWN
   if (adxSpikeLastSignalTime > 0) {
      int elapsedMinutes = (int)((TimeCurrent() - adxSpikeLastSignalTime) / 60);
      if (elapsedMinutes < ADXSpikeCooldownMinutes) return false;
   }
   
   int dmiDir = -1;
   bool isReversalSignal = false;
   
   if (IsADXSpike(dmiDir, isReversalSignal) && dmiDir != -1) {
      
      // Konfirmasi SMC
      bool smcConfirmOK = true;
      if (UseSMCConfirm) {
         int smcSignal = GetSMCSignal();
         if (smcSignal != dmiDir) {
            smcConfirmOK = false;
            Print("ADX Spike: Konfirmasi SMC gagal");
         }
      }
      
      if (smcConfirmOK) {
         // ===== STOCHASTIC CONFIRMATION (4 MODE) =====
         if (!ConfirmStochastic(dmiDir)) {
            Print("❌ ADX Spike: Entry ditolak karena Stochastic tidak sesuai");
            return false;
         }
         
         // Konfirmasi HTF
         if (!CheckHTFConfirmation(dmiDir, isReversalSignal)) {
            Print("❌ ADX Spike: Entry ditolak karena HTF konfirmasi gagal");
            return false;
         }
         
         signalDirection = dmiDir;
         adxSpikeLastSignalTime = TimeCurrent();
         adxSpikeEntryExecuted = true;
         
         Print("✅ ADX SPIKE ENTRY: ", (signalDirection == OP_BUY ? "BUY" : "SELL"),
               (isReversalSignal ? " (REVERSAL MODE)" : " (TREND MODE)"),
               " | Stochastic confirmed (Mode: ", 
               UseStochasticConfirm == STOC_EXIT_OBOS ? "EXIT OB/OS" :
               UseStochasticConfirm == STOC_CROSS_EXIT ? "CROSS EXIT" :
               UseStochasticConfirm == STOC_CROSS_EXTREME ? "CROSS EXTREME" : "OFF", ")");
         return true;
      }
   }
   
   return false;
}

//+------------------------------------------------------------------+
//| Reset ADX Spike State (panggil saat posisi ditutup)              |
//+------------------------------------------------------------------+
void ResetADXSpikeState() {
   adxSpikeEntryExecuted = false;
   // Jangan reset last signal time, cooldown tetap berjalan
   Print("ADX Spike: State reset (siap untuk sinyal berikutnya)");
}

//+------------------------------------------------------------------+
//| Close All Trades                                                 |
//+------------------------------------------------------------------+
void CloseAllTrades() {
   int totalOrders = OrdersTotal();
   int closedCount = 0;
   
   Print("===== CLOSE ALL TRADES TRIGGERED =====");
   Print("Symbol: ", Symbol(), " Magic: ", MagicNumber);
   
   for (int i = totalOrders - 1; i >= 0; i--) {
      if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) {
         if (IsMyOrder()) {
            int orderType = OrderType();
            if (orderType == OP_BUY || orderType == OP_SELL) {
               RefreshRates();
               double closePrice = (orderType == OP_BUY) ? Bid : Ask;
               
               bool closed = OrderClose(OrderTicket(), OrderLots(), closePrice, 
                                       (int)slippage, clrNONE);
               
               if (closed) {
                  closedCount++;
                  Print("Order #", OrderTicket(), " closed");
                  Sleep(200);
               } else {
                  int error = GetLastError();
                  Print("Gagal close order #", OrderTicket(), " Error: ", error);
               }
            }
         }
      }
   }
   
   if (closedCount > 0) {
      Print("Closed ", closedCount, " orders");
      ResetADXSpikeState();
   }
}

//+------------------------------------------------------------------+
//| Close Position and Open New Opposite                            |
//+------------------------------------------------------------------+
void CloseAndReverse(int newDirection) {
   CloseAllTrades();
   Sleep(500);
   RefreshRates();
   
   if (newDirection == OP_BUY) {
      Print("🔄 Reverse: Menutup posisi dan membuka BUY baru");
      ExecuteInitialEntry(OP_BUY);
   } else if (newDirection == OP_SELL) {
      Print("🔄 Reverse: Menutup posisi dan membuka SELL baru");
      ExecuteInitialEntry(OP_SELL);
   }
}

//+------------------------------------------------------------------+
//| Equity Stop berdasarkan floating profit per pair                |
//+------------------------------------------------------------------+
void CheckEquityStop() {
   if (!UseEquityStop || equityStopTriggered) return;
   
   double currentFloating = GetPairFloatingProfit();
   double floatingLoss = (currentFloating < 0) ? -currentFloating : 0;
   
   bool trigger = false;
   
   if (EquityStopType == FIXED_USD_AMOUNT) {
      if (floatingLoss >= TotalEquityRisk) trigger = true;
   }
   else {
      double drawdownPercent = (floatingLoss / initialAccountBalance) * 100.0;
      if (drawdownPercent >= TotalEquityRisk) trigger = true;
   }
   
   if (trigger) {
      Print("=== EQUITY STOP TRIGGERED for ", Symbol(), "! ===");
      Alert("🚫 EQUITY STOP ACTIVATED on ", Symbol());
      CloseAllTrades();
      equityStopTriggered = true;
      stopTriggeredTime = TimeCurrent();
   }
}

//+------------------------------------------------------------------+
//| Hitung Stop Loss dan Take Profit berdasarkan mode yang dipilih   |
//+------------------------------------------------------------------+
void CalculateSLTP(double entryPrice, int direction, double &stopLoss, double &takeProfit) {
   double pipValue = GetPipValue();
   double riskPips = 0;
   double rewardPips = 0;
   
   if (SLTPUnit == SLTP_IN_PIPS) {
      riskPips = StopLossPips;
   } else {
      double lotSize = CalculateLotSize();
      if (lotSize > 0) {
         double dollarPerPip = lotSize * pipValue;
         if (dollarPerPip > 0) {
            riskPips = StopLossDollar / dollarPerPip;
            Print("Konversi $", StopLossDollar, " → ", DoubleToString(riskPips, 1), " pips (lot=", lotSize, ")");
         }
      } else {
         riskPips = StopLossPips;
      }
   }
   
   if (SLTPMode == SLTP_BY_PIPS) {
      rewardPips = TakeProfitPips;
   } else {
      rewardPips = riskPips * RiskRewardRatio;
   }
   
   if (direction == OP_BUY) {
      stopLoss = entryPrice - (riskPips * pipValue);
      takeProfit = entryPrice + (rewardPips * pipValue);
   } else if (direction == OP_SELL) {
      stopLoss = entryPrice + (riskPips * pipValue);
      takeProfit = entryPrice - (rewardPips * pipValue);
   }
   
   stopLoss = NormalizeDouble(stopLoss, Digits);
   takeProfit = NormalizeDouble(takeProfit, Digits);
   
   Print("SL/TP Calculation (Unit: ", (SLTPUnit == SLTP_IN_PIPS ? "PIPS" : "DOLLAR"), 
         ", Mode: ", (SLTPMode == SLTP_BY_PIPS ? "PIPS" : "RR"), "):");
   Print("  Entry: ", DoubleToString(entryPrice, Digits));
   Print("  Risk: ", DoubleToString(riskPips, 1), " pips");
   Print("  SL: ", DoubleToString(stopLoss, Digits));
   Print("  TP: ", DoubleToString(takeProfit, Digits));
}

//+------------------------------------------------------------------+
//| Apply Break Even jika profit sudah mencapai target               |
//+------------------------------------------------------------------+
void ApplyBreakEven() {
   if (!UseBreakEven) return;
   
   for (int i = 0; i < OrdersTotal(); i++) {
      if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) {
         if (IsMyOrder() && (OrderType() == OP_BUY || OrderType() == OP_SELL)) {
            double pipValue = GetPipValue();
            double currentPrice = (OrderType() == OP_BUY) ? Bid : Ask;
            double profitPips = 0;
            
            if (OrderType() == OP_BUY) {
               profitPips = (currentPrice - OrderOpenPrice()) / pipValue;
            } else {
               profitPips = (OrderOpenPrice() - currentPrice) / pipValue;
            }
            
            if (profitPips >= BreakEvenPips) {
               double newSL = OrderOpenPrice();
               
               if (MathAbs(OrderStopLoss() - newSL) > pipValue / 10) {
                  bool modified = OrderModify(OrderTicket(), OrderOpenPrice(), newSL, OrderTakeProfit(), 0, clrNONE);
                  if (modified) {
                     Print("✅ Break Even applied for order #", OrderTicket(), 
                           " (profit: ", DoubleToString(profitPips, 1), " pips)");
                  } else {
                     Print("❌ Break Even failed for order #", OrderTicket(), 
                           " Error: ", GetLastError());
                  }
               }
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Apply Trailing Stop                                              |
//+------------------------------------------------------------------+
void ApplyTrailingStop() {
   isTrailingActive = false;
   trailingStatus = "";
   
   static double trailHighBuy = 0;
   static double trailLowSell = 0;
   static bool trailActiveBuy = false;
   static bool trailActiveSell = false;
   
   bool hasBuy = false, hasSell = false;
   double highestBid = 0, lowestAsk = 0;
   
   for (int i = 0; i < OrdersTotal(); i++) {
      if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) {
         if (IsMyOrder()) {
            if (OrderType() == OP_BUY) {
               hasBuy = true;
               if (Bid > highestBid) highestBid = Bid;
            }
            if (OrderType() == OP_SELL) {
               hasSell = true;
               if (Ask < lowestAsk || lowestAsk == 0) lowestAsk = Ask;
            }
         }
      }
   }
   
   if (!hasBuy) {
      trailActiveBuy = false;
      trailHighBuy = 0;
   }
   if (!hasSell) {
      trailActiveSell = false;
      trailLowSell = 0;
   }
   
   if (!hasBuy && !hasSell) {
      trailingStatus = "No Position";
      return;
   }
   
   double pipValue = GetPipValue();
   double activationDist = TrailingActivationPips * pipValue;
   double stepDist = TrailingStepPips * pipValue;
   
   // ========== TRAILING UNTUK BUY ==========
   if (hasBuy) {
      double totalLotsBuy = 0, sumPriceBuy = 0;
      for (int i = 0; i < OrdersTotal(); i++) {
         if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES) && IsMyOrder() && OrderType() == OP_BUY) {
            totalLotsBuy += OrderLots();
            sumPriceBuy += OrderOpenPrice() * OrderLots();
         }
      }
      double avgEntryBuy = (totalLotsBuy > 0) ? sumPriceBuy / totalLotsBuy : 0;
      
      if (!trailActiveBuy) {
         double profitPips = (highestBid - avgEntryBuy) / pipValue;
         if (profitPips >= TrailingActivationPips) {
            trailActiveBuy = true;
            trailHighBuy = highestBid;
            Print("🚀 TRAILING BUY AKTIF pada ", profitPips, " pips!");
            
            for (int i = 0; i < OrdersTotal(); i++) {
               if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES) && IsMyOrder() && OrderType() == OP_BUY) {
                  if (OrderStopLoss() < avgEntryBuy - pipValue/10) {
                     bool modified = OrderModify(OrderTicket(), OrderOpenPrice(), avgEntryBuy, OrderTakeProfit(), 0, clrNONE);
                     if (!modified) {
                        Print("❌ Gagal set BE buy #", OrderTicket(), " Error: ", GetLastError());
                     }
                  }
               }
            }
         }
      }
      
      if (trailActiveBuy) {
         if (Bid > trailHighBuy) {
            trailHighBuy = Bid;
         }
         double newSL = trailHighBuy - stepDist;
         for (int i = 0; i < OrdersTotal(); i++) {
            if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES) && IsMyOrder() && OrderType() == OP_BUY) {
               if (OrderStopLoss() < newSL - pipValue/10) {
                  bool modified = OrderModify(OrderTicket(), OrderOpenPrice(), newSL, OrderTakeProfit(), 0, clrNONE);
                  if (!modified) {
                     Print("❌ Gagal trailing buy #", OrderTicket(), " Error: ", GetLastError());
                  } else {
                     isTrailingActive = true;
                     trailingStatus = "Active (" + IntegerToString(TrailingActivationPips) + "/" + IntegerToString(TrailingStepPips) + ")";
                  }
               }
            }
         }
      } else {
         double profitPips = (highestBid - avgEntryBuy) / pipValue;
         trailingStatus = "Waiting (" + DoubleToString(profitPips, 1) + "/" + IntegerToString(TrailingActivationPips) + " pips)";
      }
   }
   
   // ========== TRAILING UNTUK SELL ==========
   if (hasSell) {
      double totalLotsSell = 0, sumPriceSell = 0;
      for (int i = 0; i < OrdersTotal(); i++) {
         if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES) && IsMyOrder() && OrderType() == OP_SELL) {
            totalLotsSell += OrderLots();
            sumPriceSell += OrderOpenPrice() * OrderLots();
         }
      }
      double avgEntrySell = (totalLotsSell > 0) ? sumPriceSell / totalLotsSell : 0;
      
      if (!trailActiveSell) {
         double profitPips = (avgEntrySell - lowestAsk) / pipValue;
         if (profitPips >= TrailingActivationPips) {
            trailActiveSell = true;
            trailLowSell = lowestAsk;
            Print("🚀 TRAILING SELL AKTIF pada ", profitPips, " pips!");
            
            for (int i = 0; i < OrdersTotal(); i++) {
               if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES) && IsMyOrder() && OrderType() == OP_SELL) {
                  if (OrderStopLoss() > avgEntrySell + pipValue/10 || OrderStopLoss() == 0) {
                     bool modified = OrderModify(OrderTicket(), OrderOpenPrice(), avgEntrySell, OrderTakeProfit(), 0, clrNONE);
                     if (!modified) {
                        Print("❌ Gagal set BE sell #", OrderTicket(), " Error: ", GetLastError());
                     }
                  }
               }
            }
         }
      }
      
      if (trailActiveSell) {
         if (Ask < trailLowSell) {
            trailLowSell = Ask;
         }
         double newSL = trailLowSell + stepDist;
         for (int i = 0; i < OrdersTotal(); i++) {
            if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES) && IsMyOrder() && OrderType() == OP_SELL) {
               if (OrderStopLoss() > newSL + pipValue/10 || OrderStopLoss() == 0) {
                  bool modified = OrderModify(OrderTicket(), OrderOpenPrice(), newSL, OrderTakeProfit(), 0, clrNONE);
                  if (!modified) {
                     Print("❌ Gagal trailing sell #", OrderTicket(), " Error: ", GetLastError());
                  } else {
                     isTrailingActive = true;
                     trailingStatus = "Active (" + IntegerToString(TrailingActivationPips) + "/" + IntegerToString(TrailingStepPips) + ")";
                  }
               }
            }
         }
      } else {
         double profitPips = (avgEntrySell - lowestAsk) / pipValue;
         trailingStatus = "Waiting (" + DoubleToString(profitPips, 1) + "/" + IntegerToString(TrailingActivationPips) + " pips)";
      }
   }
}

//+------------------------------------------------------------------+
//| Calculate Lot Size                                               |
//+------------------------------------------------------------------+
double CalculateLotSize() {
   double calculatedLot = baseLotSize;
   
   if (LotCalculationMode == FIXED_LOT) {
      calculatedLot = baseLotSize;
   }
   else if (LotCalculationMode == SCALING_LOT) {
      calculatedLot = baseLotSize;
   }
   
   return NormalizeDouble(calculatedLot, 2);
}

bool CheckEntryConditions() {
   if (!IsTradingTime()) return false;
   
   double currentSpread = (Ask - Bid) / Point;
   if (currentSpread > MaxAllowedSpread) return false;
   
   if (UseNewsFilter && isIncomingNews) return false;
   if (equityStopTriggered) return false;
   
   if (Use_Daily_Target) {
      double dailyPL = CalculateDailyTotalProfit();
      if (dailyPL >= Daily_Target) return false;
   }
      
   return true;
}

//+------------------------------------------------------------------+
//| Trading Time Check                                               |
//+------------------------------------------------------------------+
bool IsTradingTime() {
   int currentHour = Hour();
   int currentDay = DayOfWeek();
   
   if (currentDay == 4 && !TradeOnThursday) return false;
   if (currentDay == 5 && !TradeOnFriday) return false;
   if (currentDay == 4 && currentHour > Thursday_Hour) return false;
   if (currentDay == 5 && currentHour > Friday_Hour) return false;
   
   if (currentDay == 6 && !TradeOnSaturday) return false;
   if (currentDay == 0 && !TradeOnSunday) return false;
   if (currentDay == 6 && currentHour > Saturday_Hour) return false;
   if (currentDay == 0 && currentHour > Sunday_Hour) return false;
   
   if (Open_Hour < Close_Hour) {
      if (currentHour < Open_Hour || currentHour >= Close_Hour) return false;
   } else {
      if (currentHour < Open_Hour && currentHour >= Close_Hour) return false;
   }
   
   return true;
}

//+------------------------------------------------------------------+
//| Send Order Function dengan SL dan TP                             |
//+------------------------------------------------------------------+
int SendOrder(int orderType, double lotSize, string comment = "") {
   int ticket = -1;
   double stopLoss = 0;
   double takeProfit = 0;
   
   lotSize = NormalizeDouble(lotSize, 2);
   
   RefreshRates();
   double entryPrice = (orderType == OP_BUY) ? Ask : Bid;
   CalculateSLTP(entryPrice, orderType, stopLoss, takeProfit);
   
   for(int attempt = 0; attempt < 3; attempt++) {
      RefreshRates();
      
      if (orderType == OP_BUY) {
         ticket = OrderSend(Symbol(), OP_BUY, lotSize, Ask, (int)slippage, 
                           stopLoss, takeProfit, comment, MagicNumber, 0, clrGreen);
      } else if (orderType == OP_SELL) {
         ticket = OrderSend(Symbol(), OP_SELL, lotSize, Bid, (int)slippage, 
                           stopLoss, takeProfit, comment, MagicNumber, 0, clrRed);
      }
      
      if (ticket > 0) {
         Print("Order #", ticket, " opened: ", 
               (orderType == OP_BUY ? "BUY" : "SELL"),
               " Lot: ", lotSize,
               " SL: ", DoubleToString(stopLoss, Digits),
               " TP: ", DoubleToString(takeProfit, Digits));
         break;
      } else {
         int error = GetLastError();
         Print("OrderSend failed (attempt ", attempt+1, "). Error: ", error);
         if (error == 138 || error == 136) {
            Sleep(1000);
            continue;
         }
         break;
      }
   }
   
   return ticket;
}

//+------------------------------------------------------------------+
//| Execute Initial Entry                                            |
//+------------------------------------------------------------------+
void ExecuteInitialEntry(int entryDirection) {
   double lotSize = CalculateLotSize();
   string comment = "ADX Spike " + (entryDirection == OP_BUY ? "BUY" : "SELL");
   
   int ticket = SendOrder(entryDirection, lotSize, comment);
   if (ticket > 0) {
      if (entryDirection == OP_BUY) {
         LastBuyOpenPrice = OrderOpenPrice();
      } else {
         LastSellOpenPrice = OrderOpenPrice();
      }
      lastTradeTime = TimeCurrent();
      I_b_16 = true;
   }
}

//+------------------------------------------------------------------+
//| Check Daily Reset                                                |
//+------------------------------------------------------------------+
void CheckDailyReset() {
   datetime currentTime = TimeCurrent();
   int currentHour = TimeHour(currentTime);
   
   if (currentHour == DailyResetHour && !dailyResetPerformed) {
      ResetTradingState();
      dailyResetPerformed = true;
      lastResetTime = currentTime;
   }
   
   if (currentHour != DailyResetHour) {
      dailyResetPerformed = false;
   }
}

//+------------------------------------------------------------------+
//| Check Auto Reset                                                 |
//+------------------------------------------------------------------+
void CheckAutoReset() {
   if (!equityStopTriggered) return;
   
   if (stopTriggeredTime == 0) stopTriggeredTime = TimeCurrent();
   
   int elapsedSeconds = (int)(TimeCurrent() - stopTriggeredTime);
   remainingCooldown = 60 - elapsedSeconds;
   
   if (remainingCooldown < 0) remainingCooldown = 0;
   
   if (elapsedSeconds >= 60) {
      ResetTradingState();
      stopTriggeredTime = 0;
      remainingCooldown = 0;
   }
}

//+------------------------------------------------------------------+
//| Reset Trading State                                              |
//+------------------------------------------------------------------+
void ResetTradingState() {
   OrderCycleState = 0;
   IsEntryAllowed = false;
   HasBuyPosition = false;
   HasSellPosition = false;
   
   if (equityStopTriggered) {
      equityStopTriggered = false;
      highestEquity = AccountEquity();
   }
}

//+------------------------------------------------------------------+
//| Check Active Positions                                           |
//+------------------------------------------------------------------+
void CheckActivePositions() {
   HasBuyPosition = false;
   HasSellPosition = false;
   LastBuyOpenPrice = 0;
   LastSellOpenPrice = 0;
   double totalBuyLots = 0, totalSellLots = 0;
   double sumBuyPrice = 0, sumSellPrice = 0;
   
   for (int i = 0; i < OrdersTotal(); i++) {
      if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) {
         if (IsMyOrder()) {
            if (OrderType() == OP_BUY) {
               HasBuyPosition = true;
               totalBuyLots += OrderLots();
               sumBuyPrice += OrderOpenPrice() * OrderLots();
            }
            if (OrderType() == OP_SELL) {
               HasSellPosition = true;
               totalSellLots += OrderLots();
               sumSellPrice += OrderOpenPrice() * OrderLots();
            }
         }
      }
   }
   
   if (totalBuyLots > 0) LastBuyOpenPrice = sumBuyPrice / totalBuyLots;
   if (totalSellLots > 0) LastSellOpenPrice = sumSellPrice / totalSellLots;
}

//+------------------------------------------------------------------+
//| Calculate Daily Realized Profit                                  |
//+------------------------------------------------------------------+
double CalculateDailyRealizedProfit() {
   double realizedProfit = 0;
   
   MqlDateTime today;
   TimeCurrent(today);
   today.hour = 0;
   today.min = 0;
   today.sec = 0;
   datetime dayStart = StructToTime(today);
   
   int totalHistory = OrdersHistoryTotal();
   for (int i = totalHistory - 1; i >= 0; i--) {
      if (OrderSelect(i, SELECT_BY_POS, MODE_HISTORY)) {
         if (OrderMagicNumber() == MagicNumber && OrderSymbol() == Symbol()) {
            if (OrderCloseTime() >= dayStart) {
               realizedProfit += OrderProfit() + OrderSwap() + OrderCommission();
            }
         }
      }
   }
   
   return realizedProfit;
}

//+------------------------------------------------------------------+
//| Calculate Daily Floating Profit                                  |
//+------------------------------------------------------------------+
double CalculateDailyFloatingProfit() {
   double floatingProfit = 0;
   
   for (int i = 0; i < OrdersTotal(); i++) {
      if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) {
         if (OrderMagicNumber() == MagicNumber && OrderSymbol() == Symbol()) {
            floatingProfit += OrderProfit() + OrderSwap() + OrderCommission();
         }
      }
   }
   
   return floatingProfit;
}

//+------------------------------------------------------------------+
//| Calculate Daily Total Profit                                     |
//+------------------------------------------------------------------+
double CalculateDailyTotalProfit() {
   return CalculateDailyRealizedProfit() + CalculateDailyFloatingProfit();
}

//+------------------------------------------------------------------+
//| Fungsi String Helper                                             |
//+------------------------------------------------------------------+
string Trim(string s) {
   int len = StringLen(s);
   while(len > 0 && StringGetChar(s, len-1) <= 32) len--;
   int start = 0;
   while(start < len && StringGetChar(s, start) <= 32) start++;
   return StringSubstr(s, start, len - start);
}

string ToUpper(string s) {
   string result = "";
   int len = StringLen(s);
   for(int i = 0; i < len; i++) {
      int ch = StringGetChar(s, i);
      if(ch >= 'a' && ch <= 'z') ch -= 32;
      result += CharToString((uchar)ch);
   }
   return result;
}

string FormatCountdown(int seconds) {
   if (seconds < 0) return "0s";
   int hours = seconds / 3600;
   int mins = (seconds % 3600) / 60;
   int secs = seconds % 60;
   if (hours > 0) {
      return IntegerToString(hours) + "j " + IntegerToString(mins) + "m";
   } else if (mins > 0) {
      return IntegerToString(mins) + "m " + IntegerToString(secs) + "d";
   } else {
      return IntegerToString(secs) + "d";
   }
}

//+------------------------------------------------------------------+
//| Konversi Jam Server ke WIB                                       |
//+------------------------------------------------------------------+
string GetTradingHoursInWIB() {
   int brokerOffset = 0;
   if (ManualBrokerOffset != 0) {
      brokerOffset = ManualBrokerOffset;
   } else {
      datetime gmtTime = TimeGMT();
      brokerOffset = (int)((TimeCurrent() - gmtTime) / 3600);
   }
   
   int wibOffset = 7;
   int diffToWIB = wibOffset - brokerOffset;
   
   int openHourWIB = Open_Hour + diffToWIB;
   int closeHourWIB = Close_Hour + diffToWIB;
   
   openHourWIB = (openHourWIB + 24) % 24;
   closeHourWIB = (closeHourWIB + 24) % 24;
   
   string openStr = StringFormat("%02d:00", openHourWIB);
   string closeStr = StringFormat("%02d:00", closeHourWIB);
   
   return "(" + openStr + "-" + closeStr + " WIB)";
}

//+------------------------------------------------------------------+
//| Download XML dari ForexFactory                                   |
//+------------------------------------------------------------------+
void DownloadXML() {
   string url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml";
   char post[];
   char result[];
   string headers = "";
   string cookie = "";
   string referer = "";
   int data_size = 0;
   int timeout = 5000;
   
   int res = WebRequest("GET", url, cookie, referer, timeout, post, data_size, result, headers);
   if(res == -1){
      Print("❌ WebRequest gagal. Error: ", GetLastError(), " – Izinkan URL di Tools > Options > Expert Advisors.");
      return;
   }
   
   string xml = CharArrayToString(result);
   Print("📥 XML diterima, panjang: ", StringLen(xml));
   
   int file = FileOpen("forex_news.xml", FILE_WRITE | FILE_TXT);
   if(file < 0){
      Print("❌ Gagal membuka file untuk tulis.");
      return;
   }
   
   FileWrite(file, xml);
   FileClose(file);
   Print("✅ File forex_news.xml berhasil disimpan.");
   lastDownloadNews = TimeCurrent();
}

//+------------------------------------------------------------------+
//| Extract XML Tag Value                                            |
//+------------------------------------------------------------------+
string GetXmlTagValue(string xml, string tag) {
   string openTag = "<" + tag + ">";
   string closeTag = "</" + tag + ">";
   int start = StringFind(xml, openTag);
   int end = StringFind(xml, closeTag, start);
   
   if(start < 0 || end < 0) return "";
      
   start += StringLen(openTag);
   string value = StringSubstr(xml, start, end - start);
   
   string cdataOpen = "<![CDATA[";
   string cdataClose = "]]>";
   if(StringFind(value, cdataOpen) == 0) {
      value = StringSubstr(value, StringLen(cdataOpen));
      int cdataEnd = StringFind(value, cdataClose);
      if(cdataEnd >= 0) value = StringSubstr(value, 0, cdataEnd);
   }
   
   return value;
}

//+------------------------------------------------------------------+
//| Konversi Tanggal & Waktu ke Datetime                             |
//+------------------------------------------------------------------+
datetime ConvertNewsDateTime(string dateStr, string timeStr) {
   int y, m, d, h, min;
   string ampm = "";

   dateStr = Trim(dateStr);
   timeStr = Trim(timeStr);

   if(StringFind(dateStr, "-") > 0) {
      string dateParts[];
      int count = StringSplit(dateStr, '-', dateParts);
      if(count == 3) {
         if(StringLen(dateParts[0]) == 4) {
            y = (int)StringToInteger(dateParts[0]);
            m = (int)StringToInteger(dateParts[1]);
            d = (int)StringToInteger(dateParts[2]);
         } else {
            m = (int)StringToInteger(dateParts[0]);
            d = (int)StringToInteger(dateParts[1]);
            y = (int)StringToInteger(dateParts[2]);
         }
      } else return 0;
   } else return 0;

   string t = Trim(timeStr);
   if(StringLen(t) > 2) {
      string suffix = StringSubstr(t, StringLen(t)-2, 2);
      ampm = ToUpper(suffix);
   }
   
   string hhmm = (ampm != "") ? StringSubstr(t, 0, StringLen(t)-2) : t;
   string timeParts[];
   int timeCount = StringSplit(hhmm, ':', timeParts);
   
   if(timeCount >= 2) {
      h = (int)StringToInteger(timeParts[0]);
      min = (int)StringToInteger(timeParts[1]);
   } else {
      h = (int)StringToInteger(hhmm);
      min = 0;
   }

   if(ampm == "PM" && h < 12) h += 12;
   if(ampm == "AM" && h == 12) h = 0;

   MqlDateTime dt;
   dt.year = y;
   dt.mon = m;
   dt.day = d;
   dt.hour = h;
   dt.min = min;
   dt.sec = 0;
   
   return StructToTime(dt);
}

//+------------------------------------------------------------------+
//| Konversi Waktu Server ke WIB                                     |
//+------------------------------------------------------------------+
datetime ConvertToWIB(datetime serverTime) {
   int brokerOffset = 0;
   int wibOffset = 7;
   
   if (ManualBrokerOffset != 0) {
      brokerOffset = ManualBrokerOffset;
   } else {
      datetime gmtTime = TimeGMT();
      brokerOffset = (int)((TimeCurrent() - gmtTime) / 3600);
   }
   
   datetime utcTime = serverTime - (brokerOffset * 3600);
   datetime wibTime = utcTime + (wibOffset * 3600);
   return wibTime;
}

//+------------------------------------------------------------------+
//| Check News                                                       |
//+------------------------------------------------------------------+
bool CheckNews() {
   isIncomingNews = false;
   activeNewsTime = 0;
   windowEndTime = 0;
   activeNewsImpact = "";
   
   if(!FileIsExist("forex_news.xml")) {
      if(IsDownloader) {
         Print("📁 File forex_news.xml tidak ditemukan. Mencoba download...");
         DownloadXML();
      } else {
         return false;
      }
   }
   
   int handle = FileOpen("forex_news.xml", FILE_READ | FILE_TXT);
   if(handle < 0) {
      Print("❌ Gagal membuka forex_news.xml");
      return false;
   }
   
   string xmlContent = "";
   while(!FileIsEnding(handle))
      xmlContent += FileReadString(handle) + "\n";
   FileClose(handle);
   
   datetime now = TimeCurrent();
   datetime windowStart = now - (MinutesBeforeNews * 60);
   datetime windowEnd   = now + (MinutesAfterNews * 60);
   
   string symbol = Symbol();
   string baseCurrency  = StringSubstr(symbol, 0, 3);
   string quoteCurrency = StringSubstr(symbol, 3, 3);
   
   datetime nearestNewsTime = 0;
   string nearestImpact = "";
   string nearestTitle = "";
   
   datetime closestInWindow = 0;
   string closestImpact = "";
   string closestTitle = "";
   
   int index = 0;
   
   while(true) {
      int start = StringFind(xmlContent, "<event>", index);
      if(start < 0) break;
      
      int end = StringFind(xmlContent, "</event>", start);
      if(end < 0) break;
      
      string eventBlock = StringSubstr(xmlContent, start, end - start + 8);
      index = end + 8;
      
      string title    = GetXmlTagValue(eventBlock, "title");
      string country  = GetXmlTagValue(eventBlock, "country");
      string impact   = ToUpper(GetXmlTagValue(eventBlock, "impact"));
      string date     = GetXmlTagValue(eventBlock, "date");
      string time     = GetXmlTagValue(eventBlock, "time");
      
      if(date == "" || time == "" || country == "" || impact == "") 
         continue;
      
      datetime newsTime = ConvertNewsDateTime(date, time);
      if(newsTime == 0) continue;
      
      bool impactOK = false;
      if(FilterHighNews   && StringFind(impact, "HIGH")   >= 0) impactOK = true;
      if(FilterMediumNews && StringFind(impact, "MEDIUM") >= 0) impactOK = true;
      if(FilterLowNews    && StringFind(impact, "LOW")    >= 0) impactOK = true;
      if(!impactOK) continue;
      
      bool currencyOK = true;
      if(AffectedCurrencyOnly) {
         currencyOK = (country == baseCurrency || country == quoteCurrency);
      }
      if(!currencyOK) continue;
      
      bool inWindow = (newsTime >= windowStart && newsTime <= windowEnd);
      if(inWindow) {
         isIncomingNews = true;
         if (closestInWindow == 0 || MathAbs(newsTime - now) < MathAbs(closestInWindow - now)) {
            closestInWindow = newsTime;
            closestImpact = impact;
            closestTitle = title;
         }
      }
      
      if(newsTime > now) {
         if(nearestNewsTime == 0 || newsTime < nearestNewsTime) {
            nearestNewsTime = newsTime;
            nearestImpact = impact;
            nearestTitle = title;
         }
      }
   }
   
   if (closestInWindow > 0) {
      activeNewsTime = closestInWindow;
      activeNewsImpact = closestImpact;
      windowEndTime = activeNewsTime + (MinutesAfterNews * 60);
   }
   
   // ===== AGGRESSIVE MODE: DETEKSI WINDOW NEWS BARU =====
   if(isIncomingNews) {
      static datetime lastNewsWindowStart = 0;
      datetime currentWindowStart = windowEndTime - (MinutesAfterNews * 60);
      
      if(lastNewsWindowStart != currentWindowStart && currentWindowStart > 0) {
         lastNewsWindowStart = currentWindowStart;
         
         aggressiveStatus = AGGRESSIVE_WAITING;
         aggressiveEntryExecuted = false;
         aggressiveAttemptDone = false;
         aggressiveCheckStartTime = 0;
         CancelBothPendingOrders();
         ResetAggressiveTracker();
         
         if(closestInWindow > 0) {
            currentNews.title = closestTitle;
            currentNews.impact = closestImpact;
            currentNews.releaseTime = closestInWindow;
            currentNews.hasExecuted = false;
         }
         
         ResetPreNewsLevels();
         if(CapturePreNewsLevels(currentNews.releaseTime)) {
            Print("══════════════════════════════════════════════════");
            Print("🆕 NEWS WINDOW DIMULAI - Aggressive Mode ACTIVE");
            Print("   News: ", currentNews.title);
            Print("   Impact: ", currentNews.impact);
            Print("   Release: ", TimeToString(currentNews.releaseTime));
            Print("══════════════════════════════════════════════════");
         }
      }
   }
   
   if(nearestNewsTime > 0) {
      nextNewsTime = nearestNewsTime;
      nextNewsImpact = nearestImpact;
      nextNewsTitle = nearestTitle;
      
      datetime wibTime = ConvertToWIB(nearestNewsTime);
      nextNewsTimeString = TimeToString(wibTime, TIME_MINUTES) + " WIB";
      nextNewsTitleShort = nearestTitle;
      nextNewsFullTitle = nearestTitle;
   } else {
      nextNewsTime = 0;
      nextNewsImpact = "";
      nextNewsTitle = "";
      nextNewsTimeString = "";
      nextNewsTitleShort = "";
      nextNewsFullTitle = "";
   }
   
   lastCheckNews = TimeCurrent();
   return isIncomingNews;
}  

//+------------------------------------------------------------------+
//| Reset Pre-News Levels                                            |
//+------------------------------------------------------------------+
void ResetPreNewsLevels() {
   preNews.highLevel = 0;
   preNews.lowLevel = 0;
   preNews.candleTime = 0;
   preNews.isValid = false;
}

//+------------------------------------------------------------------+
//| Reset Aggressive Tracker                                         |
//+------------------------------------------------------------------+
void ResetAggressiveTracker() {
   aggressivePos.ticket = 0;
   aggressivePos.orderType = -1;
   aggressivePos.openPrice = 0;
   aggressivePos.highestPrice = 0;
   aggressivePos.lowestPrice = 0;
   aggressivePos.entryTime = 0;
   aggressivePos.peakProfitPips = 0;
}

//+------------------------------------------------------------------+
//| Capture Pre-News Levels (dari candle M5 sebelum news)            |
//+------------------------------------------------------------------+
bool CapturePreNewsLevels(datetime newsTime) {
   // Cari candle M5 yang selesai sebelum newsTime
   datetime previousCandleTime = iTime(Symbol(), PERIOD_M5, 1);
   
   if (previousCandleTime < newsTime) {
      preNews.highLevel = iHigh(Symbol(), PERIOD_M5, 1);
      preNews.lowLevel = iLow(Symbol(), PERIOD_M5, 1);
      preNews.candleTime = previousCandleTime;
      preNews.isValid = (preNews.highLevel > 0 && preNews.lowLevel > 0);
      
      Print("📊 Pre-News Levels captured:");
      Print("   Candle Time: ", TimeToString(preNews.candleTime));
      Print("   Pre-News High: ", DoubleToString(preNews.highLevel, Digits));
      Print("   Pre-News Low: ", DoubleToString(preNews.lowLevel, Digits));
      return preNews.isValid;
   }
   
   // Fallback: gunakan high/low dari 5 candle terakhir
   double highestHigh = 0, lowestLow = 999999;
   for(int i = 1; i <= 5; i++) {
      double h = iHigh(Symbol(), PERIOD_M5, i);
      double l = iLow(Symbol(), PERIOD_M5, i);
      if(h > highestHigh) highestHigh = h;
      if(l < lowestLow) lowestLow = l;
   }
   
   preNews.highLevel = highestHigh;
   preNews.lowLevel = lowestLow;
   preNews.isValid = (preNews.highLevel > 0 && preNews.lowLevel > 0);
   
   Print("⚠️ Fallback Pre-News Levels (5 candles):");
   Print("   High: ", DoubleToString(preNews.highLevel, Digits));
   Print("   Low: ", DoubleToString(preNews.lowLevel, Digits));
   
   return preNews.isValid;
}

//+------------------------------------------------------------------+
//| Hitung Jarak Pending Order Berdasarkan ATR (Adaptif)             |
//+------------------------------------------------------------------+
double CalculateAdaptiveDistance() {
   // Ambil ATR dari timeframe M5
   double atrValue = iATR(Symbol(), PERIOD_M5, 14, 1);
   double pipValue = GetPipValue();
   double atrInPips = atrValue / pipValue;
   
   // Hitung jarak dasar dari ATR
   double distancePips = atrInPips * AdaptiveDistanceATRMult;
   
   // Beri batasan
   distancePips = MathMax(MinDistancePips, MathMin(MaxDistancePips, distancePips));
   
   // Tambahan untuk HIGH impact news
   if(UseHighImpactBuffer && currentNews.impact == "HIGH") {
      distancePips = distancePips * HighImpactBufferMult;
      distancePips = MathMin(MaxDistancePips, distancePips);
   }
   
   Print("📏 Adaptive Distance Calculation:");
   Print("   ATR (M5): ", DoubleToString(atrValue, Digits), " (", DoubleToString(atrInPips, 1), " pips)");
   Print("   Multiplier: ", DoubleToString(AdaptiveDistanceATRMult, 1));
   Print("   Final Distance: ", DoubleToString(distancePips, 1), " pips");
   
   return distancePips * pipValue;
}

//+------------------------------------------------------------------+
//| Pasang Pending Order Berdasarkan Pre-News Levels                 |
//+------------------------------------------------------------------+
bool PlacePendingOrdersBasedOnPreNews() {
   if(!preNews.isValid) {
      Print("❌ Pre-News levels tidak valid!");
      return false;
   }
   
   // Hitung jarak pending order
   double distance = CalculateAdaptiveDistance();
   double pipValue = GetPipValue();
   
   double buyStopLevel = preNews.highLevel + distance;
   double sellStopLevel = preNews.lowLevel - distance;
   
   // Normalisasi harga
   buyStopLevel = NormalizeDouble(buyStopLevel, Digits);
   sellStopLevel = NormalizeDouble(sellStopLevel, Digits);
   
   double lotSize = CalculateLotSize();
   
   // Hitung SL (diletakkan di sisi berlawanan dari pre-news level)
   double buyStopSL = preNews.lowLevel - (StopLossPips * pipValue);
   double sellStopSL = preNews.highLevel + (StopLossPips * pipValue);
   
   // Hitung TP (menggunakan Risk Reward)
   double rewardPips = StopLossPips * RiskRewardRatio;
   double buyStopTP = buyStopLevel + (rewardPips * pipValue);
   double sellStopTP = sellStopLevel - (rewardPips * pipValue);
   
   // Normalisasi SL/TP
   buyStopSL = NormalizeDouble(buyStopSL, Digits);
   sellStopSL = NormalizeDouble(sellStopSL, Digits);
   buyStopTP = NormalizeDouble(buyStopTP, Digits);
   sellStopTP = NormalizeDouble(sellStopTP, Digits);
   
   Print("══════════════════════════════════════════════════");
   Print("🔥 AGGRESSIVE MODE: Memasang Pending Order");
   Print("   Pre-News High: ", DoubleToString(preNews.highLevel, Digits));
   Print("   Pre-News Low: ", DoubleToString(preNews.lowLevel, Digits));
   Print("   Distance: ", DoubleToString(distance / pipValue, 1), " pips");
   Print("   BUY STOP at: ", DoubleToString(buyStopLevel, Digits));
   Print("   SELL STOP at: ", DoubleToString(sellStopLevel, Digits));
   Print("══════════════════════════════════════════════════");
   
   if(buyStopTicket > 0) {
   if(OrderSelect(buyStopTicket, SELECT_BY_TICKET, MODE_TRADES)) {
      if(!OrderDelete(buyStopTicket)) {
         Print("❌ Gagal delete BUY STOP #", buyStopTicket, " Error: ", GetLastError());
      } else {
         Print("🗑️ BUY STOP #", buyStopTicket, " deleted");
      }
   }
   buyStopTicket = -1;
   }

   if(sellStopTicket > 0) {
   if(OrderSelect(sellStopTicket, SELECT_BY_TICKET, MODE_TRADES)) {
      if(!OrderDelete(sellStopTicket)) {
         Print("❌ Gagal delete SELL STOP #", sellStopTicket, " Error: ", GetLastError());
      } else {
         Print("🗑️ SELL STOP #", sellStopTicket, " deleted");
      }
   }
   sellStopTicket = -1;
   }   
   // Pasang Buy Stop
   buyStopTicket = OrderSend(Symbol(), OP_BUYSTOP, lotSize, buyStopLevel, 
                             (int)slippage, buyStopSL, buyStopTP, 
                             "News Aggressive BUY", MagicNumber, 0, clrGreen);
   
   if(buyStopTicket < 0) {
      Print("❌ Gagal pasang BUY STOP. Error: ", GetLastError());
   }
   
   Sleep(100);
   RefreshRates();
   
   // Pasang Sell Stop
   sellStopTicket = OrderSend(Symbol(), OP_SELLSTOP, lotSize, sellStopLevel, 
                              (int)slippage, sellStopSL, sellStopTP, 
                              "News Aggressive SELL", MagicNumber, 0, clrRed);
   
   if(sellStopTicket < 0) {
      Print("❌ Gagal pasang SELL STOP. Error: ", GetLastError());
   }
   
   if(buyStopTicket > 0 || sellStopTicket > 0) {
      pendingOrderPlacedTime = TimeCurrent();
      Print("✅ Pending orders terpasang! Menunggu eksekusi maksimal ", 
            PendingOrderLifetimeSeconds, " detik");
      return true;
   }
   
   aggressiveStatus = AGGRESSIVE_FAILED;
   return false;
}

//+------------------------------------------------------------------+
//| Cancel Both Pending Order                                        |
//+------------------------------------------------------------------+
void CancelBothPendingOrders() {
   // Cancel BUY STOP
   if(buyStopTicket > 0) {
      if(OrderSelect(buyStopTicket, SELECT_BY_TICKET, MODE_TRADES)) {
         bool deleted = OrderDelete(buyStopTicket);
         if(deleted) {
            Print("🗑️ BUY STOP #", buyStopTicket, " cancelled");
         }
      }
      buyStopTicket = -1;
   }
   
   // Cancel SELL STOP
   if(sellStopTicket > 0) {
      if(OrderSelect(sellStopTicket, SELECT_BY_TICKET, MODE_TRADES)) {
         bool deleted = OrderDelete(sellStopTicket);
         if(deleted) {
            Print("🗑️ SELL STOP #", sellStopTicket, " cancelled");
         }
      }
      sellStopTicket = -1;
   }
}

//+------------------------------------------------------------------+
//| Cek Pending Order Expired                                        |
//+------------------------------------------------------------------+
void CheckPendingOrderExpired() {
   if(aggressiveStatus != AGGRESSIVE_DETECTED) return;
   if(pendingOrderPlacedTime == 0) return;
   
   if(TimeCurrent() - pendingOrderPlacedTime > PendingOrderLifetimeSeconds) {
      Print("══════════════════════════════════════════════════");
      Print("⏰ AGGRESSIVE MODE: PENDING ORDER EXPIRED!");
      Print("   Tidak ada eksekusi dalam ", PendingOrderLifetimeSeconds, " detik");
      Print("══════════════════════════════════════════════════");
      
      CancelBothPendingOrders();
      aggressiveStatus = AGGRESSIVE_FAILED;
      aggressiveAttemptDone = true;
   }
}

//+------------------------------------------------------------------+
//| Cek dan Eksekusi Pending Order                                   |
//+------------------------------------------------------------------+
bool CheckPendingOrderExecuted() {
   for(int i = 0; i < OrdersTotal(); i++) {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) {
         if(IsMyOrder() && (OrderType() == OP_BUY || OrderType() == OP_SELL)) {
            if(StringFind(OrderComment(), "News Aggressive") >= 0) {
               if(aggressiveStatus != AGGRESSIVE_EXECUTED) {
                  aggressiveStatus = AGGRESSIVE_EXECUTED;
                  aggressiveEntryExecuted = true;
                  
                  // Inisialisasi tracker untuk trailing ketat
                  InitAggressiveTracker(OrderTicket(), OrderType(), OrderOpenPrice());
                  
                  Print("══════════════════════════════════════════════════");
                  Print("✅✅✅ AGGRESSIVE MODE: POSITION OPENED! ✅✅✅");
                  Print("   Type: ", (OrderType() == OP_BUY ? "BUY" : "SELL"));
                  Print("   Entry: ", DoubleToString(OrderOpenPrice(), Digits));
                  Print("   Trailing ketat akan aktif SEKARANG!");
                  Print("══════════════════════════════════════════════════");
                  
                  // Cancel pending order yang satunya
                  CancelBothPendingOrders();
                  return true;
               }
            }
         }
      }
   }
   return false;
}

//+------------------------------------------------------------------+
//| Initialize Aggressive Tracker                                    |
//+------------------------------------------------------------------+
void InitAggressiveTracker(int ticket, int type, double price) {
   aggressivePos.ticket = ticket;
   aggressivePos.orderType = type;
   aggressivePos.openPrice = price;
   aggressivePos.highestPrice = (type == OP_BUY) ? price : 0;
   aggressivePos.lowestPrice = (type == OP_SELL) ? price : 0;
   aggressivePos.entryTime = TimeCurrent();
   aggressivePos.peakProfitPips = 0;
   
   Print("📊 Aggressive Tracker initialized for #", ticket);
   Print("   Trailing distance: ", AggressiveTrailDistancePips, " pips");
   Print("   Trailing step: ", AggressiveTrailStepPips, " pips");
}

//+------------------------------------------------------------------+
//| Update Profit Peak                                               |
//+------------------------------------------------------------------+
void UpdateAggressivePeak() {
   if(aggressivePos.ticket == 0) return;
   if(!OrderSelect(aggressivePos.ticket, SELECT_BY_TICKET, MODE_TRADES)) {
      ResetAggressiveTracker();
      return;
   }
   
   double pipValue = GetPipValue();
   double currentProfitPips = 0;
   double currentPrice = (aggressivePos.orderType == OP_BUY) ? Bid : Ask;
   
   if(aggressivePos.orderType == OP_BUY) {
      currentProfitPips = (currentPrice - aggressivePos.openPrice) / pipValue;
      if(currentPrice > aggressivePos.highestPrice) {
         aggressivePos.highestPrice = currentPrice;
      }
   } else {
      currentProfitPips = (aggressivePos.openPrice - currentPrice) / pipValue;
      if(currentPrice < aggressivePos.lowestPrice) {
         aggressivePos.lowestPrice = currentPrice;
      }
   }
   
   if(currentProfitPips > aggressivePos.peakProfitPips) {
      aggressivePos.peakProfitPips = currentProfitPips;
   }
}

//+------------------------------------------------------------------+
//| Apply Aggressive Trailing Stop                                   |
//+------------------------------------------------------------------+
void ApplyAggressiveTrailingStop() {
   if(!UseAggressiveTrailing) return;
   if(aggressivePos.ticket == 0) return;
   if(!OrderSelect(aggressivePos.ticket, SELECT_BY_TICKET, MODE_TRADES)) {
      ResetAggressiveTracker();
      return;
   }
   
   double pipValue = GetPipValue();
   double currentPrice = (aggressivePos.orderType == OP_BUY) ? Bid : Ask;
   double profitPips = 0;
   
   if(aggressivePos.orderType == OP_BUY) {
      profitPips = (currentPrice - aggressivePos.openPrice) / pipValue;
   } else {
      profitPips = (aggressivePos.openPrice - currentPrice) / pipValue;
   }
   
   // TRAILING AKTIF SEGERA (tanpa menunggu profit tertentu)
   // Selama posisi sudah profit, trailing langsung jalan
   if(profitPips > 0) {
      double newSL = 0;
      
      if(aggressivePos.orderType == OP_BUY) {
         // Trail dari harga tertinggi yang pernah dicapai
         newSL = aggressivePos.highestPrice - (AggressiveTrailDistancePips * pipValue);
      } else {
         // Trail dari harga terendah yang pernah dicapai
         newSL = aggressivePos.lowestPrice + (AggressiveTrailDistancePips * pipValue);
      }
      
      newSL = NormalizeDouble(newSL, Digits);
      
      // Cek apakah perlu update (minimal step)
      bool needUpdate = false;
      if(aggressivePos.orderType == OP_BUY) {
         needUpdate = (newSL > OrderStopLoss() + (AggressiveTrailStepPips * pipValue / 2));
      } else {
         needUpdate = (newSL < OrderStopLoss() - (AggressiveTrailStepPips * pipValue / 2));
      }
      
      if(needUpdate && MathAbs(OrderStopLoss() - newSL) > pipValue / 10) {
         if(OrderModify(OrderTicket(), OrderOpenPrice(), newSL, OrderTakeProfit(), 0, clrNONE)) {
            static datetime lastTrailLog = 0;
            if(TimeCurrent() - lastTrailLog > 2) { // Log setiap 2 detik
               Print("📉 [TRAILING] SL updated to ", DoubleToString(newSL, Digits),
                     " | Profit: ", DoubleToString(profitPips, 1), " pips");
               lastTrailLog = TimeCurrent();
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Monitor Aggressive Position                                      |
//+------------------------------------------------------------------+
void MonitorAggressivePosition() {
   // Cek apakah ada posisi aggressive yang belum di-track
   if(aggressivePos.ticket == 0 && aggressiveStatus == AGGRESSIVE_EXECUTED) {
      for(int i = 0; i < OrdersTotal(); i++) {
         if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) {
            if(IsMyOrder() && StringFind(OrderComment(), "News Aggressive") >= 0) {
               InitAggressiveTracker(OrderTicket(), OrderType(), OrderOpenPrice());
               break;
            }
         }
      }
   }
   
   // Update dan apply trailing jika ada posisi
   if(aggressivePos.ticket != 0) {
      UpdateAggressivePeak();
      ApplyAggressiveTrailingStop();
   }
}

//+------------------------------------------------------------------+
//| Main Trading Logic                                               |
//+------------------------------------------------------------------+
void OnTick() {
   static int tickCount = 0;
   static datetime lastStatusLog = 0;
   tickCount++;
   
   if (tickCount % 5 == 0) UpdateDashboard();
   
   // ===== AGGRESSIVE NEWS MODE (DIPERBAIKI) =====
   if(UseAggressiveNewsEntry && UseNewsFilter && isIncomingNews && !aggressiveAttemptDone) {
      
      // Jika sudah eksekusi, monitor trailing
      if(aggressiveStatus == AGGRESSIVE_EXECUTED) {
         MonitorAggressivePosition();
         return;
      }
      
      // ===== HANYA PROSES JIKA NEWS SUDAH RILIS =====
      if(currentNews.releaseTime > 0 && TimeCurrent() >= currentNews.releaseTime) {
         
         // ===== TAHAP 1: DETEKSI LONJAKAN PADA CANDLE 0 =====
         // Hanya lakukan jika status WAITING (belum pasang pending order)
         if(aggressiveStatus == AGGRESSIVE_WAITING) {
            
            // Cek apakah candle 0 sudah terbentuk (minimal 5 detik setelah news)
            int secondsSinceRelease = (int)(TimeCurrent() - currentNews.releaseTime);
            if(secondsSinceRelease < 5) {
               return;  // Masih terlalu awal, tunggu candle mulai terbentuk
            }
            
            // Ambil data candle 0 (candle yang sedang berjalan)
            double candleOpen = iOpen(Symbol(), PERIOD_M1, 0);
            double candleHigh = iHigh(Symbol(), PERIOD_M1, 0);
            double candleLow = iLow(Symbol(), PERIOD_M1, 0);
            datetime candleTime = iTime(Symbol(), PERIOD_M1, 0);
            
            // Pastikan candle ini terbentuk SETELAH news rilis
            if(candleTime < currentNews.releaseTime - 10) {
               return;  // Candle masih dari sebelum news, tunggu candle baru
            }
            
            double pipValue = GetPipValue();
            double currentRange = (candleHigh - candleLow) / pipValue;
            
            // Parameter lonjakan minimal (bisa ditambahkan ke input)
            double minSpikePips = 15.0;  // Minimal pergerakan candle 0
            
            Print("📊 AGGRESSIVE MODE - Candle 0 Analysis:");
            Print("   Seconds since release: ", secondsSinceRelease);
            Print("   Candle 0 Range: ", DoubleToString(currentRange, 1), " pips");
            Print("   Required Spike: ", DoubleToString(minSpikePips, 1), " pips");
            
            // ===== CEK APAKAH TERJADI LONJAKAN =====
            if(currentRange >= minSpikePips) {
               Print("══════════════════════════════════════════════════");
               Print("✅ AGGRESSIVE MODE: LONJAKAN TERDETEKSI di CANDLE 0!");
               Print("   Range: ", DoubleToString(currentRange,1), " pips");
               Print("   High: ", DoubleToString(candleHigh, Digits));
               Print("   Low: ", DoubleToString(candleLow, Digits));
               Print("══════════════════════════════════════════════════");
               
               // Simpan level spike
               currentSpike.highLevel = candleHigh;
               currentSpike.lowLevel = candleLow;
               currentSpike.spikeMovePips = currentRange;
               currentSpike.isActive = true;
               
               // Lanjut ke pemasangan pending order
               aggressiveStatus = AGGRESSIVE_DETECTED;
               
            } else {
               // Belum terjadi lonjakan, terus pantau selama window news
               // Batasi waktu deteksi (misal 60 detik pertama)
               if(secondsSinceRelease > 60) {
                  Print("⏰ AGGRESSIVE MODE: Waktu deteksi habis (60 detik) - TIDAK ADA LONJAKAN");
                  aggressiveStatus = AGGRESSIVE_FAILED;
                  aggressiveAttemptDone = true;
               }
               return;
            }
         }
         
         // ===== TAHAP 2: PASANG PENDING ORDER (setelah lonjakan terdeteksi) =====
         if(aggressiveStatus == AGGRESSIVE_DETECTED && preNews.isValid) {
            if(PlacePendingOrdersBasedOnPreNews()) {
               aggressiveStatus = AGGRESSIVE_WAITING_EXECUTION;  // Status baru
               aggressiveAttemptDone = true;
               Print("📌 Pending order terpasang! Menunggu eksekusi...");
            } else {
               aggressiveStatus = AGGRESSIVE_FAILED;
               aggressiveAttemptDone = true;
            }
            return;
         }
         
         // ===== TAHAP 3: MENUNGGU EKSEKUSI ATAU EXPIRED =====
         if(aggressiveStatus == AGGRESSIVE_WAITING_EXECUTION) {
            if(CheckPendingOrderExecuted()) {
               Print("✅ AGGRESSIVE MODE: Position opened!");
               return;
            }
            CheckPendingOrderExpired();
            
            // Jika expired, tetap dalam window news, jangan coba lagi
            if(aggressiveStatus == AGGRESSIVE_FAILED) {
               Print("🟡 AGGRESSIVE MODE GAGAL - Menunggu window news selesai...");
            }
            return;
         }
      }
      
      // Belum waktunya news rilis
      return;
   }
   
   // ===== RESET AGGRESSIVE MODE KETIKA WINDOW NEWS SELESAI =====
   static bool wasIncomingNews = false;
   if(wasIncomingNews && !isIncomingNews) {
      Print("══════════════════════════════════════════════════");
      Print("🔄 NEWS WINDOW SELESAI - Aggressive Mode OFF");
      Print("   Kembali ke mode utama trading");
      Print("══════════════════════════════════════════════════");
      
      // Reset semua flag aggressive mode
      aggressiveStatus = AGGRESSIVE_WAITING;
      aggressiveAttemptDone = false;
      pendingOrderPlacedTime = 0;
      CancelBothPendingOrders();
      
      // Reset tracker
      ResetAggressiveTracker();
      preNews.isValid = false;
   }
   wasIncomingNews = isIncomingNews;
   
   if (TimeCurrent() - lastStatusLog > 300) {
      lastStatusLog = TimeCurrent();
      Print("=== STATUS DEBUG ===");
      Print("isIncomingNews: ", isIncomingNews);
      Print("nextNewsTime: ", TimeToString(nextNewsTime));
      Print("aggressiveStatus: DISABLED");
      Print("==================");
   }
     
   if (UseNewsFilter) {
      static datetime lastCheck = 0;
      if (TimeCurrent() - lastCheck > readNewsInterval * 60) {
         CheckNews();
         lastCheck = TimeCurrent();
      }
      if (IsDownloader && TimeCurrent() - lastDownloadNews > downloadNewsInterval * 60) {
         DownloadXML();
      }
   }
   
   CheckEquityStop();
   ApplyTrailingStop();
   ApplyBreakEven();
   CheckActivePositions();
   
   // Reset ADX Spike entry flag jika tidak ada posisi
   if (CountOpenTrades() == 0) {
      adxSpikeEntryExecuted = false;
   }
   
   // ===== MODE UTAMA (ADX SPIKE dengan SMC) =====
   bool canUseMainMode = !isIncomingNews;
   
   if (canUseMainMode) {
      if (!CheckEntryConditions()) return;
      
      int activeTrades = CountOpenTrades();
      
      if (activeTrades == 0) {
         int adxSignal = -1;
         if (CheckADXSpikeEntry(adxSignal)) {
            Print("🔥 ADX SPIKE: Entry ", (adxSignal == OP_BUY ? "BUY" : "SELL"));
            ExecuteInitialEntry(adxSignal);
            return;
         }
      }
   }
   
   // ===== HANDLE CLOSE & REVERSE UNTUK POSISI YANG ADA =====
   if (CountOpenTrades() > 0 && ADXSpikeCloseReverse) {
      int signalDirection = -1;
      if (CheckADXSpikeEntry(signalDirection)) {
         if ((HasBuyPosition && signalDirection == OP_SELL) || 
             (HasSellPosition && signalDirection == OP_BUY)) {
            Print("🔄 ADX SPIKE: Reverse signal - closing current and opening new position");
            CloseAndReverse(signalDirection);
            return;
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
   ObjectsDeleteAll(0, "VENUS_");
   Print(EAName + " Deinitialized");
}
//+------------------------------------------------------------------+