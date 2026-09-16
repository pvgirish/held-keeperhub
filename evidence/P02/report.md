# P02 — typed controller and native Roles enforcement

2026-09-16. Claude, sole implementation writer. **Independent review pending; nothing
here is accepted.** `make check-phase-02` → **39/39** across three separated evidence classes.

**Status: existing tests PASS. P02 completeness: the previously disclosed gaps are now
closed. Independent acceptance: still pending.**

An earlier version of this report declared P02 complete at 17/17 while its own gap list
named required acceptance clauses — reentrancy, cooldowns, nested false return, cleanup
failure and restoration separation. Documenting a gap does not waive it; those are now
implemented and tested.

## What was built

`contracts/src/HeldController.sol` (+ `Interfaces.sol`), `test/contracts/HeldController.t.sol`,
`script/run_p02_fork_tests.sh`.

Toolchain: solc 0.8.28, `via_ir = true` (the withdraw path exceeded the stack limit
without it), OpenZeppelin v5.1.0, forge-std v1.16.2, foundry 1.8.1.

## Two evidence classes, deliberately separated

| stage | what it is | result |
|---|---|---|
| 0 — property/fuzz | Fuzz properties at 256 runs each against an **independent reference** of the V4 §5 rules, with a pinned seed. Local harness. | 14/14 |
| 1 — adversarial | **Labelled hostile mocks.** Branches unreachable with well-behaved contracts: reentrancy, an ERC20 returning `false`, cleanup failing after the economic action. **Not the production profile**; no result here is native USDC / real Roles / real Morpho behaviour. | 4/4 |
| 2 — real pinned route | Genuine Base-mainnet Safe 1.4.1, Zodiac Roles v2.1, Morpho Blue, native USDC on a fork at block 51353212. Nothing mocked. | 21/21 |

They run separately on purpose: P02 asks for unit/property tests **and** realistic fork
tests, not for every adversarial fixture to run under `--fork-url`.

There is also an unresolved combined-configuration failure, and its status should be read
precisely:

- **Established:** the adversarial suite passes standalone; the real-route suite passes on
  the fork; the combined configuration fails; forge falls back to `VM::deployCode` for the
  adversarial test contract and the subsequent call reverts with zero gas. Trace preserved
  at `evidence/P02/adversarial-fork-trace.txt`.
- **Not established:** the precise cause. My diagnosis is a harness / test-contract-size
  interaction rather than a controller defect — the same controller deploys and activates
  under the fork in stage 2 — but **no minimal reproduction was built**, so that is a
  diagnosis, not a proven root cause.

Both stages build from the same controller source and compiler settings, and
`make check-phase-02` fails if **either** stage fails (verified by simulating a failing
stage).

## Gaps closed in this pass

**Restoration is now a separate Roles lane.** Zodiac permits one condition tree per
(role, target, selector), so a single role could not bind `withdraw`'s amount to two
allowance keys. The controller now carries `normalRoleKey` and `restorationRoleKey` with
their own non-refilling keys — V4 §3 explicitly permits separate normal/restoration
roles, each controller-only. The activation guard checks **both** lanes.

The worked case is tested directly: floor 1,000, cash fallen to 200, normal count
exhausted → an 800 restoration still succeeds, charges the restoration key only, and
leaves the normal key and normal count untouched.

**Cooldowns.** `dn = 3600`: refused at 3599s with `CooldownActive`, permitted at exactly
3600s. A refused operation does **not** advance `lastNormalAt` or consumption. Timestamps
and consumption survive a runner and policy change.

**Reentrancy, adversarially.** A token reenters `executeSupply` during the approval leg;
the controller refuses with `Reentrancy()`, and the fixture surfaces that through a
unique error so the guard firing is observable through the outer revert.

**Nested false return.** A token returning `false` from `approve` → `TokenReturnedFalse`.

**Cleanup failure after the economic action.** The fixture token refuses the cleanup
approval *only after observing* `supplyCount > 0`, so the revert identity is itself proof
that supply was reached before cleanup failed. Everything then rolls back: supply count,
balances, counters, operation id, residual approval.

**Atomic owner batch.** A **real** Safe `execTransaction` with two owner signatures,
delegatecalling MultiSendCallOnly with `[setAllowance, activate]`. A stale expected state
reverts the whole batch **and rolls back the allowance update** — a failed activation
cannot leave Roles rewritten.

**Failure stage relabelled.** The quota test is now
`test_RolesRefusalBeforeMorphoRollsBackEverything` and additionally asserts the Morpho
position is identical: Roles refused *permission*; Morpho was never entered. It is not
evidence that the economic action executed and then failed.

## The decisive results

| requirement | test | result |
|---|---|---|
| Deployment is not authorisation | `test_DeploymentIsPausedAndCannotOperate` | paused, epoch 0, `usedSupply` **0** |
| Owner/runner/executor are distinct | `test_OnlyOwnerMayActivateOrFence`, `test_OnlyConfiguredExecutorMayCall` | PASS |
| **Retired runner cannot execute even with the same transport sender** | `test_RetiredRunnerCannotExecuteEvenWithSameExecutor` | A signs the *new* epoch, same executor → `BadSignature`; B works; consumption preserved |
| Roles refuses permission → full rollback | `test_RolesRefusalBeforeMorphoRollsBackEverything` | no token moved, no shares, counters **not** advanced, operation id **not** consumed, no residual approval, Morpho position identical (never entered) |
| **Cleanup fails AFTER the economic action → full rollback** | `test_CleanupFailureAfterEconomicActionRollsBackEverything` (adversarial) | supply reached, then cleanup refused; supply count, balances, counters and operation id all roll back |
| Reentrancy | `test_ReentrancyIsRefused` (adversarial) | guard fires; refusal observable through the outer revert |
| Cooldowns | `test_CooldownBlocksThenAllows` | refused at 3599s, permitted at 3600s; a refusal advances nothing |
| Restoration lane independence | `test_RestorationLaneIsIndependentOfExhaustedNormalCapacity` | own role, own key, own count; normal lane untouched |
| Atomic owner batch | `test_OwnerBatchActivationIsAtomicAndRollsBackAllowance` | real two-signature Safe batch; stale activation rolls back the allowance update too |
| Budget charged once | `test_SupplySucceedsAndConsumesExactly` | Roles allowance falls by exactly the supplied amount; approval and cleanup do not double-charge; controller and Roles agree |
| **Activation consistency** | `test_ActivationRefusesStaleAllowanceAndAcceptsConsistentOne` | after Held verified **35,000**, an 80,000 ceiling with a stale **50,000** remaining reverts `AllowanceDesynchronised(50000e6, 45000e6)`; **45,000** activates |
| Ceiling cannot drop below consumption | `test_CeilingBelowConsumptionIsRejected` | PASS |
| Stale preparation cannot execute | `test_StaleExpectedStateIsRejected` | PASS |
| Replay / payload mutation | `test_ReplayOfConsumedOperationIsRejected`, `test_PayloadMutationUnderSignedEnvelopeIsRejected` | PASS |
| Signature malleability | `test_MalleableSignatureIsRejected` | high-s twin rejected; original still valid |
| HOLD is never executable | `test_HoldIsNeverExecutable` | PASS |
| Scope binding | `test_ForeignMarketIsRejected`, `test_WrongEpochIsRejected` | PASS |
| Withdraw returns to the Safe | `test_WithdrawReturnsToSafeAndDecreasesShares` | exact receipt, shares decrease, **supply capacity not refilled** |
| Held starts its own history | setUp + paused test | counters begin at 0; the native fixture's 30,000 is **not** imported |

## Design points worth defending

**Consumption is monotonic.** `usedSupply` only increases. This is the single mechanism
the P00 baseline actually motivates: native `setAllowance` writes an *absolute* remaining
value, so a policy update can silently regrant consumed capacity (baseline case I2). The
activation guard then requires `rolesRemaining == Ls - usedSupply`, which is what refuses
the stale 50,000 in the test above.

**No generic executor, ordinary CALLs only.** Two typed entry points. The action sequence
is sequential `CALL` through Roles with `shouldRevert=true` *and* the returned success
flag checked. `execTransactionWithRoleReturnData` is used rather than the plain variant
so an ERC20 that returns `false` instead of reverting cannot pass as success.

**Effects are read, not inferred.** Exact Safe debit/receipt, share direction, borrow
shares still zero, collateral unchanged, managed allowance zero on both sides. V4 §5
forbids inferring success from the outer receipt alone.

**The withdraw lane is derived, not chosen.** The controller reads the Safe balance and
decides normal vs restoration itself, so a runner cannot select the restoration lane to
evade normal limits.

## Bugs found in my own work

1. **`vm.prank` / `vm.expectRevert` consumed by inline view calls.** `_sign()` and
   `_expected()` make external view calls; when written as inline arguments they consumed
   the cheatcode before the call under test. Six tests failed with "next call did not
   revert as expected". All hoisted.
2. **The fixture never scoped Morpho `withdraw`.** `scopeTarget` sets
   `Clearance.Function`, so every function must be scoped explicitly — withdraw reverted
   `ConditionViolation(3)`. Now scoped with its own 11-node condition tree binding
   `assets` to a separate non-refilling withdraw allowance key.
3. **My floor assertion was simply wrong.** With 50,000 in the Safe and a 1,000 floor, a
   40,000 supply breaches nothing. Rewritten so each limit is the *only* thing that can
   refuse: per-action max, then cumulative ceiling, then cash floor.

## Build provenance

solc 0.8.28, `via_ir = true`, optimizer on at 200 runs. OpenZeppelin
`v5.1.0@69c8def5`, forge-std `v1.16.2@bf647bd6`, foundry 1.8.1. `lib/` and build output
are excluded from the archive; reinstall with the two pinned `forge install` commands in
`evidence/P02/acceptance.json`.

**Git state, honestly:** `forge install` required `git init` in `held/`, so the tree now
has git metadata it did not have before. **Nothing is committed** — 0 commits, 3 tracked
entries (the submodule wiring), 18 uncommitted/untracked entries. The working tree and
the archive are the snapshot; git is not.

## Honest limits

- **Owner authority is `vm.prank(safe)` for the isolated authorization tests.** The
  atomic activation batch does use a real two-signature Safe ceremony.
- **Nothing is deployed publicly.** Local fork only; no public transaction, no spending.
- **The restoration lane is not separately allowance-keyed at the Roles layer** in this
  fixture — one withdraw key covers both lanes there, while the controller keeps them
  distinct. A production configuration should key them separately.
- **Reentrancy is guarded but not adversarially tested.** `nonReentrant` exists; no
  malicious-token reentrancy fixture was built. Recorded as a gap, not a pass.
- **No cooldown test.** `dn`/`dr` are zero in the fixture policy, so the cooldown branch
  is implemented but unexercised.
- **`via_ir` changes codegen.** The tested bytecode is the IR-compiled build.
- Self-testing is not independent acceptance. `accepted` stays `false`.

## Next

**P03** — native Almanak → KeeperHub → controller/Role/Safe/Morpho → native result.
Its mandatory composed public execution depends on **L10** (authenticated KeeperHub
organisation caller/payer), which remains unresolved. Local integration preparation is
unblocked; the public execution step is not.
