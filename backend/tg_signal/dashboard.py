"""
Dashboard monitoring (NiceGUI) — HANYA MEMBACA database, log, dan akun MT5.
Kontrol: Pause per metode (data/PAUSE_TG, PAUSE_SWING, PAUSE_BUMI, PAUSE_PRO, PAUSE_ORB) dan
Pause semua (data/PAUSE). Pause = tanpa entry baru; posisi terbuka tetap dikelola runner.

Tab:
- Saldo        : saldo, equity, margin, total floating & floating/P-L per metode (semua magic + manual).
- Satu tab per metode dengan tampilan standar (method_tab): status · ringkasan · kartu per sub-metode ·
  profit kumulatif · trade tutup · log. Tab EA sinyal Telegram punya tambahan sinyal hari ini & pesan grup.

    python -m tg_signal.dashboard            # buka http://127.0.0.1:8080
    python -m tg_signal.dashboard --port 8081

Akses dari luar PC: pakai Tailscale + isi TG_DASH_PASSWORD di .env (RULES §6).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from nicegui import app, ui

import pandas as pd

from tg_signal import orb, settings
from tg_signal.orb_live import SPECS as ORB_SPECS

WIB = timedelta(hours=7)
REFRESH_SEC = 3
D = settings.DATA_DIR

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


# ── Konfigurasi metode ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class Method:
    id: str
    symbol: str
    magic: int
    desc: str
    log: str            # nama file log di data/
    hb: str             # nama file heartbeat di data/
    hb_sec: int = 90    # batas "AKTIF"


@dataclass
class Group:
    key: str
    tab: str
    icon: str
    title: str
    rule: str
    methods: list[Method]
    pause: Path                        # file pause metode (Pause global juga berlaku)
    pause_note: str = ""               # apa yang tetap jalan saat pause
    idle: str = "menunggu setup"
    extra: Callable[[Method], str] | None = None   # baris info tambahan per kartu
    db_trades: bool = False            # True: trade dari database sinyal (bukan dari deal MT5)
    logs: list[str] = field(default_factory=list)


def bumi_extra(m: Method) -> str:
    try:
        i = json.loads((D / "bumi_state.json").read_text(encoding="utf-8")).get("info", {}).get(m.id)
    except Exception:
        i = None
    if not i:
        return "belum ada data dari runner"
    bar = (pd.Timestamp(i["bar"]) + WIB).strftime("%d/%m %H:%M")
    m5, m13, m21, m34 = i["ma"]
    return (f"bar {bar} WIB · close {i['close']:g} · {i['state']} · EMA200 {i['slope']} · "
            f"MA 5/13/21/34: {m5:g} / {m13:g} / {m21:g} / {m34:g} · SL bila sinyal {i['sl_dist']:g}"
            + (f" · sinyal terakhir {i['last_signal']}" if i.get("last_signal") else ""))


def orb_extra(m: Method) -> str:
    spec = ORB_SPECS[m.symbol]
    cfg = spec.cfg
    hm = lambda t: pd.Timestamp(t).tz_convert("Asia/Jakarta").strftime("%H:%M")  # noqa: E731
    now = pd.Timestamp.now(tz="UTC")
    ny_now = now.tz_convert("America/New_York")
    op = orb.session_open_utc(ny_now.date())
    or_end = op + pd.Timedelta(minutes=cfg.or_min)
    brk_end = or_end + pd.Timedelta(minutes=orb.BREAK_WAIT)
    st = {}
    if spec.state_path.exists():
        try:
            st = json.loads(spec.state_path.read_text(encoding="utf-8"))
        except ValueError:
            st = {}
    today = st.get("day") == str(ny_now.date())
    rng = st.get("or") if today else None
    rng_txt = f" · range {rng[1]:.2f}–{rng[0]:.2f} (lebar {rng[0] - rng[1]:.2f})" if rng else ""
    if ny_now.weekday() >= 5:
        return "libur — pasar NY tutup (Sabtu/Minggu)"
    if now < op:
        return f"menunggu NY buka · range dibentuk {hm(op)}–{hm(or_end)} WIB"
    if now < or_end:
        return f"membentuk range sampai {hm(or_end)} WIB"
    if today and st.get("pos"):
        close_at = (st.get("pos") or {}).get("close_at")
        return "posisi terbuka" + rng_txt + (f" · tutup paksa {hm(close_at)} WIB" if close_at else "")
    if today and not st.get("done") and now < brk_end:
        return f"tunggu breakout s/d {hm(brk_end)} WIB" + rng_txt
    return "selesai hari ini" + rng_txt


def tg_extra(m: Method) -> str:
    try:
        with db() as con:
            r = con.execute("""SELECT COUNT(*) n, COALESCE(SUM(profit_usd),0) pnl FROM trades
                               WHERE mode='DEMO' AND open_utc >= ?""", (day_start_iso(),)).fetchone()
    except Exception:
        return ""
    hit = settings.TG_DAILY_PROFIT_USD > 0 and r["pnl"] >= settings.TG_DAILY_PROFIT_USD
    return (f"hari ini {r['n']} trade {r['pnl']:+.2f} USD · maks {settings.TG_MAX_TRADES_DAY}/hari · "
            f"batas rugi ${settings.TG_DAILY_LOSS_USD:g}"
            + (f" · target ${settings.TG_DAILY_PROFIT_USD:g}" if settings.TG_DAILY_PROFIT_USD > 0 else "")
            + (" · ✋ target tercapai, stop" if hit else ""))


GROUPS = [
    Group("tg", "EA sinyal Telegram", "send", "Scalping sinyal Telegram — XAUUSD",
          f"Entry {settings.TG_ENTRY_MODE}"
          + (f" (POI {settings.TG_POI_TF})" if settings.TG_ENTRY_MODE == "POI" else "")
          + f" · TP {settings.TG_TP_PIPS:g} / SL {settings.TG_SL_PIPS:g} pips · lot {settings.TG_LOT} · "
          f"maks {settings.TG_MAX_POSITIONS or '∞'} posisi · admin TP dari chat",
          [Method("TG_SIGNAL", settings.SYMBOL, settings.TG_MAGIC, "sinyal topik Scalping", "live.log",
                  "heartbeat", 60)],
          pause=settings.PAUSE_TG, pause_note="posisi & pending yang sudah ada tetap dikelola",
          idle="menunggu sinyal", extra=tg_extra),
    Group("swing", "Swing Donchian", "trending_up", "Swing trend-following — XAUUSD · BTCUSD · USDJPY",
          "Donchian breakout + filter tren D1 · tanpa TP, trailing ATR · risiko 0,5%/trade "
          "(skip bila lot minimum > 2% saldo) · 1 posisi per metode",
          [Method(i, s, mg, desc, "swing_live.log", "swing_heartbeat") for i, s, desc, mg in (
              ("XAU_D1_DON20", "XAUUSD", "Donchian D1 20 · trail 3 ATR", 26111201),
              ("XAU_H4_DON55", "XAUUSD", "Donchian H4 55 · trail 4 ATR", 26111202),
              ("BTC_H4_DON55", "BTCUSD", "Donchian H4 55 · trail 4 ATR", 26111203),
              ("JPY_H4_DON55", "USDJPY", "Donchian H4 55 · trail 4 ATR", 26111204))],
          pause=settings.PAUSE_SWING, pause_note="trailing tetap jalan", idle="menunggu breakout"),
    Group("bumi", "BUMI 4 MA", "show_chart", "BUMI 4 MA — XAUUSD H4 & H1",
          "SMA 5/13/21/34 · entry saat MA5 pindah ke atas/bawah ketiga MA + EMA200 searah (10 bar) · "
          "SL 3 ATR14 · breakeven setelah +0,5R · tanpa TP, exit saat MA5 cross balik · risiko 0,5%/trade · "
          "1 posisi per metode",
          [Method(i, "XAUUSD", mg, desc, "bumi_live.log", "bumi_heartbeat") for i, desc, mg in (
              ("XAU_H4_BUMI", "BUMI H4 · cross langsung · SL 3 ATR", 26111701),
              ("XAU_H1_BUMI", "BUMI H1 · cross langsung · SL 3 ATR", 26111702))],
          pause=settings.PAUSE_BUMI, pause_note="exit cross MA tetap jalan", idle="menunggu MA5 cross",
          extra=bumi_extra),
    Group("pro", "SMC Top-Down", "insights", "SMC Top-Down — XAUUSD",
          f"Bias EMA50 H1 (kemiringan > 0,1 ATR) · POI M15 FVG/OB/IFVG · konfirmasi CHoCH M5 · entry FVG M5 · "
          f"RR 1:3 · SL maks 100 pips · lot {settings.PRO_LOT} · tanpa entry ±{settings.PRO_NEWS_MIN:g} mnt "
          "news USD",
          [Method("XAU_SMC_TD", settings.SYMBOL, settings.PRO_MAGIC, "bias H1 → POI M15 → CHoCH M5",
                  "pro_live.log", "pro_heartbeat")],
          pause=settings.PAUSE_PRO, pause_note="posisi & pending yang sudah ada tetap jalan",
          idle="menunggu setup"),
    Group("orb", "ORB NY", "schedule", "ORB New York — Opening Range Breakout",
          "Range setelah NY buka 09:30 New York (DST otomatis) · breakout = close M5 di luar range ≤ 2 jam · "
          "entry market · SL sisi seberang range · TP 2R · tutup paksa 6 jam setelah buka · "
          "maks 1 trade/hari per instrumen",
          [Method(f"ORB_{s.symbol}", s.symbol, s.magic,
                  f"range {s.cfg.or_min} mnt · "
                  + ("searah bias EMA50 H1" if s.cfg.bias == "with" else "tanpa filter bias")
                  + f" · TP {s.cfg.tp}R · {s.lot_text}", s.log_path.name, s.heartbeat.name)
           for s in ORB_SPECS.values()],
          pause=settings.PAUSE_ORB, pause_note="posisi terbuka & tutup paksa tetap jalan",
          idle="maks 1 trade per hari", extra=orb_extra),
]
ALL_METHODS = [m for g in GROUPS for m in g.methods]
GROUP_OF = {m.magic: g for g in GROUPS for m in g.methods}


# ── Data ────────────────────────────────────────────────────────────────────
def db() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{settings.DB_PATH}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def wib(iso: str | None) -> str:
    if not iso:
        return "-"
    return (datetime.fromisoformat(iso) + WIB).strftime("%H:%M:%S")


def day_start_utc() -> datetime:
    now = datetime.now(timezone.utc) + WIB
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc) - WIB


def day_start_iso() -> str:
    return day_start_utc().isoformat(timespec="seconds")


def snapshot() -> dict:
    """Satu kali baca MT5 per refresh: akun, semua posisi & pending, deal tutup 365 hari (dikelompokkan per
    posisi). Gagal → dict kosong (dashboard tetap jalan)."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return {}
        acc = mt5.account_info()
        term = mt5.terminal_info()
        pos = [{"ticket": p.ticket, "magic": p.magic, "symbol": p.symbol, "dir": "BUY" if p.type == 0 else "SELL",
                "lot": p.volume, "entry": p.price_open, "sl": p.sl, "tp": p.tp, "price": p.price_current,
                "profit": p.profit + p.swap, "time": datetime.fromtimestamp(p.time, timezone.utc)}
               for p in mt5.positions_get() or ()]
        pend = [{"ticket": o.ticket, "magic": o.magic, "symbol": o.symbol,
                 "dir": "BUY" if o.type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP) else "SELL",
                 "price": o.price_open, "sl": o.sl, "tp": o.tp,
                 "time": datetime.fromtimestamp(o.time_setup, timezone.utc)}
                for o in mt5.orders_get() or ()]
        now = datetime.now(timezone.utc)
        deals = mt5.history_deals_get(now - timedelta(days=365), now + timedelta(days=1)) or ()
        by_pos: dict = {}
        for d in deals:
            if d.position_id:
                by_pos.setdefault(d.position_id, []).append(d)
        why = {mt5.DEAL_REASON_TP: "TP", mt5.DEAL_REASON_SL: "SL", mt5.DEAL_REASON_EXPERT: "tutup EA"}
        closed = []
        for ds in by_pos.values():
            ins = [d for d in ds if d.entry == mt5.DEAL_ENTRY_IN]
            outs = [d for d in ds if d.entry == mt5.DEAL_ENTRY_OUT]
            if not ins or not outs or sum(d.volume for d in outs) + 1e-9 < sum(d.volume for d in ins):
                continue                                      # masih terbuka (sebagian) → bukan trade tutup
            o = outs[-1]
            closed.append({"magic": ins[0].magic, "symbol": ins[0].symbol,
                           "time": datetime.fromtimestamp(o.time, timezone.utc),
                           "dir": "BUY" if ins[0].type == mt5.DEAL_TYPE_BUY else "SELL",
                           "entry": ins[0].price, "exit": o.price, "why": why.get(o.reason, "manual/lain"),
                           "usd": sum(x.profit + x.swap + x.commission for x in ds)})
        closed.sort(key=lambda x: x["time"])
        return {"balance": acc.balance, "equity": acc.equity, "margin": acc.margin,
                "free": acc.margin_free, "level": acc.margin_level, "currency": acc.currency,
                "demo": acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO, "algo": term.trade_allowed,
                "server": acc.server, "pos": pos, "pend": pend, "closed": closed}
    except Exception:
        return {}


def file_status(m: Method) -> tuple[str, str]:
    log = D / m.log
    if not log.exists():
        return "BELUM PERNAH JALAN", "bad"
    age = datetime.now().timestamp() - log.stat().st_mtime
    hb = D / m.hb
    if hb.exists():
        age = min(age, datetime.now().timestamp() - hb.stat().st_mtime)
    if age < m.hb_sec:
        return "AKTIF", "good"
    mins = int(age // 60)
    return (f"diam {mins} mnt", "warn") if age < 3600 else ("MATI", "bad")


LOG_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:,\d+)?(Z)?\s+(?:INFO\s+)?(.*)$")


def read_logs(names: list[str], n: int = 40) -> str:
    """Gabung beberapa log (terbaru di atas), jam diseragamkan ke WIB 'dd/mm HH:MM:SS'.
    Log berakhiran Z (swing/BUMI) = UTC; log logging Python = jam lokal PC (WIB)."""
    rows = []
    for name in names:
        p = D / name
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]:
            if "HTTP Request" in ln:
                continue
            mt = LOG_RE.match(ln)
            if not mt:
                continue
            t = datetime.strptime(mt.group(1), "%Y-%m-%d %H:%M:%S") + (WIB if mt.group(2) else timedelta())
            rows.append((t, mt.group(3)))
    rows.sort(key=lambda r: r[0], reverse=True)
    return "\n".join(f"{t:%d/%m %H:%M:%S} {txt}" for t, txt in rows[:n])


def px(x: float) -> str:
    return f"{x:,.2f}" if abs(x) >= 1000 else f"{x:.2f}" if abs(x) >= 10 else f"{x:.4f}"


def tone(x: float) -> str:
    return "good" if x > 0.005 else "bad" if x < -0.005 else ""


def usd(x: float) -> str:
    return f"{x:+,.2f}"


# ── Komponen UI ─────────────────────────────────────────────────────────────
def stat(label: str):
    with ui.element("div").classes("card"):
        ui.label(label).classes("label")
        v = ui.label("-").classes("value num")
        s = ui.label("").classes("sub num")
    return v, s


def set_val(lbl, text: str, cls: str = "") -> None:
    lbl.text = text
    lbl.classes(replace=f"value num {cls}")


def cum_chart():
    return ui.echart({
        "backgroundColor": "transparent",
        "grid": {"left": 56, "right": 16, "top": 16, "bottom": 28},
        "tooltip": {"trigger": "axis", "backgroundColor": C["surface"], "borderColor": C["axis"],
                    "textStyle": {"color": C["ink"]}},
        "xAxis": {"type": "category", "data": [], "axisLine": {"lineStyle": {"color": C["axis"]}},
                  "axisLabel": {"color": C["muted"]}},
        "yAxis": {"type": "value", "splitLine": {"lineStyle": {"color": C["grid"]}},
                  "axisLabel": {"color": C["muted"]}},
        "series": [{"type": "line", "name": "Profit kumulatif (USD)", "data": [], "showSymbol": False,
                    "lineStyle": {"width": 2, "color": C["series"]}, "itemStyle": {"color": C["series"]},
                    "markLine": {"silent": True, "symbol": "none", "lineStyle": {"color": C["axis"], "type": "solid"},
                                 "data": [{"yAxis": 0}], "label": {"show": False}}}],
    }).classes("w-full h-56")


TRADE_COLS = [
    {"name": "tutup", "label": "Tutup (WIB)", "field": "tutup", "align": "left"},
    {"name": "metode", "label": "Metode", "field": "metode", "align": "left"},
    {"name": "arah", "label": "Arah", "field": "arah", "align": "left"},
    {"name": "entry", "label": "Entry", "field": "entry", "align": "right"},
    {"name": "exit", "label": "Exit", "field": "exit", "align": "right"},
    {"name": "hasil", "label": "Hasil", "field": "hasil", "align": "left"},
    {"name": "usd", "label": "USD", "field": "usd", "align": "right"},
]


def pause_controls(g: Group, refresh_all: Callable[[], None]):
    """Tombol pause metode (file g.pause). Return tombolnya."""
    def toggle() -> None:
        if g.pause.exists():
            g.pause.unlink()
            ui.notify(f"{g.tab}: entry baru diizinkan lagi")
        else:
            g.pause.write_text("pause dari dashboard")
            ui.notify(f"{g.tab} pause: tanpa entry baru ({g.pause_note})")
        refresh_all()

    def confirm() -> None:
        with ui.dialog() as dlg, ui.card():
            ui.label(f"Lanjutkan entry {g.tab}?" if g.pause.exists()
                     else f"Hentikan entry {g.tab} baru? Posisi terbuka tetap berjalan ({g.pause_note}).")
            with ui.row():
                ui.button("Ya", on_click=lambda: (dlg.close(), toggle()))
                ui.button("Batal", on_click=dlg.close).props("flat")
        dlg.open()

    return ui.button("", on_click=confirm).props("unelevated")


def method_tab(g: Group, refresh_all: Callable[[], None]) -> Callable[[dict], None]:
    """Tampilan standar satu metode. Return refresh(snap)."""
    with ui.row().classes("w-full items-start justify-between no-wrap max-md:flex-wrap"):
        with ui.column().classes("gap-0 flex-1"):
            ui.label(g.title).classes("text-xl font-semibold")
            ui.label(g.rule).classes("sub")
        with ui.row().classes("items-center gap-3 no-wrap"):
            prog = ui.label("").classes("font-semibold")
            btn = pause_controls(g, refresh_all)

    with ui.grid(columns="repeat(auto-fit, minmax(190px, 1fr))").classes("w-full gap-3"):
        v_fl, s_fl = stat("Floating")
        v_day, s_day = stat("Tutup hari ini")
        v_tot, s_tot = stat("Total tutup")
        v_wr, s_wr = stat("Win rate")

    cards = {}
    with ui.grid(columns="repeat(auto-fit, minmax(300px, 1fr))").classes("w-full gap-3"):
        for m in g.methods:
            with ui.element("div").classes("card"):
                with ui.row().classes("w-full items-center justify-between no-wrap"):
                    ui.label(f"{m.symbol} · {m.id}").classes("label")
                    st = ui.label("").classes("sub")
                ui.label(f"{m.desc} · magic {m.magic}").classes("sub")
                v = ui.label("-").classes("value num")
                body = ui.column().classes("gap-0")
                ex = ui.label("").classes("sub num") if g.extra else None
                cards[m.magic] = (st, v, body, ex)

    with ui.element("div").classes("card w-full"):
        ui.label("Profit kumulatif (USD, trade tutup)").classes("label")
        chart = cum_chart()
        no_trade = ui.label("Belum ada trade tutup").classes("sub")

    with ui.row().classes("w-full gap-3 items-start no-wrap max-md:flex-wrap"):
        with ui.element("div").classes("card flex-1 min-w-[320px]"):
            ui.label("Trade tutup").classes("label")
            table = ui.table(columns=TRADE_COLS, rows=[], row_key="k", pagination=8) \
                .classes("w-full").props("dense flat dark")
        with ui.element("div").classes("card flex-1 min-w-[320px]"):
            ui.label("Log").classes("label")
            log_box = ui.label("").classes("logbox")

    logs = g.logs or list(dict.fromkeys(m.log for m in g.methods))
    magics = {m.magic: m for m in g.methods}

    def refresh(snap: dict) -> None:
        own, glob = g.pause.exists(), settings.PAUSE_FILE.exists()
        stats = {}
        for m in g.methods:
            stats.setdefault((m.log, m.hb), (m, file_status(m)))
        worst = min((s for _, s in stats.values()), key=lambda s: {"bad": 0, "warn": 1, "good": 2}[s[1]])
        prog.text = f"● {worst[0]}" + (" · PAUSE" if own else "") + (" · PAUSE global" if glob else "")
        prog.classes(replace=f"font-semibold {'warn' if own or glob else worst[1]}")
        btn.text = "Resume" if own else "Pause"
        btn.props(f"color={'warning' if own else 'primary'}")

        pos = [p for p in snap.get("pos", []) if p["magic"] in magics]
        pend = [o for o in snap.get("pend", []) if o["magic"] in magics]
        closed = [c for c in snap.get("closed", []) if c["magic"] in magics]
        start = day_start_utc()
        fl = sum(p["profit"] for p in pos)
        today = [c for c in closed if c["time"] >= start]
        tot = sum(c["usd"] for c in closed)
        win = [c for c in closed if c["usd"] > 0]
        loss = [c for c in closed if c["usd"] <= 0]
        if not snap:
            set_val(v_fl, "MT5 ?", "warn")
            s_fl.text = "MT5 tidak terhubung"
        else:
            set_val(v_fl, f"{usd(fl)} USD" if pos else "0.00 USD", tone(fl))
            s_fl.text = f"{len(pos)} posisi" + (f" · {len(pend)} pending" if pend else "")
        d_tot = sum(c["usd"] for c in today)
        set_val(v_day, f"{usd(d_tot)} USD" if today else "-", tone(d_tot))
        s_day.text = f"{len(today)} trade · untung {sum(c['usd'] > 0 for c in today)}"
        set_val(v_tot, f"{usd(tot)} USD" if closed else "-", tone(tot))
        s_tot.text = f"{len(closed)} trade (365 hari)"
        set_val(v_wr, f"{100 * len(win) / len(closed):.0f}%" if closed else "-")
        avg_w = sum(c["usd"] for c in win) / len(win) if win else 0
        avg_l = sum(c["usd"] for c in loss) / len(loss) if loss else 0
        s_wr.text = (f"untung {len(win)} · rugi {len(loss)} · rata² {avg_w:+.2f} / {avg_l:+.2f}" if closed else "")

        for m in g.methods:
            st, v, body, ex = cards[m.magic]
            txt, cls = file_status(m)
            st.text = f"● {txt}"
            st.classes(replace=f"sub {cls}")
            mp = [p for p in pos if p["magic"] == m.magic]
            mo = [o for o in pend if o["magic"] == m.magic]
            mc = [c for c in closed if c["magic"] == m.magic]
            mt = sum(c["usd"] for c in mc)
            body.clear()
            with body:
                if mp:
                    f = sum(p["profit"] for p in mp)
                    set_val(v, f"{usd(f)} USD", tone(f))
                    for p in mp:
                        ui.label(f"#{p['ticket']} {p['dir']} {p['lot']:g} @ {px(p['entry'])} · SL {px(p['sl'])}"
                                 + (f" · TP {px(p['tp'])}" if p["tp"] else "") + f" · sekarang {px(p['price'])} · "
                                 f"sejak {(p['time'] + WIB):%d/%m %H:%M}").classes("sub num")
                elif mo:
                    set_val(v, "pending", "warn")
                else:
                    set_val(v, "tanpa posisi")
                    ui.label(g.idle).classes("sub")
                for o in mo:
                    ui.label(f"LIMIT {o['dir']} @ {px(o['price'])} · SL {px(o['sl'])} · TP {px(o['tp'])} · "
                             f"{(o['time'] + WIB):%d/%m %H:%M}").classes("sub num warn")
                ui.label(f"tutup: {len(mc)} trade · {usd(mt)} USD").classes("sub num")
            if ex:
                ex.text = g.extra(m)

        cum, xs, ys = 0.0, [], []
        for c in closed:
            cum += c["usd"]
            xs.append((c["time"] + WIB).strftime("%d/%m %H:%M"))
            ys.append(round(cum, 2))
        chart.set_visibility(bool(ys))
        no_trade.set_visibility(not ys)
        if chart.options["series"][0]["data"] != ys:
            chart.options["xAxis"]["data"] = xs
            chart.options["series"][0]["data"] = ys
            chart.update()
        names = {m.magic: m.id for m in g.methods}
        table.rows = [{"k": i, "tutup": (c["time"] + WIB).strftime("%d/%m %H:%M"), "metode": names[c["magic"]],
                       "arah": c["dir"], "entry": px(c["entry"]), "exit": px(c["exit"]),
                       "hasil": c["why"], "usd": usd(c["usd"])} for i, c in enumerate(reversed(closed))]
        table.update()
        log_box.text = read_logs(logs)

    return refresh


def telegram_extra() -> Callable[[], None]:
    """Bagian khusus EA sinyal Telegram: sinyal hari ini & pesan grup terakhir."""
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
            ui.label("Pesan Telegram terakhir").classes("label")
            feed = ui.label("").classes("logbox")

    status_txt = {"NEW": "◌ BARU", "OPEN": "● OPEN", "PENDING": "◷ PENDING", "WAITING": "◌ TUNGGU POI",
                  "CLOSED": "✓ CLOSED", "REJECTED": "✕ DITOLAK", "EXPIRED": "⌛ HANGUS", "CANCELLED": "⊘ BATAL"}

    def refresh() -> None:
        try:
            con = db()
        except sqlite3.Error:
            return
        with con:
            sig_table.rows = [{
                "id": r["id"], "jam": wib(r["received_utc"]),
                "sinyal": f"{r['direction']} {r['level_first']:02d}-{r['level_last']:02d}"
                          + (" ✎" if r["edit_utc"] else ""),
                "zona": f"{r['zero']:.0f} / {r['last']:.0f}" if r["zero"] else "-",
                "status": status_txt.get(r["status"], r["status"]),
                "alasan": r["status_reason"],
            } for r in con.execute("""SELECT s.*, m.edit_utc FROM signals s JOIN messages m ON m.id = s.message_id
                                      WHERE s.received_utc >= ? ORDER BY s.received_utc DESC""",
                                   (day_start_iso(),)).fetchall()]
            sig_table.update()
            msgs = con.execute("""SELECT date_utc, edit_utc, kind, text FROM messages
                                  ORDER BY msg_id DESC LIMIT 25""").fetchall()
            feed.text = "\n".join(f"{wib(m['date_utc'])} [{m['kind']}]{' ✎' if m['edit_utc'] else ''} "
                                  f"{m['text'].strip().splitlines()[0][:70]}" for m in msgs)
        con.close()

    return refresh


def balance_tab() -> Callable[[dict], None]:
    """Tab Saldo: akun + floating & P/L per metode."""
    with ui.row().classes("w-full items-center justify-between"):
        with ui.column().classes("gap-0"):
            ui.label("Saldo & floating").classes("text-xl font-semibold")
            acc_info = ui.label("").classes("sub")
    with ui.grid(columns="repeat(auto-fit, minmax(190px, 1fr))").classes("w-full gap-3"):
        v_bal, s_bal = stat("Saldo")
        v_eq, s_eq = stat("Equity")
        v_fl, s_fl = stat("Total floating")
        v_day, s_day = stat("Tutup hari ini")
        v_mg, s_mg = stat("Margin")
    with ui.element("div").classes("card w-full"):
        ui.label("Floating & hasil per metode").classes("label")
        table = ui.table(columns=[
            {"name": "metode", "label": "Metode", "field": "metode", "align": "left"},
            {"name": "grup", "label": "Grup", "field": "grup", "align": "left"},
            {"name": "status", "label": "Runner", "field": "status", "align": "left"},
            {"name": "posisi", "label": "Posisi", "field": "posisi", "align": "left"},
            {"name": "floating", "label": "Floating", "field": "floating", "align": "right"},
            {"name": "hari", "label": "Tutup hari ini", "field": "hari", "align": "right"},
            {"name": "total", "label": "Total tutup", "field": "total", "align": "right"},
        ], rows=[], row_key="k").classes("w-full").props("dense flat dark hide-pagination")
        table.props(":pagination='{rowsPerPage: 0}'")
        for col in ("floating", "hari", "total"):
            table.add_slot(f"body-cell-{col}", f"""
                <q-td :props="props" class="num" :class="props.row.{col}_c"
                      :style="props.row.k === 'tot' ? 'font-weight:600' : ''">{{{{ props.value }}}}</q-td>""")
        table.add_slot("body-cell-status", """
            <q-td :props="props" :class="props.row.status_c">{{ props.value }}</q-td>""")
        table.add_slot("body-cell-metode", """
            <q-td :props="props" :style="props.row.k === 'tot' ? 'font-weight:600' : ''">{{ props.value }}</q-td>""")

    def refresh(snap: dict) -> None:
        if not snap:
            acc_info.text = "⚠️ MT5 tidak terhubung"
            return
        acc_info.text = (f"{snap['server']} · {'akun DEMO' if snap['demo'] else '⚠️ BUKAN DEMO'} · "
                         f"{snap['currency']}" + ("" if snap["algo"] else " · ⚠️ Algo Trading MATI"))
        pos, closed = snap["pos"], snap["closed"]
        start = day_start_utc()
        fl = sum(p["profit"] for p in pos)
        set_val(v_bal, f"${snap['balance']:,.2f}")
        s_bal.text = "akun demo" if snap["demo"] else "⚠️ BUKAN DEMO"
        set_val(v_eq, f"${snap['equity']:,.2f}")
        s_eq.text = f"selisih {usd(snap['equity'] - snap['balance'])}"
        set_val(v_fl, f"{usd(fl)} USD", tone(fl))
        s_fl.text = f"{len(pos)} posisi · {len(snap['pend'])} pending"
        today = [c for c in closed if c["time"] >= start]
        d_tot = sum(c["usd"] for c in today)
        set_val(v_day, f"{usd(d_tot)} USD" if today else "-", tone(d_tot))
        s_day.text = f"{len(today)} trade semua metode"
        set_val(v_mg, f"${snap['margin']:,.2f}")
        s_mg.text = f"bebas ${snap['free']:,.2f}" + (f" · level {snap['level']:,.0f}%" if snap["margin"] else "")

        rows = []
        known = {m.magic for m in ALL_METHODS}
        def runner(m: Method) -> tuple[str, str]:
            txt, cls = file_status(m)
            if settings.is_paused(GROUP_OF[m.magic].pause):
                return f"{txt} · PAUSE", "warn"
            return txt, cls

        entries = [(m.id, GROUP_OF[m.magic].tab, runner(m), lambda x, mg=m.magic: x["magic"] == mg)
                   for m in ALL_METHODS]
        entries.append(("Manual / lain", "-", ("-", ""), lambda x: x["magic"] not in known))
        for i, (name, grp, (stt, stc), sel) in enumerate(entries):
            mp = [p for p in pos if sel(p)]
            mc = [c for c in closed if sel(c)]
            md = [c for c in mc if c["time"] >= start]
            if name == "Manual / lain" and not mp and not mc:
                continue
            f, dt, tt = sum(p["profit"] for p in mp), sum(c["usd"] for c in md), sum(c["usd"] for c in mc)
            rows.append({"k": i, "metode": name, "grup": grp, "status": stt, "status_c": stc,
                         "posisi": ", ".join(f"{p['dir']} {p['lot']:g} {p['symbol']}" for p in mp) or "-",
                         "floating": usd(f) if mp else "-", "floating_c": tone(f),
                         "hari": usd(dt) if md else "-", "hari_c": tone(dt),
                         "total": f"{usd(tt)} ({len(mc)})" if mc else "-", "total_c": tone(tt)})
        tt_all = sum(c["usd"] for c in closed)
        rows.append({"k": "tot", "metode": "TOTAL", "grup": "", "status": "", "posisi": f"{len(pos)} posisi",
                     "floating": usd(fl), "floating_c": tone(fl), "hari": usd(d_tot), "hari_c": tone(d_tot),
                     "total": f"{usd(tt_all)} ({len(closed)})", "total_c": tone(tt_all)})
        table.rows = rows
        table.update()

    return refresh


def build(start_tab: str = "") -> None:
    ui.add_css(CSS)
    ui.dark_mode(True)

    with ui.row().classes("w-full items-center justify-between"):
        with ui.column().classes("gap-0"):
            ui.label("Trading monitor").classes("text-2xl font-semibold")
            head = ui.label("").classes("sub num")
        with ui.row().classes("items-center gap-3"):
            g_state = ui.label("").classes("font-semibold")
            pause_btn = ui.button("").props("unelevated")

    with ui.tabs().classes("w-full").props("align=left inline-label") as tabs:
        t_bal = ui.tab("Saldo", icon="account_balance_wallet")
        tab_of = {g.key: ui.tab(g.tab, icon=g.icon) for g in GROUPS}

    refreshers: list[Callable[[dict], None]] = []
    with ui.tab_panels(tabs, value=tab_of.get(start_tab, t_bal)).classes("w-full").style("background: transparent"):
        with ui.tab_panel(t_bal).classes("p-0 gap-3"):
            refreshers.append(balance_tab())
        for g in GROUPS:
            with ui.tab_panel(tab_of[g.key]).classes("p-0 gap-3"):
                refreshers.append(method_tab(g, lambda: refresh()))
                if g.key == "tg":
                    tg_ref = telegram_extra()
                    refreshers.append(lambda _snap: tg_ref())

    def toggle_pause() -> None:
        if settings.PAUSE_FILE.exists():
            settings.PAUSE_FILE.unlink()
            ui.notify("Resume global: metode yang tidak di-pause sendiri boleh entry lagi")
        else:
            settings.PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
            settings.PAUSE_FILE.write_text("pause dari dashboard")
            ui.notify("Pause semua metode: tidak ada entry baru (posisi terbuka tetap dikelola)")
        refresh()

    def confirm_pause() -> None:
        paused = settings.PAUSE_FILE.exists()
        with ui.dialog() as dlg, ui.card():
            ui.label("Cabut pause global? Metode yang di-pause sendiri tetap pause." if paused
                     else "Pause SEMUA metode? Tidak ada entry baru; posisi terbuka, SL/TP & trailing tetap berjalan.")
            with ui.row():
                ui.button("Ya", on_click=lambda: (dlg.close(), toggle_pause()))
                ui.button("Batal", on_click=dlg.close).props("flat")
        dlg.open()

    pause_btn.on_click(confirm_pause)

    def refresh() -> None:
        snap = snapshot()
        paused = settings.PAUSE_FILE.exists()
        own = [g.tab for g in GROUPS if g.pause.exists()]
        g_state.text = ("● PAUSE semua metode" if paused
                        else f"● pause: {', '.join(own)}" if own else "")
        g_state.classes(replace="font-semibold warn")
        pause_btn.text = "Resume semua" if paused else "Pause semua"
        pause_btn.props(f"color={'warning' if paused else 'primary'}")
        if snap:
            fl = sum(p["profit"] for p in snap["pos"])
            head.text = (f"saldo ${snap['balance']:,.2f} · equity ${snap['equity']:,.2f} · floating {usd(fl)} · "
                         + ("DEMO" if snap["demo"] else "⚠️ BUKAN DEMO")
                         + ("" if snap["algo"] else " · ⚠️ Algo Trading MATI"))
        else:
            head.text = "⚠️ MT5 tidak terhubung"
        for f in refreshers:
            try:
                f(snap)
            except Exception as e:  # satu panel error tidak boleh mematikan dashboard
                print(f"refresh gagal: {e!r}")

    refresh()
    ui.timer(REFRESH_SEC, refresh)


PASSWORD = os.getenv("TG_DASH_PASSWORD", "")


@ui.page("/")
def index(tab: str = "") -> None:
    """`/?tab=tg|swing|bumi|pro|orb` membuka langsung tab metode itu."""
    if PASSWORD and not app.storage.user.get("ok"):
        ui.navigate.to("/login")
        return
    with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-3"):
        build(tab)


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
        ui.label("Trading monitor — login")
        pw = ui.input("Password", password=True).on("keydown.enter", check)
        ui.button("Masuk", on_click=check)


def main() -> None:
    ap = argparse.ArgumentParser(description="Dashboard monitoring")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    ui.run(host=args.host, port=args.port, title="Trading monitor", dark=True, reload=False, show=False,
           storage_secret=os.getenv("TG_DASH_SECRET", "tg-scalper-local"), favicon="📈")


if __name__ in {"__main__", "__mp_main__"}:
    main()
