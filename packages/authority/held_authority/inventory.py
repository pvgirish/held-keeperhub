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
# The two modes ask different questions and must not overwrite each other's answer. This
# is the canonical mapping for the Python side; `collect()` passes the chosen path to the
# collector as HELD_INVENTORY_OUT so the collector never has to guess.
INITIAL_REPORT = os.path.join("evidence", "P03", "bootstrap-rehearsal.json")
HANDOVER_REPORT = os.path.join("evidence", "P03", "bootstrap-handover.json")
REPORTS_BY_MODE = {"initial": INITIAL_REPORT, "handover": HANDOVER_REPORT}

#: Back-compatible alias. Callers that mean the initial-activation rehearsal specifically
#: should prefer INITIAL_REPORT, which says so.
REPORT = INITIAL_REPORT


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
    # The SCOPE this inventory belongs to. Without these an inventory is just a shape:
    # a COMPLETE report about somebody else's controller would clear a handover.
    chain_id: int | None = None
    controller: str | None = None
    safe: str | None = None
    roles: str | None = None
    lineage: str | None = None
    block_number: int | None = None
    schema_ok: bool = False
    raw: dict[str, Any] = field(repr=False, default_factory=dict)
    evidence_grade: str = "REAL LOCAL FORK"

    @property
    def section_count(self) -> int:
        return len(self.sections)

    @property
    def unsatisfied_obligations(self) -> list[str]:
        return [c["obligation"] for c in self.clauses if not c.get("satisfied")]

    def scope(self) -> dict[str, Any]:
        return {"chainId": self.chain_id, "controller": self.controller,
                "safe": self.safe, "roles": self.roles, "lineage": self.lineage,
                "blockNumber": self.block_number}

    def scope_problems(self, *, chain_id: int, controller: str, safe: str,
                       lineage: str | None = None,
                       not_before_block: int | None = None) -> list[str]:
        """Every reason this inventory does NOT describe the named installation.

        Returned as a list rather than a bool so a refusal can say which field was wrong.
        A caller that cannot tell "another controller" from "stale" cannot act on either.
        """
        problems: list[str] = []
        if not self.schema_ok:
            problems.append("the report does not carry a recognisable declared installation")
        if self.chain_id != chain_id:
            problems.append(f"inventory is for chain {self.chain_id}, not {chain_id}")
        for name, got, want in (("controller", self.controller, controller),
                                ("safe", self.safe, safe)):
            if not (isinstance(got, str) and isinstance(want, str)
                    and got.lower() == want.lower()):
                problems.append(f"inventory is for {name} {got}, not {want}")
        if lineage is not None:
            if not (isinstance(self.lineage, str)
                    and self.lineage.lower() == lineage.lower()):
                problems.append(f"inventory is for lineage {self.lineage}, not {lineage}")
        if not_before_block is not None:
            if self.block_number is None:
                problems.append("the inventory states no observation block, so its "
                                "freshness cannot be judged")
            elif self.block_number < not_before_block:
                problems.append(
                    f"the inventory was observed at block {self.block_number}, before the "
                    f"fence at {not_before_block}; a pre-fence inventory cannot describe "
                    "the installation being handed over")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "scope": self.scope(),
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

    # Pin the output path to the mode being collected, and tell the collector explicitly
    # rather than letting both modes race for one filename. An unrecognised mode is the
    # collector's error to report, not ours to paper over with a default path.
    mode = run_env.get("HELD_INVENTORY_MODE", "initial")
    report_rel = REPORTS_BY_MODE.get(mode, INITIAL_REPORT)
    run_env["HELD_INVENTORY_OUT"] = report_rel

    path = os.path.join(workdir, report_rel)
    # A report left over from a previous run is NOT this run's evidence. Reading whatever
    # file happened to be on disk is how a stale inventory -- observed before the fence,
    # describing a state that has since changed -- got presented as a live collection.
    before = os.stat(path).st_mtime_ns if os.path.exists(path) else None

    proc = subprocess.run(
        [python or sys.executable, COLLECTOR],
        env=run_env, cwd=workdir, capture_output=True, text=True, timeout=timeout)

    if not os.path.exists(path):
        raise InventoryError(
            f"the collector produced no report at {path}. exit={proc.returncode}. "
            f"stderr: {proc.stderr.strip()[:400]}")
    after = os.stat(path).st_mtime_ns
    if before is not None and after == before:
        raise InventoryError(
            f"the collector did not write {path} on this run, so the file on disk is a "
            f"previous collection, not current evidence. exit={proc.returncode}. "
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

    declared_section = raw.get("declared_installation") or {}
    declared = declared_section.get("declared") or {}
    controller_section = raw.get("held_controller") or {}
    # A report with no declared installation cannot be bound to anything. It is not a
    # weaker inventory; it is an unusable one.
    schema_ok = bool(declared) and bool(observation)

    return AuthorityInventory(
        complete=not incomplete,
        sections=sections,
        incomplete_sections=incomplete,
        external_delegates=external,
        clauses=list(raw.get("clause_to_evidence") or []),
        observation=observation,
        chain_id=observation.get("chain_id"),
        controller=controller_section.get("address") or declared.get("controller"),
        safe=declared.get("safe"),
        roles=declared.get("roles"),
        lineage=declared.get("lineage"),
        block_number=observation.get("block_number"),
        schema_ok=schema_ok,
        raw=raw,
        evidence_grade="PUBLIC CHAIN" if finalized else "REAL LOCAL FORK",
    )
