"""
runner.py — ContinuousRunner: unattended daemon loop.

Key behaviours:
  * Graceful shutdown on SIGINT/SIGTERM: finish the in-flight cycle, print a
    final report, close the DB, exit 0.
  * Error resilience: one bad cycle is logged; exponential backoff up to 60s;
    stop after 8 consecutive failures to avoid spinning on a broken state.
  * Market-hours gating: optional US equities hours check (09:30–16:00 ET,
    Mon–Fri).  Holidays are NOT modeled — the flag is most useful for live
    trading where placing orders outside hours would be rejected anyway.
  * Sample clock: when using SampleDataProvider, advance() is called each
    cycle so synthetic data never runs out.
"""

from __future__ import annotations

import signal
import time
from typing import Optional

from quant_agent.data.sample import SampleDataProvider
from quant_agent.engine import Engine


def _market_is_open() -> bool:
    """Return True if US equities are currently in their core session."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # type: ignore

    import datetime
    now = datetime.datetime.now(tz=ZoneInfo("America/New_York"))
    if now.weekday() >= 5:  # Sat=5, Sun=6
        return False
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now < market_close


class ContinuousRunner:
    """Runs the engine in a continuous loop until stopped or max_cycles reached."""

    def __init__(
        self,
        engine: Engine,
        interval_seconds: float = 60.0,
        max_cycles: Optional[int] = None,
        report_every: int = 20,
        market_hours_only: bool = False,
    ) -> None:
        self._engine = engine
        self._interval = interval_seconds
        self._max_cycles = max_cycles
        self._report_every = report_every
        self._market_hours_only = market_hours_only
        self._stop_flag = False
        self._cycles_run = 0

    def run(self) -> None:
        """Start the daemon loop.  Blocks until stopped."""
        self._install_signal_handlers()
        print(f"[Runner] Starting daemon loop (interval={self._interval}s"
              + (f", max_cycles={self._max_cycles}" if self._max_cycles else "")
              + ")")

        consecutive_errors = 0
        backoff = 2.0

        while not self._stop_flag:
            # Max cycles guard.
            if self._max_cycles is not None and self._cycles_run >= self._max_cycles:
                print(f"[Runner] Reached max_cycles={self._max_cycles}, stopping.")
                break

            # Market-hours gate.
            if self._market_hours_only and not _market_is_open():
                print("[Runner] Outside market hours — sleeping 60s.")
                self._interruptible_sleep(60)
                continue

            # Advance synthetic clock if applicable.
            if isinstance(self._engine._data, SampleDataProvider):
                self._engine._data.advance()

            try:
                self._engine.run_cycle(verbose=True)
                self._cycles_run += 1
                consecutive_errors = 0
                backoff = 2.0

                if self._cycles_run % self._report_every == 0:
                    report = self._engine.report()
                    print(report.render())

            except Exception as exc:
                consecutive_errors += 1
                print(f"[Runner] Cycle error #{consecutive_errors}: {exc}")
                if consecutive_errors >= 8:
                    print("[Runner] 8 consecutive failures — aborting daemon.")
                    break
                self._interruptible_sleep(min(backoff, 60.0))
                backoff = min(backoff * 2, 60.0)
                continue

            self._interruptible_sleep(self._interval)

        self._shutdown()

    def stop(self) -> None:
        """Signal the runner to stop after the current cycle."""
        self._stop_flag = True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        def _handler(signum, frame):
            print("\n[Runner] Shutdown signal received — finishing current cycle…")
            self._stop_flag = True

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep in small increments so SIGINT is handled quickly."""
        remaining = seconds
        while remaining > 0 and not self._stop_flag:
            time.sleep(min(0.5, remaining))
            remaining -= 0.5

    def _shutdown(self) -> None:
        print("[Runner] Generating final report…")
        try:
            report = self._engine.report()
            print(report.render())
        except Exception as exc:
            print(f"[Runner] Could not generate final report: {exc}")
        try:
            self._engine._store.close()
        except Exception:
            pass
        print(f"[Runner] Daemon exited after {self._cycles_run} cycles.")
