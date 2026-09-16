"""The three identities of V4 §4, and the line between them.

  1. **Business operation ID** — a stable native decision/action identity, scoped to
     chain, controller, Safe and mandate lineage. Deliberately does NOT include the
     epoch or the runner: "Its consumed identity does not reset when an epoch or
     runner changes." If the runner were in the preimage, replacing A with B would
     mint a fresh ID for the same business operation and the consumed-ID check would
     stop protecting anything across exactly the handover it exists to survive.

  2. **Authorization envelope** — binds the operation ID to the payload AND to the
     current epoch, policy version and runner. This is what the runner signs, so an
     envelope signed under epoch N is worthless under epoch N+1 even though the
     operation ID is unchanged.

  3. **Transaction/API attempt** — evidence about attempts, never a business
     identity. Lives in journal.py.

The asymmetry between (1) and (2) is the whole point and is covered by
tests/core/test_identity.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from eth_abi import encode as abi_encode
from eth_utils import keccak

from .canonical import canonical_hash, hex32, normalize_address, normalize_hash
from .units import UINT64_MAX, UnitError, to_decimal_string, uint, uint64

OPERATION_ID_SCHEMA = "held.operation-id.v1"
ACTION_SCHEMA = "held.action.v1"
ENVELOPE_SCHEMA = "held.envelope.v1"

EIP712_DOMAIN_NAME = "Held"
EIP712_DOMAIN_VERSION = "1"

# The signed struct. Field order is part of the type hash and must not be reordered.
ENVELOPE_TYPE = (
    b"Envelope(bytes32 operationId,bytes32 sourceIdentityHash,bytes32 payloadHash,"
    b"uint8 actionFamily,address safe,bytes32 lineage,uint64 epoch,"
    b"uint32 policyVersion,address runner)"
)
ENVELOPE_TYPEHASH = keccak(ENVELOPE_TYPE)

DOMAIN_TYPE = b"EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
DOMAIN_TYPEHASH = keccak(DOMAIN_TYPE)


class ActionFamily(IntEnum):
    """V4 §2 supported native actions. The numeric values are part of the signed
    envelope, so they are frozen: never renumber, only append."""

    HOLD = 0
    SUPPLY = 1
    WITHDRAW = 2


class IdentityConflict(Exception):
    """A payload was presented under an operation ID already bound to a different one."""


@dataclass(frozen=True)
class SupportedAction:
    """One admitted economic action. V4 §2: fixed-asset SUPPLY, fixed-asset WITHDRAW
    to the same Safe, or HOLD.

    `on_behalf` is Morpho's account field. V4 §2 is explicit that it is **onBehalf**,
    and that the compiler's Morpho helper living in a file called aave_helpers.py does
    not make this an Aave integration.
    """

    family: ActionFamily
    market_id: str
    asset: str
    amount: int
    on_behalf: str

    def __post_init__(self) -> None:
        if not isinstance(self.family, ActionFamily):
            raise UnitError(f"family: expected ActionFamily, got {type(self.family).__name__}")
        object.__setattr__(self, "market_id", normalize_hash(self.market_id, "market_id"))
        object.__setattr__(self, "asset", normalize_address(self.asset, "asset"))
        object.__setattr__(self, "on_behalf", normalize_address(self.on_behalf, "on_behalf"))
        uint(self.amount, "amount")
        if self.family is ActionFamily.HOLD:
            # V4 §5: HOLD is "no executable economic call, consumed operation or
            # transaction claim". A HOLD carrying an amount is a contradiction.
            if self.amount != 0:
                raise UnitError(f"amount: HOLD must carry amount 0, got {self.amount}")
        elif self.amount == 0:
            # No MAX/all sentinel exists (V4 §2), and a zero economic action is not a
            # supported action -- it is a HOLD that has been mislabelled.
            raise UnitError("amount: a supported economic action must move a positive amount")

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": ACTION_SCHEMA,
            "family": self.family.name,
            "market_id": self.market_id,
            "asset": self.asset,
            "amount": to_decimal_string(self.amount, "amount"),
            "on_behalf": self.on_behalf,
        }

    def payload_hash(self) -> bytes:
        return canonical_hash(self.to_canonical())


@dataclass(frozen=True)
class OperationScope:
    """What an operation ID is scoped to. Epoch and runner are absent on purpose."""

    chain_id: int
    controller: str
    safe: str
    lineage: str

    def __post_init__(self) -> None:
        uint(self.chain_id, "chain_id")
        object.__setattr__(self, "controller", normalize_address(self.controller, "controller"))
        object.__setattr__(self, "safe", normalize_address(self.safe, "safe"))
        object.__setattr__(self, "lineage", normalize_hash(self.lineage, "lineage"))

    def to_canonical(self) -> dict[str, Any]:
        return {
            "chain_id": to_decimal_string(self.chain_id, "chain_id"),
            "controller": self.controller,
            "safe": self.safe,
            "lineage": self.lineage,
        }


def operation_id(scope: OperationScope, source_decision_id: str, action_index: int) -> bytes:
    """The stable business identity of one action of one native decision.

    P01 requirement: "establish a stable native decision identifier or persist a
    generated ID once at the native decision boundary. Restarts must reopen that
    decision rather than manufacture a new ID." This function is pure, so a restart
    that reloads the same source decision recomputes the same ID rather than minting
    a new one.
    """
    if not isinstance(source_decision_id, str) or not source_decision_id:
        raise UnitError("source_decision_id: must be a non-empty string")
    uint(action_index, "action_index", maximum=UINT64_MAX)
    return canonical_hash(
        {
            "schema": OPERATION_ID_SCHEMA,
            "scope": scope.to_canonical(),
            "source_decision_id": source_decision_id,
            "action_index": to_decimal_string(action_index, "action_index"),
        }
    )


@dataclass(frozen=True)
class AuthorizationEnvelope:
    """What the runner signs for one attempt at one operation, under one epoch."""

    scope: OperationScope
    operation_id: bytes
    source_identity_hash: bytes
    payload_hash: bytes
    action_family: ActionFamily
    epoch: int
    policy_version: int
    runner: str

    def __post_init__(self) -> None:
        for name in ("operation_id", "source_identity_hash", "payload_hash"):
            v = getattr(self, name)
            if not isinstance(v, bytes) or len(v) != 32:
                raise UnitError(f"{name}: expected 32 bytes")
        if self.action_family is ActionFamily.HOLD:
            # V4 §5 again: a HOLD consumes no operation and makes no transaction
            # claim, so there is nothing for a runner to authorize.
            raise UnitError("action_family: HOLD is never authorized for execution")
        uint64(self.epoch, "epoch")
        uint(self.policy_version, "policy_version", maximum=(1 << 32) - 1)
        object.__setattr__(self, "runner", normalize_address(self.runner, "runner"))

    def domain_separator(self) -> bytes:
        return keccak(
            abi_encode(
                ["bytes32", "bytes32", "bytes32", "uint256", "address"],
                [
                    DOMAIN_TYPEHASH,
                    keccak(EIP712_DOMAIN_NAME.encode()),
                    keccak(EIP712_DOMAIN_VERSION.encode()),
                    self.scope.chain_id,
                    self.scope.controller,
                ],
            )
        )

    def hash_struct(self) -> bytes:
        return keccak(
            abi_encode(
                [
                    "bytes32", "bytes32", "bytes32", "bytes32",
                    "uint8", "address", "bytes32", "uint64", "uint32", "address",
                ],
                [
                    ENVELOPE_TYPEHASH,
                    self.operation_id,
                    self.source_identity_hash,
                    self.payload_hash,
                    int(self.action_family),
                    self.scope.safe,
                    bytes.fromhex(self.scope.lineage[2:]),
                    self.epoch,
                    self.policy_version,
                    self.runner,
                ],
            )
        )

    def signing_hash(self) -> bytes:
        """EIP-712: keccak(0x19 0x01 ‖ domainSeparator ‖ hashStruct)."""
        return keccak(b"\x19\x01" + self.domain_separator() + self.hash_struct())

    def to_typed_data(self) -> dict[str, Any]:
        """The same message as an EIP-712 typed-data document.

        Exists so the hand-rolled encoding above can be checked against an
        independent implementation (eth_account) in the tests, rather than trusted.
        """
        return {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "Envelope": [
                    {"name": "operationId", "type": "bytes32"},
                    {"name": "sourceIdentityHash", "type": "bytes32"},
                    {"name": "payloadHash", "type": "bytes32"},
                    {"name": "actionFamily", "type": "uint8"},
                    {"name": "safe", "type": "address"},
                    {"name": "lineage", "type": "bytes32"},
                    {"name": "epoch", "type": "uint64"},
                    {"name": "policyVersion", "type": "uint32"},
                    {"name": "runner", "type": "address"},
                ],
            },
            "primaryType": "Envelope",
            "domain": {
                "name": EIP712_DOMAIN_NAME,
                "version": EIP712_DOMAIN_VERSION,
                "chainId": self.scope.chain_id,
                "verifyingContract": self.scope.controller,
            },
            "message": {
                "operationId": self.operation_id,
                "sourceIdentityHash": self.source_identity_hash,
                "payloadHash": self.payload_hash,
                "actionFamily": int(self.action_family),
                "safe": self.scope.safe,
                "lineage": self.scope.lineage,
                "epoch": self.epoch,
                "policyVersion": self.policy_version,
                "runner": self.runner,
            },
        }

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": ENVELOPE_SCHEMA,
            "scope": self.scope.to_canonical(),
            "operation_id": hex32(self.operation_id),
            "source_identity_hash": hex32(self.source_identity_hash),
            "payload_hash": hex32(self.payload_hash),
            "action_family": self.action_family.name,
            "epoch": to_decimal_string(self.epoch, "epoch"),
            "policy_version": to_decimal_string(self.policy_version, "policy_version"),
            "runner": self.runner,
            "signing_hash": hex32(self.signing_hash()),
        }
