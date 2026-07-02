"""
data/base.py — core data structures and the MarketDataProvider interface.

Keeping the interface minimal means every backend (sample, yfinance, live feed)
is trivially swappable without touching any upstream code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class Bar:
    """One trading day of OHLCV data."""

    date: str        # ISO-8601 "YYYY-MM-DD"
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Fundamentals:
    """Slow-moving fundamental data for a single symbol."""

    symbol: str
    pe_ratio: float        # NaN if not available / not applicable
    market_cap: float      # USD
    dividend_yield: float  # 0.0 if none
    sector: str            # e.g. "Technology"
    beta: float            # market-relative volatility; 1.0 = market


class MarketDataProvider(Protocol):
    """
    Interface every data backend must satisfy.

    history() returns bars oldest-first, newest-last so callers can naturally
    index bar[-1] for the most recent price.
    """

    def history(self, symbol: str, days: int = 252) -> Sequence[Bar]:
        """Return up to `days` bars for `symbol`, oldest first."""
        ...

    def latest_price(self, symbol: str) -> float:
        """Return the most recent closing price."""
        ...

    def fundamentals(self, symbol: str) -> Fundamentals:
        """Return fundamental data for `symbol`."""
        ...
