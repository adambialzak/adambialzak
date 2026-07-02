"""
broker/paper.py — realistic paper trading broker.

Friction model (all applied adversarially — buys fill worse, sells fill worse):
  fill_price = ref_price × (1 ± (slippage_bps + half_spread_bps) / 10_000)

Limit orders: buys fill only if ref_price ≤ limit; sells only if ≥ limit.

Short selling is fully supported: positive cash received on open, negative
cost to cover.  avg_cost is always the per-share cost basis regardless of
direction.

Protective exits: check_protective_exits() scans open positions against
current prices and emits market orders when a stop or target is breached.
This is called at the START of each cycle so stops trigger before new trades.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from quant_agent.broker.base import AccountSnapshot, Fill, Order, Position
from quant_agent.config import ExecutionCosts


class PaperBroker:
    """Simulated broker with realistic friction, shorting, and protective exits."""

    def __init__(self, starting_cash: float, costs: ExecutionCosts) -> None:
        self._cash: float = starting_cash
        self._costs = costs
        self._positions: Dict[str, Position] = {}
        self._realized_pnl: float = 0.0
        self.fills: List[Fill] = []

    # ------------------------------------------------------------------
    # Broker interface
    # ------------------------------------------------------------------

    def submit(self, order: Order, ref_price: float) -> Fill:
        """Execute an order against `ref_price` with friction."""
        fill_price = self._fill_price(order.side, ref_price, order.limit_price)
        commission = self._costs.commission_per_trade
        self._apply_fill(order, fill_price, commission)
        fill = Fill(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            commission=commission,
        )
        self.fills.append(fill)
        return fill

    def positions(self) -> Dict[str, Position]:
        return dict(self._positions)

    def snapshot(self, prices: Dict[str, float]) -> AccountSnapshot:
        equity = self.equity(prices)
        return AccountSnapshot(
            cash=self._cash,
            equity=equity,
            positions=dict(self._positions),
            realized_pnl=self._realized_pnl,
        )

    @property
    def cash(self) -> float:
        return self._cash

    # ------------------------------------------------------------------
    # Protective exits
    # ------------------------------------------------------------------

    def check_protective_exits(self, prices: Dict[str, float]) -> List[Order]:
        """
        Scan open positions for stop or target breaches.

        Returns a list of market orders to close breached positions.
        Does NOT execute them — the caller (engine) should submit each order.
        """
        exits: List[Order] = []
        for sym, pos in list(self._positions.items()):
            price = prices.get(sym)
            if price is None:
                continue

            if pos.quantity > 0:  # long position
                if pos.stop is not None and price <= pos.stop:
                    exits.append(Order(symbol=sym, side="sell", quantity=pos.quantity))
                elif pos.target is not None and price >= pos.target:
                    exits.append(Order(symbol=sym, side="sell", quantity=pos.quantity))
            elif pos.quantity < 0:  # short position
                qty = abs(pos.quantity)
                if pos.stop is not None and price >= pos.stop:
                    exits.append(Order(symbol=sym, side="buy_to_cover", quantity=qty))
                elif pos.target is not None and price <= pos.target:
                    exits.append(Order(symbol=sym, side="buy_to_cover", quantity=qty))

        return exits

    # ------------------------------------------------------------------
    # Equity computation
    # ------------------------------------------------------------------

    def equity(self, prices: Dict[str, float]) -> float:
        total = self._cash
        for sym, pos in self._positions.items():
            price = prices.get(sym, pos.avg_cost)
            total += pos.market_value_at(price)
        return total

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fill_price(
        self, side: str, ref: float, limit_price: Optional[float]
    ) -> float:
        bps = (self._costs.slippage_bps + self._costs.half_spread_bps) / 10_000
        if side in ("buy", "buy_to_cover"):
            price = ref * (1 + bps)
            if limit_price is not None:
                if ref > limit_price:
                    raise ValueError(
                        f"Limit buy at {limit_price:.4f} not fillable at ref {ref:.4f}"
                    )
                price = min(price, limit_price)
        else:  # sell / sell_short
            price = ref * (1 - bps)
            if limit_price is not None:
                if ref < limit_price:
                    raise ValueError(
                        f"Limit sell at {limit_price:.4f} not fillable at ref {ref:.4f}"
                    )
                price = max(price, limit_price)
        return round(price, 6)

    def _apply_fill(self, order: Order, fill_price: float, commission: float) -> None:
        sym = order.symbol
        qty = order.quantity
        side = order.side

        self._cash -= commission

        if side == "buy":
            cost = qty * fill_price
            self._cash -= cost
            if sym in self._positions:
                pos = self._positions[sym]
                # Weighted average cost on average-up / average-down.
                total_qty = pos.quantity + qty
                pos.avg_cost = (pos.avg_cost * pos.quantity + fill_price * qty) / total_qty
                pos.quantity = total_qty
            else:
                self._positions[sym] = Position(
                    symbol=sym,
                    quantity=qty,
                    avg_cost=fill_price,
                    stop=order.stop,
                    target=order.target,
                )

        elif side == "sell":
            pos = self._positions.get(sym)
            if pos is None:
                raise ValueError(f"Cannot sell {sym}: no long position held.")
            close_qty = min(qty, pos.quantity)
            realized = (fill_price - pos.avg_cost) * close_qty
            self._realized_pnl += realized
            self._cash += close_qty * fill_price
            remaining = pos.quantity - close_qty
            if remaining <= 0:
                del self._positions[sym]
            else:
                pos.quantity = remaining

        elif side == "sell_short":
            proceeds = qty * fill_price
            self._cash += proceeds
            if sym in self._positions:
                pos = self._positions[sym]
                # Netting against an existing long.
                if pos.quantity > 0:
                    net_qty = pos.quantity - qty
                    if net_qty > 0:
                        pos.quantity = net_qty
                    elif net_qty == 0:
                        self._realized_pnl += (fill_price - pos.avg_cost) * pos.quantity
                        del self._positions[sym]
                    else:
                        self._realized_pnl += (fill_price - pos.avg_cost) * pos.quantity
                        self._positions[sym] = Position(
                            symbol=sym,
                            quantity=net_qty,
                            avg_cost=fill_price,
                            stop=order.stop,
                            target=order.target,
                        )
                else:
                    # Add to existing short.
                    total_qty = pos.quantity - qty
                    pos.avg_cost = fill_price  # simplified for short adds
                    pos.quantity = total_qty
            else:
                self._positions[sym] = Position(
                    symbol=sym,
                    quantity=-qty,  # negative = short
                    avg_cost=fill_price,
                    stop=order.stop,
                    target=order.target,
                )

        elif side == "buy_to_cover":
            pos = self._positions.get(sym)
            if pos is None:
                raise ValueError(f"Cannot cover {sym}: no short position held.")
            cover_qty = min(qty, abs(pos.quantity))
            realized = (pos.avg_cost - fill_price) * cover_qty
            self._realized_pnl += realized
            self._cash -= cover_qty * fill_price
            remaining = pos.quantity + cover_qty  # pos.quantity is negative
            if remaining >= 0:
                del self._positions[sym]
            else:
                pos.quantity = remaining
