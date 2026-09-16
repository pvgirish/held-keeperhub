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
from held_adapter.execution.interceptor import Profile  # noqa: E402
from held_adapter.execution.native_result import (  # noqa: E402
    NativeAcknowledgementError,
    NativeStateMachineConsumer,
    NativeStateNotAuthoritative,
    bind_native_decision,
    bound_native_decision,
    native_ack_state,
    native_state_after,
    restore,
)
from held_adapter.execution.native_boundary import (  # noqa: E402
    ExecutionContext,
    admit_native_bundle,
)
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
from held_core.identity import (  # noqa: E402
    ActionFamily,
    AuthorizationEnvelope,
    OperationScope,
    operation_id,
)
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
PROFILE = None
NATIVE_MACHINE = None
SOURCE_DECISION_ID = "composed-local-run"
MORPHO = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"


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
    """Held's OWN envelope for the admitted action, in the SAME scope it was admitted in.

    The scope comes from the single deployment profile, so the envelope and the operation
    id cannot disagree. The Submitter re-derives and checks this before signing.
    """
    scope = PROFILE.scope()
    return AuthorizationEnvelope(
        scope=scope,
        operation_id=bytes(admitted.operation_id),
        source_identity_hash=keccak(SOURCE_DECISION_ID.encode()),
        payload_hash=bytes(admitted.payload_hash),
        action_family=admitted.action.family,
        epoch=1,           # the epoch the composed fork pass activates
        policy_version=1,
        runner=v["runner"],
    )


# ------------------------------------------------------------------- the build --
def deployment_profile(v: dict) -> Profile:
    """ONE profile, built from the VERIFIED DEPLOYMENT CONTEXT, before admission.

    This is the repair for a real connection error. The composed run used to admit
    against the native-bundle test's PROFILE -- controller 0x3875311c..., lineage
    0x1111... -- and then sign an envelope scoped to the DEPLOYED controller
    0x5615dEB7... with lineage 0x...0011. Since operation_id() binds chain, controller,
    Safe and lineage, the admitted id was never minted for the deployment it was signed
    for. The controller accepts such a signature happily; Held's own business identity is
    simply wrong.

    So the deployment context is obtained FIRST and one profile is used throughout:
    operation-id derivation, signing, request targeting, journaling and reconciliation.
    """
    return Profile(
        chain_id=int(v["chainId"]),
        controller=v["controller"],
        safe=v["safe"],
        lineage=v["lineage"],
        morpho=MORPHO,
        token=v["loanToken"],
        market_params=(v["loanToken"], v["collateralToken"], v["oracle"], v["irm"],
                       int(v["lltv"])),
    )


@test("the REAL pinned compiler produces the action this run admits, in ONE scope")
def _():
    """No pre-baked vector, and no borrowed profile: both come from this deployment."""
    global ADMITTED, NATIVE_CALLS, PROFILE
    sys.path.insert(0, HERE)
    from test_p03_native_bundle import compile_real_supply

    v = load_vector()
    PROFILE = deployment_profile(v)
    ctx = ExecutionContext(
        chain_id=PROFILE.chain_id, safe=PROFILE.safe,
        source_decision_id=SOURCE_DECISION_ID, action_index=0)

    result = compile_real_supply()
    record, admitted = admit_native_bundle(result, ctx, PROFILE)
    ADMITTED, NATIVE_CALLS = admitted, record.calls

    # The admitted id must derive from THIS deployment's scope, not from any other.
    assert bytes(admitted.operation_id) == operation_id(
        PROFILE.scope(), SOURCE_DECISION_ID, 0), "the admitted id is not scope-derived"
    assert PROFILE.controller == v["controller"].lower()
    assert PROFILE.lineage == v["lineage"].lower()

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


def _receipt() -> str:
    # LABEL: tx_hash is a fixture value -- the fork does not surface a transaction hash
    # to this process. The ECONOMIC effect is what was verified, in composed-result.json.
    return json.dumps({"success": True, "tx_hash": "0x" + "ef" * 32,
                       "block_number": 51353228, "gas_used": 210000})


def native_state_machine(v: dict):
    """The REAL pinned IntentStateMachine for this run's intent."""
    from decimal import Decimal

    from almanak.framework.intents import SupplyIntent
    from almanak.framework.intents.compiler import IntentCompiler
    from almanak.framework.intents.state_machine import IntentStateMachine

    kwargs = dict(chain="base", wallet_address=v["safe"], default_protocol="morpho_blue",
                  rpc_url=os.environ.get("HELD_BASE_RPC"), rpc_timeout=30.0)
    if os.environ.get("HELD_PRICE_MODE") == "testing-only":
        kwargs["price_oracle"] = {"USDC": Decimal("1")}  # TESTING-ONLY, never runtime evidence
    intent = SupplyIntent(protocol="morpho_blue", chain="base", token="USDC",
                          amount=Decimal("100"),
                          market_id=hex32(PROFILE.market_id()), use_as_collateral=False)
    return IntentStateMachine(intent, IntentCompiler(**kwargs))


@test("the producing native decision is BOUND to the composed operation")
def _():
    """Which decision produced this operation, recorded durably at admission time.

    Without the binding, an acknowledgement could be applied to any machine that happens
    to be in the right state, and a restart could not identify the original decision --
    only reconstruct one by coincidence.
    """
    global NATIVE_MACHINE
    v = load_vector()
    NATIVE_MACHINE = native_state_machine(v)
    step = NATIVE_MACHINE.step()
    assert step.needs_execution and step.action_bundle is not None, (
        f"the machine is not offering work to execute (state {NATIVE_MACHINE.state})")

    journal = Journal(JOURNAL_PATH)
    oid = hex32(ADMITTED.operation_id)
    bind_native_decision(journal, oid, NATIVE_MACHINE.intent.intent_id,
                         NATIVE_MACHINE.intent.intent_type.value)
    bound = bound_native_decision(journal, oid)
    assert bound["intent_id"] == NATIVE_MACHINE.intent.intent_id
    assert bound["intent_type"] == "SUPPLY"
    journal.close()


@test("RESTART: a completed native decision is restored and does NOT ask for execution")
def _():
    """The pinned machine has no from_dict, so the snapshot has to be the authority.

    A fresh process that simply rebuilt an IntentStateMachine would get one in
    VALIDATING_* reporting needs_execution=True -- for work that is finished. restore()
    consults the durable snapshot first and refuses to let a rebuilt machine override it.
    """
    with open(RESULT_FILE) as fh:
        result = json.load(fh)
    v = load_vector()

    with tempfile.TemporaryDirectory() as d:
        journal = Journal(os.path.join(d, "restart.sqlite"))
        oid = result["operationId"]
        journal.create_or_reopen(oid, result["consumedPayload"], SOURCE_DECISION_ID, 0, 1)

        machine = native_state_machine(v)
        consumer = NativeStateMachineConsumer(machine)
        consumer.needs_execution()
        bind_native_decision(journal, oid, machine.intent.intent_id,
                             machine.intent.intent_type.value)
        R.deliver(journal, oid, result["consumedPayload"], _receipt(), consumer)
        assert consumer.verify_committed(journal, oid) is True
        journal.close()

        # --- a NEW process: nothing in memory survives, only the database.
        del machine, consumer
        reopened = Journal(os.path.join(d, "restart.sqlite"))
        rebuilt = []

        def build():
            rebuilt.append(1)
            return native_state_machine(v)

        decision = restore(reopened, oid, build_machine=build)
        assert decision.complete is True, f"restored state was {decision.state}"
        assert decision.acked is True
        assert decision.intent_id is not None, "the producing decision was not identified"
        assert decision.needs_execution() is False, (
            "a completed native decision asked to be executed again after restart")
        assert rebuilt == [], (
            "a machine was rebuilt for a COMPLETED decision; the rebuilt one would report "
            "needs_execution=True for finished work")
        reopened.close()


@test("a persistence failure leaves the advanced machine NON-AUTHORITATIVE")
def _():
    """SQL rollback cannot undo an in-memory advance, and the pin offers no way back.

    So the guarantee is not "the machine is restored" -- it cannot be. It is that the
    mutated object refuses to be treated as truth, and that nothing durable survives.
    """
    with open(RESULT_FILE) as fh:
        result = json.load(fh)
    v = load_vector()

    class FailsAfterAdvancing(NativeStateMachineConsumer):
        """Persistence dies AFTER the native machine has advanced.

        Note the ordering in results.deliver(): the results INSERT happens BEFORE
        apply(), so a foreign-key failure never reaches the machine -- that path is
        already safe. The hazard is a failure between the advance and the commit, which
        is what this models.
        """

        def apply(self, conn, operation_id, result_hash, payload):
            state = super().apply(conn, operation_id, result_hash, payload)
            raise RuntimeError(f"persistence died after the machine reached {state}")

    with tempfile.TemporaryDirectory() as d:
        journal = Journal(os.path.join(d, "fail.sqlite"))
        oid = result["operationId"]
        journal.create_or_reopen(oid, result["consumedPayload"], SOURCE_DECISION_ID, 0, 1)
        machine = native_state_machine(v)
        consumer = FailsAfterAdvancing(machine)
        consumer.needs_execution()

        raised = None
        try:
            R.deliver(journal, oid, result["consumedPayload"], _receipt(), consumer)
        except RuntimeError as e:
            raised = e
        assert raised is not None and "after the machine reached" in str(raised)

        # The live object HAS advanced -- that is the honest part.
        assert consumer.state == "COMPLETED", consumer.state
        # ...and nothing durable survived.
        assert native_ack_state(journal, oid) is None
        assert native_state_after(journal, oid) is None
        # ...so it must refuse to be authoritative.
        assert consumer.verify_committed(journal, oid) is False
        assert consumer.authoritative is False
        try:
            consumer.require_authoritative()
            raise AssertionError("a mutated, uncommitted machine passed as authoritative")
        except NativeStateNotAuthoritative as e:
            assert "cannot be moved back" in str(e), str(e)
        journal.close()


@test("the ACTUAL pinned Almanak consumer advances to COMPLETED on Held's result")
def _():
    """P03 required work 4, with the real consumer rather than a model.

    `IntentStateMachine._handle_validating` is explicit: with no receipt it returns
    needs_execution=True and will keep asking to be executed. So "the native consumer
    acknowledged" has a checkable meaning -- it reached COMPLETED and stopped asking.

    The receipt is built from Held's OWN verified on-chain reading, not handed over by a
    gateway; that part is labelled, not claimed.
    """
    with open(RESULT_FILE) as fh:
        result = json.load(fh)
    v = load_vector()

    machine = native_state_machine(v)
    consumer = NativeStateMachineConsumer(machine)

    # Before the result: the native machine is waiting to be executed.
    assert consumer.needs_execution() is True, (
        f"the native machine is not awaiting execution (state {consumer.state})")
    assert consumer.state.startswith("VALIDATING"), consumer.state

    with tempfile.TemporaryDirectory() as d:
        journal = Journal(os.path.join(d, "native.sqlite"))
        oid = result["operationId"]
        journal.create_or_reopen(oid, result["consumedPayload"], SOURCE_DECISION_ID, 0, 1)

        outcome = R.deliver(journal, oid, result["consumedPayload"], _receipt(), consumer)
        assert outcome is R.DeliveryOutcome.APPLIED, outcome

        # The NATIVE state advanced -- this is the acknowledgement, not a Held row.
        assert consumer.state == "COMPLETED", consumer.state
        assert native_ack_state(journal, oid) == "COMPLETED"
        assert native_state_after(journal, oid) is not None, "native state was not persisted"
        assert consumer.verify_committed(journal, oid) is True, (
            "the advance was not confirmed durable")

        # And it has stopped asking to be executed, which is the part that matters:
        # a consumer still requesting execution would have Held resubmit.
        follow_up = machine.step()
        assert follow_up.needs_execution is False, "the native machine still wants execution"
        assert follow_up.is_complete and follow_up.success

        # Redelivery is a no-op at the consumer: at-least-once, applied once.
        again = R.deliver(journal, oid, result["consumedPayload"], _receipt(),
                          NativeStateMachineConsumer(machine))
        assert again is R.DeliveryOutcome.DUPLICATE, again
        journal.close()


@test("a native consumer that refuses the result leaves NO acknowledgement")
def _():
    """The rollback half. An ack the consumer never honoured is the lie to prevent."""
    with open(RESULT_FILE) as fh:
        result = json.load(fh)
    v = load_vector()
    machine = native_state_machine(v)
    consumer = NativeStateMachineConsumer(machine)
    consumer.needs_execution()

    with tempfile.TemporaryDirectory() as d:
        journal = Journal(os.path.join(d, "native-fail.sqlite"))
        oid = result["operationId"]
        journal.create_or_reopen(oid, result["consumedPayload"], SOURCE_DECISION_ID, 0, 1)

        # A FAILED receipt: the native machine goes to sadflow, not COMPLETED.
        bad = json.dumps({"success": False, "tx_hash": "0x" + "11" * 32,
                          "block_number": 1, "gas_used": 0, "error": "reverted"})
        try:
            R.deliver(journal, oid, "0x" + "dd" * 32, bad, consumer)
            raise AssertionError("a refusing consumer still produced an acknowledgement")
        except NativeAcknowledgementError as e:
            assert "did not complete" in str(e), str(e)

        assert native_ack_state(journal, oid) is None, "an ack survived a rolled-back apply"
        assert R.delivery_status(journal, oid) is None or \
            R.delivery_status(journal, oid).get("acked_at") is None
        journal.close()


@test("MODEL ONLY: the local harness exercises the same commit boundary")
def _():
    """A LOCAL harness, kept as a model test beside the real connection above.

    It is NOT the native consumer and never was. It stays because it exercises the
    commit boundary against a trivially inspectable consumer, which makes a failure here
    easy to localise. The real acknowledgement is the test above it.
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
