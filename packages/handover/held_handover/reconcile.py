"""Reconciliation as an ARTIFACT the machine derives, not a list the caller asserts.

The defect this replaces: `reconcile(unresolved: list[str])` advanced to RECONCILED whenever
the supplied list was empty. A caller could simply say nothing was outstanding and the
handover believed it. The controller's `activate()` cannot help here -- it knows nothing
about off-chain submissions -- so this boundary is load-bearing and it was trusting its
caller.

## The rule

The complete set of retiring-epoch operations comes from the DURABLE JOURNAL, and the
machine re-derives it at the moment it accepts a report. A report that omits an operation
the journal knows about is rejected as incomplete rather than believed. That makes "I
forgot to include it" and "I chose not to include it" the same, refused thing.

## What a resolution is

Only two outcomes settle an operation, and both come from the chain:

  EXECUTED       `consumed[operationId]` is a non-zero marker at a stated block. The
                 operation moved funds and its consumption is already in the controller's
                 counters.
  NOT_EXECUTED   `consumed[operationId]` is zero at a stated block. Nothing was spent.

Anything else -- an unreadable chain, a read from the wrong controller or chain, an
unfinalized reading where finality was required -- is UNRESOLVED. An unknown is not a
verified negative, and an operation that cannot be resolved keeps the handover pending,
which is exactly what Locked V4 requires.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

SCHEMA = "held.reconciliation-report.v1"

# Journal states from which an operation still needs a chain verdict before a handover.
# CONFIRMED and FAILED are already settled: the journal reached them from evidence.
UNSETTLED_STATES = frozenset({"CREATED", "AUTHORIZED", "DISPATCHED", "UNKNOWN"})

ZERO_MARKER = "0x" + "0" * 64


class ReconciliationError(Exception):
    """A reconciliation report could not be built or trusted."""


class ConsumptionReader(Protocol):
    """The minimum chain access reconciliation needs."""

    def consumed(self, controller: str, operation_id: str) -> Any: ...


@dataclass
class OperationResolution:
    operation_id: str
    journal_state: str
    resolution: str                       # EXECUTED | NOT_EXECUTED | UNRESOLVED
    reason: str = ""
    marker: str | None = None
    block_number: int | None = None
    finalized: bool = False

    @property
    def settled(self) -> bool:
        return self.resolution in ("EXECUTED", "NOT_EXECUTED")

    def to_dict(self) -> dict[str, Any]:
        return {"operationId": self.operation_id, "journalState": self.journal_state,
                "resolution": self.resolution, "reason": self.reason,
                "marker": self.marker, "blockNumber": self.block_number,
                "finalized": self.finalized}


@dataclass
class ReconciliationReport:
    """Bound to one handover, one installation, one fence observation."""

    handover_id: str
    controller: str
    chain_id: int
    retiring_epoch: int
    fence_block: int | None
    fence_block_hash: str | None
    resolutions: list[OperationResolution]
    counters_after: dict[str, int]
    evidence_block: int | None
    finalized: bool
    schema: str = SCHEMA
    built_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def operation_ids(self) -> set[str]:
        return {r.operation_id.lower() for r in self.resolutions}

    @property
    def unresolved(self) -> list[str]:
        return [r.operation_id for r in self.resolutions if not r.settled]

    @property
    def executed(self) -> list[str]:
        return [r.operation_id for r in self.resolutions if r.resolution == "EXECUTED"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "handoverId": self.handover_id,
            "controller": self.controller, "chainId": self.chain_id,
            "retiringEpoch": self.retiring_epoch,
            "fenceBlock": self.fence_block, "fenceBlockHash": self.fence_block_hash,
            "resolutions": [r.to_dict() for r in self.resolutions],
            "unresolved": self.unresolved, "executed": self.executed,
            "countersAfter": self.counters_after,
            "evidenceBlock": self.evidence_block, "finalized": self.finalized,
            "builtAt": self.built_at,
            "_derivation": "The operation set is derived from the durable journal for the "
                           "retiring epoch. The machine re-derives it on acceptance, so a "
                           "report that omits a known operation is refused.",
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"


def operations_for_epoch(journal, epoch: int) -> dict[str, str]:
    """Every operation the durable journal holds for this epoch, id -> state.

    Reads the operations table directly. The journal is the authority on what Held
    attempted; asking a caller would be asking the thing under scrutiny.
    """
    rows = journal._db.execute(  # noqa: SLF001 - read-only accessor, as elsewhere
        "SELECT operation_id, state FROM operations WHERE epoch=?", (epoch,)).fetchall()
    return {r["operation_id"].lower(): r["state"] for r in rows}


def build_report(
    journal,
    *,
    record,
    fence_reading,
    reader: ConsumptionReader | None,
    require_finalized: bool = False,
) -> ReconciliationReport:
    """Derive the report from the journal plus chain evidence. Never from a caller's list."""
    known = operations_for_epoch(journal, record.retiring_epoch)

    resolutions: list[OperationResolution] = []
    for oid, state in sorted(known.items()):
        if state not in UNSETTLED_STATES:
            resolutions.append(OperationResolution(
                operation_id=oid, journal_state=state,
                resolution="EXECUTED" if state == "CONFIRMED" else "NOT_EXECUTED",
                reason=f"the journal already settled this operation as {state}"))
            continue

        if reader is None:
            resolutions.append(OperationResolution(
                operation_id=oid, journal_state=state, resolution="UNRESOLVED",
                reason="no chain reader was supplied, so the outcome cannot be established"))
            continue

        try:
            ev = reader.consumed(record.controller, oid)
        except Exception as exc:  # noqa: BLE001 - any failure is unresolved, not negative
            resolutions.append(OperationResolution(
                operation_id=oid, journal_state=state, resolution="UNRESOLVED",
                reason=f"the consumption read failed: {exc}"))
            continue

        marker = getattr(ev, "marker", None)
        chain_id = getattr(ev, "chain_id", None)
        controller = getattr(ev, "controller", None)
        finalized = bool(getattr(ev, "finalized", False))
        block = getattr(ev, "block_number", None)

        if chain_id != record.chain_id or not _same(controller, record.controller):
            resolutions.append(OperationResolution(
                operation_id=oid, journal_state=state, resolution="UNRESOLVED",
                reason=f"evidence is scoped to chain {chain_id} controller {controller}, "
                       f"not chain {record.chain_id} controller {record.controller}",
                block_number=block, finalized=finalized))
            continue
        if require_finalized and not finalized:
            resolutions.append(OperationResolution(
                operation_id=oid, journal_state=state, resolution="UNRESOLVED",
                reason="the reading is not finalized and this reconciliation requires "
                       "finality; an unfinalized reading can be reorganised away",
                marker=marker, block_number=block, finalized=finalized))
            continue
        if not isinstance(marker, str) or not marker.startswith("0x"):
            resolutions.append(OperationResolution(
                operation_id=oid, journal_state=state, resolution="UNRESOLVED",
                reason=f"the consumption marker is not usable: {marker!r}",
                block_number=block, finalized=finalized))
            continue

        executed = marker.lower() != ZERO_MARKER
        resolutions.append(OperationResolution(
            operation_id=oid, journal_state=state,
            resolution="EXECUTED" if executed else "NOT_EXECUTED",
            reason=("consumed[operationId] carries a payload marker at the stated block"
                    if executed else
                    "consumed[operationId] is zero at the stated block"),
            marker=marker, block_number=block, finalized=finalized))

    return ReconciliationReport(
        handover_id=record.handover_id,
        controller=record.controller,
        chain_id=record.chain_id,
        retiring_epoch=record.retiring_epoch,
        fence_block=getattr(fence_reading, "block_number", None),
        fence_block_hash=getattr(fence_reading, "block_hash", None),
        resolutions=resolutions,
        counters_after=dict(getattr(fence_reading, "used", {}) or {}),
        evidence_block=getattr(fence_reading, "block_number", None),
        finalized=bool(getattr(fence_reading, "finalized", False)),
    )


def _same(a: Any, b: Any) -> bool:
    return isinstance(a, str) and isinstance(b, str) and a.lower() == b.lower()
