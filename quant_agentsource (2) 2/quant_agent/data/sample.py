"""
data/sample.py — deterministic, infinitely extendable synthetic market data.

Design goals:
  * Zero third-party dependencies — pure stdlib.
  * Fully deterministic: same symbol always produces the same price path.
  * Infinitely extendable: advance() generates new bars so a daemon never
    runs out of data.
  * Realistic-ish: geometric Brownian motion with per-symbol drift/vol;
    weekends skipped.

The synthetic data is intentionally not tuned to look good.  Some symbols will
trend up, some down, some sideways — that is the honest behavior to test
against.
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import date, timedelta
from typing import Dict, List, Sequence

from quant_agent.data.base import Bar, Fundamentals, MarketDataProvider

# Initial history length generated per symbol at construction time.
_MASTER_LEN = 400

# Per-sector fundamentals for variety.
_SECTOR_MAP = {
    "AAPL": ("Technology", 28.0, 2.8e12, 0.005, 1.2),
    "MSFT": ("Technology", 32.0, 2.5e12, 0.008, 0.9),
    "NVDA": ("Technology", 55.0, 1.8e12, 0.001, 1.7),
    "AMZN": ("Consumer Cyclical", 60.0, 1.9e12, 0.0, 1.1),
    "GOOGL": ("Communication Services", 25.0, 2.0e12, 0.0, 1.0),
    "META":  ("Communication Services", 22.0, 1.3e12, 0.0, 1.3),
    "TSLA": ("Consumer Cyclical", 70.0, 8.0e11, 0.0, 2.0),
    "JPM":  ("Financial Services", 12.0, 5.5e11, 0.025, 1.1),
    "XOM":  ("Energy", 14.0, 4.5e11, 0.035, 0.8),
    "KO":   ("Consumer Defensive", 24.0, 2.6e11, 0.030, 0.5),
}
_DEFAULT_SECTOR = ("Unknown", 20.0, 1e10, 0.01, 1.0)


def _symbol_seed(symbol: str) -> int:
    """Derive a stable integer seed from a symbol name."""
    digest = hashlib.sha256(symbol.encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _symbol_params(symbol: str) -> tuple[float, float, float]:
    """Return (start_price, daily_drift, daily_vol) for a symbol."""
    rng = random.Random(_symbol_seed(symbol))
    start_price = rng.uniform(20.0, 400.0)
    # Drift: roughly −5% to +15% annualised, converted to daily.
    drift_ann = rng.uniform(-0.05, 0.15)
    vol_ann = rng.uniform(0.15, 0.55)
    daily_drift = drift_ann / 252
    daily_vol = vol_ann / math.sqrt(252)
    return start_price, daily_drift, daily_vol


def _is_weekday(d: date) -> bool:
    return d.weekday() < 5  # Mon=0 … Fri=4


def _next_weekday(d: date) -> date:
    d = d + timedelta(days=1)
    while not _is_weekday(d):
        d = d + timedelta(days=1)
    return d


def _generate_bars(symbol: str, start_date: date, n: int) -> List[Bar]:
    """Generate `n` weekday bars for `symbol` starting from `start_date`."""
    _, daily_drift, daily_vol = _symbol_params(symbol)

    # Use a fresh RNG seeded by symbol + start_date so extension bars are
    # consistent regardless of when advance() is called.
    seed = _symbol_seed(symbol) ^ int(start_date.strftime("%Y%m%d"))
    rng = random.Random(seed)

    bars: List[Bar] = []
    d = start_date
    # Determine starting price: if we have no bars, use the symbol param;
    # otherwise the caller supplies the open.
    _, _, _ = _symbol_params(symbol)
    start_price, _, _ = _symbol_params(symbol)

    # Walk forward from start_date using GBM.
    # To get a consistent price at start_date we replay from the beginning.
    # For efficiency, replay is only done once per symbol during __init__.
    price = start_price
    while not _is_weekday(d):
        d = d + timedelta(days=1)

    for _ in range(n):
        ret = rng.gauss(daily_drift, daily_vol)
        close = max(price * math.exp(ret), 0.01)
        high = close * (1 + abs(rng.gauss(0, daily_vol * 0.5)))
        low = close * (1 - abs(rng.gauss(0, daily_vol * 0.5)))
        open_ = price * (1 + rng.gauss(0, daily_vol * 0.3))
        bars.append(Bar(
            date=d.isoformat(),
            open=round(open_, 4),
            high=round(max(high, open_, close), 4),
            low=round(min(low, open_, close), 4),
            close=round(close, 4),
            volume=round(rng.uniform(1e6, 5e7)),
        ))
        price = close
        d = _next_weekday(d)

    return bars


class SampleDataProvider:
    """
    Synthetic market data provider.

    The clock starts at bar index `cursor`.  Call advance() to move forward
    one trading day; a new bar is generated when the cursor reaches the end
    of the pre-generated history, so the provider never runs dry.
    """

    def __init__(self, symbols: list[str], lookback: int = 252) -> None:
        self._symbols = symbols
        self._bars: Dict[str, List[Bar]] = {}
        self._cursor: int = 0

        # Compute a stable start date for bar generation.
        # Use a fixed anchor so reruns produce identical paths.
        self._origin: date = date(2020, 1, 2)  # first trading day 2020

        for sym in symbols:
            self._bars[sym] = _generate_bars(sym, self._origin, _MASTER_LEN)

        # Set cursor so history(lookback) is satisfiable.
        self._cursor = min(lookback, _MASTER_LEN - 1)

    # ------------------------------------------------------------------
    # Clock control
    # ------------------------------------------------------------------

    def reset_clock(self, lookback: int = 252) -> None:
        """Reset cursor so at least `lookback` bars precede the current day."""
        self._cursor = min(lookback, len(next(iter(self._bars.values()))) - 1)

    def advance(self) -> bool:
        """
        Advance the clock by one trading day.

        If the cursor is at the end of the generated history, extend every
        symbol's bar list by one bar before advancing.  Always returns True
        so callers can use `while provider.advance()` forever.
        """
        max_idx = min(len(bars) for bars in self._bars.values()) - 1
        if self._cursor >= max_idx:
            # Extend history by one bar for each symbol.
            for sym in self._symbols:
                existing = self._bars[sym]
                last_date = date.fromisoformat(existing[-1].date)
                next_date = _next_weekday(last_date)
                new_bars = _generate_bars(sym, next_date, 1)
                existing.extend(new_bars)
        self._cursor += 1
        return True

    @property
    def current_date(self) -> str:
        """ISO-8601 date string for the current cursor position."""
        # Use first symbol as reference; all share the same calendar.
        ref = self._bars[self._symbols[0]]
        return ref[self._cursor].date

    # ------------------------------------------------------------------
    # MarketDataProvider interface
    # ------------------------------------------------------------------

    def history(self, symbol: str, days: int = 252) -> Sequence[Bar]:
        bars = self._bars.get(symbol, [])
        end = self._cursor + 1          # inclusive of cursor
        start = max(0, end - days)
        return bars[start:end]

    def latest_price(self, symbol: str) -> float:
        bars = self._bars.get(symbol, [])
        if not bars:
            return 0.0
        return bars[self._cursor].close

    def fundamentals(self, symbol: str) -> Fundamentals:
        sector, pe, mcap, div, beta = _SECTOR_MAP.get(symbol, _DEFAULT_SECTOR)
        return Fundamentals(
            symbol=symbol,
            pe_ratio=pe,
            market_cap=mcap,
            dividend_yield=div,
            sector=sector,
            beta=beta,
        )
