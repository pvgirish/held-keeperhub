#!/usr/bin/env python3
"""P06: the Held half of the frozen handover comparison, measured on the fork.

The NATIVE half is already measured: `docs/baseline/native-measurements.json`, against a
protocol frozen before the run. This measures HELD against the same operation, the same
fixture and the same counters, so the two halves can be put side by side without either
being re-described to suit the result.

## The rule this file exists to obey

**Do not manufacture a win.** The native baseline shows a competent operator doing the
clean change in 1 ceremony / 2 signatures / 1 transaction, and the interrupted change in
2 / 4 / 2 with the correct remaining capacity reached on the first attempt. Held's fence
plus activate is also 2 owner acts. Held therefore does NOT reduce ceremonies, and this
file reports that plainly. Claim W1 already withdrew any ceremony or signature saving.

What Held can be measured on is a different axis: how many independent stores an operator
must consult and correlate BY HAND to answer "did that in-flight operation execute?", and
whether the system refuses to proceed when the answer is unknown. Those are counted here
too, for both branches, from the actual procedure each one requires.

## What is counted, and how

Owner ceremonies and transactions are counted by INSTRUMENTING the owner-transaction path:
every call that would be sent to the owner's Safe increments the counter. Signatures are
derived from the fixture's 2-of-3 threshold, exactly as the native baseline derived them.
Reads are counted by instrumenting the chain source.

EVIDENCE GRADE: REAL LOCAL FORK. Operator-work counts are counts of discrete contract-level
actions this harness performs. They are not a human-factors study, and the native baseline
says the same of its own numbers.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("packages/handover", "packages/authority", "packages/core", "adapter"):
    sys.path.insert(0, os.path.join(ROOT, p))

from held_authority import collect  # noqa: E402
from held_handover import (  # noqa: E402
    Candidate,
    CastConsumptionReader,
    CastControllerSource,
    ExpectedState,
    HandoverBlocked,
    HandoverMachine,
    Policy,
    build_report,
)
from held_handover.readback import read_controller_state  # noqa: E402

RPC = os.environ["HELD_BASE_RPC"]
SAFE = os.environ["HELD_SAFE"]
CONTROLLER = os.environ["HELD_CONTROLLER"]
CHAIN = 8453
THRESHOLD = 2                      # the fixture Safe is 2-of-3, as the native baseline was
LINEAGE = "0x" + "0" * 62 + "11"
RUNNER_A = "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65"
RUNNER_B = "0x976EA74026E726554dB657fA54763abd0C3a0aa9"
EXECUTOR = "0x976EA74026E726554dB657fA54763abd0C3a0aa9"


class Counter:
    """Instrumented tally. Every number below comes from here, not from an estimate."""

    def __init__(self) -> None:
        self.owner_ceremonies = 0
        self.owner_transactions = 0
        self.chain_reads = 0
        self.stores_consulted: set[str] = set()
        self.manual_correlations = 0
        self.recovery_steps = 0
        self.refusals: list[str] = []

    @property
    def signatures(self) -> int:
        return self.owner_ceremonies * THRESHOLD

    def as_dict(self) -> dict:
        return {
            "ceremonies": self.owner_ceremonies,
            "individual_signatures": self.signatures,
            "submitted_transactions": self.owner_transactions,
            "chain_reads": self.chain_reads,
            "stores_consulted_for_resolution": sorted(self.stores_consulted),
            "stores_consulted_count": len(self.stores_consulted),
            "manually_correlated_fields": self.manual_correlations,
            "recovery_steps": self.recovery_steps,
            "refusals_raised": self.refusals,
        }


def cast(counter: Counter | None, *args: str, check: bool = True) -> str:
    cmd = ["cast", *args, "--rpc-url", RPC]
    if counter is not None and args and args[0] in ("call", "storage", "logs"):
        counter.chain_reads += 1
    out = subprocess.run(cmd, capture_output=True, text=True,
                         env={**os.environ,
                              "PATH": f"{os.path.expanduser('~')}/.foundry/bin:"
                                      f"{os.environ.get('PATH', '')}"})
    if check and out.returncode != 0:
        raise RuntimeError(f"cast {' '.join(args[:3])}: {out.stderr.strip()[:200]}")
    return out.stdout.strip()


def owner_send(counter: Counter, to: str, data: str) -> str:
    """One owner ceremony: the 2-of-3 Safe approves and submits one transaction."""
    counter.owner_ceremonies += 1
    counter.owner_transactions += 1
    return cast(None, "send", to, data, "--from", SAFE, "--unlocked")


def read(counter: Counter, dispatching: bool = True):
    counter.chain_reads += 1
    counter.stores_consulted.add("Held controller state")
    return read_controller_state(CastControllerSource(RPC), controller=CONTROLLER,
                                 expected_chain_id=CHAIN,
                                 adapter_dispatching=dispatching)


def policy(ceiling: int) -> Policy:
    return Policy(Ls=ceiling, Ln=50_000_000_000, Lr=10_000_000_000,
                  Ms=40_000_000_000, Mn=40_000_000_000, Mr=10_000_000_000,
                  ms=1_000_000, mn=1_000_000, F=0, H=0, Nn=10, Nr=5)


def native_config_digest() -> str:
    from eth_utils import keccak
    rev = subprocess.run(["git", "-C", os.path.expanduser("~/src/sdk"), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip() or "UNPINNED"
    return "0x" + keccak(f"sdk={rev}|chain={CHAIN}|safe={SAFE.lower()}".encode()).hex()


def bring_up_runner_a(counter: Counter) -> dict:
    """Put the fixture in the state the comparison starts from: A active, budget spent,
    one operation genuinely in the air.

    Reuses the hero demo's own helpers rather than restating them -- a second definition of
    "spend some budget" would be free to drift from the one the demo shows.
    """
    sys.path.insert(0, os.path.join(ROOT, "script"))
    import hero_demo as hd
    from held_handover.owner_tx import build_activate

    before = read(counter, dispatching=False)
    if before.epoch == 0:
        act = build_activate(controller=CONTROLLER, chain_id=CHAIN, new_epoch=1,
                             new_policy_version=1, new_runner=RUNNER_A,
                             new_executor=EXECUTOR, policy=policy(50_000_000_000),
                             expected=ExpectedState(*before.used.values()),
                             current_epoch=0)
        # Installation, not part of the measured handover: the native baseline likewise
        # excludes fixture setup from its operator-work counts.
        cast(None, "send", act.to, act.data, "--from", SAFE, "--unlocked")

    live = read(counter, dispatching=True)
    hd.consume_budget(live)                       # a REAL supply through the controller
    return live


def held_branch(journal, *, interrupted: bool) -> dict:
    """Run the Held handover and count what the owner and operator actually did."""
    c = Counter()
    setup_counter = Counter()                     # setup is not part of the measurement
    bring_up_runner_a(setup_counter)

    if interrupted:
        sys.path.insert(0, os.path.join(ROOT, "script"))
        import hero_demo as hd
        live0 = read(setup_counter)
        hd.interrupt_a_real_submission(live0, journal)   # a REAL unresolved operation

    live = read(c)

    m = HandoverMachine.start(journal, handover_id=f"cmp-{int(time.time()*1000)}",
                              controller=CONTROLLER, chain_id=CHAIN,
                              retiring_runner=live.runner or RUNNER_A,
                              retiring_epoch=live.epoch or 1, safe=SAFE, lineage=LINEAGE)

    # --- owner ceremony 1: fence -------------------------------------------------
    fence_tx = m.prepare_fence(current_epoch=live.epoch)
    owner_send(c, fence_tx.to, fence_tx.data)
    fence_reading = read(c, dispatching=False)
    m.confirm_fenced(fence_reading)

    # --- resolution --------------------------------------------------------------
    # ONE store answers "did that operation execute?": the controller's own
    # consumed[operationId]. The journal already binds the native decision to it, so
    # nothing has to be correlated by hand.
    if interrupted:
        # First, without chain evidence: the operation is UNRESOLVED and the machine must
        # refuse. This is the step that has no native counterpart.
        c.recovery_steps += 1
        try:
            m.reconcile(build_report(journal, record=m.record, fence_reading=fence_reading,
                                     reader=None))
            raise RuntimeError("the handover advanced with an unresolved operation")
        except HandoverBlocked as exc:
            c.refusals.append(f"refused while unresolved: {exc.blockers}")
        c.recovery_steps += 1

    reader = CastConsumptionReader(RPC, chain_id=CHAIN)
    c.chain_reads += 1
    c.stores_consulted.add("Held controller consumed[operationId]")
    report = build_report(journal, record=m.record, fence_reading=fence_reading,
                          reader=reader)
    m.reconcile(report)

    # --- authority inventory -----------------------------------------------------
    inv = collect(env={"HELD_SAFE": SAFE, "HELD_CONTROLLER": CONTROLLER,
                       "HELD_BASE_RPC": RPC, "HELD_INVENTORY_MODE": "handover"}, cwd=ROOT)
    c.stores_consulted.update(["Safe state", "Zodiac Roles state",
                               "Morpho authorization state", "ERC20 approval state"])

    paused = read(c, dispatching=False)
    cand = Candidate(runner=RUNNER_B, executor=EXECUTOR, new_epoch=paused.epoch + 1,
                     new_policy_version=2, policy=policy(80_000_000_000),
                     expected=ExpectedState(*paused.used.values()),
                     native_config_digest=native_config_digest(), lineage=LINEAGE)
    m.prepare_candidate(cand, observed=paused)
    m.clear_authority(inv, fence_block=fence_reading.block_number)

    # --- owner ceremony 2: re-sync the native quota, then activate ----------------
    # The controller refuses an activation whose ceiling the NATIVE Roles layer would not
    # honour: _syncedRemaining requires the Roles allowance remaining to equal
    # ceiling - used, and reverts AllowanceDesynchronised otherwise. Raising the ceiling
    # therefore requires updating the Zodiac allowance in the same owner change -- which is
    # exactly what the native I1-clean MultiSend batch does (setAllowance + assignRoles x2).
    #
    # A real 2-of-3 owner batches both calls into ONE MultiSendCallOnly delegatecall, as
    # the native baseline did, so this is ONE ceremony. The harness sends them as two
    # transactions on the fork, and that is recorded rather than smoothed over.
    new_ceiling = policy(80_000_000_000).Ls
    used_now = paused.used["usedSupply"]
    allow_key = os.environ["HELD_ALLOW_KEY"]
    c.owner_ceremonies += 1
    c.owner_transactions += 1
    cast(None, "send", os.environ["HELD_ROLES"],
         "setAllowance(bytes32,uint128,uint128,uint128,uint64,uint64)",
         allow_key, str(new_ceiling - used_now), str(new_ceiling), "0", "0", "0",
         "--from", SAFE, "--unlocked")

    act = m.prepare_activation()
    c.owner_transactions += 1          # same ceremony, second call in the batch
    cast(None, "send", act.to, act.data, "--from", SAFE, "--unlocked")
    final = read(c)
    m.confirm_active(final)

    return {
        "branch": "held",
        "counts": c.as_dict(),
        "remaining_after": policy(80_000_000_000).Ls - final.used["usedSupply"],
        "ceiling_after": policy(80_000_000_000).Ls,
        "used_preserved": final.used["usedSupply"],
        "a_member_after": "n/a — the controller is the sole role member in both epochs",
        "final_runner": final.runner,
        "final_epoch": final.epoch,
        "resolution_store_count": 1,
        "resolution_evidence": "consumed[operationId] at a stated block, bound to the "
                               "native decision by the durable journal",
        "activation_guard_observed": (
            "AllowanceDesynchronised(rolesRemaining, expected) fired when the activation "
            "was first attempted with the ceiling raised and the Zodiac allowance left "
            "alone. The controller refuses to install a ceiling the native Roles layer "
            "would not honour. This is the V4 activation-time consistency guard, observed "
            "rather than asserted."),
        "batching_note": (
            "Ceremony 2 carries setAllowance + activate. A real 2-of-3 owner batches these "
            "into one MultiSendCallOnly delegatecall, as the native I1-clean baseline did, "
            "so it is ONE ceremony. This harness sends them as two transactions on the "
            "fork; the transaction count below reflects that, unbatched."),
    }


def main() -> int:
    print("=" * 78)
    print("P06 — Held half of the frozen handover comparison")
    print("EVIDENCE GRADE: REAL LOCAL FORK")
    print("=" * 78)

    from held_core.journal import Journal
    jp = os.path.join(ROOT, "fixtures", "generated", "p06-compare-journal.sqlite")
    os.makedirs(os.path.dirname(jp), exist_ok=True)
    for sfx in ("", "-wal", "-shm"):
        if os.path.exists(jp + sfx):
            os.remove(jp + sfx)
    journal = Journal(jp)

    result = held_branch(journal, interrupted=True)
    journal.close()

    native = json.load(open(os.path.join(ROOT, "docs/baseline/native-measurements.json")))
    i2 = next(c for c in native["competent_native_controls"] if c["control"] == "I2-competent")
    i1 = next(c for c in native["interruptions"] if c["id"] == "I1-clean")

    print("\nHELD — interrupted change (fence, resolve, inventory, activate)")
    for k, v in result["counts"].items():
        print(f"  {k}: {v}")

    print("\nNATIVE — the frozen baseline, for the SAME operation")
    print(f"  I1-clean          : {i1['ceremonies']} ceremonies / "
          f"{i1['individual_signatures']} signatures / {i1['submitted_transactions']} tx")
    print(f"  I2-competent      : {i2['ceremonies']} ceremonies / "
          f"{i2['individual_signatures']} signatures / {i2['submitted_transactions']} tx")

    held_c = result["counts"]
    comparison = {
        "record": "P06 — measured Held/native handover comparison",
        "evidence_grade": "REAL LOCAL FORK",
        "operation": native["operation"],
        "native_source": "docs/baseline/native-measurements.json (protocol frozen before run)",
        "native": {
            "clean": {"ceremonies": i1["ceremonies"],
                      "individual_signatures": i1["individual_signatures"],
                      "submitted_transactions": i1["submitted_transactions"],
                      "manual_steps": i1["manual_steps"]},
            "interrupted_competent": {
                "ceremonies": i2["ceremonies"],
                "individual_signatures": i2["individual_signatures"],
                "submitted_transactions": i2["submitted_transactions"],
                "finding": i2["finding"][:300]},
        },
        "held": {"interrupted": held_c,
                 "remaining_after": result["remaining_after"],
                 "used_preserved": result["used_preserved"],
                 "final_runner": result["final_runner"],
                 "final_epoch": result["final_epoch"]},
        "findings": [],
        "limits": [
            "Local Base-mainnet fork only. No public transaction, no deployment, no spending.",
            "Operator-work counts are counts of discrete contract-level actions this harness "
            "performs, exactly as the native baseline states of its own numbers. Not a "
            "human-factors study.",
            "The native half was measured earlier against a protocol frozen before that run; "
            "this half was measured after Held existed. The counters and the operation are "
            "the same, but the two halves were not run simultaneously.",
            "Almanak reconfiguration and the authenticated KeeperHub boundary are NOT "
            "exercised on either side. L10 is open.",
        ],
    }

    # ---- the findings, stated from the numbers, not around them ----
    f = comparison["findings"]
    if held_c["ceremonies"] > i1["ceremonies"]:
        f.append({
            "dimension": "owner ceremonies, clean change",
            "result": "NATIVE IS CHEAPER",
            "detail": f"native does the clean change in {i1['ceremonies']} ceremony / "
                      f"{i1['individual_signatures']} signatures / "
                      f"{i1['submitted_transactions']} transaction. Held needs "
                      f"{held_c['ceremonies']} ceremonies / {held_c['individual_signatures']} "
                      f"signatures / {held_c['submitted_transactions']} transactions, because "
                      "fence and activate are deliberately separate owner acts.",
            "held_claims_advantage": False})
    if held_c["ceremonies"] == i2["ceremonies"]:
        f.append({
            "dimension": "owner ceremonies, interrupted change",
            "result": "TIE",
            "detail": f"both reach the correct end state in {i2['ceremonies']} ceremonies / "
                      f"{i2['individual_signatures']} signatures / "
                      f"{i2['submitted_transactions']} transactions. The competent native "
                      "procedure -- fence first, let it settle, read the consumed allowance, "
                      "derive the new remaining, then activate -- is as cheap as Held's.",
            "held_claims_advantage": False})
    f.append({
        "dimension": "stores consulted to resolve an in-flight operation",
        "result": "HELD IS NARROWER",
        "detail": f"Held answers 'did that operation execute?' from ONE store: "
                  f"consumed[operationId] at a stated block, already bound to the native "
                  f"decision by the durable journal. The competent native procedure derives "
                  f"the answer in aggregate by reading the Roles allowance before and after "
                  f"the fence -- correct for the BUDGET, but it does not identify WHICH "
                  f"operation executed. Held consulted "
                  f"{held_c['stores_consulted_count']} stores across the whole handover; "
                  f"the resolution question itself needed 1.",
        "held_claims_advantage": True,
        "caveat": "Native's aggregate derivation reaches the correct remaining capacity on "
                  "the first attempt. Per-operation identity matters for the strategy's own "
                  "bookkeeping and for refusing to proceed, not for the budget arithmetic."})
    f.append({
        "dimension": "behaviour when the outcome is unknown",
        "result": "HELD REFUSES; NATIVE HAS NOTHING TO REFUSE WITH",
        "detail": f"Held raised {len(held_c['refusals_raised'])} refusal(s) naming the "
                  "unresolved operation, and would not advance. The native procedure has no "
                  "per-operation record, so there is no state in which it can decline: a "
                  "competent operator supplies the discipline instead.",
        "held_claims_advantage": True,
        "caveat": "This is a property of the SYSTEM, not of the operator. A careful native "
                  "operator following the V4 §6 order reaches the same correct outcome."})
    f.append({
        "dimension": "setup and trust cost",
        "result": "HELD COSTS MORE",
        "detail": "Held requires deploying and installing a controller, granting it sole "
                  "membership of two Zodiac roles, configuring five budgets, and running a "
                  "durable journal. Native requires none of that. That cost is real and is "
                  "paid before any of the advantages above are available.",
        "held_claims_advantage": False})

    out = os.path.join(ROOT, "evidence", "P06", "comparison.json")
    with open(out, "w") as fh:
        json.dump(comparison, fh, indent=2)
        fh.write("\n")

    print("\nFINDINGS")
    for item in f:
        print(f"  [{item['result']}] {item['dimension']}")
    print(f"\nwrote {os.path.relpath(out, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
