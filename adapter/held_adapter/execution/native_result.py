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

## What this still does not do

It does not run a full native strategy loop, and the receipt is constructed from Held's
own verified on-chain reading rather than handed over by a gateway. Those are labelled
where they occur.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

NATIVE_STATE_KEY = "native_state_machine:{operation_id}"
NATIVE_ACK_KEY = "native_ack:{operation_id}"


class NativeAcknowledgementError(Exception):
    """The native consumer did not accept the result."""


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
        self.step_results: list[Any] = []

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
    def apply(self, conn, operation_id: str, result_hash: str, payload: str) -> str:
        """Hand the receipt to the native machine, in the ack's own transaction."""
        receipt = NativeReceipt(**json.loads(payload)).to_native()

        before = self.state
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
        conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
            (NATIVE_STATE_KEY.format(operation_id=operation_id),
             json.dumps(self.machine.to_dict(), default=str)))
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
