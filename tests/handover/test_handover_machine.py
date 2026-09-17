"""Does the handover refuse what it claims to refuse, and preserve what it claims to keep?

METHOD. The real `held_handover` machine against a real SQLite journal -- real
transactions, real commits, real close/reopen. The CONTROLLER is a readback double: it
stands in for chain ACCESS, not chain BEHAVIOUR. That the contract itself reverts a stale
activation is proven on the fork by test/contracts/HeldAuthority.t.sol; what is established
here is that Held never asks an owner to sign one.

Four groups:

  GUARDS    the refusals, each asserting the BLOCK and the stated reason
  REVIEW 1  acceptance regressions for R1-R9 -- every one of which was a way the machine
            could be talked into RECONCILED or CLEARED without evidence
  PRESERVE  properties a handover must not damage
  POSITIVE  a clean handover must complete. A machine that blocks everything proves as
            little as one that blocks nothing
"""
from __future__ import annotations

import contextlib
import os
import sqlite3
import sys
import tempfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in ("packages/handover", "packages/authority", "packages/core", "adapter"):
    sys.path.insert(0, os.path.join(ROOT, p))

from held_authority import from_report  # noqa: E402
from held_handover import (  # noqa: E402
    Candidate,
    ExpectedState,
    HandoverBlocked,
    HandoverError,
    HandoverMachine,
    HandoverState,
    OperationResolution,
    Policy,
    build_activate,
    build_export,
    build_report,
)
from held_handover.owner_tx import ACTIVATE_SELECTOR, FENCE_SELECTOR, OwnerTransactionError  # noqa: E402
from held_handover.readback import ControllerStatus, read_controller_state  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

CONTROLLER = "0x5615deb798bb3e4dfa0139dfa1b3d433cc23b72f"
SAFE = "0x08deeda0ba1eb4b6b4b5cc4dd0c4bc689ea37180"
ROLES = "0x5fbdb2315678afecb367f032d93f642f64180aa3"
RUNNER_A = "0x15d34aaf54267db7d7c367839aaf71a00a2c6a65"
RUNNER_B = "0x976ea74026e726554db657fa54763abd0c3a0aa9"
EXECUTOR = "0x14dc79964da2c08b23698b3d3cc7ca32193d9955"
LINEAGE = "0x" + "0" * 62 + "11"
DIGEST = "0x" + "6e" * 32          # a real-looking digest, not the 0xabab placeholder
CHAIN = 8453
FENCE_BLOCK = 51353212

USED = {"usedSupply": 12_000_000, "usedNormalWithdraw": 0, "usedRestoration": 0,
        "normalCount": 1, "restorationCount": 0}
ZERO_MARKER = "0x" + "0" * 64


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


class JournalDouble:
    """Real SQLite, with the operations table the machine re-derives its truth from."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(
            "PRAGMA journal_mode=WAL;"
            "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS operations("
            " operation_id TEXT PRIMARY KEY, state TEXT NOT NULL, epoch INTEGER NOT NULL);")

    @contextlib.contextmanager
    def transaction(self):
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield self._db
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise

    def add_operation(self, oid: str, state: str, epoch: int) -> None:
        self._db.execute("INSERT OR REPLACE INTO operations VALUES(?,?,?)",
                         (oid.lower(), state, epoch))

    def close(self) -> None:
        self._db.close()


class ControllerDouble:
    def __init__(self, **over) -> None:
        self.state = {
            "chainId": CHAIN, "controller": CONTROLLER, "active": True, "epoch": 1,
            "runner": RUNNER_A, "executor": EXECUTOR, "policyVersion": 1,
            "lineage": LINEAGE, "blockNumber": FENCE_BLOCK,
            "blockHash": "0x" + "ab" * 32, "finalized": False,
            "policyRaw": "50000000000\n50000000000\n10000000000", **USED}
        self.state.update(over)
        self.fail = False

    def read_controller(self, controller):
        if self.fail:
            raise RuntimeError("rpc unavailable")
        return dict(self.state)


class Reader:
    """Chain consumption evidence for reconciliation."""

    def __init__(self, markers=None, fail=False) -> None:
        self.markers = {k.lower(): v for k, v in (markers or {}).items()}
        self.fail = fail

    def consumed(self, controller, operation_id):
        if self.fail:
            raise RuntimeError("chain unavailable")
        return SimpleNamespace(
            marker=self.markers.get(operation_id.lower(), ZERO_MARKER),
            chain_id=CHAIN, controller=controller, block_number=FENCE_BLOCK,
            block_hash="0x" + "ab" * 32, finalized=False)


TMP = tempfile.TemporaryDirectory()
_N = [0]


def fresh() -> JournalDouble:
    _N[0] += 1
    return JournalDouble(os.path.join(TMP.name, f"{_N[0]:02d}.sqlite"))


def reading(source, *, dispatching=True):
    return read_controller_state(source, controller=CONTROLLER, expected_chain_id=CHAIN,
                                 adapter_dispatching=dispatching)


def policy() -> Policy:
    return Policy(Ls=50_000_000_000, Ln=50_000_000_000, Lr=10_000_000_000,
                  Ms=40_000_000_000, Mn=40_000_000_000, Mr=10_000_000_000,
                  ms=1_000_000, mn=1_000_000, F=0, H=0, Nn=10, Nr=5)


def expected() -> ExpectedState:
    return ExpectedState(*USED.values())


def candidate(**kw) -> Candidate:
    base = dict(runner=RUNNER_B, executor=EXECUTOR, new_epoch=2, new_policy_version=2,
                policy=policy(), expected=expected(), native_config_digest=DIGEST,
                lineage=LINEAGE)
    base.update(kw)
    return Candidate(**base)


def inventory_report(**over):
    """A collector report shaped exactly as the real collector writes one."""
    base = {
        "observation": {"block_number": FENCE_BLOCK, "chain_id": CHAIN,
                        "finality": "NONE — anvil fork."},
        "declared_installation": {"verdict": "COMPLETE",
                                  "declared": {"safe": SAFE, "roles": ROLES,
                                               "controller": CONTROLLER,
                                               "lineage": LINEAGE}},
        "safe": {"verdict": "COMPLETE"},
        "roles": {"verdict": "COMPLETE"},
        "morpho_grants": {"verdict": "COMPLETE", "external_delegates": []},
        "held_controller": {"verdict": "COMPLETE", "address": CONTROLLER},
        "clause_to_evidence": [{"obligation": "o1", "satisfied": True}],
        "verdict": {"incomplete_sections": []},
    }
    base.update(over)
    return from_report(base)


def machine(j, **kw) -> HandoverMachine:
    base = dict(handover_id="h1", controller=CONTROLLER, chain_id=CHAIN,
                retiring_runner=RUNNER_A, retiring_epoch=1, safe=SAFE, lineage=LINEAGE)
    base.update(kw)
    return HandoverMachine.start(j, **base)


def blocks(fn, *, contains: str = "") -> HandoverBlocked:
    try:
        fn()
    except HandoverBlocked as exc:
        assert contains in str(exc), f"blocked, but not for {contains!r}: {exc}"
        return exc
    raise AssertionError(f"expected a block mentioning {contains!r}; it proceeded")


def fenced(j):
    m = machine(j)
    c = ControllerDouble()
    m.prepare_fence(current_epoch=1)
    c.state["active"] = False
    m.confirm_fenced(reading(c, dispatching=False))
    return m, c


def report_for(m, c, reader=None):
    return build_report(m.journal, record=m.record,
                        fence_reading=reading(c, dispatching=False),
                        reader=reader or Reader())


def reconciled(j):
    m, c = fenced(j)
    m.reconcile(report_for(m, c))
    return m, c


def cleared(j):
    m, c = reconciled(j)
    m.prepare_candidate(candidate(), observed=reading(c, dispatching=False))
    m.clear_authority(inventory_report(), fence_block=FENCE_BLOCK)
    return m, c


# ------------------------------------------------------------------------- GUARDS --

@test("GUARD: an adapter that stopped dispatching is NOT an owner fence")
def _():
    j = fresh()
    m = machine(j)
    m.prepare_fence(current_epoch=1)
    r = reading(ControllerDouble(), dispatching=False)
    assert r.status is ControllerStatus.ADAPTER_REFUSING, r.status
    exc = blocks(lambda: m.confirm_fenced(r), contains="STILL")
    assert "ADAPTER_REFUSING_NOT_FENCED" in exc.blockers
    j.close()


@test("GUARD: an unreadable or wrong-scoped controller is not a fence either")
def _():
    for over, fail in (({}, True), ({"chainId": 1}, False),
                       ({"controller": "0x" + "de" * 20}, False)):
        j = fresh()
        m = machine(j)
        m.prepare_fence(current_epoch=1)
        c = ControllerDouble(active=False, **over)
        c.fail = fail
        blocks(lambda c=c: m.confirm_fenced(reading(c, dispatching=False)),
               contains="not be established")
        j.close()


@test("GUARD: the controller must stay PAUSED throughout preparation")
def _():
    j = fresh()
    m, c = reconciled(j)
    c.state["active"] = True
    blocks(lambda: m.prepare_candidate(candidate(), observed=reading(c)),
           contains="stay PAUSED")
    j.close()


@test("GUARD: a candidate pinned to stale consumption is refused before the owner sees it")
def _():
    j = fresh()
    m, c = reconciled(j)
    c.state["usedSupply"] = USED["usedSupply"] + 5_000_000
    exc = blocks(lambda: m.prepare_candidate(candidate(),
                                             observed=reading(c, dispatching=False)),
                 contains="stale state")
    assert "STALE_CANDIDATE" in exc.blockers
    j.close()


@test("GUARD: stale epoch, reused runner, drifted lineage and placeholder digest all block")
def _():
    for kw, want in ((dict(new_epoch=1), "STALE_EPOCH"),
                     (dict(runner=RUNNER_A), "SAME_RUNNER"),
                     (dict(lineage="0x" + "cd" * 32), "LINEAGE_MISMATCH"),
                     (dict(native_config_digest="0x" + "ab" * 32),
                      "NATIVE_CONFIG_DIGEST_PLACEHOLDER")):
        j = fresh()
        m, c = reconciled(j)
        exc = blocks(lambda kw=kw, c=c: m.prepare_candidate(
            candidate(**kw), observed=reading(c, dispatching=False)))
        assert want in exc.blockers, (kw, exc.blockers)
        j.close()


@test("GUARD: an external Morpho delegate blocks, and is NOT revoked automatically")
def _():
    j = fresh()
    m, c = reconciled(j)
    m.prepare_candidate(candidate(), observed=reading(c, dispatching=False))
    inv = inventory_report(morpho_grants={"verdict": "COMPLETE",
                                          "external_delegates": ["0x" + "ee" * 20]})
    exc = blocks(lambda: m.clear_authority(inv, fence_block=FENCE_BLOCK),
                 contains="owner must decide")
    assert exc.blockers == ["EXTERNAL_DELEGATE:0x" + "ee" * 20]
    j.close()


@test("GUARD: steps cannot be skipped to reach activation sooner")
def _():
    j = fresh()
    m = machine(j)
    for attempt in (lambda: m.prepare_activation(),
                    lambda: m.clear_authority(inventory_report())):
        try:
            attempt()
            raise AssertionError("a handover step was skipped")
        except (HandoverError, HandoverBlocked):
            pass
    assert m.record.state is HandoverState.PROPOSED
    j.close()


@test("GUARD: the owner transaction builder refuses a ceiling below consumption")
def _():
    bad = Policy(**{**policy().__dict__, "Ls": USED["usedSupply"] - 1})
    try:
        build_activate(controller=CONTROLLER, chain_id=CHAIN, new_epoch=2,
                       new_policy_version=2, new_runner=RUNNER_B, new_executor=EXECUTOR,
                       policy=bad, expected=expected(), current_epoch=1)
        raise AssertionError("a ceiling below what was already spent was accepted")
    except OwnerTransactionError as exc:
        assert "below consumption" in str(exc)


# ==================================================================== REVIEW 1 ====

@test("R1: an empty reconciliation cannot hide an operation the journal holds")
def _():
    # The finding: reconcile(unresolved=[]) advanced whenever the caller said nothing was
    # outstanding, making the caller the authority on its own completeness.
    j = fresh()
    j.add_operation("0x" + "7e" * 32, "UNKNOWN", 1)
    m, c = fenced(j)
    empty = report_for(m, c)
    empty.resolutions = []
    exc = blocks(lambda: m.reconcile(empty), contains="omits 1 operation")
    assert exc.blockers == ["OMITTED:0x" + "7e" * 32]
    assert m.record.state is HandoverState.BLOCKED
    j.close()


@test("R1: an unresolved operation keeps the handover pending; resolving it releases")
def _():
    oid = "0x" + "7e" * 32
    j = fresh()
    j.add_operation(oid, "UNKNOWN", 1)
    m, c = fenced(j)

    stuck = report_for(m, c, reader=Reader(fail=True))
    assert stuck.unresolved == [oid], stuck.unresolved
    blocks(lambda: m.reconcile(stuck), contains="unresolved")

    good = report_for(m, c)
    assert good.unresolved == []
    m.reconcile(good)
    assert m.record.state is HandoverState.RECONCILED
    assert m.record.reconciliation["retiringEpoch"] == 1
    j.close()


@test("R1: a report about another handover, controller, chain or epoch is refused")
def _():
    for field, value in (("handover_id", "other"), ("controller", "0x" + "de" * 20),
                         ("chain_id", 1), ("retiring_epoch", 9), ("fence_block", None)):
        j = fresh()
        m, c = fenced(j)
        rep = report_for(m, c)
        setattr(rep, field, value)
        exc = blocks(lambda rep=rep: m.reconcile(rep), contains="does not describe")
        assert exc.blockers == ["REPORT_OUT_OF_SCOPE"], (field, exc.blockers)
        j.close()


@test("R1: a report covering an operation the journal does not hold is refused")
def _():
    j = fresh()
    m, c = fenced(j)
    rep = report_for(m, c)
    rep.resolutions.append(OperationResolution(
        operation_id="0x" + "99" * 32, journal_state="CONFIRMED", resolution="EXECUTED"))
    exc = blocks(lambda: m.reconcile(rep), contains="does not hold")
    assert exc.blockers[0].startswith("UNKNOWN_OPERATION:")
    j.close()


@test("R1: evidence from the wrong chain or controller leaves an operation UNRESOLVED")
def _():
    j = fresh()
    j.add_operation("0x" + "7e" * 32, "UNKNOWN", 1)
    m, c = fenced(j)

    class WrongScope(Reader):
        def consumed(self, controller, operation_id):
            ev = super().consumed(controller, operation_id)
            ev.chain_id = 1
            return ev

    rep = report_for(m, c, reader=WrongScope())
    assert rep.unresolved == ["0x" + "7e" * 32]
    blocks(lambda: m.reconcile(rep), contains="unresolved")
    j.close()


@test("R2: a hand-made object with the right shape is NOT an authority inventory")
def _():
    # The finding: clear_authority accepted any duck-typed object, and the hero demo built
    # one out of nothing whenever the report was missing.
    j = fresh()
    m, c = reconciled(j)
    m.prepare_candidate(candidate(), observed=reading(c, dispatching=False))
    fake = SimpleNamespace(incomplete_sections=[], external_delegates=[], section_count=0,
                           unsatisfied_obligations=[])
    exc = blocks(lambda: m.clear_authority(fake, fence_block=FENCE_BLOCK),
                 contains="not a collected report")
    assert "NOT_AN_INVENTORY" in exc.blockers
    j.close()


@test("R2: no inventory at all is BLOCKED, never CLEARED")
def _():
    j = fresh()
    m, c = reconciled(j)
    m.prepare_candidate(candidate(), observed=reading(c, dispatching=False))
    exc = blocks(lambda: m.clear_authority(None, fence_block=FENCE_BLOCK),
                 contains="Missing evidence is not")
    assert "NO_INVENTORY" in exc.blockers
    j.close()


@test("R2: a COMPLETE inventory of another installation is refused")
def _():
    other = "0x" + "de" * 20
    cases = [
        ("controller", dict(
            held_controller={"verdict": "COMPLETE", "address": other},
            declared_installation={"verdict": "COMPLETE",
                                   "declared": {"safe": SAFE, "roles": ROLES,
                                                "controller": other, "lineage": LINEAGE}})),
        ("chain", dict(observation={"block_number": FENCE_BLOCK, "chain_id": 1,
                                    "finality": "NONE"})),
        ("safe", dict(declared_installation={
            "verdict": "COMPLETE",
            "declared": {"safe": "0x" + "cc" * 20, "roles": ROLES,
                         "controller": CONTROLLER, "lineage": LINEAGE}})),
        ("lineage", dict(declared_installation={
            "verdict": "COMPLETE",
            "declared": {"safe": SAFE, "roles": ROLES, "controller": CONTROLLER,
                         "lineage": "0x" + "cd" * 32}})),
    ]
    for label, over in cases:
        j = fresh()
        m, c = reconciled(j)
        m.prepare_candidate(candidate(), observed=reading(c, dispatching=False))
        exc = blocks(lambda over=over: m.clear_authority(inventory_report(**over),
                                                         fence_block=FENCE_BLOCK),
                     contains="does not describe this installation")
        assert any(b.startswith("SCOPE:") for b in exc.blockers), (label, exc.blockers)
        j.close()


@test("R2: an inventory observed BEFORE the fence is stale and refused")
def _():
    j = fresh()
    m, c = reconciled(j)
    m.prepare_candidate(candidate(), observed=reading(c, dispatching=False))
    stale = inventory_report(observation={"block_number": FENCE_BLOCK - 10,
                                          "chain_id": CHAIN, "finality": "NONE"})
    blocks(lambda: m.clear_authority(stale, fence_block=FENCE_BLOCK),
           contains="before the fence")
    j.close()


@test("R2: an unsatisfied obligation blocks even when every section says COMPLETE")
def _():
    j = fresh()
    m, c = reconciled(j)
    m.prepare_candidate(candidate(), observed=reading(c, dispatching=False))
    misleading = inventory_report(
        clause_to_evidence=[{"obligation": "both roles verified", "satisfied": False}])
    exc = blocks(lambda: m.clear_authority(misleading, fence_block=FENCE_BLOCK),
                 contains="unsatisfied")
    assert exc.blockers == ["OBLIGATION:both roles verified"]
    j.close()


@test("R3: a refusal survives a restart and cannot be jumped over")
def _():
    j = fresh()
    m, c = reconciled(j)
    m.prepare_candidate(candidate(), observed=reading(c, dispatching=False))
    blocks(lambda: m.clear_authority(
        inventory_report(verdict={"incomplete_sections": ["roles"]}),
        fence_block=FENCE_BLOCK), contains="INCOMPLETE")
    path = j.path
    j.close()

    j2 = JournalDouble(path)
    resumed = HandoverMachine.load(j2, "h1")
    assert resumed.record.state is HandoverState.BLOCKED, "the refusal did not survive"
    assert resumed.record.blocked_from is HandoverState.CANDIDATE_PREPARED
    assert resumed.record.blockers == ["INCOMPLETE:roles"]
    assert resumed.record.candidate.runner == RUNNER_B, "the candidate was lost"
    try:
        resumed.prepare_activation()
        raise AssertionError("activation was prepared straight out of BLOCKED")
    except HandoverError:
        pass
    resumed.clear_authority(inventory_report(), fence_block=FENCE_BLOCK)
    assert resumed.record.state is HandoverState.CLEARED
    j2.close()


@test("R5: an activation that installed anything other than the candidate is refused")
def _():
    for over, want in (({"epoch": 3}, "EPOCH_MISMATCH"),
                       ({"runner": RUNNER_A}, "RUNNER_MISMATCH"),
                       ({"executor": "0x" + "cc" * 20}, "EXECUTOR_MISMATCH"),
                       ({"policyVersion": 9}, "POLICY_VERSION_MISMATCH"),
                       ({"lineage": "0x" + "cd" * 32}, "LINEAGE_MISMATCH"),
                       ({"policyRaw": "1\n2\n3"}, "POLICY_MISMATCH"),
                       ({"usedSupply": 0}, "CONSUMPTION_NOT_PRESERVED")):
        j = fresh()
        m, c = cleared(j)
        m.prepare_activation()
        after = ControllerDouble(**{"active": True, "epoch": 2, "runner": RUNNER_B,
                                    "policyVersion": 2, **over})
        exc = blocks(lambda after=after: m.confirm_active(reading(after)))
        assert any(want in b for b in exc.blockers), (over, exc.blockers)
        j.close()


@test("R9: reopening a handover id under a different installation is a conflict")
def _():
    j = fresh()
    machine(j)
    for kw in (dict(controller="0x" + "de" * 20), dict(chain_id=1),
               dict(safe="0x" + "cc" * 20), dict(lineage="0x" + "cd" * 32),
               dict(retiring_runner=RUNNER_B), dict(retiring_epoch=7)):
        try:
            machine(j, **kw)
            raise AssertionError(f"reopened under a different {list(kw)[0]}")
        except HandoverError as exc:
            assert "DIFFERENT installation" in str(exc), str(exc)
    assert machine(j).record.handover_id == "h1", "identical scope stopped being idempotent"
    j.close()


@test("R4: every value in one reading is pinned to ONE resolved block")
def _():
    # The finding: the source reported block N but pinned nothing, so active/epoch/runner/
    # counters could be read over N, N+1, N+2 -- a state combination that never existed.
    from held_handover.sources import CastControllerSource

    src = CastControllerSource("http://127.0.0.1:1")
    seen: list[tuple[tuple, str | None]] = []
    answers = {"block-number": "51353300", "chain-id": "8453", "block": "0x" + "ab" * 32,
               "active": "true", "epoch": "2", "runner": RUNNER_B, "executor": EXECUTOR,
               "policyVersion": "2", "lineage": LINEAGE, "policy": "1\n2\n3"}

    def fake(*args, at=None):
        seen.append((args, at))
        if args[0] in ("block-number", "chain-id", "block"):
            return answers[args[0]]
        sig = args[2].split("(")[0]
        return answers.get(sig, "0")

    src._cast = fake
    out = src.read_controller(CONTROLLER)

    calls = [(a, at) for a, at in seen if a and a[0] == "call"]
    assert calls, "no state was read at all"
    assert all(at == "51353300" for _a, at in calls), (
        f"state reads were not pinned to one block: {sorted({at for _a, at in calls})}")
    assert out["blockNumber"] == 51353300
    assert out["blockHash"] == "0x" + "ab" * 32


@test("R4: finality is established, never asserted by a caller")
def _():
    from held_handover.sources import CastControllerSource

    # No finality source at all: a fork. Not finalized, whatever anyone would like.
    bare = CastControllerSource("http://127.0.0.1:1")
    assert bare._finalized_at("100") is False

    class Late:
        def finalized_block_number(self):
            return 50

    class Broken:
        def finalized_block_number(self):
            raise RuntimeError("no finality endpoint")

    assert CastControllerSource("x", finality_source=Late())._finalized_at("100") is False
    assert CastControllerSource("x", finality_source=Late())._finalized_at("40") is True
    assert CastControllerSource("x", finality_source=Broken())._finalized_at("1") is False


# ----------------------------------------------------------------------- PRESERVE --

@test("PRESERVE: a restart resumes the handover from the durable record")
def _():
    j = fresh()
    m, c = reconciled(j)
    m.prepare_candidate(candidate(), observed=reading(c, dispatching=False))
    path = j.path
    j.close()
    j2 = JournalDouble(path)
    resumed = HandoverMachine.load(j2, "h1")
    assert resumed.record.state is HandoverState.CANDIDATE_PREPARED
    assert resumed.record.candidate.runner == RUNNER_B
    j2.close()


@test("PRESERVE: the activation carries consumption forward rather than resetting it")
def _():
    tx = build_activate(controller=CONTROLLER, chain_id=CHAIN, new_epoch=2,
                        new_policy_version=2, new_runner=RUNNER_B, new_executor=EXECUTOR,
                        policy=policy(), expected=expected(), current_epoch=1,
                        retiring_runner=RUNNER_A)
    body = tx.data[len(ACTIVATE_SELECTOR):]
    assert len(body) == 23 * 64, f"{len(body) // 64} words, expected 23"
    tail = [int(body[(18 + i) * 64:(19 + i) * 64], 16) for i in range(5)]
    assert tail == list(expected().as_tuple()), tail
    assert "supply 49988000000" in tx.summary, tx.summary


@test("PRESERVE: runner B is never given a Zodiac role seat, and the fence is narrow")
def _():
    from held_handover import build_fence
    act = build_activate(controller=CONTROLLER, chain_id=CHAIN, new_epoch=2,
                         new_policy_version=2, new_runner=RUNNER_B, new_executor=EXECUTOR,
                         policy=policy(), expected=expected(), current_epoch=1)
    assert act.to == CONTROLLER
    assert any("sole member" in d for d in act.does_not_change)
    fence = build_fence(controller=CONTROLLER, chain_id=CHAIN, current_epoch=1)
    assert fence.data == FENCE_SELECTOR
    joined = " ".join(fence.does_not_change)
    for must in ("consumption", "Roles", "owners"):
        assert must in joined, joined


# ------------------------------------------------------------------------- EXPORT --

@test("EXPORT: raw key material is refused; a reference is required")
def _():
    from held_handover import ExportError, assert_reference
    assert assert_reference("env:HELD_RUNNER_B_KEY", "k") == "env:HELD_RUNNER_B_KEY"
    for bad in ("0x" + "47" * 32, "47" * 32, "just-a-string"):
        try:
            assert_reference(bad, "k")
            raise AssertionError(f"accepted {bad[:14]}... as a reference")
        except ExportError:
            pass


@test("R7: an export missing what B needs is NOT usable, and says which")
def _():
    j = fresh()
    m, c = cleared(j)
    m.prepare_activation()
    after = ControllerDouble(active=True, epoch=2, runner=RUNNER_B, policyVersion=2)
    m.confirm_active(reading(after))
    live = reading(after)

    def export(**kw):
        base = dict(handover_id="h1", record=m.record, reading=live,
                    runner_key_reference="env:HELD_RUNNER_B_KEY",
                    native_checkpoints=[{"intent": "i1", "state": "COMPLETED"}],
                    settled_operations=[{"operation_id": "0xaa", "state": "CONFIRMED"}])
        base.update(kw)
        return build_export(**base)

    good = export()
    assert good.usable is True, good.blocked_on
    assert good.remaining_capacity["supply"] == 50_000_000_000 - USED["usedSupply"]

    for kw, needle in ((dict(native_checkpoints=[]), "no native checkpoints"),
                       (dict(settled_operations=None), "settled-operation history"),
                       (dict(pending_operations=["0x7e"]), None)):
        exp = export(**kw)
        assert exp.usable is False, (kw, exp.blocked_on)
        if needle:
            assert any(needle in b for b in exp.blocked_on), exp.blocked_on

    # And no secret may appear anywhere in the serialised export.
    blob = good.to_json()
    assert "47" * 32 not in blob and "RUNNER_B_KEY" in blob
    j.close()


@test("R7: an export bound to the WRONG active state is not usable")
def _():
    j = fresh()
    m, c = cleared(j)
    m.prepare_activation()
    for over, needle in (({"epoch": 5}, "not the replacement epoch"),
                         ({"runner": RUNNER_A}, "not the replacement"),
                         ({"active": False}, "not active")):
        wrong = ControllerDouble(**{"active": True, "epoch": 2, "runner": RUNNER_B,
                                    "policyVersion": 2, **over})
        exp = build_export(handover_id="h1", record=m.record,
                           reading=reading(wrong, dispatching=False),
                           runner_key_reference="env:HELD_RUNNER_B_KEY",
                           native_checkpoints=[{"intent": "i1"}],
                           settled_operations=[])
        assert exp.usable is False, (over, exp.blocked_on)
        assert any(needle in b for b in exp.blocked_on), (over, exp.blocked_on)
    j.close()


@test("R7: a placeholder native configuration digest is not a digest")
def _():
    j = fresh()
    m, c = cleared(j)
    m.prepare_activation()
    after = ControllerDouble(active=True, epoch=2, runner=RUNNER_B, policyVersion=2)
    m.confirm_active(reading(after))
    m.record.candidate.native_config_digest = "0x" + "ab" * 32   # the old hero value
    exp = build_export(handover_id="h1", record=m.record, reading=reading(after),
                       runner_key_reference="env:HELD_RUNNER_B_KEY",
                       native_checkpoints=[{"intent": "i1"}], settled_operations=[])
    assert exp.usable is False
    assert any("placeholder" in b for b in exp.blocked_on), exp.blocked_on
    j.close()


# ----------------------------------------------------------------------- POSITIVE --

@test("POSITIVE CONTROL: a clean handover completes and preserves the budget")
def _():
    j = fresh()
    j.add_operation("0x" + "aa" * 32, "CONFIRMED", 1)
    m, c = fenced(j)
    m.reconcile(report_for(m, c))
    m.prepare_candidate(candidate(), observed=reading(c, dispatching=False))
    m.clear_authority(inventory_report(), fence_block=FENCE_BLOCK)
    tx = m.prepare_activation()
    assert tx.kind == "activate"
    assert m.status()["awaitingOwner"] is True

    after = ControllerDouble(active=True, epoch=2, runner=RUNNER_B, policyVersion=2)
    m.confirm_active(reading(after))
    assert m.record.state is HandoverState.ACTIVE
    assert m.record.history[-1]["preservedConsumption"] == list(expected().as_tuple())
    j.close()


@test("POSITIVE CONTROL: a settled operation needs no chain read to resolve")
def _():
    j = fresh()
    j.add_operation("0x" + "aa" * 32, "CONFIRMED", 1)
    j.add_operation("0x" + "bb" * 32, "FAILED", 1)
    m, c = fenced(j)
    rep = build_report(m.journal, record=m.record,
                       fence_reading=reading(c, dispatching=False), reader=None)
    assert rep.unresolved == [], rep.unresolved
    assert rep.executed == ["0x" + "aa" * 32]
    m.reconcile(rep)
    assert m.record.state is HandoverState.RECONCILED
    j.close()


@test("POSITIVE CONTROL: an operation from ANOTHER epoch is not this handover's problem")
def _():
    j = fresh()
    j.add_operation("0x" + "cc" * 32, "UNKNOWN", 2)   # a later epoch
    m, c = fenced(j)
    rep = report_for(m, c)
    assert rep.resolutions == [], "an operation from another epoch was pulled in"
    m.reconcile(rep)
    assert m.record.state is HandoverState.RECONCILED
    j.close()


def main() -> int:
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"P04 handover: FAIL ({len(FAILED)}/{len(PASSED) + len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} handover machine tests held "
          "(real SQLite; controller readback is a double — the fork proves the contract)")
    return 0


if __name__ == "__main__":
    code = main()
    TMP.cleanup()
    sys.exit(code)
