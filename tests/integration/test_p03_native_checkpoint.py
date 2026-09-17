"""Does the native decision/recovery contract enforce what its docstring claims?

The review of 67eed71 found it did not, in three places, and proved it by executing the
committed adapter. This file runs those same cases against the LIVE adapter -- the one the
running process imports -- so the findings cannot silently come back.

METHOD. The adapter is imported normally from `held_adapter`. What is synthetic is the
JOURNAL and the MACHINE: a real SQLite database with real transactions, real commits and
real close/reopen, and a controlled `Machine` that models the pinned `IntentStateMachine`'s
step/receipt behaviour. No SDK, no fork, no RPC, no signer, no key.

That boundary is the point. These are DECISION tests about the adapter's own control flow.
The pinned machine's real behaviour is exercised by `make check-phase-03-composed`, which
drives the actual Almanak consumer; nothing here substitutes for it.

Three groups:

  PRESERVED  the nine controls 67eed71 established. The review confirms them and they must
             keep holding -- this is the regression half.
  CLOSED     the three findings the review left open (N1, N2). Each asserts the REFUSAL,
             not merely that the value changed.
  POSITIVE   a checklist that blocks everything proves as little as one that blocks
             nothing, so a clean machine must still be able to answer.
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import sys
import tempfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "adapter"))
sys.path.insert(0, os.path.join(ROOT, "packages", "core"))

from held_adapter.execution.native_result import (  # noqa: E402
    NATIVE_ACK_KEY,
    NATIVE_STATE_KEY,
    NativeDecisionConflict,
    NativeReceipt,
    NativeRecoveryBlocked,
    NativeStateMachineConsumer,
    NativeStateNotAuthoritative,
    bind_native_decision,
    bound_native_decision,
    native_state_after,
    restore,
)

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

OID = "0x" + "11" * 32
RESULT_HASH = "0x" + "99" * 32
PAYLOAD = json.dumps({"success": True, "tx_hash": "0x" + "44" * 32, "block_number": 123})

REFUSALS = (NativeRecoveryBlocked, NativeStateNotAuthoritative)


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


class JournalDouble:
    """Real SQLite with real transactions. Stands in for Journal ACCESS, not behaviour."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(
            "PRAGMA journal_mode=WAL;"
            "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS operations("
            "  operation_id TEXT PRIMARY KEY, state TEXT, payload_hash TEXT);")

    @contextlib.contextmanager
    def transaction(self):
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield self._db
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise

    def set_state(self, oid: str, state: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO operations VALUES(?,?,?)",
                         (oid, state, "0x" + "11" * 32))

    def get(self, oid: str):
        row = self._db.execute(
            "SELECT * FROM operations WHERE operation_id=?", (oid,)).fetchone()
        return SimpleNamespace(state=SimpleNamespace(value=row["state"])) if row else None

    def close(self) -> None:
        self._db.close()


class Machine:
    """Controlled model of the pinned machine's step/receipt behaviour. NOT Almanak."""

    def __init__(self, intent: str = "decision-A", state: str = "VALIDATING_SUPPLY") -> None:
        self.intent = SimpleNamespace(
            intent_id=intent, intent_type=SimpleNamespace(value="SUPPLY"))
        self.state = state
        self.receipt = None
        self.step_count = 0

    def set_receipt(self, receipt) -> None:
        self.receipt = receipt

    def step(self):
        self.step_count += 1
        if self.receipt is not None:
            self.state = "COMPLETED" if self.receipt.success else "SADFLOW_SUPPLY"
        done = self.state == "COMPLETED"
        return SimpleNamespace(
            needs_execution=not done, is_complete=done, success=done, error=None)

    def to_dict(self) -> dict:
        return {"intent_id": self.intent.intent_id, "intent_type": "SUPPLY",
                "state": self.state}


TMP = tempfile.TemporaryDirectory()
COUNTER = [0]


def fresh(name: str) -> JournalDouble:
    COUNTER[0] += 1
    return JournalDouble(os.path.join(TMP.name, f"{COUNTER[0]:02d}-{name}.sqlite"))


def reopen(journal: JournalDouble) -> JournalDouble:
    """Close and reopen the SAME file, so 'durable' means survived a process boundary."""
    path = journal.path
    journal.close()
    return JournalDouble(path)


def write_snapshot(journal, *, state="COMPLETED", intent="decision-A", ack=True,
                   stamp=True, ack_state=None) -> None:
    """Write a checkpoint DIRECTLY, to manufacture records apply() would never write.

    Deliberately bypasses apply(): these are recovery/import-consistency cases. A record
    that arrives by restore, migration or corruption still has to be judged.
    """
    snapshot = {"state": state, "intent_id": intent}
    if stamp:
        snapshot["held_bound_decision"] = {"intent_id": intent, "intent_type": "SUPPLY"}
    with journal.transaction() as conn:
        conn.execute("INSERT OR REPLACE INTO meta VALUES(?,?)",
                     (NATIVE_STATE_KEY.format(operation_id=OID), json.dumps(snapshot)))
        if ack:
            conn.execute("INSERT OR REPLACE INTO meta VALUES(?,?)",
                         (NATIVE_ACK_KEY.format(operation_id=OID), ack_state or state))


def refuses(fn, *, contains: str) -> str:
    """Require a refusal AND require it to say why. A bare raise is not an explanation."""
    try:
        value = fn()
    except REFUSALS as exc:
        message = str(exc)
        assert contains in message, (
            f"refused, but the reason does not mention {contains!r}: {message}")
        return message
    raise AssertionError(f"expected a refusal mentioning {contains!r}; got {value!r}")


def applied(journal, machine, *, oid: str = OID) -> NativeStateMachineConsumer:
    consumer = NativeStateMachineConsumer(machine)
    with journal.transaction() as conn:
        consumer.apply(conn, oid, RESULT_HASH, PAYLOAD)
    return consumer


# --------------------------------------------------------------------------------------
# PRESERVED: the nine controls 67eed71 established, which the review confirms.
# --------------------------------------------------------------------------------------

@test("PRESERVED: an identical binding reopens, a changed one conflicts")
def _():
    j = fresh("binding")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")   # idempotent reopen
    assert bound_native_decision(j, OID) == {
        "intent_id": "decision-A", "intent_type": "SUPPLY"}
    for intent, kind in (("decision-B", "SUPPLY"), ("decision-A", "WITHDRAW")):
        try:
            bind_native_decision(j, OID, intent, kind)
            raise AssertionError(f"rebinding to {intent}/{kind} was allowed")
        except NativeDecisionConflict:
            pass
    j.close()


@test("PRESERVED: a machine for a DIFFERENT decision is refused BEFORE it is mutated")
def _():
    j = fresh("wrong-machine")
    j.set_state(OID, "CONFIRMED")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")
    wrong = Machine("decision-B")
    consumer = NativeStateMachineConsumer(wrong)
    try:
        with j.transaction() as conn:
            consumer.apply(conn, OID, RESULT_HASH, PAYLOAD)
        raise AssertionError("a machine for decision B applied under a binding to A")
    except NativeDecisionConflict:
        pass
    assert wrong.step_count == 0, (
        f"the wrong machine was stepped {wrong.step_count} times before being refused; "
        "identity must be checked before the machine is touched")
    j.close()


@test("PRESERVED: a settled or unsettled operation with no snapshot never asks for work")
def _():
    for state, expected in (("CONFIRMED", "Recover and DELIVER"),
                            ("UNKNOWN", "not settled"),
                            ("DISPATCHED", "not settled")):
        j = fresh(f"no-snapshot-{state}")
        j.set_state(OID, state)
        bind_native_decision(j, OID, "decision-A", "SUPPLY")
        built = []
        decision = restore(j, OID, build_machine=lambda: built.append(1) or Machine())
        refuses(decision.needs_execution, contains=expected)
        assert not built, f"{state}: a replacement machine was built"
        j.close()


@test("PRESERVED: a matching committed checkpoint reopens as complete, building nothing")
def _():
    j = fresh("good")
    j.set_state(OID, "CONFIRMED")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")
    consumer = applied(j, Machine())
    assert consumer.verify_committed(j, OID) is True

    j = reopen(j)
    built = []
    decision = restore(j, OID, build_machine=lambda: built.append(1) or Machine())
    assert decision.complete is True, decision.inconsistent
    assert decision.inconsistent == [], decision.inconsistent
    assert decision.needs_execution() is False, "finished work asked to be done again"
    assert not built, "a replacement machine was built for a completed decision"
    j.close()


@test("PRESERVED: the separate verification connection cannot see an uncommitted snapshot")
def _():
    j = fresh("rollback")
    j.set_state(OID, "CONFIRMED")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")
    consumer = NativeStateMachineConsumer(Machine())
    seen = None
    try:
        with j.transaction() as conn:
            consumer.apply(conn, OID, RESULT_HASH, PAYLOAD)
            seen = consumer.verify_committed(j, OID)
            raise RuntimeError("fail after mutation, before commit")
    except RuntimeError:
        pass
    assert seen is False, "an uncommitted snapshot verified as committed"
    assert native_state_after(j, OID) is None, "the snapshot survived a rollback"
    j.close()


@test("PRESERVED: a terminal snapshot with no acknowledgement blocks")
def _():
    j = fresh("terminal-unacked")
    j.set_state(OID, "CONFIRMED")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")
    write_snapshot(j, ack=False)
    decision = restore(j, OID)
    assert decision.complete is False
    refuses(decision.needs_execution, contains="no acknowledgement")
    j.close()


# --------------------------------------------------------------------------------------
# CLOSED: N1 and N2, the findings the review of 67eed71 left open.
# --------------------------------------------------------------------------------------

@test("N1: a machine mutated by a rolled-back apply refuses to answer needs_execution")
def _():
    j = fresh("n1-dirty")
    j.set_state(OID, "CONFIRMED")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")
    consumer = NativeStateMachineConsumer(Machine())
    try:
        with j.transaction() as conn:
            consumer.apply(conn, OID, RESULT_HASH, PAYLOAD)
            raise RuntimeError("fail after mutation, before commit")
    except RuntimeError:
        pass

    # The rollback removed the snapshot; the in-memory machine is nevertheless COMPLETED.
    assert native_state_after(j, OID) is None
    assert consumer.state == "COMPLETED"
    assert consumer.authoritative is False
    assert consumer.dirty is True

    refuses(consumer.needs_execution, contains="NOT confirmed durable")
    refuses(consumer.require_clean, contains="restore()")
    j.close()


@test("N1: a clean machine is still usable, before and after a committed apply")
def _():
    # Before: never applied to, so it answers from its own pre-dispatch lifecycle.
    consumer = NativeStateMachineConsumer(Machine(state="VALIDATING_SUPPLY"))
    assert consumer.dirty is False
    assert consumer.needs_execution() is True, (
        "a clean pre-dispatch machine must still be able to offer work")

    # After a COMMITTED apply, confirming durability clears the dirty state.
    j = fresh("n1-clean")
    j.set_state(OID, "CONFIRMED")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")
    committed = applied(j, Machine())
    assert committed.dirty is True, "durability was assumed before it was verified"
    assert committed.verify_committed(j, OID) is True
    assert committed.dirty is False
    assert committed.needs_execution() is False
    j.close()


@test("N2: a snapshot for decision B under a binding to A is reported and blocks")
def _():
    j = fresh("n2-wrong-checkpoint")
    j.set_state(OID, "CONFIRMED")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")
    write_snapshot(j, intent="decision-B")          # manufactured inconsistent checkpoint

    decision = restore(j, OID)
    assert decision.intent_id == "decision-A"
    assert decision.complete is False, "an inconsistent record reported as complete"
    assert decision.inconsistent, "the mismatch was not reported at all"
    joined = " ".join(decision.inconsistent)
    assert "decision-B" in joined and "decision-A" in joined, joined
    refuses(decision.needs_execution, contains="inconsistent durable record")
    j.close()


@test("N2: an unstamped terminal snapshot cannot be identified, so it blocks")
def _():
    j = fresh("n2-unstamped")
    j.set_state(OID, "CONFIRMED")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")
    write_snapshot(j, stamp=False)

    decision = restore(j, OID)
    assert decision.complete is False
    refuses(decision.needs_execution, contains="bound-decision stamp")
    j.close()


@test("N2: an acknowledgement naming a different state than the snapshot blocks")
def _():
    j = fresh("n2-ack-mismatch")
    j.set_state(OID, "CONFIRMED")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")
    write_snapshot(j, ack_state="SADFLOW_SUPPLY")

    decision = restore(j, OID)
    assert decision.complete is False
    refuses(decision.needs_execution, contains="acknowledgement records")
    j.close()


@test("N2: a binding with no durable operation is an evidence gap, not a work order")
def _():
    j = fresh("n2-missing-operation")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")   # history lost: no operation row
    built = []

    decision = restore(j, OID, build_machine=lambda: built.append(1) or Machine())
    assert decision.operation_state is None
    assert not built, (
        "a machine was built with no durable operation behind it; lost history became "
        "permission for fresh work")
    assert decision.inconsistent, "the missing operation was not reported"
    refuses(decision.needs_execution, contains="no durable operation record")
    j.close()


@test("N2: a complete native decision whose operation never CONFIRMED blocks")
def _():
    j = fresh("n2-unconfirmed")
    j.set_state(OID, "FAILED")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")
    write_snapshot(j)

    decision = restore(j, OID)
    assert decision.complete is False, (
        "a COMPLETED, acknowledged native decision was reported complete while its "
        "operation had not confirmed")
    refuses(decision.needs_execution, contains="not CONFIRMED")
    j.close()


# --------------------------------------------------------------------------------------
# SECOND PASS: gaps an independent review of the N1/N2 fixes found in them.
# --------------------------------------------------------------------------------------

@test("C1: an acknowledgement with NO snapshot is a torn record, not a work order")
def _():
    # The mirror of "terminal snapshot with no acknowledgement", which was guarded while
    # this was not. apply() writes both in one transaction, so an ack alone cannot happen
    # cleanly -- and unflagged it read as permission to do the work again.
    j = fresh("c1-ack-without-snapshot")
    j.set_state(OID, "FAILED")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")
    with j.transaction() as conn:
        conn.execute("INSERT OR REPLACE INTO meta VALUES(?,?)",
                     (NATIVE_ACK_KEY.format(operation_id=OID), "COMPLETED"))
    built = []

    decision = restore(j, OID, build_machine=lambda: built.append(1) or Machine())
    assert decision.inconsistent, "an acknowledgement with no snapshot was not reported"
    assert not built, "a machine was built for an operation the native side already acked"
    refuses(decision.needs_execution, contains="torn")
    j.close()


@test("C2: an UNSTAMPED snapshot blocks at any state, not only a terminal one")
def _():
    # Gating the stamp requirement on TERMINAL let a mid-lifecycle snapshot that belongs
    # to nobody sit under an operation that then asked to work again.
    j = fresh("c2-unstamped-midlifecycle")
    j.set_state(OID, "AUTHORIZED")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")
    write_snapshot(j, state="SADFLOW_SUPPLY", ack=True, stamp=False,
                   ack_state="SADFLOW_SUPPLY")
    built = []

    decision = restore(j, OID, build_machine=lambda: built.append(1) or Machine())
    assert decision.inconsistent, "an unattributable snapshot was accepted"
    assert not built, "a machine was built under an unattributable snapshot"
    refuses(decision.needs_execution, contains="bound-decision stamp")
    j.close()


@test("B1: a step that MOVES the machine invalidates a prior verification")
def _():
    # step() is an in-memory advance like any other. Previously needs_execution() could
    # walk the object off the state its snapshot described while `authoritative` stayed
    # True, so require_authoritative() kept passing for a state never committed.
    j = fresh("b1-drift")
    j.set_state(OID, "CONFIRMED")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")
    machine = Machine()
    consumer = applied(j, machine)
    assert consumer.verify_committed(j, OID) is True
    assert consumer.authoritative is True

    # Make the NEXT step move the machine off the verified COMPLETED state: this model
    # recomputes its state from the receipt, so a failing one drives COMPLETED ->
    # SADFLOW_SUPPLY. The drift has to happen inside step(), not be written around it.
    machine.receipt = SimpleNamespace(success=False)
    assert consumer.needs_execution() is True
    assert consumer.state == "SADFLOW_SUPPLY", consumer.state
    assert consumer.authoritative is False, (
        "the machine advanced off its committed snapshot but stayed authoritative")
    assert consumer.dirty is True
    refuses(consumer.require_authoritative, contains="cannot be moved back")
    j.close()


@test("B1 CONTROL: a poll that does NOT move the machine changes nothing")
def _():
    # The counterpart. A clean pre-dispatch machine must stay pollable, so a step that
    # leaves the state alone must not mark it dirty.
    consumer = NativeStateMachineConsumer(Machine(state="VALIDATING_SUPPLY"))
    for _i in range(3):
        assert consumer.needs_execution() is True
    assert consumer.dirty is False, "repeated polling of a clean machine made it dirty"

    j = fresh("b1-control-verified")
    j.set_state(OID, "CONFIRMED")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")
    committed = applied(j, Machine())
    assert committed.verify_committed(j, OID) is True
    # At COMPLETED the pinned machine does not move, so authority survives the poll.
    assert committed.needs_execution() is False
    assert committed.authoritative is True, (
        "an inert poll revoked authority that was legitimately established")
    j.close()


# --------------------------------------------------------------------------------------
# POSITIVE: the controls above must not be blocking everything.
# --------------------------------------------------------------------------------------

@test("POSITIVE CONTROL: a coherent fresh decision still builds a machine and asks to work")
def _():
    j = fresh("positive-fresh")
    j.set_state(OID, "AUTHORIZED")
    bind_native_decision(j, OID, "decision-A", "SUPPLY")
    built = []

    decision = restore(j, OID, build_machine=lambda: built.append(1) or Machine())
    assert decision.inconsistent == [], decision.inconsistent
    assert len(built) == 1, "a coherent pre-dispatch record did not build its machine"
    assert decision.needs_execution() is True, (
        "a coherent operation with work outstanding refused to ask for it")
    j.close()


@test("POSITIVE CONTROL: nothing recorded at all is a genuinely new decision, not a gap")
def _():
    j = fresh("positive-empty")
    built = []
    decision = restore(j, OID, build_machine=lambda: built.append(1) or Machine())
    assert decision.inconsistent == [], (
        f"an empty record was read as an evidence gap: {decision.inconsistent}")
    assert len(built) == 1
    assert decision.needs_execution() is True
    j.close()


def main() -> int:
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"P03 native checkpoint: FAIL ({len(FAILED)}/{len(PASSED) + len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} native decision/recovery tests held "
          "(synthetic journal and machine; the pinned consumer is check-phase-03-composed)")
    return 0


if __name__ == "__main__":
    code = main()
    TMP.cleanup()
    sys.exit(code)
