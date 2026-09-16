"""What the console knows, and how it says it in words an owner can act on.

Separated from the HTTP layer on purpose: the four operator jobs are questions about
state, and they should be answerable and testable without a browser.

## The four views are SPECIFIED, not derived

V4 §8 (`docs/plan/14_Held_Locked_V4.md`) names them:

  1. **Terms** -- market, supported actions, current ceilings, Used/Remaining, floor and
     precise changes.
  2. **Activity** -- action/HOLD/refusal/unknown, original operation, KeeperHub attempt,
     transaction and effect evidence.
  3. **Change & handover** -- fence status, unresolved work, owner cleanup, candidate
     terms, activation and missing inputs.
  4. **Authority & export** -- scope/block/finality, complete/incomplete sections,
     credential references, offline recovery package.

An earlier version of this module DERIVED a different four ("J1-J4") from the product
sentence, because the locked plan was not in the repository at the time. That was the
wrong move even though the derivation looked reasonable: the authoritative list existed
and should have been asked for. The plan is now restored under `docs/plan/` and is the
source of truth.

The J-labels below survive as explanatory shorthand for the operator TASK each view
serves, and they are useful for naming tests. They do NOT replace the four required
views, their required data or their required actions, and this module does not yet
implement §8 in full -- see `evidence/P05/acceptance.json` for what is missing.

  J1 run under limits (Terms)              J3 replace the runner (Change & handover)
  J2 change limits (Change & handover)     J4 resolve an interruption (Activity)

## What the console deliberately cannot do

It holds **no keys** and broadcasts **nothing**. J2 and J3 are owner actions on a 2-of-3
Safe, and a console that could perform them would be a fourth authority over the customer's
funds that the P04 inventory does not contain.

So the console PREPARES an owner action and EXPLAINS it -- what changes, from what to
what, and what it does not change -- and the owner executes it in their own Safe. That is
also what makes owner approval understandable: the owner approves a described change,
not an opaque calldata blob.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


class Job(str, Enum):
    RUN = "J1-run-under-limits"
    CHANGE_LIMITS = "J2-change-limits"
    REPLACE_RUNNER = "J3-replace-runner"
    RESOLVE_INTERRUPTED = "J4-resolve-interrupted"


# Units. USDC is 6dp; showing raw base units to an owner approving a limit change is how
# somebody approves a thousand times what they meant to.
USDC_DECIMALS = 6


def usdc(amount: int | str) -> str:
    """Render base units as a decimal string. Never float: 6dp is exact in integers."""
    n = int(amount)
    sign = "-" if n < 0 else ""
    n = abs(n)
    whole, frac = divmod(n, 10 ** USDC_DECIMALS)
    return f"{sign}{whole:,}.{frac:0{USDC_DECIMALS}d}"


def duration(seconds: int) -> str:
    s = int(seconds)
    if s == 0:
        return "none"
    if s % 3600 == 0:
        return f"{s // 3600}h"
    if s % 60 == 0:
        return f"{s // 60}m"
    return f"{s}s"


@dataclass(frozen=True)
class Budget:
    """One consumption dimension, with the remaining amount computed, not asserted."""

    name: str
    ceiling: int
    used: int
    unit: str = "USDC"

    @property
    def remaining(self) -> int:
        return max(self.ceiling - self.used, 0)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.ceiling

    def render(self) -> dict[str, str]:
        fmt = usdc if self.unit == "USDC" else (lambda v: f"{int(v):,}")
        return {
            "name": self.name,
            "ceiling": fmt(self.ceiling),
            "used": fmt(self.used),
            "remaining": fmt(self.remaining),
            "unit": self.unit,
        }


@dataclass(frozen=True)
class LiveState:
    """The controller as it actually is on chain, plus the native quota beside it.

    `native_remaining` is kept separate from `budgets` deliberately. Held's counters and
    the Zodiac allowances are two independent layers, and the console's job is to show
    when they disagree -- not to average them into one reassuring number.
    """

    controller: str
    safe: str
    active: bool
    epoch: int
    policy_version: int
    runner: str
    executor: str
    budgets: Sequence[Budget]
    native_remaining: Mapping[str, int]
    cooldowns: Mapping[str, int]
    last_normal_at: int = 0
    last_restoration_at: int = 0

    @property
    def status_line(self) -> str:
        if not self.active:
            return "FENCED — the runner cannot execute. Consumption history is preserved."
        return f"Active — epoch {self.epoch}, policy v{self.policy_version}"

    def drift(self) -> list[str]:
        """Disagreements between Held's counters and the native Roles quota.

        Shown rather than reconciled. The controller refuses to operate while these
        disagree, so the console's job is to make the reason legible, not to hide it.
        """
        out = []
        for b in self.budgets:
            native = self.native_remaining.get(b.name)
            if native is None:
                continue
            if native != b.remaining:
                out.append(
                    f"{b.name}: Held expects {b.remaining} remaining, the Zodiac "
                    f"allowance holds {native}. The controller will refuse to operate "
                    f"until these agree."
                )
        return out


@dataclass(frozen=True)
class PreparedChange:
    """An owner action, described before it is approved. The console cannot execute it.

    `lines` is the plain-language diff an owner reads. `unchanged` matters as much as
    `lines`: most of the anxiety in approving a change is about what ELSE it might move.
    """

    job: Job
    title: str
    lines: Sequence[str]
    unchanged: Sequence[str]
    warnings: Sequence[str]
    owner_steps: Sequence[str]

    def to_record(self) -> dict[str, Any]:
        return {
            "job": self.job.value,
            "title": self.title,
            "changes": list(self.lines),
            "unchanged": list(self.unchanged),
            "warnings": list(self.warnings),
            "owner_steps": list(self.owner_steps),
            "executed_by_console": False,
        }


def prepare_limit_change(current: LiveState, new_policy: Mapping[str, int]) -> PreparedChange:
    """J2. Describe a limit change in owner-readable terms, and refuse impossible ones."""
    lines: list[str] = []
    warnings: list[str] = []
    by_name = {b.name: b for b in current.budgets}

    for name, new_ceiling in new_policy.items():
        b = by_name.get(name)
        if b is None:
            lines.append(f"{name}: set to {new_ceiling}")
            continue
        if new_ceiling == b.ceiling:
            continue
        unit = usdc if b.unit == "USDC" else (lambda v: f"{int(v):,}")
        direction = "raised" if new_ceiling > b.ceiling else "LOWERED"
        lines.append(
            f"{b.name}: {direction} from {unit(b.ceiling)} to {unit(new_ceiling)} "
            f"{b.unit}. {unit(b.used)} is already spent, so this leaves "
            f"{unit(max(new_ceiling - b.used, 0))} available."
        )
        if new_ceiling < b.used:
            # The controller refuses this outright; saying so here is the difference
            # between an owner learning it now and learning it from a reverted ceremony.
            warnings.append(
                f"{b.name}: a ceiling of {unit(new_ceiling)} is BELOW the "
                f"{unit(b.used)} already consumed. The controller will refuse this "
                "activation (CeilingBelowConsumption). Consumption is never reset."
            )

    if not lines:
        lines.append("No limit changes.")

    return PreparedChange(
        job=Job.CHANGE_LIMITS,
        title="Change customer-approved limits",
        lines=lines,
        unchanged=[
            "Consumption history: every counter carries forward. A limit change is not a reset.",
            f"The runner stays {current.runner}.",
            "The Safe, the Roles module, the market and the lineage are immutable.",
            "Already-executed operations stay executed and can never be replayed.",
        ],
        warnings=warnings,
        owner_steps=[
            "Fence the controller (owner call: fence()).",
            "Re-sync every Zodiac allowance to the NEW ceiling minus what is already spent.",
            "Activate under a NEW epoch with the expected consumption state.",
            "The controller refuses the activation if any allowance disagrees, so a "
            "half-applied change cannot take effect.",
        ],
    )


def prepare_runner_replacement(current: LiveState, new_runner: str,
                               in_flight: Sequence[Mapping[str, Any]] = ()) -> PreparedChange:
    """J3. Replace the runner, and say plainly what happens to work in flight."""
    warnings: list[str] = []
    if new_runner.lower() == current.runner.lower():
        warnings.append("The new runner is the same as the current one. Nothing would change.")
    if in_flight:
        warnings.append(
            f"{len(in_flight)} operation(s) are in flight. After the handover they "
            "CANNOT execute, because their epoch is retired. Each one is then "
            "unambiguous: check whether its id was consumed on chain. Nothing has to be "
            "guessed, and anything unconsumed can be reauthorized by the new runner as a "
            "first execution."
        )
    return PreparedChange(
        job=Job.REPLACE_RUNNER,
        title=f"Replace the runner: {current.runner} → {new_runner}",
        lines=[
            f"The runner becomes {new_runner}.",
            f"The epoch advances from {current.epoch}, which retires every signature "
            f"{current.runner} has produced.",
        ],
        unchanged=[
            "Consumption history: every counter and every consumed operation id carries forward.",
            "The limits themselves, unless you change them in the same activation.",
            "The Safe, the Roles module, the market and the lineage.",
        ],
        warnings=warnings,
        owner_steps=[
            "Fence the controller.",
            "Confirm the in-flight list below is resolved or accepted as retired.",
            "Activate under a NEW epoch naming the new runner.",
        ],
    )


# ------------------------------------------------------------------------- J4 --

# What an operation's journal state means for the operator, in the terms the operator
# actually cares about: can I act, and do I know what happened?
_INTERRUPTION_READING = {
    "CREATED": ("Nothing was sent.", "Safe to authorize."),
    "AUTHORIZED": ("Signed. No attempt has been claimed.", "Safe to send or to abandon."),
    "DISPATCHED": (
        "Handed to the executor. The chain has not been read yet.",
        "Read consumed[operationId] on the controller. That is the only answer.",
    ),
    "UNKNOWN": (
        "The send may or may not have reached the chain. This is NOT 'it failed'.",
        "Read consumed[operationId]. Do not resend: that is how one operation executes twice.",
    ),
    "CONFIRMED": ("Executed on chain.", "Nothing to do. It can never be re-executed."),
    "FAILED": (
        "Definitively not executed. Nothing was consumed.",
        "The same id and payload may be reauthorized under a new epoch.",
    ),
}


@dataclass(frozen=True)
class Interruption:
    operation_id: str
    state: str
    payload_hash: str
    epoch: int
    attempts: int
    what_is_known: str
    what_to_do: str
    resolved: bool
    pending_attempt: str | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "state": self.state,
            "epoch": self.epoch,
            "attempts": self.attempts,
            "what_is_known": self.what_is_known,
            "what_to_do": self.what_to_do,
            "resolved": self.resolved,
            "pending_attempt": self.pending_attempt,
        }


def read_interruptions(journal) -> list[Interruption]:
    """J4. Every operation a restart must resolve, with a reading rather than a code.

    An unresolved ATTEMPT overrides the operation's state wording. The state alone is not
    enough: an operation can read AUTHORIZED while a claimed attempt is outstanding, and
    telling an operator "nothing was sent" in that situation is how a duplicate
    submission gets authorised by hand. The attempt row is the authority on whether
    bytes may have left.
    """
    out = []
    for op in journal.unresolved():
        known, todo = _INTERRUPTION_READING.get(
            op.state.value, ("Unrecognised state.", "Investigate before acting.")
        )
        attempts = journal.attempts_for(op.operation_id)
        pending = None
        if hasattr(journal, "unresolved_attempt"):
            pending = journal.unresolved_attempt(op.operation_id)
        if pending is not None:
            known = (
                "A submission was claimed and may have reached the executor. "
                "This is NOT 'nothing was sent'."
            )
            todo = (
                "Read consumed[operationId] on the controller. If it did not execute, "
                "RESUME the original attempt under its original idempotency key -- never "
                "start a new submission."
            )
        out.append(
            Interruption(
                operation_id=op.operation_id,
                state=op.state.value,
                payload_hash=op.payload_hash,
                epoch=op.epoch,
                attempts=len(attempts),
                what_is_known=known,
                what_to_do=todo,
                resolved=op.state.value in ("CONFIRMED", "FAILED"),
                pending_attempt=(pending or {}).get("attempt_id") if pending else None,
            )
        )
    return out
