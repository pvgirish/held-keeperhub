"""What the controller ACTUALLY says, kept apart from what Held wishes were true.

P04 required work 8: "Separate observed UI state from on-chain state after readback failure
or reorg; adapter stop is not owner fence."

That sentence is the whole module. Four situations look identical in a naive UI and are
completely different in their safety properties:

  CONTRACT_ACTIVE          the controller is live and will honour a correctly signed
                           envelope from the current runner
  OWNER_FENCED             `active == false` on chain. The runner cannot act, full stop
  ADAPTER_REFUSING         Held's own dispatcher declines to send, but the controller is
                           STILL ACTIVE. Anyone holding a valid signature and the executor
                           route can still move funds. This is NOT a fence
  OBSERVATION_INCOMPLETE    the readback failed, was unfinalized, or came from the wrong
                           chain or controller. Nothing is known, and an unknown is not a
                           verified negative

Reporting ADAPTER_REFUSING as though it were OWNER_FENCED is the most dangerous mistake
available here, because it would tell an owner their funds were fenced while the on-chain
authorization they are worried about was still live.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class ControllerStatus(str, Enum):
    CONTRACT_ACTIVE = "CONTRACT_ACTIVE"
    OWNER_FENCED = "OWNER_FENCED"
    ADAPTER_REFUSING = "ADAPTER_REFUSING"
    OBSERVATION_INCOMPLETE = "OBSERVATION_INCOMPLETE"


class ReadbackError(Exception):
    """The controller's state could not be established."""


@dataclass(frozen=True)
class ControllerReading:
    """One observation of the controller, with the scope that makes it meaningful."""

    status: ControllerStatus
    active: bool | None
    epoch: int | None
    runner: str | None
    executor: str | None
    policy_version: int | None
    used: dict[str, int]
    chain_id: int | None
    controller: str | None
    block_number: int | None
    block_hash: str | None
    lineage: str | None
    policy_raw: str | None
    finalized: bool
    adapter_dispatching: bool
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.status is not ControllerStatus.OBSERVATION_INCOMPLETE

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value, "active": self.active, "epoch": self.epoch,
            "runner": self.runner, "executor": self.executor,
            "policyVersion": self.policy_version, "used": self.used,
            "chainId": self.chain_id, "controller": self.controller,
            "blockNumber": self.block_number, "blockHash": self.block_hash,
            "lineage": self.lineage, "finalized": self.finalized,
            "adapterDispatching": self.adapter_dispatching, "reason": self.reason,
            "evidenceGrade": "REAL LOCAL FORK" if self.chain_id == 8453 and not self.finalized
                             else "PUBLIC CHAIN" if self.finalized else "UNKNOWN",
        }


class ControllerSource(Protocol):
    """Minimum access a readback needs. Implemented by a fork reader or an RPC reader."""

    def read_controller(self, controller: str) -> dict[str, Any]: ...


def read_controller_state(
    source: ControllerSource,
    *,
    controller: str,
    expected_chain_id: int,
    adapter_dispatching: bool,
    require_finalized: bool = False,
) -> ControllerReading:
    """Classify the controller's state, refusing to guess.

    `adapter_dispatching` is Held's OWN state and is never allowed to stand in for the
    chain's. It only distinguishes CONTRACT_ACTIVE from ADAPTER_REFUSING once the chain has
    already told us the controller is active.
    """
    blank = dict(active=None, epoch=None, runner=None, executor=None, policy_version=None,
                 used={}, chain_id=None, controller=controller, block_number=None,
                 block_hash=None, lineage=None, policy_raw=None,
                 finalized=False, adapter_dispatching=adapter_dispatching)

    try:
        raw = source.read_controller(controller)
    except Exception as exc:  # noqa: BLE001 - any failure is an incomplete observation
        return ControllerReading(status=ControllerStatus.OBSERVATION_INCOMPLETE,
                                 reason=f"the controller read failed: {exc}", **blank)

    if raw is None:
        return ControllerReading(status=ControllerStatus.OBSERVATION_INCOMPLETE,
                                 reason="the controller read returned nothing", **blank)

    chain_id = raw.get("chainId")
    got_controller = raw.get("controller")
    active = raw.get("active")
    epoch = raw.get("epoch")

    if chain_id != expected_chain_id:
        return ControllerReading(
            status=ControllerStatus.OBSERVATION_INCOMPLETE,
            reason=f"the reading is from chain {chain_id}, not {expected_chain_id}; the "
                   "same bytes from the wrong chain say nothing about this installation",
            **{**blank, "chain_id": chain_id})

    if not isinstance(got_controller, str) or got_controller.lower() != controller.lower():
        return ControllerReading(
            status=ControllerStatus.OBSERVATION_INCOMPLETE,
            reason=f"the reading is of controller {got_controller}, not {controller}",
            **{**blank, "chain_id": chain_id})

    if not isinstance(active, bool) or not isinstance(epoch, int):
        return ControllerReading(
            status=ControllerStatus.OBSERVATION_INCOMPLETE,
            reason="active/epoch did not come back as usable values; a malformed read is "
                   "not a paused controller",
            **{**blank, "chain_id": chain_id})

    finalized = bool(raw.get("finalized", False))
    if require_finalized and not finalized:
        return ControllerReading(
            status=ControllerStatus.OBSERVATION_INCOMPLETE,
            reason="the reading is not finalized and this step requires finality; an "
                   "unfinalized state can be reorganised away",
            **{**blank, "chain_id": chain_id, "finalized": finalized})

    used = {k: raw.get(k) for k in ("usedSupply", "usedNormalWithdraw", "usedRestoration",
                                    "normalCount", "restorationCount")}
    if any(not isinstance(v, int) for v in used.values()):
        return ControllerReading(
            status=ControllerStatus.OBSERVATION_INCOMPLETE,
            reason=f"consumption did not come back as integers: {used}",
            **{**blank, "chain_id": chain_id, "finalized": finalized})

    common = dict(active=active, epoch=epoch, runner=raw.get("runner"),
                  executor=raw.get("executor"), policy_version=raw.get("policyVersion"),
                  used=used, chain_id=chain_id, controller=controller,
                  block_number=raw.get("blockNumber"), block_hash=raw.get("blockHash"),
                  lineage=raw.get("lineage"), policy_raw=raw.get("policyRaw"),
                  finalized=finalized, adapter_dispatching=adapter_dispatching)

    if not active:
        return ControllerReading(
            status=ControllerStatus.OWNER_FENCED,
            reason=f"the controller is paused on chain at epoch {epoch}. The runner's "
                   "authorization is not honoured, whatever Held's adapter is doing.",
            **common)

    if adapter_dispatching:
        return ControllerReading(
            status=ControllerStatus.CONTRACT_ACTIVE,
            reason=f"the controller is active at epoch {epoch} and Held is dispatching.",
            **common)

    return ControllerReading(
        status=ControllerStatus.ADAPTER_REFUSING,
        reason=f"Held's adapter is NOT dispatching, but the controller is still ACTIVE at "
               f"epoch {epoch}. This is not a fence: a correctly signed envelope from the "
               "current runner would still execute. To actually stop it, the owner must "
               "call fence().",
        **common)
