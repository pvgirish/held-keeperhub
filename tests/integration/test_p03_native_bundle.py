"""P03: the REAL pinned compiler's ActionBundle, through Held's named boundary.

The parser tests in test_p03_interception.py build Held's `{safe, calls}` record by
hand. Those remain valid UNIT tests, but they never proved the entry point could accept
what the SDK actually produces — and it could not: the SDK exposes `transactions`.

This file closes that gap. It compiles a real SupplyIntent with the pinned
`IntentCompiler` and feeds the resulting object through
`admit_native_bundle` -> `admit_bundle`, then asserts the admitted economic calldata is
**byte-identical** to what the compiler emitted.

It also writes a cross-language vector for the Solidity side to check against the
deployed controller's own `actionHash`, so the Python hash is no longer only
self-consistent.

Requires the pinned SDK and HELD_PRICE_MODE=testing-only (a labelled test-only price
configuration, never runtime evidence). No chain, no network, no KeeperHub.
"""
from __future__ import annotations

import json
import subprocess
import os
import sys
from decimal import Decimal

SDK_PIN = "6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "packages", "core"))
sys.path.insert(0, os.path.join(ROOT, "adapter"))

from held_adapter.execution.interceptor import Profile  # noqa: E402
from held_adapter.execution.native_boundary import (  # noqa: E402
    HELD_RECORD_VERSION,
    ExecutionContext,
    HoldDecision,
    NativeBoundaryError,
    admit_native_bundle,
    normalize_native_bundle,
)
from held_core.canonical import hex32  # noqa: E402
from eth_utils import keccak  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

SAFE = "0x08deEDA0Ba1eb4B6B4b5cc4DD0c4BC689EA37180"
CONTROLLER = "0x3875311cc0d4017a033893a9653a0725378aca1c"
MORPHO = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
COLL = "0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452"
ORACLE = "0xD7A1abA119a236Fea5BBC5cAC6836465cbe9289A"
IRM = "0x46415998764C29aB2a25CbeA6254146D50D22687"
LLTV = 860000000000000000

PROFILE = Profile(chain_id=8453, controller=CONTROLLER, safe=SAFE, lineage="0x" + "11" * 32,
                  morpho=MORPHO, token=USDC, market_params=(USDC, COLL, ORACLE, IRM, LLTV))


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


def compile_real_supply(amount_usdc="100"):
    """Compile with the ACTUAL pinned compiler and return its real result object."""
    from almanak.framework.intents import SupplyIntent
    from almanak.framework.intents.compiler import IntentCompiler

    kwargs = dict(chain="base", wallet_address=SAFE, default_protocol="morpho_blue",
                  rpc_url=os.environ.get("HELD_BASE_RPC"), rpc_timeout=30.0)
    if os.environ.get("HELD_PRICE_MODE") == "testing-only":
        kwargs["price_oracle"] = {"USDC": Decimal("1")}  # TESTING-ONLY, never runtime evidence
    compiler = IntentCompiler(**kwargs)
    intent = SupplyIntent(protocol="morpho_blue", chain="base", token="USDC",
                          amount=Decimal(amount_usdc), market_id=hex32(PROFILE.market_id()),
                          use_as_collateral=False)
    return compiler.compile(intent)


def context(**kw) -> ExecutionContext:
    base = dict(chain_id=8453, safe=SAFE, source_decision_id="native-decision-1", action_index=0)
    base.update(kw)
    return ExecutionContext(**base)


# ------------------------------------------------- the real producer, end to end --
@test("the REAL compiler result is admitted through the named boundary")
def _():
    result = compile_real_supply()
    assert type(result).__name__ == "CompilationResult", type(result)
    assert hasattr(result, "action_bundle"), "the real seam nests the ActionBundle"
    record, admitted = admit_native_bundle(result, context(), PROFILE)

    assert record.version == "held.native-record.v1"
    assert admitted.action.amount == 100_000_000, admitted.action.amount
    assert admitted.action.on_behalf == SAFE.lower()
    print(f"      intent_type={record.intent_type} calls={len(record.calls)} "
          f"amount={admitted.action.amount} approval={admitted.approval_amount}")


@test("the admitted economic calldata is BYTE-IDENTICAL to what the compiler emitted")
def _():
    result = compile_real_supply()
    # Compare against the ActionBundle's OWN transactions, not the flattened list.
    native_txs = list(result.action_bundle.transactions)
    record, _ = admit_native_bundle(result, context(), PROFILE)

    def as_hex(d):
        return (d if isinstance(d, str) else "0x" + bytes(d).hex()).lower()

    assert len(record.calls) == len(native_txs), "the boundary dropped or added a call"
    for i, (native, held) in enumerate(zip(native_txs, record.calls)):
        n = native.get("data") if isinstance(native, dict) else getattr(native, "data")
        assert as_hex(held["data"]) == as_hex(n), f"call[{i}] calldata was altered"
    print(f"      {len(record.calls)} calls passed through byte-identical")


@test("the raw native objects would NOT have been accepted by the old entry point")
def _():
    from held_adapter.execution.interceptor import BundleRejected, admit_bundle
    result = compile_real_supply()
    for raw, what in ((result, "CompilationResult"), (result.action_bundle, "ActionBundle")):
        try:
            admit_bundle(raw, PROFILE, "d", 0)
        except BundleRejected as e:
            assert "no calls" in str(e), f"{what}: {e}"
        else:
            raise AssertionError(f"admit_bundle accepted a raw {what}")
    return


def _unused():
    from held_adapter.execution.interceptor import BundleRejected, admit_bundle
    result = compile_real_supply()
    try:
        admit_bundle(result, PROFILE, "d", 0)
    except BundleRejected as e:
        assert "no calls" in str(e), str(e)
        return
    raise AssertionError(
        "admit_bundle accepted a raw ActionBundle; the schema mismatch this test "
        "documents would no longer exist")


# ------------------------------------------------------------------ fail closed --
@test("a HOLD never becomes an operation, and a HOLD with transactions is contradictory")
def _():
    from held_adapter.execution.native_boundary import NativeBoundaryError

    class Bundle:
        def __init__(self, txs):
            self.intent_type = "HOLD"; self.transactions = txs; self.metadata = {}

    class Result:
        def __init__(self, txs):
            self.status = "SUCCESS"; self.error = None; self.is_safety_refusal = False
            self.action_bundle = Bundle(txs)

    # A genuine HOLD: no economic call, no operation.
    try:
        admit_native_bundle(Result([]), context(), PROFILE)
    except HoldDecision:
        pass
    else:
        raise AssertionError("a HOLD produced an executable operation")

    # A HOLD carrying executable transactions is contradictory input. Classifying it as
    # a successful no-action decision would discard real calls in silence.
    try:
        admit_native_bundle(Result([{"to": MORPHO, "data": "0x5c2bea49", "value": 0}]),
                            context(), PROFILE)
    except NativeBoundaryError as e:
        assert "contradictory" in str(e), str(e)
    else:
        raise AssertionError("a HOLD carrying transactions was accepted as a HOLD")


@test("the producer verdict is exact: no prefix match, no default success")
def _():
    from held_adapter.execution.native_boundary import (
        NativeBoundaryError, NativeRefusal, unwrap_compilation_result)

    class R:
        def __init__(self, status=None, error=None, refusal=False, bundle=object(), omit=False):
            if not omit:
                self.status = status
            self.error = error; self.is_safety_refusal = refusal; self.action_bundle = bundle

    # 1. Prefix-matched impostors are refused. These previously PASSED the verdict check.
    for bad in ("SUCCESS_BUT_FAILED", "OKAY", "COMPILED_UNSAFE", "success", "", "UNKNOWN"):
        try:
            unwrap_compilation_result(R(status=bad))
        except NativeBoundaryError as e:
            assert "unrecognised" in str(e), f"{bad!r} -> {e}"
        else:
            raise AssertionError(f"status {bad!r} was admitted")

    # 2. A missing verdict is NOT success by default.
    for missing in (R(omit=True), R(status=None)):
        try:
            unwrap_compilation_result(missing)
        except NativeBoundaryError as e:
            assert "no producer verdict" in str(e), str(e)
        else:
            raise AssertionError("an object with no verdict was admitted")

    # 3. The ORDINARY native refusal shape is FAILED + is_safety_refusal, per the SDK's
    #    own docstring. It must keep its category, not collapse into a generic error.
    try:
        unwrap_compilation_result(R(status="FAILED", error="price impact too high", refusal=True))
    except NativeRefusal as e:
        assert "safety" in str(e), str(e)
    else:
        raise AssertionError("a native safety refusal lost its category")

    # 4. Plain failure, PARTIAL, and SUCCESS carrying contradictions.
    for r, needle in (
        (R(status="FAILED", error="boom"), "FAILED"),
        (R(status="PARTIAL"), "PARTIAL"),
        (R(status="SUCCESS", refusal=True), "contradictory"),
        (R(status="SUCCESS", error="boom"), "contradictory"),
        (R(status="SUCCESS", bundle=None), "no action_bundle"),
    ):
        try:
            unwrap_compilation_result(r)
        except NativeBoundaryError as e:
            assert needle in str(e), f"{needle} -> {e}"
        else:
            raise AssertionError(f"expected refusal containing {needle!r}")

    # 5. The explicitly-named bare-bundle helper still works for parser-level use.
    from held_adapter.execution.native_boundary import normalize_bare_bundle

    class Bare:
        intent_type = "SUPPLY"
        transactions = [{"to": USDC, "data": "0x095ea7b3", "value": 0}]
        metadata: dict = {}
    assert normalize_bare_bundle(Bare(), context()).intent_type == "SUPPLY"


@test("a declared intent that disagrees with the decoded calldata is refused")
def _():
    from held_adapter.execution.native_boundary import NativeBoundaryError
    result = compile_real_supply()

    class Mislabelled:
        # the REAL supply transactions, deliberately labelled WITHDRAW
        intent_type = "WITHDRAW"
        transactions = list(result.action_bundle.transactions)
        metadata: dict = {}

    class R:
        status = "SUCCESS"; error = None; is_safety_refusal = False
        action_bundle = Mislabelled()

    try:
        admit_native_bundle(R(), context(), PROFILE)
    except NativeBoundaryError as e:
        assert "disagrees with the family decoded" in str(e), str(e)
    else:
        raise AssertionError("a mislabelled bundle was admitted")


@test("contradictory execution context is refused")
def _():
    from held_adapter.execution.native_boundary import NativeBoundaryError
    result = compile_real_supply()
    for kw, needle in (
        (dict(chain_id=1), "contradicts profile chain"),
        (dict(safe="0x000000000000000000000000000000000000dEaD"), "contradicts profile Safe"),
    ):
        try:
            admit_native_bundle(result, context(**kw), PROFILE)
        except NativeBoundaryError as e:
            assert needle in str(e), f"{kw} -> {e}"
        else:
            raise AssertionError(f"{kw} was admitted")


@test("sensitive_data is never copied into Held's record")
def _():
    class Bundle:
        intent_type = "SUPPLY"
        transactions = [{"to": USDC, "data": "0x095ea7b3", "value": 0}]
        metadata = {"cycle_id": "abc", "deployment_id": "d"}
        sensitive_data = {"signer_secret": "MUST-NOT-APPEAR"}

    record = normalize_native_bundle(Bundle(), context())
    blob = json.dumps({"version": record.version, "intent": record.intent_type,
                       "safe": record.safe, "calls": record.calls,
                       "metadata_keys": record.source_metadata_keys}, default=str)
    assert "MUST-NOT-APPEAR" not in blob, "sensitive_data leaked into the record"
    assert "signer_secret" not in blob, "a sensitive key name leaked into the record"
    # metadata KEY NAMES are retained for provenance; values are not.
    assert record.source_metadata_keys == ("cycle_id", "deployment_id")
    assert "abc" not in blob, "a metadata VALUE was copied wholesale"


# -------------------------------------------- cross-language vector for Solidity --
def installed_sdk_commit() -> str:
    """The commit of the SDK actually imported, read from its own checkout.

    Recording the pin as a constant would only repeat what this file claims. This reads
    the revision of the tree the `almanak` module was imported FROM, so a vector produced
    against a different checkout is detectable rather than merely asserted.
    """
    import almanak
    sdk_root = os.path.dirname(os.path.dirname(os.path.abspath(almanak.__file__)))
    out = subprocess.run(["git", "-C", sdk_root, "rev-parse", "HEAD"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise AssertionError(f"cannot read SDK revision from {sdk_root}: {out.stderr.strip()}")
    return out.stdout.strip()


@test("writes a cross-language actionHash vector carrying its own provenance")
def _():
    result = compile_real_supply()
    record, admitted = admit_native_bundle(result, context(), PROFILE)

    # A vector with no provenance cannot be re-checked from a fresh checkout: nothing in
    # it says which producer or which SDK tree it came from, so a stale file would keep
    # passing against a controller it was never derived against.
    sdk_commit = installed_sdk_commit()
    assert sdk_commit == SDK_PIN, (
        f"vector would be produced against SDK {sdk_commit}, not the pin {SDK_PIN}"
    )

    # The economic call is the one the hash is derived from; digesting its exact bytes
    # ties the vector to the calldata it was produced from, not just to the numbers.
    economic = record.calls[-1]["data"]
    if isinstance(economic, str):
        economic = bytes.fromhex(economic[2:] if economic.startswith("0x") else economic)
    dest = os.path.join(ROOT, "fixtures", "crosslang-vectors.json")
    vector = {
        "note": ("Computed by the Python adapter from the REAL compiler output. "
                 "test/contracts/HeldController.t.sol reads this and asserts the DEPLOYED "
                 "controller's actionHash() agrees, which is what makes the hash claim a "
                 "cross-language check rather than Python agreeing with itself."),
        "producer": "tests/integration/test_p03_native_bundle.py",
        "almanakSdkCommit": sdk_commit,
        "heldRecordVersion": HELD_RECORD_VERSION,
        "family": 1,
        "marketId": hex32(PROFILE.market_id()),
        "asset": PROFILE.token,
        "amount": str(admitted.action.amount),
        "onBehalf": PROFILE.safe,
        "expectedActionHash": hex32(admitted.payload_hash),
    }
    vector["economicCalldataDigest"] = hex32(keccak(economic))
    with open(dest, "w") as fh:
        json.dump(vector, fh, indent=2)
    print(f"      wrote {os.path.relpath(dest, ROOT)}  sdk={sdk_commit[:12]} "
          f"hash={vector['expectedActionHash'][:18]}...")


def main() -> int:
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"P03 native-bundle: FAIL ({len(FAILED)}/{len(PASSED)+len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} P03 native-bundle tests held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
