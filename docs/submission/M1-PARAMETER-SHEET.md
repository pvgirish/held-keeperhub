# M1 parameter sheet — steps 3 and 7

Every value the M1 ceremony needs at **step 3** (choose role and allowance keys) and
**step 7** (owner activation), separated into what is *already fixed by the code*, what is
*forced by a contract invariant*, and what is *genuinely an open choice*.

**Paper only. Nothing here has been deployed, funded, broadcast or submitted.** This is
written before the fact so the ceremony can be checked against a prior commitment.

Companion to `M1-EXECUTION-RUNBOOK.md`, which has the ordered path and the costs.

Derived from `contracts/src/install/HeldInstall.sol` and `contracts/src/HeldController.sol`
at the current working tree. Values recomputed independently with `cast` and cross-checked
against `fixtures/generated/held-install-manifest.json`, which the 2026-09-18 bootstrap
rehearsal read back on the fork.

---

## Step 3 — role keys and allowance keys

The controller takes **seven** keys in `HeldController.Keys`. Five are constants in
`HeldInstall` and are not decisions; two are `HeldInstall.Params` fields and are.

### Fixed by the code — five of seven

| Keys field | Constant | Preimage | Value |
|---|---|---|---|
| `restorationRole` | `RESTORE_ROLE` | `keccak256("held-restoration-v1")` | `0xad5e119df756c7a61cf7391a44f6005729ca211e9d19d7c2d5e4b143cab049c9` |
| `normalWithdrawAmount` | `WITHDRAW_KEY` | `keccak256("held-withdraw-cap")` | `0x75b80a4223ed54e07d15ae036ea29bbd579be7229b1f0f19c15349fb9419ba02` |
| `restorationAmount` | `RESTORE_KEY` | `keccak256("held-restoration-cap")` | `0x33b7a1087cc5f69fafc4dd1125f2c17abf70b277b5edcfe36dc930ea88a5f680` |
| `normalCount` | `NORMAL_COUNT_KEY` | `keccak256("held-normal-count")` | `0xd1a3cff9379833a9717789833503118af84eed2cf5c696bfb48f36ceb84762ed` |
| `restorationCount` | `RESTORE_COUNT_KEY` | `keccak256("held-restoration-count")` | `0xe342f32716a9c9637d8c5e7701681e4f37dd2270bf0f76dc69b00879567e00dc` |

Changing any of these means editing `HeldInstall`, which the P02 fork suite would catch.

### A choice — two of seven

| Keys field | `Params` field | Fixture value today | Mainnet |
|---|---|---|---|
| `normalRole` | `p.normalRole` | `0x68656c642d6f70657261746f722d763100…` | **UNRESOLVED — your choice** |
| `supplyAmount` | `p.supplyKey` | `0x68656c642d737570706c792d6361700000…` | **UNRESOLVED — your choice** |

#### Finding: the two chosen keys use a different encoding convention from the five fixed ones

`fixtures/scripts/03_scope_role.sh` derives them with `cast format-bytes32-string`, which
right-pads the raw ASCII into `bytes32`. The five constants use `keccak256`. Zodiac accepts
any `bytes32` as a role or allowance key, so both work — but one installation carrying two
conventions is a footgun, and the packed form is the one a reader is most likely to
mis-transcribe. For reference, the same two names under the other convention:

| Name | `format-bytes32-string` (fixture today) | `keccak256` (matches the other five) |
|---|---|---|
| `held-operator-v1` | `0x68656c642d6f70657261746f722d763100000000000000000000000000000000` | `0xa42add86bc83e750f3ba8a53e81130e2d15a08595fe423aaf8ee7235220647cf` |
| `held-supply-cap` | `0x68656c642d737570706c792d6361700000000000000000000000000000000000` | `0x771a9951d46e5791484c6fa37347ab116c902522956e3d9a9f33bd787ec63cb2` |

**Recommendation, not a decision taken:** use the `keccak256` form on mainnet so all seven
keys share one convention. This is a real change from the fixture and is left open
deliberately.

#### Two constraints on whichever values are chosen

1. **`normalRole` must not collide with an existing role on the mainnet Roles module.** A
   collision silently inherits foreign membership and conditions.
2. **`supplyAmount` must not collide with an existing allowance key.** On the fork it
   *deliberately* points at the pre-existing native `held-supply-cap` budget carrying
   20,000 USDC of P00 consumption history — that is the P00 baseline fixture, not the
   intended mainnet shape. V4 §6 forbids importing pre-Held native consumption into a new
   lineage, so a **fresh, unused key** is required for a new dedicated Safe.

### Non-key installation terms, all fixed

| Term | Value |
|---|---|
| `morpho` | `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` |
| `token` (loan asset, native USDC) | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` |
| collateral | `0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452` |
| oracle | `0xD7A1abA119a236Fea5BBC5cAC6836465cbe9289A` |
| IRM | `0x46415998764C29aB2a25CbeA6254146D50D22687` |
| LLTV | `860000000000000000` (86%) |
| **`marketId`** | **`0x13c42741a359ac4a8aa8287d2be109dcf28344484f91185f9a79bd5a805a55ae`** |
| **`lineage`** | **`0x0000000000000000000000000000000000000000000000000000000000000011`** |

`marketId = keccak256(abi.encode(loanToken, collateralToken, oracle, irm, lltv))`,
recomputed independently here and equal to the manifest's value.

### The five native budgets `install()` configures

All non-refilling (`refill=0, period=0, timestamp=0`), balance equal to max.

| Allowance key | Constant | Value |
|---|---|---|
| supply amount | `LS` | 50,000.000000 USDC |
| normal withdraw amount | `LN` | 50,000.000000 USDC |
| restoration amount | `LR` | 10,000.000000 USDC |
| normal count | `NORMAL_COUNT` | 10 |
| restoration count | `RESTORE_COUNT` | 5 |

`MS = 40,000e6` is the **approval value bound** in the condition tree, not an allowance.
Do not confuse it with `Policy.Ms`.

---

## Step 7 — owner activation

```solidity
activate(uint64 newEpoch, uint32 newPolicyVersion, address newRunner,
         address newExecutor, Policy p, ExpectedState expected)
```

### Scalars

| Argument | Value | Basis |
|---|---|---|
| `newEpoch` | **1** | `activate` reverts `StaleActivation` unless `newEpoch > epoch`, and a freshly installed controller is at epoch 0 |
| `newPolicyVersion` | **1** | first policy of this lineage |
| `newRunner` | **UNRESOLVED — your choice** | the mainnet Held runner signing identity. The fixture uses an anvil account; that is local-fixture-only and must never be used |
| `newExecutor` | **UNRESOLVED — B2, and genuinely blocked** | see below |

#### `newExecutor` is the one that cannot be resolved on paper

It must be the **KeeperHub organisation Turnkey wallet address on Base**. `executeSupply`
reverts `NotExecutor` unless `msg.sender == executor`, and `executor` is fixed at
`activate()`. It is readable from KeeperHub's wallet-management UI, or observable as the
`from` field of an authenticated simulate-mode response — but a simulate response needs a
deployed controller, which is step 4, which is after B4. **So on the current read-only
credential and with nothing deployed, this value cannot be obtained from this
repository.** Activating with a wrong address costs gas and yields a controller that
refuses every call until re-activated. It is not fund-threatening.

### `ExpectedState` — fully determined, not a choice

| Field | Value |
|---|---|
| `usedSupply` | 0 |
| `usedNormalWithdraw` | 0 |
| `usedRestoration` | 0 |
| `normalCount` | 0 |
| `restorationCount` | 0 |

`activate` reverts `StaleActivation` if any field disagrees with the controller's live
counters, and obligation 11 of the bootstrap checklist independently asserts the controller
is paused at epoch 0 with zero consumption in all five dimensions. For an initial
activation on a never-active controller, all zeros is the only value that can succeed.

### `Policy` — five fields forced, nine chosen

**Forced by `_requireSynced`.** At `activate`, for every one of the five budget
dimensions, the *live Roles allowance balance* must equal `ceiling − consumption`.
Consumption is zero at initial activation, so each ceiling must equal the installed
balance **exactly**. These are not policy decisions at this step:

| Field | Forced value | Equals |
|---|---|---|
| `Ls` | 50,000.000000 USDC | `HeldInstall.LS` |
| `Ln` | 50,000.000000 USDC | `HeldInstall.LN` |
| `Lr` | 10,000.000000 USDC | `HeldInstall.LR` |
| `Nn` | 10 | `HeldInstall.NORMAL_COUNT` |
| `Nr` | 5 | `HeldInstall.RESTORE_COUNT` |

A different ceiling is reachable only by changing the installed allowance to match, as an
owner act, before activating. Because `install()` already sets balance = max = these
values, **no allowance re-sync is needed at initial activation if the policy uses them.**

**Genuinely chosen.** Fixture values shown as a starting point, not as a recommendation:

| Field | Meaning | Fixture value | Mainnet |
|---|---|---|---|
| `Ms` | per-action supply maximum | 40,000.000000 | must be **≥** the B3 amount |
| `Mn` | per-action normal-withdraw maximum | 10,000.000000 | open |
| `Mr` | per-action restoration maximum | 5,000.000000 | open |
| `ms` | per-action supply **minimum** | 1,000.000000 | must be **≤** the B3 amount — see below |
| `mn` | per-action normal-withdraw minimum | 1,000.000000 | open |
| `F` | liquid cash floor | 1,000.000000 | see below |
| `H` | supply-trigger surplus | 0 | open |
| `dn` | normal cooldown (chain seconds) | 0 | open |
| `dr` | restoration cooldown (chain seconds) | 0 | open |

---

## Two constraints that link step 7 to B3, and are easy to miss

Both are read directly off `HeldController.executeSupply`. Neither is stated in the
runbook, and both would fail *after* the gas is spent.

### 1. `ms` must be ≤ the agreed USDC amount

The fixture's `ms` is 1,000 USDC. The real pinned compiler produced a **100 USDC** supply,
and the composed run had to lower `ms` to admit it — see
`HeldComposed.t.sol::_activateForComposedAmount`, which lowers `ms` rather than rewriting
the compiler's output. **If B3's amount is under 1,000 USDC and `ms` is left at the fixture
default, activation succeeds and the supply is then refused.**

### 2. The Safe must be funded with more than the supply amount

`executeSupply` enforces three floor conditions:

```
balanceBefore >= F + H
amount        <= balanceBefore - F
balanceAfter  >= F
```

So the **minimum Safe funding is `amount + F`** (and at least `F + H`). With the fixture's
`F = 1,000` USDC, funding the Safe with exactly the supply amount reverts `FloorViolated`.

Runbook step 6 currently reads "Fund the Safe with the agreed USDC" and does not say this.
**It is underspecified**, and the amount is B3, which is yours to fix. Setting `F = 0`
would remove the constraint but also removes the cash floor the policy exists to enforce;
that is a policy decision, not a workaround to apply silently.

---

## Unresolved parameters, collected

| # | Parameter | Step | Why it is open |
|---|---|---|---|
| 1 | `normalRole` | 3 | Your choice. Encoding convention also open — see the finding above |
| 2 | `supplyAmount` key | 3 | Your choice. Must be fresh and uncollided |
| 3 | `newRunner` | 7 | Your choice. The mainnet Held runner identity |
| 4 | **`newExecutor`** | 7 | **B2 — genuinely blocked.** Needs KeeperHub's Turnkey wallet address, unobtainable on a read-only credential with nothing deployed |
| 5 | `Ms, Mn, Mr, ms, mn, F, H, dn, dr` | 7 | Policy choices. `ms` and `Ms` are constrained by the B3 amount; `F` is constrained by the funding |
| 6 | The USDC amount | B3/6 | Yours. Determines `ms`, `Ms` and the minimum funding |
| 7 | `SAFE`, `ROLES`, `CONTROLLER` addresses | 1, 2, 4 | Outputs of steps that spend gas. Cannot exist before B4 |

Items 1, 2, 3, 5 and 6 are decidable now, on paper, without spending anything. Item 4 is
blocked on B2. Item 7 is blocked on B4 by construction.
