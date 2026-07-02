"""
store.py — SQLite audit trail.

Every decision (acted or not), every fill, and every equity snapshot is
persisted.  This means any open position can be fully explained by tracing
back through the decisions table — critical for a system that may run
unattended for weeks.

Schema is created automatically on first open.  Thread-safety is not
guaranteed; use one Store instance per process.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import List, Optional, Tuple


class Store:
    """SQLite-backed audit trail for decisions, fills, and equity snapshots."""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._create_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS decisions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL NOT NULL,
                cycle       INTEGER NOT NULL,
                symbol      TEXT NOT NULL,
                direction   TEXT NOT NULL,
                conviction  REAL NOT NULL,
                qa_decision TEXT NOT NULL,
                qa_issues   TEXT NOT NULL,   -- JSON array
                rationale   TEXT NOT NULL,
                acted       INTEGER NOT NULL, -- 0 or 1
                detail      TEXT             -- free-form JSON
            );

            CREATE TABLE IF NOT EXISTS fills (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL NOT NULL,
                cycle       INTEGER NOT NULL,
                symbol      TEXT NOT NULL,
                side        TEXT NOT NULL,
                quantity    INTEGER NOT NULL,
                price       REAL NOT NULL,
                commission  REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS equity (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL NOT NULL,
                cycle       INTEGER NOT NULL,
                cash        REAL NOT NULL,
                equity      REAL NOT NULL,
                realized_pnl REAL NOT NULL
            );
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write methods
    # ------------------------------------------------------------------

    def log_decision(
        self,
        cycle: int,
        symbol: str,
        direction: str,
        conviction: float,
        qa_decision: str,
        qa_issues: List[str],
        rationale: str,
        acted: bool,
        detail: Optional[dict] = None,
    ) -> None:
        self._conn.execute(
            """INSERT INTO decisions
               (ts, cycle, symbol, direction, conviction, qa_decision, qa_issues,
                rationale, acted, detail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(), cycle, symbol, direction, conviction,
                qa_decision, json.dumps(qa_issues), rationale,
                1 if acted else 0,
                json.dumps(detail) if detail else None,
            ),
        )
        self._conn.commit()

    def log_fill(
        self,
        cycle: int,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        commission: float,
    ) -> None:
        self._conn.execute(
            """INSERT INTO fills (ts, cycle, symbol, side, quantity, price, commission)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (time.time(), cycle, symbol, side, quantity, price, commission),
        )
        self._conn.commit()

    def log_equity(self, cycle: int, cash: float, equity: float, realized_pnl: float) -> None:
        self._conn.execute(
            """INSERT INTO equity (ts, cycle, cash, equity, realized_pnl)
               VALUES (?, ?, ?, ?, ?)""",
            (time.time(), cycle, cash, equity, realized_pnl),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    def equity_curve(self) -> List[float]:
        """Return equity values in cycle order."""
        cur = self._conn.execute("SELECT equity FROM equity ORDER BY id ASC")
        return [row[0] for row in cur.fetchall()]

    def realized_pnl_series(self) -> List[Tuple[int, str, float]]:
        """Return (cycle, symbol, pnl_proxy) from fills for closed trades."""
        # Approximate realized P&L from fill prices; exact figures are in
        # PaperBroker._realized_pnl.
        cur = self._conn.execute(
            "SELECT cycle, symbol, side, quantity, price FROM fills ORDER BY id ASC"
        )
        return cur.fetchall()

    def close(self) -> None:
        self._conn.close()
