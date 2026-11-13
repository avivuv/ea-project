"""
Eksekusi order di MT5 via library MetaTrader5.

PENGAMAN: koneksi DITOLAK bila akun yang login bukan akun DEMO (RULES §1).
Mode LIVE belum didukung sama sekali di program ini.

    python -m tg_signal.executor --check     # cek akun, algo trading, simbol, harga
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import MetaTrader5 as mt5

from tg_signal import settings


@dataclass
class Tick:
    bid: float
    ask: float
    time: datetime

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def age_sec(self) -> float:
        return (datetime.now(timezone.utc) - self.time).total_seconds()


@dataclass
class Fill:
    ticket: int
    price: float
    sl: float
    tp: float
    time: datetime


@dataclass
class Closed:
    exit_price: float
    profit_usd: float
    time: datetime
    reason: str          # TP | SL | MANUAL | OTHER


class MT5Executor:
    def __init__(self, symbol: str = settings.SYMBOL, magic: int = settings.TG_MAGIC):
        self.symbol = symbol
        self.magic = magic          # penanda order milik program ini (EA sinyal vs strategi sendiri)
        self.info = None

    # ── koneksi ─────────────────────────────────────────────────────────────
    def connect(self) -> None:
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize gagal: {mt5.last_error()}")
        acc = mt5.account_info()
        if acc is None:
            raise RuntimeError("MT5 belum login ke akun")
        if acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
            mt5.shutdown()
            raise RuntimeError(f"DITOLAK: akun {acc.login} bukan akun DEMO. Program ini hanya untuk demo.")
        if not mt5.symbol_select(self.symbol, True):
            raise RuntimeError(f"Simbol {self.symbol} tidak tersedia")
        self.info = mt5.symbol_info(self.symbol)

    def status(self) -> dict:
        acc, term = mt5.account_info(), mt5.terminal_info()
        return {
            "login": acc.login, "server": acc.server, "demo": acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO,
            "balance": acc.balance, "equity": acc.equity, "currency": acc.currency,
            "connected": term.connected, "algo_trading": term.trade_allowed,
            "account_trade_allowed": acc.trade_allowed,
        }

    def shutdown(self) -> None:
        mt5.shutdown()

    # ── harga ───────────────────────────────────────────────────────────────
    def tick(self) -> Tick:
        t = mt5.symbol_info_tick(self.symbol)
        if t is None:
            raise RuntimeError(f"Tidak ada tick: {mt5.last_error()}")
        # time_msc = jam server (Exness UTC+0); dikoreksi offset bila ada
        ts = datetime.fromtimestamp(t.time_msc / 1000 - settings.MT5_UTC_OFFSET_H * 3600, timezone.utc)
        return Tick(t.bid, t.ask, ts)

    def rates(self, tf: str = "M1", count: int = 300):
        """Bar yang SUDAH close (bar berjalan tidak ikut), urut lama → baru: (time, open, high, low, close)."""
        r = mt5.copy_rates_from_pos(self.symbol, getattr(mt5, f"TIMEFRAME_{tf}"), 1, count)
        if r is None or len(r) == 0:
            raise RuntimeError(f"Tidak ada bar {tf}: {mt5.last_error()}")
        return r["time"], r["open"], r["high"], r["low"], r["close"]

    def rates_df(self, tf: str = "M5", count: int = 3000):
        """Bar yang sudah close sebagai DataFrame (index UTC; open/high/low/close BID; spread dalam harga)."""
        import pandas as pd
        r = mt5.copy_rates_from_pos(self.symbol, getattr(mt5, f"TIMEFRAME_{tf}"), 1, count)
        if r is None or len(r) == 0:
            raise RuntimeError(f"Tidak ada bar {tf}: {mt5.last_error()}")
        df = pd.DataFrame(r)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True) - pd.Timedelta(hours=settings.MT5_UTC_OFFSET_H)
        df["spread"] = df["spread"] * self.info.point
        return df.set_index("time")[["open", "high", "low", "close", "spread"]]

    # ── order ───────────────────────────────────────────────────────────────
    def _filling(self) -> int:
        fm = self.info.filling_mode
        if fm & 1:
            return mt5.ORDER_FILLING_FOK
        if fm & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def open_market(self, direction: str, lot: float, sl_price_dist: float, tp_price_dist: float,
                    zone_last: float | None, sl_from: str, comment: str) -> Fill:
        """Order market dengan SL & TP wajib (RULES §4). Jarak dalam satuan harga."""
        tk = mt5.symbol_info_tick(self.symbol)
        d = self.info.digits
        if direction == "BUY":
            price = tk.ask
            base = price if sl_from == "entry" or zone_last is None else min(zone_last, price)
            sl, tp, otype = base - sl_price_dist, price + tp_price_dist, mt5.ORDER_TYPE_BUY
        else:
            price = tk.bid
            base = price if sl_from == "entry" or zone_last is None else max(zone_last, price)
            sl, tp, otype = base + sl_price_dist, price - tp_price_dist, mt5.ORDER_TYPE_SELL
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": float(lot),
            "type": otype, "price": round(price, d), "sl": round(sl, d), "tp": round(tp, d),
            "deviation": settings.TG_DEVIATION_POINTS, "magic": self.magic,
            "comment": comment[:31], "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling(),
        }
        res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            code = None if res is None else res.retcode
            msg = mt5.last_error() if res is None else res.comment
            raise RuntimeError(f"order_send gagal (retcode={code}): {msg}")
        pos = mt5.positions_get(ticket=res.order)
        p = pos[0] if pos else None
        return Fill(ticket=res.order, price=p.price_open if p else res.price,
                    sl=p.sl if p else req["sl"], tp=p.tp if p else req["tp"],
                    time=datetime.now(timezone.utc))

    def open_market_at(self, direction: str, lot: float, sl: float, tp: float, comment: str) -> Fill:
        """Order market dengan SL & TP berupa harga tetap (mode ZONE: SL dari LAST)."""
        tk = mt5.symbol_info_tick(self.symbol)
        d = self.info.digits
        price, otype = (tk.ask, mt5.ORDER_TYPE_BUY) if direction == "BUY" else (tk.bid, mt5.ORDER_TYPE_SELL)
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": float(lot),
            "type": otype, "price": round(price, d), "sl": round(sl, d), "tp": round(tp, d),
            "deviation": settings.TG_DEVIATION_POINTS, "magic": self.magic,
            "comment": comment[:31], "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling(),
        }
        res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            code = None if res is None else res.retcode
            msg = mt5.last_error() if res is None else res.comment
            raise RuntimeError(f"order_send gagal (retcode={code}): {msg}")
        p = self.position_of(res.order)
        return Fill(ticket=res.order, price=p.price_open if p else res.price,
                    sl=p.sl if p else req["sl"], tp=p.tp if p else req["tp"],
                    time=datetime.now(timezone.utc))

    def place_limit(self, direction: str, lot: float, price: float, sl: float, tp: float,
                    comment: str) -> int:
        """Pending BUY LIMIT / SELL LIMIT dengan SL & TP. Return ticket order."""
        d = self.info.digits
        otype = mt5.ORDER_TYPE_BUY_LIMIT if direction == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
        req = {
            "action": mt5.TRADE_ACTION_PENDING, "symbol": self.symbol, "volume": float(lot),
            "type": otype, "price": round(price, d), "sl": round(sl, d), "tp": round(tp, d),
            "magic": self.magic, "comment": comment[:31], "type_time": mt5.ORDER_TIME_GTC,
        }
        res = None
        for filling in (mt5.ORDER_FILLING_RETURN, self._filling()):   # broker beda-beda untuk pending
            res = mt5.order_send({**req, "type_filling": filling})
            if res is not None and res.retcode != mt5.TRADE_RETCODE_INVALID_FILL:
                break
        if res is None or res.retcode not in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
            code = None if res is None else res.retcode
            msg = mt5.last_error() if res is None else res.comment
            raise RuntimeError(f"pending gagal (retcode={code}): {msg}")
        return res.order

    def cancel_order(self, ticket: int) -> bool:
        res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": int(ticket)})
        return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE

    def pending_tickets(self) -> set[int]:
        orders = mt5.orders_get(symbol=self.symbol) or ()
        return {o.ticket for o in orders if o.magic == self.magic}

    def position_of(self, order_ticket: int):
        """Posisi yang dibuka oleh order ini (ticket posisi = ticket order pembuka), atau None."""
        for p in mt5.positions_get(symbol=self.symbol) or ():
            if p.ticket == order_ticket or p.identifier == order_ticket:
                return p
        return None

    def entry_deal(self, order_ticket: int):
        """Deal pembuka posisi dari order ini (untuk posisi yang sudah tutup lagi), atau None."""
        deals = mt5.history_deals_get(position=order_ticket) or ()
        ins = [d for d in deals if d.entry == mt5.DEAL_ENTRY_IN]
        return ins[0] if ins else None

    def open_tickets(self) -> set[int]:
        pos = mt5.positions_get(symbol=self.symbol) or ()
        return {p.ticket for p in pos if p.magic == self.magic}

    def floating_usd(self) -> float:
        """Profit mengambang (profit + swap) semua posisi milik program ini."""
        pos = mt5.positions_get(symbol=self.symbol) or ()
        return round(sum(p.profit + p.swap for p in pos if p.magic == self.magic), 2)

    def close_position(self, ticket: int, comment: str = "target harian") -> bool:
        """Tutup posisi dengan order market berlawanan. True bila berhasil / sudah tidak ada."""
        pos = mt5.positions_get(ticket=int(ticket))
        if not pos:
            return True
        p = pos[0]
        tk = mt5.symbol_info_tick(self.symbol)
        buy = p.type == mt5.POSITION_TYPE_BUY
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": p.volume, "position": p.ticket,
            "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
            "price": tk.bid if buy else tk.ask, "deviation": settings.TG_DEVIATION_POINTS,
            "magic": self.magic, "comment": comment[:31], "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(),
        }
        res = mt5.order_send(req)
        return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE

    def closed_info(self, ticket: int) -> Closed | None:
        deals = mt5.history_deals_get(position=ticket) or ()
        out = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
        if not out:
            return None
        d = out[-1]
        profit = sum(x.profit + x.commission + x.swap + getattr(x, "fee", 0.0) for x in deals)
        reason = {mt5.DEAL_REASON_TP: "TP", mt5.DEAL_REASON_SL: "SL"}.get(d.reason, "MANUAL"
                                                                           if d.reason == mt5.DEAL_REASON_CLIENT
                                                                           else "OTHER")
        return Closed(d.price, round(profit, 2), datetime.fromtimestamp(d.time, timezone.utc), reason)


def main() -> None:
    ap = argparse.ArgumentParser(description="Cek koneksi eksekusi MT5")
    ap.add_argument("--check", action="store_true")
    ap.parse_args()
    ex = MT5Executor()
    ex.connect()
    try:
        st = ex.status()
        for k, v in st.items():
            print(f"  {k:<22}: {v}")
        tk = ex.tick()
        print(f"  {ex.symbol} bid/ask         : {tk.bid} / {tk.ask} (spread {tk.spread / settings.PIP_SIZE:.1f} pips,"
              f" umur {tk.age_sec:.0f} dtk)")
        print(f"  filling mode            : {ex.info.filling_mode} | volume_min {ex.info.volume_min}")
        if not st["algo_trading"]:
            print("\n  ⚠️  Tombol 'Algo Trading' di MT5 MATI — nyalakan supaya order bisa dikirim.")
    finally:
        ex.shutdown()


if __name__ == "__main__":
    main()
