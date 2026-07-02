"""
risk.py — RiskManager: position sizing and hard portfolio-level limits.

This is where "control risk" actually lives.  Every limit is enforced before
an order is created; the broker never sees an order that violates the rules.

Sizing method: fixed-fractional risk-to-stop.
  risk_dollars = equity × per_trade_risk_pct × conviction
  qty = int(risk_dollars / |entry - stop|)

Then the position notional is clamped by the per-name cap, the gross exposure
ceiling, and the cash buffer (long side).

No pyramiding in v1: if a symbol is already held, it is skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Set

from quant_agent.agents.qa import Verdict
from quant_agent.config import RiskLimits
from quant_agent.reasoning.base import Thesis


@dataclass
class PortfolioState:
    """Snapshot of the portfolio as RiskManager sees it."""

    equity: float
    cash: float
    held_symbols: Set[str] = field(default_factory=set)
    gross_exposure: float = 0.0   # total long + short notional


@dataclass
class SizedOrder:
    """An order with all risk parameters attached."""

    symbol: str
    side: str           # "buy" | "sell_short"
    quantity: int
    entry: float
    stop: float
    target: float
    conviction: float
    risk_dollars: float
    rationale: str


@dataclass
class _Candidate:
    thesis: Thesis
    verdict: Verdict


class RiskManager:
    """Converts approved theses into size-constrained orders."""

    def __init__(self, limits: RiskLimits) -> None:
        self._lim = limits

    def size_orders(
        self,
        candidates: List[tuple[Thesis, Verdict]],
        state: PortfolioState,
    ) -> List[SizedOrder]:
        """
        Convert approved thesis+verdict pairs into sized orders.

        Returns only orders that pass all hard limits.
        """
        lim = self._lim

        # Sort by adjusted conviction (highest first) so the best ideas
        # are allocated first when limits bind.
        approved = [
            _Candidate(thesis=t, verdict=v)
            for t, v in candidates
            if v.approved and v.adjusted_conviction >= lim.min_conviction_to_trade
        ]
        approved.sort(key=lambda c: c.verdict.adjusted_conviction, reverse=True)

        orders: List[SizedOrder] = []
        new_positions = 0
        gross_exposure = state.gross_exposure

        for cand in approved:
            t = cand.thesis
            v = cand.verdict

            # Skip names already in the portfolio (no pyramiding in v1).
            if t.symbol in state.held_symbols:
                continue

            # Global position cap check.
            if len(state.held_symbols) + new_positions >= lim.max_positions:
                break

            # Per-cycle new-position throttle.
            if new_positions >= lim.max_new_positions_per_cycle:
                break

            # Fixed-fractional size.
            risk_dollars = state.equity * lim.per_trade_risk_pct * v.adjusted_conviction
            stop_distance = abs(t.entry - t.stop)
            if stop_distance == 0:
                continue
            qty = int(risk_dollars / stop_distance)
            if qty <= 0:
                continue

            # Per-name cap: qty × entry ≤ max_position_pct × equity.
            max_notional = lim.max_position_pct * state.equity
            if qty * t.entry > max_notional:
                qty = int(max_notional / t.entry)
            if qty <= 0:
                continue

            trade_notional = qty * t.entry

            # Gross exposure cap.
            if gross_exposure + trade_notional > lim.max_gross_exposure * state.equity:
                # Trim to what fits.
                room = lim.max_gross_exposure * state.equity - gross_exposure
                qty = int(room / t.entry)
                if qty <= 0:
                    continue
                trade_notional = qty * t.entry

            # Cash buffer (long side only).
            if t.direction == "long":
                available_cash = state.cash - lim.min_cash_buffer_pct * state.equity
                if trade_notional > available_cash:
                    qty = int(available_cash / t.entry)
                    if qty <= 0:
                        continue
                    trade_notional = qty * t.entry

            side = "buy" if t.direction == "long" else "sell_short"
            orders.append(SizedOrder(
                symbol=t.symbol,
                side=side,
                quantity=qty,
                entry=t.entry,
                stop=t.stop,
                target=t.target,
                conviction=v.adjusted_conviction,
                risk_dollars=round(risk_dollars, 2),
                rationale=t.rationale,
            ))
            gross_exposure += trade_notional
            new_positions += 1

        return orders
