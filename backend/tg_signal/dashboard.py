"""
Dashboard monitoring (NiceGUI) — HANYA MEMBACA database, log, dan akun MT5.
Kontrol: Pause/Resume (file data/PAUSE: EA sinyal & strategi sendiri) dan Pause swing.
Bagian: EA sinyal Telegram, swing Donchian, strategi sendiri (pro_live).

    python -m tg_signal.dashboard            # buka http://127.0.0.1:8080
    python -m tg_signal.dashboard --port 8081

Akses dari luar PC: pakai Tailscale + isi TG_DASH_PASSWORD di .env (RULES §6).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from nicegui import app, ui

from tg_signal import settings

WIB = timedelta(hours=7)
REFRESH_SEC = 3

# Token warna (dataviz reference palette, mode gelap)
C = {
    "surface": "#1a1a19", "page": "#0d0d0d", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781",
    "grid": "#2c2c2a", "axis": "#383835", "series": "#3987e5", "good": "#0ca30c", "critical": "#d03b3b",
    "warning": "#fab219", "border": "rgba(255,255,255,0.10)",
}
CSS = f"""
body {{ background: {C['page']}; color: {C['ink']}; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
.card {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 10px; padding: 14px 16px; }}
.label {{ color: {C['muted']}; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
.value {{ color: {C['ink']}; font-size: 24px; font-weight: 600; }}
.sub {{ color: {C['ink2']}; font-size: 13px; }}
.num {{ font-variant-numeric: tabular-nums; }}
.good {{ color: {C['good']}; }} .bad {{ color: {C['critical']}; }} .warn {{ color: {C['warning']}; }}
.logbox {{ font-family: ui-monospace, Consolas, monospace; font-size: 12px; color: {C['ink2']};
           white-space: pre-wrap; max-height: 320px; overflow-y: auto; }}
.q-table {{ background: {C['surface']} !important; color: {C['ink']} !important; }}
.q-table th {{ color: {C['muted']} !important; }}
"""


# ── Data ────────────────────────────────────────────────────────────────────
def db() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{settings.DB_PATH}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def wib(iso: str | None) -> str:
    if not iso:
        return "-"
    return (datetime.fromisoformat(iso) + WIB).strftime("%H:%M:%S")


def day_start_iso() -> str:
    now = datetime.now(timezone.utc) + WIB
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) - WIB
    return start.isoformat(timespec="seconds")


def mt5_snapshot() -> dict:
    """Akun + posisi milik program (magic). Gagal → dict kosong (dashboard tetap jalan)."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return {}
        acc = mt5.account_info()
        tick = mt5.symbol_info_tick(settings.SYMBOL)
        pos = [p for p in (mt5.positions_get(symbol=settings.SYMBOL) or ()) if p.magic == settings.TG_MAGIC]
        term = mt5.terminal_info()
        return {"balance": acc.balance, "equity": acc.equity, "currency": acc.currency,
                "demo": acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO, "algo": term.trade_allowed,
                "bid": tick.bid if tick else None, "ask": tick.ask if tick else None,
                "positions": [{"ticket": p.ticket, "dir": "BUY" if p.type == 0 else "SELL",
                               "entry": p.price_open, "sl": p.sl, "tp": p.tp, "price": p.price_current,
                               "profit": p.profit, "time": datetime.fromtimestamp(p.time, timezone.utc)}
                              for p in pos]}
    except Exception:
        return {}


SWING_METHODS = [  # sama dengan intraday.swing_live.METHODS (tidak di-import agar dashboard ringan)
    ("XAU_D1_DON20", "XAUUSD", "Donchian D1 20 · trail 3 ATR", 26111201),
    ("XAU_H4_DON55", "XAUUSD", "Donchian H4 55 · trail 4 ATR", 26111202),
    ("BTC_H4_DON55", "BTCUSD", "Donchian H4 55 · trail 4 ATR", 26111203),
    ("JPY_H4_DON55", "USDJPY", "Donchian H4 55 · trail 4 ATR", 26111204),
]


def swing_snapshot() -> dict:
    """Posisi & deal tutup EA swing (dibedakan lewat magic). Gagal → dict kosong."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return {}
        magics = {m[3]: m for m in SWING_METHODS}
        pos = {}
        for p in mt5.positions_get() or ():
            if p.magic in magics:
                pos[p.magic] = {"ticket": p.ticket, "dir": "BUY" if p.type == 0 else "SELL", "lot": p.volume,
                                "entry": p.price_open, "sl": p.sl, "price": p.price_current,
                                "profit": p.profit + p.swap, "time": datetime.fromtimestamp(p.time, timezone.utc)}
        now = datetime.now(timezone.utc)
        deals = [d for d in (mt5.history_deals_get(now - timedelta(days=365), now + timedelta(days=1)) or ())
                 if d.magic in magics and d.entry == mt5.DEAL_ENTRY_OUT]
        closed = [{"time": datetime.fromtimestamp(d.time, timezone.utc), "id": magics[d.magic][0],
                   "symbol": d.symbol, "usd": d.profit + d.swap + d.commission} for d in deals]
        return {"pos": pos, "closed": sorted(closed, key=lambda x: x["time"])}
    except Exception:
        return {}


def pro_snapshot() -> dict:
    """Posisi, pending, dan deal tutup strategi sendiri (magic PRO_MAGIC). Gagal -> dict kosong."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return {}
        mg = settings.PRO_MAGIC
        pos = [{"ticket": p.ticket, "dir": "BUY" if p.type == 0 else "SELL", "entry": p.price_open, "sl": p.sl,
                "tp": p.tp, "price": p.price_current, "profit": p.profit + p.swap,
                "time": datetime.fromtimestamp(p.time, timezone.utc)}
               for p in (mt5.positions_get(symbol=settings.SYMBOL) or ()) if p.magic == mg]
        pend = [{"ticket": o.ticket, "dir": "BUY" if o.type == mt5.ORDER_TYPE_BUY_LIMIT else "SELL",
                 "price": o.price_open, "sl": o.sl, "tp": o.tp,
                 "time": datetime.fromtimestamp(o.time_setup, timezone.utc)}
                for o in (mt5.orders_get(symbol=settings.SYMBOL) or ()) if o.magic == mg]
        now = datetime.now(timezone.utc)
        deals = mt5.history_deals_get(now - timedelta(days=365), now + timedelta(days=1)) or ()
        mine = {d.position_id for d in deals if d.magic == mg}
        by_pos: dict = {}
        for d in deals:
            if d.position_id in mine:
                by_pos.setdefault(d.position_id, []).append(d)
        closed = []
        for ds in by_pos.values():
            outs = [d for d in ds if d.entry == mt5.DEAL_ENTRY_OUT]
            ins = [d for d in ds if d.entry == mt5.DEAL_ENTRY_IN]
            if not outs or not ins:
                continue
            o = outs[-1]
            closed.append({"time": datetime.fromtimestamp(o.time, timezone.utc),
                           "dir": "BUY" if ins[0].type == mt5.DEAL_TYPE_BUY else "SELL",
                           "entry": ins[0].price, "exit": o.price,
                           "why": {mt5.DEAL_REASON_TP: "TP", mt5.DEAL_REASON_SL: "SL"}.get(o.reason, "lain"),
                           "usd": sum(x.profit + x.swap + x.commission for x in ds)})
        return {"pos": pos, "pend": pend, "closed": sorted(closed, key=lambda x: x["time"])}
    except Exception:
        return {}


def file_status(log_name: str, hb_name: str) -> tuple[str, str]:
    log = settings.DATA_DIR / log_name
    if not log.exists():
        return "BELUM PERNAH JALAN", "bad"
    age = datetime.now().timestamp() - log.stat().st_mtime
    hb = settings.DATA_DIR / hb_name
    if hb.exists():
        age = min(age, datetime.now().timestamp() - hb.stat().st_mtime)
    if age < 90:
        return "AKTIF", "good"
    mins = int(age // 60)
    return (f"tidak ada aktivitas {mins} menit", "warn") if age < 3600 else ("MATI / DIAM", "bad")


def program_status() -> tuple[str, str]:
    """(teks, kelas warna) dari umur baris terakhir live.log."""
    log = settings.DATA_DIR / "live.log"
    if not log.exists():
        return "BELUM PERNAH JALAN", "bad"
    age = datetime.now().timestamp() - log.stat().st_mtime
    hb = settings.DATA_DIR / "heartbeat"
    if hb.exists():
        age = min(age, datetime.now().timestamp() - hb.stat().st_mtime)
    if age < 60:
        return "AKTIF", "good"
    mins = int(age // 60)
    return (f"tidak ada aktivitas {mins} menit", "warn") if age < 3600 else ("MATI / DIAM", "bad")


# ── UI ──────────────────────────────────────────────────────────────────────
def stat(label: str):
    with ui.element("div").classes("card"):
        ui.label(label).classes("label")
        v = ui.label("-").classes("value num")
        s = ui.label("").classes("sub")
    return v, s


def build() -> None:
    ui.add_css(CSS)
    ui.dark_mode(True)
    with ui.tabs().classes("w-full").props("align=left inline-label") as tabs:
        tab_sig = ui.tab("EA sinyal Telegram", icon="send")
        tab_sw = ui.tab("Swing Donchian", icon="trending_up")
        tab_pro = ui.tab("Strategi sendiri", icon="insights")
    with ui.tab_panels(tabs, value=tab_sig).classes("w-full").style("background: transparent"):
        with ui.tab_panel(tab_sig).classes("p-0 gap-3"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label("Scalping sinyal Telegram — XAUUSD").classes("text-xl font-semibold")
                    info = ui.label("").classes("sub")
                with ui.row().classes("items-center gap-3"):
                    prog = ui.label("").classes("font-semibold")
                    pause_btn = ui.button("").props("unelevated")

            with ui.grid(columns="repeat(auto-fit, minmax(170px, 1fr))").classes("w-full gap-3"):
                v_bal, s_bal = stat("Saldo")
                v_eq, s_eq = stat("Equity")
                v_pnl, s_pnl = stat("P/L hari ini")
                v_tr, s_tr = stat("Trade hari ini")
                v_wr, s_wr = stat("Win rate (semua)")

            with ui.element("div").classes("card w-full"):
                ui.label("Posisi terbuka").classes("label")
                pos_box = ui.column().classes("w-full gap-1")

            with ui.element("div").classes("card w-full"):
                ui.label("Profit kumulatif (USD, trade yang sudah tutup)").classes("label")
                chart = ui.echart({
                    "backgroundColor": "transparent",
                    "grid": {"left": 48, "right": 16, "top": 16, "bottom": 28},
                    "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross", "lineStyle": {"color": C["muted"]}},
                                "backgroundColor": C["surface"], "borderColor": C["axis"],
                                "textStyle": {"color": C["ink"]}},
                    "xAxis": {"type": "category", "data": [], "axisLine": {"lineStyle": {"color": C["axis"]}},
                              "axisLabel": {"color": C["muted"]}},
                    "yAxis": {"type": "value", "splitLine": {"lineStyle": {"color": C["grid"]}},
                              "axisLabel": {"color": C["muted"]}},
                    "series": [{"type": "line", "name": "Profit kumulatif", "data": [], "showSymbol": True,
                                "symbolSize": 8, "lineStyle": {"width": 2, "color": C["series"]},
                                "itemStyle": {"color": C["series"]},
                                "markLine": {"silent": True, "symbol": "none",
                                             "lineStyle": {"color": C["axis"], "type": "solid"},
                                             "data": [{"yAxis": 0}], "label": {"show": False}}}],
                }).classes("w-full h-64")

            with ui.row().classes("w-full gap-3 items-start no-wrap max-md:flex-wrap"):
                with ui.element("div").classes("card flex-1 min-w-[320px]"):
                    ui.label("Sinyal hari ini").classes("label")
                    sig_table = ui.table(columns=[
                        {"name": "jam", "label": "Jam", "field": "jam", "align": "left"},
                        {"name": "sinyal", "label": "Sinyal", "field": "sinyal", "align": "left"},
                        {"name": "zona", "label": "Zona", "field": "zona", "align": "left"},
                        {"name": "status", "label": "Status", "field": "status", "align": "left"},
                        {"name": "alasan", "label": "Keterangan", "field": "alasan", "align": "left"},
                    ], rows=[], row_key="id", pagination=10).classes("w-full").props("dense flat dark")
                with ui.element("div").classes("card flex-1 min-w-[320px]"):
                    ui.label("Riwayat trade").classes("label")
                    tr_table = ui.table(columns=[
                        {"name": "buka", "label": "Buka", "field": "buka", "align": "left"},
                        {"name": "arah", "label": "Arah", "field": "arah", "align": "left"},
                        {"name": "entry", "label": "Entry", "field": "entry", "align": "right"},
                        {"name": "exit", "label": "Exit", "field": "exit", "align": "right"},
                        {"name": "hasil", "label": "Hasil", "field": "hasil", "align": "left"},
                        {"name": "pips", "label": "Pips", "field": "pips", "align": "right"},
                        {"name": "usd", "label": "USD", "field": "usd", "align": "right"},
                    ], rows=[], row_key="id", pagination=10).classes("w-full").props("dense flat dark")

            with ui.row().classes("w-full gap-3 items-start no-wrap max-md:flex-wrap"):
                with ui.element("div").classes("card flex-1 min-w-[320px]"):
                    ui.label("Pesan Telegram terakhir").classes("label")
                    feed = ui.label("").classes("logbox")
                with ui.element("div").classes("card flex-1 min-w-[320px]"):
                    ui.label("Log program").classes("label")
                    logbox = ui.label("").classes("logbox")

        with ui.tab_panel(tab_sw).classes("p-0 gap-3"):
            # ── Swing ───────────────────────────────────────────────────────────────
            swing_pause = settings.DATA_DIR / "PAUSE_SWING"
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label("Swing trend-following — XAUUSD · BTCUSD · USDJPY").classes("text-xl font-semibold")
                    ui.label("Donchian breakout + filter tren D1 · tanpa TP, trailing ATR · risiko 0,5%/trade "
                             "(skip bila lot minimum > 2% saldo) · 1 posisi per metode").classes("sub")
                with ui.row().classes("items-center gap-3"):
                    sw_prog = ui.label("").classes("font-semibold")
                    sw_btn = ui.button("").props("unelevated")
            with ui.grid(columns="repeat(auto-fit, minmax(240px, 1fr))").classes("w-full gap-3"):
                sw_cards = {}
                for mid, sym, desc, _ in SWING_METHODS:
                    with ui.element("div").classes("card"):
                        ui.label(f"{sym} · {mid}").classes("label")
                        ui.label(desc).classes("sub")
                        v = ui.label("-").classes("value num")
                        s = ui.label("").classes("sub num")
                        sw_cards[mid] = (v, s)
            with ui.row().classes("w-full gap-3 items-start no-wrap max-md:flex-wrap"):
                with ui.element("div").classes("card flex-1 min-w-[320px]"):
                    sw_sum = ui.label("Trade swing tutup").classes("label")
                    sw_table = ui.table(columns=[
                        {"name": "tutup", "label": "Tutup", "field": "tutup", "align": "left"},
                        {"name": "metode", "label": "Metode", "field": "metode", "align": "left"},
                        {"name": "usd", "label": "USD", "field": "usd", "align": "right"},
                    ], rows=[], row_key="k", pagination=8).classes("w-full").props("dense flat dark")
                with ui.element("div").classes("card flex-1 min-w-[320px]"):
                    ui.label("Log swing").classes("label")
                    sw_log = ui.label("").classes("logbox")

            def toggle_swing() -> None:
                if swing_pause.exists():
                    swing_pause.unlink(); ui.notify("Swing resume: entry baru diizinkan")
                else:
                    swing_pause.write_text("pause dari dashboard"); ui.notify("Swing pause: tanpa entry baru (trailing tetap jalan)")
                refresh()

            def confirm_swing() -> None:
                with ui.dialog() as dlg, ui.card():
                    ui.label("Lanjutkan entry swing?" if swing_pause.exists()
                             else "Hentikan entry swing baru? Posisi terbuka & trailing tetap berjalan.")
                    with ui.row():
                        ui.button("Ya", on_click=lambda: (dlg.close(), toggle_swing()))
                        ui.button("Batal", on_click=dlg.close).props("flat")
                dlg.open()

            sw_btn.on_click(confirm_swing)

            def refresh_swing() -> None:
                txt, cls = file_status("swing_live.log", "swing_heartbeat")
                paused = swing_pause.exists()
                sw_prog.text = f"● Swing: {txt}" + (" · PAUSE" if paused else "")
                sw_prog.classes(replace=f"font-semibold {('warn' if paused else cls)}")
                sw_btn.text = "Resume swing" if paused else "Pause swing"
                snap = swing_snapshot()
                closed = snap.get("closed", [])
                for mid, sym, _, magic in SWING_METHODS:
                    v, s = sw_cards[mid]
                    p = snap.get("pos", {}).get(magic)
                    tot = sum(c["usd"] for c in closed if c["id"] == mid)
                    n = sum(1 for c in closed if c["id"] == mid)
                    if p:
                        v.text = f"{p['profit']:+.2f} USD"
                        v.classes(replace="value num " + ("good" if p["profit"] > 0 else "bad" if p["profit"] < 0 else ""))
                        s.text = (f"{p['dir']} {p['lot']} @ {p['entry']:g} · SL {p['sl']:g} · sejak "
                                  f"{(p['time'] + WIB):%d/%m %H:%M} WIB · tutup: {n} trade {tot:+.2f}")
                    else:
                        v.text = "tanpa posisi"
                        v.classes(replace="value num")
                        s.text = f"menunggu breakout · tutup: {n} trade {tot:+.2f} USD"
                total = sum(c["usd"] for c in closed)
                sw_sum.text = f"Trade swing tutup · {len(closed)} trade · total {total:+.2f} USD"
                sw_table.rows = [{"k": i, "tutup": (c["time"] + WIB).strftime("%d/%m %H:%M"), "metode": c["id"],
                                  "usd": f"{c['usd']:+.2f}"} for i, c in enumerate(reversed(closed))]
                sw_table.update()
                log = settings.DATA_DIR / "swing_live.log"
                if log.exists():
                    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
                    sw_log.text = "\n".join(l[5:] for l in reversed(lines))

        with ui.tab_panel(tab_pro).classes("p-0 gap-3"):
            # ── Strategi sendiri ────────────────────────────────────────────────────
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label("Strategi sendiri — SMC top-down XAUUSD").classes("text-xl font-semibold")
                    ui.label("Bias EMA50 H1 (kemiringan > 0,1 ATR) · POI M15 FVG/OB/IFVG · konfirmasi CHoCH M5 · "
                             f"entry FVG M5 · RR 1:3 · SL maks 100 pips · lot {settings.PRO_LOT} · "
                             f"tanpa entry ±{settings.PRO_NEWS_MIN:g} mnt news USD · ikut tombol Pause di atas").classes("sub")
                pro_prog = ui.label("").classes("font-semibold")
            with ui.grid(columns="repeat(auto-fit, minmax(240px, 1fr))").classes("w-full gap-3"):
                pro_cards = {}
                for d in ("BUY", "SELL"):
                    with ui.element("div").classes("card"):
                        ui.label(f"Arah {d}").classes("label")
                        pv = ui.label("-").classes("value num")
                        ps_ = ui.label("").classes("sub num")
                        pro_cards[d] = (pv, ps_)
                with ui.element("div").classes("card"):
                    ui.label("Hasil (trade tutup)").classes("label")
                    pro_v = ui.label("-").classes("value num")
                    pro_s = ui.label("").classes("sub num")
            with ui.row().classes("w-full gap-3 items-start no-wrap max-md:flex-wrap"):
                with ui.element("div").classes("card flex-1 min-w-[320px]"):
                    ui.label("Trade strategi sendiri").classes("label")
                    pro_table = ui.table(columns=[
                        {"name": "tutup", "label": "Tutup", "field": "tutup", "align": "left"},
                        {"name": "arah", "label": "Arah", "field": "arah", "align": "left"},
                        {"name": "entry", "label": "Entry", "field": "entry", "align": "right"},
                        {"name": "exit", "label": "Exit", "field": "exit", "align": "right"},
                        {"name": "hasil", "label": "Hasil", "field": "hasil", "align": "left"},
                        {"name": "usd", "label": "USD", "field": "usd", "align": "right"},
                    ], rows=[], row_key="k", pagination=8).classes("w-full").props("dense flat dark")
                with ui.element("div").classes("card flex-1 min-w-[320px]"):
                    ui.label("Log strategi sendiri").classes("label")
                    pro_log = ui.label("").classes("logbox")

            def refresh_pro() -> None:
                txt, cls = file_status("pro_live.log", "pro_heartbeat")
                paused = settings.PAUSE_FILE.exists()
                pro_prog.text = f"● Strategi sendiri: {txt}" + (" · PAUSE" if paused else "")
                pro_prog.classes(replace=f"font-semibold {('warn' if paused else cls)}")
                snap = pro_snapshot()
                closed = snap.get("closed", [])
                for d, (pv, ps_) in pro_cards.items():
                    p = next((x for x in snap.get("pos", []) if x["dir"] == d), None)
                    o = next((x for x in snap.get("pend", []) if x["dir"] == d), None)
                    if p:
                        pv.text = f"{p['profit']:+.2f} USD"
                        pv.classes(replace="value num " + ("good" if p["profit"] > 0 else "bad" if p["profit"] < 0 else ""))
                        ps_.text = (f"posisi @ {p['entry']:.2f} · SL {p['sl']:.2f} · TP {p['tp']:.2f} · "
                                    f"sekarang {p['price']:.2f} · sejak {(p['time'] + WIB):%H:%M}")
                    elif o:
                        pv.text = "pending"
                        pv.classes(replace="value num warn")
                        ps_.text = f"LIMIT @ {o['price']:.2f} · SL {o['sl']:.2f} · TP {o['tp']:.2f} · {(o['time'] + WIB):%H:%M}"
                    else:
                        pv.text = "menunggu setup"
                        pv.classes(replace="value num")
                        ps_.text = "bias H1 → POI M15 → CHoCH M5"
                n = len(closed)
                tot = sum(c["usd"] for c in closed)
                w = sum(1 for c in closed if c["usd"] > 0)
                pro_v.text = f"{tot:+.2f} USD" if n else "-"
                pro_v.classes(replace="value num " + ("good" if tot > 0 else "bad" if tot < 0 else ""))
                pro_s.text = f"{n} trade · TP {w} · SL {n - w}" + (f" · winrate {100 * w / n:.0f}%" if n else "")
                pro_table.rows = [{"k": i, "tutup": (c["time"] + WIB).strftime("%d/%m %H:%M"), "arah": c["dir"],
                                   "entry": f"{c['entry']:.2f}", "exit": f"{c['exit']:.2f}", "hasil": c["why"],
                                   "usd": f"{c['usd']:+.2f}"} for i, c in enumerate(reversed(closed))]
                pro_table.update()
                log = settings.DATA_DIR / "pro_live.log"
                if log.exists():
                    lines = [ln for ln in log.read_text(encoding="utf-8", errors="replace").splitlines()
                             if "HTTP Request" not in ln][-40:]
                    pro_log.text = "\n".join(ln[11:] for ln in reversed(lines))

    def toggle_pause() -> None:
        if settings.PAUSE_FILE.exists():
            settings.PAUSE_FILE.unlink()
            ui.notify("Resume: order baru diizinkan lagi")
        else:
            settings.PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
            settings.PAUSE_FILE.write_text("pause dari dashboard")
            ui.notify("Pause: tidak ada order baru (posisi terbuka tetap jalan)")
        refresh()

    def confirm_pause() -> None:
        paused = settings.PAUSE_FILE.exists()
        with ui.dialog() as dlg, ui.card():
            ui.label("Lanjutkan order baru?" if paused else "Hentikan order baru? Posisi terbuka tetap berjalan.")
            with ui.row():
                ui.button("Ya", on_click=lambda: (dlg.close(), toggle_pause()))
                ui.button("Batal", on_click=dlg.close).props("flat")
        dlg.open()

    pause_btn.on_click(confirm_pause)

    def refresh() -> None:
        snap = mt5_snapshot()
        st_txt, st_cls = program_status()
        paused = settings.PAUSE_FILE.exists()
        prog.text = f"● Program: {st_txt}" + (" · PAUSE" if paused else "")
        prog.classes(replace=f"font-semibold {('warn' if paused else st_cls)}")
        pause_btn.text = "Resume" if paused else "Pause"
        bid = f"{snap['bid']:.2f}" if snap.get("bid") else "-"
        info.text = (f"Mode DEMO · entry {settings.TG_ENTRY_MODE}"
                     + (f" (POI {settings.TG_POI_TF})" if settings.TG_ENTRY_MODE == "POI" else "")
                     + f" · TP {settings.TG_TP_PIPS:g} / SL {settings.TG_SL_PIPS:g} pips · lot {settings.TG_LOT} · "
                     f"maks {settings.TG_MAX_POSITIONS or '∞'} posisi · XAUUSD {bid}"
                     + ("" if snap.get("algo", True) else " · ⚠️ Algo Trading MATI")
                     + ("" if snap else " · ⚠️ MT5 tidak terhubung"))
        if snap:
            v_bal.text, s_bal.text = f"${snap['balance']:,.2f}", "akun demo" if snap["demo"] else "⚠️ BUKAN DEMO"
            fl = snap["equity"] - snap["balance"]
            v_eq.text, s_eq.text = f"${snap['equity']:,.2f}", f"floating {fl:+.2f}"

        with db() as con:
            start = day_start_iso()
            day = con.execute("""SELECT COUNT(*) n, COALESCE(SUM(profit_usd),0) pnl,
                                 SUM(outcome='TP') tp, SUM(outcome='SL') sl FROM trades
                                 WHERE mode='DEMO' AND open_utc >= ?""", (start,)).fetchone()
            v_pnl.text = f"{day['pnl']:+.2f} USD"
            v_pnl.classes(replace="value num " + ("good" if day["pnl"] > 0 else "bad" if day["pnl"] < 0 else ""))
            hit = settings.TG_DAILY_PROFIT_USD > 0 and day["pnl"] >= settings.TG_DAILY_PROFIT_USD
            s_pnl.text = (f"batas rugi harian ${settings.TG_DAILY_LOSS_USD:g}"
                          + (f" · target ${settings.TG_DAILY_PROFIT_USD:g}" if settings.TG_DAILY_PROFIT_USD > 0 else "")
                          + (" · ✋ target tercapai, stop" if hit else ""))
            v_tr.text = f"{day['n']}"
            s_tr.text = f"✓ TP {day['tp'] or 0} · ✕ SL {day['sl'] or 0} · maks {settings.TG_MAX_TRADES_DAY}/hari"
            allr = con.execute("""SELECT COUNT(*) n, SUM(profit_usd > 0) w, COALESCE(SUM(profit_usd),0) p
                                  FROM trades WHERE mode='DEMO' AND close_utc IS NOT NULL""").fetchone()
            v_wr.text = f"{100 * (allr['w'] or 0) / allr['n']:.0f}%" if allr["n"] else "-"
            s_wr.text = f"{allr['n']} trade tutup · total {allr['p']:+.2f} USD"

            closed = con.execute("""SELECT close_utc, profit_usd FROM trades WHERE mode='DEMO'
                                    AND close_utc IS NOT NULL ORDER BY close_utc""").fetchall()
            cum, xs, ys = 0.0, [], []
            for r in closed:
                cum += r["profit_usd"] or 0
                xs.append((datetime.fromisoformat(r["close_utc"]) + WIB).strftime("%d/%m %H:%M"))
                ys.append(round(cum, 2))
            chart.options["xAxis"]["data"] = xs
            chart.options["series"][0]["data"] = ys
            chart.update()

            sig_table.rows = [{
                "id": r["id"], "jam": wib(r["received_utc"]),
                "sinyal": f"{r['direction']} {r['level_first']:02d}-{r['level_last']:02d}",
                "zona": f"{r['zero']:.0f} / {r['last']:.0f}" if r["zero"] else "-",
                "status": {"OPEN": "● OPEN", "PENDING": "◷ PENDING", "WAITING": "◌ TUNGGU POI", "CLOSED": "✓ CLOSED", "REJECTED": "✕ DITOLAK",
                           "EXPIRED": "⌛ HANGUS", "CANCELLED": "⊘ BATAL"}.get(r["status"], r["status"]),
                "alasan": r["status_reason"],
            } for r in con.execute("""SELECT * FROM signals WHERE received_utc >= ?
                                      ORDER BY received_utc DESC""", (start,)).fetchall()]
            sig_table.update()

            tr_table.rows = [{
                "id": r["id"], "buka": (datetime.fromisoformat(r["open_utc"]) + WIB).strftime("%d/%m %H:%M"),
                "arah": r["direction"], "entry": f"{r['entry']:.2f}",
                "exit": f"{r['exit']:.2f}" if r["exit"] else "-",
                "hasil": {"TP": "✓ TP", "SL": "✕ SL", "TP_ADMIN": "✓ TP admin"}.get(r["outcome"], r["outcome"] or "● berjalan"),
                "pips": f"{r['pips']:+.1f}" if r["pips"] is not None else "-",
                "usd": f"{r['profit_usd']:+.2f}" if r["profit_usd"] is not None else "-",
            } for r in con.execute("SELECT * FROM trades WHERE mode='DEMO' ORDER BY open_utc DESC LIMIT 200")]
            tr_table.update()

            msgs = con.execute("""SELECT date_utc, kind, sender_name, text FROM messages
                                  ORDER BY msg_id DESC LIMIT 25""").fetchall()
            feed.text = "\n".join(f"{wib(m['date_utc'])} [{m['kind']}] {m['text'].strip().splitlines()[0][:70]}"
                                  for m in msgs)

        pos_box.clear()
        with pos_box:
            positions = snap.get("positions", [])
            if not positions:
                ui.label("Tidak ada posisi terbuka").classes("sub")
            for p in positions:
                cls = "good" if p["profit"] > 0 else "bad" if p["profit"] < 0 else ""
                ui.label(f"#{p['ticket']} {p['dir']} 0.01 @ {p['entry']:.2f} · SL {p['sl']:.2f} · TP {p['tp']:.2f} · "
                         f"sekarang {p['price']:.2f} · sejak {(p['time'] + WIB):%H:%M}").classes("sub num")
                ui.label(f"{p['profit']:+.2f} USD").classes(f"value num {cls}")

        log = settings.DATA_DIR / "live.log"
        if log.exists():
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
            logbox.text = "\n".join(l[11:] for l in reversed(lines))
        refresh_swing()
        refresh_pro()

    refresh()
    ui.timer(REFRESH_SEC, refresh)


PASSWORD = os.getenv("TG_DASH_PASSWORD", "")


@ui.page("/")
def index() -> None:
    if PASSWORD and not app.storage.user.get("ok"):
        ui.navigate.to("/login")
        return
    with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-3"):
        build()


@ui.page("/login")
def login() -> None:
    ui.add_css(CSS)
    ui.dark_mode(True)

    def check() -> None:
        if pw.value == PASSWORD:
            app.storage.user["ok"] = True
            ui.navigate.to("/")
        else:
            ui.notify("Password salah", type="negative")

    with ui.card().classes("mx-auto mt-24"):
        ui.label("Telegram Scalper — login")
        pw = ui.input("Password", password=True).on("keydown.enter", check)
        ui.button("Masuk", on_click=check)


def main() -> None:
    ap = argparse.ArgumentParser(description="Dashboard monitoring")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    ui.run(host=args.host, port=args.port, title="Telegram Scalper", dark=True, reload=False, show=False,
           storage_secret=os.getenv("TG_DASH_SECRET", "tg-scalper-local"), favicon="📈")


if __name__ in {"__main__", "__mp_main__"}:
    main()
