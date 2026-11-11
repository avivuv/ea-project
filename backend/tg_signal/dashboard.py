"""
Dashboard monitoring (NiceGUI) — HANYA MEMBACA database, log, dan akun MT5.
Satu-satunya kontrol: Pause/Resume (membuat/menghapus file data/PAUSE).

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
    with ui.row().classes("w-full items-center justify-between"):
        with ui.column().classes("gap-0"):
            ui.label("Telegram Scalper — XAUUSD").classes("text-xl font-semibold")
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
        info.text = (f"Mode DEMO · TP {settings.TG_TP_PIPS:g} / SL {settings.TG_SL_PIPS:g} pips · lot {settings.TG_LOT} · "
                     f"maks {settings.TG_MAX_POSITIONS} posisi · XAUUSD {bid}"
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
            s_pnl.text = f"batas rugi harian ${settings.TG_DAILY_LOSS_USD:g}"
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
                "status": {"OPEN": "● OPEN", "CLOSED": "✓ CLOSED", "REJECTED": "✕ DITOLAK"}.get(r["status"], r["status"]),
                "alasan": r["status_reason"],
            } for r in con.execute("""SELECT * FROM signals WHERE received_utc >= ?
                                      ORDER BY received_utc DESC""", (start,)).fetchall()]
            sig_table.update()

            tr_table.rows = [{
                "id": r["id"], "buka": (datetime.fromisoformat(r["open_utc"]) + WIB).strftime("%d/%m %H:%M"),
                "arah": r["direction"], "entry": f"{r['entry']:.2f}",
                "exit": f"{r['exit']:.2f}" if r["exit"] else "-",
                "hasil": {"TP": "✓ TP", "SL": "✕ SL"}.get(r["outcome"], r["outcome"] or "● berjalan"),
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
