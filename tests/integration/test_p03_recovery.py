"""P03-C2: crash and restart across a real SQLite database.

The previous submission tests asserted that a function returned UNKNOWN. That is not the
failure the review found. The failure is what a NEW PROCESS does when it opens the
database after the old one died mid-send, so these tests close and reopen the actual
SQLite file, and one of them kills a real child process between the send and the
response.

Reproducing the original defect, from the review:

  1. Authorize operation O and persist attempt A.
  2. Let the transport receive the request, then terminate the caller before the result
     is recorded.
  3. Reopen the database in a fresh process.
  4. O is AUTHORIZED with a PENDING attempt.
  5. submit() again -> a NEW attempt B and a SECOND network request.

Step 5 is what must no longer be possible.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "packages", "core"))
sys.path.insert(0, os.path.join(ROOT, "adapter"))

from held_adapter.execution.keeperhub import (  # noqa: E402
    HttpResponse,
    KeeperHubClient,
    OfflineTransport,
    SendOutcome,
)
from held_adapter.execution.submit import (  # noqa: E402
    NotReconcilable,
    ResumeRequired,
    SubmissionError,
    Submitter,
)
from held_adapter.signing.runner_signer import RunnerSigner  # noqa: E402
from held_core.identity import ActionFamily, AuthorizationEnvelope, OperationScope  # noqa: E402
from held_core.journal import Journal, OperationState, StateTransitionError  # noqa: E402

from p03_fixtures import (  # noqa: E402
    API_ENV, CONTROLLER, EMPTY, MARKET_PARAMS, OP_HEX, PAYLOAD_HEX, RUNNER, RUNNER_KEY,
    Admitted, Chain, accepted, envelope, response, rig,
)

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


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


# ------------------------------------------- the claim is durable before any I/O --
@test("the operation is DISPATCHED on disk BEFORE the request leaves the process")
def _():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "held.sqlite")
        j, t, sub = rig([accepted()], path=path)
        seen = {}

        original = t.request

        def spy(*a, **k):
            # Open a SEPARATE connection to the same file at the moment of the send.
            # Anything not committed yet is invisible here, which is exactly what a
            # crashed-and-restarted process would see.
            probe = Journal(path)
            op = probe.get(OP_HEX)
            seen["state"] = op.state.value
            seen["attempt"] = probe.unresolved_attempt(OP_HEX)
            probe.close()
            return original(*a, **k)

        t.request = spy
        sub.submit(Admitted(), envelope())

        assert seen["state"] == "DISPATCHED", (
            f"at send time the durable state was {seen['state']}, not DISPATCHED. A crash "
            "here would look like an operation that was never sent.")
        assert seen["attempt"] is not None
        assert seen["attempt"]["idempotency_key"].startswith("0x")
        assert seen["attempt"]["request_body"], "the exact request was not persisted"
        assert seen["attempt"]["calldata"].startswith("0x")


@test("REGRESSION C2: a restart does NOT start a second submission")
def _():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "held.sqlite")
        # Process 1: claims and sends, then "dies" before recording the result.
        j1, t1, sub1 = rig([TimeoutError("killed mid-send")], path=path)
        try:
            sub1.submit(Admitted(), envelope())
        except Exception:
            pass
        j1.close()

        # Process 2: fresh connection to the same file.
        j2, t2, sub2 = rig([accepted()], path=path)
        op = j2.get(OP_HEX)
        assert op.state is OperationState.UNKNOWN or op.state is OperationState.DISPATCHED, op.state

        outstanding = j2.unresolved_attempt(OP_HEX)
        assert outstanding is not None, (
            "the crashed attempt is invisible to recovery, so nothing points at the "
            "original idempotency key")
        msg = expect(ResumeRequired, sub2.submit, Admitted(), envelope())
        assert "unresolved attempt" in msg and "executed twice" in msg, msg
        assert len(t2.calls) == 0, "a second network request was sent after the crash"


@test("REGRESSION C2: killing a real process mid-send leaves a resumable claim")
def _():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "held.sqlite")
        script = os.path.join(d, "crash.py")
        with open(script, "w") as fh:
            fh.write(f'''
import os, sys, signal
sys.path.insert(0, {os.path.join(ROOT, "packages", "core")!r})
sys.path.insert(0, {os.path.join(ROOT, "adapter")!r})
sys.path.insert(0, {HERE!r})
from p03_fixtures import rig, Admitted, envelope
import p03_fixtures

class Suicide:
    hosted = False
    calls = []
    def request(self, *a, **k):
        # The request has "reached" the server. Die before anything is recorded.
        os.kill(os.getpid(), signal.SIGKILL)

j, _, sub = rig([], path={path!r}, transport=Suicide())
sub.submit(Admitted(), envelope())
''')
        proc = subprocess.run([sys.executable, script], capture_output=True)
        assert proc.returncode != 0, "the child was supposed to be killed"

        # A brand-new process opens the database the killed one left behind.
        j, t, sub = rig([accepted()], path=path)
        op = j.get(OP_HEX)
        assert op is not None, "the claim was not durable across SIGKILL"
        assert op.state is OperationState.DISPATCHED, (
            f"after SIGKILL the operation is {op.state.value}; it must be DISPATCHED so a "
            "restart cannot treat it as never-sent")
        attempt = j.unresolved_attempt(OP_HEX)
        assert attempt is not None and attempt["state"] == "PENDING"

        msg = expect(ResumeRequired, sub.submit, Admitted(), envelope())
        assert "resume()" in msg
        assert len(t.calls) == 0, "a duplicate submission was sent after SIGKILL"


@test("an UNKNOWN send leaves a LIVE attempt, not an invisible one")
def _():
    # This was a real bug in my own work: unresolved_attempt() matched only PENDING, so
    # an ambiguous send -- the single most important case -- recorded UNKNOWN and vanished
    # from recovery. It also let two tests below return before asserting anything.
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "held.sqlite")
        j, t, sub = rig([TimeoutError("t")] * 4, path=path)
        s = sub.submit(Admitted(), envelope())
        assert s.send.outcome is SendOutcome.UNKNOWN
        row = j.attempts_for(OP_HEX)[0]
        assert row["state"] == "UNKNOWN"
        live = j.unresolved_attempt(OP_HEX)
        assert live is not None, "an UNKNOWN attempt must remain visible to recovery"
        assert live["attempt_id"] == row["attempt_id"]


@test("resume resends the IDENTICAL body under the IDENTICAL key")
def _():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "held.sqlite")
        j1, t1, sub1 = rig([TimeoutError("t")] * 4, path=path)
        sub1.submit(Admitted(), envelope())
        first = j1.attempts_for(OP_HEX)[0]
        first_body, first_key = first["request_body"], first["idempotency_key"]
        j1.close()

        j2, t2, sub2 = rig([accepted()], path=path)
        live = j2.unresolved_attempt(OP_HEX)
        assert live is not None, "nothing to resume — the claim was lost across restart"
        s = sub2.resume(OP_HEX)
        assert s.resumed is True
        assert len(t2.calls) == 1, "resume must send exactly one request"
        sent = t2.calls[0]
        assert sent["headers"]["Idempotency-Key"] == first_key, "resume minted a new key"
        assert json.dumps(sent["body"], sort_keys=True) == first_body, "the body changed on resume"


@test("an ACCEPTED or IN_PROGRESS attempt is polled, never resent")
def _():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "held.sqlite")
        j, t, sub = rig([accepted("exec-1")], path=path)
        sub.submit(Admitted(), envelope())
        assert j.unresolved_attempt(OP_HEX)["state"] == "ACCEPTED"
        before = len(t.calls)
        msg = expect(SubmissionError, sub.resume, OP_HEX)
        assert "the executor has it" in msg and "do not resend" in msg, msg
        assert len(t.calls) == before, "resume re-sent an attempt the executor already had"


@test("two concurrent submitters cannot both claim the same operation")
def _():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "held.sqlite")
        j, t, sub = rig([accepted(), accepted()], path=path, attempt_ids=["a1", "a2"])
        # First claim succeeds and leaves a PENDING row (transport never answers).
        j.create_or_reopen(OP_HEX, PAYLOAD_HEX, "decision-1", 0, 1)
        j.transition(OP_HEX, OperationState.AUTHORIZED, epoch=1)
        j.claim_for_dispatch(
            attempt_id="first", operation_id=OP_HEX, envelope_hash="0x" + "dd" * 32,
            epoch=1, runner=RUNNER, signer_ref="env:HELD_RUNNER_KEY",
            idempotency_key="0x" + "ee" * 32, request_body="{}", calldata="0xabcd")
        msg = expect(
            StateTransitionError, j.claim_for_dispatch,
            attempt_id="second", operation_id=OP_HEX, envelope_hash="0x" + "dd" * 32,
            epoch=1, runner=RUNNER, signer_ref="env:HELD_RUNNER_KEY",
            idempotency_key="0x" + "ff" * 32, request_body="{}", calldata="0xabcd")
        assert "already has an unresolved attempt" in msg, msg


@test("a simulation never claims the operation and never blocks a real send")
def _():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "held.sqlite")
        j, t, sub = rig([
            # The DOCUMENTED affirmative simulation result.
            HttpResponse(200, json.dumps(
                {"success": True, "status": "simulated", "wouldRevert": False}).encode(), {}),
            accepted(),
        ], path=path)
        j.create_or_reopen(OP_HEX, PAYLOAD_HEX, "decision-1", 0, 1)
        s = sub.dry_run(Admitted(), envelope())
        assert s.send.outcome is SendOutcome.SIMULATED, s.send.outcome
        assert j.unresolved_attempt(OP_HEX) is None, "a dry run claimed the operation"
        assert j.get(OP_HEX).state is OperationState.CREATED
        assert t.calls[0]["body"]["simulate"] is True
        # The real send still works afterwards.
        s2 = sub.submit(Admitted(), envelope())
        assert s2.journal_state is OperationState.DISPATCHED


def _expired_rig(d):
    """A crash-preserved live attempt, observed far past the idempotency window."""
    path = os.path.join(d, "held.sqlite")
    j1, t1, sub1 = rig([TimeoutError("t")] * 4, path=path)
    sub1.submit(Admitted(), envelope())
    j1.close()
    j2, t2, sub2 = rig([accepted()], path=path, now=lambda: 1e12)
    assert j2.unresolved_attempt(OP_HEX) is not None, "no live attempt to exercise"
    return j2, t2, sub2


@test("beyond the window, a resend requires chain evidence first")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = _expired_rig(d)
        msg = expect(NotReconcilable, sub.resume, OP_HEX, None)
        assert "idempotency window" in msg and "consumed[operationId]" in msg, msg
        assert len(t.calls) == 0, "resent past the window without checking the chain"


@test("beyond the window, chain evidence showing execution resolves instead of resending")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = _expired_rig(d)
        msg = expect(SubmissionError, sub.resume, OP_HEX, Chain(PAYLOAD_HEX))
        assert "already executed" in msg, msg
        assert len(t.calls) == 0
        assert j.get(OP_HEX).state is OperationState.CONFIRMED


@test("REGRESSION: beyond the window, a ZERO marker alone must NOT resend")
def _():
    # The defect: "not consumed at block N" was treated as "did not execute", and the
    # method fell through to broadcast. Outside the dedupe window that is a SECOND
    # submission of the same economic action, not a protected retry -- the original
    # transaction may still be pending.
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = _expired_rig(d)
        msg = expect(NotReconcilable, sub.resume, OP_HEX, Chain(EMPTY, controller_epoch=1))
        assert "has NOT been retired" in msg, msg
        assert "SECOND submission" in msg, msg
        assert len(t.calls) == 0, "a zero marker alone caused a resend"
        assert j.get(OP_HEX).state is OperationState.UNKNOWN, "must remain blocked"
        assert j.unresolved_attempt(OP_HEX) is not None, "the claim must survive"


@test("beyond the window, a RETIRED authorization is definite non-execution")
def _():
    # The epoch has advanced past the one the envelope was signed under, so that
    # signature can never execute. Only now is non-execution definite -- and the answer
    # is still not "resend the old request", which would revert on the epoch check.
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = _expired_rig(d)
        msg = expect(SubmissionError, sub.resume, OP_HEX, Chain(EMPTY, controller_epoch=2))
        assert "definitely did not execute" in msg, msg
        assert "Reauthorize the SAME id and payload" in msg, msg
        assert len(t.calls) == 0, "a retired attempt was resent"
        assert j.get(OP_HEX).state is OperationState.FAILED
        assert j.unresolved_attempt(OP_HEX) is None, "a retired attempt must stop blocking"
        assert j.attempts_for(OP_HEX)[0]["state"] == "RETIRED"


@test("a reader that cannot report the controller epoch cannot retire anything")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = _expired_rig(d)
        msg = expect(NotReconcilable, sub.resume, OP_HEX, Chain(EMPTY))  # epoch None
        assert "did not report the controller epoch" in msg, msg
        assert len(t.calls) == 0


@test("an idempotency_conflict blocks the operation instead of looking in-flight")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = rig([HttpResponse(409, json.dumps({
            "code": "idempotency_conflict", "retryable": False,
            "message": "key reused with a different body"}).encode(), {})],
            path=os.path.join(d, "held.sqlite"))
        s = sub.submit(Admitted(), envelope())
        assert s.send.outcome is SendOutcome.IDEMPOTENCY_CONFLICT
        assert s.journal_state is OperationState.UNKNOWN, (
            "a conflicting body means the ORIGINAL body's outcome is unknown; treating it "
            "as in-flight would invite a poll for something that was never accepted")
        assert "non-deterministic" in (s.send.error or "")


# ------------------------------------------- outcome-state consistency (review 3) --
@test("REGRESSION: a CONFIRMED operation never submits through resume()")
def _():
    # reconcile() settled the OPERATION but left its attempt live, and resume() reached
    # broadcast() before noticing. The prohibited transition was caught afterwards --
    # long after the outbound-call decision.
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "held.sqlite")
        j1, t1, sub1 = rig([TimeoutError("t")] * 4, path=path)
        sub1.submit(Admitted(), envelope())
        sub1.reconcile(OP_HEX, PAYLOAD_HEX, Chain(PAYLOAD_HEX))
        assert j1.get(OP_HEX).state is OperationState.CONFIRMED
        assert j1.unresolved_attempt(OP_HEX) is None, (
            "reconciliation left a live attempt under a CONFIRMED operation")
        j1.close()

        j2, t2, sub2 = rig([accepted()], path=path)   # fresh process, in-window
        msg = expect(SubmissionError, sub2.resume, OP_HEX)
        assert "CONFIRMED" in msg and "never re-execute" in msg, msg
        assert len(t2.calls) == 0, "resume sent work already known to be complete"


@test("a stale live attempt under a CONFIRMED operation is settled, not resent")
def _():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "held.sqlite")
        j, t, sub = rig([TimeoutError("t")] * 4, path=path)
        sub.submit(Admitted(), envelope())
        # Confirm the operation WITHOUT going through reconcile(), so a live attempt
        # survives -- the exact state the defect produced.
        j.transition(OP_HEX, OperationState.CONFIRMED, epoch=1)
        assert j.unresolved_attempt(OP_HEX) is not None
        before = len(t.calls)   # the submit above already spent its retry attempts
        msg = expect(SubmissionError, sub.resume, OP_HEX)
        assert "stale attempt(s) settled" in msg, msg
        assert j.unresolved_attempt(OP_HEX) is None
        assert len(t.calls) == before, "resume sent a request for a CONFIRMED operation"


def _crash_then_reject(d, kind: str):
    """Leave a crash-preserved attempt, then reject the RESUMED request."""
    path = os.path.join(d, kind + ".sqlite")
    if kind == "killed":
        # Dies inside the transport: DISPATCHED + PENDING, no outcome recorded.
        class Dies:
            hosted = False
            calls: list = []

            def request(self, *a, **k):
                raise SystemExit("process died mid-send")

        j, t, sub = rig([], path=path, transport=Dies())
        try:
            sub.submit(Admitted(), envelope())
        except SystemExit:
            pass
    else:
        # Returns ambiguous: UNKNOWN + UNKNOWN.
        j, t, sub = rig([TimeoutError("t")] * 4, path=path)
        sub.submit(Admitted(), envelope())
    before = (j.get(OP_HEX).state.value, j.attempts_for(OP_HEX)[0]["state"])
    j.close()
    j2, t2, sub2 = rig([response({"message": "key revoked"}, 401)], path=path)
    sub2.resume(OP_HEX)
    return before, j2


@test("REGRESSION: a rejected retry settles neither post-crash form")
def _():
    # THE RULE: the response to the latest request and the settlement of the ORIGINAL
    # attempt are different facts. Keying on state pairs was the wrong shape --
    # DISPATCHED/PENDING took the FAILED path while UNKNOWN/UNKNOWN did not, and BOTH
    # dropped the original attempt out of the live set.
    with tempfile.TemporaryDirectory() as d:
        for kind in ("killed", "ambiguous"):
            before, j = _crash_then_reject(d, kind)
            assert j.get(OP_HEX).state is OperationState.UNKNOWN, (
                f"{kind} ({before}): a 401 on the retry declared the operation settled, "
                "though the pre-crash request may have reached execution")
            assert j.unresolved_attempt(OP_HEX) is not None, (
                f"{kind} ({before}): the ORIGINAL attempt left the live set, so recovery "
                "can no longer find the thing it has to resolve")
            assert j.attempts_for(OP_HEX)[0]["state"] == "UNKNOWN"


@test("CONTROL: a fresh request definitively refused IS settled")
def _():
    # The rule must still let a genuine first-dispatch rejection settle, or it would
    # block every operation forever.
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = rig([response({"message": "bad request"}, 400)],
                        path=os.path.join(d, "held.sqlite"))
        s = sub.submit(Admitted(), envelope())
        assert s.journal_state is OperationState.FAILED
        assert j.attempts_for(OP_HEX)[0]["state"] == "REJECTED"
        assert j.unresolved_attempt(OP_HEX) is None


@test("REGRESSION: ambiguity inside the client's own retry loop is preserved")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = rig([TimeoutError("t"), response({"message": "revoked"}, 401)],
                        path=os.path.join(d, "held.sqlite"))
        s = sub.submit(Admitted(), envelope())
        assert s.send.outcome is SendOutcome.UNKNOWN, (
            "the first attempt was ambiguous, so a rejection on the retry is definitive "
            "about the retry only")
        assert "ambiguous" in (s.send.error or "")
        assert j.get(OP_HEX).state is OperationState.UNKNOWN


@test("the exact idempotency-window boundary counts as expired")
def _():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "held.sqlite")
        j1, t1, sub1 = rig([TimeoutError("t")] * 4, path=path)
        sub1.submit(Admitted(), envelope())
        created = float(j1.attempts_for(OP_HEX)[0]["created_at"])
        j1.close()
        # Exactly at the window: the provider may already have dropped the key. Being a
        # second early costs nothing; a second late costs an unprotected duplicate.
        j2, t2, sub2 = rig([accepted()], path=path, now=lambda: created + 86400)
        expect(NotReconcilable, sub2.resume, OP_HEX, Chain(EMPTY, controller_epoch=1))
        assert len(t2.calls) == 0, "resent at the exact window boundary"


def main() -> int:
    os.environ.pop(API_ENV, None)
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"P03 recovery: FAIL ({len(FAILED)}/{len(PASSED)+len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} P03 crash/restart recovery tests held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
