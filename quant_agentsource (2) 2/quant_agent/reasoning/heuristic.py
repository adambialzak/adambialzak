"""
reasoning/heuristic.py — transparent, rule-based reasoner (offline default).

Every scoring rule is explicit and auditable.  There is no black box here.
The scores and thresholds were chosen to be internally consistent, not to
look good on backtests — no in-sample fitting was done.

Stops and targets are scaled by volatility so noisier names get wider bands,
targeting roughly a 2.2:1 reward-to-risk ratio.
"""

from __future__ import annotations

import math
from typing import List

from quant_agent.data.base import Fundamentals
from quant_agent.reasoning.base import FeatureSet, Thesis


class HeuristicReasoner:
    """Deterministic, rule-based reasoner.  No network calls, no randomness."""

    def analyze(self, features: FeatureSet, fundamentals: Fundamentals) -> Thesis:
        score, rationale_parts, risks = self._score(features)

        # Map score to direction and conviction.
        if score >= 0.20:
            direction = "long"
            conviction = min(0.90, 0.55 + score * 0.8)
        elif score <= -0.20:
            direction = "short"
            conviction = min(0.90, 0.55 + abs(score) * 0.8)
        else:
            direction = "flat"
            conviction = max(0.0, 0.5 - abs(score))

        price = features.price
        vol = max(features.annual_vol, 0.10)  # floor vol so stops aren't zero

        # Stop distance = 1× daily-vol-equivalent; target = 2.2× stop distance.
        # Use 20-day horizon: daily vol * sqrt(20) ≈ monthly vol.
        stop_dist = price * vol / math.sqrt(252) * math.sqrt(20)
        target_dist = stop_dist * 2.2

        if direction == "long":
            stop = round(price - stop_dist, 4)
            target = round(price + target_dist, 4)
        elif direction == "short":
            stop = round(price + stop_dist, 4)
            target = round(price - target_dist, 4)
        else:
            stop = price
            target = price

        rationale = "Heuristic signals: " + "; ".join(rationale_parts) if rationale_parts else "No clear edge."

        return Thesis(
            symbol=features.symbol,
            direction=direction,
            conviction=round(conviction, 4),
            entry=round(price, 4),
            stop=stop,
            target=target,
            rationale=rationale,
            key_risks=risks,
            source="heuristic",
        )

    # ------------------------------------------------------------------
    # Internal scoring
    # ------------------------------------------------------------------

    def _score(self, f: FeatureSet) -> tuple[float, List[str], List[str]]:
        score = 0.0
        parts: List[str] = []
        risks: List[str] = []

        # Trend relative to long-term average.
        if f.above_sma200:
            score += 0.20
            parts.append("above 200-day SMA (+)")
        else:
            score -= 0.15
            parts.append("below 200-day SMA (−)")
            risks.append("Price in long-term downtrend")

        # Medium-term trend.
        if f.above_sma50:
            score += 0.10
            parts.append("above 50-day SMA (+)")
        else:
            risks.append("Price below 50-day SMA")

        # Momentum.
        if f.momentum > 0.05:
            score += 0.20
            parts.append(f"positive momentum {f.momentum*100:.1f}% (+)")
        elif f.momentum < -0.05:
            score -= 0.20
            parts.append(f"negative momentum {f.momentum*100:.1f}% (−)")
            risks.append("Sustained price decline")

        # Overbought / oversold via RSI.
        if f.rsi14 > 75:
            score -= 0.12
            parts.append("RSI overbought >75 (−)")
            risks.append("Overbought; elevated reversal risk")
        elif f.rsi14 < 30:
            score += 0.08
            parts.append("RSI oversold <30 (+)")
            risks.append("Oversold but may continue lower")

        # Valuation via P/E.
        if not math.isnan(f.pe_ratio):
            if f.pe_ratio < 18:
                score += 0.10
                parts.append(f"cheap valuation P/E={f.pe_ratio:.1f} (+)")
            elif f.pe_ratio > 40:
                score -= 0.10
                parts.append(f"expensive valuation P/E={f.pe_ratio:.1f} (−)")
                risks.append("High valuation multiple compresses margin of safety")

        # High volatility penalises conviction.
        if f.annual_vol > 0.45:
            score -= 0.10
            parts.append(f"high volatility {f.annual_vol*100:.0f}% (−)")
            risks.append("High volatility increases position sizing risk")

        # Always include a generic macro risk.
        risks.append("Macro / sector-wide drawdown could invalidate thesis")

        return score, parts, risks
