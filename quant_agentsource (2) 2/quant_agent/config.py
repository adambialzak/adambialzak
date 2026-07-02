"""
config.py — typed configuration dataclasses for the whole system.

All defaults are conservative.  Every field can be overridden via QA_* env vars
or by constructing a Config programmatically.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class RiskLimits:
    """Hard limits enforced by RiskManager before any order is placed."""

    # Maximum fraction of equity in a single name.
    max_position_pct: float = 0.15
    # Maximum total long+short exposure as fraction of equity.
    max_gross_exposure: float = 0.90
    # New positions opened per cycle (prevents over-trading in one shot).
    max_new_positions_per_cycle: int = 3
    # Minimum cash kept undeployed (long side only).
    min_cash_buffer_pct: float = 0.10
    # Risk dollars per trade as fraction of equity, scaled by conviction.
    per_trade_risk_pct: float = 0.01
    # Absolute cap on simultaneous open positions.
    max_positions: int = 8
    # Default stop-loss distance from entry (used when not set by reasoner).
    stop_loss_pct: float = 0.08
    # Default take-profit distance from entry.
    take_profit_pct: float = 0.20
    # Theses with conviction below this are skipped entirely.
    min_conviction_to_trade: float = 0.55


@dataclass
class ExecutionCosts:
    """Realistic friction model.  The defaults are tight but not zero."""

    # Flat commission per trade (many modern brokers are $0).
    commission_per_trade: float = 0.0
    # One-way slippage in basis points (market impact + latency).
    slippage_bps: float = 5.0
    # One-way half-spread cost in basis points.
    half_spread_bps: float = 3.0


@dataclass
class Config:
    """Top-level system configuration."""

    starting_cash: float = 10_000.0
    base_currency: str = "USD"

    # Swap points — change these strings to switch backends.
    data_provider: str = "sample"     # "sample" | "yfinance"
    reasoner: str = "heuristic"       # "heuristic" | "anthropic"
    broker: str = "paper"             # "paper" | "webull"

    watchlist: List[str] = field(default_factory=lambda: [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
        "META", "TSLA", "JPM", "XOM", "KO",
    ])

    db_path: str = "quant_agent.db"
    anthropic_model: str = "claude-sonnet-4-6"

    # Guards for the live path — both must be True before real orders flow.
    live_enabled: bool = False

    risk: RiskLimits = field(default_factory=RiskLimits)
    costs: ExecutionCosts = field(default_factory=ExecutionCosts)

    @classmethod
    def from_env(cls) -> "Config":
        """Build a Config from QA_* environment variables, falling back to defaults."""
        cfg = cls()

        if val := os.getenv("QA_STARTING_CASH"):
            cfg.starting_cash = float(val)
        if val := os.getenv("QA_DATA_PROVIDER"):
            cfg.data_provider = val
        if val := os.getenv("QA_REASONER"):
            cfg.reasoner = val
        if val := os.getenv("QA_BROKER"):
            cfg.broker = val
        if val := os.getenv("QA_ANTHROPIC_MODEL"):
            cfg.anthropic_model = val
        if val := os.getenv("QA_WATCHLIST"):
            cfg.watchlist = [s.strip() for s in val.split(",") if s.strip()]

        return cfg
