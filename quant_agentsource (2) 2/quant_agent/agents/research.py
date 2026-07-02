"""
agents/research.py — ResearchAgent: fetch data, compute features, produce thesis.

The agent is fault-tolerant: one bad symbol must not kill the whole cycle.
Errors are caught, logged, and the symbol is skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from quant_agent.data.base import MarketDataProvider
from quant_agent.reasoning.base import FeatureSet, Reasoner, Thesis, compute_features


@dataclass
class ResearchOutput:
    """Bundled result from researching a single symbol."""

    thesis: Thesis
    features: FeatureSet


class ResearchAgent:
    """Orchestrates data fetch → feature computation → thesis generation."""

    def __init__(
        self,
        data: MarketDataProvider,
        reasoner: Reasoner,
        history_days: int = 252,
    ) -> None:
        self._data = data
        self._reasoner = reasoner
        self._history_days = history_days

    def research(self, symbol: str) -> ResearchOutput:
        """Research a single symbol.  Raises on error — caller should catch."""
        bars = self._data.history(symbol, self._history_days)
        fundamentals = self._data.fundamentals(symbol)
        features = compute_features(symbol, bars, fundamentals)
        thesis = self._reasoner.analyze(features, fundamentals)
        return ResearchOutput(thesis=thesis, features=features)

    def research_universe(self, symbols: List[str]) -> List[ResearchOutput]:
        """
        Research every symbol in the watchlist.

        Errors for individual symbols are logged but do not abort the run;
        the rest of the universe is still processed.
        """
        results: List[ResearchOutput] = []
        for sym in symbols:
            try:
                results.append(self.research(sym))
            except Exception as exc:
                print(f"  [ResearchAgent] {sym} skipped: {exc}")
        return results
