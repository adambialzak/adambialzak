"""
engine.py — Engine orchestrator.

One cycle:
  1. Mark prices; run protective exits (PaperBroker); record realized P&L.
  2. Research the universe.
  3. QA every thesis; log every decision.
  4. Size approved theses.
  5. Execute orders; log fills; log acted decisions.
  6. Snapshot equity.

simulate(cycles) drives the sample clock forward and returns a PerformanceReport.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from quant_agent.agents.hedge_fund import HedgeFundAnalystAgent
from quant_agent.agents.qa import QAAgent
from quant_agent.agents.research import ResearchAgent
from quant_agent.broker.base import Broker, Order
from quant_agent.broker.paper import PaperBroker
from quant_agent.config import Config
from quant_agent.data.base import MarketDataProvider
from quant_agent.data.sample import SampleDataProvider
from quant_agent.portfolio import PerformanceReport, compute_performance
from quant_agent.reasoning.base import Reasoner
from quant_agent.risk import PortfolioState, RiskManager
from quant_agent.store import Store


class Engine:
    """Orchestrates one trading cycle and wraps bounded simulation."""

    def __init__(
        self,
        config: Config,
        data: MarketDataProvider,
        reasoner: Reasoner,
        broker: Broker,
        store: Store,
    ) -> None:
        self._config = config
        self._data = data
        self._reasoner = reasoner
        self._broker = broker
        self._store = store

        self._research_agent = ResearchAgent(data, reasoner)
        self._qa_agent = QAAgent()
        self._hf_agent = HedgeFundAnalystAgent()
        self._risk_manager = RiskManager(config.risk)
        self._cycle = 0
        self._starting_equity = config.starting_cash
        self._closed_trade_pnls: List[float] = []
        # Cooldown: maps symbol -> cycle number when it last exited.
        # Prevents re-entering a name within COOLDOWN_CYCLES of an exit.
        self._exit_cycle: Dict[str, int] = {}
        self.COOLDOWN_CYCLES: int = 5

    # ------------------------------------------------------------------
    # Single cycle
    # ------------------------------------------------------------------

    def run_cycle(self, verbose: bool = True) -> None:
        self._cycle += 1
        cycle = self._cycle
        watchlist = self._config.watchlist

        # --- 1. Current prices ---
        prices: Dict[str, float] = {
            sym: self._data.latest_price(sym) for sym in watchlist
        }

        # --- 1b. Protective exits (PaperBroker only) ---
        if isinstance(self._broker, PaperBroker):
            exit_orders = self._broker.check_protective_exits(prices)
            if exit_orders and verbose:
                print(f"  [Cycle {cycle}] Protective exits: {len(exit_orders)}")
            pre_snap = self._broker.snapshot(prices)
            for order in exit_orders:
                ref = prices.get(order.symbol, 0.0)
                if ref > 0:
                    fill = self._broker.submit(order, ref)
                    self._store.log_fill(cycle, fill.symbol, fill.side,
                                         fill.quantity, fill.price, fill.commission)
                    # Record exit cycle for cooldown enforcement.
                    self._exit_cycle[fill.symbol] = cycle
                    if verbose:
                        print(f"    EXIT {fill.side.upper()} {fill.quantity} "
                              f"{fill.symbol} @ ${fill.price:.2f}")
            post_snap = self._broker.snapshot(prices)
            trade_pnl = post_snap.realized_pnl - pre_snap.realized_pnl
            if trade_pnl != 0:
                self._closed_trade_pnls.append(trade_pnl)

        # --- 2. Research ---
        if verbose:
            print(f"  [Cycle {cycle}] Researching {len(watchlist)} symbols…")
        outputs = self._research_agent.research_universe(watchlist)

        # --- 3. QA ---
        candidates = []
        for out in outputs:
            verdict = self._qa_agent.review(out.thesis, out.features)
            self._store.log_decision(
                cycle=cycle,
                symbol=out.thesis.symbol,
                direction=out.thesis.direction,
                conviction=out.thesis.conviction,
                qa_decision=verdict.decision,
                qa_issues=verdict.issues,
                rationale=out.thesis.rationale,
                acted=False,  # updated below if order executed
            )
            if verbose:
                status = "✓" if verdict.approved else "✗"
                print(f"    {status} {out.thesis.symbol:6s} "
                      f"{out.thesis.direction:5s} "
                      f"conv={out.thesis.conviction:.2f} "
                      f"→ {verdict.decision}"
                      + (f" ({'; '.join(verdict.issues[:1])})" if verdict.issues else ""))
            if verdict.approved:
                candidates.append((out.thesis, verdict))

        # --- 3b. Hedge-fund quality filter ---
        # Update the HF agent's view of current sector exposure.
        if isinstance(self._broker, PaperBroker):
            snap_for_sectors = self._broker.snapshot(prices)
            sector_map: Dict[str, str] = {}
            for out in outputs:
                if out.thesis.symbol in snap_for_sectors.positions:
                    sector_map[out.thesis.symbol] = out.features.sector
            self._hf_agent.update_sector_counts(sector_map)

        hf_candidates = []
        for thesis, verdict in candidates:
            # Look up the FeatureSet for this thesis.
            features_for_sym = next(
                (o.features for o in outputs if o.thesis.symbol == thesis.symbol), None
            )
            if features_for_sym is None:
                hf_candidates.append((thesis, verdict))
                continue
            hf_verdict = self._hf_agent.review(thesis, features_for_sym, verdict)
            if verbose:
                hf_status = "HF✓" if hf_verdict.approved else "HF✗"
                print(f"    {hf_status} {thesis.symbol:6s} "
                      f"q={hf_verdict.quality_score:.0f}/100 "
                      f"conv={hf_verdict.adjusted_conviction:.2f}"
                      + (f" ({'; '.join(hf_verdict.issues[:1])})" if hf_verdict.issues else ""))
            if hf_verdict.approved:
                # Replace verdict conviction with the HF-adjusted value.
                from quant_agent.agents.qa import Verdict as _Verdict
                merged_verdict = _Verdict(
                    symbol=verdict.symbol,
                    decision=verdict.decision,
                    issues=verdict.issues + hf_verdict.issues,
                    adjusted_conviction=hf_verdict.adjusted_conviction,
                    notes=f"{verdict.notes} | HF: {hf_verdict.notes}",
                )
                hf_candidates.append((thesis, merged_verdict))
        candidates = hf_candidates

        # --- 3c. Cooldown filter ---
        # Drop candidates that exited within the last COOLDOWN_CYCLES cycles
        # to prevent immediately re-entering a churning position.
        cooled_candidates = []
        for thesis, verdict in candidates:
            last_exit = self._exit_cycle.get(thesis.symbol, -999)
            if cycle - last_exit <= self.COOLDOWN_CYCLES:
                if verbose:
                    print(f"    ~ {thesis.symbol:6s} cooldown ({cycle - last_exit} cycles since exit)")
                continue
            cooled_candidates.append((thesis, verdict))
        candidates = cooled_candidates

        # --- 4. Size orders ---
        snap = self._broker.snapshot(prices)
        state = PortfolioState(
            equity=snap.equity,
            cash=snap.cash,
            held_symbols=set(snap.positions.keys()),
            gross_exposure=sum(
                abs(pos.market_value_at(prices.get(sym, pos.avg_cost)))
                for sym, pos in snap.positions.items()
            ),
        )
        sized = self._risk_manager.size_orders(candidates, state)

        # --- 5. Execute ---
        for so in sized:
            ref = prices.get(so.symbol, so.entry)
            order = Order(
                symbol=so.symbol,
                side=so.side,
                quantity=so.quantity,
                stop=so.stop,
                target=so.target,
            )
            # Attach stop/target to the position record.
            if isinstance(self._broker, PaperBroker):
                order.stop = so.stop
                order.target = so.target
            fill = self._broker.submit(order, ref)
            self._store.log_fill(cycle, fill.symbol, fill.side,
                                  fill.quantity, fill.price, fill.commission)
            # Update the decision record to mark it acted.
            self._store.log_decision(
                cycle=cycle,
                symbol=so.symbol,
                direction="long" if so.side == "buy" else "short",
                conviction=so.conviction,
                qa_decision="ACTED",
                qa_issues=[],
                rationale=so.rationale,
                acted=True,
                detail={"qty": so.quantity, "fill_price": fill.price},
            )
            if verbose:
                print(f"    EXEC {so.side.upper()} {so.quantity} "
                      f"{so.symbol} @ ${fill.price:.2f} "
                      f"(risk=${so.risk_dollars:.0f})")

        # --- 6. Equity snapshot ---
        final_snap = self._broker.snapshot(prices)
        self._store.log_equity(cycle, final_snap.cash, final_snap.equity,
                                final_snap.realized_pnl)

        if verbose and isinstance(self._broker, PaperBroker):
            print(f"  [Cycle {cycle}] Equity: ${final_snap.equity:,.2f}  "
                  f"Cash: ${final_snap.cash:,.2f}  "
                  f"Positions: {len(final_snap.positions)}")

    # ------------------------------------------------------------------
    # Bounded simulation (walk-forward)
    # ------------------------------------------------------------------

    def simulate(self, cycles: int, verbose: bool = True) -> PerformanceReport:
        """
        Run `cycles` cycles advancing the sample clock each time.

        This is walk-forward testing, not backtesting — each cycle only
        uses data that would have been available at that point in time.
        """
        if isinstance(self._data, SampleDataProvider):
            self._data.reset_clock(lookback=252)

        for i in range(cycles):
            if verbose and i % 10 == 0:
                print(f"[simulate] cycle {i+1}/{cycles}")
            self.run_cycle(verbose=False)
            if isinstance(self._data, SampleDataProvider):
                self._data.advance()

        return self.report()

    # ------------------------------------------------------------------
    # Performance report from DB
    # ------------------------------------------------------------------

    def report(self) -> PerformanceReport:
        curve = self._store.equity_curve()
        snap = self._broker.snapshot({})
        return compute_performance(
            equity_curve=curve,
            realized_pnl=snap.realized_pnl if hasattr(snap, "realized_pnl") else 0.0,
            closed_trade_pnls=self._closed_trade_pnls,
            starting_equity=self._starting_equity,
        )
