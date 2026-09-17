"""Does the handover refuse what it claims to refuse, and preserve what it claims to keep?

METHOD. The real `held_handover` machine, against a real SQLite journal with real
transactions and real close/reopen. The CONTROLLER is a readback double: it stands in for
chain ACCESS, not chain BEHAVIOUR. That the controller actually reverts a stale activation
is proven separately on the fork by test/contracts/HeldAuthority.t.sol; what is established
here is that Held never asks an owner to sign one.

Three groups:

  GUARDS    the refusals. Each asserts the BLOCK and the stated reason, because a handover
            that stalls without saying which operation is unresolved is not actionable.
  PRESERVE  the properties a handover must not damage -- consumption carried, lineage kept,
            runner B not given a Roles seat.
  POSITIVE  a clean handover must complete. A machine that blocks everything proves as
            little as one that blocks nothing.
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

from held_handover import (  # noqa: E402
    Candidate,
    ExpectedState,
    HandoverBlocked,
    HandoverError,
    HandoverMachine,
    HandoverState,
    Policy,
    build_activate,
)
from held_handover.owner_tx import ACTIVATE_SELECTOR, FENCE_SELECTOR, OwnerTransactionError  # noqa: E402
from held_handover.readback import (  # noqa: E402
    ControllerStatus,
    read_controller_state,
)

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

CONTROLLER = "0x5615deb798bb3e4dfa0139dfa1b3d433cc23b72f"
RUNNER_A = "0x15d34aaf54267db7d7c367839aaf71a00a2c6a65"
RUNNER_B = "0x976ea74026e726554db657fa54763abd0c3a0aa9"
EXECUTOR = "0x14dc79964da2c08b23698b3d3cc7ca32193d9955"
LINEAGE = "0x" + "11" * 32
CHAIN = 8453

USED = {"usedSupply": 30_000_000_000, "usedNormalWithdraw": 0, "usedRestoration": 0,
        "normalCount": 3, "restorationCount": 0}


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
    """Real SQLite, real transactions. Stands in for journal ACCESS, not behaviour."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(
            "PRAGMA journal_mode=WAL;"
            "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);")

    @contextlib.contextmanager
    def transaction(self):
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield self._db
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise

    def close(self) -> None:
        self._db.close()


class ControllerDouble:
    """Chain ACCESS for readback. Its behaviour is fixed by the test, not by a contract."""

    def __init__(self, **overrides) -> None:
        self.state = {
            "chainId": CHAIN, "controller": CONTROLLER, "active": True, "epoch": 1,
            "runner": RUNNER_A, "executor": EXECUTOR, "policyVersion": 1,
            "blockNumber": 51353212, "finalized": False, **USED}
        self.state.update(overrides)
        self.fail = False

    def read_controller(self, controller: str):
        if self.fail:
            raise RuntimeError("rpc unavailable")
        return dict(self.state)


TMP = tempfile.TemporaryDirectory()
_N = [0]


def fresh() -> JournalDouble:
    _N[0] += 1
    return JournalDouble(os.path.join(TMP.name, f"{_N[0]:02d}.sqlite"))


def reading(source, *, dispatching=True, require_finalized=False):
    return read_controller_state(source, controller=CONTROLLER, expected_chain_id=CHAIN,
                                 adapter_dispatching=dispatching,
                                 require_finalized=require_finalized)


def policy() -> Policy:
    return Policy(Ls=50_000_000_000, Ln=50_000_000_000, Lr=10_000_000_000,
                  Ms=40_000_000_000, Mn=40_000_000_000, Mr=10_000_000_000,
                  ms=1_000_000, mn=1_000_000, F=0, H=0, Nn=10, Nr=5)


def expected() -> ExpectedState:
    return ExpectedState(USED["usedSupply"], USED["usedNormalWithdraw"],
                         USED["usedRestoration"], USED["normalCount"],
                         USED["restorationCount"])


def candidate(**kw) -> Candidate:
    base = dict(runner=RUNNER_B, executor=EXECUTOR, new_epoch=2, new_policy_version=2,
                policy=policy(), expected=expected(),
                native_config_digest="0x" + "ab" * 32, lineage=LINEAGE)
    base.update(kw)
    return Candidate(**base)


def machine(j, **kw) -> HandoverMachine:
    return HandoverMachine.start(j, handover_id="h1", controller=CONTROLLER, chain_id=CHAIN,
                                 retiring_runner=RUNNER_A, retiring_epoch=1, **kw)


def blocks(fn, *, contains: str) -> HandoverBlocked:
    try:
        fn()
    except HandoverBlocked as exc:
        assert contains in str(exc), f"blocked, but not for {contains!r}: {exc}"
        return exc
    raise AssertionError(f"expected a block mentioning {contains!r}; it proceeded")


def fenced(j) -> tuple[HandoverMachine, ControllerDouble]:
    """Drive a machine to FENCED with a paused controller."""
    m = machine(j)
    c = ControllerDouble()
    m.prepare_fence(current_epoch=1)
    c.state["active"] = False
    m.confirm_fenced(reading(c, dispatching=False))
    return m, c


# ------------------------------------------------------------------------- GUARDS --

@test("GUARD: an adapter that stopped dispatching is NOT an owner fence")
def _():
    j = fresh()
    m = machine(j)
    m.prepare_fence(current_epoch=1)
    live = ControllerDouble()            # still ACTIVE on chain
    r = reading(live, dispatching=False)  # ...but Held is not sending
    assert r.status is ControllerStatus.ADAPTER_REFUSING, r.status
    exc = blocks(lambda: m.confirm_fenced(r), contains="STILL")
    assert "ADAPTER_REFUSING_NOT_FENCED" in exc.blockers
    assert m.record.state is HandoverState.FENCE_PREPARED
    j.close()


@test("GUARD: an unreadable controller is not a fence either")
def _():
    j = fresh()
    m = machine(j)
    m.prepare_fence(current_epoch=1)
    broken = ControllerDouble()
    broken.fail = True
    blocks(lambda: m.confirm_fenced(reading(broken)), contains="not be established")
    j.close()


@test("GUARD: a reading from the wrong chain or controller is incomplete, not a fence")
def _():
    for override, why in (({"chainId": 1}, "chain"), ({"controller": "0x" + "de" * 20}, "controller")):
        j = fresh()
        m = machine(j)
        m.prepare_fence(current_epoch=1)
        wrong = ControllerDouble(active=False, **override)
        r = reading(wrong, dispatching=False)
        assert r.status is ControllerStatus.OBSERVATION_INCOMPLETE, (why, r.status)
        blocks(lambda: m.confirm_fenced(r), contains="not be established")
        j.close()


@test("GUARD: unresolved operations block reconciliation, and are named")
def _():
    j = fresh()
    m, _c = fenced(j)
    exc = blocks(lambda: m.reconcile(["0xaa", "0xbb"]), contains="unresolved")
    assert exc.blockers == ["UNRESOLVED:0xaa", "UNRESOLVED:0xbb"], exc.blockers
    assert m.record.state is HandoverState.FENCED, "it advanced despite unresolved work"
    j.close()


@test("GUARD: a candidate pinned to stale consumption is refused before the owner sees it")
def _():
    j = fresh()
    m, c = fenced(j)
    m.reconcile([])
    # One more supply landed after the candidate was drafted.
    c.state["usedSupply"] = USED["usedSupply"] + 5_000_000_000
    exc = blocks(lambda: m.prepare_candidate(candidate(), observed=reading(c, dispatching=False)),
                 contains="stale state")
    assert "STALE_CANDIDATE" in exc.blockers
    j.close()


@test("GUARD: the controller must stay PAUSED throughout preparation")
def _():
    j = fresh()
    m, c = fenced(j)
    m.reconcile([])
    c.state["active"] = True                      # someone re-activated mid-preparation
    blocks(lambda: m.prepare_candidate(candidate(), observed=reading(c)),
           contains="stay PAUSED")
    j.close()


@test("GUARD: a candidate that does not advance the epoch, or reuses runner A, is refused")
def _():
    for kw, want in ((dict(new_epoch=1), "STALE_EPOCH"), (dict(runner=RUNNER_A), "SAME_RUNNER")):
        j = fresh()
        m, c = fenced(j)
        m.reconcile([])
        exc = blocks(
            lambda kw=kw, c=c: m.prepare_candidate(candidate(**kw),
                                                   observed=reading(c, dispatching=False)),
            contains="")
        assert want in exc.blockers, (kw, exc.blockers)
        j.close()


@test("GUARD: an INCOMPLETE authority inventory blocks activation")
def _():
    j = fresh()
    m, c = fenced(j)
    m.reconcile([])
    m.prepare_candidate(candidate(), observed=reading(c, dispatching=False))
    inv = SimpleNamespace(incomplete_sections=["morpho_grants", "roles"],
                          external_delegates=[], section_count=9)
    exc = blocks(lambda: m.clear_authority(inv), contains="INCOMPLETE")
    assert exc.blockers == ["INCOMPLETE:morpho_grants", "INCOMPLETE:roles"]
    j.close()


@test("GUARD: an external Morpho delegate blocks, and is NOT revoked automatically")
def _():
    j = fresh()
    m, c = fenced(j)
    m.reconcile([])
    m.prepare_candidate(candidate(), observed=reading(c, dispatching=False))
    inv = SimpleNamespace(incomplete_sections=[], external_delegates=["0x" + "ee" * 20],
                          section_count=9)
    exc = blocks(lambda: m.clear_authority(inv), contains="owner must decide")
    assert exc.blockers == ["EXTERNAL_DELEGATE:0x" + "ee" * 20]
    j.close()


@test("GUARD: steps cannot be skipped to reach activation sooner")
def _():
    j = fresh()
    m = machine(j)
    for attempt in (lambda: m.reconcile([]),
                    lambda: m.prepare_activation()):
        try:
            attempt()
            raise AssertionError("a handover step was skipped")
        except (HandoverError, HandoverBlocked):
            pass
    assert m.record.state is HandoverState.PROPOSED
    j.close()


@test("GUARD: activation is not confirmed unless the chain shows the new runner and epoch")
def _():
    for override, want in (({"epoch": 1}, "EPOCH_MISMATCH"),
                           ({"runner": RUNNER_A}, "RUNNER_MISMATCH"),
                           ({"usedSupply": 0}, "CONSUMPTION_NOT_PRESERVED")):
        j = fresh()
        m, c = fenced(j)
        m.reconcile([])
        m.prepare_candidate(candidate(), observed=reading(c, dispatching=False))
        m.clear_authority(SimpleNamespace(incomplete_sections=[], external_delegates=[],
                                          section_count=9))
        m.prepare_activation()
        after = ControllerDouble(**{"active": True, "epoch": 2, "runner": RUNNER_B, **override})
        exc = blocks(lambda after=after: m.confirm_active(reading(after)), contains="")
        assert want in exc.blockers, (override, exc.blockers)
        j.close()


@test("GUARD: the owner transaction builder refuses a ceiling below consumption")
def _():
    p = policy()
    bad = Policy(**{**p.__dict__, "Ls": USED["usedSupply"] - 1})
    try:
        build_activate(controller=CONTROLLER, chain_id=CHAIN, new_epoch=2,
                       new_policy_version=2, new_runner=RUNNER_B, new_executor=EXECUTOR,
                       policy=bad, expected=expected(), current_epoch=1)
        raise AssertionError("a ceiling below what was already spent was accepted")
    except OwnerTransactionError as exc:
        assert "below consumption" in str(exc), str(exc)


# ----------------------------------------------------------------------- PRESERVE --

@test("PRESERVE: a restart resumes the handover from the durable record")
def _():
    j = fresh()
    m, c = fenced(j)
    m.reconcile([])
    m.prepare_candidate(candidate(), observed=reading(c, dispatching=False))
    path = j.path
    j.close()

    # A NEW process: nothing in memory survives.
    j2 = JournalDouble(path)
    resumed = HandoverMachine.load(j2, "h1")
    assert resumed is not None, "the handover did not survive a restart"
    assert resumed.record.state is HandoverState.CANDIDATE_PREPARED
    assert resumed.record.candidate.runner == RUNNER_B
    assert resumed.record.retiring_runner == RUNNER_A
    j2.close()


@test("PRESERVE: the activation carries consumption forward rather than resetting it")
def _():
    tx = build_activate(controller=CONTROLLER, chain_id=CHAIN, new_epoch=2,
                        new_policy_version=2, new_runner=RUNNER_B, new_executor=EXECUTOR,
                        policy=policy(), expected=expected(), current_epoch=1,
                        retiring_runner=RUNNER_A)
    assert tx.data.startswith(ACTIVATE_SELECTOR)
    # activate() takes 4 scalars + a 14-field Policy + a 5-field ExpectedState = 23 words.
    body = tx.data[len(ACTIVATE_SELECTOR):]
    assert len(body) == 23 * 64, f"{len(body) // 64} words, expected 23"
    tail = [int(body[-(5 - i) * 64: len(body) - (4 - i) * 64 or None], 16) for i in range(5)]
    assert tail == list(expected().as_tuple()), tail
    # Remaining capacity is stated, and it is the ceiling MINUS what was already spent.
    assert "supply 20000000000" in tx.summary, tx.summary
    assert any("CARRIED" in d for d in tx.does_not_change), tx.does_not_change


@test("PRESERVE: runner B is never given a Zodiac role seat")
def _():
    tx = build_activate(controller=CONTROLLER, chain_id=CHAIN, new_epoch=2,
                        new_policy_version=2, new_runner=RUNNER_B, new_executor=EXECUTOR,
                        policy=policy(), expected=expected(), current_epoch=1)
    assert tx.to == CONTROLLER, "the activation targets something other than the controller"
    assert any("sole member" in d for d in tx.does_not_change), tx.does_not_change


@test("PRESERVE: the fence describes what it does NOT change")
def _():
    from held_handover import build_fence
    tx = build_fence(controller=CONTROLLER, chain_id=CHAIN, current_epoch=1)
    assert tx.data == FENCE_SELECTOR
    joined = " ".join(tx.does_not_change)
    for must in ("consumption", "Roles", "owners"):
        assert must in joined, f"the fence does not say it leaves {must} alone: {joined}"


# ----------------------------------------------------------------------- POSITIVE --

@test("POSITIVE CONTROL: a clean handover completes and preserves the budget")
def _():
    j = fresh()
    m, c = fenced(j)
    m.reconcile([])
    m.prepare_candidate(candidate(), observed=reading(c, dispatching=False))
    m.clear_authority(SimpleNamespace(incomplete_sections=[], external_delegates=[],
                                      section_count=9))
    tx = m.prepare_activation()
    assert tx.kind == "activate"
    assert m.status()["awaitingOwner"] is True

    after = ControllerDouble(active=True, epoch=2, runner=RUNNER_B)
    m.confirm_active(reading(after))
    assert m.record.state is HandoverState.ACTIVE
    # The whole point: runner B inherits the SPENT budget, not a fresh one.
    last = m.record.history[-1]
    assert last["preservedConsumption"] == list(expected().as_tuple()), last
    j.close()


@test("POSITIVE CONTROL: a blocked handover records where it stalled and can resume")
def _():
    j = fresh()
    m, c = fenced(j)
    blocks(lambda: m.reconcile(["0xaa"]), contains="unresolved")
    m.block("one operation is still in the air", ["UNRESOLVED:0xaa"])
    assert m.record.state is HandoverState.BLOCKED
    assert m.record.blocked_from is HandoverState.FENCED
    # The owner resolves it; the machine continues from where it stalled.
    m.reconcile([])
    assert m.record.state is HandoverState.RECONCILED
    assert m.record.blockers == []
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
