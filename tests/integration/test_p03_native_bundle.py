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
import os
import sys
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "packages", "core"))
sys.path.insert(0, os.path.join(ROOT, "adapter"))

from held_adapter.execution.interceptor import Profile  # noqa: E402
from held_adapter.execution.native_boundary import (  # noqa: E402
    ExecutionContext,
    HoldDecision,
    NativeBoundaryError,
    admit_native_bundle,
    normalize_native_bundle,
)
from held_core.canonical import hex32  # noqa: E402

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
@test("a HOLD never becomes an operation")
def _():
    class Bundle:
        intent_type = "HOLD"
        transactions: list = []
        metadata: dict = {}
    try:
        admit_native_bundle(Bundle(), context(), PROFILE)
    except HoldDecision:
        return
    raise AssertionError("a HOLD produced an executable operation")


@test("native status, refusal, contradictory context and unsupported intent fail closed")
def _():
    from held_adapter.execution.native_boundary import NativeRefusal, unwrap_compilation_result

    class Failed:
        status = "FAILED"; error = None; is_safety_refusal = False; action_bundle = None
    try:
        unwrap_compilation_result(Failed())
    except NativeBoundaryError as e:
        assert "did not succeed" in str(e), str(e)
    else:
        raise AssertionError("a failed compilation was unwrapped")

    class Refused:
        status = "SUCCESS"; error = None; is_safety_refusal = True; action_bundle = None
    try:
        unwrap_compilation_result(Refused())
    except NativeRefusal:
        pass
    else:
        raise AssertionError("a native safety refusal was routed around")

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

    class Weird:
        intent_type = "BORROW"
        transactions = [{"to": MORPHO, "data": "0x", "value": 0}]
        metadata: dict = {}
    try:
        normalize_native_bundle(Weird(), context())
    except NativeBoundaryError as e:
        assert "outside the supported profile" in str(e), str(e)
    else:
        raise AssertionError("an unsupported intent_type was admitted")


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
@test("writes a cross-language actionHash vector for the deployed controller to check")
def _():
    result = compile_real_supply()
    _, admitted = admit_native_bundle(result, context(), PROFILE)
    dest = os.path.join(ROOT, "fixtures", "crosslang-vectors.json")
    vector = {
        "note": ("Computed by the Python adapter from the REAL compiler output. "
                 "test/contracts/HeldController.t.sol reads this and asserts the DEPLOYED "
                 "controller's actionHash() agrees, which is what makes the hash claim a "
                 "cross-language check rather than Python agreeing with itself."),
        "family": 1,
        "marketId": hex32(PROFILE.market_id()),
        "asset": PROFILE.token,
        "amount": str(admitted.action.amount),
        "onBehalf": PROFILE.safe,
        "expectedActionHash": hex32(admitted.payload_hash),
    }
    with open(dest, "w") as fh:
        json.dump(vector, fh, indent=2)
    print(f"      wrote {os.path.relpath(dest, ROOT)}  hash={vector['expectedActionHash'][:18]}...")


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
