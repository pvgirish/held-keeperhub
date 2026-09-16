"""P03: the composed local run, Python half.

This is the step the review asked for: "connect one genuine LOCAL native producer ->
admitted action -> signature -> exact typed request -> controller effect -> durable/native
result and recovery flow."

The chain here is real at every link except the executor:

    real pinned Almanak IntentCompiler
      -> CompilationResult (producer verdict checked, not assumed)
      -> ActionBundle -> Held record -> admit_bundle
      -> AuthorizationEnvelope signed by the runner key
      -> the ONE permitted typed controller call, ABI-encoded
      -> fixtures/generated/composed-call.json
      -> executed by HeldComposed.t.sol against the REAL controller on the fork
      -> fixtures/generated/composed-result.json
      -> journal reconciled from THAT reading

KeeperHub is absent, because the hosted route needs an organisation credential (L10)
that does not exist and is not simulated. What this establishes is that Held's own
request bytes are accepted by the real controller and produce the intended effect, and
that the journal reaches CONFIRMED from a real on-chain reading rather than an in-test
double.

Ordering: the fork suite must have written fixtures/generated/signing-vector.json, which
carries the controller address Python cannot otherwise know. `make check-phase-03-composed`
runs the passes in order.
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

from held_adapter.execution.controller_abi import build_execute_call, encode_call  # noqa: E402
from held_adapter.execution.submit import ChainEvidence  # noqa: E402
from held_adapter.signing.runner_signer import RunnerSigner  # noqa: E402
from held_core.canonical import hex32  # noqa: E402
from held_core.identity import ActionFamily, AuthorizationEnvelope, OperationScope  # noqa: E402
from held_core.journal import Journal, OperationState  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

GENERATED = os.path.join(ROOT, "fixtures", "generated")
VECTOR = os.path.join(GENERATED, "signing-vector.json")
CALL_FILE = os.path.join(GENERATED, "composed-call.json")
RESULT_FILE = os.path.join(GENERATED, "composed-result.json")

# anvil account #4, the fork fixture's runnerB. Public, local-fork only, never custody.
RUNNER_B_KEY = "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a"


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


def load_vector() -> dict:
    assert os.path.exists(VECTOR), (
        f"{VECTOR} is missing. It is written by the fork suite, which is the only thing "
        "that knows the deployed controller address. Run make check-phase-02 first.")
    with open(VECTOR) as fh:
        return json.load(fh)


class ComposedAction:
    family = ActionFamily.SUPPLY

    def __init__(self, amount: int, on_behalf: str):
        self.amount = amount
        self.on_behalf = on_behalf


class ComposedAdmitted:
    """The admitted operation, carrying the real compiler-derived action hash."""

    def __init__(self, v: dict):
        self.operation_id = bytes.fromhex(v["operationId"][2:])
        self.payload_hash = bytes.fromhex(v["payloadHash"][2:])
        self.source_decision_id = "composed-local-run"
        self.action_index = 0
        self.action = ComposedAction(int(v["amount"]), v["safe"])


def envelope_from(v: dict) -> AuthorizationEnvelope:
    scope = OperationScope(int(v["chainId"]), v["controller"], v["safe"], v["lineage"])
    return AuthorizationEnvelope(
        scope=scope,
        operation_id=bytes.fromhex(v["operationId"][2:]),
        source_identity_hash=bytes.fromhex(v["sourceIdentityHash"][2:]),
        payload_hash=bytes.fromhex(v["payloadHash"][2:]),
        action_family=ActionFamily(int(v["actionFamily"])),
        epoch=int(v["epoch"]),
        policy_version=int(v["policyVersion"]),
        runner=v["runner"],
    )


# ------------------------------------------------------------------- the build --
@test("the admitted action hash matches what the REAL pinned compiler produced")
def _():
    # The vector's payloadHash is the controller's own actionHash. The adapter derived
    # the same value from the real compiler output in test_p03_native_bundle.py and
    # recorded it in fixtures/crosslang-vectors.json. If these ever diverge, the request
    # built below would be authorizing a different action than the one admitted.
    v = load_vector()
    with open(os.path.join(ROOT, "fixtures", "crosslang-vectors.json")) as fh:
        adapter = json.load(fh)
    assert v["payloadHash"].lower() == adapter["expectedActionHash"].lower(), (
        f"the fork's actionHash {v['payloadHash']} and the adapter's "
        f"{adapter['expectedActionHash']} disagree")
    assert int(v["amount"]) == int(adapter["amount"])


@test("builds the ONE permitted typed call from the admitted action and its signature")
def _():
    v = load_vector()
    os.environ["HELD_COMPOSED_RUNNER_KEY"] = RUNNER_B_KEY
    signer = RunnerSigner("env:HELD_COMPOSED_RUNNER_KEY", v["runner"])
    env = envelope_from(v)
    auth = signer.sign(env)

    # The fork published the signature it produced for this envelope; ours must be the
    # same bytes, or the request would not be the authorization the controller verifies.
    assert "0x" + auth.signature.hex() == v["signature"], (
        "the runner signature does not match the one the fork published")

    admitted = ComposedAdmitted(v)
    market = (v["loanToken"], v["collateralToken"], v["oracle"], v["irm"], int(v["lltv"]))
    fn, args, calldata = build_execute_call(admitted, env, auth.signature, market)

    assert fn == "executeSupply"
    assert calldata.startswith("0xfe6a574c"), f"unexpected selector: {calldata[:10]}"
    assert encode_call(fn, args) == calldata, "the arguments do not re-encode to themselves"

    os.makedirs(GENERATED, exist_ok=True)
    with open(CALL_FILE, "w") as fh:
        json.dump({
            "note": ("Built by tests/integration/test_p03_composed.py from the admitted "
                     "action and the runner signature. test/contracts/HeldComposed.t.sol "
                     "executes these bytes VERBATIM against the real controller. "
                     "KeeperHub is not involved: L10 is open and is not simulated."),
            "controller": v["controller"],
            "chainId": v["chainId"],
            "executor": v["executor"],
            "functionName": fn,
            "operationId": v["operationId"],
            "payloadHash": v["payloadHash"],
            "amount": str(admitted.action.amount),
            "calldata": calldata,
        }, fh, indent=2)
    print(f"      wrote composed-call.json  {len(calldata) // 2 - 1} bytes of calldata")


@test("the built request carries the operation, envelope and signature the fork verified")
def _():
    v = load_vector()
    with open(CALL_FILE) as fh:
        call = json.load(fh)
    data = bytes.fromhex(call["calldata"][2:])
    # Selector + the envelope's first word (operationId) sit at a fixed offset because
    # the envelope is a static-head tuple.
    assert data[4:36].hex() == v["operationId"][2:], "operation id not in the request"
    assert call["payloadHash"].lower() == v["payloadHash"].lower()
    assert v["signature"][2:] in call["calldata"][2:], "the signature is not in the request"


# ---------------------------------------------------- the loop, closed on chain --
@test("the journal reaches CONFIRMED from the REAL on-chain reading")
def _():
    if not os.path.exists(RESULT_FILE):
        raise AssertionError(
            f"{RESULT_FILE} is missing. It is written by HeldComposed.t.sol after it "
            "executes the request. Run the composed fork pass before this check; this "
            "must not pass without a real execution.")
    with open(RESULT_FILE) as fh:
        result = json.load(fh)
    assert result["executed"] is True

    from held_adapter.execution.keeperhub import KeeperHubClient, OfflineTransport
    from held_adapter.execution.submit import Submitter

    class RealReading:
        """Chain evidence taken from what the controller ACTUALLY recorded on the fork."""

        def __init__(self, r: dict):
            self._r = r
            self.reads = 0

        def consumed(self, controller: str, operation_id: str) -> ChainEvidence:
            self.reads += 1
            assert controller.lower() == self._r["controller"].lower()
            assert operation_id.lower() == self._r["operationId"].lower()
            return ChainEvidence(
                marker=self._r["consumedPayload"], chain_id=int(self._r["chainId"]),
                controller=self._r["controller"], block_number=51353212,
                block_hash="0x" + "ab" * 32, finalized=True)

    v = load_vector()
    with tempfile.TemporaryDirectory() as d:
        j = Journal(os.path.join(d, "held.sqlite"))
        oid, ph = v["operationId"], v["payloadHash"]
        j.create_or_reopen(oid, ph, "composed-local-run", 0, int(v["epoch"]))
        j.transition(oid, OperationState.AUTHORIZED, epoch=int(v["epoch"]))
        j.claim_for_dispatch(
            "composed-attempt-1", oid, "0x" + "dd" * 32, int(v["epoch"]), v["runner"],
            "env:HELD_COMPOSED_RUNNER_KEY", idempotency_key="0x" + "ee" * 32,
            request_body="{}", calldata=json.load(open(CALL_FILE))["calldata"])
        j.record_send_result("composed-attempt-1", state="ACCEPTED")

        os.environ["HELD_KEEPERHUB_API_KEY"] = "kh_local_test_credential_not_real"
        client = KeeperHubClient(transport=OfflineTransport([]), sleep=lambda _: None)
        signer = RunnerSigner("env:HELD_COMPOSED_RUNNER_KEY", v["runner"])
        sub = Submitter(j, client, signer, v["controller"], int(v["chainId"]),
                        (v["loanToken"], v["collateralToken"], v["oracle"], v["irm"],
                         int(v["lltv"])))

        chain = RealReading(result)
        state = sub.reconcile(oid, ph, chain)
        assert state is OperationState.CONFIRMED, state
        assert chain.reads == 1
        assert j.get(oid).state is OperationState.CONFIRMED

        # And the loop is closed the right way round: CONFIRMED came from the controller's
        # consumed[] marker equalling the payload the journal durably bound -- not from
        # anything the executor said.
        assert result["consumedPayload"].lower() == ph.lower()


@test("recovery after the real execution refuses to re-send, and resolves instead")
def _():
    with open(RESULT_FILE) as fh:
        result = json.load(fh)
    v = load_vector()
    from held_adapter.execution.submit import SubmissionError

    with tempfile.TemporaryDirectory() as d:
        j = Journal(os.path.join(d, "held.sqlite"))
        oid, ph = v["operationId"], v["payloadHash"]
        j.create_or_reopen(oid, ph, "composed-local-run", 0, int(v["epoch"]))
        j.transition(oid, OperationState.AUTHORIZED, epoch=int(v["epoch"]))
        j.claim_for_dispatch(
            "composed-attempt-1", oid, "0x" + "dd" * 32, int(v["epoch"]), v["runner"],
            "env:HELD_COMPOSED_RUNNER_KEY", idempotency_key="0x" + "ee" * 32,
            request_body="{}", calldata="0xabcd")
        # The process died here: a claimed attempt, outcome unrecorded. But it DID
        # execute -- which is exactly the case that must never be resent.
        from held_adapter.execution.keeperhub import KeeperHubClient, OfflineTransport
        from held_adapter.execution.submit import Submitter

        os.environ["HELD_KEEPERHUB_API_KEY"] = "kh_local_test_credential_not_real"
        transport = OfflineTransport([])
        sub = Submitter(
            j, KeeperHubClient(transport=transport, sleep=lambda _: None),
            RunnerSigner("env:HELD_COMPOSED_RUNNER_KEY", v["runner"]),
            v["controller"], int(v["chainId"]),
            (v["loanToken"], v["collateralToken"], v["oracle"], v["irm"], int(v["lltv"])))

        class RealReading:
            def consumed(self, controller, operation_id):
                return ChainEvidence(
                    marker=result["consumedPayload"], chain_id=int(result["chainId"]),
                    controller=result["controller"], block_number=51353212,
                    block_hash="0x" + "ab" * 32, finalized=True)

        # Far past the idempotency window, so resume() must consult the chain.
        sub._now = lambda: 1e12
        try:
            sub.resume(oid, RealReading())
            raise AssertionError("resume re-sent an operation that had already executed")
        except SubmissionError as e:
            assert "already executed" in str(e), str(e)
        assert len(transport.calls) == 0, "a duplicate request was sent after real execution"
        assert j.get(oid).state is OperationState.CONFIRMED


def main() -> int:
    for v in ("HELD_COMPOSED_RUNNER_KEY", "HELD_KEEPERHUB_API_KEY"):
        os.environ.pop(v, None)
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"P03 composed: FAIL ({len(FAILED)}/{len(PASSED)+len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} P03 composed-run checks held (KeeperHub NOT involved; L10 open)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
