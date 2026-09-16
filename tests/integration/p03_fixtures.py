"""Shared P03 test fixtures.

Extracted so the submission, recovery and binding suites build the same rig. The chain
reader here stands in for chain ACCESS, not chain BEHAVIOUR -- that the controller writes
consumed[id]=payloadHash in the same transaction as the economic effect is proven against
real pinned Morpho on the fork in P02.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (os.path.join(ROOT, "packages", "core"), os.path.join(ROOT, "adapter")):
    if p not in sys.path:
        sys.path.insert(0, p)

from held_adapter.execution.keeperhub import (  # noqa: E402
    HttpResponse,
    KeeperHubClient,
    OfflineTransport,
)
from held_adapter.execution.submit import ChainEvidence, Submitter  # noqa: E402
from held_adapter.signing.runner_signer import RunnerSigner  # noqa: E402
from held_core.identity import (  # noqa: E402
    ActionFamily,
    AuthorizationEnvelope,
    OperationScope,
    operation_id,
)
from held_core.journal import Journal  # noqa: E402

API_ENV = "HELD_KEEPERHUB_API_KEY"
FAKE_CREDENTIAL = "kh_local_test_credential_not_real"
# anvil account #3 -- public, well-known, local only, never custody.
RUNNER_KEY = "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6"
RUNNER = "0x90F79bf6EB2c4f870365E785982E1f101E93b906"
SAFE = "0x08deEDA0Ba1eb4B6B4b5cc4DD0c4BC689EA37180"
CONTROLLER = "0x3875311cc0d4017a033893a9653a0725378aca1c"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
COLL = "0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452"
ORACLE = "0xD7A1abA119a236Fea5BBC5cAC6836465cbe9289A"
IRM = "0x46415998764C29aB2a25CbeA6254146D50D22687"
LLTV = 860000000000000000
MARKET_PARAMS = (USDC, COLL, ORACLE, IRM, LLTV)
CHAIN_ID = 8453
SCOPE = OperationScope(CHAIN_ID, CONTROLLER, SAFE, "0x" + "11" * 32)

SOURCE_DECISION_ID = "decision-1"
ACTION_INDEX = 0
# DERIVED, not invented. operation_id() binds chain, controller, Safe and lineage, and
# the Submitter now re-derives it from the envelope scope before signing. A hardcoded
# 0xaa... id passed every earlier check because those checks compared copies of it.
OP_ID = operation_id(SCOPE, SOURCE_DECISION_ID, ACTION_INDEX)
OP_HEX = "0x" + OP_ID.hex()
EMPTY = "0x" + "00" * 32


class Action:
    family = ActionFamily.SUPPLY
    amount = 100_000_000
    on_behalf = SAFE.lower()


class Admitted:
    """The fields the Submitter reads off an AdmittedOperation."""

    operation_id = OP_ID
    source_decision_id = SOURCE_DECISION_ID
    action_index = ACTION_INDEX
    action = Action()

    def __init__(self, payload_hash: bytes | None = None):
        self.payload_hash = payload_hash if payload_hash is not None else _payload_hash()


def _payload_hash() -> bytes:
    """The action hash the controller will recompute. Kept consistent with envelope()."""
    from eth_abi import encode as abi_encode
    from eth_utils import keccak

    typehash = keccak(
        b"Action(uint8 family,bytes32 marketId,address asset,uint256 amount,address onBehalf)")
    market_id = keccak(abi_encode(
        ["address", "address", "address", "address", "uint256"], list(MARKET_PARAMS)))
    return keccak(abi_encode(
        ["bytes32", "uint8", "bytes32", "address", "uint256", "address"],
        [typehash, 1, market_id, USDC.lower(), 100_000_000, SAFE.lower()]))


PAYLOAD_HEX = "0x" + _payload_hash().hex()


def envelope(epoch: int = 1, payload_hash: bytes | None = None) -> AuthorizationEnvelope:
    return AuthorizationEnvelope(
        scope=SCOPE,
        operation_id=OP_ID,
        source_identity_hash=bytes.fromhex("bb" * 32),
        payload_hash=payload_hash if payload_hash is not None else _payload_hash(),
        action_family=ActionFamily.SUPPLY,
        epoch=epoch,
        policy_version=1,
        runner=RUNNER,
    )


class Chain:
    """Chain ACCESS stand-in. Returns whatever consumed[] was seeded with."""

    def __init__(self, marker: str = EMPTY, *, chain_id: int = CHAIN_ID,
                 controller: str = CONTROLLER, finalized: bool = True,
                 block_number: int = 51353212, controller_epoch: int | None = None) -> None:
        self.marker = marker
        self.chain_id = chain_id
        self.controller = controller
        self.finalized = finalized
        self.block_number = block_number
        self.controller_epoch = controller_epoch
        self.reads = 0

    def consumed(self, controller: str, operation_id: str) -> ChainEvidence:
        self.reads += 1
        # SYNTHETIC. block_hash is a fixture value, not an observed hash; `finalized` is
        # asserted by this stub rather than derived from a node. Tests that need real
        # provenance must read it from the fork, not from here.
        return ChainEvidence(
            marker=self.marker, chain_id=self.chain_id, controller=self.controller,
            block_number=self.block_number, block_hash="0x" + "ab" * 32,
            finalized=self.finalized, controller_epoch=self.controller_epoch)


def accepted(execution_id: str = "exec-1", tx_hash: str | None = None) -> HttpResponse:
    """A documented write success: 202 Accepted."""
    body = {"executionId": execution_id}
    if tx_hash:
        body["transactionHash"] = tx_hash
    return HttpResponse(202, json.dumps(body).encode(), {})


def response(body: dict, status: int = 200, headers: dict | None = None) -> HttpResponse:
    return HttpResponse(status, json.dumps(body).encode(), headers or {})


def rig(responses, *, path: str, transport=None, attempt_ids=None, now=None):
    """Journal + offline transport + submitter over a REAL SQLite file at `path`."""
    os.environ[API_ENV] = FAKE_CREDENTIAL
    os.environ["HELD_RUNNER_KEY"] = RUNNER_KEY
    j = Journal(path)
    t = transport if transport is not None else OfflineTransport(responses)
    c = KeeperHubClient(transport=t, sleep=lambda _: None)
    s = RunnerSigner("env:HELD_RUNNER_KEY", RUNNER)
    ids = iter(attempt_ids or [f"attempt-{i}" for i in range(1, 200)])
    sub = Submitter(j, c, s, CONTROLLER, CHAIN_ID, MARKET_PARAMS,
                    new_attempt_id=lambda: next(ids), now=now)
    return j, t, sub
