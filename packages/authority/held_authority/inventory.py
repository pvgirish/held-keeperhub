"""The bounded authority inventory, as something the runtime can ASK rather than read.

P04 required work 1 and 2: a finalized common-block inventory of the supported Safe,
module, guard, fallback and Role paths, Morpho grant candidates with readback, and the
relevant token/Permit2 paths -- published with its discovery range, provenance and missing
evidence per section.

## Why this wraps the collector instead of reimplementing it

`script/collect_bootstrap_evidence.py` already does the chain reading, and it is the file
43 decision tests execute as a subprocess. Reimplementing its predicates here would create
a second definition of "what authority exists", and the two would drift -- which is exactly
the class of bug that produced a deployment helper installing something the checklist never
inspected. So this module RUNS that collector and interprets its report.

The collector stays the single source of truth for the predicates. This module adds what a
runtime needs and a script does not: a typed result, an explicit `complete` question, and
the distinction between "no external delegates" and "we could not tell".

## What it deliberately does not do

It does not claim universal authority discovery. The inventory is bounded by a declared
range and a declared supported profile, and anything outside that is reported as out of
scope rather than as absent. It never revokes anything: a Morpho grant to another agent may
be legitimate conflicting use, and silently revoking someone else's access to turn a
section green would be its own incident.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
COLLECTOR = os.path.join(ROOT, "script", "collect_bootstrap_evidence.py")
REPORT = os.path.join("evidence", "P03", "bootstrap-rehearsal.json")


class InventoryError(Exception):
    """The inventory could not be collected at all."""


@dataclass
class AuthorityInventory:
    """One bounded observation of who can move the customer's funds."""

    complete: bool
    sections: dict[str, Any]
    incomplete_sections: list[str]
    external_delegates: list[str]
    clauses: list[dict[str, Any]]
    observation: dict[str, Any]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)
    evidence_grade: str = "REAL LOCAL FORK"

    @property
    def section_count(self) -> int:
        return len(self.sections)

    @property
    def unsatisfied_obligations(self) -> list[str]:
        return [c["obligation"] for c in self.clauses if not c.get("satisfied")]

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "sectionCount": self.section_count,
            "incompleteSections": self.incomplete_sections,
            "externalDelegates": self.external_delegates,
            "unsatisfiedObligations": self.unsatisfied_obligations,
            "observation": self.observation,
            "evidenceGrade": self.evidence_grade,
            "_scope": "BOUNDED. This is the declared supported profile over a declared "
                      "range, not universal authority discovery. Anything outside the "
                      "profile is out of scope, which is not the same as absent.",
        }

    def summary_lines(self) -> list[str]:
        """What an owner needs to read before approving an activation."""
        out = [f"{self.section_count} section(s) collected at "
               f"block {self.observation.get('block_number')} on chain "
               f"{self.observation.get('chain_id')}"]
        if self.incomplete_sections:
            out.append(f"INCOMPLETE: {', '.join(self.incomplete_sections)}")
        else:
            out.append("every declared section is COMPLETE")
        if self.external_delegates:
            out.append(f"external Morpho delegates present: {', '.join(self.external_delegates)} "
                       "-- NOT revoked automatically; the owner decides")
        else:
            out.append("no external Morpho delegate holds authority over the Safe")
        return out


def collect(
    *,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    python: str | None = None,
    timeout: int = 300,
) -> AuthorityInventory:
    """Run the real collector and interpret its report.

    A non-zero exit is NOT an error here: the collector exits non-zero precisely when it
    blocks, and a blocking inventory is a legitimate, useful answer. Only a missing or
    unparseable report is an error, because then nothing is known at all.
    """
    workdir = cwd or ROOT
    run_env = {**os.environ, **(env or {})}
    os.makedirs(os.path.join(workdir, "evidence", "P03"), exist_ok=True)

    proc = subprocess.run(
        [python or sys.executable, COLLECTOR],
        env=run_env, cwd=workdir, capture_output=True, text=True, timeout=timeout)

    path = os.path.join(workdir, REPORT)
    if not os.path.exists(path):
        raise InventoryError(
            f"the collector produced no report at {path}. exit={proc.returncode}. "
            f"stderr: {proc.stderr.strip()[:400]}")
    try:
        with open(path) as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryError(f"the collector's report could not be read: {exc}") from None

    return from_report(raw)


def from_report(raw: dict[str, Any]) -> AuthorityInventory:
    """Interpret an already-collected report. Kept separate so it is testable offline."""
    verdict = raw.get("verdict") or {}
    sections = {k: v for k, v in raw.items()
                if isinstance(v, dict) and "verdict" in v and k != "verdict"}
    incomplete = list(verdict.get("incomplete_sections") or [])

    grants = raw.get("morpho_grants") or {}
    # "No external delegates" is only meaningful if the grant section could actually read.
    # A section that failed tells us nothing, and an unknown is not a verified negative.
    if grants.get("verdict") == "COMPLETE":
        external = list(grants.get("external_delegates") or [])
    else:
        external = []
        if "morpho_grants" not in incomplete:
            incomplete.append("morpho_grants")

    observation = raw.get("observation") or {}
    finalized = bool(observation.get("finality") and "NONE" not in str(observation.get("finality")))
    return AuthorityInventory(
        complete=not incomplete,
        sections=sections,
        incomplete_sections=incomplete,
        external_delegates=external,
        clauses=list(raw.get("clause_to_evidence") or []),
        observation=observation,
        raw=raw,
        evidence_grade="PUBLIC CHAIN" if finalized else "REAL LOCAL FORK",
    )
