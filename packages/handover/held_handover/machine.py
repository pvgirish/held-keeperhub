"""The owner-controlled handover, as a durable machine that survives a restart.

The hero workflow of Locked V4:

    runner A active -> capacity consumed -> an operation becomes ambiguous ->
    owner fences -> reconciliation -> supported authority cleanup ->
    prepare runner B -> owner activates -> remaining Held budget preserved ->
    A cannot reuse its old authorization -> B continues

Every arrow is a place where a partial failure could either strand the customer's funds or
double-spend their budget, which is why this is a durable state machine and not a function.

## What the machine is for

Three rules, and everything else follows from them.

1. **The owner acts, Held prepares.** Held holds no owner key. Each transition that
   requires authority produces an `OwnerTransaction` and then WAITS for readback to show
   the owner executed it. `held_handover.owner_tx` builds those; nothing here signs.

2. **An unresolved operation blocks activation.** If the retiring epoch left an operation
   whose outcome nobody knows, activating a replacement would either lose consumption that
   really happened or charge the customer twice for work that did not. `RECONCILE` refuses
   to advance while any operation is unresolved, and says which ones.

3. **Stale state fails loudly.** The candidate carries the exact consumption the owner saw.
   If anything moved in between, activation reverts on chain -- and this machine refuses to
   even offer the transaction, so the owner is not asked to approve a fiction.

## Restartability

Every transition is committed before it is reported, in the SAME SQLite file as the
journal, so a crash between "the owner executed the fence" and "Held noticed" cannot lose
the handover. `HandoverMachine.load()` resumes from the durable record; the in-memory
object is never the authority.

The states are deliberately coarse. A finer machine would have more places to be wrong
about, and each state here corresponds to a real-world fact an owner could check.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .owner_tx import ExpectedState, OwnerTransaction, Policy, build_activate, build_fence
from .readback import ControllerReading, ControllerStatus

HANDOVER_KEY = "handover:{handover_id}"


class HandoverState(str, Enum):
    """Coarse on purpose: each one is a fact an owner could independently verify."""

    PROPOSED = "PROPOSED"                    # a replacement is wanted; nothing has happened
    FENCE_PREPARED = "FENCE_PREPARED"        # owner transaction built, not executed
    FENCED = "FENCED"                        # readback: active == false on chain
    RECONCILED = "RECONCILED"                # every operation of the old epoch is settled
    CANDIDATE_PREPARED = "CANDIDATE_PREPARED"  # runner B, terms and counter snapshot pinned
    CLEARED = "CLEARED"                      # bounded authority inventory is COMPLETE
    ACTIVATION_PREPARED = "ACTIVATION_PREPARED"  # owner transaction built, not executed
    ACTIVE = "ACTIVE"                        # readback: new epoch live with runner B
    BLOCKED = "BLOCKED"                      # a stated reason, requiring an owner decision


# The only legal moves. A transition not listed here cannot be taken, which is what keeps a
# caller from skipping reconciliation to get to an activation faster.
_ALLOWED: dict[HandoverState, frozenset[HandoverState]] = {
    HandoverState.PROPOSED: frozenset({HandoverState.FENCE_PREPARED, HandoverState.BLOCKED}),
    HandoverState.FENCE_PREPARED: frozenset({HandoverState.FENCED, HandoverState.BLOCKED}),
    HandoverState.FENCED: frozenset({HandoverState.RECONCILED, HandoverState.BLOCKED}),
    HandoverState.RECONCILED: frozenset({HandoverState.CANDIDATE_PREPARED, HandoverState.BLOCKED}),
    HandoverState.CANDIDATE_PREPARED: frozenset({HandoverState.CLEARED, HandoverState.BLOCKED}),
    HandoverState.CLEARED: frozenset({HandoverState.ACTIVATION_PREPARED, HandoverState.BLOCKED}),
    HandoverState.ACTIVATION_PREPARED: frozenset({HandoverState.ACTIVE, HandoverState.BLOCKED}),
    HandoverState.ACTIVE: frozenset(),
    # BLOCKED is not terminal: the owner resolves the cause and the machine retries from
    # the state it was blocked in, which is recorded alongside the reason.
    HandoverState.BLOCKED: frozenset(_s for _s in HandoverState if _s is not HandoverState.ACTIVE),
}


class HandoverError(Exception):
    """A handover step could not be taken truthfully."""


class HandoverBlocked(HandoverError):
    """A guard refused. The reason is the point; it is carried on the exception."""

    def __init__(self, message: str, *, blockers: list[str] | None = None) -> None:
        super().__init__(message)
        self.blockers = blockers or []


@dataclass
class Candidate:
    """The replacement, pinned before anyone is asked to approve it."""

    runner: str
    executor: str
    new_epoch: int
    new_policy_version: int
    policy: Policy
    expected: ExpectedState
    native_config_digest: str
    lineage: str
    prepared_at: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner": self.runner, "executor": self.executor, "newEpoch": self.new_epoch,
            "newPolicyVersion": self.new_policy_version,
            "policy": list(self.policy.as_tuple()),
            "expected": list(self.expected.as_tuple()),
            "nativeConfigDigest": self.native_config_digest,
            "lineage": self.lineage, "preparedAt": self.prepared_at,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Candidate":
        return Candidate(
            runner=d["runner"], executor=d["executor"], new_epoch=d["newEpoch"],
            new_policy_version=d["newPolicyVersion"],
            policy=Policy(*d["policy"]), expected=ExpectedState(*d["expected"]),
            native_config_digest=d["nativeConfigDigest"], lineage=d["lineage"],
            prepared_at=d.get("preparedAt", 0))


@dataclass
class HandoverRecord:
    handover_id: str
    state: HandoverState
    controller: str
    chain_id: int
    retiring_runner: str
    retiring_epoch: int
    candidate: Candidate | None = None
    blocked_from: HandoverState | None = None
    blockers: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "handoverId": self.handover_id, "state": self.state.value,
            "controller": self.controller, "chainId": self.chain_id,
            "retiringRunner": self.retiring_runner, "retiringEpoch": self.retiring_epoch,
            "candidate": self.candidate.to_dict() if self.candidate else None,
            "blockedFrom": self.blocked_from.value if self.blocked_from else None,
            "blockers": self.blockers, "history": self.history,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "HandoverRecord":
        return HandoverRecord(
            handover_id=d["handoverId"], state=HandoverState(d["state"]),
            controller=d["controller"], chain_id=d["chainId"],
            retiring_runner=d["retiringRunner"], retiring_epoch=d["retiringEpoch"],
            candidate=Candidate.from_dict(d["candidate"]) if d.get("candidate") else None,
            blocked_from=HandoverState(d["blockedFrom"]) if d.get("blockedFrom") else None,
            blockers=d.get("blockers", []), history=d.get("history", []))


class HandoverMachine:
    """Durable, restartable, and unable to skip a step.

    The journal is passed in rather than opened here: the handover and the operations it
    reconciles must be able to commit together, and two connections to the same file cannot
    do that.
    """

    def __init__(self, journal, record: HandoverRecord) -> None:
        self.journal = journal
        self.record = record

    # ------------------------------------------------------------------ durability --
    @classmethod
    def start(cls, journal, *, handover_id: str, controller: str, chain_id: int,
              retiring_runner: str, retiring_epoch: int) -> "HandoverMachine":
        existing = cls.load(journal, handover_id)
        if existing is not None:
            return existing
        record = HandoverRecord(
            handover_id=handover_id, state=HandoverState.PROPOSED, controller=controller,
            chain_id=chain_id, retiring_runner=retiring_runner,
            retiring_epoch=retiring_epoch)
        machine = cls(journal, record)
        machine._persist("start", {"controller": controller, "epoch": retiring_epoch})
        return machine

    @classmethod
    def load(cls, journal, handover_id: str) -> "HandoverMachine | None":
        row = journal._db.execute(  # noqa: SLF001 - read-only accessor, as elsewhere
            "SELECT value FROM meta WHERE key=?",
            (HANDOVER_KEY.format(handover_id=handover_id),)).fetchone()
        if row is None:
            return None
        return cls(journal, HandoverRecord.from_dict(json.loads(row["value"])))

    def _persist(self, event: str, detail: dict[str, Any] | None = None) -> None:
        self.record.history.append(
            {"at": int(time.time()), "event": event, "state": self.record.state.value,
             **(detail or {})})
        key = HANDOVER_KEY.format(handover_id=self.record.handover_id)
        with self.journal.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                         (key, json.dumps(self.record.to_dict())))

    def _move(self, to: HandoverState, event: str, detail: dict[str, Any] | None = None) -> None:
        if to not in _ALLOWED[self.record.state]:
            raise HandoverError(
                f"{self.record.state.value} -> {to.value} is not a legal handover move. "
                "The order exists so a step cannot be skipped to reach activation sooner.")
        self.record.state = to
        if to is not HandoverState.BLOCKED:
            self.record.blocked_from = None
            self.record.blockers = []
        self._persist(event, detail)

    def block(self, reason: str, blockers: list[str] | None = None) -> None:
        """Record why the handover cannot proceed, keeping the state it stalled in."""
        if self.record.state is not HandoverState.BLOCKED:
            self.record.blocked_from = self.record.state
        self.record.blockers = blockers or [reason]
        self.record.state = HandoverState.BLOCKED
        self._persist("blocked", {"reason": reason, "blockers": self.record.blockers})

    # ----------------------------------------------------------------- transitions --
    def prepare_fence(self, *, current_epoch: int) -> OwnerTransaction:
        """Build the owner's fence transaction. Held does NOT execute it."""
        tx = build_fence(controller=self.record.controller, chain_id=self.record.chain_id,
                         current_epoch=current_epoch)
        self._move(HandoverState.FENCE_PREPARED, "fence prepared",
                   {"currentEpoch": current_epoch})
        return tx

    def confirm_fenced(self, reading: ControllerReading) -> None:
        """Accept the fence only on evidence that the CONTROLLER is paused.

        An adapter that stopped dispatching is not a fence, and this is the guard that
        refuses to call it one.
        """
        if not reading.usable:
            raise HandoverBlocked(
                f"the controller's state could not be established: {reading.reason}. An "
                "unknown is not a verified fence.", blockers=["OBSERVATION_INCOMPLETE"])
        if reading.status is ControllerStatus.ADAPTER_REFUSING:
            raise HandoverBlocked(
                "Held's adapter has stopped dispatching, but the controller is STILL "
                "ACTIVE on chain. That is not a fence: a correctly signed envelope from "
                "the retiring runner would still execute. The owner must call fence().",
                blockers=["ADAPTER_REFUSING_NOT_FENCED"])
        if reading.status is not ControllerStatus.OWNER_FENCED:
            raise HandoverBlocked(
                f"the controller reads {reading.status.value}, not OWNER_FENCED.",
                blockers=[reading.status.value])
        self._move(HandoverState.FENCED, "fence confirmed on chain",
                   {"epoch": reading.epoch, "blockNumber": reading.block_number})

    def reconcile(self, unresolved: list[str]) -> None:
        """Advance only when nothing from the retiring epoch is still in the air."""
        if unresolved:
            raise HandoverBlocked(
                f"{len(unresolved)} operation(s) from the retiring epoch are unresolved. "
                "Activating a replacement now would either lose consumption that really "
                "happened or charge the customer twice for work that did not. Reconcile "
                "each against the chain first.",
                blockers=[f"UNRESOLVED:{oid}" for oid in unresolved])
        self._move(HandoverState.RECONCILED, "all operations of the retiring epoch settled")

    def prepare_candidate(self, candidate: Candidate, *, observed: ControllerReading) -> None:
        """Pin the replacement against the consumption actually on chain right now."""
        if not observed.usable:
            raise HandoverBlocked(
                f"the candidate cannot be pinned to an unreadable controller: "
                f"{observed.reason}", blockers=["OBSERVATION_INCOMPLETE"])
        if observed.status is not ControllerStatus.OWNER_FENCED:
            raise HandoverBlocked(
                "the controller must stay PAUSED throughout preparation; it reads "
                f"{observed.status.value}", blockers=[observed.status.value])
        on_chain = ExpectedState(
            usedSupply=observed.used["usedSupply"],
            usedNormalWithdraw=observed.used["usedNormalWithdraw"],
            usedRestoration=observed.used["usedRestoration"],
            normalCount=observed.used["normalCount"],
            restorationCount=observed.used["restorationCount"])
        if candidate.expected.as_tuple() != on_chain.as_tuple():
            raise HandoverBlocked(
                f"the candidate was prepared against consumption "
                f"{candidate.expected.as_tuple()} but the controller reads "
                f"{on_chain.as_tuple()}. Preparing against stale state would ask the owner "
                "to approve remaining capacity that does not exist.",
                blockers=["STALE_CANDIDATE"])
        if candidate.new_epoch <= self.record.retiring_epoch:
            raise HandoverBlocked(
                f"epoch {candidate.new_epoch} does not advance past the retiring epoch "
                f"{self.record.retiring_epoch}", blockers=["STALE_EPOCH"])
        if candidate.runner.lower() == self.record.retiring_runner.lower():
            raise HandoverBlocked(
                "the candidate runner is the runner being retired; that is not a handover",
                blockers=["SAME_RUNNER"])
        self.record.candidate = candidate
        self._move(HandoverState.CANDIDATE_PREPARED, "candidate pinned",
                   {"runner": candidate.runner, "newEpoch": candidate.new_epoch})

    def clear_authority(self, inventory: Any) -> None:
        """Require a COMPLETE bounded inventory before offering an activation.

        `inventory` is a `held_authority.AuthorityInventory`. Incomplete sections block:
        V4 §6 says incomplete evidence blocks activation, and an inventory that cannot say
        what authority exists cannot say that cleanup is done.
        """
        incomplete = list(getattr(inventory, "incomplete_sections", []) or [])
        if incomplete:
            raise HandoverBlocked(
                f"the bounded authority inventory is INCOMPLETE in {len(incomplete)} "
                f"section(s): {', '.join(incomplete)}. Activation requires complete "
                "supported evidence, and an unreadable section is not an empty one.",
                blockers=[f"INCOMPLETE:{s}" for s in incomplete])
        external = list(getattr(inventory, "external_delegates", []) or [])
        if external:
            raise HandoverBlocked(
                f"external Morpho delegate(s) still hold authority over the Safe: "
                f"{', '.join(external)}. These are NOT revoked automatically -- they may "
                "be legitimate conflicting use by another agent, and revoking someone "
                "else's access to make a checklist green would be its own incident. The "
                "owner must decide.",
                blockers=[f"EXTERNAL_DELEGATE:{d}" for d in external])
        self._move(HandoverState.CLEARED, "bounded authority inventory complete",
                   {"sections": getattr(inventory, "section_count", None)})

    def prepare_activation(self) -> OwnerTransaction:
        """Build the single atomic activation, carrying the owner's expected state."""
        c = self.record.candidate
        if c is None:
            raise HandoverError("no candidate has been prepared")
        tx = build_activate(
            controller=self.record.controller, chain_id=self.record.chain_id,
            new_epoch=c.new_epoch, new_policy_version=c.new_policy_version,
            new_runner=c.runner, new_executor=c.executor, policy=c.policy,
            expected=c.expected, current_epoch=self.record.retiring_epoch,
            retiring_runner=self.record.retiring_runner)
        self._move(HandoverState.ACTIVATION_PREPARED, "activation prepared",
                   {"newEpoch": c.new_epoch, "runner": c.runner})
        return tx

    def confirm_active(self, reading: ControllerReading) -> None:
        """Accept the handover only when the chain shows the replacement live."""
        c = self.record.candidate
        if c is None:
            raise HandoverError("no candidate has been prepared")
        if not reading.usable:
            raise HandoverBlocked(
                f"activation could not be verified: {reading.reason}",
                blockers=["OBSERVATION_INCOMPLETE"])
        if reading.status is not ControllerStatus.CONTRACT_ACTIVE:
            raise HandoverBlocked(
                f"the controller reads {reading.status.value}, not CONTRACT_ACTIVE",
                blockers=[reading.status.value])
        if reading.epoch != c.new_epoch:
            raise HandoverBlocked(
                f"the controller is at epoch {reading.epoch}, not the activated "
                f"{c.new_epoch}", blockers=["EPOCH_MISMATCH"])
        if (reading.runner or "").lower() != c.runner.lower():
            raise HandoverBlocked(
                f"the controller's runner is {reading.runner}, not the activated "
                f"{c.runner}", blockers=["RUNNER_MISMATCH"])
        carried = ExpectedState(
            usedSupply=reading.used["usedSupply"],
            usedNormalWithdraw=reading.used["usedNormalWithdraw"],
            usedRestoration=reading.used["usedRestoration"],
            normalCount=reading.used["normalCount"],
            restorationCount=reading.used["restorationCount"])
        if carried.as_tuple() != c.expected.as_tuple():
            raise HandoverBlocked(
                f"consumption after activation is {carried.as_tuple()}, not the "
                f"{c.expected.as_tuple()} that was carried. Held's verified history must "
                "survive a handover unchanged.", blockers=["CONSUMPTION_NOT_PRESERVED"])
        self._move(HandoverState.ACTIVE, "replacement active on chain",
                   {"epoch": reading.epoch, "runner": reading.runner,
                    "preservedConsumption": list(carried.as_tuple())})

    # ------------------------------------------------------------------- reporting --
    def status(self) -> dict[str, Any]:
        r = self.record
        return {
            **r.to_dict(),
            "readyForActivation": r.state is HandoverState.CLEARED,
            "awaitingOwner": r.state in (HandoverState.FENCE_PREPARED,
                                         HandoverState.ACTIVATION_PREPARED),
            "_note": "PREPARED steps are waiting on an owner transaction that Held cannot "
                     "and will not send.",
        }
