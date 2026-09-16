"""P00 required work 2 and 6: the native WORKFLOW, not merely native components.

REVISION 3. Two further corrections, both withdrawing an earlier claim of mine:
  * Revision 2 stopped at "the reconciliation marker survived a reload". That is a
    persistence round trip, not a decision. The native callable
    `assess_replay_barrier` now consumes the reopened record and returns the
    refusal itself, with a releasable control proving the NO is a real decision.
  * Revision 2 said `state_machine.set_receipt` was blocked by L10. WRONG. At the
    pin it is a local assignment and `step()` evaluates it; section B3 exercises
    the boundary locally and it transitions VALIDATING_SUPPLY -> COMPLETED.

REVISION 2. Revision 1 claimed "native reconfiguration" on the strength of two
`StrategyConfig` objects producing different digests. That is **withdrawn**:
`StrategyConfig` declares `extra="allow"` and has no supply/ceiling/limit field at
all, so a changed digest can reflect a field no native component ever reads. A
digest delta is not effective reconfiguration.

Three evidence classes, deliberately kept apart so neither can be mistaken for the
other:

  A. **NATIVE CONFIGURATION** — what the measured task actually requires of Almanak
     configuration, established from the pinned source, and exercised through the
     real loader where a change is genuinely required.
  B. **NATIVE-ONLY RECOVERY WORKFLOW** — the runner's own `ExecutionProgress`
     restart record, persisted, dropped and reloaded. No Held code participates.
  C. **HELD ADAPTER COMPATIBILITY** — the native predicates mapped onto Held's
     journal. Useful, but a Held test, NOT native baseline evidence.

Pinned SDK 6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938. Offline; no chain, no keys.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "core"))

import almanak  # noqa: E402
from almanak.config import safe_signer as almanak_safe_signer  # noqa: E402
from almanak.config import service as almanak_service  # noqa: E402
from almanak.config import strategy as almanak_strategy  # noqa: E402
from almanak.framework.execution import reconciliation as rec  # noqa: E402
from almanak.framework.execution.submission import SubmissionProvenance  # noqa: E402
from almanak.framework.cli.execution_recovery import assess_replay_barrier  # noqa: E402
from almanak.framework.execution.signer.safe.config import SafeWalletMapping  # noqa: E402
from almanak.framework.intents import SupplyIntent  # noqa: E402
from almanak.framework.intents.state_machine import IntentStateMachine  # noqa: E402
from almanak.framework.runner.runner_models import (  # noqa: E402
    ExecutionProgress,
    StepSubmissionEvidence,
)

from held_core import journal as J  # noqa: E402
from held_core import canonical, identity  # noqa: E402
from held_core.identity import ActionFamily, OperationScope, SupportedAction  # noqa: E402

SDK_REV = "6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938"
SAFE = "0x08deEDA0Ba1eb4B6B4b5cc4DD0c4BC689EA37180"
CONTROLLER = "0x3875311cc0d4017a033893a9653a0725378aca1c"
RUNNER_A = "0x90F79bf6EB2c4f870365E785982E1f101E93b906"
RUNNER_B = "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
MARKET = "0x13c42741a359ac4a8aa8287d2be109dcf28344484f91185f9a79bd5a805a55ae"
SCOPE = OperationScope(8453, CONTROLLER, SAFE, "0x" + "11" * 32)

failures: list[str] = []


def check(cond: bool, msg: str) -> bool:
    if not cond:
        failures.append(msg)
    return cond


def revert_receipt(tx_hash: str) -> dict[str, object]:
    return {"tx_hash": tx_hash, "status": 0, "block_number": 51353212, "gas_used": 21000,
            "effective_gas_price": 1000000,
            "block_hash": "0xe1933ad8acf0950c3992368ef1d1157b17af4d2e973e686d11b7b1235de68254",
            "logs": []}


out: dict[str, object] = {
    "probe": "p00-native-workflow",
    "revision": 3,
    "revision_note": (
        "Revision 1's 'native reconfiguration' claim is WITHDRAWN. A StrategyConfig "
        "digest delta does not establish that any native component consumed the change."
    ),
    "sdk_revision_expected": SDK_REV,
    "sdk_module_path": os.path.dirname(almanak.__file__),
}

# ===================================================== A. NATIVE CONFIGURATION ==
# What does the measured task -- raise the ceiling 50,000 -> 80,000 and replace
# operator A with B -- actually require of Almanak configuration?
cfg_fields = list(almanak_strategy.StrategyConfig.model_fields)
limitish = [f for f in cfg_fields
            if any(k in f.lower() for k in ("supply", "ceiling", "limit", "allowance", "cap"))]

# Two genuine boots of the REAL mapping, with the wallet entry changed between them.
# Revision 3: this now asserts the EFFECTIVE SIGNING EOA changed, not merely that a
# raw environment string differs. SafeWalletMapping.get_config() is the native
# lookup that resolves a Safe to its signing EOA and Roles module.
ROLES_ADDR = CONTROLLER


def boot_wallet_mapping(eoa: str):
    os.environ["ALMANAK_PLATFORM_WALLETS"] = json.dumps(
        [{"SAFE_ACCOUNT_ADDRESS": SAFE, "EOA_ADDRESS": eoa, "ZODIAC_ROLES_ADDRESS": ROLES_ADDR}]
    )
    return SafeWalletMapping().get_config(SAFE)


prev_env = os.environ.get("ALMANAK_PLATFORM_WALLETS")
try:
    cfg_a = boot_wallet_mapping(RUNNER_A)
    cfg_b = boot_wallet_mapping(RUNNER_B)
    effective_eoa_a, effective_eoa_b = cfg_a.eoa_address, cfg_b.eoa_address
    loader_consumed_change = (
        effective_eoa_a.lower() == RUNNER_A.lower()
        and effective_eoa_b.lower() == RUNNER_B.lower()
        and effective_eoa_a.lower() != effective_eoa_b.lower()
    )
    roles_unchanged = cfg_a.zodiac_roles_address == cfg_b.zodiac_roles_address
finally:
    if prev_env is None:
        os.environ.pop("ALMANAK_PLATFORM_WALLETS", None)
    else:
        os.environ["ALMANAK_PLATFORM_WALLETS"] = prev_env

out["A_native_configuration"] = {
    "evidence_class": "real native config modules, source-grounded + real loader executed",
    "ceiling_change_50k_to_80k": {
        "native_almanak_config_steps_required": 0,
        "why": (
            "StrategyConfig declares NO supply/ceiling/limit/allowance field "
            f"(checked all {len(cfg_fields)} fields; matches: {limitish}). The cumulative "
            "supply ceiling is Zodiac Roles state on-chain, not Almanak configuration. "
            "Raising it requires no native Almanak configuration change."
        ),
        "credit": (
            "NATIVE IS CREDITED WITH A NO-OP here. Inventing an Almanak "
            "'cumulative supply ceiling' setting to mirror the Roles allowance would "
            "manufacture native work that the real workflow does not require."
        ),
        "extra_policy_caveat": (
            f"StrategyConfig model_config extra={almanak_strategy.StrategyConfig.model_config.get('extra')!r}. "
            "Arbitrary extra fields are accepted, so a config digest change proves "
            "nothing about consumption. This is why revision 1's digest test was withdrawn."
        ),
    },
    "operator_swap_A_to_B": {
        "native_config_surface": "ALMANAK_PLATFORM_WALLETS env -> safe_signer_service_config_from_env()",
        "consumed_at": (
            "process boot. load_config() is documented as 'Construct the typed "
            "configuration once at the relevant boot surface... Process entrypoints / "
            "wrappers call it once after loading the relevant dotenv source, then "
            "downstream code should consume injected slices'."
        ),
        "live_reload_api_found_on_this_path": False,
        "scope_note": ("Absence on the inspected boot path. NOT a claim that no reload "
                       "mechanism exists anywhere in the SDK or in any deployment."),
        "consequence_for_the_baseline": (
            "IN THE CONFIGURATION TESTED HERE, replacing the operator costs an "
            "environment/wallet-mapping change plus a process restart, because the mapping "
            "is constructed at boot. SCOPE LIMIT: this is the procedure exercised in this "
            "configuration. The inspected source establishes construction and caching "
            "behaviour; it does NOT prove that no other reload mechanism exists in any "
            "deployment, and no such universal claim is made."
        ),
        "real_lookup_executed": "SafeWalletMapping().get_config(safe) -> SafeWalletConfig",
        "loader_consumed_the_change": loader_consumed_change,
        "effective_signing_eoa_boot_a": effective_eoa_a,
        "effective_signing_eoa_boot_b": effective_eoa_b,
        "effective_eoa_actually_changed": effective_eoa_a.lower() != effective_eoa_b.lower(),
        "zodiac_roles_address_unchanged": roles_unchanged,
        "what_this_asserts": (
            "The EFFECTIVE SIGNING EOA resolved by the native lookup changed from A to B "
            "- not merely that a raw environment string differs. The Roles module address "
            "is unchanged, as expected: the operator swaps, the authority path does not."
        ),
        "load_config_signature": "load_config(*, gateway_overrides=None, dotenv_path=None)",
        "load_config_not_called_here": (
            "load_config() reads the whole environment and would pick up ambient host "
            "state; the signer slice is exercised directly instead. Recorded rather than "
            "implied."
        ),
    },
}
check(not limitish, "StrategyConfig unexpectedly has a supply/limit field")
check(loader_consumed_change, "the real signer loader did not consume the changed wallet mapping")


# ============================================= B. NATIVE-ONLY RECOVERY WORKFLOW ==
# The runner's OWN restart record. Held does not appear in this section.
#
# ExecutionProgress documents three mutually exclusive per-step markers:
#   failed_at_step_index              -> never broadcast; must be re-executed
#   accounting_pending_step_index     -> broadcast CONFIRMED; do NOT re-broadcast
#   reconciliation_required_step_index-> hashes retained, receipts untrustworthy;
#                                        terminal, must NEVER be auto re-executed
# The recovery module's own eligibility gate, evaluated against a real SupplyIntent.
from decimal import Decimal as _D  # noqa: E402

from almanak.framework.intents import LPOpenIntent as _LPOpen  # noqa: E402
from almanak.framework.intents import SwapIntent as _Swap  # noqa: E402

_probe_supply_intent = SupplyIntent(protocol="morpho_blue", chain="base", token="USDC",
                                    amount=_D("100"), market_id=MARKET, use_as_collateral=False)
_supply_is_auto_recoverable = isinstance(_probe_supply_intent, _Swap | _LPOpen)

PLAN_HASH = "b" * 64
AMBIGUOUS_TX = "0x" + "b2" * 32

ambiguous_result = {
    "success": False,
    "submission_provenance": "ATTEMPTED",
    "tx_hashes": [AMBIGUOUS_TX],
    "receipts": [],
    "execution_plan_hash": PLAN_HASH,
    "error": "gateway timeout after submission",
}

# The runner consults the native predicate to classify the failure. We call the
# same predicate it calls.
needs_reconciliation = rec.failed_submission_requires_reconciliation(ambiguous_result)
proves_revert = rec.failed_submission_proves_revert(ambiguous_result)
native_hashes = list(rec.submitted_transaction_hashes(ambiguous_result))

evidence = StepSubmissionEvidence(
    step_index=0,
    chain="base",
    submission_provenance=SubmissionProvenance.ATTEMPTED,
    submitted_transaction_ids=native_hashes,
    execution_plan_hash=PLAN_HASH,
)
progress = ExecutionProgress(
    execution_id="held-fixture-exec-1",
    deployment_id="held-p00-fixture",
    intents_hash="intents-" + PLAN_HASH[:16],
    total_steps=1,
    completed_step_index=-1,
    submission_evidence=[evidence],
)
# Apply the runner's documented contract for this classification.
if needs_reconciliation:
    progress.reconciliation_required_step_index = 0
    progress.failure_error = rec.reconciliation_required_error(ambiguous_result)
elif proves_revert:
    progress.failed_at_step_index = 0

# --- a real restart: serialise, drop every in-memory object, reload -------------
statedir = tempfile.mkdtemp(prefix="held-native-recovery-")
statefile = os.path.join(statedir, "execution_progress.json")
with open(statefile, "w") as fh:
    json.dump(
        {
            "execution_id": progress.execution_id,
            "deployment_id": progress.deployment_id,
            "intents_hash": progress.intents_hash,
            "total_steps": progress.total_steps,
            "completed_step_index": progress.completed_step_index,
            "failed_at_step_index": progress.failed_at_step_index,
            "accounting_pending_step_index": progress.accounting_pending_step_index,
            "reconciliation_required_step_index": progress.reconciliation_required_step_index,
            "failure_error": progress.failure_error,
            "submission_evidence": [e.to_dict() for e in progress.submission_evidence],
        },
        fh,
        indent=2,
    )

del progress, evidence  # the process is gone; nothing in memory survives

with open(statefile) as fh:
    raw = json.load(fh)
reopened = ExecutionProgress(
    execution_id=raw["execution_id"],
    deployment_id=raw["deployment_id"],
    intents_hash=raw["intents_hash"],
    total_steps=raw["total_steps"],
    completed_step_index=raw["completed_step_index"],
    failed_at_step_index=raw["failed_at_step_index"],
    accounting_pending_step_index=raw["accounting_pending_step_index"],
    reconciliation_required_step_index=raw["reconciliation_required_step_index"],
    failure_error=raw["failure_error"],
    submission_evidence=[StepSubmissionEvidence.from_dict(d) for d in raw["submission_evidence"]],
)

identity_survived = (
    reopened.submission_evidence
    and AMBIGUOUS_TX in reopened.submission_evidence[0].submitted_transaction_ids
)
marker_survived = reopened.reconciliation_required_step_index == 0

# --- THE DECISION, made by native code, not asserted by Held --------------------
# Revision 2 stopped at "the marker survived", which is only a persistence round
# trip. `assess_replay_barrier` is the native callable that CONSUMES a reopened
# ExecutionProgress and returns whether re-dispatch is proven safe. Its own
# docstring: "Only ``reverted`` is a release proof ... deliberately treats
# absent/novel gateway statuses as unknown so protocol skew cannot turn
# uncertainty into permission to rebroadcast."
native_decision = assess_replay_barrier(reopened, {})          # no status evidence
native_releasable = bool(native_decision.releasable)
native_reason = str(native_decision.reason)

# The same callable must be capable of saying YES, or a NO proves nothing.
not_attempted = ExecutionProgress(
    execution_id="held-fixture-exec-3", deployment_id="held-p00-fixture",
    intents_hash="intents-not-attempted", total_steps=1, completed_step_index=-1,
    reconciliation_required_step_index=0,
    submission_evidence=[StepSubmissionEvidence(
        step_index=0, chain="base",
        submission_provenance=SubmissionProvenance.NOT_ATTEMPTED,
        submitted_transaction_ids=[], execution_plan_hash=PLAN_HASH)],
)
control_decision = assess_replay_barrier(not_attempted, {})

check(bool(identity_survived), "submitted transaction identity did not survive the restart")
check(marker_survived, "reconciliation-required marker did not survive the restart")
check(not native_releasable,
      f"NATIVE decided re-dispatch was releasable for an uncertain op: {native_reason}")
check(bool(control_decision.releasable),
      "control failed: assess_replay_barrier never returns releasable, so the NO is not a decision")

# Contrast cases, same machinery, different classification.
reverted_result = {"success": False, "submission_provenance": "ATTEMPTED",
                   "tx_hashes": ["0x" + "c3" * 32],
                   "receipts": [revert_receipt("0x" + "c3" * 32)], "error": "reverted"}
confirmed_progress = ExecutionProgress(
    execution_id="held-fixture-exec-2", deployment_id="held-p00-fixture",
    intents_hash="intents-confirmed", total_steps=1, completed_step_index=-1,
    accounting_pending_step_index=0,
)

out["B_native_only_recovery_workflow"] = {
    "evidence_class": "NATIVE ONLY - the runner's own ExecutionProgress restart record. No Held code participates.",
    "components": [
        "almanak.framework.runner.runner_models.ExecutionProgress",
        "almanak.framework.runner.runner_models.StepSubmissionEvidence",
        "almanak.framework.execution.reconciliation (classification predicates)",
    ],
    "documented_contract": {
        "failed_at_step_index": "step never broadcast; must be re-executed",
        "accounting_pending_step_index": "broadcast CONFIRMED on-chain; do NOT re-broadcast on resume",
        "reconciliation_required_step_index": (
            "hashes retained but no trustworthy receipt set; terminal operator-"
            "reconciliation marker; must NEVER be automatically re-executed"
        ),
    },
    "ambiguous_case": {
        "scenario": "I2-style: broadcast crossed the boundary, then the gateway timed out",
        "native_submitted_hashes": native_hashes,
        "native_requires_reconciliation": needs_reconciliation,
        "native_proves_revert": proves_revert,
        "marker_set_by_contract": "reconciliation_required_step_index=0",
        "restart": {
            "persisted_to": statefile,
            "in_memory_objects_dropped": True,
            "reopened_execution_id": reopened.execution_id,
            "submitted_identity_survived": bool(identity_survived),
            "surviving_hashes": list(reopened.submission_evidence[0].submitted_transaction_ids),
            "reconciliation_marker_survived": marker_survived,
            "native_error": (reopened.failure_error or "")[:180],
        },
        "native_decision_on_the_reopened_record": {
            "callable": "almanak.framework.cli.execution_recovery.assess_replay_barrier(progress, statuses)",
            "why_this_matters": (
                "Revision 2 stopped at 'the marker survived', which is only a persistence "
                "round trip. THIS is the native callable that consumes the reopened record "
                "and decides. The verdict below is returned by native code; Held asserts "
                "nothing about it."
            ),
            "releasable": native_releasable,
            "native_reason": native_reason,
            "step_index": native_decision.step_index,
            "dispatch_path_invoked": False,
            "evidence_label": (
                "Native recovery-release decision evaluated against a REOPENED RECORD, "
                "using labelled fixture evidence. NOT an operating-system restart "
                "demonstration and NOT an end-to-end runner test."
            ),
            "control_not_attempted_case": {
                "releasable": bool(control_decision.releasable),
                "native_reason": str(control_decision.reason),
                "reason_is_the_sdk_message_for_this_input": (
                    "The string 'gateway proved submission was not attempted' is the SDK's "
                    "message for NOT_ATTEMPTED provenance in the supplied record. It does "
                    "NOT mean this test obtained fresh proof from a live gateway."
                ),
                "why": ("The same callable must be able to return YES, or a NO proves "
                        "nothing. With gateway-proved NOT_ATTEMPTED evidence it releases."),
            },
        },
        "finding": (
            "The native runner retains the submitted transaction identity across a restart, "
            "reopens holding a TERMINAL reconciliation marker, and the native decision "
            "callable then REFUSES release for the uncertain operation while releasing a "
            "provably-not-attempted one. Established without any Held component."
        ),
        "honest_scope_of_the_restart": (
            "Serialisation, object drop and reload within one process. This is a durable "
            "state round trip plus the real native decision on the reopened record. It is "
            "NOT an operating-system process restart, and is not claimed as one."
        ),
    },
    "contrast_cases": {
        "proven_revert": {
            "native_proves_revert": rec.failed_submission_proves_revert(reverted_result),
            "native_requires_reconciliation": rec.failed_submission_requires_reconciliation(reverted_result),
            "marker": "failed_at_step_index -> step never took effect; re-execution permitted",
        },
        "accounting_pending": {
            "marker": "accounting_pending_step_index=0",
            "value": confirmed_progress.accounting_pending_step_index,
            "meaning": "broadcast confirmed, accounting incomplete; resume repairs state, never re-broadcasts",
        },
    },
    "intent_scope_of_automatic_recovery": {
        "gate_checked_live": _supply_is_auto_recoverable,
        "finding": (
            "single_chain_recovery is NOT a general automatic recovery mechanism. "
            "_original_intent() gates on isinstance(intent, SwapIntent | LPOpenIntent); a "
            "Morpho SupplyIntent is therefore INELIGIBLE for automatic recovery by design."
        ),
        "supply_intent_is_swap_or_lp_open": _supply_is_auto_recoverable,
        "consequence_for_our_supply_case": (
            "The native outcome is _operator_reconciliation(...) -> IterationStatus."
            "EXECUTION_PENDING: uncertainty preserved, automatic rebroadcast blocked, "
            "operator recovery required."
        ),
        "what_is_NOT_claimed": (
            "That native automatically completes a pending SUPPLY's accounting and callback. "
            "It does not, by design. That absence is NOT a defect and is NOT reported as one. "
            "'Native preserves uncertainty and blocks automatic rebroadcast' is the correct "
            "and arguably desirable baseline behaviour; it is recorded as found."
        ),
    },
    "not_established_here": [
        "A full live runner cycle: needs a constructed strategy and a gateway client. "
        "That is an integration/configuration dependency, NOT the KeeperHub org key.",
        "Deterministic fault injection is used and labelled: the failed-result objects are "
        "constructed fixtures. The PREDICATES, RECORD TYPES, DECISION CALLABLE and CONTRACT "
        "are native.",
    ],
}


# ------------------- B3. native receipt consumption and state transition --------
# Revision 2 wrongly stated that state_machine.set_receipt is blocked by L10. It is
# not. At the pin, set_receipt() is a local assignment (`self._receipt = receipt`)
# and the following step() evaluates state and receipt. Constructing the state
# machine is implementation work, not a missing external credential. That claim is
# WITHDRAWN and the boundary is exercised here.
receipt_boundary: dict[str, object] = {
    "withdrawn_claim": (
        "Revision 2 said 'state_machine.set_receipt ... needs a gateway client -- L10'. "
        "WRONG, and withdrawn. set_receipt is a local assignment at this revision; the "
        "authenticated KeeperHub dependency is a separate concern."
    ),
    "callable": "almanak.framework.intents.state_machine.IntentStateMachine.set_receipt / .step",
}
try:
    from decimal import Decimal

    from almanak.framework.intents.compiler import IntentCompiler

    price_mode = os.environ.get("HELD_PRICE_MODE", "none")
    ckwargs = dict(chain="base", wallet_address=SAFE, default_protocol="morpho_blue",
                   rpc_url=os.environ.get("HELD_BASE_RPC"), rpc_timeout=30.0)
    if price_mode == "testing-only":
        # TESTING-ONLY price configuration. Never runtime evidence.
        ckwargs["price_oracle"] = {"USDC": Decimal("1")}
    supply_intent = SupplyIntent(protocol="morpho_blue", chain="base", token="USDC",
                                 amount=Decimal("100"), market_id=MARKET,
                                 use_as_collateral=False)
    sm = IntentStateMachine(supply_intent, IntentCompiler(**ckwargs))

    first = sm.step()
    state_before = str(getattr(sm, "current_state", None) or getattr(sm, "state", ""))
    needs_exec = bool(getattr(first, "needs_execution", False))

    # A CONFIRMED result enters the native result boundary. The receipt is a
    # labelled deterministic fixture; the ingestion and transition are native.
    from almanak.framework.execution.interfaces import TransactionReceipt

    confirmed_receipt = TransactionReceipt(
        tx_hash="0x" + "a7" * 32,
        block_number=51353212,
        block_hash="0xe1933ad8acf0950c3992368ef1d1157b17af4d2e973e686d11b7b1235de68254",
        gas_used=120000,
        effective_gas_price=1000000,
        status=1,
        logs=[],
    )
    sm.set_receipt(confirmed_receipt)
    receipt_stored = getattr(sm, "_receipt", None) is confirmed_receipt
    second = sm.step()
    state_after = str(getattr(sm, "current_state", None) or getattr(sm, "state", ""))

    receipt_boundary.update({
        "executed_locally": True,
        "price_mode": price_mode,
        "first_step_needs_execution": needs_exec,
        "state_before_receipt": state_before,
        "receipt_ingested": receipt_stored,
        "state_after_receipt": state_after,
        "state_advanced": state_before != state_after,
        "is_complete": bool(getattr(sm, "is_complete", False)),
        "success": getattr(sm, "success", None),
        "error": str(getattr(sm, "error", "") or "")[:200],
        "receipt_type": "almanak.framework.execution.interfaces.TransactionReceipt (real native type)",
        "receipt_success_property": confirmed_receipt.success,
        "receipt_is_a_labelled_fixture": True,
        "not_from_hosted_keeperhub": True,
        "evidence_label": (
            "Local result CONSUMPTION for the supplied receipt. It does NOT independently "
            "verify that an economic transaction succeeded -- fork receipts, transaction "
            "identity and economic readbacks remain their own separate evidence."
        ),
    })
    check(receipt_stored, "native state machine did not ingest the receipt")
except Exception as exc:  # noqa: BLE001
    receipt_boundary.update({
        "executed_locally": False,
        "blocker": f"{type(exc).__name__}: {str(exc)[:240]}",
        "classification": (
            "Local construction/configuration dependency. Recorded as such, NOT as an "
            "L10 hosted-credential blocker."
        ),
    })

out["B3_native_receipt_consumption"] = receipt_boundary

# ============================================ C. HELD ADAPTER COMPATIBILITY ONLY ==
# Kept, but relabelled. This is a Held test, not native baseline evidence.
CASES = [
    ("success", {"success": True, "submission_provenance": "ATTEMPTED",
                 "tx_hashes": ["0x" + "a1" * 32], "receipts": []}, J.OperationState.CONFIRMED),
    ("broadcast-then-timeout", ambiguous_result, J.OperationState.UNKNOWN),
    ("proven-revert", reverted_result, J.OperationState.FAILED),
    ("never-submitted", {"success": False, "submission_provenance": "NOT_ATTEMPTED",
                         "tx_hashes": [], "receipts": [], "error": "compile rejected"},
     J.OperationState.FAILED),
    ("contradicted-provenance", {"success": False, "submission_provenance": "NOT_ATTEMPTED",
                                 "tx_hashes": ["0x" + "d4" * 32], "receipts": [],
                                 "error": "skewed producer"}, J.OperationState.UNKNOWN),
    ("partial-receipts", {"success": False, "submission_provenance": "ATTEMPTED",
                          "tx_hashes": ["0x" + "e5" * 32, "0x" + "f6" * 32],
                          "receipts": [revert_receipt("0x" + "e5" * 32)], "error": "partial"},
     J.OperationState.UNKNOWN),
]


def native_to_held_state(result: object) -> J.OperationState:
    success = result.get("success", False) if isinstance(result, dict) else False
    if success:
        return J.OperationState.CONFIRMED
    if rec.failed_submission_requires_reconciliation(result):
        return J.OperationState.UNKNOWN
    return J.OperationState.FAILED


action = SupportedAction(ActionFamily.SUPPLY, MARKET, USDC, 10_000_000_000, SAFE)
compat: list[dict[str, object]] = []
for name, result, expected in CASES:
    src = f"native-decision-{name}"
    oid = identity.operation_id(SCOPE, src, 0)
    derived = native_to_held_state(result)
    agree = derived is expected
    dbpath = os.path.join(tempfile.mkdtemp(prefix="held-compat-"), "j.sqlite")
    enforced, note = True, ""
    with J.Journal(dbpath) as j:
        j.create_or_reopen(oid, action.payload_hash(), src, 0, 1)
        j.transition(oid, J.OperationState.AUTHORIZED)
        if name != "never-submitted":
            j.record_attempt_before_send(f"att-{name}", oid,
                                         canonical.canonical_hash({"case": name}), 1,
                                         RUNNER_A, "env:HELD_RUNNER_KEY")
            j.transition(oid, J.OperationState.DISPATCHED)
        j.transition(oid, derived)
        if derived is J.OperationState.UNKNOWN:
            try:
                j.assert_recoverable(oid)
                enforced, note = False, "UNKNOWN did not block"
            except J.RecoveryBlocked:
                note = "UNKNOWN blocks"
        elif derived is J.OperationState.CONFIRMED:
            try:
                j.transition(oid, J.OperationState.AUTHORIZED)
                enforced, note = False, "CONFIRMED was re-authorized"
            except J.StateTransitionError:
                note = "CONFIRMED terminal"
        else:
            try:
                j.transition(oid, J.OperationState.AUTHORIZED, epoch=1)
                enforced, note = False, "reauthorized without a newer epoch"
            except J.StateTransitionError:
                j.transition(oid, J.OperationState.AUTHORIZED, epoch=2)
                note = "FAILED reauthorizes same id+payload under a newer epoch"
    check(agree and enforced, f"compatibility case {name} failed")
    compat.append({"case": name, "held_state": derived.value, "agrees": agree,
                   "journal_enforced": enforced, "enforcement": note})

out["C_held_adapter_compatibility"] = {
    "evidence_class": (
        "HELD ADAPTER TEST -- NOT native baseline evidence. It shows Held's journal "
        "adopts the native predicates' verdicts rather than inventing its own. The "
        "native-only recovery evidence is section B, which uses no Held code."
    ),
    "mismatches": sum(1 for c in compat if not (c["agrees"] and c["journal_enforced"])),
    "cases": compat,
}

out["blocked_under_L10"] = {
    "requirement": "Authenticated KeeperHub organisation caller/payer preflight.",
    "exact_missing_evidence": (
        "An organisation-scoped KeeperHub API key permitting GET /api/chains as an "
        "authenticated caller, and a direct-execution preflight naming the payer."
    ),
    "blocks": [
        "Authenticated hosted execution and the hosted half of result delivery: whether a "
        "delayed ack is retried, duplicated or dropped by the real hosted pipeline.",
    ],
    "does_NOT_block": [
        "state_machine.set_receipt and the resulting local state transition (section B3) -- "
        "an earlier claim that it did is WITHDRAWN.",
        "assess_replay_barrier, the native decision on a reopened record (section B).",
        "A full live runner cycle is gated by strategy/gateway CONSTRUCTION, which is an "
        "integration dependency, not this credential.",
    ],
    "does_not_block": "Sections A, B and C above, all of which ran offline.",
    "not_simulated": True,
}

out["limits"] = [
    "Offline in-process execution of the pinned SDK. No chain, no network, no keys.",
    "Failed-result objects are CONSTRUCTED fixtures (deterministic fault injection, "
    "labelled). The predicates, record types and documented contract are native.",
    "Section B exercises the native restart RECORD and its contract, not a live runner "
    "cycle, which needs a gateway client.",
    "Not independently reviewed.",
]

dest = os.path.join(os.path.dirname(__file__), "..", "evidence", "P00", "native-workflow-probe.json")
os.makedirs(os.path.dirname(dest), exist_ok=True)
with open(dest, "w") as fh:
    json.dump(out, fh, indent=2, default=str)

print("A. native configuration")
print(f"   ceiling change  -> native Almanak config steps required: 0 "
      f"(no supply/limit field among {len(cfg_fields)} fields)")
print(f"   operator swap   -> env wallet mapping + process restart; "
      f"real loader consumed the change: {loader_consumed_change}")
print("B. native-only recovery workflow (no Held code)")
print(f"   requires_reconciliation={needs_reconciliation}  proves_revert={proves_revert}")
print(f"   after restart: identity survived={bool(identity_survived)}  marker survived={marker_survived}")
print(f"   NATIVE decision on reopened record: releasable={native_releasable}  "
      f"reason={native_reason[:70]!r}")
print(f"   control (NOT_ATTEMPTED): releasable={bool(control_decision.releasable)}")
print(f"   supply intent eligible for auto-recovery: {_supply_is_auto_recoverable} "
      f"(gate is SwapIntent|LPOpenIntent)")
print("B3. native receipt consumption")
print(f"   executed_locally={receipt_boundary.get('executed_locally')}  "
      f"ingested={receipt_boundary.get('receipt_ingested')}  "
      f"state {receipt_boundary.get('state_before_receipt')} -> {receipt_boundary.get('state_after_receipt')}")
print("C. held adapter compatibility")
print(f"   cases={len(compat)}  mismatches={out['C_held_adapter_compatibility']['mismatches']}")
print(f"\nwrote {os.path.normpath(dest)}")

if failures:
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)
print("native-workflow: PASS")
