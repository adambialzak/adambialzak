"""
data/yfinance_provider.py — real market data via yfinance.

This module is only imported when config.data_provider == "yfinance".
The `yfinance` package is an optional extra; a clear error is raised if absent.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Sequence

from quant_agent.data.base import Bar, Fundamentals


def _require_yfinance():
    try:
        import yfinance  # noqa: F401
        return yfinance
    except ImportError:
        raise ImportError(
            "yfinance is required for real market data.\n"
            "Install it with:  pip install yfinance\n"
            "Or run in offline mode with --data-provider sample"
        )


class YFinanceProvider:
    """MarketDataProvider backed by Yahoo Finance via yfinance."""

    def history(self, symbol: str, days: int = 252) -> Sequence[Bar]:
        yf = _require_yfinance()
        ticker = yf.Ticker(symbol)
        # Fetch a little extra to account for weekends / holidays.
        start = (datetime.utcnow() - timedelta(days=int(days * 1.5))).strftime("%Y-%m-%d")
        df = ticker.history(start=start)
        bars = []
        for idx, row in df.iterrows():
            bars.append(Bar(
                date=idx.strftime("%Y-%m-%d"),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row.get("Volume", 0)),
            ))
        return bars[-days:]

    def latest_price(self, symbol: str) -> float:
        bars = self.history(symbol, days=1)
        return bars[-1].close if bars else 0.0

    def fundamentals(self, symbol: str) -> Fundamentals:
        yf = _require_yfinance()
        info = yf.Ticker(symbol).info

        def _safe(key: str, default: float = float("nan")) -> float:
            v = info.get(key)
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return default
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        return Fundamentals(
            symbol=symbol,
            pe_ratio=_safe("trailingPE"),
            market_cap=_safe("marketCap", 0.0),
            dividend_yield=_safe("dividendYield", 0.0),
            sector=info.get("sector", "Unknown"),
            beta=_safe("beta", 1.0),
        )
