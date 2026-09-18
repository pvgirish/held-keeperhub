#!/usr/bin/env python3
"""Run the private operator console locally.

    HELD_CONSOLE_SECRET=... python console/run.py --state-source live \\
        --controller 0x... --safe 0x... --rpc http://127.0.0.1:8545 --journal PATH

Binds to 127.0.0.1 only. The console holds no keys and cannot move funds: it reads state
and prepares owner actions that the owner executes in their own Safe.

## Two modes, and they never blend

    live   reads the ACTUAL controller, journal, bounded inventory and handover record.
           If a source cannot be read, the affected view renders UNAVAILABLE with the
           reason. It does NOT fall back to demonstration numbers -- an operator would act
           on those, which is worse than showing nothing.

    demo   renders a clearly labelled demonstration state so the interface can be reviewed
           without a fork running. It is NOT evidence about any deployed controller and the
           banner says so.

`--state-source` used to be documented here and not implemented: the console always built
the demonstration state regardless. That is the gap this file closes.
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("packages/core", "packages/handover", "packages/authority", "console"):
    sys.path.insert(0, os.path.join(ROOT, p))

from held_console.app import Console, serve  # noqa: E402
from held_console.live import build_views, live_state_from  # noqa: E402
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


class LiveSources:
    """Real state, assembled per request. A dead source blanks its view and nothing else."""

    def __init__(self, *, controller: str, safe: str, rpc: str, chain_id: int,
                 journal, handover_id: str | None) -> None:
        self.controller = controller
        self.safe = safe
        self.rpc = rpc
        self.chain_id = chain_id
        self.journal = journal
        self.handover_id = handover_id

    @staticmethod
    def policy_from(reading):
        """The ACTIVE policy, read off the controller. Never a constant.

        The console used to carry a hard-coded 50,000 ceiling, so Terms showed a remaining
        figure derived from a number nobody had read. If the policy cannot be decoded the
        answer is None, and Terms renders UNAVAILABLE rather than substituting one.
        """
        from held_handover import Policy

        raw = getattr(reading, "policy_raw", None)
        if not raw:
            return None
        parts = [p.strip().split()[0] for p in str(raw).strip().split("\n") if p.strip()]
        if len(parts) < 12:
            return None
        try:
            v = [int(x) for x in parts[:14]]
        except ValueError:
            return None
        while len(v) < 14:
            v.append(0)
        return Policy(*v)

    def reading(self):
        from held_handover.readback import read_controller_state
        from held_handover.sources import CastControllerSource
        # No finality source: a local fork has none, so this grades REAL LOCAL FORK.
        return read_controller_state(
            CastControllerSource(self.rpc), controller=self.controller,
            expected_chain_id=self.chain_id, adapter_dispatching=False)

    def operations(self):
        """None means the journal could not be read -- which is not the same as empty."""
        try:
            rows = self.journal._db.execute(  # noqa: SLF001 - read-only accessor
                "SELECT operation_id, state, epoch FROM operations "
                "ORDER BY updated_at DESC LIMIT 50").fetchall()
        except Exception:  # noqa: BLE001
            return None
        return [{"operation_id": r["operation_id"], "state": r["state"],
                 "epoch": r["epoch"]} for r in rows]

    def inventory(self):
        """The bounded inventory, WITH its observation boundary checked.

        A stored report is not current evidence. It used to be loaded and presented as the
        authority view without its block or scope ever being compared to this installation,
        so a report collected against something else, or long before, would have rendered
        as though it described the live Safe.
        """
        import json

        from held_authority import HANDOVER_REPORT, INITIAL_REPORT, from_report

        # The two collection modes now write separate files. A live console describes an
        # installation that may be mid-life, so the handover report is preferred when one
        # exists; the initial-activation rehearsal is the fallback. Whichever is read, the
        # scope check below still has to pass -- preferring a file is not trusting it.
        last = None
        for rel in (HANDOVER_REPORT, INITIAL_REPORT):
            path = os.path.join(ROOT, rel)
            if not os.path.exists(path):
                continue
            try:
                with open(path) as fh:
                    inv = from_report(json.load(fh))
            except Exception:  # noqa: BLE001
                continue

            problems = inv.scope_problems(chain_id=self.chain_id,
                                          controller=self.controller, safe=self.safe)
            if not problems:
                return inv
            # Out of scope for this installation. Surfaced as incomplete rather than shown.
            inv.incomplete_sections = list(inv.incomplete_sections) + [
                f"stored report out of scope: {p}" for p in problems]
            inv.complete = False
            last = last or inv
        return last

    def handover(self):
        if not self.handover_id:
            return None
        try:
            from held_handover import HandoverMachine
            m = HandoverMachine.load(self.journal, self.handover_id)
            return m.status() if m else None
        except Exception:  # noqa: BLE001
            return None

    def state(self) -> LiveState | None:
        r = self.reading()
        p = self.policy_from(r)
        if p is None:
            return None
        return live_state_from(r, p, safe=self.safe)

    def views(self):
        r = self.reading()
        return build_views(reading=r, policy=self.policy_from(r),
                           operations=self.operations(), inventory=self.inventory(),
                           handover_status=self.handover())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-source", choices=("demo", "live"), default="demo",
                    help="'live' reads the real controller/journal/inventory; 'demo' "
                         "renders a clearly labelled demonstration state")
    ap.add_argument("--journal", help="path to the durable journal (SQLite)")
    ap.add_argument("--controller", help="controller address (live mode)")
    ap.add_argument("--safe", help="Safe address (live mode)")
    ap.add_argument("--rpc", default=os.environ.get("HELD_BASE_RPC", ""),
                    help="RPC endpoint (live mode)")
    ap.add_argument("--chain-id", type=int, default=8453)
    ap.add_argument("--handover-id", help="a handover in progress, if any")
    ap.add_argument("--port", type=int, default=8799)
    args = ap.parse_args()

    journal = Journal(args.journal) if args.journal else EmptyJournal()

    if args.state_source == "live":
        missing = [n for n in ("controller", "safe", "rpc") if not getattr(args, n)]
        if missing:
            print(f"live mode needs --{', --'.join(missing)}. Refusing to start: a console "
                  "that silently fell back to demonstration numbers would be worse than "
                  "one that did not start.", file=sys.stderr)
            return 2
        sources = LiveSources(
            controller=args.controller, safe=args.safe, rpc=args.rpc,
            chain_id=args.chain_id, journal=journal, handover_id=args.handover_id)

        def state_fn():
            s = sources.state()
            if s is None:
                raise RuntimeError(
                    "the controller or its policy could not be read. This console does NOT "
                    "substitute demonstration data; fix the source or use "
                    "--state-source demo.")
            return s

        console = Console(state_fn, journal)
        console.views = sources.views          # the four V4 §8 views, from real sources
        banner = f"LIVE — controller {args.controller} on chain {args.chain_id}"
    else:
        console = Console(demonstration_state, journal)
        banner = "DEMONSTRATION STATE — not evidence about any deployed controller"

    srv = serve(console, "127.0.0.1", args.port)
    print(f"held console on http://127.0.0.1:{args.port}  (localhost only, no keys held)")
    print(f"  {banner}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
