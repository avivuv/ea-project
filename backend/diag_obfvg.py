import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.environ["OBFVG_ENABLED"] = "true"

import importlib, config
importlib.reload(config)
print("OBFVG_ENABLED:", config.OBFVG_ENABLED)

import pandas as pd, ta

df = pd.read_csv(os.path.join(os.path.dirname(__file__), "../data/XAUUSD_GMT+0_NO-DST_M15.csv"),
    header=None, names=["date","time","open","high","low","close","volume"])
df["datetime"] = pd.to_datetime(df["date"] + " " + df["time"])
df = df.set_index("datetime")
h4 = df["close"].resample("4H").ohlc()
h4["high"] = df["high"].resample("4H").max()
h4["low"]  = df["low"].resample("4H").min()
h4 = h4.dropna()
print(f"H4 bars total: {len(h4)}")

h4s = h4.tail(250).reset_index()
atr_s = ta.volatility.average_true_range(h4s["high"], h4s["low"], h4s["close"], window=14)
atr = float(atr_s.iloc[-1])
ema50  = float(ta.trend.ema_indicator(h4s["close"], window=50).iloc[-1])
ema200 = float(ta.trend.ema_indicator(h4s["close"], window=200).iloc[-1])
trend = "BUY" if ema50 > ema200 else "SELL"
print(f"ATR H4: {atr:.2f} | EMA50: {ema50:.2f} | EMA200: {ema200:.2f} | Trend: {trend}")

from strategies.strategy_obfvg import _find_order_blocks
obs = _find_order_blocks(h4s, atr, 50, 2.0)
curr = float(h4s["close"].iloc[-1])
proximity = 3.0 * atr
print(f"OBs found: {len(obs)} | Current price: {curr:.2f} | Proximity radius: {proximity:.2f}")
near = [o for o in obs if abs(curr - o.mid) <= proximity]
print(f"OBs within proximity: {len(near)} | Trend-aligned: {sum(1 for o in near if o.direction == trend)}")
for ob in obs[:10]:
    dist = abs(curr - ob.mid)
    marker = "<-- NEAR" if dist <= proximity else ""
    print(f"  {ob.direction} [{ob.bottom:.2f}~{ob.top:.2f}] mid={ob.mid:.2f} age={ob.bars_ago} fvg={ob.has_fvg} dist={dist:.2f} {marker}")
