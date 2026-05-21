"""
Generate backtest analysis charts: equity curve, drawdown, monthly returns, trade distribution.
Usage:
  python generate_charts.py                      # all pairs
  python generate_charts.py --pair XAUUSD        # single pair
"""
import argparse
import json
import os
import sys
import datetime
import math

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.colors import TwoSlopeNorm
import matplotlib.ticker as mticker

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "charts")
os.makedirs(OUTPUT_DIR, exist_ok=True)

PAIRS = ["XAUUSD", "USDJPY"]
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
CSV_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

INITIAL_EQUITY = 1000.0

# step → label TF yang ditampilkan di chart
STEP_LABEL = {
    1:  "M15 (tiap bar)",
    4:  "H1 (step=4)",
    8:  "H2 (step=8)",
    16: "H4 (step=16)",
    24: "H6 (step=24)",
    96: "D1 (step=96)",
}


def load_trades(pair: str) -> list:
    path = os.path.join(LOG_DIR, f"backtest_{pair}.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_m15_dates(pair: str) -> pd.Series:
    """Load M15 bar timestamps from CSV."""
    candidates = [
        os.path.join(CSV_DIR, f"{pair}_GMT+0_NO-DST_M15.csv"),
        os.path.join(CSV_DIR, f"{pair}_M15.csv"),
    ]
    for p in candidates:
        if os.path.exists(p):
            df = pd.read_csv(p, header=None,
                             names=["date","time","open","high","low","close","volume"])
            df["datetime"] = pd.to_datetime(df["date"] + " " + df["time"])
            return df["datetime"]
    return pd.Series(dtype="datetime64[ns]")


def build_equity_curve(trades: list, dates: pd.Series) -> pd.DataFrame:
    eq = INITIAL_EQUITY
    rows = []
    for t in sorted(trades, key=lambda x: x["close_idx"]):
        eq *= (1 + t["pnl_pct"] / 100)
        idx = t["close_idx"]
        dt = dates.iloc[idx] if idx < len(dates) else None
        rows.append({"datetime": dt, "equity": eq, "pnl_pct": t["pnl_pct"],
                     "strategy": t["strategy_id"], "direction": t["direction"]})
    return pd.DataFrame(rows)


def compute_drawdown(equity_series: pd.Series) -> pd.Series:
    peak = equity_series.cummax()
    return (equity_series - peak) / peak * 100


def monthly_returns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["year"]  = df["datetime"].dt.year
    df["month"] = df["datetime"].dt.month
    monthly = df.groupby(["year", "month"])["pnl_pct"].sum().reset_index()
    pivot = monthly.pivot(index="year", columns="month", values="pnl_pct").fillna(0)
    return pivot


def sharpe_ratio(equity_series: pd.Series, periods_per_year: float = 252) -> float:
    returns = equity_series.pct_change().dropna()
    if returns.std() == 0:
        return 0.0
    return (returns.mean() / returns.std()) * math.sqrt(periods_per_year)


def strategy_label(trades: list) -> str:
    """Build short label from unique strategy IDs in the trade log."""
    ids = []
    seen = set()
    for t in trades:
        s = t.get("strategy_id", "?")
        if s not in seen:
            seen.add(s)
            ids.append(s)
    return " + ".join(ids) if ids else "Unknown"


def generate_pair_chart(pair: str, step: int = 4, initial_equity: float = INITIAL_EQUITY):
    trades = load_trades(pair)
    dates  = load_m15_dates(pair)

    strat_label = strategy_label(trades)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    # Build short slug for filename: "EMA_TREND + FVG" → "EMA_FVG"
    strat_slug = "_".join(
        s.replace("_TREND", "").replace("_", "") for s in strat_label.split(" + ")
    )
    tf_label  = STEP_LABEL.get(step, f"step={step}")
    step_slug = f"step{step}"

    closed = [t for t in trades if t["close_reason"] != "end_of_data"]
    df_eq  = build_equity_curve(trades, dates)

    equity_series = pd.concat([
        pd.Series([initial_equity]),
        df_eq["equity"]
    ]).reset_index(drop=True)

    dd = compute_drawdown(equity_series)
    max_dd = dd.min()

    wins   = [t for t in closed if t["pnl_pct"] > 0]
    losses = [t for t in closed if t["pnl_pct"] < 0]
    wr     = len(wins) / len(closed) * 100 if closed else 0
    pf     = (sum(t["pnl_pct"] for t in wins) /
               abs(sum(t["pnl_pct"] for t in losses))) if losses else 999

    final_eq = equity_series.iloc[-1]
    total_ret = (final_eq - initial_equity) / initial_equity * 100

    sr = sharpe_ratio(equity_series)

    strategies = {}
    for t in closed:
        s = t["strategy_id"]
        strategies.setdefault(s, {"n": 0, "wins": 0, "pnl": 0.0})
        strategies[s]["n"] += 1
        if t["pnl_pct"] > 0:
            strategies[s]["wins"] += 1
        strategies[s]["pnl"] += t["pnl_pct"]

    mon_ret = None
    if df_eq["datetime"].notna().any():
        try:
            mon_ret = monthly_returns(df_eq.dropna(subset=["datetime"]))
        except Exception:
            pass

    # ── Per-strategy breakdown for summary table ──
    strat_table = []
    for s, d in strategies.items():
        s_wins   = [t for t in closed if t["strategy_id"] == s and t["pnl_pct"] > 0]
        s_losses = [t for t in closed if t["strategy_id"] == s and t["pnl_pct"] < 0]
        s_wr  = d["wins"] / d["n"] * 100 if d["n"] else 0
        s_pf  = (sum(t["pnl_pct"] for t in s_wins) /
                 abs(sum(t["pnl_pct"] for t in s_losses))) if s_losses else 999
        s_avgw = sum(t["pnl_pct"] for t in s_wins)  / len(s_wins)  if s_wins  else 0
        s_avgl = sum(t["pnl_pct"] for t in s_losses) / len(s_losses) if s_losses else 0
        verdict = "GOOD" if s_pf >= 1.3 else ("OK" if s_pf >= 1.0 else "POOR")
        strat_table.append([s, d["n"], f"{s_wr:.1f}%", f"{s_pf:.2f}",
                            f"+{s_avgw:.2f}%", f"{s_avgl:.2f}%", verdict])

    # ── Figure ──
    fig = plt.figure(figsize=(16, 24))
    fig.patch.set_facecolor("#0d1117")
    gs = gridspec.GridSpec(5, 2, figure=fig, hspace=0.45, wspace=0.35,
                           height_ratios=[2, 1.2, 1.2, 1.2, 0.7])

    DARK  = "#0d1117"
    PANEL = "#161b22"
    GREEN = "#3fb950"
    RED   = "#f85149"
    BLUE  = "#58a6ff"
    AMBER = "#e3b341"
    TEXT  = "#c9d1d9"
    GRID  = "#21262d"

    def style_ax(ax, title=""):
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=TEXT, labelsize=8)
        ax.xaxis.label.set_color(TEXT)
        ax.yaxis.label.set_color(TEXT)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID)
        ax.grid(True, color=GRID, linewidth=0.5, alpha=0.7)
        if title:
            ax.set_title(title, color=TEXT, fontsize=10, fontweight="bold", pad=8)

    # 1. Equity Curve
    ax1 = fig.add_subplot(gs[0, :])
    style_ax(ax1, f"{pair} — Equity Curve  (2020–2025)  |  Strategies: {strat_label}  |  TF: {tf_label}")
    x = range(len(equity_series))
    ax1.fill_between(x, initial_equity, equity_series.values,
                     where=equity_series.values >= initial_equity,
                     alpha=0.15, color=GREEN)
    ax1.fill_between(x, initial_equity, equity_series.values,
                     where=equity_series.values < initial_equity,
                     alpha=0.15, color=RED)
    ax1.plot(x, equity_series.values, color=GREEN, linewidth=1.2, label="Equity")
    ax1.axhline(initial_equity, color=TEXT, linewidth=0.8, linestyle="--", alpha=0.5, label="Initial")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax1.set_xlabel("Trade #")
    ax1.set_ylabel("Equity (USD)")
    ax1.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT, fontsize=8)

    sign = "+" if total_ret >= 0 else ""
    info_text = (f"Return: {sign}{total_ret:.1f}%  |  "
                 f"Max DD: {max_dd:.1f}%  |  "
                 f"WR: {wr:.1f}%  |  "
                 f"PF: {pf:.2f}  |  "
                 f"Trades: {len(closed)}  |  "
                 f"Sharpe≈{sr:.2f}")
    ax1.text(0.5, -0.12, info_text, transform=ax1.transAxes,
             color=AMBER, fontsize=9, ha="center",
             bbox=dict(boxstyle="round,pad=0.3", facecolor=PANEL, edgecolor=GRID))

    # 2. Drawdown
    ax2 = fig.add_subplot(gs[1, :])
    style_ax(ax2, "Drawdown from Peak")
    ax2.fill_between(x, dd.values, 0, color=RED, alpha=0.5)
    ax2.plot(x, dd.values, color=RED, linewidth=0.8)
    ax2.axhline(max_dd, color=RED, linewidth=0.8, linestyle="--", alpha=0.6,
                label=f"Max DD: {max_dd:.1f}%")
    ax2.set_xlabel("Trade #")
    ax2.set_ylabel("Drawdown %")
    ax2.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT, fontsize=8)

    # 3. Monthly Returns Heatmap
    ax3 = fig.add_subplot(gs[2, :])
    if mon_ret is not None and not mon_ret.empty:
        style_ax(ax3, "Monthly Returns Heatmap (%)")
        all_months = list(range(1, 13))
        mon_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        for m in all_months:
            if m not in mon_ret.columns:
                mon_ret[m] = 0.0
        mon_ret = mon_ret[all_months]
        data = mon_ret.values
        vmax = max(abs(data.max()), abs(data.min()), 1)
        norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
        im = ax3.imshow(data, aspect="auto", cmap="RdYlGn", norm=norm)
        ax3.set_xticks(range(12))
        ax3.set_xticklabels(mon_labels, color=TEXT, fontsize=8)
        ax3.set_yticks(range(len(mon_ret.index)))
        ax3.set_yticklabels(mon_ret.index.astype(str), color=TEXT, fontsize=8)
        ax3.tick_params(left=False, bottom=False)
        for i in range(len(mon_ret.index)):
            for j in range(12):
                v = data[i, j]
                ax3.text(j, i, f"{v:.1f}", ha="center", va="center",
                         color="black" if abs(v) > vmax * 0.3 else TEXT,
                         fontsize=7, fontweight="bold")
        plt.colorbar(im, ax=ax3, fraction=0.02, pad=0.02)
    else:
        ax3.text(0.5, 0.5, "No datetime data for monthly heatmap",
                 transform=ax3.transAxes, ha="center", color=TEXT)
        style_ax(ax3, "Monthly Returns Heatmap")

    # 4. PnL Distribution
    ax4 = fig.add_subplot(gs[3, 0])
    style_ax(ax4, "PnL Distribution per Trade (%)")
    pnl_vals = [t["pnl_pct"] for t in closed]
    bins = np.linspace(min(pnl_vals) - 0.1, max(pnl_vals) + 0.1, 40)
    win_vals  = [p for p in pnl_vals if p > 0]
    loss_vals = [p for p in pnl_vals if p <= 0]
    ax4.hist(loss_vals, bins=bins, color=RED,   alpha=0.8, label=f"Loss ({len(losses)})")
    ax4.hist(win_vals,  bins=bins, color=GREEN, alpha=0.8, label=f"Win ({len(wins)})")
    ax4.axvline(0, color=TEXT, linewidth=1, linestyle="--", alpha=0.6)
    ax4.set_xlabel("PnL %")
    ax4.set_ylabel("Trade Count")
    ax4.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT, fontsize=8)

    # 5. Per-Strategy Breakdown
    ax5 = fig.add_subplot(gs[3, 1])
    style_ax(ax5, "Per-Strategy: Trade Count & Win Rate")
    s_names  = list(strategies.keys())
    s_counts = [strategies[s]["n"] for s in s_names]
    s_wr     = [strategies[s]["wins"] / strategies[s]["n"] * 100 for s in s_names]
    s_colors = [GREEN if w >= 40 else AMBER for w in s_wr]
    bars = ax5.bar(s_names, s_counts, color=s_colors, alpha=0.8, edgecolor=GRID)
    ax5.set_ylabel("Trade Count", color=TEXT)
    ax5b = ax5.twinx()
    ax5b.set_facecolor(PANEL)
    ax5b.tick_params(colors=TEXT, labelsize=8)
    ax5b.plot(s_names, s_wr, "o--", color=BLUE, linewidth=1.5,
              markersize=6, label="Win Rate %")
    ax5b.set_ylabel("Win Rate %", color=BLUE)
    ax5b.set_ylim(0, 100)
    ax5b.tick_params(axis="y", colors=BLUE)
    for i, (bar, wr_v, cnt) in enumerate(zip(bars, s_wr, s_counts)):
        ax5.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 5,
                 f"n={cnt}\nWR={wr_v:.0f}%", ha="center", color=TEXT, fontsize=8)

    # 6. Summary Table
    ax6 = fig.add_subplot(gs[4, :])
    ax6.set_facecolor(PANEL)
    ax6.axis("off")
    ax6.set_title("Backtest Summary by Strategy", color=TEXT, fontsize=10,
                  fontweight="bold", pad=8, loc="left")
    col_labels = ["Strategy", "Trades", "Win Rate", "Profit Factor", "Avg Win", "Avg Loss", "Verdict"]
    col_widths = [0.14, 0.10, 0.12, 0.16, 0.12, 0.12, 0.10]
    row_colors_map = {"GOOD": GREEN, "OK": AMBER, "POOR": RED}
    # Header
    x_pos = 0.01
    for lbl, w in zip(col_labels, col_widths):
        ax6.text(x_pos, 0.80, lbl, transform=ax6.transAxes,
                 color=AMBER, fontsize=8, fontweight="bold", va="top")
        x_pos += w
    # Divider
    ax6.axhline(0.65, color=GRID, linewidth=0.8, )
    # Rows
    for r_idx, row in enumerate(strat_table):
        y = 0.55 - r_idx * 0.25
        x_pos = 0.01
        verdict_color = row_colors_map.get(row[-1], TEXT)
        for c_idx, (val, w) in enumerate(zip(row, col_widths)):
            color = verdict_color if c_idx == len(row) - 1 else TEXT
            ax6.text(x_pos, y, str(val), transform=ax6.transAxes,
                     color=color, fontsize=8, va="top",
                     fontweight="bold" if c_idx == len(row) - 1 else "normal")
            x_pos += w
    # Overall row
    y_overall = 0.55 - len(strat_table) * 0.25
    ax6.axhline(y_overall + 0.10, color=GRID, linewidth=0.5, linestyle="--",
                )
    overall_vals = [
        "OVERALL", str(len(closed)), f"{wr:.1f}%", f"{pf:.2f}",
        f"+{sum(t['pnl_pct'] for t in wins)/max(len(wins),1):.2f}%",
        f"{sum(t['pnl_pct'] for t in losses)/max(len(losses),1):.2f}%",
        f"${final_eq:,.0f}",
    ]
    x_pos = 0.01
    for val, w in zip(overall_vals, col_widths):
        ax6.text(x_pos, y_overall, val, transform=ax6.transAxes,
                 color=GREEN if final_eq >= initial_equity else RED,
                 fontsize=8, fontweight="bold", va="top")
        x_pos += w

    fig.suptitle(
        f"EA Brain Backtest — {pair}  |  Initial ${initial_equity:,.0f}  |  2020–2025"
        f"  |  TF: {tf_label}  |  Strategies: {strat_label}",
        color=TEXT, fontsize=11, fontweight="bold", y=0.995
    )

    out_path = os.path.join(OUTPUT_DIR, f"backtest_{pair}_{strat_slug}_{step_slug}_{ts}.png")
    fig.savefig(out_path, dpi=130, bbox_inches="tight", facecolor=DARK)
    plt.close(fig)
    print(f"Chart saved: {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Generate EA Brain backtest charts")
    parser.add_argument("--pair",   default="", help="Single pair (default: all)")
    parser.add_argument("--step",   type=int, default=4,
                        help="Step used in backtest (1=M15, 4=H1, 16=H4). Default: 4")
    parser.add_argument("--equity", type=float, default=INITIAL_EQUITY,
                        help="Initial equity used in backtest. Default: 1000")
    args = parser.parse_args()

    pairs = [args.pair.upper()] if args.pair else PAIRS
    for pair in pairs:
        try:
            path = generate_pair_chart(pair, step=args.step, initial_equity=args.equity)
            print(f"  -> {path}")
        except Exception as e:
            print(f"ERROR {pair}: {e}")
            import traceback; traceback.print_exc()


if __name__ == "__main__":
    main()
