"""
reasoning/base.py — feature engineering and the Reasoner interface.

FeatureSet captures every numeric signal the system uses.  All reasoners
receive the same FeatureSet, so the LLM and the heuristic are evaluated on
identical inputs — the LLM cannot invent prices or cherry-pick data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Protocol, Sequence

from quant_agent.data.base import Bar, Fundamentals


# ---------------------------------------------------------------------------
# Feature container
# ---------------------------------------------------------------------------

@dataclass
class FeatureSet:
    """Computed numeric signals for a single symbol."""

    symbol: str
    price: float

    # Return over the last ~21 and ~63 trading days.
    ret_1m: float = 0.0
    ret_3m: float = 0.0

    # Weighted momentum composite.
    momentum: float = 0.0

    # Realized annualised volatility (std of log returns * sqrt(252)).
    annual_vol: float = 0.0

    # Peak-to-trough drawdown over the history window (negative number).
    max_drawdown: float = 0.0

    # Price relative to moving averages.
    above_sma50: bool = False
    above_sma200: bool = False

    # Relative Strength Index, 14-period.
    rsi14: float = 50.0

    # Fundamental inputs passed through from Fundamentals.
    pe_ratio: float = float("nan")
    sector: str = "Unknown"
    beta: float = 1.0

    def as_text(self) -> str:
        """Human-readable summary for LLM grounding."""
        above_50 = "yes" if self.above_sma50 else "no"
        above_200 = "yes" if self.above_sma200 else "no"
        pe_str = f"{self.pe_ratio:.1f}" if not math.isnan(self.pe_ratio) else "N/A"
        return (
            f"Symbol: {self.symbol}\n"
            f"Price: ${self.price:.2f}\n"
            f"1-month return: {self.ret_1m*100:.1f}%\n"
            f"3-month return: {self.ret_3m*100:.1f}%\n"
            f"Momentum composite: {self.momentum*100:.1f}%\n"
            f"Annual volatility: {self.annual_vol*100:.1f}%\n"
            f"Max drawdown: {self.max_drawdown*100:.1f}%\n"
            f"Above 50-day SMA: {above_50}\n"
            f"Above 200-day SMA: {above_200}\n"
            f"RSI(14): {self.rsi14:.1f}\n"
            f"P/E ratio: {pe_str}\n"
            f"Sector: {self.sector}\n"
            f"Beta: {self.beta:.2f}"
        )


# ---------------------------------------------------------------------------
# Thesis container
# ---------------------------------------------------------------------------

@dataclass
class Thesis:
    """A trading thesis produced by a Reasoner."""

    symbol: str
    direction: str          # "long" | "short" | "flat"
    conviction: float       # 0.0 … 1.0
    entry: float
    stop: float
    target: float
    rationale: str
    key_risks: List[str] = field(default_factory=list)
    source: str = "unknown"

    @property
    def reward_risk(self) -> float:
        """Ratio of potential gain to potential loss.  Positive means valid."""
        if self.direction == "flat":
            return 0.0
        loss = abs(self.entry - self.stop)
        gain = abs(self.target - self.entry)
        if loss == 0:
            return 0.0
        return gain / loss


# ---------------------------------------------------------------------------
# Reasoner protocol
# ---------------------------------------------------------------------------

class Reasoner(Protocol):
    """Every reasoning backend must satisfy this interface."""

    def analyze(self, features: FeatureSet, fundamentals: Fundamentals) -> Thesis:
        """Produce a trading thesis from pre-computed features."""
        ...


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def _sma(closes: list[float], n: int) -> float:
    if len(closes) < n:
        return closes[-1] if closes else 0.0
    return sum(closes[-n:]) / n


def _rsi(closes: list[float], period: int = 14) -> float:
    """Wilder RSI over `period` bars."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(-period, 0):
        delta = closes[i] - closes[i - 1]
        if delta > 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(delta))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def _max_drawdown(closes: list[float]) -> float:
    """Peak-to-trough max drawdown; returned as a negative fraction."""
    peak = closes[0]
    max_dd = 0.0
    for c in closes:
        if c > peak:
            peak = c
        dd = (c - peak) / peak
        if dd < max_dd:
            max_dd = dd
    return max_dd


def _realized_vol(closes: list[float]) -> float:
    """Annualised realised volatility from daily log returns."""
    if len(closes) < 2:
        return 0.0
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    n = len(log_returns)
    mean = sum(log_returns) / n
    variance = sum((r - mean) ** 2 for r in log_returns) / max(n - 1, 1)
    return math.sqrt(variance * 252)


def compute_features(
    symbol: str,
    bars: Sequence[Bar],
    fundamentals: Fundamentals,
) -> FeatureSet:
    """
    Compute the full FeatureSet from raw bars and fundamentals.

    Requires at least 2 bars; returns a flat FeatureSet with defaults when
    history is insufficient.
    """
    closes = [b.close for b in bars]
    if not closes:
        return FeatureSet(symbol=symbol, price=0.0, sector=fundamentals.sector,
                          pe_ratio=fundamentals.pe_ratio, beta=fundamentals.beta)

    price = closes[-1]
    ret_1m = (closes[-1] / closes[-22] - 1) if len(closes) >= 22 else 0.0
    ret_3m = (closes[-1] / closes[-63] - 1) if len(closes) >= 63 else 0.0
    momentum = 0.6 * ret_3m + 0.4 * ret_1m

    return FeatureSet(
        symbol=symbol,
        price=price,
        ret_1m=ret_1m,
        ret_3m=ret_3m,
        momentum=momentum,
        annual_vol=_realized_vol(closes),
        max_drawdown=_max_drawdown(closes),
        above_sma50=price > _sma(closes, 50),
        above_sma200=price > _sma(closes, 200),
        rsi14=_rsi(closes, 14),
        pe_ratio=fundamentals.pe_ratio,
        sector=fundamentals.sector,
        beta=fundamentals.beta,
    )
