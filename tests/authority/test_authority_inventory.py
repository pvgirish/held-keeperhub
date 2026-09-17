"""Does the authority inventory interpret the collector's report honestly?

METHOD. `held_authority.from_report` against report shapes the real collector produces.
The collector itself is exercised by tests/integration/test_p03_bootstrap_collector.py (43
decision tests) and against a live fork by `make check-bootstrap-rehearsal`; this file is
about the INTERPRETATION layer the handover machine depends on.

The interesting property is negative: "no external delegates" must only be reported when
the grant section could actually read. A section that failed tells us nothing, and an
unknown is not a verified negative -- reporting one as the other would clear a handover
that should have blocked.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "packages/authority"))

from held_authority import from_report  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


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


def report(**overrides):
    base = {
        "observation": {"block_number": 51353228, "chain_id": 8453,
                        "finality": "NONE — anvil fork."},
        "safe": {"verdict": "COMPLETE"},
        "roles": {"verdict": "COMPLETE"},
        "morpho_grants": {"verdict": "COMPLETE", "external_delegates": []},
        "held_controller": {"verdict": "COMPLETE"},
        "clause_to_evidence": [{"obligation": "o1", "satisfied": True}],
        "verdict": {"incomplete_sections": [], "activation_would_be": "PERMITTED BY THIS CHECKLIST"},
    }
    base.update(overrides)
    return base


@test("a clean report is complete, with every section counted")
def _():
    inv = from_report(report())
    assert inv.complete is True
    assert inv.section_count == 4, inv.sections.keys()
    assert inv.external_delegates == []
    assert inv.unsatisfied_obligations == []


@test("an incomplete section makes the whole inventory incomplete")
def _():
    inv = from_report(report(verdict={"incomplete_sections": ["roles"]}))
    assert inv.complete is False
    assert inv.incomplete_sections == ["roles"]


@test("an UNREADABLE grant section does not report 'no external delegates'")
def _():
    # The decisive case. If the grant section could not read, we do not know whether an
    # external delegate exists -- and saying "none" would clear a handover that should
    # have blocked.
    inv = from_report(report(
        morpho_grants={"verdict": "INCOMPLETE", "external_delegates": []},
        verdict={"incomplete_sections": []}))
    assert inv.complete is False, "an unreadable grant section was treated as clean"
    assert "morpho_grants" in inv.incomplete_sections
    assert inv.external_delegates == [], "it invented delegates it could not see"


@test("a real external delegate is surfaced for the owner to decide on")
def _():
    inv = from_report(report(
        morpho_grants={"verdict": "COMPLETE", "external_delegates": ["0x" + "ee" * 20]}))
    assert inv.external_delegates == ["0x" + "ee" * 20]
    assert any("owner decides" in line for line in inv.summary_lines()), inv.summary_lines()


@test("an anvil fork is never labelled PUBLIC CHAIN evidence")
def _():
    inv = from_report(report())
    assert inv.evidence_grade == "REAL LOCAL FORK", inv.evidence_grade
    assert "BOUNDED" in inv.to_dict()["_scope"]


@test("unsatisfied clause obligations are reported even when sections pass")
def _():
    inv = from_report(report(clause_to_evidence=[
        {"obligation": "both roles verified", "satisfied": False},
        {"obligation": "budgets read", "satisfied": True}]))
    assert inv.unsatisfied_obligations == ["both roles verified"]


@test("the live rehearsal artifact in this repo parses and reports its real state")
def _():
    path = os.path.join(ROOT, "evidence", "P03", "bootstrap-rehearsal.json")
    if not os.path.exists(path):
        print("      (no rehearsal artifact committed; skipped)")
        return
    with open(path) as fh:
        inv = from_report(json.load(fh))
    assert inv.section_count >= 7, inv.sections.keys()
    assert inv.evidence_grade == "REAL LOCAL FORK", (
        "the committed rehearsal is a fork run and must not be graded as public")
    print(f"      committed rehearsal: complete={inv.complete}, "
          f"{inv.section_count} sections, {len(inv.clauses)} obligations")


def main() -> int:
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"P04 authority: FAIL ({len(FAILED)}/{len(PASSED) + len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} authority inventory tests held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
