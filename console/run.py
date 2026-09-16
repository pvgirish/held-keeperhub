#!/usr/bin/env python3
"""Run the private operator console locally.

    HELD_CONSOLE_SECRET=... python console/run.py [--journal PATH] [--port N]

Binds to 127.0.0.1 only. The console holds no keys and cannot move funds: it reads state
and prepares owner actions that the owner executes in their own Safe.

Without --state-source it renders from a DEMONSTRATION state, clearly labelled in the
banner, so the interface can be reviewed without a fork running. That demonstration state
is NOT evidence about any deployed controller.
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "core"))
sys.path.insert(0, os.path.join(ROOT, "console"))

from held_console.app import Console, serve  # noqa: E402
from held_console.state import Budget, LiveState  # noqa: E402
from held_core.journal import Journal  # noqa: E402


def demonstration_state() -> LiveState:
    """Plausible shapes for reviewing the interface. Not a reading of any chain."""
    return LiveState(
        controller="0x3875311cc0d4017a033893a9653a0725378aca1c",
        safe="0x08deEDA0Ba1eb4B6B4b5cc4DD0c4BC689EA37180",
        active=True, epoch=3, policy_version=1,
        runner="0x90F79bf6EB2c4f870365E785982E1f101E93b906",
        executor="0x976EA74026E726554dB657fA54763abd0C3a0aa9",
        budgets=[
            Budget("supply", 50_000_000_000, 17_500_000_000),
            Budget("normal_withdraw", 20_000_000_000, 2_400_000_000),
            Budget("restoration", 10_000_000_000, 0),
            Budget("normal_count", 100, 12, unit="operations"),
        ],
        native_remaining={
            "supply": 32_500_000_000, "normal_withdraw": 17_600_000_000,
            "restoration": 10_000_000_000, "normal_count": 88,
        },
        cooldowns={"normal": 3600, "restoration": 0},
    )


class EmptyJournal:
    def unresolved(self): return []
    def attempts_for(self, oid): return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal", help="path to the durable journal (SQLite)")
    ap.add_argument("--port", type=int, default=8799)
    args = ap.parse_args()

    journal = Journal(args.journal) if args.journal else EmptyJournal()
    console = Console(demonstration_state, journal)
    srv = serve(console, "127.0.0.1", args.port)
    print(f"held console on http://127.0.0.1:{args.port}  (localhost only, no keys held)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
