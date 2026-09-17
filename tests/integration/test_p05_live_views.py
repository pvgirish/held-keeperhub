"""Do the four operator views tell the truth, including when they cannot be built?

The defect this file exists to prevent: a console that silently substitutes fixture data
when a source is unreachable. An operator would act on those numbers. A view that cannot be
built must SAY it cannot be built.

METHOD. The real `held_console.live` assembly against controller readings, journal rows and
inventories supplied by the test. These are view-construction tests; the live rendering is
`make check-phase-05` and the real chain path is `make hero-demo`.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in ("console", "packages/handover", "packages/authority", "packages/core"):
    sys.path.insert(0, os.path.join(ROOT, p))

from held_console.live import build_views, live_state_from, load_hero_trace  # noqa: E402
from held_handover import Policy  # noqa: E402
from held_handover.readback import ControllerStatus, read_controller_state  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

CONTROLLER = "0x5615deb798bb3e4dfa0139dfa1b3d433cc23b72f"
SAFE = "0x08deeda0ba1eb4b6b4b5cc4dd0c4bc689ea37180"
RUNNER = "0x15d34aaf54267db7d7c367839aaf71a00a2c6a65"
CHAIN = 8453


def test(name):
    def deco(fn):
        try:
            fn()
            PASSED.append(name)
            print(f"ok    {name}")
        except Exception:
            import traceback
            FAILED.append((name, traceback.format_exc()))
            print(f"FAIL  {name}")
        return fn
    return deco


class Source:
    def __init__(self, fail=False, **over):
        self.fail = fail
        self.state = {"chainId": CHAIN, "controller": CONTROLLER, "active": True,
                      "epoch": 1, "runner": RUNNER, "executor": RUNNER,
                      "policyVersion": 1, "blockNumber": 51353212, "finalized": False,
                      "usedSupply": 12_000_000, "usedNormalWithdraw": 0,
                      "usedRestoration": 0, "normalCount": 1, "restorationCount": 0}
        self.state.update(over)

    def read_controller(self, controller):
        if self.fail:
            raise RuntimeError("rpc unavailable")
        return dict(self.state)


def reading(src, dispatching=True):
    return read_controller_state(src, controller=CONTROLLER, expected_chain_id=CHAIN,
                                 adapter_dispatching=dispatching)


def policy():
    return Policy(Ls=50_000_000_000, Ln=50_000_000_000, Lr=10_000_000_000,
                  Ms=40_000_000_000, Mn=40_000_000_000, Mr=10_000_000_000,
                  ms=1_000_000, mn=1_000_000, F=0, H=0, Nn=10, Nr=5)


def inventory(**over):
    base = dict(section_count=9, complete=True, incomplete_sections=[],
                external_delegates=[], unsatisfied_obligations=[],
                evidence_grade="REAL LOCAL FORK",
                summary_lines=lambda: ["9 section(s) collected"])
    base.update(over)
    return SimpleNamespace(**base)


# ----------------------------------------------------------------- honest failure --

@test("a view whose source is unreachable says so and does NOT show fixture data")
def _():
    v = build_views(reading=reading(Source(fail=True)), policy=policy(),
                    operations=None, inventory=None)
    for name in ("terms", "activity", "unresolved", "authority"):
        assert v[name].loaded is False, f"{name} claimed to load with no source"
        assert v[name].grade == "UNAVAILABLE", v[name].grade
        assert v[name].problems, f"{name} failed silently"
        assert not v[name].rows, f"{name} produced rows from nothing"


@test("one dead source blanks only the view that needed it")
def _():
    v = build_views(reading=reading(Source()), policy=policy(),
                    operations=[], inventory=None)
    assert v["terms"].loaded is True
    assert v["activity"].loaded is True
    assert v["authority"].loaded is False, "a dead inventory blanked the whole console"


@test("an empty journal is an empty journal, not a failed read")
def _():
    v = build_views(reading=reading(Source()), policy=policy(), operations=[],
                    inventory=inventory())
    assert v["activity"].loaded is True
    assert "not a failed read" in v["activity"].summary, v["activity"].summary
    assert v["unresolved"].loaded is True
    assert "Nothing is in the air" in v["unresolved"].summary


# ------------------------------------------------------------------ grade honesty --

@test("a fork reading is graded REAL LOCAL FORK, never PUBLIC CHAIN")
def _():
    v = build_views(reading=reading(Source(finalized=False)), policy=policy(),
                    operations=[], inventory=inventory())
    assert v["terms"].grade == "REAL LOCAL FORK", v["terms"].grade


@test("KeeperHub execution and transaction show NOT ESTABLISHED when absent")
def _():
    v = build_views(reading=reading(Source()), policy=policy(),
                    operations=[{"operation_id": "0x" + "aa" * 32, "state": "CONFIRMED"}],
                    inventory=inventory())
    row = v["activity"].rows[0]
    assert row["keeperhubExecution"] == "NOT ESTABLISHED", row
    assert row["transaction"] == "NOT ESTABLISHED", row


# ------------------------------------------------------------- what blocks, and why --

@test("an UNKNOWN operation is shown as blocking, with the evidence it needs")
def _():
    ops = [{"operation_id": "0x" + "7e" * 32, "state": "UNKNOWN"},
           {"operation_id": "0x" + "aa" * 32, "state": "CONFIRMED"}]
    v = build_views(reading=reading(Source()), policy=policy(), operations=ops,
                    inventory=inventory())
    u = v["unresolved"]
    assert len(u.rows) == 1, u.rows
    assert "handover" in u.rows[0]["blocks"]
    assert "consumed[operationId]" in u.rows[0]["requiredEvidence"]
    assert "not a verified negative" in " ".join(u.problems)


@test("an incomplete inventory surfaces every incomplete section as a problem")
def _():
    v = build_views(reading=reading(Source()), policy=policy(), operations=[],
                    inventory=inventory(complete=False,
                                        incomplete_sections=["morpho_grants", "roles"]))
    assert "INCOMPLETE: morpho_grants" in v["authority"].problems
    assert "INCOMPLETE: roles" in v["authority"].problems


@test("a handover in progress shows its state, blockers and carried consumption")
def _():
    status = {"state": "BLOCKED", "retiringRunner": RUNNER, "awaitingOwner": False,
              "blockers": ["UNRESOLVED:0x7e7e"],
              "candidate": {"runner": "0x" + "bb" * 20, "expected": [12000000, 0, 0, 1, 0]}}
    v = build_views(reading=reading(Source()), policy=policy(), operations=[],
                    inventory=inventory(), handover_status=status)
    fields = {r["field"]: r["value"] for r in v["authority"].rows}
    assert fields["handover state"] == "BLOCKED"
    assert fields["consumption carried"] == [12000000, 0, 0, 1, 0]
    assert "UNRESOLVED:0x7e7e" in v["authority"].problems


@test("ADAPTER_REFUSING is shown as itself, never as a fence")
def _():
    v = build_views(reading=reading(Source(), dispatching=False), policy=policy(),
                    operations=[], inventory=inventory())
    status = {r["field"]: r["value"] for r in v["terms"].rows}["status"]
    assert status == ControllerStatus.ADAPTER_REFUSING.value, status
    assert "OWNER_FENCED" not in v["terms"].summary


# ------------------------------------------------------------------------ remaining --

@test("Terms computes remaining rather than asserting it")
def _():
    v = build_views(reading=reading(Source()), policy=policy(), operations=[],
                    inventory=inventory())
    supply = [r for r in v["terms"].rows if r["field"] == "supply ceiling"][0]
    assert supply["used"] == 12_000_000
    assert supply["remaining"] == 50_000_000_000 - 12_000_000, supply


@test("LiveState adapts from a real reading, and refuses an unusable one")
def _():
    good = live_state_from(reading(Source()), policy(), safe=SAFE)
    assert good is not None and good.epoch == 1
    assert good.budgets[0].remaining == 50_000_000_000 - 12_000_000
    assert live_state_from(reading(Source(fail=True)), policy(), safe=SAFE) is None


@test("the committed hero trace, if present, is a fork trace and says so")
def _():
    trace = load_hero_trace(ROOT)
    if trace is None:
        print("      (no hero trace committed; skipped)")
        return
    assert trace["evidenceGrade"] == "REAL LOCAL FORK", trace["evidenceGrade"]
    assert "NOT a public-chain execution" in trace["_scope"]
    assert len(trace["steps"]) >= 12, len(trace["steps"])


# ------------------------------------------------- R8: the ACTUAL console binary --

@test("R8: live mode refuses to start without real sources rather than falling back")
def _():
    # The finding: --state-source was documented and never implemented; the console always
    # built the demonstration state. A console that silently shows demo numbers when the
    # chain is unreachable is worse than one that will not start.
    import subprocess
    out = subprocess.run(
        [sys.executable, os.path.join(ROOT, "console", "run.py"),
         "--state-source", "live", "--port", "0"],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "HELD_CONSOLE_SECRET": "x", "HELD_BASE_RPC": ""})
    assert out.returncode == 2, (out.returncode, out.stdout[:400], out.stderr[:400])
    assert "live mode needs" in out.stderr, out.stderr[:400]
    assert "demonstration" in out.stderr, "it did not say why it refused"


@test("R8: the console exposes both modes, and demo mode is labelled")
def _():
    import subprocess
    out = subprocess.run(
        [sys.executable, os.path.join(ROOT, "console", "run.py"), "--help"],
        capture_output=True, text=True, timeout=60)
    assert "--state-source" in out.stdout, out.stdout[:400]
    assert "{demo,live}" in out.stdout.replace(" ", ""), out.stdout[:400]
    src = open(os.path.join(ROOT, "console", "run.py")).read()
    assert "DEMONSTRATION STATE — not evidence" in src
    # ...and live mode must never construct the demonstration state.
    live_block = src[src.index('if args.state_source == "live":'):src.index("    else:")]
    assert "demonstration_state" not in live_block, "live mode can reach the demo state"


def main() -> int:
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"P05 live views: FAIL ({len(FAILED)}/{len(PASSED) + len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} live operator-view tests held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
