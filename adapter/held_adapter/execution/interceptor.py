"""Intercept the native ActionBundle BEFORE Zodiac/Safe wrapping and signing.

V4 §3: "Intercept the native ActionBundle before Zodiac/Safe wrapping and signing.
Preserve native risk validation and receipt/result semantics." This module does the
admission half of that seam: it takes the bundle the native Almanak compiler actually
produced and decides whether it is exactly one supported economic action.

Two rules shape everything here:

  * **Decode the real bytes.** Never trust a `decoded` field an adapter happens to
    expose. Every check below runs against the calldata the compiler emitted, and a
    strict re-encode rejects trailing bytes.
  * **Admit the WHOLE bundle, not each call.** A per-call check that says "this approve
    is fine" and "this supply is fine" will happily admit a bundle containing a third
    call that drains the Safe. The call list is matched as a shape.

The native approval carries headroom — the pinned compiler emitted `approve(Morpho,
110000000)` for a 100000000-unit supply. That is native behaviour and is NOT rewritten
here; it is bounded and recorded. Held's own zero-allowance entry/exit requirement is
enforced by the controller at execution time (P02), not by editing native output.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import keccak

sys.path.insert(0, __file__.rsplit("/adapter/", 1)[0] + "/packages/core")

from held_core.canonical import hex32, normalize_address  # noqa: E402
from held_core.identity import ActionFamily, OperationScope, SupportedAction, operation_id  # noqa: E402

SELECTOR_APPROVE = bytes.fromhex("095ea7b3")
SELECTOR_SUPPLY = bytes.fromhex("a99aad89")
SELECTOR_WITHDRAW = bytes.fromhex("5c2bea49")

# Must equal HeldController.ACTION_TYPEHASH byte for byte, or the envelope the runner
# signs will not bind the action the controller reconstructs. Verified against the
# deployed contract in tests/integration.
ACTION_TYPEHASH = keccak(
    b"Action(uint8 family,bytes32 marketId,address asset,uint256 amount,address onBehalf)"
)

MARKET_PARAMS_TYPES = ["(address,address,address,address,uint256)"]
SUPPLY_ARG_TYPES = ["(address,address,address,address,uint256)", "uint256", "uint256", "address", "bytes"]
WITHDRAW_ARG_TYPES = ["(address,address,address,address,uint256)", "uint256", "uint256", "address", "address"]

# The compiler's observed headroom. A bound, not a licence: an unlimited or wildly
# oversized approval is refused.
MAX_APPROVAL_HEADROOM_BPS = 2000  # 20%


class BundleRejected(Exception):
    """The native bundle is not exactly one supported economic action."""


@dataclass(frozen=True)
class Profile:
    """The single supported profile this adapter will admit for (V4 §2)."""

    chain_id: int
    controller: str
    safe: str
    lineage: str
    morpho: str
    token: str
    market_params: tuple  # (loan, collateral, oracle, irm, lltv)

    def __post_init__(self) -> None:
        # Normalise on the way in. Every comparison below is against a normalised
        # address, and an EIP-55 checksummed profile value would otherwise never match
        # -- which is exactly the case hazard canonical.py warns about, and exactly the
        # bug the interception tests caught here.
        for field in ("controller", "safe", "morpho", "token"):
            object.__setattr__(self, field, normalize_address(getattr(self, field), f"profile.{field}"))
        object.__setattr__(
            self,
            "market_params",
            (
                normalize_address(self.market_params[0], "market.loanToken"),
                normalize_address(self.market_params[1], "market.collateralToken"),
                normalize_address(self.market_params[2], "market.oracle"),
                normalize_address(self.market_params[3], "market.irm"),
                int(self.market_params[4]),
            ),
        )

    def market_id(self) -> bytes:
        return keccak(abi_encode(MARKET_PARAMS_TYPES, [self.market_params]))

    def scope(self) -> OperationScope:
        return OperationScope(self.chain_id, self.controller, self.safe, self.lineage)


@dataclass(frozen=True)
class AdmittedOperation:
    """What the adapter will ask the runner to authorize."""

    action: SupportedAction
    operation_id: bytes
    payload_hash: bytes  # the ON-CHAIN action hash the controller recomputes
    approval_amount: int  # 0 for withdraw
    source_decision_id: str
    action_index: int

    def to_record(self) -> dict[str, Any]:
        return {
            "operation_id": hex32(self.operation_id),
            "payload_hash": hex32(self.payload_hash),
            "family": self.action.family.name,
            "amount": str(self.action.amount),
            "on_behalf": self.action.on_behalf,
            "approval_amount": str(self.approval_amount),
            "source_decision_id": self.source_decision_id,
            "action_index": self.action_index,
        }


def onchain_action_hash(family: ActionFamily, market_id: bytes, asset: str, amount: int, on_behalf: str) -> bytes:
    """The payload hash the CONTROLLER computes.

    Distinct from `SupportedAction.payload_hash()`, which is the canonical-JSON hash used
    for the journal's cross-language record. This one must match Solidity's
    `abi.encode` layout exactly, because the controller recomputes it from the typed
    action and compares it to the signed envelope.
    """
    return keccak(
        abi_encode(
            ["bytes32", "uint8", "bytes32", "address", "uint256", "address"],
            [ACTION_TYPEHASH, int(family), market_id, normalize_address(asset, "asset"),
             amount, normalize_address(on_behalf, "on_behalf")],
        )
    )


def _call_fields(call: Mapping[str, Any] | Any) -> tuple[str, bytes, int]:
    def get(name: str, default: Any = None) -> Any:
        if isinstance(call, Mapping):
            return call.get(name, default)
        return getattr(call, name, default)

    to = get("to")
    data = get("data")
    value = get("value", 0)
    if not isinstance(to, str):
        raise BundleRejected(f"call target is not an address: {to!r}")
    if isinstance(data, str):
        data = bytes.fromhex(data[2:] if data.startswith("0x") else data)
    if not isinstance(data, (bytes, bytearray)):
        raise BundleRejected("call data is neither hex string nor bytes")
    if int(value or 0) != 0:
        raise BundleRejected(f"call carries non-zero value {value}: no ETH movement is supported")
    return normalize_address(to, "call.to"), bytes(data), int(value or 0)


def _strict_decode(types: Sequence[str], payload: bytes, what: str) -> tuple:
    """Decode, then re-encode and require equality. Rejects trailing bytes."""
    try:
        decoded = abi_decode(list(types), payload)
    except Exception as exc:  # noqa: BLE001
        raise BundleRejected(f"{what}: undecodable arguments ({type(exc).__name__})") from None
    if abi_encode(list(types), list(decoded)) != payload:
        raise BundleRejected(f"{what}: arguments do not re-encode exactly (trailing or non-canonical bytes)")
    return decoded


def admit_bundle(
    bundle: Mapping[str, Any] | Any,
    profile: Profile,
    source_decision_id: str,
    action_index: int = 0,
) -> AdmittedOperation:
    """Admit a native bundle as exactly one supported action, or raise.

    SUPPLY is two calls: a bounded approval to Morpho, then the unchanged economic
    call. WITHDRAW is one call and needs no approval. Anything else is refused.
    """
    safe = bundle.get("safe") if isinstance(bundle, Mapping) else getattr(bundle, "safe", None)
    raw_calls = bundle.get("calls") if isinstance(bundle, Mapping) else getattr(bundle, "calls", None)
    if not isinstance(raw_calls, (list, tuple)) or not raw_calls:
        raise BundleRejected("bundle has no calls")
    if safe is not None and normalize_address(safe, "bundle.safe") != profile.safe:
        raise BundleRejected(f"bundle targets Safe {safe}, profile Safe is {profile.safe}")

    calls = [_call_fields(c) for c in raw_calls]
    selectors = [c[1][:4] for c in calls]

    if selectors == [SELECTOR_APPROVE, SELECTOR_SUPPLY]:
        return _admit_supply(calls, profile, source_decision_id, action_index)
    if selectors == [SELECTOR_WITHDRAW]:
        return _admit_withdraw(calls, profile, source_decision_id, action_index)
    raise BundleRejected(
        "unsupported call shape: "
        + ", ".join("0x" + s.hex() for s in selectors)
        + " (expected approve+supply, or withdraw alone)"
    )


def _admit_supply(calls, profile: Profile, source_decision_id: str, action_index: int) -> AdmittedOperation:
    (approve_to, approve_data, _), (supply_to, supply_data, _) = calls

    if approve_to != profile.token:
        raise BundleRejected(f"approval targets {approve_to}, not the profile token {profile.token}")
    spender, approval_amount = _strict_decode(["address", "uint256"], approve_data[4:], "approve")
    if normalize_address(spender, "approve.spender") != profile.morpho:
        raise BundleRejected(f"approval spender is {spender}, not Morpho {profile.morpho}")

    if supply_to != profile.morpho:
        raise BundleRejected(f"economic call targets {supply_to}, not Morpho {profile.morpho}")
    market, assets, shares, on_behalf, callback = _strict_decode(
        SUPPLY_ARG_TYPES, supply_data[4:], "supply"
    )

    if tuple(market) != tuple(profile.market_params):
        raise BundleRejected("supply market parameters do not match the profile market")
    if keccak(abi_encode(MARKET_PARAMS_TYPES, [tuple(market)])) != profile.market_id():
        raise BundleRejected("derived market id does not match the profile market id")
    if shares != 0:
        raise BundleRejected(f"supply uses shares={shares}; only fixed-asset amounts are supported")
    if normalize_address(on_behalf, "supply.onBehalf") != profile.safe:
        raise BundleRejected(f"supply onBehalf is {on_behalf}, not the customer Safe {profile.safe}")
    if callback:
        raise BundleRejected("supply carries callback data; callbacks are not supported")
    if assets <= 0:
        raise BundleRejected("supply amount must be positive")

    # The approval must cover the amount and must not be unlimited or wildly oversized.
    if approval_amount < assets:
        raise BundleRejected(f"approval {approval_amount} is below the supplied amount {assets}")
    ceiling = assets + (assets * MAX_APPROVAL_HEADROOM_BPS) // 10_000
    if approval_amount > ceiling:
        raise BundleRejected(
            f"approval {approval_amount} exceeds the permitted headroom ceiling {ceiling} "
            f"for a {assets}-unit supply"
        )

    action = SupportedAction(ActionFamily.SUPPLY, hex32(profile.market_id()), profile.token, assets, profile.safe)
    return AdmittedOperation(
        action=action,
        operation_id=operation_id(profile.scope(), source_decision_id, action_index),
        payload_hash=onchain_action_hash(
            ActionFamily.SUPPLY, profile.market_id(), profile.token, assets, profile.safe
        ),
        approval_amount=approval_amount,
        source_decision_id=source_decision_id,
        action_index=action_index,
    )


def _admit_withdraw(calls, profile: Profile, source_decision_id: str, action_index: int) -> AdmittedOperation:
    (to, data, _), = calls
    if to != profile.morpho:
        raise BundleRejected(f"economic call targets {to}, not Morpho {profile.morpho}")
    market, assets, shares, on_behalf, receiver = _strict_decode(
        WITHDRAW_ARG_TYPES, data[4:], "withdraw"
    )
    if tuple(market) != tuple(profile.market_params):
        raise BundleRejected("withdraw market parameters do not match the profile market")
    if shares != 0:
        raise BundleRejected(f"withdraw uses shares={shares}; only fixed-asset amounts are supported")
    if normalize_address(on_behalf, "withdraw.onBehalf") != profile.safe:
        raise BundleRejected(f"withdraw onBehalf is {on_behalf}, not the customer Safe")
    # V4 §2: WITHDRAW is to the SAME Safe. An arbitrary recipient is the whole risk.
    if normalize_address(receiver, "withdraw.receiver") != profile.safe:
        raise BundleRejected(f"withdraw receiver is {receiver}, not the customer Safe {profile.safe}")
    if assets <= 0:
        raise BundleRejected("withdraw amount must be positive")

    action = SupportedAction(ActionFamily.WITHDRAW, hex32(profile.market_id()), profile.token, assets, profile.safe)
    return AdmittedOperation(
        action=action,
        operation_id=operation_id(profile.scope(), source_decision_id, action_index),
        payload_hash=onchain_action_hash(
            ActionFamily.WITHDRAW, profile.market_id(), profile.token, assets, profile.safe
        ),
        approval_amount=0,
        source_decision_id=source_decision_id,
        action_index=action_index,
    )
