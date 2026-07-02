"""
portfolio.py — performance reporting.

compute_performance() takes raw time-series data and returns a PerformanceReport
with all standard metrics.  No data is embellished; if the system lost money,
the report says so plainly.

Annualised Sharpe uses rf=0 and assumes ~252 trading days per year.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List


@dataclass
class PerformanceReport:
    """Summary performance metrics for a completed simulation or live run."""

    starting_equity: float
    ending_equity: float
    total_return: float         # fraction, e.g. 0.12 = +12%
    max_drawdown: float         # fraction, negative, e.g. -0.15 = -15%
    annualized_sharpe: float
    trades_closed: int
    win_rate: float             # fraction of closed trades with positive P&L
    realized_pnl: float
    cycles: int

    def render(self) -> str:
        """Human-readable report string."""
        lines = [
            "=" * 60,
            "  PERFORMANCE REPORT",
            "=" * 60,
            f"  Starting equity   : ${self.starting_equity:>12,.2f}",
            f"  Ending equity     : ${self.ending_equity:>12,.2f}",
            f"  Total return      : {self.total_return*100:>+8.2f}%",
            f"  Max drawdown      : {self.max_drawdown*100:>8.2f}%",
            f"  Annualized Sharpe : {self.annualized_sharpe:>8.2f}",
            f"  Realized P&L      : ${self.realized_pnl:>+12,.2f}",
            f"  Trades closed     : {self.trades_closed:>8d}",
            f"  Win rate          : {self.win_rate*100:>8.1f}%",
            f"  Cycles run        : {self.cycles:>8d}",
            "=" * 60,
        ]
        return "\n".join(lines)


def compute_performance(
    equity_curve: List[float],
    realized_pnl: float,
    closed_trade_pnls: List[float],
    starting_equity: float = 0.0,
) -> PerformanceReport:
    """
    Compute a PerformanceReport from raw equity curve data.

    Args:
        equity_curve: List of equity snapshots (one per cycle), newest last.
        realized_pnl: Total realized P&L over the run.
        closed_trade_pnls: Per-trade realized P&L list (may be empty).
        starting_equity: Initial equity; inferred from equity_curve[0] if 0.
    """
    if not equity_curve:
        return PerformanceReport(
            starting_equity=starting_equity,
            ending_equity=starting_equity,
            total_return=0.0,
            max_drawdown=0.0,
            annualized_sharpe=0.0,
            trades_closed=0,
            win_rate=0.0,
            realized_pnl=0.0,
            cycles=0,
        )

    start = starting_equity if starting_equity > 0 else equity_curve[0]
    end = equity_curve[-1]
    total_return = (end - start) / start if start else 0.0

    # Max drawdown over the equity curve.
    peak = equity_curve[0]
    max_dd = 0.0
    for e in equity_curve:
        if e > peak:
            peak = e
        dd = (e - peak) / peak if peak else 0.0
        if dd < max_dd:
            max_dd = dd

    # Annualised Sharpe (rf=0): use cycle-over-cycle returns.
    if len(equity_curve) > 1:
        cycle_returns = [
            (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
            if equity_curve[i - 1] else 0.0
            for i in range(1, len(equity_curve))
        ]
        n = len(cycle_returns)
        mean_r = sum(cycle_returns) / n
        variance = sum((r - mean_r) ** 2 for r in cycle_returns) / max(n - 1, 1)
        std_r = math.sqrt(variance)
        # Scale to annual assuming 252 cycles per year is not true for a daemon
        # running every minute — but in a trading simulation one cycle ≈ one day.
        sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0
    else:
        sharpe = 0.0

    trades = len(closed_trade_pnls)
    wins = sum(1 for p in closed_trade_pnls if p > 0)
    win_rate = wins / trades if trades else 0.0

    return PerformanceReport(
        starting_equity=start,
        ending_equity=end,
        total_return=total_return,
        max_drawdown=max_dd,
        annualized_sharpe=round(sharpe, 4),
        trades_closed=trades,
        win_rate=win_rate,
        realized_pnl=realized_pnl,
        cycles=len(equity_curve),
    )
