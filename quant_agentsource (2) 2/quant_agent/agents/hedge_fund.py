"""
agents/hedge_fund.py — HedgeFundAnalystAgent: conservative, quality-first filter.

Philosophy: "smaller wins, very little downside."

After QA approves a thesis, the HF analyst applies a second, more conservative
layer of scrutiny modelled on how a long/short equity hedge fund evaluates ideas:

  * Avoid macro landmines: reject high-beta, high-vol names.
  * Only trade names in clean structural uptrends (longs: above SMA200 is hard).
  * Keep RSI in the neutral zone — no chasing momentum extremes.
  * Diversify by sector: no more than 2 open positions in any one sector.
  * Size down for uncertainty; size up for quality.
  * Track a quality score 0–100; require ≥ MIN_QUALITY to proceed.

Integration: sits between QA and the RiskManager.  The engine passes each
QA-approved (thesis, features, verdict) triple through here; the returned
HFVerdict carries an `approved` flag and an `adjusted_conviction` that
replaces the QA conviction for risk sizing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set

from quant_agent.agents.qa import Verdict
from quant_agent.reasoning.base import FeatureSet, Thesis


# Sectors considered "defensive" — lower hurdles for approval.
_DEFENSIVE_SECTORS: Set[str] = {
    "Consumer Staples",
    "Healthcare",
    "Utilities",
    "Real Estate",
}

# Sectors that attract extra scrutiny when volatile.
_CYCLICAL_SECTORS: Set[str] = {
    "Technology",
    "Energy",
    "Consumer Discretionary",
    "Materials",
}


@dataclass
class HFVerdict:
    """Hedge-fund analyst review result for a single thesis."""

    symbol: str
    approved: bool
    quality_score: float          # 0–100 composite
    adjusted_conviction: float    # conviction to use for sizing (may be lower than QA)
    issues: List[str] = field(default_factory=list)
    notes: str = ""


class HedgeFundAnalystAgent:
    """
    Conservative quality filter applied after QA approval.

    Calibrated to produce a high win rate with small, reliable gains:
    - Strict vol and beta ceilings keep tails thin.
    - RSI neutrality avoids buying exhaustion.
    - Sector caps prevent crowding.
    - Quality score gates out marginal ideas.
    """

    # --- Hard limits --------------------------------------------------------
    MAX_ANNUAL_VOL: float = 0.38       # Reject names more volatile than this.
    MAX_BETA: float = 1.50             # Reject names too correlated to the market.
    MAX_DRAWDOWN_FLOOR: float = -0.28  # Reject names that have crashed > 28%.
    MIN_QUALITY: float = 42.0          # Minimum quality score to pass (0–100).

    # RSI band for healthy trend (not overbought, not deeply sold-off).
    LONG_RSI_MIN: float = 32.0
    LONG_RSI_MAX: float = 72.0
    SHORT_RSI_MIN: float = 28.0
    SHORT_RSI_MAX: float = 68.0

    # Max positions in the same sector (sector crowding guard).
    MAX_SAME_SECTOR: int = 2

    def __init__(self) -> None:
        # Tracks sector counts for currently OPEN positions.
        # The engine updates this via `update_sector_counts()`.
        self._sector_counts: Dict[str, int] = {}

    def update_sector_counts(self, sector_map: Dict[str, str]) -> None:
        """
        Called each cycle with {symbol: sector} for currently held positions.
        Enables the sector-crowding guard without the agent needing broker access.
        """
        counts: Dict[str, int] = {}
        for sector in sector_map.values():
            counts[sector] = counts.get(sector, 0) + 1
        self._sector_counts = counts

    def review(
        self,
        thesis: Thesis,
        features: FeatureSet,
        qa_verdict: Verdict,
    ) -> HFVerdict:
        """
        Evaluate a QA-approved thesis through a hedge-fund quality lens.

        Returns HFVerdict.approved=False to block the trade, or True with a
        (possibly lower) adjusted_conviction for conservative sizing.
        """
        issues: List[str] = []
        conviction = qa_verdict.adjusted_conviction
        score = 50.0   # Start at neutral; adjustments move it up or down.

        # ----------------------------------------------------------------
        # Hard REJECTs
        # ----------------------------------------------------------------

        if features.annual_vol > self.MAX_ANNUAL_VOL:
            return HFVerdict(
                symbol=thesis.symbol,
                approved=False,
                quality_score=0.0,
                adjusted_conviction=0.0,
                issues=[f"Vol {features.annual_vol*100:.0f}% > HF ceiling "
                        f"{self.MAX_ANNUAL_VOL*100:.0f}%."],
                notes="Too volatile for a conservative mandate.",
            )

        if features.beta > self.MAX_BETA:
            return HFVerdict(
                symbol=thesis.symbol,
                approved=False,
                quality_score=0.0,
                adjusted_conviction=0.0,
                issues=[f"Beta {features.beta:.2f} > HF ceiling {self.MAX_BETA:.2f}."],
                notes="Excessive market sensitivity.",
            )

        if features.max_drawdown < self.MAX_DRAWDOWN_FLOOR:
            return HFVerdict(
                symbol=thesis.symbol,
                approved=False,
                quality_score=0.0,
                adjusted_conviction=0.0,
                issues=[f"Max drawdown {features.max_drawdown*100:.1f}% "
                        f"< floor {self.MAX_DRAWDOWN_FLOOR*100:.0f}%."],
                notes="Structural damage — HF avoids broken charts.",
            )

        # Longs must be in an established uptrend.
        if thesis.direction == "long" and not features.above_sma200:
            return HFVerdict(
                symbol=thesis.symbol,
                approved=False,
                quality_score=0.0,
                adjusted_conviction=0.0,
                issues=["Long thesis: price below 200-SMA (HF hard rule)."],
                notes="HF only buys names above the 200-day trend line.",
            )

        # RSI range check — avoid buying exhausted or deeply oversold (whipsaw).
        if thesis.direction == "long":
            if not (self.LONG_RSI_MIN <= features.rsi14 <= self.LONG_RSI_MAX):
                return HFVerdict(
                    symbol=thesis.symbol,
                    approved=False,
                    quality_score=0.0,
                    adjusted_conviction=0.0,
                    issues=[f"RSI {features.rsi14:.0f} outside HF long band "
                            f"[{self.LONG_RSI_MIN:.0f}, {self.LONG_RSI_MAX:.0f}]."],
                    notes="Momentum too extreme — risk of reversal.",
                )
        elif thesis.direction == "short":
            if not (self.SHORT_RSI_MIN <= features.rsi14 <= self.SHORT_RSI_MAX):
                return HFVerdict(
                    symbol=thesis.symbol,
                    approved=False,
                    quality_score=0.0,
                    adjusted_conviction=0.0,
                    issues=[f"RSI {features.rsi14:.0f} outside HF short band "
                            f"[{self.SHORT_RSI_MIN:.0f}, {self.SHORT_RSI_MAX:.0f}]."],
                    notes="Momentum too extreme — risk of short squeeze.",
                )

        # Sector crowding guard. The count includes both currently-held
        # positions and names already approved earlier in THIS cycle (each
        # approval increments the map below), so the cap binds intra-cycle.
        sector = features.sector or "Unknown"
        current_sector_count = self._sector_counts.get(sector, 0)
        if current_sector_count >= self.MAX_SAME_SECTOR:
            return HFVerdict(
                symbol=thesis.symbol,
                approved=False,
                quality_score=0.0,
                adjusted_conviction=0.0,
                issues=[f"Sector '{sector}' already at {current_sector_count} "
                        f"positions (cap={self.MAX_SAME_SECTOR})."],
                notes="Sector concentration limit reached.",
            )

        # ----------------------------------------------------------------
        # Quality scoring  (adjustments to the base 50 pts)
        # ----------------------------------------------------------------

        # Volatility: lower is better for a conservative mandate.
        if features.annual_vol < 0.18:
            score += 18.0
        elif features.annual_vol < 0.25:
            score += 10.0
        elif features.annual_vol < 0.32:
            score += 4.0
        else:
            score -= 5.0

        # Beta: defensive orientation preferred.
        if features.beta < 0.75:
            score += 18.0
        elif features.beta < 1.0:
            score += 10.0
        elif features.beta < 1.25:
            score += 3.0
        else:
            score -= 6.0

        # Trend alignment: both SMAs confirms quality.
        if features.above_sma200:
            score += 8.0
        if features.above_sma50:
            score += 6.0

        # RSI neutrality: sweet spot 42–62 gets full bonus.
        if 42.0 <= features.rsi14 <= 62.0:
            score += 12.0
        elif 35.0 <= features.rsi14 <= 68.0:
            score += 6.0

        # Drawdown: shallow drawdowns indicate a resilient chart.
        if features.max_drawdown > -0.08:
            score += 10.0
        elif features.max_drawdown > -0.15:
            score += 5.0
        elif features.max_drawdown < -0.22:
            score -= 8.0

        # Sector premium: defensive sectors get extra credit.
        if sector in _DEFENSIVE_SECTORS:
            score += 8.0
        elif sector in _CYCLICAL_SECTORS and features.annual_vol > 0.28:
            score -= 5.0

        # Conviction from QA acts as a signal-quality multiplier.
        score += (qa_verdict.adjusted_conviction - 0.55) * 20.0  # ±10 range

        score = max(0.0, min(100.0, score))

        if score < self.MIN_QUALITY:
            return HFVerdict(
                symbol=thesis.symbol,
                approved=False,
                quality_score=round(score, 1),
                adjusted_conviction=0.0,
                issues=[f"Quality score {score:.1f} < minimum {self.MIN_QUALITY}."],
                notes="Below HF quality threshold.",
            )

        # ----------------------------------------------------------------
        # Conviction soft adjustments (approved, sizing scaled conservatively)
        # ----------------------------------------------------------------

        if features.beta > 1.0:
            cut = 0.10
            conviction = max(0.0, conviction - cut)
            issues.append(f"Beta {features.beta:.2f} > 1.0 — conviction cut {cut:.0%}.")

        if features.annual_vol > 0.28:
            cut = 0.08
            conviction = max(0.0, conviction - cut)
            issues.append(f"Vol {features.annual_vol*100:.0f}% > 28% — conviction cut {cut:.0%}.")

        if features.max_drawdown < -0.18:
            cut = 0.08
            conviction = max(0.0, conviction - cut)
            issues.append(f"Deep drawdown {features.max_drawdown*100:.1f}% — cut {cut:.0%}.")

        # Cyclical sector under scrutiny: trim further.
        if sector in _CYCLICAL_SECTORS:
            cut = 0.06
            conviction = max(0.0, conviction - cut)
            issues.append(f"Cyclical sector '{sector}' — cut {cut:.0%}.")

        # Quality premium: high-score names get a small conviction boost.
        if score >= 75.0:
            boost = 0.06
            conviction = min(1.0, conviction + boost)
            issues.append(f"High quality {score:.0f}/100 — conviction boosted {boost:.0%}.")

        notes = (
            f"HF quality {score:.0f}/100. "
            + ("Passed with adjustments." if issues else "Clean approval.")
        )

        # Count this approval so later candidates in the SAME cycle see the
        # updated sector exposure and the crowding cap binds within the cycle.
        # (update_sector_counts() resets this map from held positions each cycle.)
        self._sector_counts[sector] = current_sector_count + 1

        return HFVerdict(
            symbol=thesis.symbol,
            approved=True,
            quality_score=round(score, 1),
            adjusted_conviction=round(conviction, 4),
            issues=issues,
            notes=notes,
        )
