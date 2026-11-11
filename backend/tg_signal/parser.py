"""
Parser pesan grup: sinyal & laporan harian (SIGNAL_SPEC §1, §4).

Logika murni: tidak boleh import MetaTrader5 / telethon.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

SIGNAL_RE = re.compile(r"^\s*(BUY|SELL)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\b", re.I | re.M)
SL_RE = re.compile(r"\bSL\s*:?\s*(\d+)\s*pips?\b", re.I)

REPORT_HEADER_RE = re.compile(r"^\s*Report\s+\w+\s*\((\d{2})-(\d{2})-(\d{4})\)", re.I | re.M)
REPORT_LINE_RE = re.compile(
    r"^\s*(\d+)\.\s*(BUY|SELL)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\s*(✅|❌)?\s*(ZERO|MID|LAST)-(TP|SL)",
    re.I | re.M,
)


@dataclass
class ParsedSignal:
    direction: str
    level_first: int
    level_last: int
    sl_pips: float
    sl_from_message: bool


@dataclass
class ReportLine:
    no: int
    direction: str
    level_first: int
    level_last: int
    win: bool | None        # None bila emoji tidak ada
    depth: str              # ZERO | MID | LAST
    outcome: str            # TP | SL


@dataclass
class ParsedReport:
    report_date: date
    lines: list[ReportLine] = field(default_factory=list)


def parse_signal(text: str, default_sl_pips: float = 30) -> ParsedSignal | None:
    """Return ParsedSignal bila pesan adalah sinyal, selain itu None.

    Laporan harian juga berisi "BUY 34-30", jadi pesan laporan dikecualikan.
    """
    if not text or REPORT_HEADER_RE.search(text):
        return None
    m = SIGNAL_RE.search(text)
    if not m:
        return None
    sl = SL_RE.search(text)
    return ParsedSignal(
        direction=m.group(1).upper(),
        level_first=int(m.group(2)),
        level_last=int(m.group(3)),
        sl_pips=float(sl.group(1)) if sl else float(default_sl_pips),
        sl_from_message=bool(sl),
    )


def parse_report(text: str) -> ParsedReport | None:
    """Return ParsedReport bila pesan adalah laporan harian, selain itu None."""
    if not text:
        return None
    h = REPORT_HEADER_RE.search(text)
    if not h:
        return None
    dd, mm, yyyy = (int(x) for x in h.groups())
    try:
        report_date = date(yyyy, mm, dd)
    except ValueError:
        return None
    report = ParsedReport(report_date=report_date)
    for m in REPORT_LINE_RE.finditer(text):
        emoji = m.group(5)
        report.lines.append(ReportLine(
            no=int(m.group(1)),
            direction=m.group(2).upper(),
            level_first=int(m.group(3)),
            level_last=int(m.group(4)),
            win=None if emoji is None else emoji == "✅",
            depth=m.group(6).upper(),
            outcome=m.group(7).upper(),
        ))
    return report


def classify(text: str) -> str:
    """SIGNAL | REPORT | OTHER."""
    if parse_report(text):
        return "REPORT"
    if parse_signal(text):
        return "SIGNAL"
    return "OTHER"
