"""
disclaimer.py — risk disclosure printed at every startup.

This is not an attempt to scare users away; it is an attempt to be honest
about what this system is and is not.
"""

DISCLAIMER = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                        RISK DISCLOSURE — READ CAREFULLY                    ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  1. NOT FINANCIAL ADVICE.  This software is a research and educational       ║
║     tool.  Nothing it produces constitutes investment advice.  The authors   ║
║     are not registered investment advisers.  Consult a licensed professional ║
║     before making any real investment decision.                              ║
║                                                                              ║
║  2. HONESTY OVER FLATTERY.  Results are reported as they happen — wins       ║
║     and losses alike.  A system engineered to always look profitable on      ║
║     paper is precisely what you should distrust.                             ║
║                                                                              ║
║  3. RISK AND RETURN TRADE OFF.  This system controls and bounds risk; it     ║
║     does not eliminate it.  "Maximize profit while minimizing risk" is not   ║
║     achievable.  Higher expected returns come with higher expected losses.   ║
║                                                                              ║
║  4. PAPER ≠ LIVE.  Simulated and paper-trading performance does NOT predict  ║
║     live trading results.  Realistic frictions (slippage, spreads,           ║
║     commissions) are modeled but will still understate real-world costs.     ║
║     A long-running paper daemon is forward-testing, not proof of edge.      ║
║                                                                              ║
║  5. THE LLM IS A PLAUSIBILITY ENGINE, NOT AN EDGE.  Any AI reasoner is      ║
║     grounded in pre-computed numeric features.  It cannot invent prices.     ║
║     LLM judgment reflects patterns in training data, not market knowledge.  ║
║                                                                              ║
║  6. NO ACCIDENTAL PATH TO REAL MONEY.  Going live requires multiple         ║
║     deliberate opt-ins.  The default is always paper trading.               ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""


def print_disclaimer() -> None:
    """Print the risk disclosure to stdout."""
    print(DISCLAIMER)
