"""The owner-controlled handover, as a durable machine that survives a restart.

The hero workflow of Locked V4:

    runner A active -> capacity consumed -> an operation becomes ambiguous ->
    owner fences -> reconciliation -> supported authority cleanup ->
    prepare runner B -> owner activates -> remaining Held budget preserved ->
    A cannot reuse its old authorization -> B continues

Every arrow is a place where a partial failure could either strand the customer's funds or
double-spend their budget, which is why this is a durable state machine and not a function.

## What the machine is for

Three rules, and everything else follows from them.

1. **The owner acts, Held prepares.** Held holds no owner key. Each transition that
   requires authority produces an `OwnerTransaction` and then WAITS for readback to show
   the owner executed it. `held_handover.owner_tx` builds those; nothing here signs.

2. **An unresolved operation blocks activation.** If the retiring epoch left an operation
   whose outcome nobody knows, activating a replacement would either lose consumption that
   really happened or charge the customer twice for work that did not. `RECONCILE` refuses
   to advance while any operation is unresolved, and says which ones.

3. **Stale state fails loudly.** The candidate carries the exact consumption the owner saw.
   If anything moved in between, activation reverts on chain -- and this machine refuses to
   even offer the transaction, so the owner is not asked to approve a fiction.

## Restartability

Every transition is committed before it is reported, in the SAME SQLite file as the
journal, so a crash between "the owner executed the fence" and "Held noticed" cannot lose
the handover. `HandoverMachine.load()` resumes from the durable record; the in-memory
object is never the authority.

The states are deliberately coarse. A finer machine would have more places to be wrong
about, and each state here corresponds to a real-world fact an owner could check.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .owner_tx import ExpectedState, OwnerTransaction, Policy, build_activate, build_fence
from .readback import ControllerReading, ControllerStatus
from .reconcile import SCHEMA as RECONCILIATION_SCHEMA
from .reconcile import ReconciliationReport, operations_for_epoch

try:  # the authority package is a sibling; import it by name when it is on the path
    from held_authority import AuthorityInventory
except ImportError:  # pragma: no cover - only when packages/authority is not installed
    AuthorityInventory = ()  # type: ignore[assignment]


def _same(a: Any, b: Any) -> bool:
    return isinstance(a, str) and isinstance(b, str) and a.lower() == b.lower()


def _policy_ceilings(raw: str) -> tuple[int, int, int] | None:
    """The first three policy fields (Ls, Ln, Lr) from a `cast call policy()` result.

    Returns None rather than guessing if the shape is not what we expect: an unreadable
    policy is unreadable, not a matching one.
    """
    parts = [p.strip().split()[0] for p in str(raw).strip().split("\n") if p.strip()]
    if len(parts) < 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None

HANDOVER_KEY = "handover:{handover_id}"


class HandoverState(str, Enum):
    """Coarse on purpose: each one is a fact an owner could independently verify."""

    PROPOSED = "PROPOSED"                    # a replacement is wanted; nothing has happened
    FENCE_PREPARED = "FENCE_PREPARED"        # owner transaction built, not executed
    FENCED = "FENCED"                        # readback: active == false on chain
    RECONCILED = "RECONCILED"                # every operation of the old epoch is settled
    CANDIDATE_PREPARED = "CANDIDATE_PREPARED"  # runner B, terms and counter snapshot pinned
    CLEARED = "CLEARED"                      # bounded authority inventory is COMPLETE
    ACTIVATION_PREPARED = "ACTIVATION_PREPARED"  # owner transaction built, not executed
    ACTIVE = "ACTIVE"                        # readback: new epoch live with runner B
    BLOCKED = "BLOCKED"                      # a stated reason, requiring an owner decision


# The only legal moves. A transition not listed here cannot be taken, which is what keeps a
# caller from skipping reconciliation to get to an activation faster.
_ALLOWED: dict[HandoverState, frozenset[HandoverState]] = {
    HandoverState.PROPOSED: frozenset({HandoverState.FENCE_PREPARED, HandoverState.BLOCKED}),
    HandoverState.FENCE_PREPARED: frozenset({HandoverState.FENCED, HandoverState.BLOCKED}),
    HandoverState.FENCED: frozenset({HandoverState.RECONCILED, HandoverState.BLOCKED}),
    HandoverState.RECONCILED: frozenset({HandoverState.CANDIDATE_PREPARED, HandoverState.BLOCKED}),
    HandoverState.CANDIDATE_PREPARED: frozenset({HandoverState.CLEARED, HandoverState.BLOCKED}),
    HandoverState.CLEARED: frozenset({HandoverState.ACTIVATION_PREPARED, HandoverState.BLOCKED}),
    HandoverState.ACTIVATION_PREPARED: frozenset({HandoverState.ACTIVE, HandoverState.BLOCKED}),
    HandoverState.ACTIVE: frozenset(),
    # BLOCKED is NOT generically permissive. It used to allow every state except ACTIVE,
    # so a machine blocked during authority clearance could reach ACTIVATION_PREPARED
    # directly if a candidate already existed -- jumping the gate that refused it.
    # Resume is now computed from `blocked_from`: the only way out of BLOCKED is to
    # re-attempt the exact gate that failed. See `_legal_targets`.
    HandoverState.BLOCKED: frozenset(),
}


class HandoverError(Exception):
    """A handover step could not be taken truthfully."""


class HandoverBlocked(HandoverError):
    """A guard refused. The reason is the point; it is carried on the exception."""

    def __init__(self, message: str, *, blockers: list[str] | None = None) -> None:
        super().__init__(message)
        self.blockers = blockers or []


@dataclass
class Candidate:
    """The replacement, pinned before anyone is asked to approve it."""

    runner: str
    executor: str
    new_epoch: int
    new_policy_version: int
    policy: Policy
    expected: ExpectedState
    native_config_digest: str
    lineage: str
    prepared_at: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner": self.runner, "executor": self.executor, "newEpoch": self.new_epoch,
            "newPolicyVersion": self.new_policy_version,
            "policy": list(self.policy.as_tuple()),
            "expected": list(self.expected.as_tuple()),
            "nativeConfigDigest": self.native_config_digest,
            "lineage": self.lineage, "preparedAt": self.prepared_at,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Candidate":
        return Candidate(
            runner=d["runner"], executor=d["executor"], new_epoch=d["newEpoch"],
            new_policy_version=d["newPolicyVersion"],
            policy=Policy(*d["policy"]), expected=ExpectedState(*d["expected"]),
            native_config_digest=d["nativeConfigDigest"], lineage=d["lineage"],
            prepared_at=d.get("preparedAt", 0))


@dataclass
class HandoverRecord:
    handover_id: str
    state: HandoverState
    controller: str
    chain_id: int
    retiring_runner: str
    retiring_epoch: int
    safe: str = ""
    lineage: str = ""
    candidate: Candidate | None = None
    blocked_from: HandoverState | None = None
    blockers: list[str] = field(default_factory=list)
    reconciliation: dict[str, Any] | None = None
    inventory_scope: dict[str, Any] | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "handoverId": self.handover_id, "state": self.state.value,
            "controller": self.controller, "chainId": self.chain_id,
            "retiringRunner": self.retiring_runner, "retiringEpoch": self.retiring_epoch,
            "safe": self.safe, "lineage": self.lineage,
            "candidate": self.candidate.to_dict() if self.candidate else None,
            "blockedFrom": self.blocked_from.value if self.blocked_from else None,
            "blockers": self.blockers, "reconciliation": self.reconciliation,
            "inventoryScope": self.inventory_scope, "history": self.history,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "HandoverRecord":
        return HandoverRecord(
            handover_id=d["handoverId"], state=HandoverState(d["state"]),
            controller=d["controller"], chain_id=d["chainId"],
            retiring_runner=d["retiringRunner"], retiring_epoch=d["retiringEpoch"],
            safe=d.get("safe", ""), lineage=d.get("lineage", ""),
            candidate=Candidate.from_dict(d["candidate"]) if d.get("candidate") else None,
            blocked_from=HandoverState(d["blockedFrom"]) if d.get("blockedFrom") else None,
            blockers=d.get("blockers", []), reconciliation=d.get("reconciliation"),
            inventory_scope=d.get("inventoryScope"), history=d.get("history", []))


class HandoverMachine:
    """Durable, restartable, and unable to skip a step.

    The journal is passed in rather than opened here: the handover and the operations it
    reconciles must be able to commit together, and two connections to the same file cannot
    do that.
    """

    def __init__(self, journal, record: HandoverRecord) -> None:
        self.journal = journal
        self.record = record

    # ------------------------------------------------------------------ durability --
    # The handover identity. Reopening under the same id must mean the SAME handover, not
    # merely the same string -- the exact distinction a P03 review already forced on the
    # native decision binding. A mismatch is a conflict, never a silently returned machine.
    SCOPE_FIELDS = ("controller", "chain_id", "safe", "lineage", "retiring_runner",
                    "retiring_epoch")

    @classmethod
    def start(cls, journal, *, handover_id: str, controller: str, chain_id: int,
              retiring_runner: str, retiring_epoch: int, safe: str = "",
              lineage: str = "") -> "HandoverMachine":
        wanted = {"controller": controller, "chain_id": chain_id, "safe": safe,
                  "lineage": lineage, "retiring_runner": retiring_runner,
                  "retiring_epoch": retiring_epoch}
        existing = cls.load(journal, handover_id)
        if existing is not None:
            mismatched = {}
            for f in cls.SCOPE_FIELDS:
                got, want = getattr(existing.record, f), wanted[f]
                if isinstance(got, str) and isinstance(want, str):
                    same = got.lower() == want.lower()
                else:
                    same = got == want
                if not same:
                    mismatched[f] = (got, want)
            if mismatched:
                raise HandoverError(
                    f"handover {handover_id!r} already exists for a DIFFERENT installation: "
                    + "; ".join(f"{k} is {g!r}, not {w!r}" for k, (g, w) in mismatched.items())
                    + ". An idempotent reopen must mean the same handover, not the same key.")
            return existing
        record = HandoverRecord(
            handover_id=handover_id, state=HandoverState.PROPOSED, controller=controller,
            chain_id=chain_id, retiring_runner=retiring_runner,
            retiring_epoch=retiring_epoch, safe=safe, lineage=lineage)
        machine = cls(journal, record)
        machine._persist("start", {"controller": controller, "epoch": retiring_epoch})
        return machine

    @classmethod
    def load(cls, journal, handover_id: str) -> "HandoverMachine | None":
        row = journal._db.execute(  # noqa: SLF001 - read-only accessor, as elsewhere
            "SELECT value FROM meta WHERE key=?",
            (HANDOVER_KEY.format(handover_id=handover_id),)).fetchone()
        if row is None:
            return None
        return cls(journal, HandoverRecord.from_dict(json.loads(row["value"])))

    def _persist(self, event: str, detail: dict[str, Any] | None = None) -> None:
        self.record.history.append(
            {"at": int(time.time()), "event": event, "state": self.record.state.value,
             **(detail or {})})
        key = HANDOVER_KEY.format(handover_id=self.record.handover_id)
        with self.journal.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                         (key, json.dumps(self.record.to_dict())))

    def _legal_targets(self) -> frozenset[HandoverState]:
        """Where this machine may go next, including the narrow way out of BLOCKED."""
        if self.record.state is not HandoverState.BLOCKED:
            return _ALLOWED[self.record.state]
        origin = self.record.blocked_from
        if origin is None:
            return frozenset()
        # Re-attempting the gate that failed means moving as if from the state it stalled
        # in -- and nothing else.
        return _ALLOWED[origin]

    def _require_state(self, *expected: HandoverState) -> None:
        """Every public transition asserts its exact source state.

        A blocked machine counts as being in the state it stalled in, and only that one, so
        a refusal cannot be walked around by calling the next method.
        """
        current = self.record.state
        effective = (self.record.blocked_from
                     if current is HandoverState.BLOCKED else current)
        if effective not in expected:
            want = " or ".join(s.value for s in expected)
            raise HandoverError(
                f"this step requires the handover to be at {want}; it is at "
                f"{current.value}"
                + (f" (blocked from {effective.value})" if current is HandoverState.BLOCKED
                   and effective else ""))

    def _refuse(self, reason: str, blockers: list[str]) -> "HandoverBlocked":
        """Persist the refusal BEFORE raising it.

        Guard failures used to raise without recording anything, so a restart lost the fact
        that a gate had refused and why. A blocker that does not survive a restart is not a
        blocker.
        """
        if self.record.state is not HandoverState.BLOCKED:
            self.record.blocked_from = self.record.state
        self.record.blockers = blockers
        self.record.state = HandoverState.BLOCKED
        self._persist("blocked", {"reason": reason, "blockers": blockers})
        return HandoverBlocked(reason, blockers=blockers)

    def _move(self, to: HandoverState, event: str, detail: dict[str, Any] | None = None) -> None:
        if to not in self._legal_targets():
            raise HandoverError(
                f"{self.record.state.value} -> {to.value} is not a legal handover move. "
                "The order exists so a step cannot be skipped to reach activation sooner.")
        self.record.state = to
        if to is not HandoverState.BLOCKED:
            self.record.blocked_from = None
            self.record.blockers = []
        self._persist(event, detail)

    def block(self, reason: str, blockers: list[str] | None = None) -> None:
        """Record why the handover cannot proceed, keeping the state it stalled in."""
        if self.record.state is not HandoverState.BLOCKED:
            self.record.blocked_from = self.record.state
        self.record.blockers = blockers or [reason]
        self.record.state = HandoverState.BLOCKED
        self._persist("blocked", {"reason": reason, "blockers": self.record.blockers})

    # ----------------------------------------------------------------- transitions --
    def prepare_fence(self, *, current_epoch: int) -> OwnerTransaction:
        """Build the owner's fence transaction. Held does NOT execute it."""
        self._require_state(HandoverState.PROPOSED)
        tx = build_fence(controller=self.record.controller, chain_id=self.record.chain_id,
                         current_epoch=current_epoch)
        self._move(HandoverState.FENCE_PREPARED, "fence prepared",
                   {"currentEpoch": current_epoch})
        return tx

    def confirm_fenced(self, reading: ControllerReading) -> None:
        """Accept the fence only on evidence that the CONTROLLER is paused.

        An adapter that stopped dispatching is not a fence, and this is the guard that
        refuses to call it one.
        """
        self._require_state(HandoverState.FENCE_PREPARED)
        if not reading.usable:
            raise self._refuse(
                f"the controller's state could not be established: {reading.reason}. An "
                "unknown is not a verified fence.", ["OBSERVATION_INCOMPLETE"])
        if reading.status is ControllerStatus.ADAPTER_REFUSING:
            raise self._refuse(
                "Held's adapter has stopped dispatching, but the controller is STILL "
                "ACTIVE on chain. That is not a fence: a correctly signed envelope from "
                "the retiring runner would still execute. The owner must call fence().",
                ["ADAPTER_REFUSING_NOT_FENCED"])
        if reading.status is not ControllerStatus.OWNER_FENCED:
            raise self._refuse(
                f"the controller reads {reading.status.value}, not OWNER_FENCED.",
                [reading.status.value])
        self._move(HandoverState.FENCED, "fence confirmed on chain",
                   {"epoch": reading.epoch, "blockNumber": reading.block_number})

    def reconcile(self, report: "ReconciliationReport") -> None:
        """Advance only on a report the machine itself can confirm is COMPLETE.

        This used to take `unresolved: list[str]` and advance whenever the list was empty,
        which made the caller the authority on what was outstanding. It is now given a
        report, and it RE-DERIVES the retiring-epoch operation set from the durable journal
        to check that report against. A report that omits an operation the journal knows
        about is refused, so forgetting and concealing are the same refused thing.
        """
        self._require_state(HandoverState.FENCED)

        if getattr(report, "schema", None) != RECONCILIATION_SCHEMA:
            raise self._refuse(
                f"reconciliation report schema {getattr(report, 'schema', None)!r} is not "
                f"{RECONCILIATION_SCHEMA!r}; a shape that merely looks right is not a report",
                ["BAD_REPORT_SCHEMA"])

        # The report must be about THIS handover, installation and epoch.
        scope: list[str] = []
        if report.handover_id != self.record.handover_id:
            scope.append(f"report is for handover {report.handover_id!r}")
        if not _same(report.controller, self.record.controller):
            scope.append(f"report is for controller {report.controller}")
        if report.chain_id != self.record.chain_id:
            scope.append(f"report is for chain {report.chain_id}")
        if report.retiring_epoch != self.record.retiring_epoch:
            scope.append(f"report is for epoch {report.retiring_epoch}")
        if report.fence_block is None:
            scope.append("the report states no fence block, so it cannot be tied to the "
                         "observation the fence was confirmed at")
        if scope:
            raise self._refuse(
                "the reconciliation report does not describe this handover: "
                + "; ".join(scope), ["REPORT_OUT_OF_SCOPE"])

        # THE GUARANTEE. The journal, not the caller, says what existed.
        known = set(operations_for_epoch(self.journal, self.record.retiring_epoch))
        covered = report.operation_ids
        missing = sorted(known - covered)
        if missing:
            raise self._refuse(
                f"the reconciliation report omits {len(missing)} operation(s) the journal "
                f"holds for epoch {self.record.retiring_epoch}: {', '.join(missing[:4])}"
                + (" ..." if len(missing) > 4 else "")
                + ". A report is complete or it is not a report.",
                [f"OMITTED:{oid}" for oid in missing])
        extra = sorted(covered - known)
        if extra:
            raise self._refuse(
                f"the reconciliation report covers {len(extra)} operation(s) the journal "
                f"does not hold for this epoch: {', '.join(extra[:4])}. Evidence about "
                "something else is not evidence about this handover.",
                [f"UNKNOWN_OPERATION:{oid}" for oid in extra])

        if report.unresolved:
            raise self._refuse(
                f"{len(report.unresolved)} operation(s) from the retiring epoch are "
                "unresolved. Activating a replacement now would either lose consumption "
                "that really happened or charge the customer twice for work that did not.",
                [f"UNRESOLVED:{oid}" for oid in report.unresolved])

        self.record.reconciliation = report.to_dict()
        self._move(HandoverState.RECONCILED,
                   "every operation of the retiring epoch is settled from chain evidence",
                   {"operations": len(report.resolutions),
                    "executed": len(report.executed),
                    "fenceBlock": report.fence_block})

    def prepare_candidate(self, candidate: Candidate, *, observed: ControllerReading) -> None:
        """Pin the replacement against the consumption actually on chain right now."""
        self._require_state(HandoverState.RECONCILED)
        if not observed.usable:
            raise self._refuse(
                f"the candidate cannot be pinned to an unreadable controller: "
                f"{observed.reason}", ["OBSERVATION_INCOMPLETE"])
        if observed.status is not ControllerStatus.OWNER_FENCED:
            raise self._refuse(
                "the controller must stay PAUSED throughout preparation; it reads "
                f"{observed.status.value}", [observed.status.value])
        on_chain = ExpectedState(
            usedSupply=observed.used["usedSupply"],
            usedNormalWithdraw=observed.used["usedNormalWithdraw"],
            usedRestoration=observed.used["usedRestoration"],
            normalCount=observed.used["normalCount"],
            restorationCount=observed.used["restorationCount"])
        if candidate.expected.as_tuple() != on_chain.as_tuple():
            raise self._refuse(
                f"the candidate was prepared against consumption "
                f"{candidate.expected.as_tuple()} but the controller reads "
                f"{on_chain.as_tuple()}. Preparing against stale state would ask the owner "
                "to approve remaining capacity that does not exist.",
                ["STALE_CANDIDATE"])
        if candidate.new_epoch <= self.record.retiring_epoch:
            raise self._refuse(
                f"epoch {candidate.new_epoch} does not advance past the retiring epoch "
                f"{self.record.retiring_epoch}", ["STALE_EPOCH"])
        if candidate.runner.lower() == self.record.retiring_runner.lower():
            raise self._refuse(
                "the candidate runner is the runner being retired; that is not a handover",
                ["SAME_RUNNER"])
        if self.record.lineage and not _same(candidate.lineage, self.record.lineage):
            raise self._refuse(
                f"the candidate declares lineage {candidate.lineage}, but this handover is "
                f"bound to {self.record.lineage}. A replacement under a different lineage "
                "is a different installation, not a handover.", ["LINEAGE_MISMATCH"])
        if not candidate.native_config_digest or set(
                candidate.native_config_digest.lower().replace("0x", "")) <= {"a", "b"}:
            raise self._refuse(
                f"the candidate's native configuration digest {candidate.native_config_digest!r} "
                "is absent or a placeholder. Runner B's continuation depends on it being "
                "the digest of the ACTUAL pinned configuration.",
                ["NATIVE_CONFIG_DIGEST_PLACEHOLDER"])
        self.record.candidate = candidate
        self._move(HandoverState.CANDIDATE_PREPARED, "candidate pinned",
                   {"runner": candidate.runner, "newEpoch": candidate.new_epoch})

    def clear_authority(self, inventory: Any, *, fence_block: int | None = None) -> None:
        """Require a COMPLETE inventory that provably describes THIS installation.

        This used to ask two duck-typed questions -- are `incomplete_sections` and
        `external_delegates` empty? -- of any object at all. A `SimpleNamespace` with two
        empty lists satisfied it, and so would a genuine COMPLETE inventory of somebody
        else's controller. Missing evidence could be turned into clean evidence by
        constructing it.

        So the inventory must now be the real typed one, and it must carry a scope that
        matches this handover: chain, controller, Safe, lineage, and an observation no
        older than the fence. No inventory means BLOCKED, never CLEARED.
        """
        self._require_state(HandoverState.CANDIDATE_PREPARED)

        if inventory is None:
            raise self._refuse(
                "no bounded authority inventory was supplied. Missing evidence is not "
                "clean evidence: without it nothing is known about who can move the "
                "customer's funds.", ["NO_INVENTORY"])
        if not isinstance(inventory, AuthorityInventory):
            raise self._refuse(
                f"the authority inventory must be a real AuthorityInventory, not "
                f"{type(inventory).__name__}. An object of the right shape is not a "
                "collected report.", ["NOT_AN_INVENTORY"])

        problems = inventory.scope_problems(
            chain_id=self.record.chain_id,
            controller=self.record.controller,
            safe=self.record.safe or "",
            lineage=(self.record.candidate.lineage if self.record.candidate else None),
            not_before_block=fence_block)
        if problems:
            raise self._refuse(
                "the authority inventory does not describe this installation: "
                + "; ".join(problems), [f"SCOPE:{p}" for p in problems])

        if inventory.incomplete_sections:
            raise self._refuse(
                f"the bounded authority inventory is INCOMPLETE in "
                f"{len(inventory.incomplete_sections)} section(s): "
                f"{', '.join(inventory.incomplete_sections)}. An unreadable section is not "
                "an empty one.",
                [f"INCOMPLETE:{s}" for s in inventory.incomplete_sections])
        if inventory.unsatisfied_obligations:
            raise self._refuse(
                f"{len(inventory.unsatisfied_obligations)} declared obligation(s) are "
                "unsatisfied even though every section reported COMPLETE: "
                + "; ".join(inventory.unsatisfied_obligations),
                [f"OBLIGATION:{o}" for o in inventory.unsatisfied_obligations])
        if inventory.external_delegates:
            raise self._refuse(
                f"external Morpho delegate(s) still hold authority over the Safe: "
                f"{', '.join(inventory.external_delegates)}. These are NOT revoked "
                "automatically -- they may be legitimate conflicting use by another agent, "
                "and revoking someone else's access to make a checklist green would be its "
                "own incident. The owner must decide.",
                [f"EXTERNAL_DELEGATE:{d}" for d in inventory.external_delegates])

        self.record.inventory_scope = inventory.scope()
        self._move(HandoverState.CLEARED,
                   "bounded authority inventory complete and scoped to this installation",
                   {"sections": inventory.section_count,
                    "observedAtBlock": inventory.block_number})

    def prepare_activation(self) -> OwnerTransaction:
        """Build the single atomic activation, carrying the owner's expected state."""
        self._require_state(HandoverState.CLEARED)
        c = self.record.candidate
        if c is None:
            raise HandoverError("no candidate has been prepared")
        tx = build_activate(
            controller=self.record.controller, chain_id=self.record.chain_id,
            new_epoch=c.new_epoch, new_policy_version=c.new_policy_version,
            new_runner=c.runner, new_executor=c.executor, policy=c.policy,
            expected=c.expected, current_epoch=self.record.retiring_epoch,
            retiring_runner=self.record.retiring_runner)
        self._move(HandoverState.ACTIVATION_PREPARED, "activation prepared",
                   {"newEpoch": c.new_epoch, "runner": c.runner})
        return tx

    def confirm_active(self, reading: ControllerReading) -> None:
        """Accept the handover only when the chain shows the replacement live."""
        c = self.record.candidate
        if c is None:
            raise HandoverError("no candidate has been prepared")
        self._require_state(HandoverState.ACTIVATION_PREPARED)
        if not reading.usable:
            raise self._refuse(
                f"activation could not be verified: {reading.reason}",
                ["OBSERVATION_INCOMPLETE"])
        if reading.status is not ControllerStatus.CONTRACT_ACTIVE:
            raise self._refuse(
                f"the controller reads {reading.status.value}, not CONTRACT_ACTIVE",
                [reading.status.value])

        # ACTIVE is accepted only when EVERY observable candidate field matches. Checking
        # epoch and runner alone let an activation that installed a different executor,
        # policy version or lineage read as the one the owner approved.
        mismatches: list[str] = []
        if reading.epoch != c.new_epoch:
            mismatches.append(f"EPOCH_MISMATCH: on chain {reading.epoch}, approved {c.new_epoch}")
        if not _same(reading.runner, c.runner):
            mismatches.append(f"RUNNER_MISMATCH: on chain {reading.runner}, approved {c.runner}")
        if not _same(reading.executor, c.executor):
            mismatches.append(
                f"EXECUTOR_MISMATCH: on chain {reading.executor}, approved {c.executor}")
        if reading.policy_version != c.new_policy_version:
            mismatches.append(
                f"POLICY_VERSION_MISMATCH: on chain {reading.policy_version}, approved "
                f"{c.new_policy_version}")
        if reading.lineage is not None and not _same(reading.lineage, c.lineage):
            mismatches.append(
                f"LINEAGE_MISMATCH: on chain {reading.lineage}, approved {c.lineage}")
        if reading.policy_raw:
            observed_ceilings = _policy_ceilings(reading.policy_raw)
            approved = (c.policy.Ls, c.policy.Ln, c.policy.Lr)
            if observed_ceilings is not None and observed_ceilings != approved:
                mismatches.append(
                    f"POLICY_MISMATCH: ceilings on chain {observed_ceilings}, approved "
                    f"{approved}")
        if mismatches:
            raise self._refuse(
                "the activated controller is not the candidate the owner approved: "
                + "; ".join(mismatches), mismatches)

        carried = ExpectedState(
            usedSupply=reading.used["usedSupply"],
            usedNormalWithdraw=reading.used["usedNormalWithdraw"],
            usedRestoration=reading.used["usedRestoration"],
            normalCount=reading.used["normalCount"],
            restorationCount=reading.used["restorationCount"])
        if carried.as_tuple() != c.expected.as_tuple():
            raise self._refuse(
                f"consumption after activation is {carried.as_tuple()}, not the "
                f"{c.expected.as_tuple()} that was carried. Held's verified history must "
                "survive a handover unchanged.", ["CONSUMPTION_NOT_PRESERVED"])
        self._move(HandoverState.ACTIVE, "replacement active on chain",
                   {"epoch": reading.epoch, "runner": reading.runner,
                    "preservedConsumption": list(carried.as_tuple())})

    # ------------------------------------------------------------------- reporting --
    def status(self) -> dict[str, Any]:
        r = self.record
        return {
            **r.to_dict(),
            "readyForActivation": r.state is HandoverState.CLEARED,
            "awaitingOwner": r.state in (HandoverState.FENCE_PREPARED,
                                         HandoverState.ACTIVATION_PREPARED),
            "_note": "PREPARED steps are waiting on an owner transaction that Held cannot "
                     "and will not send.",
        }
