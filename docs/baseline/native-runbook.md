# Native baseline runbook — RUN

Status: **executed.** All nine declared cases ran on the pinned Base-mainnet fork and are
recorded in `native-measurements.json` with per-case evidence under
`../../evidence/P00/baseline/`. `make check-baseline` passes.

Not independently reviewed. Claude authored and ran this; that is not acceptance.

## Vehicle

`chain=base` + `Network.ANVIL`, forking **Base mainnet**. The pinned SDK supports anvil
natively (`NETWORK_PROFILES[Network.ANVIL].is_local = True`, per-chain local fork URLs in
`almanak/config/runtime.py`). Forking mainnet is what keeps the Morpho address registry
correct — see `route-evidence.json` L6 and L8.

## Corrections, newest first

**v3, 2026-09-16 — the RPC blocker is withdrawn.** The previous revision said "every Base RPC
host tested returns 403 at the egress gateway", and that this runbook therefore could not run.
That was true of the device VM and the cloud container. It is **not** true of the device this
evidence was produced on: `https://mainnet.base.org` answers `eth_blockNumber`, and
`fixtures/with_fork.sh` reaches the pinned block 51353212 in under five seconds. The blocker
description is preserved here as history, not as a current condition.

**v2, 2026-09-15 — manufactured history withdrawn.** The original wording — "set a
non-refilling allowance of 50,000 with 20,000 remaining, representing 30,000 used" — was wrong
and is withdrawn. `balance` is *unused allowance*; it can be set by hand, so configuring 20,000
proves nothing about use. The frozen benchmark objective is unchanged; only the setup
instruction was corrected. Consumption is now established by execution.

## Steps, as actually executed

Each script is idempotent and the whole chain rebuilds from a fresh fork in about 90 seconds.
They must run in **one** invocation — see L12 on fork lifecycle.

1. `fixtures/with_fork.sh` — fork Base mainnet at the pinned block; refuse the fork unless
   chain id, block number and Morpho code all match `fixtures/fork.env`.
2. `01_deploy_safe_and_roles.sh` — 2-of-3 fixture Safe and Zodiac Roles module from the real
   mainnet singletons and factories. Every identity is an anvil deterministic account.
3. `02_enable_module_and_fund.sh` — enable the module through a real two-signature
   `execTransaction`; fund the Safe with 50,000 USDC (balance slot 9) and gas.
4. `03_scope_role.sh` — assign operator A, scope Morpho as the role target.
5. `03b_bind_allowance_and_build_history.sh` — bind supply `assets` to the allowance key with
   `WithinAllowance` (Operator 28), scope `USDC.approve` to Morpho as the only spender, set the
   original **50,000** budget, then **execute three real 10,000 supplies** and watch the
   allowance fall 50,000 → 40,000 → 30,000 → 20,000 by consumption.
6. `03c_quota_isolation.sh` — the isolated over-quota refusal and the exact-quota control,
   each inside its own snapshot (see below).
7. `04_scenarios.sh` — the nine declared cases.
8. `05_native_competent_controls.sh` — the competent-native controls for I2 and I6.
9. `probes/assemble_baseline.py` — bind the run to the frozen protocol digest and write
   `native-measurements.json`. Run it inside the same fork invocation.

## Correction v4, 2026-09-16 — the comparator was not yet competent

The nine cases in step 7 run **one** native procedure: a single batched owner change. Two of
its outcomes failed the customer objective (I2, I6). That establishes what *that procedure*
does. It does not establish that a competent native operator with these same tools cannot reach
the correct outcome — and V4 §9 forbids comparing against a knowingly weaker alternative, while
A1 places this review **before** P01 rather than in P06.

Step 8 therefore runs the complete competent native workflow for both:

- **I2** — fence as its own ceremony, let it settle, read the allowance *actually* consumed,
  derive the new ceiling from that observation, then activate B. Reaches the correct remaining
  capacity first time. Costs two ceremonies rather than one, because the correct value is not
  knowable until the fence has settled.
- **I6** — inventory the Safe's Morpho authorizations and batch `setAuthorization(legacy,false)`
  into the *same* MultiSend as the ceiling change and role swap. Zero extra ceremonies.
  Verified behaviourally in both directions.

The step-7 traces are **retained unchanged** as naive/omission controls. Nothing is replaced,
and neither an expected fault nor an intermediate state is relabelled as a correct outcome.

Each case now records `experiment_result` (did the harness assertions hold), `workflow_outcome`
(was the owner's objective actually achieved safely), `evidence_class` (what was exercised) and
`unmeasured` separately. A PASS can mean the harness successfully reproduced an unsafe state.

## Isolation and state discipline

Every case takes an `evm_snapshot`, asserts the canonical starting state, runs, writes its
evidence, and reverts. Consequences worth stating plainly:

- No case can inherit another case's state.
- The exact-quota control, which drives the allowance to zero, **cannot** leak into the
  measured scenarios — it is reverted.
- The canonical 30,000-used / 20,000-remaining start is re-asserted before each case rather
  than assumed, and re-checked at the end of the run.

`03c` exists because the earlier over-quota attempt was **not** isolated: its top-up had
silently failed (the storage value was not written as a full 32-byte word), so the Safe held
only 20,000 and balance could equally have blocked the transfer. The repaired test reads back
a Safe balance of 100,000 and an ERC20 approval of 25,000 before attempting 25,000 against a
20,000 quota, leaving the Roles quota as the only constraint that can bind.

## Rules while running

- Batch what a competent operator would batch. The owner change goes through Safe
  MultiSendCallOnly 1.4.1 by delegatecall as one ceremony, two signatures, one transaction.
  Do not manufacture extra ceremonies.
- Use native reconciliation where it exists. Do not pretend it is absent.
- Reconstruct the original allowance from history rather than assuming it is unavailable.
- A skipped revocation is an error in the run, not a result.
- Read every result back from chain. Three fixture bugs were caught this way; a fourth
  (`is_member` asserting on `isModuleEnabled`) was caught because the readback disagreed with
  observed behaviour.
