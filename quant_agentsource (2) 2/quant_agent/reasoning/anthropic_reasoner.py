"""
reasoning/anthropic_reasoner.py — LLM-backed reasoner using Anthropic Claude.

Important design constraints (see NON-NEGOTIABLE PRINCIPLES):
  * The LLM receives only pre-computed numeric features via as_text().
    It cannot see raw price history and cannot invent prices.
  * Entry, stop, and target prices always come from the heuristic baseline.
    The LLM can only adjust direction, conviction, rationale, and risk list.
  * On any network or parse error the heuristic result is returned as-is,
    so the system degrades gracefully without breaking a cycle.

The system prompt explicitly instructs the model to be skeptical and to
prefer "flat" on weak evidence — we do not want an LLM that always finds
a reason to trade.
"""

from __future__ import annotations

import json
import os
from typing import List

from quant_agent.data.base import Fundamentals
from quant_agent.reasoning.base import FeatureSet, Thesis
from quant_agent.reasoning.heuristic import HeuristicReasoner

_SYSTEM_PROMPT = """
You are a skeptical quantitative analyst reviewing a pre-computed feature set
for a single equity.  Your job is to decide whether to go long, short, or flat.

Rules you MUST follow:
1. Return ONLY a JSON object — no markdown, no prose outside the JSON.
2. The JSON must have exactly these keys:
   {"direction": "long"|"short"|"flat",
    "conviction": <float 0.0-1.0>,
    "rationale": "<one or two sentences>",
    "key_risks": ["<risk 1>", "<risk 2>", ...]}
3. Be skeptical.  Prefer "flat" when evidence is weak or mixed.
4. DO NOT invent prices.  You will not set entry, stop, or target — those
   are determined by the system from the numeric features.
5. Conviction above 0.8 requires a very strong, unambiguous setup.
6. Always include at least two key_risks even for high-conviction trades.
""".strip()


def _require_anthropic():
    try:
        import anthropic
        return anthropic
    except ImportError:
        raise ImportError(
            "anthropic is required for LLM reasoning.\n"
            "Install it with:  pip install anthropic\n"
            "Or run with --reasoner heuristic for the offline default."
        )


class AnthropicReasoner:
    """LLM reasoner using Anthropic Claude.  Falls back to heuristic on error."""

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self._model = model
        self._heuristic = HeuristicReasoner()
        self._client = None  # lazy init so import errors surface clearly

    def _get_client(self):
        if self._client is None:
            anthropic = _require_anthropic()
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise EnvironmentError(
                    "ANTHROPIC_API_KEY environment variable is not set.\n"
                    "Export it or run with --reasoner heuristic."
                )
            self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def analyze(self, features: FeatureSet, fundamentals: Fundamentals) -> Thesis:
        # Always compute the heuristic baseline first — it provides
        # entry/stop/target and serves as the fallback.
        baseline = self._heuristic.analyze(features, fundamentals)

        try:
            result = self._call_llm(features)
            direction = result.get("direction", baseline.direction)
            if direction not in ("long", "short", "flat"):
                direction = baseline.direction

            conviction = float(result.get("conviction", baseline.conviction))
            conviction = max(0.0, min(1.0, conviction))

            rationale = str(result.get("rationale", baseline.rationale))
            key_risks: List[str] = result.get("key_risks", baseline.key_risks)
            if not isinstance(key_risks, list):
                key_risks = baseline.key_risks

            return Thesis(
                symbol=features.symbol,
                direction=direction,
                conviction=round(conviction, 4),
                # Prices always come from the heuristic — LLM cannot move them.
                entry=baseline.entry,
                stop=baseline.stop,
                target=baseline.target,
                rationale=rationale,
                key_risks=key_risks,
                source="anthropic",
            )

        except Exception as exc:
            # Do not crash the cycle — just log and fall back.
            print(f"  [AnthropicReasoner] fallback to heuristic: {exc}")
            return baseline

    def _call_llm(self, features: FeatureSet) -> dict:
        client = self._get_client()
        response = client.messages.create(
            model=self._model,
            max_tokens=400,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": features.as_text()}],
        )
        text = response.content[0].text.strip()
        # Strip markdown code fences if present.
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
