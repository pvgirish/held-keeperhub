#!/usr/bin/env python3
"""P05: drive the console's REAL mode against a live fork, and against dead sources.

The view-assembly tests use doubles. This exercises `LiveSources` against an actual RPC and
an actual journal, because "reads real sources" is a claim about real sources.

The property under test is still the honest failure: with a dead RPC the affected views must
report UNAVAILABLE and must NOT fall back to demonstration numbers.
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("console", "packages/core", "packages/handover", "packages/authority"):
    sys.path.insert(0, os.path.join(ROOT, p))

sys.path.insert(0, os.path.join(ROOT, "console"))
from run import LiveSources  # noqa: E402
from held_core.journal import Journal  # noqa: E402
from held_handover import Policy  # noqa: E402

RPC = os.environ["HELD_BASE_RPC"]
SAFE = os.environ["HELD_SAFE"]
CONTROLLER = os.environ["HELD_CONTROLLER"]
CHAIN = 8453

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
    if not ok:
        FAILS.append(name)


def policy() -> Policy:
    return Policy(Ls=50_000_000_000, Ln=50_000_000_000, Lr=10_000_000_000,
                  Ms=40_000_000_000, Mn=40_000_000_000, Mr=10_000_000_000,
                  ms=1_000_000, mn=1_000_000, F=0, H=0, Nn=10, Nr=5)


def main() -> int:
    print("P05 — console REAL mode against a live fork")
    print("=" * 70)

    jp = os.path.join(ROOT, "fixtures", "generated", "console-live-journal.sqlite")
    os.makedirs(os.path.dirname(jp), exist_ok=True)
    for s in ("", "-wal", "-shm"):
        if os.path.exists(jp + s):
            os.remove(jp + s)
    journal = Journal(jp)

    print("\n1. Working fork sources")
    live = LiveSources(controller=CONTROLLER, safe=SAFE, rpc=RPC, chain_id=CHAIN,
                       journal=journal, handover_id=None, policy=policy())
    views = live.views()
    check("terms loads from the chain", views["terms"].loaded,
          f"{views['terms'].summary}")
    check("terms is graded as fork evidence", views["terms"].grade == "REAL LOCAL FORK",
          views["terms"].grade)
    check("activity loads", views["activity"].loaded, views["activity"].summary)
    check("unresolved loads", views["unresolved"].loaded, views["unresolved"].summary)
    check("authority loads from the committed inventory", views["authority"].loaded,
          views["authority"].summary[:80])
    check("no handover in progress is stated, not blank",
          any(r["field"] == "handover state" for r in views["authority"].rows),
          "handover state row present")

    print("\n2. Dead RPC — must NOT fall back to demonstration numbers")
    dead = LiveSources(controller=CONTROLLER, safe=SAFE, rpc="http://127.0.0.1:1",
                       chain_id=CHAIN, journal=journal, handover_id=None, policy=policy())
    dv = dead.views()
    check("terms reports UNAVAILABLE", not dv["terms"].loaded and dv["terms"].grade == "UNAVAILABLE",
          dv["terms"].summary[:80])
    check("terms shows no rows", not dv["terms"].rows, f"{len(dv['terms'].rows)} rows")
    check("state() returns None rather than a fixture", dead.state() is None,
          "no LiveState is synthesised")
    check("a dead RPC does not blank the journal views",
          dv["activity"].loaded and dv["unresolved"].loaded,
          "activity and unresolved still load from the journal")

    print("\n3. Unreadable authority inventory")
    import held_console.live as live_mod
    real_inv = live.inventory
    try:
        live.inventory = lambda: None
        v = live.views()
        check("authority reports UNAVAILABLE", not v["authority"].loaded,
              v["authority"].summary[:80])
        check("terms still loads", v["terms"].loaded,
              "one dead source blanks only its own view")
    finally:
        live.inventory = real_inv

    print("\n4. No key material anywhere in the rendered views")
    blob = json.dumps({k: v.to_dict() for k, v in views.items()})
    leaked = [w for w in ("PRIVATE", "0x47e179ec", "kh_live", "BEGIN") if w in blob]
    check("no secret-looking value in the views", not leaked, str(leaked) or "clean")

    journal.close()
    print("\n" + "=" * 70)
    if FAILS:
        print(f"console-live: FAIL ({len(FAILS)}): {FAILS}")
        return 1
    print("console-live: PASS (REAL LOCAL FORK)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
