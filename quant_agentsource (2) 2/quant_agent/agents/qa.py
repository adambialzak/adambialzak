"""
agents/qa.py — QAAgent: independent, deterministic adversarial review.

The QA agent does NOT use the research reasoner.  It re-derives its own
view from raw features and applies a set of hard rules to catch common
thesis errors before they reach the risk manager.

Why an independent agent?
  * Separation of duties: the same model that produced the thesis should not
    also approve it.
  * Determinism: QA decisions are rule-based and reproducible, so every
    REJECT/REVISE can be explained precisely.

Verdict decisions:
  APPROVE  — thesis is internally consistent and passes all checks.
  REVISE   — thesis is approved but conviction was cut due to a concern.
  REJECT   — thesis has a hard problem and should not be traded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from quant_agent.reasoning.base import FeatureSet, Thesis


class _Decision:
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    REJECT = "REJECT"


@dataclass
class Verdict:
    """QA review result for a single thesis."""

    symbol: str
    decision: str           # APPROVE | REVISE | REJECT
    issues: List[str] = field(default_factory=list)
    adjusted_conviction: float = 0.0
    notes: str = ""

    @property
    def approved(self) -> bool:
        """True for APPROVE and REVISE — both may proceed to risk sizing."""
        return self.decision in (_Decision.APPROVE, _Decision.REVISE)


class QAAgent:
    """Deterministic, rule-based adversarial reviewer."""

    # Minimum reward-to-risk ratio to pass QA.
    MIN_RR: float = 1.8

    # Stop distance must be at least this many daily-vol units to avoid
    # being stopped out by routine noise on the very next bar.
    MIN_STOP_VOL_MULTIPLE: float = 1.5

    def review(self, thesis: Thesis, features: FeatureSet) -> Verdict:
        issues: List[str] = []
        conviction = thesis.conviction

        # --- Hard REJECTs ---

        if thesis.direction == "flat":
            return Verdict(
                symbol=thesis.symbol,
                decision=_Decision.REJECT,
                issues=["Direction is flat — no trade thesis."],
                adjusted_conviction=0.0,
                notes="Flat theses are not acted upon.",
            )

        rr = thesis.reward_risk
        if rr < self.MIN_RR:
            return Verdict(
                symbol=thesis.symbol,
                decision=_Decision.REJECT,
                issues=[f"Reward:risk {rr:.2f} < minimum {self.MIN_RR:.1f}"],
                adjusted_conviction=0.0,
                notes="Poor risk-adjusted setup; skip.",
            )

        # Internal consistency: for a long, stop < entry < target.
        if thesis.direction == "long":
            if not (thesis.stop < thesis.entry < thesis.target):
                return Verdict(
                    symbol=thesis.symbol,
                    decision=_Decision.REJECT,
                    issues=["Long thesis: requires stop < entry < target."],
                    adjusted_conviction=0.0,
                    notes="Price levels are inconsistent.",
                )
        elif thesis.direction == "short":
            if not (thesis.target < thesis.entry < thesis.stop):
                return Verdict(
                    symbol=thesis.symbol,
                    decision=_Decision.REJECT,
                    issues=["Short thesis: requires target < entry < stop."],
                    adjusted_conviction=0.0,
                    notes="Price levels are inconsistent.",
                )

        if not thesis.key_risks:
            return Verdict(
                symbol=thesis.symbol,
                decision=_Decision.REJECT,
                issues=["No key risks listed — thesis is incomplete."],
                adjusted_conviction=0.0,
                notes="A thesis without identified risks is overconfident.",
            )

        # Stop too tight relative to daily noise: the position will be stopped
        # out by a single bad tick rather than a genuine trend reversal.
        # daily_vol = annual_vol / sqrt(252); stop must be >= MIN_STOP_VOL_MULTIPLE days wide.
        import math
        daily_vol = features.annual_vol / math.sqrt(252) if features.annual_vol > 0 else 0.01
        stop_distance_pct = abs(thesis.entry - thesis.stop) / thesis.entry if thesis.entry else 0
        min_stop_pct = daily_vol * self.MIN_STOP_VOL_MULTIPLE
        if stop_distance_pct < min_stop_pct:
            return Verdict(
                symbol=thesis.symbol,
                decision=_Decision.REJECT,
                issues=[
                    f"Stop too tight: {stop_distance_pct*100:.2f}% < "
                    f"{min_stop_pct*100:.2f}% ({self.MIN_STOP_VOL_MULTIPLE}× daily vol). "
                    f"Routine noise will trigger exit."
                ],
                adjusted_conviction=0.0,
                notes="Stop is inside the daily noise band.",
            )

        # --- Conditional conviction cuts (REVISE) ---

        decision = _Decision.APPROVE

        # Long thesis but price is below 200-day SMA → counter-trend.
        if thesis.direction == "long" and not features.above_sma200:
            cut = 0.15
            conviction = max(0.0, conviction - cut)
            issues.append(f"Long below 200-SMA — conviction cut by {cut:.0%}.")
            decision = _Decision.REVISE

        # Buying into overbought / shorting into oversold.
        if thesis.direction == "long" and features.rsi14 > 80:
            cut = 0.12
            conviction = max(0.0, conviction - cut)
            issues.append(f"RSI {features.rsi14:.0f} overbought on long — cut {cut:.0%}.")
            decision = _Decision.REVISE

        if thesis.direction == "short" and features.rsi14 < 20:
            cut = 0.12
            conviction = max(0.0, conviction - cut)
            issues.append(f"RSI {features.rsi14:.0f} oversold on short — cut {cut:.0%}.")
            decision = _Decision.REVISE

        # Extreme volatility reduces the quality of any signal.
        if features.annual_vol > 0.60:
            factor = 0.80
            conviction = conviction * factor
            issues.append(
                f"Extreme vol {features.annual_vol*100:.0f}% — conviction scaled to {factor:.0%}."
            )
            decision = _Decision.REVISE

        notes = "Passed with adjustments." if decision == _Decision.REVISE else "Clean approval."
        return Verdict(
            symbol=thesis.symbol,
            decision=decision,
            issues=issues,
            adjusted_conviction=round(conviction, 4),
            notes=notes,
        )
