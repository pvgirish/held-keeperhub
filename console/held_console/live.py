"""The four operator views, assembled from REAL state — or honestly reporting that they are not.

V4 §8 names four views and P05 requires them to be answerable from the running service, not
from a fixture. This module is the bridge: it reads the controller, the handover record, the
bounded authority inventory and the journal, and turns them into the four views the console
renders.

## The rule that matters

**If a source cannot be loaded, the view says so.** It never falls back to fixture data.
A console that quietly shows demo numbers when the chain is unreachable is worse than one
that shows nothing, because an operator would act on them. Every view therefore carries:

    loaded    could this view be built at all?
    grade     the evidence class behind it, never promoted
    problems  what could not be read, stated

A view with `loaded=False` renders as a stated failure. A view built from a fork carries
`REAL LOCAL FORK` and says so on screen, so nobody mistakes a demo for public evidence.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from .state import Budget, LiveState


@dataclass
class View:
    """One operator view, with its provenance attached rather than implied."""

    name: str
    loaded: bool
    grade: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "loaded": self.loaded, "grade": self.grade,
                "rows": self.rows, "summary": self.summary, "problems": self.problems}


def _unavailable(name: str, why: str) -> View:
    return View(name=name, loaded=False, grade="UNAVAILABLE",
                summary=f"This view could not be built: {why}",
                problems=[why])


def terms_view(reading, policy=None) -> View:
    """Terms — what the customer approved, what is used, what is left."""
    if reading is None or not getattr(reading, "usable", False):
        return _unavailable("Terms", getattr(reading, "reason", "no controller reading"))
    grade = "PUBLIC CHAIN" if reading.finalized else "REAL LOCAL FORK"
    rows = [
        {"field": "status", "value": reading.status.value},
        {"field": "epoch", "value": reading.epoch},
        {"field": "runner", "value": reading.runner},
        {"field": "executor", "value": reading.executor},
        {"field": "policy version", "value": reading.policy_version},
    ]
    if policy is not None:
        for label, ceiling, used_key in (
            ("supply", policy.Ls, "usedSupply"),
            ("normal withdraw", policy.Ln, "usedNormalWithdraw"),
            ("restoration", policy.Lr, "usedRestoration"),
        ):
            used = reading.used.get(used_key, 0)
            rows.append({"field": f"{label} ceiling", "value": ceiling,
                         "used": used, "remaining": max(ceiling - used, 0)})
        rows.append({"field": "normal count", "value": policy.Nn,
                     "used": reading.used.get("normalCount", 0),
                     "remaining": max(policy.Nn - reading.used.get("normalCount", 0), 0)})
    return View(name="Terms", loaded=True, grade=grade, rows=rows,
                summary=f"{reading.status.value} at epoch {reading.epoch}, "
                        f"block {reading.block_number}")


def activity_view(operations: list[dict[str, Any]] | None) -> View:
    """Activity — what was decided, submitted, executed, and with what evidence."""
    if operations is None:
        return _unavailable("Activity", "the journal could not be read")
    rows = []
    for op in operations:
        rows.append({
            "operation": op.get("operation_id", "")[:18] + "...",
            "state": op.get("state"),
            "nativeDecision": op.get("native_decision"),
            "keeperhubExecution": op.get("execution_id") or "NOT ESTABLISHED",
            "transaction": op.get("tx_hash") or "NOT ESTABLISHED",
            "grade": op.get("grade", "REAL LOCAL FORK"),
        })
    return View(name="Activity", loaded=True, grade="REAL LOCAL FORK", rows=rows,
                summary=f"{len(rows)} operation(s)" if rows
                        else "No operations recorded yet. This is an empty journal, "
                             "not a failed read.")


def unresolved_view(operations: list[dict[str, Any]] | None) -> View:
    """Unresolved — what is in the air, and what it blocks.

    The point of this view is that it never invents certainty. An UNKNOWN operation stays
    UNKNOWN until the chain says otherwise.
    """
    if operations is None:
        return _unavailable("Unresolved", "the journal could not be read")
    stuck = [o for o in operations
             if o.get("state") in ("UNKNOWN", "DISPATCHED")]
    rows = [{
        "operation": o.get("operation_id", "")[:18] + "...",
        "state": o.get("state"),
        "blocks": "a new action and any handover",
        "requiredEvidence": "consumed[operationId] read from the controller at a stated "
                            "block, with chain id, controller and finality",
    } for o in stuck]
    return View(
        name="Unresolved", loaded=True, grade="REAL LOCAL FORK", rows=rows,
        summary=(f"{len(stuck)} operation(s) unresolved — a handover is blocked"
                 if stuck else "Nothing is in the air."),
        problems=[] if not stuck else
        [f"{o['operation']} is {o['state']}; an unknown is not a verified negative"
         for o in rows])


def authority_view(inventory, handover_status: dict[str, Any] | None) -> View:
    """Authority & handover — who can move funds, and where a change has got to."""
    if inventory is None:
        return _unavailable("Authority & handover", "the bounded inventory is unavailable")
    rows = [{"field": "sections collected", "value": inventory.section_count},
            {"field": "complete", "value": inventory.complete},
            {"field": "external Morpho delegates",
             "value": inventory.external_delegates or "none"}]
    problems = [f"INCOMPLETE: {s}" for s in inventory.incomplete_sections]
    problems += [f"unsatisfied: {o}" for o in inventory.unsatisfied_obligations]

    if handover_status:
        rows += [
            {"field": "handover state", "value": handover_status.get("state")},
            {"field": "retiring runner", "value": handover_status.get("retiringRunner")},
            {"field": "awaiting owner", "value": handover_status.get("awaitingOwner")},
        ]
        cand = handover_status.get("candidate")
        if cand:
            rows.append({"field": "replacement runner", "value": cand.get("runner")})
            rows.append({"field": "consumption carried", "value": cand.get("expected")})
        problems += handover_status.get("blockers", [])
    else:
        rows.append({"field": "handover state", "value": "none in progress"})

    return View(name="Authority & handover", loaded=True, grade=inventory.evidence_grade,
                rows=rows, problems=problems,
                summary="; ".join(inventory.summary_lines()))


def build_views(*, reading=None, policy=None, operations=None, inventory=None,
                handover_status=None) -> dict[str, View]:
    """Assemble all four. Each is independently loadable, so one dead source does not
    blank the console -- it blanks exactly the view that depended on it."""
    return {
        "terms": terms_view(reading, policy),
        "activity": activity_view(operations),
        "unresolved": unresolved_view(operations),
        "authority": authority_view(inventory, handover_status),
    }


def live_state_from(reading, policy, *, safe: str) -> LiveState | None:
    """Adapt a controller reading into the console's existing LiveState."""
    if reading is None or not getattr(reading, "usable", False):
        return None
    budgets = [
        Budget("supply", policy.Ls, reading.used.get("usedSupply", 0)),
        Budget("normal withdraw", policy.Ln, reading.used.get("usedNormalWithdraw", 0)),
        Budget("restoration", policy.Lr, reading.used.get("usedRestoration", 0)),
    ]
    return LiveState(
        controller=reading.controller, safe=safe, active=bool(reading.active),
        epoch=reading.epoch or 0, policy_version=reading.policy_version or 0,
        runner=reading.runner or "", executor=reading.executor or "",
        budgets=budgets, native_remaining={}, cooldowns={})


def load_hero_trace(root: str) -> dict[str, Any] | None:
    """The hero demo's own trace, if one has been produced. Never fabricated."""
    path = os.path.join(root, "evidence", "P04", "hero-demo-trace.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
