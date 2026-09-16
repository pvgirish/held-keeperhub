"""Delivering Held's execution result to the ACTUAL pinned Almanak consumer.

P03 required work 4: "Integrate the durable journal with actual native result/dedupe
acknowledgement." Until now Held had a local harness that wrote a row into its own SQLite
metadata table and returned "CONSUMED". That was honest about being a model, and it did
exercise the commit boundary -- but it established nothing about the native side.

This module connects the real one.

## The native surface, at the pin

`almanak.framework.intents.state_machine.IntentStateMachine` is the component that owns a
native intent's lifecycle:

    step()                      -> PREPARING_<ACTION>, compiles, then
                                   VALIDATING_<ACTION> with needs_execution=True and the
                                   ActionBundle to execute
    set_receipt(TransactionReceipt)
    step()                      -> COMPLETED (success) or SADFLOW_<ACTION> (failure)

`_handle_validating` is explicit: with no receipt it returns `needs_execution=True`
again -- it will keep asking to execute. With a successful receipt it transitions to
COMPLETED. So "the native consumer acknowledged the result" has a concrete, checkable
meaning: **the state machine reached COMPLETED and stopped asking for execution.**

## Why the acknowledgement has to share Held's transaction

V4 §4 names the crash window: callback received -> consumer state updated -> CRASH -> ack
never written -> redelivery -> consumer state updated AGAIN. The state machine is an
in-memory object whose durable form is `to_dict()`. So the only way to close that window
is to write the advanced native state and the acknowledgement in the SAME commit, which
is what `NativeStateMachineConsumer.apply()` does: it advances the machine, serialises it,
and stores it on the journal connection the ack is written on.

If it could not do that -- if the native state lived somewhere this process cannot commit
atomically with -- then exactly-once would NOT be available at that boundary, and
`held_core.results` raises `ExactlyOnceUnavailable` rather than quietly downgrading. That
is the honest failure mode, and it is not the one we are in.

## The pinned machine can serialise but NOT restore

`IntentStateMachine.to_dict()` exists; there is no `from_dict`, no state setter, and no
documented reconstruction path at the pin. That is a real property of the native boundary,
not an oversight here, and it has two consequences this module has to handle rather than
paper over:

1. **The durable snapshot is authoritative, not the live object.** After a restart the
   machine cannot be rebuilt into its recorded state, so `restore()` does not pretend to:
   for a COMPLETED decision it returns a completed marker that refuses to be used for
   execution. Handing back a freshly-built machine would have it report
   `needs_execution=True` for work that is already done.

2. **An in-memory advance is not transactional.** `set_receipt()`/`step()` mutate the
   machine before anything is committed, and SQL rollback cannot undo that. So the
   consumer marks itself NOT authoritative until its snapshot is confirmed present, and
   `verify_committed()` is the check. A mutated-but-uncommitted machine must never be
   treated as the truth.

## What this still does not do

It does not run a full native strategy loop, and the receipt is constructed from Held's
own verified on-chain reading rather than handed over by a gateway. Those are labelled
where they occur.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

NATIVE_STATE_KEY = "native_state_machine:{operation_id}"
NATIVE_ACK_KEY = "native_ack:{operation_id}"
# The producing native decision, bound to the operation at admission time.
NATIVE_DECISION_KEY = "native_decision:{operation_id}"

TERMINAL_NATIVE_STATES = frozenset({"COMPLETED"})


class NativeAcknowledgementError(Exception):
    """The native consumer did not accept the result."""


class NativeStateNotAuthoritative(Exception):
    """A live machine was used as truth without a confirmed durable snapshot."""


class NativeDecisionConflict(Exception):
    """An operation is already bound to a DIFFERENT native decision."""


class NativeRecoveryBlocked(Exception):
    """The durable record does not permit a fresh work decision."""


def bind_native_decision(journal, operation_id: str, intent_id: str, intent_type: str) -> None:
    """Bind WHICH native decision produced this operation. WRITE-ONCE.

    Reopening the identical binding is idempotent -- a restart must be able to re-assert
    what it already recorded. Changing the identity or the type is a conflict and raises.

    The previous version used INSERT OR REPLACE, so calling it twice silently replaced
    the original decision, even with a different intent type. A binding that can be
    overwritten identifies nothing: the whole point is that a restart can tell WHICH
    decision this operation came from rather than accept whichever one shows up.
    """
    key = NATIVE_DECISION_KEY.format(operation_id=operation_id)
    new = {"intent_id": intent_id, "intent_type": intent_type}
    with journal.transaction() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if row is not None:
            existing = json.loads(row["value"])
            if existing != new:
                raise NativeDecisionConflict(
                    f"operation {operation_id} is already bound to native decision "
                    f"{existing}; refusing to rebind to {new}")
            return  # identical reopen: idempotent
        conn.execute("INSERT INTO meta(key,value) VALUES(?,?)", (key, json.dumps(new)))


def bound_native_decision(journal, operation_id: str) -> dict[str, Any] | None:
    row = journal._db.execute(  # noqa: SLF001 - read-only accessor
        "SELECT value FROM meta WHERE key=?",
        (NATIVE_DECISION_KEY.format(operation_id=operation_id),)).fetchone()
    return json.loads(row["value"]) if row else None


@dataclass
class RestoredDecision:
    """What a restart can honestly say about a native decision it cannot rebuild."""

    operation_id: str
    intent_id: str | None
    state: str | None
    acked: bool
    machine: Any = None
    operation_state: str | None = None
    inconsistent: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.state in TERMINAL_NATIVE_STATES and self.acked and not self.inconsistent

    @property
    def result_recoverable(self) -> bool:
        """The economic outcome is settled but the native side has not acknowledged."""
        return self.operation_state == "CONFIRMED" and not self.complete

    def needs_execution(self) -> bool:
        """Whether this decision still needs economic work. Durable record decides.

        A completed decision NEVER asks again; and neither does one whose OPERATION is
        settled or unresolved. The pinned machine has no `from_dict`, so a fresh process
        that rebuilt one would get a machine in VALIDATING_* reporting True -- for work
        already done, or for work whose outcome nobody knows.
        """
        if self.inconsistent:
            raise NativeRecoveryBlocked(
                f"operation {self.operation_id} has an inconsistent durable record "
                f"({'; '.join(self.inconsistent)}). Resolve it before deciding whether "
                "work is needed.")
        if self.complete:
            return False
        if self.result_recoverable:
            raise NativeRecoveryBlocked(
                f"operation {self.operation_id} is CONFIRMED on chain but its native "
                "acknowledgement is missing. Recover and DELIVER the existing result; "
                "this is not a request for fresh economic work.")
        if self.operation_state in _NO_FRESH_WORK:
            raise NativeRecoveryBlocked(
                f"operation {self.operation_id} is {self.operation_state}: its outcome is "
                "not settled, so no fresh work decision may be derived. Reconcile against "
                "the chain first.")
        if self.machine is None:
            raise NativeStateNotAuthoritative(
                f"operation {self.operation_id} has no terminal native snapshot and no "
                "live machine; nothing can say whether execution is still needed.")
        return bool(getattr(self.machine.step(), "needs_execution", False))


# Durable operation states from which NO fresh economic-work decision may be derived.
# CONFIRMED: it executed; the job is to recover and deliver the result.
# UNKNOWN:   the outcome is unresolved; the job is to stay blocked.
_NO_FRESH_WORK = {"CONFIRMED", "UNKNOWN", "DISPATCHED"}


def restore(journal, operation_id: str, build_machine=None) -> RestoredDecision:
    """Recover what is known about the native decision behind an operation.

    Order matters and was wrong before: this consulted ONLY the native snapshot, so with
    the snapshot missing it happily built a fresh machine and let THAT decide whether
    execution was needed -- at precisely the gap between economic confirmation and native
    acknowledgement. A CONFIRMED operation with no native snapshot is the crash window,
    and the answer there is "recover and deliver the result", never "ask a new machine
    whether to work".

    So the DURABLE OPERATION STATE is consulted first, then the native snapshot, and only
    then may a machine be built.
    """
    decision = bound_native_decision(journal, operation_id) or {}
    snapshot = native_state_after(journal, operation_id)
    acked = native_ack_state(journal, operation_id) is not None
    state = (snapshot or {}).get("state")

    op = journal.get(operation_id)
    op_state = op.state.value if op is not None else None

    # An inconsistent durable record is reported, not smoothed over.
    inconsistent = []
    if state in TERMINAL_NATIVE_STATES and not acked:
        inconsistent.append("a terminal native snapshot exists with no acknowledgement")
    if state in TERMINAL_NATIVE_STATES and not decision:
        inconsistent.append("a terminal native snapshot exists with no bound decision")

    machine = None
    if state not in TERMINAL_NATIVE_STATES and build_machine is not None:
        # Only build when the durable operation state permits a fresh work decision.
        if op_state not in _NO_FRESH_WORK:
            machine = build_machine()

    return RestoredDecision(
        operation_id=operation_id, intent_id=decision.get("intent_id"),
        state=state, acked=acked, machine=machine,
        operation_state=op_state, inconsistent=inconsistent)


@dataclass
class NativeReceipt:
    """The fields the pinned `TransactionReceipt` carries.

    Kept as a plain record so the adapter does not need the SDK imported to describe a
    result; `to_native()` builds the real object at the boundary.
    """

    success: bool
    tx_hash: str
    block_number: int
    gas_used: int = 0
    error: str | None = None

    def to_native(self):
        from almanak.framework.intents.state_machine import TransactionReceipt

        return TransactionReceipt(
            success=self.success,
            tx_hash=self.tx_hash,
            block_number=self.block_number,
            gas_used=self.gas_used,
            error=self.error,
        )


class NativeStateMachineConsumer:
    """Advances the REAL `IntentStateMachine` and enrols that advance in Held's commit.

    Conforms to `held_core.results.TransactionalConsumer`: `apply` receives the live
    journal connection, must use it, must not open its own transaction, and must not
    perform network I/O. Nothing here does.
    """

    def __init__(self, machine, *, require_complete: bool = True) -> None:
        self.machine = machine
        self.require_complete = require_complete
        self.applied_state: str | None = None
        self.state_before_apply: str | None = None
        self.step_results: list[Any] = []
        # The live machine is NOT authoritative until its snapshot is confirmed durable.
        # apply() mutates it before the commit, and SQL rollback cannot undo that.
        self._authoritative = False

    @property
    def authoritative(self) -> bool:
        return self._authoritative

    def verify_committed(self, journal, operation_id: str) -> bool:
        """Confirm the durable snapshot matches this machine, AFTER the commit.

        Two things were wrong before.

        First, it compared only STATE LABELS, so a different already-completed machine
        verified fine. It now requires the recorded identity to match as well.

        Second, it read the journal's OWN connection. Called from inside the delivering
        transaction it could see its own uncommitted write and set `authoritative=True`;
        a later rollback removed the snapshot and left the flag set. It now reads through
        a SEPARATE connection, which by definition cannot see an uncommitted write, so
        "verified" means committed.
        """
        import sqlite3

        probe = sqlite3.connect(journal.path, timeout=30.0)
        probe.row_factory = sqlite3.Row
        try:
            def meta(key: str):
                r = probe.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
                return r["value"] if r else None

            raw = meta(NATIVE_STATE_KEY.format(operation_id=operation_id))
            ack = meta(NATIVE_ACK_KEY.format(operation_id=operation_id))
        finally:
            probe.close()

        saved = json.loads(raw) if raw else None
        ok = (
            bool(saved)
            and saved.get("state") == self.state
            and saved.get("held_bound_decision") == self._identity()
            and ack == self.state
        )
        self._authoritative = ok
        return ok

    def require_authoritative(self) -> None:
        if not self._authoritative:
            raise NativeStateNotAuthoritative(
                f"the native machine is at {self.state} but that advance is not confirmed "
                "durable. The pinned IntentStateMachine has no from_dict and no state "
                "setter, so it cannot be moved back -- this object must be discarded, not "
                "used as authoritative state.")

    # ------------------------------------------------------------------ helpers --
    @property
    def state(self) -> str:
        return str(getattr(self.machine.state, "name", self.machine.state))

    def needs_execution(self) -> bool:
        """True while the native machine is still asking to be executed."""
        result = self.machine.step()
        self.step_results.append(result)
        return bool(getattr(result, "needs_execution", False))

    # -------------------------------------------------------------------- apply --
    def _identity(self) -> dict[str, str]:
        intent = self.machine.intent
        return {"intent_id": str(intent.intent_id),
                "intent_type": str(getattr(intent.intent_type, "value", intent.intent_type))}

    def apply(self, conn, operation_id: str, result_hash: str, payload: str) -> str:
        """Hand the receipt to the native machine, in the ack's own transaction."""
        # IDENTITY FIRST, before the machine is touched. Previously any machine could
        # apply under any binding as long as it reached COMPLETED -- a machine for
        # decision B satisfied an operation bound to decision A, and verify_committed()
        # returned True because it compared only STATE LABELS. Both saying "COMPLETED" is
        # not proof that the correct decision was completed.
        key = NATIVE_DECISION_KEY.format(operation_id=operation_id)
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if row is None:
            raise NativeDecisionConflict(
                f"operation {operation_id} has no bound native decision. Bind the "
                "producing decision before delivering a result to it.")
        bound = json.loads(row["value"])
        mine = self._identity()
        if bound != mine:
            raise NativeDecisionConflict(
                f"operation {operation_id} is bound to native decision {bound}, but this "
                f"consumer carries {mine}. Refusing to advance the wrong decision.")

        receipt = NativeReceipt(**json.loads(payload)).to_native()

        before = self.state
        self.state_before_apply = before
        self._authoritative = False
        self.machine.set_receipt(receipt)
        result = self.machine.step()
        self.step_results.append(result)
        after = self.state

        if self.require_complete:
            if not getattr(result, "is_complete", False) or not getattr(result, "success", False):
                # Raising here rolls the whole transaction back, so a native consumer
                # that did NOT accept the result leaves no acknowledgement behind. The
                # alternative -- recording an ack the consumer never honoured -- is the
                # exact lie this boundary exists to prevent.
                raise NativeAcknowledgementError(
                    f"the native state machine did not complete: {before} -> {after}, "
                    f"error={getattr(result, 'error', None)!r}. No acknowledgement was "
                    "written.")
            if getattr(result, "needs_execution", False):
                raise NativeAcknowledgementError(
                    "the native state machine still asks to be executed after the "
                    "receipt; it has not consumed the result.")

        # The advanced native state is written on the SAME connection as the ack, so the
        # two cannot be torn apart by a crash.
        snapshot = dict(self.machine.to_dict())
        # Stamp the identity INTO the snapshot so a later reader can check whose state
        # this is, not merely what label it carries.
        snapshot.setdefault("intent_id", mine["intent_id"])
        snapshot["held_bound_decision"] = mine
        conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
            (NATIVE_STATE_KEY.format(operation_id=operation_id),
             json.dumps(snapshot, default=str)))
        conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
            (NATIVE_ACK_KEY.format(operation_id=operation_id), after))

        self.applied_state = after
        return after


def native_state_after(journal, operation_id: str) -> dict[str, Any] | None:
    """The native state recorded alongside the acknowledgement, if any."""
    row = journal._db.execute(  # noqa: SLF001 - read-only accessor
        "SELECT value FROM meta WHERE key=?",
        (NATIVE_STATE_KEY.format(operation_id=operation_id),)).fetchone()
    return json.loads(row["value"]) if row else None


def native_ack_state(journal, operation_id: str) -> str | None:
    row = journal._db.execute(  # noqa: SLF001 - read-only accessor
        "SELECT value FROM meta WHERE key=?",
        (NATIVE_ACK_KEY.format(operation_id=operation_id),)).fetchone()
    return row["value"] if row else None
