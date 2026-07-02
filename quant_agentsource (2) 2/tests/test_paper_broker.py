"""
tests/test_paper_broker.py — unit tests for PaperBroker accounting.

Tests:
  1. buy → sell realizes correct profit
  2. short → cover realizes correct profit
  3. averaging-up computes correct average cost
  4. slippage makes buys fill worse than ref price
  5. protective exit triggers on stop breach

Run standalone:  python tests/test_paper_broker.py
Or with pytest:  pytest tests/test_paper_broker.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant_agent.broker.paper import PaperBroker
from quant_agent.broker.base import Order
from quant_agent.config import ExecutionCosts


def _broker(cash: float = 10_000.0, slippage_bps: float = 0.0, spread_bps: float = 0.0) -> PaperBroker:
    """Create a broker with controllable friction."""
    costs = ExecutionCosts(
        commission_per_trade=0.0,
        slippage_bps=slippage_bps,
        half_spread_bps=spread_bps,
    )
    return PaperBroker(starting_cash=cash, costs=costs)


# ---------------------------------------------------------------------------
# Test 1: buy → sell profit accounting
# ---------------------------------------------------------------------------

def test_buy_sell_profit():
    b = _broker()
    b.submit(Order("AAPL", "buy", 10), ref_price=100.0)
    assert abs(b.cash - 9_000.0) < 0.01, f"cash after buy: {b.cash}"
    b.submit(Order("AAPL", "sell", 10), ref_price=110.0)
    assert abs(b.cash - 10_100.0) < 0.01, f"cash after sell: {b.cash}"
    assert abs(b._realized_pnl - 100.0) < 0.01, f"realized_pnl: {b._realized_pnl}"
    assert "AAPL" not in b.positions(), "position should be closed"


# ---------------------------------------------------------------------------
# Test 2: short → cover profit accounting
# ---------------------------------------------------------------------------

def test_short_cover_profit():
    b = _broker()
    # Sell short 10 shares @ 100 → receive $1000
    b.submit(Order("AAPL", "sell_short", 10), ref_price=100.0)
    assert abs(b.cash - 11_000.0) < 0.01, f"cash after short: {b.cash}"
    # Cover at 90 → pay $900, profit $100
    b.submit(Order("AAPL", "buy_to_cover", 10), ref_price=90.0)
    assert abs(b.cash - 10_100.0) < 0.01, f"cash after cover: {b.cash}"
    assert abs(b._realized_pnl - 100.0) < 0.01, f"realized_pnl: {b._realized_pnl}"
    assert "AAPL" not in b.positions(), "short should be covered"


# ---------------------------------------------------------------------------
# Test 3: averaging-up average cost
# ---------------------------------------------------------------------------

def test_average_up_cost():
    b = _broker(cash=20_000.0)
    b.submit(Order("AAPL", "buy", 10), ref_price=100.0)  # avg = 100
    b.submit(Order("AAPL", "buy", 10), ref_price=120.0)  # avg = 110
    pos = b.positions()["AAPL"]
    assert pos.quantity == 20, f"quantity: {pos.quantity}"
    assert abs(pos.avg_cost - 110.0) < 0.01, f"avg_cost: {pos.avg_cost}"


# ---------------------------------------------------------------------------
# Test 4: slippage makes buys fill worse (higher price)
# ---------------------------------------------------------------------------

def test_slippage_buy_fills_worse():
    b = _broker(slippage_bps=10.0, spread_bps=5.0)  # 15 bps total
    fill = b.submit(Order("AAPL", "buy", 1), ref_price=100.0)
    expected = 100.0 * (1 + 0.0015)
    assert abs(fill.price - expected) < 0.01, f"fill: {fill.price}, expected: {expected}"
    assert fill.price > 100.0, "buy should fill above ref"


def test_slippage_sell_fills_worse():
    b = _broker(cash=20_000.0, slippage_bps=10.0, spread_bps=5.0)
    b.submit(Order("AAPL", "buy", 10), ref_price=100.0)  # use zero-friction broker... but need to get in
    # Re-create with friction for sell
    b2 = _broker(slippage_bps=10.0, spread_bps=5.0)
    b2._positions["AAPL"] = __import__(
        "quant_agent.broker.base", fromlist=["Position"]
    ).Position(symbol="AAPL", quantity=10, avg_cost=100.0)
    b2._cash = 0.0
    fill = b2.submit(Order("AAPL", "sell", 10), ref_price=100.0)
    assert fill.price < 100.0, "sell should fill below ref"


# ---------------------------------------------------------------------------
# Test 5: protective exit triggers on stop breach
# ---------------------------------------------------------------------------

def test_protective_stop_exit():
    b = _broker()
    b.submit(Order("AAPL", "buy", 10, stop=90.0, target=130.0), ref_price=100.0)
    pos = b.positions()["AAPL"]
    pos.stop = 90.0
    pos.target = 130.0

    # Price above stop — no exit.
    exits = b.check_protective_exits({"AAPL": 95.0})
    assert len(exits) == 0, f"should not exit at 95: {exits}"

    # Price hits stop — exit order emitted.
    exits = b.check_protective_exits({"AAPL": 89.0})
    assert len(exits) == 1, f"should exit at 89: {exits}"
    assert exits[0].side == "sell"
    assert exits[0].symbol == "AAPL"


def test_protective_target_exit():
    b = _broker()
    b.submit(Order("AAPL", "buy", 10, stop=90.0, target=130.0), ref_price=100.0)
    pos = b.positions()["AAPL"]
    pos.stop = 90.0
    pos.target = 130.0

    exits = b.check_protective_exits({"AAPL": 131.0})
    assert len(exits) == 1
    assert exits[0].side == "sell"


# ---------------------------------------------------------------------------
# Self-running harness (no pytest dependency)
# ---------------------------------------------------------------------------

def _run_all():
    tests = [
        test_buy_sell_profit,
        test_short_cover_profit,
        test_average_up_cost,
        test_slippage_buy_fills_worse,
        test_slippage_sell_fills_worse,
        test_protective_stop_exit,
        test_protective_target_exit,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = _run_all()
    sys.exit(0 if ok else 1)
