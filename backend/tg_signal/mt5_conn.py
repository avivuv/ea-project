"""
Koneksi library MetaTrader5 bersama + auto-reconnect.

Library MetaTrader5 terhubung ke terminal lewat IPC. Bila terminal ditutup/restart (update MT5,
dipakai Strategy Tester, dsb.), koneksi lama mati selamanya: setiap panggilan mengembalikan None
dengan last_error (-10001, 'IPC send failed'). `ensure()` dipanggil di awal tiap siklus runner:
bila koneksi putus → shutdown + initialize ulang (dengan pengaman akun DEMO yang sama).
"""
from __future__ import annotations

import MetaTrader5 as mt5

from tg_signal import settings


def connect(symbols: list[str] | tuple[str, ...] = (), strict: bool = True) -> None:
    """initialize + tolak akun non-DEMO + pilih simbol. strict=False: simbol tak tersedia diabaikan."""
    if not mt5.initialize(**settings.mt5_init_kwargs()):
        raise RuntimeError(f"MT5 initialize gagal: {mt5.last_error()}")
    acc = mt5.account_info()
    if acc is None:
        raise RuntimeError("MT5 belum login ke akun")
    if acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        mt5.shutdown()
        raise RuntimeError(f"DITOLAK: akun {acc.login} bukan akun DEMO. Program ini hanya untuk demo.")
    for s in symbols:
        if not mt5.symbol_select(s, True) and strict:
            raise RuntimeError(f"Simbol {s} tidak tersedia")


def alive() -> bool:
    """Koneksi IPC hidup dan terminal sudah login."""
    return mt5.terminal_info() is not None and mt5.account_info() is not None


def ensure(symbols: list[str] | tuple[str, ...] = (), strict: bool = True) -> str | None:
    """Sambung ulang bila koneksi putus. Return pesan (untuk log) bila baru saja reconnect, None bila
    koneksi sehat. Raise RuntimeError bila belum bisa (terminal belum siap) → coba lagi siklus berikutnya."""
    if alive():
        return None
    err = mt5.last_error()
    mt5.shutdown()
    connect(symbols, strict)
    acc = mt5.account_info()
    return f"koneksi MT5 pulih (sebelumnya {err}) — login {acc.login} {acc.server}"
