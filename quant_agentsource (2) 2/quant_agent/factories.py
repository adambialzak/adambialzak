"""
factories.py — resolve config strings to concrete component instances.

This is the single place where "sample" → SampleDataProvider,
"heuristic" → HeuristicReasoner, etc.  Adding a new backend only requires
editing this file.
"""

from __future__ import annotations

from quant_agent.config import Config
from quant_agent.data.base import MarketDataProvider
from quant_agent.reasoning.base import Reasoner


def make_data_provider(config: Config) -> MarketDataProvider:
    if config.data_provider == "sample":
        from quant_agent.data.sample import SampleDataProvider
        return SampleDataProvider(symbols=config.watchlist)
    elif config.data_provider == "yfinance":
        from quant_agent.data.yfinance_provider import YFinanceProvider
        return YFinanceProvider()
    else:
        raise ValueError(f"Unknown data_provider: {config.data_provider!r}")


def make_reasoner(config: Config) -> Reasoner:
    if config.reasoner == "heuristic":
        from quant_agent.reasoning.heuristic import HeuristicReasoner
        return HeuristicReasoner()
    elif config.reasoner == "anthropic":
        from quant_agent.reasoning.anthropic_reasoner import AnthropicReasoner
        return AnthropicReasoner(model=config.anthropic_model)
    else:
        raise ValueError(f"Unknown reasoner: {config.reasoner!r}")


def make_broker(config: Config):
    if config.broker == "paper":
        from quant_agent.broker.paper import PaperBroker
        return PaperBroker(starting_cash=config.starting_cash, costs=config.costs)
    elif config.broker == "webull":
        from quant_agent.broker.webull import WebullBroker
        return WebullBroker(live_enabled=config.live_enabled)
    else:
        raise ValueError(f"Unknown broker: {config.broker!r}")


def make_engine(config: Config):
    from quant_agent.engine import Engine
    from quant_agent.store import Store

    data = make_data_provider(config)
    reasoner = make_reasoner(config)
    broker = make_broker(config)
    store = Store(config.db_path)

    return Engine(
        config=config,
        data=data,
        reasoner=reasoner,
        broker=broker,
        store=store,
    )
