"""Owner transactions Held PREPARES and the owner EXECUTES. Held never signs them.

V4 §3 and §7: every authority over the customer's funds belongs to the customer's 2-of-3
Safe. Held holds no owner key, and a Held component that could fence or activate on its own
would be a fourth authority the P04 inventory does not contain and the owner never approved.

So this module builds calldata and DESCRIBES it. The description is not decoration: owner
approval is only meaningful if the owner can see what changes, from what to what, and what
it deliberately does not change. A hex blob in a Safe UI is not informed consent.

## The two owner acts

`fence()` pauses the controller at its current epoch. It is the on-chain act -- an adapter
that stops dispatching is NOT a fence, because the controller would still honour a
correctly signed envelope from the existing runner. That distinction is load-bearing and
`readback.py` keeps it visible.

`activate(newEpoch, newPolicyVersion, newRunner, newExecutor, Policy, ExpectedState)` is the
single atomic act that installs the replacement. It carries the consumption the owner
believed when they approved it, so an activation prepared against stale state REVERTS
rather than silently installing a runner under the wrong remaining capacity.

## Why the runner changes in POLICY, not in Roles

The controller is the sole member of both Zodiac roles. Replacing a runner by assigning
runner B into the role would create a second path to the Safe that bypasses the controller
entirely -- the opposite of what a handover is for. The runner key lives in the
controller's own policy, so `activate` is the only thing that moves it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Selectors, taken from `forge inspect HeldController methods` rather than derived from
# type strings written here -- both were guessed wrong on the first attempt, which is
# exactly why this project reads them off the compiled artifact instead. Recomputed from
# contracts/out/ by tests/handover/test_owner_tx.py, which fails if the contract changes
# shape.
#
#   fence()                                                       f33a513e
#   activate(uint64,uint32,address,address,
#            (uint128 x10, uint64 x4), (uint128 x3, uint64 x2))    be6d7eb6
FENCE_SELECTOR = "0xf33a513e"
ACTIVATE_SELECTOR = "0xbe6d7eb6"


class OwnerTransactionError(Exception):
    """A described owner action could not be built truthfully."""


@dataclass(frozen=True)
class Policy:
    """The V4 §5 policy, in unsigned base units. No floats, no MAX sentinel."""

    Ls: int
    Ln: int
    Lr: int
    Ms: int
    Mn: int
    Mr: int
    ms: int
    mn: int
    F: int
    H: int
    Nn: int
    Nr: int
    dn: int = 0
    dr: int = 0

    def as_tuple(self) -> tuple[int, ...]:
        return (self.Ls, self.Ln, self.Lr, self.Ms, self.Mn, self.Mr,
                self.ms, self.mn, self.F, self.H, self.Nn, self.Nr, self.dn, self.dr)


@dataclass(frozen=True)
class ExpectedState:
    """What the owner believed the controller had consumed when they approved.

    The controller compares this field by field and reverts `StaleActivation` on any
    disagreement. That is the whole anti-stale mechanism: an activation approved an hour
    ago, during which one more supply landed, must not install a runner under capacity the
    owner never agreed to.
    """

    usedSupply: int
    usedNormalWithdraw: int
    usedRestoration: int
    normalCount: int
    restorationCount: int

    def as_tuple(self) -> tuple[int, ...]:
        return (self.usedSupply, self.usedNormalWithdraw, self.usedRestoration,
                self.normalCount, self.restorationCount)


@dataclass
class OwnerTransaction:
    """One transaction for the owner's Safe to execute, with its plain-language meaning."""

    kind: str
    to: str
    value: int
    data: str
    chain_id: int
    summary: str
    changes: list[str] = field(default_factory=list)
    does_not_change: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    reverts_if: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "to": self.to, "value": self.value, "data": self.data,
            "chainId": self.chain_id, "summary": self.summary, "changes": self.changes,
            "doesNotChange": self.does_not_change, "preconditions": self.preconditions,
            "revertsIf": self.reverts_if,
            "_note": "PREPARED, NOT SIGNED AND NOT BROADCAST. Held holds no owner key. "
                     "The owner executes this in their own Safe.",
        }


def _u(value: int, bits: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise OwnerTransactionError(f"{name}: must be an int, got {type(value).__name__}")
    if value < 0 or value >= (1 << bits):
        raise OwnerTransactionError(f"{name}: {value} does not fit in uint{bits}")
    return value


def _addr(value: str, name: str) -> str:
    if not isinstance(value, str) or len(value) != 42 or not value.startswith("0x"):
        raise OwnerTransactionError(f"{name}: not an address: {value!r}")
    try:
        int(value, 16)
    except ValueError:
        raise OwnerTransactionError(f"{name}: not hex: {value!r}") from None
    return value


def _word(value: int) -> str:
    return f"{value:064x}"


def _addr_word(value: str) -> str:
    return f"{int(value, 16):064x}"


def build_fence(*, controller: str, chain_id: int, current_epoch: int) -> OwnerTransaction:
    """Pause the controller at its current epoch."""
    _addr(controller, "controller")
    _u(current_epoch, 64, "current_epoch")
    return OwnerTransaction(
        kind="fence",
        to=controller,
        value=0,
        data=FENCE_SELECTOR,
        chain_id=chain_id,
        summary=f"Pause the Held controller at epoch {current_epoch}. "
                "The current runner's authorization stops being honoured on chain.",
        changes=[
            "active: true -> false",
            f"emits Fenced({current_epoch})",
        ],
        does_not_change=[
            "the recorded consumption (usedSupply, usedNormalWithdraw, usedRestoration, "
            "normalCount, restorationCount) -- Held's verified history survives a fence",
            "the Zodiac Roles configuration or its allowances",
            "the Safe's owners, threshold, modules or guard",
            "any Morpho position",
        ],
        preconditions=["the caller is the owner Safe", "the controller is currently active"],
        reverts_if=["the caller is not the owner Safe"],
    )


def build_activate(
    *,
    controller: str,
    chain_id: int,
    new_epoch: int,
    new_policy_version: int,
    new_runner: str,
    new_executor: str,
    policy: Policy,
    expected: ExpectedState,
    current_epoch: int,
    retiring_runner: str | None = None,
) -> OwnerTransaction:
    """Install the replacement runner and terms, in ONE atomic owner act.

    Every guard the controller applies is restated in `reverts_if`, because an owner who
    cannot predict why a transaction would fail cannot meaningfully approve it.
    """
    _addr(controller, "controller")
    _addr(new_runner, "new_runner")
    _addr(new_executor, "new_executor")
    _u(new_epoch, 64, "new_epoch")
    _u(new_policy_version, 32, "new_policy_version")
    _u(current_epoch, 64, "current_epoch")

    if new_epoch <= current_epoch:
        raise OwnerTransactionError(
            f"new_epoch {new_epoch} must be greater than the current epoch {current_epoch}; "
            "the controller refuses a stale activation and so does this builder")

    for name, ceiling, used in (
        ("Ls", policy.Ls, expected.usedSupply),
        ("Ln", policy.Ln, expected.usedNormalWithdraw),
        ("Lr", policy.Lr, expected.usedRestoration),
    ):
        if ceiling < used:
            raise OwnerTransactionError(
                f"policy.{name}={ceiling} is below consumption already recorded ({used}). "
                "A ceiling beneath what has been spent is not a smaller budget, it is an "
                "unsatisfiable one, and the controller reverts CeilingBelowConsumption.")
    for name, ceiling, used in (("Nn", policy.Nn, expected.normalCount),
                                ("Nr", policy.Nr, expected.restorationCount)):
        if ceiling < used:
            raise OwnerTransactionError(
                f"policy.{name}={ceiling} is below the count already consumed ({used})")

    words = [
        _word(new_epoch), _word(new_policy_version),
        _addr_word(new_runner), _addr_word(new_executor),
    ]
    words += [_word(v) for v in policy.as_tuple()]
    words += [_word(v) for v in expected.as_tuple()]
    data = ACTIVATE_SELECTOR + "".join(words)

    remaining = {
        "supply": policy.Ls - expected.usedSupply,
        "normalWithdraw": policy.Ln - expected.usedNormalWithdraw,
        "restoration": policy.Lr - expected.usedRestoration,
        "normalCount": policy.Nn - expected.normalCount,
        "restorationCount": policy.Nr - expected.restorationCount,
    }
    changes = [
        f"epoch: {current_epoch} -> {new_epoch}",
        f"runner: {retiring_runner or '(current)'} -> {new_runner}",
        f"executor: -> {new_executor}",
        f"policyVersion: -> {new_policy_version}",
        "active: false -> true",
    ]
    return OwnerTransaction(
        kind="activate",
        to=controller,
        value=0,
        data=data,
        chain_id=chain_id,
        summary=f"Activate epoch {new_epoch} with runner {new_runner}. Remaining capacity "
                f"after this change: supply {remaining['supply']}, normal withdraw "
                f"{remaining['normalWithdraw']}, restoration {remaining['restoration']}, "
                f"counts {remaining['normalCount']}/{remaining['restorationCount']}.",
        changes=changes,
        does_not_change=[
            "the recorded consumption -- it is CARRIED, which is why the remaining capacity "
            "above is what it is. The replacement runner inherits the budget, not a fresh one",
            "the Zodiac Roles membership: the controller remains the sole member of both "
            "roles, and runner B is NOT assigned into a role",
            "the Safe's owners, threshold, modules or guard",
            "the Held lineage",
        ],
        preconditions=[
            "the caller is the owner Safe",
            "the controller is currently PAUSED (fence first)",
            f"the controller's consumption is exactly {expected.as_tuple()}",
            "every in-flight operation from the retiring epoch is resolved",
        ],
        reverts_if=[
            "AlreadyActive -- the controller was not fenced",
            f"StaleActivation -- newEpoch {new_epoch} is not greater than the live epoch",
            "StaleActivation -- consumption moved since this transaction was prepared, "
            "which means the owner would be approving capacity they never saw",
            "CeilingBelowConsumption -- a ceiling is below what has already been spent",
        ],
    )
