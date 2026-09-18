"""Reading the controller off an actual chain, with the scope that makes it meaningful.

`readback.read_controller_state` takes a `ControllerSource` so the machine can be tested
without a chain. This is the real one: it shells out to `cast`, the same tool the bootstrap
collector uses, against a stated RPC.

Everything it returns is labelled with where it came from. A reading that cannot state its
chain, its controller and whether it was finalized is not evidence, and `readback` will
classify it OBSERVATION_INCOMPLETE rather than guess.
"""
from __future__ import annotations

import os
import re
import subprocess
from types import SimpleNamespace
from typing import Any

_UINT = re.compile(r"^\d+$")
_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")


class CastControllerSource:
    """Read the controller with `cast`, every value pinned to ONE block.

    Finality is established, never asserted. An anvil fork has no meaningful finality, so a
    fork read supplies no finality source and its evidence is graded REAL LOCAL FORK.
    Claiming finality a fork cannot provide is exactly the promotion between evidence
    classes this project refuses to make.
    """

    def __init__(self, rpc: str, *, block: str | None = None,
                 finality_source: Any = None) -> None:
        """`block` pins the observation. Left None, ONE block is resolved per read and
        every call in that read is pinned to it.

        The previous version fetched `block-number`, reported it, and then pinned nothing
        unless a block had been supplied at construction -- so the reported block could be
        N while active/epoch/runner/counters were read over N, N+1, N+2. That can produce a
        state combination which never existed simultaneously, which is precisely what a
        handover decision must not be made on.

        `finalized` is no longer a boolean a caller may simply assert. Finality is
        ESTABLISHED by asking `finality_source` for the finalized block number and
        comparing; with no source, the reading is not finalized and is graded accordingly.
        """
        self.rpc = rpc
        self.block = block
        self.finality_source = finality_source

    def _cast(self, *args: str, at: str | None = None) -> str | None:
        cmd = ["cast", *args, "--rpc-url", self.rpc]
        pin = at if at is not None else self.block
        if pin and args and args[0] in ("call", "storage"):
            cmd += ["--block", str(pin)]
        out = subprocess.run(cmd, capture_output=True, text=True,
                             env={**os.environ,
                                  "PATH": f"{os.path.expanduser('~')}/.foundry/bin:"
                                          f"{os.environ.get('PATH', '')}"})
        if out.returncode != 0:
            return None
        return out.stdout.strip() or None

    def _uint(self, raw: str | None) -> int | None:
        if raw is None:
            return None
        head = raw.split()[0] if raw.split() else ""
        return int(head) if _UINT.match(head) else None

    def _addr(self, raw: str | None) -> str | None:
        if raw is None:
            return None
        head = raw.split()[0] if raw.split() else ""
        return head if _ADDR.match(head) else None

    def _resolve_block(self) -> str | None:
        """ONE observation boundary, resolved before any state is read."""
        if self.block:
            return str(self.block)
        return self._cast("block-number")

    def _finalized_at(self, block: str | None) -> bool:
        """Establish finality rather than accept an assertion about it."""
        if self.finality_source is None or block is None:
            return False
        try:
            finalized_block = self.finality_source.finalized_block_number()
        except Exception:  # noqa: BLE001 - unknown finality is not finality
            return False
        return isinstance(finalized_block, int) and int(block) <= finalized_block

    def read_controller(self, controller: str) -> dict[str, Any] | None:
        block = self._resolve_block()
        if block is None:
            return None
        chain_id = self._uint(self._cast("chain-id"))
        block_hash = self._cast("block", str(block), "--field", "hash")
        active_raw = self._cast("call", controller, "active()(bool)", at=block)
        if active_raw is None or chain_id is None:
            return None
        active = active_raw.strip().lower()
        if active not in ("true", "false"):
            return None

        out: dict[str, Any] = {
            "chainId": chain_id,
            "controller": controller,
            "active": active == "true",
            "epoch": self._uint(self._cast("call", controller, "epoch()(uint64)", at=block)),
            "runner": self._addr(self._cast("call", controller, "runner()(address)", at=block)),
            "executor": self._addr(
                self._cast("call", controller, "executor()(address)", at=block)),
            "policyVersion": self._uint(
                self._cast("call", controller, "policyVersion()(uint32)", at=block)),
            "lineage": self._cast("call", controller, "lineage()(bytes32)", at=block),
            "blockNumber": self._uint(block),
            "blockHash": block_hash,
            "finalized": self._finalized_at(block),
        }
        for name, typ in (("usedSupply", "uint128"), ("usedNormalWithdraw", "uint128"),
                          ("usedRestoration", "uint128"), ("normalCount", "uint64"),
                          ("restorationCount", "uint64")):
            out[name] = self._uint(self._cast("call", controller, f"{name}()({typ})", at=block))

        # A public struct getter returns its members individually, so the full return
        # signature is required -- without it cast hands back an undecoded blob and the
        # console silently had no policy to show.
        policy_sig = ("policy()(uint128,uint128,uint128,uint128,uint128,uint128,uint128,"
                      "uint128,uint128,uint128,uint64,uint64,uint64,uint64)")
        policy_raw = self._cast("call", controller, policy_sig, at=block)
        if policy_raw:
            out["policyRaw"] = policy_raw
        return out


class CastConsumptionReader:
    """Read `consumed[operationId]` off the chain, with the scope that makes it evidence.

    Reconciliation's verdict comes from here and nowhere else. A transport's silence says
    nothing about whether an operation executed; this does.
    """

    def __init__(self, rpc: str, *, chain_id: int, block: str | None = None,
                 finality_source: Any = None) -> None:
        self._src = CastControllerSource(rpc, block=block, finality_source=finality_source)
        self.chain_id = chain_id

    def consumed(self, controller: str, operation_id: str):
        block = self._src._resolve_block()  # noqa: SLF001 - one boundary per read
        marker = self._src._cast(  # noqa: SLF001
            "call", controller, "consumed(bytes32)(bytes32)", operation_id, at=block)
        if marker is None:
            raise RuntimeError("the consumption read failed")
        return SimpleNamespace(
            marker=marker.split()[0] if marker.split() else marker,
            chain_id=self.chain_id,
            controller=controller,
            block_number=self._src._uint(block),  # noqa: SLF001
            block_hash=self._src._cast("block", str(block), "--field", "hash"),  # noqa: SLF001
            finalized=self._src._finalized_at(block),  # noqa: SLF001
        )
