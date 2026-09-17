#!/usr/bin/env python3
"""The submission gate. Mandatory items are not waived by strong engineering.

P08: a deterministic checklist that says BLOCKED or READY and cannot be talked round. It
reads the repository's own claim ledger and evidence rather than asking anyone how it went,
because the whole point is to catch the case where the engineering is good and a mandatory
requirement is simply absent.

Exit 0 = READY FOR SUBMISSION AUTHORIZATION. Exit 1 = BLOCKED.

Being READY is not permission to submit. Publication, repository visibility and DoraHacks
submission all need separate explicit authorization, and this gate grants none of it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MANDATORY: list[tuple[str, str]] = [
    ("M1", "A real transaction executed through KeeperHub"),
    ("M2", "The transaction corresponds to the integrated workflow"),
    ("M3", "Source is public and accessible"),
    ("M4", "A working demo video"),
]

blocked: list[str] = []
warned: list[str] = []
ok: list[str] = []


def check(name: str, passed: bool, detail: str, *, mandatory: bool = True) -> None:
    if passed:
        ok.append(f"{name}: {detail}")
        print(f"  [PASS ] {name} — {detail}")
    elif mandatory:
        blocked.append(f"{name}: {detail}")
        print(f"  [BLOCK] {name} — {detail}")
    else:
        warned.append(f"{name}: {detail}")
        print(f"  [WARN ] {name} — {detail}")


def read(path: str) -> str | None:
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return None
    with open(full) as fh:
        return fh.read()


def main() -> int:
    print("HELD — submission gate")
    print("=" * 74)

    # ------------------------------------------------ the claim ledger is the source --
    ledger = read("docs/submission/CLAIM-LEDGER.md")
    if ledger is None:
        print("  [BLOCK] no claim ledger — nothing can be verified against anything")
        return 1

    print("\nMandatory competition requirements")
    for claim_id, title in MANDATORY:
        row = next((ln for ln in ledger.splitlines()
                    if ln.startswith(f"| {claim_id} |")), None)
        if row is None:
            check(claim_id, False, f"{title}: not present in the claim ledger")
            continue
        status = "VERIFIED" if "VERIFIED" in row else (
            "PARTIAL" if "PARTIAL" in row else "NOT YET ESTABLISHED")
        check(claim_id, status == "VERIFIED", f"{title}: {status}")

    # ------------------------------------------------------------- claim discipline --
    print("\nClaim discipline")
    unestablished = [ln.split("|")[1].strip() for ln in ledger.splitlines()
                     if ln.startswith("| P") and "NOT YET ESTABLISHED" in ln]
    readme = read("README.md") or ""
    # A NOT YET ESTABLISHED claim must not be asserted as fact in the README.
    leaked = [c for c in unestablished
              if re.search(rf"\b{re.escape(c)}\b", readme)]
    check("ledger-vs-readme", not leaked,
          f"{len(unestablished)} claim(s) NOT YET ESTABLISHED; none asserted in README"
          if not leaked else f"asserted in README: {leaked}", mandatory=False)
    check("withdrawn-visible", "## Withdrawn" in ledger,
          "withdrawn claims are kept visible rather than deleted", mandatory=False)

    # ----------------------------------------------------------------- judge surfaces --
    print("\nJudge surfaces")
    for path, label in (("README.md", "root README"),
                        ("docs/submission/EVIDENCE-INDEX.md", "evidence index"),
                        ("docs/submission/DEMO-RUNBOOK.md", "demo runbook"),
                        ("docs/submission/FINALIST-QA.md", "finalist Q&A")):
        check(label, read(path) is not None, path, mandatory=False)
    check("limitations-stated", "What is not established" in readme,
          "README states what is not established", mandatory=False)

    # -------------------------------------------------------------- evidence exists --
    print("\nEvidence artifacts")
    trace = read("evidence/P04/hero-demo-trace.json")
    if trace is None:
        check("hero-demo-trace", False, "no hero demo trace", mandatory=False)
    else:
        t = json.loads(trace)
        check("hero-demo-trace", len(t.get("steps", [])) >= 12,
              f"{len(t.get('steps', []))} steps, grade {t.get('evidenceGrade')}",
              mandatory=False)
        check("fork-labelled", t.get("evidenceGrade") == "REAL LOCAL FORK"
              and "NOT a public-chain execution" in t.get("_scope", ""),
              "the trace labels itself fork evidence, not public", mandatory=False)

    acceptance = read("evidence/P03/acceptance.json")
    if acceptance:
        a = json.loads(acceptance)
        check("p03-not-overclaimed", a.get("accepted") is False
              and a.get("phase_complete") is False,
              "P03 records accepted=false and phase_complete=false", mandatory=False)

    # ------------------------------------------------------- no fake public evidence --
    print("\nNo fabricated public evidence")
    # A PUBLIC CHAIN grade anywhere in the ledger while M1 is unestablished would be a lie.
    m1_row = next((ln for ln in ledger.splitlines() if ln.startswith("| M1 |")), "")
    m1_done = "VERIFIED" in m1_row
    public_rows = [ln for ln in ledger.splitlines()
                   if "PUBLIC CHAIN" in ln and ln.startswith("| P")]
    check("no-public-grade-without-m1", m1_done or not public_rows,
          "no claim carries PUBLIC CHAIN while M1 is unestablished"
          if not public_rows else f"{len(public_rows)} claim(s) claim PUBLIC CHAIN")

    # ------------------------------------------------------------------ release state --
    print("\nRelease candidate")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    check("clean-tree", not dirty,
          f"HEAD {sha[:12]} with a clean tree" if not dirty
          else f"{len(dirty.splitlines())} uncommitted change(s)", mandatory=False)

    # ---------------------------------------------------------------------- verdict --
    print("\n" + "=" * 74)
    if blocked:
        print(f"VERDICT: BLOCKED — {len(blocked)} mandatory requirement(s) missing")
        for b in blocked:
            print(f"  - {b}")
        print("\nA mandatory requirement is not waived by strong engineering.")
        if warned:
            print(f"\n({len(warned)} non-blocking warning(s).)")
        return 1
    print("VERDICT: READY FOR SUBMISSION AUTHORIZATION")
    print("\nReadiness is not authorization. Publication, repository visibility and any")
    print("DoraHacks submission each need separate explicit approval.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
