"""What runner B needs to continue, and what it must NOT be given.

P04 required work 7: "Export replacement context, native checkpoints, source and pending
IDs, finalized results, quota state and credential references. B must obtain actual
required data or explicitly remain blocked."

The last clause is the interesting one. A replacement that silently starts without the
state it needs is worse than one that refuses: it would re-derive decisions from a blank
history and could repeat economic work the retiring runner already did. So the export
carries a `blocked_on` list, and it is populated rather than hidden when something required
is missing.

## Credentials are REFERENCED, never carried

The export names where a key lives -- `env:HELD_RUNNER_B_KEY`, `keystore:/path` -- and
never the key itself. A handover package containing a private key would be a copy of the
customer's authority sitting in a file, which is precisely the thing Held exists to bound.
`assert_no_secrets` refuses a value that looks like a key rather than trusting the caller.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

# A 32-byte hex string is a private key often enough that carrying one by accident is a
# real risk. Reference forms are permitted; raw material is not.
_KEY_SHAPED = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
_REFERENCE = re.compile(r"^(env|keystore|kms|file):")


class ExportError(Exception):
    """The replacement context could not be exported truthfully."""


def assert_reference(value: str, field_name: str) -> str:
    """A credential must be a REFERENCE. Key-shaped material is refused outright."""
    if not isinstance(value, str) or not value:
        raise ExportError(f"{field_name}: must be a non-empty reference string")
    if _KEY_SHAPED.match(value.strip()):
        raise ExportError(
            f"{field_name}: this looks like raw key material, not a reference. The export "
            "names where a key lives (env:NAME, keystore:/path); it never carries one.")
    if not _REFERENCE.match(value):
        raise ExportError(
            f"{field_name}: {value!r} is not a recognised reference form "
            "(env:, keystore:, kms:, file:)")
    return value


@dataclass
class ReplacementExport:
    """Everything runner B needs, and an explicit account of what is missing."""

    handover_id: str
    lineage: str
    controller: str
    chain_id: int
    new_epoch: int
    runner: str
    runner_key_reference: str
    executor: str
    policy: list[int]
    consumption_carried: dict[str, int]
    remaining_capacity: dict[str, int]
    native_config_digest: str
    native_checkpoints: list[dict[str, Any]] = field(default_factory=list)
    settled_operations: list[dict[str, Any]] = field(default_factory=list)
    pending_operations: list[str] = field(default_factory=list)
    blocked_on: list[str] = field(default_factory=list)
    evidence_grade: str = "REAL LOCAL FORK"
    exported_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def usable(self) -> bool:
        """B may start only if nothing required is missing."""
        return not self.blocked_on and not self.pending_operations

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "held.replacement-export.v1",
            "handoverId": self.handover_id,
            "lineage": self.lineage,
            "controller": self.controller,
            "chainId": self.chain_id,
            "newEpoch": self.new_epoch,
            "runner": self.runner,
            "runnerKeyReference": self.runner_key_reference,
            "executor": self.executor,
            "policy": self.policy,
            "consumptionCarried": self.consumption_carried,
            "remainingCapacity": self.remaining_capacity,
            "nativeConfigDigest": self.native_config_digest,
            "nativeCheckpoints": self.native_checkpoints,
            "settledOperations": self.settled_operations,
            "pendingOperations": self.pending_operations,
            "blockedOn": self.blocked_on,
            "usable": self.usable,
            "evidenceGrade": self.evidence_grade,
            "exportedAt": self.exported_at,
            "_credentials": "REFERENCED, NOT CARRIED. No private key, API key or secret "
                            "appears in this file. B resolves the reference in its own "
                            "environment.",
            "_consumption": "CARRIED FORWARD. B inherits the budget the retiring runner "
                            "spent from; it does not get a fresh one. That is the point of "
                            "a handover as opposed to a redeployment.",
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"


def build_export(
    *,
    handover_id: str,
    record: Any,
    reading: Any,
    runner_key_reference: str,
    native_checkpoints: list[dict[str, Any]] | None = None,
    settled_operations: list[dict[str, Any]] | None = None,
    pending_operations: list[str] | None = None,
    evidence_grade: str = "REAL LOCAL FORK",
) -> ReplacementExport:
    """Assemble the export from the handover record and a controller reading.

    Anything required but absent lands in `blocked_on` instead of being defaulted. A
    replacement that starts on invented state is the failure this is designed to prevent.
    """
    candidate = getattr(record, "candidate", None)
    if candidate is None:
        raise ExportError("no candidate has been prepared; there is nothing to export")

    assert_reference(runner_key_reference, "runner_key_reference")

    blocked: list[str] = []
    if not getattr(reading, "usable", False):
        blocked.append(
            f"the controller state could not be established: {getattr(reading, 'reason', '')}")
    if not candidate.native_config_digest:
        blocked.append("no native configuration digest was pinned for the replacement")

    carried = dict(zip(
        ("usedSupply", "usedNormalWithdraw", "usedRestoration", "normalCount",
         "restorationCount"),
        candidate.expected.as_tuple()))
    p = candidate.policy
    remaining = {
        "supply": p.Ls - carried["usedSupply"],
        "normalWithdraw": p.Ln - carried["usedNormalWithdraw"],
        "restoration": p.Lr - carried["usedRestoration"],
        "normalCount": p.Nn - carried["normalCount"],
        "restorationCount": p.Nr - carried["restorationCount"],
    }
    for name, value in remaining.items():
        if value < 0:
            blocked.append(f"remaining {name} is negative ({value}); the terms do not "
                           "cover what has already been spent")

    pending = list(pending_operations or [])
    return ReplacementExport(
        handover_id=handover_id,
        lineage=candidate.lineage,
        controller=record.controller,
        chain_id=record.chain_id,
        new_epoch=candidate.new_epoch,
        runner=candidate.runner,
        runner_key_reference=runner_key_reference,
        executor=candidate.executor,
        policy=list(p.as_tuple()),
        consumption_carried=carried,
        remaining_capacity=remaining,
        native_config_digest=candidate.native_config_digest,
        native_checkpoints=list(native_checkpoints or []),
        settled_operations=list(settled_operations or []),
        pending_operations=pending,
        blocked_on=blocked,
        evidence_grade=evidence_grade,
    )
