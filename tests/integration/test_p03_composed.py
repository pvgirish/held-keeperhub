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

from held_adapter.execution.keeperhub import (  # noqa: E402
    KeeperHubClient,
    OfflineTransport,
    SendOutcome,
)
from held_adapter.execution.native_boundary import admit_native_bundle  # noqa: E402
from held_adapter.execution.submit import (  # noqa: E402
    ChainEvidence,
    ResumeRequired,
    SubmissionError,
    Submitter,
)
from held_adapter.signing.runner_signer import RunnerSigner  # noqa: E402
from held_core import results as R  # noqa: E402
from eth_utils import keccak  # noqa: E402

from held_core.canonical import hex32  # noqa: E402
from held_core.identity import ActionFamily, AuthorizationEnvelope, OperationScope  # noqa: E402
from held_core.journal import Journal, OperationState  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

GENERATED = os.path.join(ROOT, "fixtures", "generated")
VECTOR = os.path.join(GENERATED, "signing-vector.json")
CALL_FILE = os.path.join(GENERATED, "composed-call.json")
RESULT_FILE = os.path.join(GENERATED, "composed-result.json")
# ONE journal for the whole composed run, so the claim made before the request and the
# reconciliation afterwards are the same operation in the same database.
JOURNAL_PATH = os.path.join(GENERATED, "composed-journal.sqlite")

ADMITTED = None
NATIVE_CALLS = None
BUILT = None


class ForkReading:
    """Chain evidence taken from what the controller ACTUALLY recorded on the fork.

    LABELLING, because this is exactly where invented metadata would hide: `marker`,
    `controller`, `chainId` and `usedSupply` are READ from the executing fork test.
    `block_hash` and `finalized` are NOT observed -- an anvil fork has no meaningful
    finality, so they are stated fixture values and this run must not be described as
    carrying finalized-chain provenance. `controller_epoch` is the epoch the composed
    fork test activated.
    """

    OBSERVED = ("marker", "chain_id", "controller")
    SYNTHETIC = ("block_hash", "finalized", "block_number")

    def __init__(self, result: dict, controller_epoch: int = 1):
        self._r = result
        self._epoch = controller_epoch
        self.reads = 0

    def consumed(self, controller: str, operation_id: str) -> ChainEvidence:
        self.reads += 1
        assert controller.lower() == self._r["controller"].lower()
        assert operation_id.lower() == self._r["operationId"].lower()
        return ChainEvidence(
            marker=self._r["consumedPayload"],          # observed
            chain_id=int(self._r["chainId"]),           # observed
            controller=self._r["controller"],           # observed
            block_number=51353212,                      # SYNTHETIC (fork pin)
            block_hash="0x" + "ab" * 32,                # SYNTHETIC, not an observed hash
            finalized=True,                             # SYNTHETIC: a fork has no finality
            controller_epoch=self._epoch)

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


def envelope_for(v: dict, admitted) -> AuthorizationEnvelope:
    """Held's OWN envelope for the admitted action.

    Only the CONTROLLER ADDRESS is taken from the fork -- Python cannot know it before
    deployment, and the EIP-712 domain separator commits to it. Everything else comes
    from the adapter: the operation id the compiler's decision produced, and the payload
    hash derived from the compiler's own output.

    An earlier version reused the fork's whole published envelope, whose operation id was
    keccak("xlang-sign") -- a fork test fixture, not an admitted operation. That made the
    "composed" run execute an id the adapter had never minted.
    """
    scope = OperationScope(int(v["chainId"]), v["controller"], v["safe"], v["lineage"])
    return AuthorizationEnvelope(
        scope=scope,
        operation_id=bytes(admitted.operation_id),
        source_identity_hash=keccak(admitted.source_decision_id.encode()),
        payload_hash=bytes(admitted.payload_hash),
        action_family=admitted.action.family,
        epoch=1,           # the epoch the composed fork pass activates
        policy_version=1,
        runner=v["runner"],
    )


# ------------------------------------------------------------------- the build --
@test("the REAL pinned compiler produces the action this run admits")
def _():
    """No pre-baked vector: the compiler actually runs here."""
    global ADMITTED, NATIVE_CALLS
    sys.path.insert(0, HERE)
    from test_p03_native_bundle import PROFILE, compile_real_supply, context

    result = compile_real_supply()
    record, admitted = admit_native_bundle(result, context(), PROFILE)
    ADMITTED, NATIVE_CALLS = admitted, record.calls

    assert record.intent_type == "SUPPLY"
    assert admitted.action.amount == 100_000_000, admitted.action.amount
    # The fork's vector describes the same economic action (100 USDC supply by the same
    # Safe into the same market), so its payload hash must equal the one the adapter
    # derived from the compiler. If these diverge, Python and Solidity disagree about
    # what the action IS, before any encoding question arises.
    v = load_vector()
    assert hex32(admitted.payload_hash).lower() == v["payloadHash"].lower(), (
        "the compiler-derived action hash and the fork's actionHash disagree")
    print(f"      compiler produced {len(record.calls)} native call(s), "
          f"action hash {hex32(admitted.payload_hash)[:18]}...")


@test("the REAL Submitter claims, builds and persists the request before any I/O")
def _():
    """The actual pre-I/O journal path, not a hand-built row.

    The earlier version of this file created a temporary journal with placeholder request
    metadata after the fact. That tested reconcile() but skipped the thing the phase is
    about: the durable claim that happens BEFORE the request leaves.
    """
    global BUILT
    v = load_vector()
    os.environ["HELD_COMPOSED_RUNNER_KEY"] = RUNNER_B_KEY
    os.environ["HELD_KEEPERHUB_API_KEY"] = "kh_local_test_credential_not_real"

    env = envelope_for(v, ADMITTED)
    market = (v["loanToken"], v["collateralToken"], v["oracle"], v["irm"], int(v["lltv"]))

    class CaptureTransport:
        """Captures the request at the moment it would leave, and refuses to send it.

        KeeperHub is not called: L10 is open. The point is to observe what the REAL
        Submitter built and what it had already committed by then.
        """

        hosted = False

        def __init__(self):
            self.captured = None
            self.journal_at_send = None

        def request(self, method, url, *, headers, body, timeout):
            self.captured = {"headers": dict(headers), "body": json.loads(body)}
            probe = Journal(JOURNAL_PATH)
            op = probe.get(hex32(ADMITTED.operation_id))
            self.journal_at_send = {
                "state": op.state.value,
                "attempt": probe.unresolved_attempt(hex32(ADMITTED.operation_id)),
            }
            probe.close()
            raise TimeoutError("deliberately not delivered: L10 is open")

    journal = Journal(JOURNAL_PATH)
    oid = hex32(ADMITTED.operation_id)
    existing = journal.unresolved_attempt(oid)

    if existing is None:
        # Build phase: the Submitter runs for real and the transport captures what it
        # had already committed at the moment the request would have left.
        transport = CaptureTransport()
        sub = Submitter(
            journal, KeeperHubClient(transport=transport, sleep=lambda _: None),
            RunnerSigner("env:HELD_COMPOSED_RUNNER_KEY", v["runner"]),
            v["controller"], int(v["chainId"]), market,
            new_attempt_id=lambda: "composed-attempt-1")

        submission = sub.submit(ADMITTED, env)
        assert submission.send.outcome is SendOutcome.UNKNOWN, (
            "the capture transport did not refuse")

        at_send = transport.journal_at_send
        assert at_send["state"] == "DISPATCHED", (
            f"at send time the durable state was {at_send['state']}, not DISPATCHED")
        assert at_send["attempt"] is not None, "nothing was persisted before the send"
        persisted = at_send["attempt"]
        assert persisted["idempotency_key"] == submission.execution_key
        assert persisted["calldata"].startswith("0xfe6a574c")

        body = transport.captured["body"]
        assert body["functionName"] == "executeSupply"
        assert transport.captured["headers"]["Idempotency-Key"] == submission.execution_key
    else:
        # Verify phase (the second invocation, after the fork executed): the claim from
        # the build phase must still be intact and must still describe this request.
        # Re-claiming here would be wrong -- and the Submitter correctly refuses it.
        persisted = existing
        # The build phase's capture transport refused to deliver, which is an AMBIGUOUS
        # send, so the operation is UNKNOWN rather than DISPATCHED. Both are live and
        # unsettled; the distinction is whether the send returned at all.
        state = journal.get(oid).state
        assert state in (OperationState.DISPATCHED, OperationState.UNKNOWN), state
        assert persisted["state"] in ("PENDING", "UNKNOWN"), persisted["state"]
        assert persisted["idempotency_key"].startswith("0x")
        assert persisted["calldata"].startswith("0xfe6a574c")
        with open(CALL_FILE) as fh:
            assert json.load(fh)["calldata"] == persisted["calldata"], (
                "the persisted claim no longer matches the request that was executed")
        try:
            Submitter(
                journal, KeeperHubClient(transport=OfflineTransport([]), sleep=lambda _: None),
                RunnerSigner("env:HELD_COMPOSED_RUNNER_KEY", v["runner"]),
                v["controller"], int(v["chainId"]), market).submit(ADMITTED, env)
            raise AssertionError("a second claim was allowed on a live operation")
        except ResumeRequired:
            pass

    BUILT = {"calldata": persisted["calldata"], "attempt": persisted["attempt_id"]}

    if existing is None:
        # Written ONCE, by the build phase. The verify phase must never rewrite it: the
        # fork executed these exact bytes, and regenerating them would quietly replace
        # the artifact the evidence refers to.
        os.makedirs(GENERATED, exist_ok=True)
        with open(CALL_FILE, "w") as fh:
            json.dump({
                "note": ("Built by the REAL Submitter from the REAL compiler output, "
                         "captured at the moment it would have been sent. KeeperHub was "
                         "NOT called: L10 is open and is not simulated. "
                         "HeldComposed.t.sol executes these bytes verbatim against the "
                         "real controller."),
                "controller": v["controller"],
                "chainId": v["chainId"],
                "executor": v["executor"],
                "functionName": "executeSupply",
                "operationId": hex32(ADMITTED.operation_id),
                "payloadHash": hex32(ADMITTED.payload_hash),
                "amount": str(ADMITTED.action.amount),
                "calldata": persisted["calldata"],
            }, fh, indent=2)
        print(f"      wrote composed-call.json  {len(persisted['calldata']) // 2 - 1} bytes")
    else:
        print(f"      verified the existing claim {persisted['attempt_id']} "
              f"({persisted['state']})")
    journal.close()


@test("the built request carries the operation, envelope and signature the fork verified")
def _():
    v = load_vector()
    with open(CALL_FILE) as fh:
        call = json.load(fh)
    data = bytes.fromhex(call["calldata"][2:])
    assert data[4:36].hex() == call["operationId"][2:], "operation id not in the request"
    assert call["payloadHash"].lower() == v["payloadHash"].lower()
    # The signature is the adapter's own, over its own envelope; recover it rather than
    # comparing to the fork's fixture signature for a different operation id.
    # ABI-decode it: `bytes` is padded to a 32-byte boundary, so slicing the tail would
    # pick up padding.
    from eth_abi import decode as abi_decode
    from eth_account import Account
    from held_adapter.execution.controller_abi import ENVELOPE_TYPE, MARKET_PARAMS_TYPE

    _, _, _, sig = abi_decode(
        [ENVELOPE_TYPE, MARKET_PARAMS_TYPE, "uint256", "bytes"], data[4:])
    assert len(sig) == 65, f"expected a 65-byte signature, decoded {len(sig)}"
    env = envelope_for(v, ADMITTED)
    assert Account._recover_hash(env.signing_hash(), signature=sig).lower() == v["runner"].lower(), (
        "the signature in the request does not recover to the runner over this envelope")


# ---------------------------------------------------- the loop, closed on chain --
@test("the SAME journal reaches CONFIRMED from the REAL on-chain reading")
def _():
    """Continues the journal the Submitter actually claimed in, not a fresh one."""
    if not os.path.exists(RESULT_FILE):
        raise AssertionError(
            f"{RESULT_FILE} is missing. It is written by HeldComposed.t.sol after it "
            "executes the request. Run the composed fork pass before this check; this "
            "must not pass without a real execution.")
    with open(RESULT_FILE) as fh:
        result = json.load(fh)
    assert result["executed"] is True

    v = load_vector()
    journal = Journal(JOURNAL_PATH)
    oid = result["operationId"]
    op = journal.get(oid)
    assert op is not None, "the composed submission did not leave a journal row"
    assert journal.unresolved_attempt(oid) is not None, (
        "the claim from the capture pass is gone; reconciliation would not be continuing "
        "the same operation")

    market = (v["loanToken"], v["collateralToken"], v["oracle"], v["irm"], int(v["lltv"]))
    os.environ["HELD_KEEPERHUB_API_KEY"] = "kh_local_test_credential_not_real"
    sub = Submitter(
        journal, KeeperHubClient(transport=OfflineTransport([]), sleep=lambda _: None),
        RunnerSigner("env:HELD_COMPOSED_RUNNER_KEY", v["runner"]),
        result["controller"], int(result["chainId"]), market)

    chain = ForkReading(result)
    state = sub.reconcile(oid, op.payload_hash, chain)
    assert state is OperationState.CONFIRMED, state
    assert chain.reads == 1
    assert journal.get(oid).state is OperationState.CONFIRMED
    # CONFIRMED came from the controller's own marker equalling the journal's durable
    # binding -- not from anything an executor said.
    assert result["consumedPayload"].lower() == op.payload_hash.lower()
    journal.close()


@test("the native result is delivered and acknowledged in ONE commit, idempotently")
def _():
    """The native result/ack boundary, closed locally.

    V4 §4: at-least-once delivery with an idempotent consumer acknowledgement, where the
    ack is written in the SAME transaction as the consumer's own state update. The
    consumer here is a LOCAL harness standing in for a native strategy's result sink --
    labelled as such. What it exercises is the commit boundary, which is the part that
    can be wrong.
    """
    with open(RESULT_FILE) as fh:
        result = json.load(fh)
    journal = Journal(JOURNAL_PATH)
    oid = result["operationId"]

    applied: list[str] = []

    class LocalConsumer:
        """Stands in for the native result sink. NOT the Almanak consumer."""

        def apply(self, conn, operation_id, result_hash, payload):
            # Enrols in the journal's transaction; no network, nothing unrollbackable.
            conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                (f"native_result:{operation_id}", result_hash))
            applied.append(operation_id)
            return "CONSUMED"

    result_hash = result["consumedPayload"]
    first = R.deliver(journal, oid, result_hash, json.dumps(result), LocalConsumer())
    assert first is R.DeliveryOutcome.APPLIED, first
    assert applied == [oid]

    # At-least-once: the same result arriving again is a no-op, not a second state change.
    second = R.deliver(journal, oid, result_hash, json.dumps(result), LocalConsumer())
    assert second is R.DeliveryOutcome.DUPLICATE, second
    assert applied == [oid], "a duplicate delivery moved consumer state a second time"

    # A DIFFERENT result for an already-acknowledged operation is a conflict, not an
    # overwrite.
    try:
        R.deliver(journal, oid, "0x" + "99" * 32, "{}", LocalConsumer())
        raise AssertionError("a conflicting result was accepted")
    except R.ResultConflict:
        pass
    journal.close()


@test("recovery after the real execution refuses to re-send, and resolves instead")
def _():
    with open(RESULT_FILE) as fh:
        result = json.load(fh)
    v = load_vector()
    oid = result["operationId"]

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "held.sqlite")
        journal = Journal(path)
        journal.create_or_reopen(oid, result["consumedPayload"], "composed-local-run", 0,
                                 int(v["epoch"]))
        journal.transition(oid, OperationState.AUTHORIZED, epoch=int(v["epoch"]))
        journal.claim_for_dispatch(
            "composed-attempt-1", oid, "0x" + "dd" * 32, int(v["epoch"]), v["runner"],
            "env:HELD_COMPOSED_RUNNER_KEY", idempotency_key="0x" + "ee" * 32,
            request_body="{}", calldata="0xabcd")

        os.environ["HELD_KEEPERHUB_API_KEY"] = "kh_local_test_credential_not_real"
        transport = OfflineTransport([])
        market = (v["loanToken"], v["collateralToken"], v["oracle"], v["irm"], int(v["lltv"]))
        sub = Submitter(
            journal, KeeperHubClient(transport=transport, sleep=lambda _: None),
            RunnerSigner("env:HELD_COMPOSED_RUNNER_KEY", v["runner"]),
            result["controller"], int(result["chainId"]), market)
        sub._now = lambda: 1e12  # far past the idempotency window

        try:
            sub.resume(oid, ForkReading(result))
            raise AssertionError("resume re-sent an operation that had already executed")
        except SubmissionError as e:
            assert "already executed" in str(e), str(e)
        assert len(transport.calls) == 0, "a duplicate request was sent after real execution"
        assert journal.get(oid).state is OperationState.CONFIRMED
        journal.close()


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
