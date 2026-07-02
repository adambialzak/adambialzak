"""
cli.py — command-line interface for quant_agent.

Subcommands:
  cycle      — run one research+execution cycle
  simulate   — bounded walk-forward simulation
  run        — continuous daemon loop
  report     — print performance from the DB
  status     — show open positions and today's decisions

The disclaimer is always printed at startup.
"""

from __future__ import annotations

import argparse
import sys

from quant_agent.disclaimer import print_disclaimer


def _build_config(args: argparse.Namespace):
    from quant_agent.config import Config
    cfg = Config.from_env()

    if getattr(args, "live", False):
        cfg.live_enabled = True
        cfg.broker = "webull"
        # Double opt-in: interactive confirmation in addition to env token.
        confirm = input(
            "\n*** LIVE TRADING FLAG SET ***\n"
            "Type 'I_UNDERSTAND_REAL_MONEY' to proceed (anything else aborts): "
        ).strip()
        if confirm != "I_UNDERSTAND_REAL_MONEY":
            print("Live trading cancelled.")
            sys.exit(0)

    return cfg


def cmd_cycle(args: argparse.Namespace) -> None:
    cfg = _build_config(args)
    from quant_agent.factories import make_engine
    engine = make_engine(cfg)
    engine.run_cycle(verbose=not args.quiet)
    report = engine.report()
    print(report.render())
    engine._store.close()


def cmd_simulate(args: argparse.Namespace) -> None:
    cfg = _build_config(args)
    from quant_agent.factories import make_engine
    engine = make_engine(cfg)
    report = engine.simulate(cycles=args.cycles, verbose=not args.quiet)
    print(report.render())
    engine._store.close()


def cmd_run(args: argparse.Namespace) -> None:
    cfg = _build_config(args)
    from quant_agent.factories import make_engine
    from quant_agent.runner import ContinuousRunner
    engine = make_engine(cfg)
    runner = ContinuousRunner(
        engine=engine,
        interval_seconds=args.interval,
        max_cycles=args.max_cycles,
        report_every=args.report_every,
        market_hours_only=args.market_hours,
    )
    runner.run()


def cmd_report(args: argparse.Namespace) -> None:
    cfg = _build_config(args)
    from quant_agent.factories import make_engine
    engine = make_engine(cfg)
    report = engine.report()
    print(report.render())
    engine._store.close()


def cmd_status(args: argparse.Namespace) -> None:
    cfg = _build_config(args)
    from quant_agent.factories import make_data_provider, make_broker
    import sqlite3

    data = make_data_provider(cfg)
    broker = make_broker(cfg)
    prices = {sym: data.latest_price(sym) for sym in cfg.watchlist}
    snap = broker.snapshot(prices)

    print("\n=== OPEN POSITIONS ===")
    if not snap.positions:
        print("  (none)")
    for sym, pos in snap.positions.items():
        price = prices.get(sym, pos.avg_cost)
        pnl = pos.unrealized(price)
        print(f"  {sym:6s}  qty={pos.quantity:+d}  "
              f"cost=${pos.avg_cost:.2f}  price=${price:.2f}  "
              f"unreal={pnl:+.2f}")

    print(f"\n  Cash: ${snap.cash:,.2f}   Equity: ${snap.equity:,.2f}")

    # Latest decisions from DB.
    try:
        conn = sqlite3.connect(cfg.db_path)
        rows = conn.execute(
            "SELECT symbol, direction, conviction, qa_decision, rationale "
            "FROM decisions ORDER BY id DESC LIMIT 20"
        ).fetchall()
        conn.close()
        if rows:
            print("\n=== RECENT DECISIONS ===")
            for r in rows:
                print(f"  {r[0]:6s}  {r[1]:5s}  conv={r[2]:.2f}  "
                      f"{r[3]:8s}  {r[4][:60]}")
    except Exception:
        pass


def main() -> None:
    print_disclaimer()

    parser = argparse.ArgumentParser(
        prog="quant-agent",
        description="Autonomous research-driven paper trading platform.",
    )
    parser.add_argument("--live", action="store_true",
                        help="Enable live trading (requires two-factor opt-in).")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Suppress per-cycle verbose output.")

    sub = parser.add_subparsers(dest="command", required=True)

    # cycle
    p_cycle = sub.add_parser("cycle", help="Run one trading cycle.")
    p_cycle.set_defaults(func=cmd_cycle)

    # simulate
    p_sim = sub.add_parser("simulate", help="Bounded walk-forward simulation.")
    p_sim.add_argument("--cycles", type=int, default=40,
                       help="Number of cycles to simulate (default: 40).")
    p_sim.set_defaults(func=cmd_simulate)

    # run (daemon)
    p_run = sub.add_parser("run", help="Run as a continuous daemon.")
    p_run.add_argument("--interval", type=float, default=60.0,
                       help="Seconds between cycles (default: 60).")
    p_run.add_argument("--max-cycles", type=int, default=None,
                       help="Stop after N cycles (default: run forever).")
    p_run.add_argument("--report-every", type=int, default=20,
                       help="Print a full report every N cycles (default: 20).")
    p_run.add_argument("--market-hours", action="store_true",
                       help="Only run during US market hours (Mon–Fri 09:30–16:00 ET).")
    p_run.set_defaults(func=cmd_run)

    # report
    p_rep = sub.add_parser("report", help="Print performance report from DB.")
    p_rep.set_defaults(func=cmd_report)

    # status
    p_sta = sub.add_parser("status", help="Show open positions and recent decisions.")
    p_sta.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
