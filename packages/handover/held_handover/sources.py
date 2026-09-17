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
from typing import Any

_UINT = re.compile(r"^\d+$")
_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")


class CastControllerSource:
    """Read the controller with `cast`, pinned to one block.

    `finalized` is NOT inferred. An anvil fork has no meaningful finality, so a caller
    reading a fork must pass `finalized=False` and the evidence is graded REAL LOCAL FORK.
    Claiming finality a fork cannot provide is exactly the promotion between evidence
    classes this project refuses to make.
    """

    def __init__(self, rpc: str, *, block: str | None = None, finalized: bool = False) -> None:
        self.rpc = rpc
        self.block = block
        self.finalized = finalized

    def _cast(self, *args: str) -> str | None:
        cmd = ["cast", *args, "--rpc-url", self.rpc]
        if self.block and args and args[0] == "call":
            cmd += ["--block", self.block]
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

    def read_controller(self, controller: str) -> dict[str, Any] | None:
        block = self.block or self._cast("block-number")
        chain_id = self._uint(self._cast("chain-id"))
        active_raw = self._cast("call", controller, "active()(bool)")
        if active_raw is None or chain_id is None:
            return None
        active = active_raw.strip().lower()
        if active not in ("true", "false"):
            return None

        out: dict[str, Any] = {
            "chainId": chain_id,
            "controller": controller,
            "active": active == "true",
            "epoch": self._uint(self._cast("call", controller, "epoch()(uint64)")),
            "runner": self._addr(self._cast("call", controller, "runner()(address)")),
            "executor": self._addr(self._cast("call", controller, "executor()(address)")),
            "policyVersion": self._uint(
                self._cast("call", controller, "policyVersion()(uint32)")),
            "blockNumber": self._uint(block),
            "finalized": self.finalized,
        }
        for name, typ in (("usedSupply", "uint128"), ("usedNormalWithdraw", "uint128"),
                          ("usedRestoration", "uint128"), ("normalCount", "uint64"),
                          ("restorationCount", "uint64")):
            out[name] = self._uint(self._cast("call", controller, f"{name}()({typ})"))
        return out
