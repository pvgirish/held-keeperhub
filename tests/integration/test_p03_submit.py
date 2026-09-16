"""P03-C3 and P03-C4: binding the signature to the request, and honest reconciliation.

C3: the submitted request must BE the signed authorization, not merely travel with it.
    The old `submit()` took `admitted`, `envelope` and an arbitrary `calldata` and never
    checked that they corresponded.

C4: reconciliation must use the journal's durable payload binding, not a hash the caller
    supplies. The old code loaded the operation and then compared the chain marker to its
    ARGUMENT, so a caller passing Q for an operation bound to P could drive CONFIRMED.

Each rejection test also asserts that ZERO network calls were made, because "it refused"
and "it refused before spending an execution" are different claims.

The chain reader is an in-test double for chain ACCESS, not chain BEHAVIOUR -- that the
controller writes consumed[id]=payloadHash in the same transaction as the economic effect
is proven against real pinned Morpho on the fork in P02.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "packages", "core"))
sys.path.insert(0, os.path.join(ROOT, "adapter"))
sys.path.insert(0, HERE)

from eth_utils import keccak  # noqa: E402

from held_adapter.execution.controller_abi import (  # noqa: E402
    ControllerAbiError,
    build_execute_call,
    encode_call,
    selector,
)
from held_adapter.execution.keeperhub import SendOutcome  # noqa: E402
from held_adapter.execution.submit import (  # noqa: E402
    NotReconcilable,
    SubmissionError,
)
from held_adapter.signing.runner_signer import RunnerSigner  # noqa: E402
from held_core.identity import ActionFamily  # noqa: E402
from held_core.journal import OperationState  # noqa: E402

from p03_fixtures import (  # noqa: E402
    API_ENV, CONTROLLER, EMPTY, MARKET_PARAMS, OP_HEX, PAYLOAD_HEX, RUNNER, RUNNER_KEY,
    SAFE, Admitted, Chain, accepted, envelope, response, rig,
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


def sub_rig(responses, d):
    return rig(responses, path=os.path.join(d, "held.sqlite"))


# ------------------------------------------------- C3: the request IS the auth --
@test("C3: submit() takes no calldata parameter at all")
def _():
    import inspect
    from held_adapter.execution.submit import Submitter
    params = inspect.signature(Submitter.submit).parameters
    assert "calldata" not in params, (
        "submit() still accepts caller-supplied calldata; the signed authorization and "
        "the submitted request can drift apart again")
    assert set(params) == {"self", "admitted", "envelope", "attempt_id"}, params


@test("C3: the submitted request encodes to the signed operation, envelope and signature")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = sub_rig([accepted()], d)
        env = envelope()
        s = sub.submit(Admitted(), env)

        body = t.calls[0]["body"]
        args = json.loads(body["functionArgs"])
        # Selector belongs to executeSupply on the real controller.
        assert body["functionName"] == "executeSupply"
        # The envelope in the request is the envelope that was signed.
        env_arg = args[0]
        assert env_arg[0].lower() == OP_HEX.lower(), "operation id not carried"
        assert env_arg[2].lower() == PAYLOAD_HEX.lower(), "payload hash not carried"
        assert env_arg[4].lower() == SAFE.lower()
        assert env_arg[8].lower() == RUNNER.lower()
        assert int(env_arg[6]) == env.epoch

        # The signature in the request recovers to the runner over the signed digest.
        from eth_account import Account
        sig = bytes.fromhex(args[3][2:])
        assert len(sig) == 65
        recovered = Account._recover_hash(env.signing_hash(), signature=sig)
        assert recovered.lower() == RUNNER.lower(), (
            "the signature in the submitted request is not the runner's signature over "
            "this envelope")

        # And the persisted calldata equals a local re-encode of those arguments.
        stored = j.attempts_for(OP_HEX)[0]["calldata"]
        assert stored == encode_call("executeSupply", args)


@test("C3: an envelope that disagrees with the admitted action is refused, with no send")
def _():
    with tempfile.TemporaryDirectory() as d:
        # Envelope carries a DIFFERENT payload hash than the admitted action.
        j, t, sub = sub_rig([accepted()], d)
        bad = envelope(payload_hash=bytes.fromhex("dd" * 32))
        msg = expect(ControllerAbiError, sub.submit, Admitted(), bad)
        assert "payload hash disagrees" in msg, msg
        assert len(t.calls) == 0, "a mismatched envelope reached the network"


@test("C3: a family mismatch between envelope and admitted action is refused")
def _():
    class WithdrawAction:
        family = ActionFamily.WITHDRAW
        amount = 100_000_000
        on_behalf = SAFE.lower()

    class Mixed(Admitted):
        action = WithdrawAction()

    with tempfile.TemporaryDirectory() as d:
        j, t, sub = sub_rig([accepted()], d)
        msg = expect(ControllerAbiError, sub.submit, Mixed(), envelope())
        assert "family" in msg, msg
        assert len(t.calls) == 0


@test("C3: a HOLD has no controller entry point and cannot be built")
def _():
    class HoldAction:
        family = ActionFamily.HOLD
        amount = 0
        on_behalf = SAFE.lower()

    class Held(Admitted):
        action = HoldAction()

    msg = expect(ControllerAbiError, build_execute_call, Held(), envelope(), bytes(65), MARKET_PARAMS)
    assert "no controller entry point" in msg, msg


@test("C3: a corrupted expected calldata is caught before the request leaves")
def _():
    from held_adapter.execution.controller_abi import function_abi
    from held_adapter.execution.keeperhub import ContractCallRequest
    args = [
        (bytes(32), bytes(32), bytes(32), 1, SAFE.lower(), bytes(32), 1, 1, RUNNER.lower()),
        MARKET_PARAMS, 100_000_000, bytes(65),
    ]
    good = encode_call("executeSupply", args)
    bad = good[:-2] + ("00" if good[-2:] != "00" else "11")
    req = ContractCallRequest(
        chain_id=8453, contract_address=CONTROLLER, function_name="executeSupply",
        function_args=args, abi=function_abi("executeSupply"), expected_calldata=bad)
    msg = expect(ControllerAbiError, req.verify_encoding)
    assert "do not encode to the expected controller calldata" in msg, msg


@test("C3: the round-tripped JSON request still encodes to the same calldata")
def _():
    # This is what resume() depends on: the persisted body is replayable.
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = sub_rig([accepted()], d)
        sub.submit(Admitted(), envelope())
        row = j.attempts_for(OP_HEX)[0]
        body = json.loads(row["request_body"])
        args = json.loads(body["functionArgs"])
        assert encode_call(body["functionName"], args) == row["calldata"], (
            "the persisted request no longer encodes to its own calldata, so a resume "
            "would send different bytes than the original attempt")


# --------------------------------------------------- C4: durable reconciliation --
@test("C4: a caller-supplied hash that disagrees with the journal is refused")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = sub_rig([accepted()], d)
        sub.submit(Admitted(), envelope())
        wrong = "0x" + "99" * 32
        # The old code compared the chain marker to THIS argument, so seeding the chain
        # with the same wrong value would have produced CONFIRMED.
        msg = expect(SubmissionError, sub.reconcile, OP_HEX, wrong, Chain(wrong))
        assert "durably bound" in msg, msg
        assert j.get(OP_HEX).state is not OperationState.CONFIRMED


@test("C4: the verdict comes from consumed[operationId] matching the DURABLE payload")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = sub_rig([accepted("e", "0x" + "ef" * 32)], d)
        sub.submit(Admitted(), envelope())
        chain = Chain(PAYLOAD_HEX)
        assert sub.reconcile(OP_HEX, PAYLOAD_HEX, chain) is OperationState.CONFIRMED
        assert chain.reads == 1, "reconciliation must actually read the chain"


@test("C4: an id consumed by a DIFFERENT payload is not success")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = sub_rig([accepted()], d)
        sub.submit(Admitted(), envelope())
        msg = expect(SubmissionError, sub.reconcile, OP_HEX, PAYLOAD_HEX,
                     Chain("0x" + "dd" * 32))
        assert "DIFFERENT action" in msg, msg


@test("C4: evidence from the wrong chain or controller is not evidence")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = sub_rig([accepted()], d)
        sub.submit(Admitted(), envelope())
        msg = expect(NotReconcilable, sub.reconcile, OP_HEX, PAYLOAD_HEX,
                     Chain(PAYLOAD_HEX, chain_id=1))
        assert "chain 1" in msg and "says nothing" in msg, msg
        msg2 = expect(NotReconcilable, sub.reconcile, OP_HEX, PAYLOAD_HEX,
                      Chain(PAYLOAD_HEX, controller="0x" + "ab" * 20))
        assert "controller" in msg2, msg2


@test("C4: an unfinalized reading is not a verdict")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = sub_rig([accepted()], d)
        sub.submit(Admitted(), envelope())
        msg = expect(NotReconcilable, sub.reconcile, OP_HEX, PAYLOAD_HEX,
                     Chain(PAYLOAD_HEX, finalized=False))
        assert "reorganised" in msg, msg
        assert j.get(OP_HEX).state is not OperationState.CONFIRMED


@test("C4: a mined-but-unconsumed operation is not declared failed")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = sub_rig([accepted("e", "0x" + "ef" * 32)], d)
        sub.submit(Admitted(), envelope())
        msg = expect(NotReconcilable, sub.reconcile, OP_HEX, PAYLOAD_HEX, Chain(EMPTY))
        assert "still be in flight" in msg, msg


@test("C4: a definitively refused send reconciles to FAILED without chain consumption")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = sub_rig([response({"message": "nope"}, 422)], d)
        s = sub.submit(Admitted(), envelope())
        assert s.journal_state is OperationState.FAILED
        assert sub.reconcile(OP_HEX, PAYLOAD_HEX, Chain(EMPTY)) is OperationState.FAILED


@test("C4: without a chain reader there is no verdict at all")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = sub_rig([accepted()], d)
        sub.submit(Admitted(), envelope())
        msg = expect(NotReconcilable, sub.reconcile, OP_HEX, PAYLOAD_HEX, None)
        assert "not a substitute" in msg, msg


# --------------------------------------------------------------- state mapping --
@test("a CONFIRMED operation is never re-executed")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = sub_rig([accepted()], d)
        sub.submit(Admitted(), envelope())
        sub.reconcile(OP_HEX, PAYLOAD_HEX, Chain(PAYLOAD_HEX))
        assert j.get(OP_HEX).state is OperationState.CONFIRMED
        msg = expect(SubmissionError, sub.submit, Admitted(), envelope(epoch=3))
        assert "never re-execute" in msg, msg


@test("REJECTED becomes FAILED, which permits reauthorizing the SAME id and payload")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = sub_rig([response({"message": "bad"}, 400), accepted("exec-2")], d)
        s = sub.submit(Admitted(), envelope())
        assert s.journal_state is OperationState.FAILED
        s2 = sub.submit(Admitted(), envelope(epoch=2))
        assert s2.journal_state is OperationState.DISPATCHED
        assert j.get(OP_HEX).payload_hash == PAYLOAD_HEX, "the payload binding held"


@test("the submission record is loggable and carries no secrets")
def _():
    with tempfile.TemporaryDirectory() as d:
        j, t, sub = sub_rig([accepted()], d)
        rec = sub.submit(Admitted(), envelope()).to_record()
        blob = json.dumps(rec)
        assert RUNNER_KEY not in blob and "kh_local" not in blob
        assert rec["hosted"] is False, "a local submission must not look hosted"
        assert rec["journal_state"] == "DISPATCHED"
        assert rec["idempotency_key"].startswith("0x")


def main() -> int:
    for v in (API_ENV, "HELD_RUNNER_KEY"):
        os.environ.pop(v, None)
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"P03 submit: FAIL ({len(FAILED)}/{len(PASSED)+len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} P03 submission binding/reconciliation tests held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
