"""
broker/base.py — order and account data structures; Broker interface.

Keeping the interface minimal means PaperBroker and WebullBroker are
interchangeable without touching the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol


@dataclass
class Order:
    """A trading instruction sent to a broker."""

    symbol: str
    side: str               # "buy" | "sell" | "sell_short" | "buy_to_cover"
    quantity: int
    type: str = "market"    # "market" | "limit"
    limit_price: Optional[float] = None
    stop: Optional[float] = None    # protective stop price (metadata only)
    target: Optional[float] = None  # take-profit price (metadata only)


@dataclass
class Fill:
    """Confirmation that an order was executed."""

    symbol: str
    side: str
    quantity: int
    price: float            # actual fill price (includes friction)
    commission: float = 0.0


@dataclass
class Position:
    """One open position.  Negative quantity means short."""

    symbol: str
    quantity: int           # negative = short
    avg_cost: float         # average cost basis per share
    stop: Optional[float] = None
    target: Optional[float] = None

    @property
    def market_value(self) -> float:
        """Signed market value at current price (negative for shorts)."""
        # Caller must pass a price; this uses avg_cost as a stub.
        return self.quantity * self.avg_cost

    def market_value_at(self, price: float) -> float:
        return self.quantity * price

    def unrealized(self, price: float) -> float:
        """Unrealized P&L at `price`."""
        return (price - self.avg_cost) * self.quantity


@dataclass
class AccountSnapshot:
    """Point-in-time account state."""

    cash: float
    equity: float           # cash + sum of marked-to-market positions
    positions: Dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0


class Broker(Protocol):
    """Interface every broker implementation must satisfy."""

    def submit(self, order: Order, ref_price: float) -> Fill:
        """Submit an order; `ref_price` is used to compute slippage."""
        ...

    def positions(self) -> Dict[str, Position]:
        """Return all open positions keyed by symbol."""
        ...

    def snapshot(self, prices: Dict[str, float]) -> AccountSnapshot:
        """Return a full account snapshot marked to `prices`."""
        ...

    @property
    def cash(self) -> float:
        """Available cash balance."""
        ...
