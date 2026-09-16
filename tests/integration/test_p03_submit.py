"""P03: the submission path -- journal, sign, send, reconcile.

LOCAL. The executor is `OfflineTransport`, so nothing here establishes L10. What these
tests establish is the ORDERING and the state mapping: that the attempt is durable
before any network I/O, that an ambiguous send leaves the operation blocked rather than
retried, and that a verdict comes from the chain rather than from the executor's word.

The chain reader is a small in-test double over `consumed[operationId]`. It is a stand-in
for chain ACCESS, not for chain BEHAVIOUR: the behaviour it stands in for -- that the
controller writes consumed[id] = payloadHash in the same transaction as the economic
effect -- is separately proven against the real pinned Morpho on the fork in P02.
"""
from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "packages", "core"))
sys.path.insert(0, os.path.join(ROOT, "adapter"))

import json  # noqa: E402

from held_adapter.execution.keeperhub import (  # noqa: E402
    HttpResponse,
    KeeperHubClient,
    OfflineTransport,
    SendOutcome,
)
from held_adapter.execution.submit import (  # noqa: E402
    NotReconcilable,
    SubmissionError,
    Submitter,
)
from held_adapter.signing.runner_signer import RunnerSigner  # noqa: E402
from held_core.identity import ActionFamily, AuthorizationEnvelope, OperationScope  # noqa: E402
from held_core.journal import Journal, OperationState  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

API_ENV = "HELD_KEEPERHUB_API_KEY"
RUNNER_KEY = "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6"
RUNNER = "0x90F79bf6EB2c4f870365E785982E1f101E93b906"
SAFE = "0x08deEDA0Ba1eb4B6B4b5cc4DD0c4BC689EA37180"
CONTROLLER = "0x3875311cc0d4017a033893a9653a0725378aca1c"
SCOPE = OperationScope(8453, CONTROLLER, SAFE, "0x" + "11" * 32)

OP_ID = bytes.fromhex("aa" * 32)
PAYLOAD = bytes.fromhex("cc" * 32)
OP_HEX = "0x" + "aa" * 32
PAYLOAD_HEX = "0x" + "cc" * 32
EMPTY = "0x" + "00" * 32
CALLDATA = "0x" + "ab" * 200


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


def expect(exc_type, fn, *a, **k) -> str:
    try:
        fn(*a, **k)
    except exc_type as e:
        return str(e)
    raise AssertionError(f"expected {exc_type.__name__}, nothing raised")


def ok(body: dict, status: int = 200) -> HttpResponse:
    return HttpResponse(status, json.dumps(body).encode(), {})


class Admitted:
    """The fields Submitter reads off an AdmittedOperation."""
    operation_id = OP_ID
    payload_hash = PAYLOAD
    source_decision_id = "decision-1"
    action_index = 0


class Chain:
    """A stand-in for chain ACCESS. Returns whatever consumed[] was seeded with."""

    def __init__(self, marker: str = EMPTY) -> None:
        self.marker = marker
        self.reads = 0

    def consumed(self, controller: str, operation_id: str) -> str:
        self.reads += 1
        return self.marker


def envelope(epoch: int = 1) -> AuthorizationEnvelope:
    return AuthorizationEnvelope(
        scope=SCOPE, operation_id=OP_ID, source_identity_hash=bytes.fromhex("bb" * 32),
        payload_hash=PAYLOAD, action_family=ActionFamily.SUPPLY,
        epoch=epoch, policy_version=1, runner=RUNNER,
    )


def rig(responses, *, tmp):
    os.environ[API_ENV] = "kh_local_test_credential_not_real"
    os.environ["HELD_RUNNER_KEY"] = RUNNER_KEY
    j = Journal(os.path.join(tmp, "held.sqlite"))
    t = OfflineTransport(responses)
    c = KeeperHubClient(transport=t, sleep=lambda _: None)
    s = RunnerSigner("env:HELD_RUNNER_KEY", RUNNER)
    n = iter([f"attempt-{i}" for i in range(1, 50)])
    return j, t, Submitter(j, c, s, CONTROLLER, 8453, new_attempt_id=lambda: next(n))


# --------------------------------------------------------------------- ordering --
@test("the attempt is durable BEFORE any network I/O")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = rig([ok({"executionId": "exec-1"})], tmp=d)

        seen: dict = {}
        original = t.request

        def spy(*a, **k):
            # At the moment the request goes out, the attempt row must already exist.
            seen["attempts"] = j.attempts_for(OP_HEX)
            return original(*a, **k)

        t.request = spy  # type: ignore[assignment]
        sub.submit(Admitted(), envelope(), CALLDATA)

        assert len(seen["attempts"]) == 1, (
            "no attempt row existed when the request was sent; a crash there would look "
            "like nothing was sent"
        )
        assert seen["attempts"][0]["state"] == "PENDING"


@test("the journaled attempt carries the signer REFERENCE, never key material")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, _, sub = rig([ok({"executionId": "e"})], tmp=d)
        sub.submit(Admitted(), envelope(), CALLDATA)
        row = j.attempts_for(OP_HEX)[0]
        assert row["signer_ref"] == "env:HELD_RUNNER_KEY"
        assert RUNNER_KEY not in json.dumps(row) and RUNNER_KEY[2:] not in json.dumps(row)
        assert row["runner"] == RUNNER.lower()


@test("a retry of the same attempt id reuses the execution key")
def _():
    with tempfile.TemporaryDirectory() as d:
        _, t, sub = rig([ok({}, 503), ok({"executionId": "e"})], tmp=d)
        s = sub.submit(Admitted(), envelope(), CALLDATA, attempt_id="fixed-attempt")
        keys = {c["body"]["idempotencyKey"] for c in t.calls}
        assert len(keys) == 1 and s.execution_key in keys


# -------------------------------------------------------------- state mapping --
@test("ACCEPTED becomes DISPATCHED and awaits the chain")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, _, sub = rig([ok({"executionId": "exec-1", "transactionHash": "0x" + "ef" * 32})], tmp=d)
        s = sub.submit(Admitted(), envelope(), CALLDATA)
        assert s.send.outcome is SendOutcome.ACCEPTED
        assert s.journal_state is OperationState.DISPATCHED
        assert j.get(OP_HEX).state is OperationState.DISPATCHED
        assert s.needs_reconciliation, "a tx hash is not a verdict"


@test("a 409 is DISPATCHED, not a failure and not a resend")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = rig([ok({"executionId": "exec-existing"}, 409)], tmp=d)
        s = sub.submit(Admitted(), envelope(), CALLDATA)
        assert s.send.outcome is SendOutcome.IN_PROGRESS
        assert j.get(OP_HEX).state is OperationState.DISPATCHED
        assert len(t.calls) == 1


@test("REJECTED becomes FAILED, which permits reauthorizing the SAME id")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, _, sub = rig([ok({"message": "bad request"}, 400),
                         ok({"executionId": "exec-2"})], tmp=d)
        s = sub.submit(Admitted(), envelope(), CALLDATA)
        assert s.journal_state is OperationState.FAILED
        # V4 §4: definite non-execution means the same id and payload may be retried
        # under a new epoch. Nothing was consumed, so nothing is being re-executed.
        s2 = sub.submit(Admitted(), envelope(epoch=2), CALLDATA)
        assert s2.journal_state is OperationState.DISPATCHED
        assert j.get(OP_HEX).payload_hash == PAYLOAD_HEX, "the payload binding held"


@test("an ambiguous send leaves the operation UNKNOWN and BLOCKED")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, _, sub = rig([TimeoutError("t")] * 4, tmp=d)
        s = sub.submit(Admitted(), envelope(), CALLDATA)
        assert s.send.outcome is SendOutcome.UNKNOWN
        assert j.get(OP_HEX).state is OperationState.UNKNOWN

        # The point of UNKNOWN: no amount of trying again is allowed to resolve it.
        msg = expect(SubmissionError, sub.submit, Admitted(), envelope(epoch=2), CALLDATA)
        assert "UNKNOWN" in msg and "chain evidence" in msg, msg


@test("a CONFIRMED operation is never re-executed")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, _, sub = rig([ok({"executionId": "e"})], tmp=d)
        sub.submit(Admitted(), envelope(), CALLDATA)
        sub.reconcile(OP_HEX, PAYLOAD_HEX, Chain(PAYLOAD_HEX))
        assert j.get(OP_HEX).state is OperationState.CONFIRMED
        msg = expect(SubmissionError, sub.submit, Admitted(), envelope(epoch=3), CALLDATA)
        assert "never re-execute" in msg, msg


@test("a dry run does not advance the operation towards execution")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = rig([ok({"simulated": True})], tmp=d)
        s = sub.submit(Admitted(), envelope(), CALLDATA, dry_run=True)
        assert t.calls[0]["body"]["simulate"] is True
        assert j.get(OP_HEX).state is not OperationState.DISPATCHED
        assert j.attempts_for(OP_HEX)[0]["state"] == "DRY_RUN"


# ----------------------------------------------------------- reconciliation --
@test("the verdict comes from consumed[operationId], not from the executor")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, _, sub = rig([ok({"executionId": "e", "transactionHash": "0x" + "ef" * 32})], tmp=d)
        sub.submit(Admitted(), envelope(), CALLDATA)
        chain = Chain(PAYLOAD_HEX)
        assert sub.reconcile(OP_HEX, PAYLOAD_HEX, chain) is OperationState.CONFIRMED
        assert chain.reads == 1, "reconciliation must actually read the chain"


@test("an id consumed by a DIFFERENT payload is not success")
def _():
    with tempfile.TemporaryDirectory() as d:
        _, _, sub = rig([ok({"executionId": "e"})], tmp=d)
        sub.submit(Admitted(), envelope(), CALLDATA)
        msg = expect(SubmissionError, sub.reconcile, OP_HEX, PAYLOAD_HEX,
                     Chain("0x" + "dd" * 32))
        assert "DIFFERENT action" in msg, msg
        # A mere presence check would have called this a success.


@test("a mined-but-unconsumed operation is not declared failed")
def _():
    with tempfile.TemporaryDirectory() as d:
        _, _, sub = rig([ok({"executionId": "e", "transactionHash": "0x" + "ef" * 32})], tmp=d)
        sub.submit(Admitted(), envelope(), CALLDATA)
        # KeeperHub reported a hash, but nothing consumed the id. It may still be in
        # flight; declaring failure here would invite a double execution.
        msg = expect(NotReconcilable, sub.reconcile, OP_HEX, PAYLOAD_HEX, Chain(EMPTY))
        assert "still be in flight" in msg, msg


@test("a definitively refused send reconciles to FAILED without chain consumption")
def _():
    with tempfile.TemporaryDirectory() as d:
        _, _, sub = rig([ok({"message": "nope"}, 422)], tmp=d)
        sub.submit(Admitted(), envelope(), CALLDATA)
        assert sub.reconcile(OP_HEX, PAYLOAD_HEX, Chain(EMPTY)) is OperationState.FAILED


@test("without a chain reader there is no verdict at all")
def _():
    with tempfile.TemporaryDirectory() as d:
        _, _, sub = rig([ok({"executionId": "e"})], tmp=d)
        sub.submit(Admitted(), envelope(), CALLDATA)
        msg = expect(NotReconcilable, sub.reconcile, OP_HEX, PAYLOAD_HEX, None)
        assert "not a substitute" in msg, msg


@test("an UNKNOWN operation is resolved by chain evidence, in either direction")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, _, sub = rig([TimeoutError("t")] * 4, tmp=d)
        sub.submit(Admitted(), envelope(), CALLDATA)
        assert j.get(OP_HEX).state is OperationState.UNKNOWN
        # It turns out it DID execute. Recovering that is the whole point of not
        # having retried it.
        assert sub.reconcile(OP_HEX, PAYLOAD_HEX, Chain(PAYLOAD_HEX)) is OperationState.CONFIRMED


@test("polling an in-flight execution still takes its verdict from the chain")
def _():
    with tempfile.TemporaryDirectory() as d:
        _, t, sub = rig([ok({"executionId": "exec-5"}, 409),
                         ok({"executionId": "exec-5", "transactionHash": "0x" + "ef" * 32})],
                        tmp=d)
        s = sub.submit(Admitted(), envelope(), CALLDATA)
        chain = Chain(PAYLOAD_HEX)
        assert sub.resolve_in_progress(s, chain) is OperationState.CONFIRMED
        assert t.calls[-1]["url"].endswith("/api/execute/exec-5")
        assert chain.reads == 1


@test("the submission record is loggable and carries no secrets")
def _():
    with tempfile.TemporaryDirectory() as d:
        _, _, sub = rig([ok({"executionId": "e"})], tmp=d)
        rec = sub.submit(Admitted(), envelope(), CALLDATA).to_record()
        blob = json.dumps(rec)
        assert RUNNER_KEY not in blob and "kh_local" not in blob
        assert rec["hosted"] is False, "a local submission must not look hosted"
        assert rec["journal_state"] == "DISPATCHED"


def main() -> int:
    for v in (API_ENV, "HELD_RUNNER_KEY"):
        os.environ.pop(v, None)
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"P03 submit: FAIL ({len(FAILED)}/{len(PASSED)+len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} P03 submission tests held (L10 NOT established)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
