"""P03 integration tests, local half: native bundle interception and envelope binding.

The bundle used here is the SHAPE the pinned Almanak compiler actually produced in P00
(`evidence/P00/native-seam-probe.json`): `approve(Morpho, 110000000)` followed by
`supply(marketParams, 100000000, 0, safe, 0x)`. The 10% approval headroom is native
behaviour, preserved rather than rewritten.

These tests are LOCAL. They do not establish the hosted KeeperHub route, which is
blocked by L10 and is not simulated anywhere here.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "packages", "core"))
sys.path.insert(0, os.path.join(ROOT, "adapter"))

from eth_abi import encode as abi_encode  # noqa: E402
from eth_utils import keccak  # noqa: E402

from held_adapter.execution.interceptor import (  # noqa: E402
    ACTION_TYPEHASH,
    BundleRejected,
    Profile,
    admit_bundle,
    onchain_action_hash,
)
from held_core.identity import ActionFamily  # noqa: E402

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

PROFILE = Profile(
    chain_id=8453, controller=CONTROLLER, safe=SAFE, lineage="0x" + "11" * 32,
    morpho=MORPHO, token=USDC,
    market_params=(USDC, COLL, ORACLE, IRM, LLTV),
)


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


def expect_rejected(fn, *a, **k) -> str:
    try:
        fn(*a, **k)
    except BundleRejected as e:
        return str(e)
    raise AssertionError("expected BundleRejected, nothing raised")


def approve_call(spender: str, amount: int, to: str = USDC) -> dict:
    return {"to": to, "value": 0,
            "data": "0x095ea7b3" + abi_encode(["address", "uint256"], [spender, amount]).hex()}


def supply_call(amount=100_000_000, shares=0, on_behalf=SAFE, callback=b"", market=None, to=MORPHO) -> dict:
    return {"to": to, "value": 0,
            "data": "0xa99aad89" + abi_encode(
                ["(address,address,address,address,uint256)", "uint256", "uint256", "address", "bytes"],
                [market or PROFILE.market_params, amount, shares, on_behalf, callback]).hex()}


def withdraw_call(amount=50_000_000, shares=0, on_behalf=SAFE, receiver=SAFE) -> dict:
    return {"to": MORPHO, "value": 0,
            "data": "0x5c2bea49" + abi_encode(
                ["(address,address,address,address,uint256)", "uint256", "uint256", "address", "address"],
                [PROFILE.market_params, amount, shares, on_behalf, receiver]).hex()}


def native_supply_bundle(**kw) -> dict:
    """The exact shape the pinned compiler emitted in P00."""
    amount = kw.pop("amount", 100_000_000)
    approval = kw.pop("approval", 110_000_000)  # native 10% headroom
    return {"safe": SAFE, "calls": [approve_call(MORPHO, approval), supply_call(amount, **kw)]}


# ------------------------------------------------------------------ admission --
@test("admits the exact bundle the pinned compiler produced, headroom and all")
def _():
    op = admit_bundle(native_supply_bundle(), PROFILE, "decision-1", 0)
    assert op.action.family is ActionFamily.SUPPLY
    assert op.action.amount == 100_000_000, op.action.amount
    assert op.approval_amount == 110_000_000, "native headroom must be preserved, not rewritten"
    assert op.action.on_behalf == SAFE.lower()


@test("payload hash matches the controller's abi.encode layout exactly")
def _():
    op = admit_bundle(native_supply_bundle(), PROFILE, "decision-1", 0)
    expected = keccak(abi_encode(
        ["bytes32", "uint8", "bytes32", "address", "uint256", "address"],
        [ACTION_TYPEHASH, 1, PROFILE.market_id(), USDC.lower(), 100_000_000, SAFE.lower()]))
    assert op.payload_hash == expected
    # And the typehash itself is the string the contract declares.
    assert ACTION_TYPEHASH == keccak(
        b"Action(uint8 family,bytes32 marketId,address asset,uint256 amount,address onBehalf)")


@test("operation id is stable across repeated interception of the same decision")
def _():
    a = admit_bundle(native_supply_bundle(), PROFILE, "decision-1", 0)
    b = admit_bundle(native_supply_bundle(), PROFILE, "decision-1", 0)
    assert a.operation_id == b.operation_id, "a restart must reopen, not mint a new id"
    c = admit_bundle(native_supply_bundle(), PROFILE, "decision-2", 0)
    assert c.operation_id != a.operation_id


@test("admits a same-Safe withdraw")
def _():
    op = admit_bundle({"safe": SAFE, "calls": [withdraw_call()]}, PROFILE, "d", 0)
    assert op.action.family is ActionFamily.WITHDRAW
    assert op.approval_amount == 0


# ------------------------------------------------------------------ refusals --
@test("refuses an extra call smuggled into an otherwise valid bundle")
def _():
    b = native_supply_bundle()
    b["calls"].append(approve_call("0x000000000000000000000000000000000000dEaD", 1 << 255))
    msg = expect_rejected(admit_bundle, b, PROFILE, "d", 0)
    assert "unsupported call shape" in msg, msg


@test("refuses an unlimited or oversized approval")
def _():
    msg = expect_rejected(admit_bundle, native_supply_bundle(approval=2**256 - 1), PROFILE, "d", 0)
    assert "headroom ceiling" in msg, msg
    msg2 = expect_rejected(admit_bundle, native_supply_bundle(approval=200_000_000), PROFILE, "d", 0)
    assert "headroom ceiling" in msg2, msg2


@test("refuses an approval that does not cover the supplied amount")
def _():
    msg = expect_rejected(admit_bundle, native_supply_bundle(approval=99_000_000), PROFILE, "d", 0)
    assert "below the supplied amount" in msg, msg


@test("refuses an approval to a spender other than Morpho")
def _():
    b = {"safe": SAFE, "calls": [approve_call("0x000000000000000000000000000000000000dEaD", 110_000_000),
                                 supply_call()]}
    msg = expect_rejected(admit_bundle, b, PROFILE, "d", 0)
    assert "spender" in msg, msg


@test("refuses onBehalf pointing anywhere but the customer Safe")
def _():
    msg = expect_rejected(
        admit_bundle, native_supply_bundle(on_behalf="0x000000000000000000000000000000000000dEaD"),
        PROFILE, "d", 0)
    assert "onBehalf" in msg, msg


@test("refuses a withdraw to an arbitrary recipient")
def _():
    b = {"safe": SAFE, "calls": [withdraw_call(receiver="0x000000000000000000000000000000000000dEaD")]}
    msg = expect_rejected(admit_bundle, b, PROFILE, "d", 0)
    assert "receiver" in msg, msg


@test("refuses callback data on the economic call")
def _():
    msg = expect_rejected(admit_bundle, native_supply_bundle(callback=b"\x01"), PROFILE, "d", 0)
    assert "callback" in msg, msg


@test("refuses a shares-denominated action")
def _():
    msg = expect_rejected(admit_bundle, native_supply_bundle(amount=0, shares=5), PROFILE, "d", 0)
    assert "shares" in msg, msg


@test("refuses a foreign market")
def _():
    other = (USDC, COLL, ORACLE, IRM, 770000000000000000)
    msg = expect_rejected(admit_bundle, native_supply_bundle(market=other), PROFILE, "d", 0)
    assert "market" in msg, msg


@test("refuses trailing bytes appended to the calldata")
def _():
    b = native_supply_bundle()
    b["calls"][1]["data"] = b["calls"][1]["data"] + "00" * 32
    msg = expect_rejected(admit_bundle, b, PROFILE, "d", 0)
    assert "re-encode" in msg, msg


@test("refuses any call carrying ETH value")
def _():
    b = native_supply_bundle()
    b["calls"][1]["value"] = 1
    msg = expect_rejected(admit_bundle, b, PROFILE, "d", 0)
    assert "value" in msg, msg


@test("refuses a bundle whose Safe is not the profile Safe")
def _():
    b = native_supply_bundle()
    b["safe"] = "0x000000000000000000000000000000000000dEaD"
    msg = expect_rejected(admit_bundle, b, PROFILE, "d", 0)
    assert "Safe" in msg, msg


@test("refuses an economic call to a target other than Morpho")
def _():
    b = {"safe": SAFE, "calls": [approve_call(MORPHO, 110_000_000),
                                 supply_call(to="0x000000000000000000000000000000000000dEaD")]}
    msg = expect_rejected(admit_bundle, b, PROFILE, "d", 0)
    assert "unsupported call shape" in msg or "Morpho" in msg, msg


def main() -> int:
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"check-phase-03 (local interception): FAIL ({len(FAILED)}/{len(PASSED)+len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} P03 local interception tests held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
