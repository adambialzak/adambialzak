"""
broker/webull.py — Webull OpenAPI broker adapter.

This module connects to Webull's official OpenAPI via the
`webull-openapi-python-sdk` package.

Safety gates (BOTH must be satisfied for live orders):
  1. config.live_enabled must be True (set via --live CLI flag).
  2. env var QA_WEBULL_LIVE_CONFIRM must equal "I_UNDERSTAND_REAL_MONEY".

Without both gates, all orders are routed to the UAT (paper) endpoint.
This is a deliberate multi-factor opt-in to prevent accidental real trades.

Required environment variables:
  QA_WEBULL_APP_KEY       — Webull API application key
  QA_WEBULL_APP_SECRET    — Webull API application secret
  QA_WEBULL_ACCOUNT_ID    — trading account ID
  QA_WEBULL_REGION        — region code, e.g. "US"

References:
  https://developer.webull.com/apis/docs/
"""

from __future__ import annotations

import os
from typing import Dict

from quant_agent.broker.base import AccountSnapshot, Fill, Order, Position


_LIVE_CONFIRM_TOKEN = "I_UNDERSTAND_REAL_MONEY"


def _require_sdk():
    try:
        from webull.core.client import ApiClient  # noqa: F401
        from webull.trade.trade_client import TradeClient  # noqa: F401
        import webull
        return webull
    except ImportError:
        raise ImportError(
            "webull-openapi-python-sdk is required for live/UAT trading.\n"
            "Install it with:  pip install webull-openapi-python-sdk\n"
            "Or run in paper mode with --broker paper"
        )


def _webull_side(side: str) -> str:
    """Map our internal side string to a Webull action string."""
    mapping = {
        "buy": "BUY",
        "sell": "SELL",
        "sell_short": "SELL",    # Webull uses BUY/SELL + positionSide
        "buy_to_cover": "BUY",
    }
    return mapping[side]


class WebullBroker:
    """
    Broker implementation backed by Webull's official OpenAPI.

    Defaults to UAT endpoint; only routes to production when both safety
    gates are satisfied.
    """

    def __init__(self, live_enabled: bool = False) -> None:
        wb = _require_sdk()

        app_key = os.environ["QA_WEBULL_APP_KEY"]
        app_secret = os.environ["QA_WEBULL_APP_SECRET"]
        self._account_id = os.environ["QA_WEBULL_ACCOUNT_ID"]
        region = os.getenv("QA_WEBULL_REGION", "US")

        confirm_token = os.getenv("QA_WEBULL_LIVE_CONFIRM", "")
        self._is_live = live_enabled and confirm_token == _LIVE_CONFIRM_TOKEN

        if not self._is_live:
            print("[WebullBroker] Connecting to UAT (paper) endpoint.")
        else:
            print("[WebullBroker] *** LIVE TRADING ENABLED — REAL MONEY ***")

        # The Webull OpenAPI SDK uses ApiClient for configuration.
        from webull.core.client import ApiClient, Configuration
        from webull.trade.trade_client import TradeClient

        config = Configuration(
            app_key=app_key,
            app_secret=app_secret,
            region=region,
        )
        if not self._is_live:
            # Point to the UAT sandbox host if supported.
            config.host = "https://openapi-sandbox.webull.com"

        self._client = TradeClient(ApiClient(config))

    # ------------------------------------------------------------------
    # Broker interface
    # ------------------------------------------------------------------

    def submit(self, order: Order, ref_price: float) -> Fill:
        """Place a DAY market order via Webull OpenAPI."""
        from webull.trade.models import PlaceOrderRequest

        req = PlaceOrderRequest(
            account_id=self._account_id,
            symbol=order.symbol,
            action=_webull_side(order.side),
            order_type="MKT",
            time_in_force="DAY",
            quantity=order.quantity,
        )
        response = self._client.place_order(req)

        # Use ref_price as fill price estimate; a real implementation would
        # poll for execution details.
        return Fill(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=ref_price,
            commission=0.0,
        )

    def positions(self) -> Dict[str, Position]:
        """Fetch open positions from Webull."""
        raw = self._client.get_positions(account_id=self._account_id)
        result: Dict[str, Position] = {}
        for p in raw:
            sym = p.symbol
            qty = int(p.quantity)
            cost = float(p.cost_price or p.last_price or 0)
            result[sym] = Position(symbol=sym, quantity=qty, avg_cost=cost)
        return result

    def snapshot(self, prices: Dict[str, float]) -> AccountSnapshot:
        """Return account snapshot from Webull account data."""
        acct = self._client.get_account(account_id=self._account_id)
        cash = float(acct.settled_funds or 0)
        equity = float(acct.net_liquidation or cash)
        positions = self.positions()
        return AccountSnapshot(cash=cash, equity=equity, positions=positions)

    @property
    def cash(self) -> float:
        acct = self._client.get_account(account_id=self._account_id)
        return float(acct.settled_funds or 0)
