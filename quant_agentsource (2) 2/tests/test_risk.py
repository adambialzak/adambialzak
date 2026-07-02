"""
tests/test_risk.py — unit tests for RiskManager position sizing.

Tests:
  1. Sizing equals risk-to-stop math
  2. Single-name cap enforced
  3. Low-conviction filtered out
  4. max_new_positions_per_cycle throttle
  5. Rejected theses are never sized

Run standalone:  python tests/test_risk.py
Or with pytest:  pytest tests/test_risk.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant_agent.risk import RiskManager, PortfolioState
from quant_agent.config import RiskLimits
from quant_agent.reasoning.base import Thesis
from quant_agent.agents.qa import Verdict


def _limits(**overrides) -> RiskLimits:
    lim = RiskLimits()
    for k, v in overrides.items():
        setattr(lim, k, v)
    return lim


def _thesis(symbol: str, direction: str = "long",
            entry: float = 100.0, stop: float = 90.0, target: float = 122.0,
            conviction: float = 0.70) -> Thesis:
    return Thesis(
        symbol=symbol,
        direction=direction,
        conviction=conviction,
        entry=entry,
        stop=stop,
        target=target,
        rationale="test",
        key_risks=["test risk"],
        source="test",
    )


def _verdict(symbol: str, decision: str = "APPROVE",
             conviction: float = 0.70) -> Verdict:
    return Verdict(
        symbol=symbol,
        decision=decision,
        adjusted_conviction=conviction,
    )


def _state(equity: float = 10_000.0, cash: float = 10_000.0,
           held: set = None) -> PortfolioState:
    return PortfolioState(
        equity=equity,
        cash=cash,
        held_symbols=held or set(),
        gross_exposure=0.0,
    )


# ---------------------------------------------------------------------------
# Test 1: sizing equals risk-to-stop math
# ---------------------------------------------------------------------------

def test_sizing_math():
    lim = _limits(per_trade_risk_pct=0.01, max_position_pct=0.50)
    rm = RiskManager(lim)
    t = _thesis("AAPL", entry=100.0, stop=90.0, conviction=0.70)
    v = _verdict("AAPL", conviction=0.70)
    orders = rm.size_orders([(t, v)], _state())
    assert len(orders) == 1
    o = orders[0]
    # risk_dollars = 10_000 * 0.01 * 0.70 = 70
    # stop_distance = 100 - 90 = 10
    # qty = int(70 / 10) = 7
    assert o.quantity == 7, f"qty: {o.quantity}"
    assert abs(o.risk_dollars - 70.0) < 0.01


# ---------------------------------------------------------------------------
# Test 2: single-name cap enforced
# ---------------------------------------------------------------------------

def test_single_name_cap():
    # max_position_pct=0.05 → max notional = 500; qty = int(500/100) = 5
    lim = _limits(max_position_pct=0.05, per_trade_risk_pct=0.10)
    rm = RiskManager(lim)
    t = _thesis("AAPL", entry=100.0, stop=80.0, conviction=0.90)
    v = _verdict("AAPL", conviction=0.90)
    orders = rm.size_orders([(t, v)], _state())
    assert len(orders) == 1
    # Uncapped: risk=90, stop_dist=20, qty=4 → notional=400 < 500 → fine
    # Let's use tighter cap so it definitely binds:
    # Actually with per_trade_risk_pct=0.10: risk=10_000*0.10*0.90=900
    # stop_dist=20 → raw_qty=45 → notional=4500 > 500 → capped
    # capped qty = int(500/100) = 5
    assert orders[0].quantity <= 5, f"qty: {orders[0].quantity}"


# ---------------------------------------------------------------------------
# Test 3: low-conviction filtered out
# ---------------------------------------------------------------------------

def test_low_conviction_filtered():
    lim = _limits(min_conviction_to_trade=0.60)
    rm = RiskManager(lim)
    t = _thesis("AAPL", conviction=0.50)
    v = _verdict("AAPL", conviction=0.50)   # below threshold
    orders = rm.size_orders([(t, v)], _state())
    assert len(orders) == 0, "low-conviction should be filtered"


# ---------------------------------------------------------------------------
# Test 4: max_new_positions_per_cycle throttle
# ---------------------------------------------------------------------------

def test_max_new_positions_throttle():
    lim = _limits(max_new_positions_per_cycle=2, per_trade_risk_pct=0.01,
                  max_position_pct=0.50)
    rm = RiskManager(lim)
    candidates = [
        (_thesis(sym, entry=100.0, stop=90.0), _verdict(sym, conviction=0.70))
        for sym in ["AAPL", "MSFT", "NVDA", "AMZN"]
    ]
    orders = rm.size_orders(candidates, _state())
    assert len(orders) <= 2, f"expected ≤2 orders, got {len(orders)}"


# ---------------------------------------------------------------------------
# Test 5: rejected theses are never sized
# ---------------------------------------------------------------------------

def test_rejected_never_sized():
    lim = _limits(per_trade_risk_pct=0.01, max_position_pct=0.50)
    rm = RiskManager(lim)
    t = _thesis("AAPL")
    v = Verdict(symbol="AAPL", decision="REJECT", adjusted_conviction=0.0)
    orders = rm.size_orders([(t, v)], _state())
    assert len(orders) == 0, "rejected thesis should never produce an order"


# ---------------------------------------------------------------------------
# Test 6: already-held symbols are skipped (no pyramiding)
# ---------------------------------------------------------------------------

def test_no_pyramiding():
    lim = _limits(per_trade_risk_pct=0.01, max_position_pct=0.50)
    rm = RiskManager(lim)
    t = _thesis("AAPL")
    v = _verdict("AAPL", conviction=0.70)
    state = _state(held={"AAPL"})
    orders = rm.size_orders([(t, v)], state)
    assert len(orders) == 0, "should not pyramid into existing position"


# ---------------------------------------------------------------------------
# Self-running harness
# ---------------------------------------------------------------------------

def _run_all():
    tests = [
        test_sizing_math,
        test_single_name_cap,
        test_low_conviction_filtered,
        test_max_new_positions_throttle,
        test_rejected_never_sized,
        test_no_pyramiding,
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
            import traceback; traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = _run_all()
    sys.exit(0 if ok else 1)
