#!/usr/bin/env python3
"""P06: the Held half of the frozen handover comparison, measured on the fork.

The NATIVE half is already measured in `docs/baseline/native-measurements.json`, against a
protocol frozen before that run. This measures HELD against the same operation, from the
same economic starting state, with the same counters.

## What an earlier version of this file got wrong, and why it mattered

It started Held at 12 USDC consumed while native started at 30,000, so the two branches were
not comparing the same change. It ran only the interrupted case. And it counted
`setAllowance` + `activate` as one owner ceremony on the strength of a MultiSend it never
executed -- hypothetical batching inside a measured row.

All three are fixed here:

* **Parity is established and ASSERTED.** Held performs three REAL 10,000 USDC supplies
  through its own controller before either branch runs, so `usedSupply` is exactly
  30,000,000,000 against a 50,000,000,000 ceiling -- the same 20,000 remaining the native
  baseline starts from.
* **Both branches run.** Clean and interrupted execute separately from that same state,
  isolated by `evm_snapshot`/`evm_revert` so neither contaminates the other.
* **The batch is real.** The owner change is one genuine Safe `execTransaction` delegatecall
  to MultiSendCallOnly 1.4.1, signed by two of three owners -- the same mechanism the native
  baseline used. Counts are of what actually happened.

## Why Held still needs two ceremonies

The controller refuses `activate` while it is active, and Held requires the fence to be
CONFIRMED and the retiring epoch reconciled before a candidate is pinned. Fence and activate
therefore cannot share a transaction. That is a real product constraint, not an accounting
artifact, and it is reported as a cost.

EVIDENCE GRADE: REAL LOCAL FORK. Operator-work counts are counts of discrete contract-level
actions, exactly as the native baseline says of its own numbers.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("packages/handover", "packages/authority", "packages/core", "adapter", "script"):
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
from held_handover.owner_tx import build_activate  # noqa: E402
from held_handover.readback import read_controller_state  # noqa: E402

RPC = os.environ["HELD_BASE_RPC"]
SAFE = os.environ["HELD_SAFE"]
ROLES = os.environ["HELD_ROLES"]
CONTROLLER = os.environ["HELD_CONTROLLER"]
ALLOW_KEY = os.environ["HELD_ALLOW_KEY"]
CHAIN = 8453
LINEAGE = "0x" + "0" * 62 + "11"

# anvil deterministic owners 1 and 2 of the 2-of-3 fixture Safe. Public, fork only.
PK1 = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
PK2 = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
ZERO = "0x" + "0" * 40
MULTISEND = "0x9641d764fc13c8B624c04430C7356C1C7C8102e2"   # MultiSendCallOnly 1.4.1
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USDC_SLOT = 9

RUNNER_A = "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65"
RUNNER_B = "0x976EA74026E726554dB657fA54763abd0C3a0aa9"
EXECUTOR = "0x976EA74026E726554dB657fA54763abd0C3a0aa9"

CEILING_OLD = 50_000_000_000
CEILING_NEW = 80_000_000_000
TARGET_USED = 30_000_000_000            # the native baseline's starting consumption
CHUNK = 10_000_000_000                  # three of these, as the native fixture does

FOUNDRY_ENV = {"PATH": f"{os.path.expanduser('~')}/.foundry/bin:{os.environ.get('PATH','')}"}


def sh(*args: str, check: bool = True) -> str:
    out = subprocess.run(["cast", *args, "--rpc-url", RPC], capture_output=True, text=True,
                         env={**os.environ, **FOUNDRY_ENV})
    if check and out.returncode != 0:
        raise RuntimeError(f"cast {' '.join(args[:3])}: {out.stderr.strip()[:240]}")
    return out.stdout.strip()


def local(*args: str) -> str:
    out = subprocess.run(["cast", *args], capture_output=True, text=True,
                         env={**os.environ, **FOUNDRY_ENV})
    if out.returncode != 0:
        raise RuntimeError(f"cast {' '.join(args[:2])}: {out.stderr.strip()[:200]}")
    return out.stdout.strip()


def uint(raw: str) -> int:
    return int(raw.split()[0])


class Counter:
    def __init__(self) -> None:
        self.ceremonies = 0
        self.signatures = 0
        self.transactions = 0
        self.chain_reads = 0
        self.stores: set[str] = set()
        self.resolution_stores: set[str] = set()
        self.recovery_steps = 0
        self.refusals: list[str] = []

    def as_dict(self) -> dict:
        return {"ceremonies": self.ceremonies,
                "individual_signatures": self.signatures,
                "submitted_transactions": self.transactions,
                "chain_reads": self.chain_reads,
                "stores_consulted": sorted(self.stores),
                "stores_for_resolution": sorted(self.resolution_stores),
                "stores_for_resolution_count": len(self.resolution_stores),
                "recovery_steps": self.recovery_steps,
                "refusals_raised": self.refusals}


def safe_exec(counter: Counter | None, to: str, data: str, operation: int = 0) -> str:
    """ONE real owner ceremony: two of three owners sign, one execTransaction is sent."""
    nonce = str(uint(sh("call", SAFE, "nonce()(uint256)")))
    txh = sh("call", SAFE,
             "getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,uint256,"
             "address,address,uint256)(bytes32)",
             to, "0", data, str(operation), "0", "0", "0", ZERO, ZERO, nonce).split()[0]
    s1 = local("wallet", "sign", "--no-hash", "--private-key", PK1, txh)
    s2 = local("wallet", "sign", "--no-hash", "--private-key", PK2, txh)
    sigs = "0x" + s2[2:] + s1[2:]
    if counter is not None:
        counter.ceremonies += 1
        counter.signatures += 2          # actually produced, immediately above
        counter.transactions += 1
    out = subprocess.run(
        ["cast", "send", SAFE,
         "execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,"
         "address,bytes)", to, "0", data, str(operation), "0", "0", "0", ZERO, ZERO, sigs,
         "--private-key", PK1, "--rpc-url", RPC, "--json"],
        capture_output=True, text=True, env={**os.environ, **FOUNDRY_ENV})
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"safe_exec reverted: {out.stderr.strip()[:240]}")
    status = json.loads(out.stdout)["status"]
    if str(status) not in ("0x1", "1", "success"):
        raise RuntimeError(f"safe_exec status {status}")
    return status


def ms_part(to: str, data: str) -> str:
    d = data[2:]
    return f"00{to[2:].lower()}{0:064x}{len(d) // 2:064x}{d}"


def multisend_calldata(parts: list[tuple[str, str]]) -> str:
    return local("calldata", "multiSend(bytes)",
                 "0x" + "".join(ms_part(to, data) for to, data in parts))


def snapshot() -> str:
    return sh("rpc", "evm_snapshot").strip('"')


def revert(sid: str) -> None:
    sh("rpc", "evm_revert", sid)


def read(counter: Counter | None, dispatching: bool = True):
    if counter is not None:
        counter.chain_reads += 1
        counter.stores.add("Held controller state")
    return read_controller_state(CastControllerSource(RPC), controller=CONTROLLER,
                                 expected_chain_id=CHAIN, adapter_dispatching=dispatching)


def allowance_remaining() -> int:
    raw = sh("call", ROLES,
             "allowances(bytes32)(uint128,uint128,uint64,uint128,uint64)", ALLOW_KEY)
    return uint(raw.split("\n")[3])


def policy(ceiling: int) -> Policy:
    return Policy(Ls=ceiling, Ln=50_000_000_000, Lr=10_000_000_000,
                  Ms=40_000_000_000, Mn=40_000_000_000, Mr=10_000_000_000,
                  ms=1_000_000, mn=1_000_000, F=0, H=0, Nn=10, Nr=5)


def establish_parity() -> dict:
    """Bring Held to the native baseline's economic starting state, and ASSERT it."""
    import hero_demo as hd

    before = read(None, dispatching=False)
    if before.epoch == 0:
        act = build_activate(controller=CONTROLLER, chain_id=CHAIN, new_epoch=1,
                             new_policy_version=1, new_runner=RUNNER_A,
                             new_executor=EXECUTOR, policy=policy(CEILING_OLD),
                             expected=ExpectedState(*before.used.values()), current_epoch=0)
        safe_exec(None, act.to, act.data)          # installation, deliberately not measured

    # Top up the Safe so Held can spend the same 30,000 the native fixture already spent
    # from the original funding. Fixture setup, using the fixture's own mechanism.
    key = local("index", "address", SAFE, str(USDC_SLOT))
    sh("rpc", "anvil_setStorageAt", USDC, key, f"0x{100_000_000_000:064x}")

    hd.SUPPLY_AMOUNT = CHUNK
    sh("rpc", "anvil_impersonateAccount", EXECUTOR, check=False)
    sh("rpc", "anvil_setBalance", EXECUTOR, "0xDE0B6B3A7640000", check=False)
    for i in range(TARGET_USED // CHUNK):
        live = read(None)
        _adm, _env, calldata = hd._build_supply(
            live, decision_id=f"p06-parity-{i}", runner=RUNNER_A, key=hd.RUNNER_A_KEY)
        sh("send", CONTROLLER, calldata, "--from", EXECUTOR, "--unlocked")

    state = read(None)
    used = state.used["usedSupply"]
    remaining = allowance_remaining()
    assert used == TARGET_USED, (
        f"parity NOT established: Held usedSupply is {used}, not {TARGET_USED}. The "
        "comparison is invalid unless both branches start from the same economic state.")
    assert remaining == CEILING_OLD - TARGET_USED, (
        f"parity NOT established: Roles allowance remaining is {remaining}, not "
        f"{CEILING_OLD - TARGET_USED}")
    return {"used_supply": used, "ceiling": CEILING_OLD, "remaining": remaining,
            "supplies": TARGET_USED // CHUNK, "chunk": CHUNK,
            "_note": "Held performs three REAL 10,000 USDC supplies through its own "
                     "controller so it starts from the SAME 30,000 consumed / 20,000 "
                     "remaining the native baseline starts from. Asserted, not assumed."}


def run_branch(journal, *, interrupted: bool, label: str) -> dict:
    import hero_demo as hd

    c = Counter()
    live = read(c)
    hid = f"{label}-{int(time.time() * 1000)}"

    if interrupted:
        hd.SUPPLY_AMOUNT = CHUNK
        hd.interrupt_a_real_submission(live, journal)   # a REAL unresolved operation

    m = HandoverMachine.start(journal, handover_id=hid, controller=CONTROLLER,
                              chain_id=CHAIN, retiring_runner=live.runner,
                              retiring_epoch=live.epoch, safe=SAFE, lineage=LINEAGE)

    # --- ceremony 1: fence ---------------------------------------------------------
    fence_tx = m.prepare_fence(current_epoch=live.epoch)
    safe_exec(c, fence_tx.to, fence_tx.data)
    fence_reading = read(c, dispatching=False)
    m.confirm_fenced(fence_reading)

    if interrupted:
        c.recovery_steps += 1
        try:
            m.reconcile(build_report(journal, record=m.record,
                                     fence_reading=fence_reading, reader=None))
            raise RuntimeError("advanced with an unresolved operation")
        except HandoverBlocked as exc:
            c.refusals.append(f"refused while unresolved: {exc.blockers}")
        c.recovery_steps += 1

    c.chain_reads += 1
    c.resolution_stores.add("Held controller consumed[operationId]")
    c.stores.add("Held controller consumed[operationId]")
    m.reconcile(build_report(journal, record=m.record, fence_reading=fence_reading,
                             reader=CastConsumptionReader(RPC, chain_id=CHAIN)))

    inv = collect(env={"HELD_SAFE": SAFE, "HELD_CONTROLLER": CONTROLLER,
                       "HELD_BASE_RPC": RPC, "HELD_INVENTORY_MODE": "handover"}, cwd=ROOT)
    c.stores.update(["Safe state", "Zodiac Roles state", "Morpho authorization state",
                     "ERC20 approval state"])

    paused = read(c, dispatching=False)
    cand = Candidate(runner=RUNNER_B, executor=EXECUTOR, new_epoch=paused.epoch + 1,
                     new_policy_version=2, policy=policy(CEILING_NEW),
                     expected=ExpectedState(*paused.used.values()),
                     native_config_digest=hd.native_config_digest(), lineage=LINEAGE)
    m.prepare_candidate(cand, observed=paused)
    m.clear_authority(inv, fence_block=fence_reading.block_number)

    # --- ceremony 2: ONE real MultiSend carrying setAllowance + activate ------------
    # The controller refuses an activation whose ceiling the Zodiac allowance would not
    # honour (AllowanceDesynchronised), so a raised ceiling must update both in the same
    # change -- exactly as the native I1-clean batch does.
    used_now = paused.used["usedSupply"]
    set_allow = local("calldata",
                      "setAllowance(bytes32,uint128,uint128,uint128,uint64,uint64)",
                      ALLOW_KEY, str(CEILING_NEW - used_now), str(CEILING_NEW), "0", "0", "0")
    act = m.prepare_activation()
    safe_exec(c, MULTISEND, multisend_calldata([(ROLES, set_allow), (CONTROLLER, act.data)]),
              operation=1)                                     # 1 = delegatecall
    final = read(c)
    m.confirm_active(final)

    return {"branch": label,
            "counts": c.as_dict(),
            "starting_used": TARGET_USED,
            "final_used": final.used["usedSupply"],
            "final_ceiling": CEILING_NEW,
            "final_remaining": CEILING_NEW - final.used["usedSupply"],
            "final_roles_remaining": allowance_remaining(),
            "final_runner": final.runner,
            "final_epoch": final.epoch,
            "batch_was_real_multisend": True}


def main() -> int:
    print("=" * 78)
    print("P06 — Held half of the frozen handover comparison")
    print("EVIDENCE GRADE: REAL LOCAL FORK")
    print("=" * 78)

    from held_core.journal import Journal

    print("\nEstablishing parity with the native baseline's starting state")
    parity = establish_parity()
    print(f"  usedSupply {parity['used_supply']} / ceiling {parity['ceiling']} / "
          f"Roles remaining {parity['remaining']}  "
          f"({parity['supplies']} x {parity['chunk']} through the Held controller)")

    results = {}
    for label, interrupted in (("clean", False), ("interrupted", True)):
        sid = snapshot()
        jp = os.path.join(ROOT, "fixtures", "generated", f"p06-{label}.sqlite")
        for s in ("", "-wal", "-shm"):
            if os.path.exists(jp + s):
                os.remove(jp + s)
        j = Journal(jp)
        print(f"\nHELD — {label}")
        results[label] = run_branch(j, interrupted=interrupted, label=label)
        j.close()
        cc = results[label]["counts"]
        print(f"  ceremonies {cc['ceremonies']} / signatures {cc['individual_signatures']} "
              f"/ transactions {cc['submitted_transactions']}")
        print(f"  refusals {len(cc['refusals_raised'])} | resolution stores "
              f"{cc['stores_for_resolution_count']}")
        print(f"  final: used {results[label]['final_used']} / remaining "
              f"{results[label]['final_remaining']} / epoch {results[label]['final_epoch']}")
        revert(sid)                                     # isolate the branches

    native = json.load(open(os.path.join(ROOT, "docs/baseline/native-measurements.json")))
    i1 = next(c for c in native["interruptions"] if c["id"] == "I1-clean")
    i2 = next(c for c in native["competent_native_controls"]
              if c["control"] == "I2-competent")

    rows = [
        ("native clean", i1["ceremonies"], i1["individual_signatures"],
         i1["submitted_transactions"], TARGET_USED, int(i1["remaining_after"])),
        ("held clean", results["clean"]["counts"]["ceremonies"],
         results["clean"]["counts"]["individual_signatures"],
         results["clean"]["counts"]["submitted_transactions"],
         TARGET_USED, results["clean"]["final_remaining"]),
        ("native interrupted", i2["ceremonies"], i2["individual_signatures"],
         i2["submitted_transactions"], TARGET_USED, int(i2["final_remaining"])),
        ("held interrupted", results["interrupted"]["counts"]["ceremonies"],
         results["interrupted"]["counts"]["individual_signatures"],
         results["interrupted"]["counts"]["submitted_transactions"],
         TARGET_USED, results["interrupted"]["final_remaining"]),
    ]

    print("\n" + "-" * 78)
    print(f"{'branch':<20}{'cer':>5}{'sig':>5}{'tx':>5}{'start used':>14}{'remaining':>14}")
    for name, cer, sig, tx, su, rem in rows:
        print(f"{name:<20}{cer:>5}{sig:>5}{tx:>5}{su:>14}{rem:>14}")

    hc, hi = results["clean"]["counts"], results["interrupted"]["counts"]
    comparison = {
        "record": "P06 — measured Held/native handover comparison",
        "evidence_grade": "REAL LOCAL FORK",
        "operation": native["operation"],
        "native_source": "docs/baseline/native-measurements.json (frozen before that run)",
        "parity": parity,
        "isolation": "evm_snapshot before each branch, evm_revert after, so the clean and "
                     "interrupted cases cannot contaminate each other.",
        "accounting": "ONE method. Every ceremony is a real Safe execTransaction signed by "
                      "two of three owners; the change is a real MultiSendCallOnly "
                      "delegatecall. Nothing is counted as batched that was not batched.",
        "table": [{"branch": n, "ceremonies": c, "individual_signatures": s,
                   "submitted_transactions": t, "starting_used": su, "final_remaining": r}
                  for n, c, s, t, su, r in rows],
        "held": results,
        "findings": [
            {"dimension": "owner work, clean change",
             "result": "NATIVE IS CHEAPER" if hc["ceremonies"] > i1["ceremonies"] else "TIE",
             "detail": f"native {i1['ceremonies']}/{i1['individual_signatures']}/"
                       f"{i1['submitted_transactions']} against Held {hc['ceremonies']}/"
                       f"{hc['individual_signatures']}/{hc['submitted_transactions']}. Held "
                       "cannot batch fence with activate: the controller refuses to activate "
                       "while active, and the fence must be CONFIRMED before a candidate is "
                       "pinned. A product constraint, not an accounting artifact.",
             "held_claims_advantage": False},
            {"dimension": "owner work, interrupted change",
             "result": "TIE" if hi["ceremonies"] == i2["ceremonies"] else "NATIVE IS CHEAPER",
             "detail": f"native {i2['ceremonies']}/{i2['individual_signatures']}/"
                       f"{i2['submitted_transactions']} against Held {hi['ceremonies']}/"
                       f"{hi['individual_signatures']}/{hi['submitted_transactions']}. The "
                       "competent native procedure reaches the correct result on the first "
                       "attempt and costs the same.",
             "held_claims_advantage": False},
            {"dimension": "stores consulted to resolve an in-flight operation",
             "result": "HELD IS NARROWER",
             "detail": f"Held answers 'did THAT operation execute?' from "
                       f"{hi['stores_for_resolution_count']} store: consumed[operationId] at "
                       "a stated block, bound to the native decision by the journal. Native "
                       "derives the BUDGET correctly in aggregate from the allowance but "
                       "does not identify which operation ran.",
             "held_claims_advantage": True,
             "caveat": "Native reaches the correct remaining capacity without this."},
            {"dimension": "behaviour when the outcome is unknown",
             "result": "HELD REFUSES; NATIVE HAS NOTHING TO REFUSE WITH",
             "detail": f"the interrupted branch raised {len(hi['refusals_raised'])} "
                       "refusal(s) naming the unresolved operation and would not advance. "
                       "Native has no per-operation record, so there is no state in which "
                       "it can decline.",
             "held_claims_advantage": True,
             "caveat": "A property of the SYSTEM, not the operator. A careful native "
                       "operator following the V4 order reaches the same outcome."},
            {"dimension": "activation-time consistency guard",
             "result": "HELD ENFORCES SOMETHING NATIVE DOES NOT",
             "detail": "The controller refuses an activation whose ceiling the Zodiac "
                       "allowance would not honour (AllowanceDesynchronised), which is why "
                       "the change batch must carry setAllowance and activate together.",
             "held_claims_advantage": True,
             "caveat": "Makes one specific operator error impossible rather than unlikely."},
            {"dimension": "setup and trust cost",
             "result": "HELD COSTS MORE",
             "detail": "A controller deployed and installed, sole membership of two Zodiac "
                       "roles, five budgets configured, and a durable journal.",
             "held_claims_advantage": False},
        ],
        "conclusion": {
            "headline": "Held does not reduce owner work. It costs more on the clean change "
                        "and ties competent native tooling on the interrupted one.",
            "held_adds": ["per-operation resolution from one store",
                          "a refusal the system enforces while an outcome is unknown",
                          "an activation-time consistency guard"],
            "held_costs": ["more owner work on a clean change",
                           "controller, two role memberships, five budgets, a journal",
                           "a further component to trust and maintain"],
            "what_is_NOT_claimed": "That Held is cheaper or faster, or that native tooling "
                                   "cannot do this. The measurements say otherwise.",
        },
        "interruption_semantics": {
            "_warning": "The two interrupted branches do NOT share an interruption, and "
                        "their final remaining figures must not be compared as if they did.",
            "native_I2": "an in-flight supply that DID land (5,000 more consumed), so the "
                         "competent procedure derives 35,000 used and 45,000 remaining.",
            "held": "a submission whose transport never returned and which did NOT reach "
                    "the chain, so consumption stays at 30,000 and 50,000 remains.",
            "what_this_does_and_does_not_show": "Both branches reach the CORRECT remaining "
                                                "capacity for the interruption they actually "
                                                "suffered. Neither preserved more than the "
                                                "other; they faced different events.",
        },
        "limits": [
            "Local Base-mainnet fork only. No public transaction, deployment or spending.",
            "Operator-work counts are counts of discrete contract-level actions, as the "
            "native baseline states of its own numbers. Not a human-factors study.",
            "The native half was measured before Held existed; the halves were not run "
            "simultaneously. The operation, counters and starting state are the same.",
            "Almanak reconfiguration and the authenticated KeeperHub boundary are exercised "
            "on neither side. L10 is open.",
        ],
    }

    out = os.path.join(ROOT, "evidence", "P06", "comparison.json")
    with open(out, "w") as fh:
        json.dump(comparison, fh, indent=2)
        fh.write("\n")
    print(f"\nwrote {os.path.relpath(out, ROOT)}")
    for item in comparison["findings"]:
        print(f"  [{item['result']}] {item['dimension']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
