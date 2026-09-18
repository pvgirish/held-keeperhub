# M1 owner decision sheet

Every remaining choice, with a recommendation, the constraint that produces it, and whether
it can be changed later. **Recommendations only — none of these is decided, and nothing here
has been deployed, funded, broadcast or submitted.**

Companion to `M1-PARAMETER-SHEET.md` (what the parameters are) and `M1-EXECUTION-RUNBOOK.md`
(the ordered path and the costs). All values verified against `HeldController.sol` and
`HeldInstall.sol` in the current working tree.

Recommended test amount throughout: **10.000000 USDC** (`10000000` base units).

---

## The decision table

| Parameter | Recommended value | Reason | Source / constraint | Reversible? | Owner decision? |
|---|---|---|---|---|---|
| `normalRole` | `keccak256("held-operator-v1")` = `0xa42add86bc83e750f3ba8a53e81130e2d15a08595fe423aaf8ee7235220647cf` | One encoding convention across all seven keys. Also guarantees a different key from the fork fixture's packed form, so no native history can be inherited | `HeldInstall.Params.normalRole`; V4 §6 forbids importing pre-Held consumption | **No** — constructor immutable. Change = redeploy controller | **Yes** |
| `supplyAmount` key | `keccak256("held-supply-cap")` = `0x771a9951d46e5791484c6fa37347ab116c902522956e3d9a9f33bd787ec63cb2` | Same convention as the five fixed keys; fresh and uncollided on a new Safe | `HeldInstall.Params.supplyKey` | **No** — constructor immutable | **Yes** |
| `newRunner` | A **freshly generated dedicated EOA**, address supplied; key held only as `env:HELD_RUNNER_KEY` | V4 §3: "the supported first signer is an ordinary EOA". Must be distinct from the executor and from every Safe owner | `docs/plan/14_Held_Locked_V4.md` line 93; `RunnerSigner` resolves `env:HELD_RUNNER_KEY` and asserts recovery equals this address | **Yes** — `fence()` + `activate()` at a higher epoch | **Yes** |
| `newExecutor` | **LEAVE UNRESOLVED** | KeeperHub's Turnkey wallet address. Not observable until a controller exists to simulate against | `executeSupply` reverts `NotExecutor` unless `msg.sender == executor` | **Yes** — re-activatable | Deferred (B2) |
| **B3 USDC amount** | **10.000000 USDC** (`10000000`) | Smallest amount with comfortable margin above Morpho share-rounding, while being real capital on a real market | ≤ 40,000e6 (Roles approve bound `MS`); ≤ `Ls` | **Yes** — Safe owners can withdraw the position | **Yes** |
| `ms` (supply minimum) | `10000000` (= amount) | Pins the low edge exactly at the test amount | `amount < ms` reverts `AmountOutOfRange`. Newly found constraint `ms ≤ amount` | **Yes** | **Yes** |
| `Ms` (supply maximum) | `10000000` (= amount) | Pins the high edge too, so the controller can execute **exactly one amount and no other** | `amount > Ms` reverts. Must be ≤ `HeldInstall.MS` = 40,000e6 | **Yes** | **Yes** |
| `F` (liquid cash floor) | `1000000` (1 USDC) | Keeps the floor invariant genuinely live rather than vacuous, for 1 USDC of extra capital. `F = 0` would disable the restoration lane entirely | `balanceAfter < F` reverts; restoration triggers only when `balance < F` | **Yes** | **Yes** |
| `H` (supply-trigger surplus) | `0` | Any `H > 0` demands more funding for no gain on a single execution | `balanceBefore < F + H` reverts | **Yes** | **Yes** |
| `mn` (normal-withdraw minimum) | `1000000` (1 USDC) | Permits a later Held-routed withdraw without being trivially small | `amount < mn` reverts on the normal lane | **Yes** | **Yes** |
| `Mn` (normal-withdraw maximum) | `100000000` (100 USDC) | 10× headroom over the position plus accrued interest; far below `Ln` | Must be ≤ `Ln` = 50,000e6 | **Yes** | **Yes** |
| `Mr` (restoration maximum) | `1000000` (1 USDC) | Restoration can never exceed `F − balance`, and `F` is 1 USDC, so anything larger is unreachable | `amount > F - balanceBefore` reverts | **Yes** | **Yes** |
| `dn` (normal cooldown) | `0` | No safety value on a single execution. Counters update only on success, so a cooldown would not gate a retry either | — | **Yes** | **Yes** |
| `dr` (restoration cooldown) | `0` | Same | — | **Yes** | **Yes** |
| `Ls` | `50000000000` (50,000 USDC) | **Leave as installed.** Deviating means activating a configuration no test covers | Must equal the live Roles allowance balance at activation (`_requireSynced`) | **Yes**, with matching `setAllowance` | Confirm only |
| `Ln` | `50000000000` | Leave as installed | Same | **Yes** | Confirm only |
| `Lr` | `10000000000` (10,000 USDC) | Leave as installed | Same | **Yes** | Confirm only |
| `Nn` | `10` | Leave as installed | Same | **Yes** | Confirm only |
| `Nr` | `5` | Leave as installed | Same | **Yes** | Confirm only |
| `newEpoch` | `1` | Must exceed epoch 0 | `newEpoch <= epoch` reverts `StaleActivation` | n/a | No — determined |
| `newPolicyVersion` | `1` | First policy of this lineage | — | **Yes** | No — determined |
| `ExpectedState` | all five zeros | Only value that can succeed on a never-active controller | `activate` reverts `StaleActivation` on mismatch | n/a | No — determined |
| `retireMember` | `address(0)` | A fresh mainnet Safe has no prior native runner to retire | `HeldInstall.Params.retireMember` | n/a | Confirm only |

### A correction to what I said last turn

I described the five ceilings as "forced". More precisely: they are forced to **equal the
live Roles allowance balances** at activation. The owner may install different balances and
match the policy to them. I am recommending you do **not** — the installed values are what
the P02 and P03 suites exercise, and tightening them would mean activating a configuration
no test covers. The blast radius is bounded by funding instead, which is strictly better
evidence. See below.

---

## Why the blast radius is one execution, without deviating from the tested install

With **funding = 11.000000 USDC**, `F = 1000000` and `ms = Ms = 10000000`:

| | |
|---|---|
| First supply | `balanceBefore` 11 ≥ `F+H` 1 ✔; `amount` 10 within `[ms, Ms]` ✔; `10 ≤ 11 − 1` ✔; `balanceAfter` 1 ≥ `F` 1 ✔ → **executes** |
| Second supply | `balanceBefore` 1 ≥ `F+H` 1 ✔; but `10 ≤ 1 − 1 = 0` is **false** → reverts `FloorViolated` |
| Any other amount | outside `[ms, Ms]` = `[10, 10]` → reverts `AmountOutOfRange` |

So the controller is capable of exactly one supply, of exactly 10.000000 USDC, and the bound
comes from the funded balance and the policy — not from a hand-tightened allowance that no
test has run against. `Nn = 10` is never reached because funding runs out first.

---

## Exact funding requirement from these choices

| Pot | Asset | Minimum | Recommended to send | Why |
|---|---|---|---|---|
| Customer Safe | USDC (native, `0x8335…2913`) | **11.000000** (`11000000`) | **11.000000** | `amount + F` = 10 + 1. **Funding exactly 10 would revert `FloorViolated` after the gas is spent** |
| Owner EOA | ETH on Base | 0.000989 (3× headroom on measured ceremony gas) | **0.002** | Covers the ceremony plus the excluded Base L1 data fee, which is in no ceiling |
| KeeperHub org Turnkey wallet | ETH on Base | 0.000062 (3× headroom on 474,975 gas) | **0.001** | Funded through KeeperHub, not from here. Same L1 data-fee caveat |

Total capital at risk: **11 USDC**, of which 10 becomes a Safe-owned Morpho position and 1
stays as Safe balance. Total spend: **≈ $2.60 of gas** across two pots. The USDC is capital,
not spend — `onBehalf` is the Safe and a withdraw can only pay the Safe.

---

## Reversible vs irreversible, collected

### Irreversible without redeploying the controller
Constructor immutables: `owner`, `safe`, `roles`, `morpho`, `token`, `marketId`, `lineage`,
and **all seven role/allowance keys**. Redeploying costs roughly $0.30 of gas and yields a
new address — which changes the EIP-712 domain separator, so every envelope must be
re-signed. The Safe and Roles module survive untouched.

**Decide `normalRole` and `supplyAmount` before step 4. They cannot be changed after.**

### Irreversible full stop
Only **step 9, the broadcast**. The Morpho position then exists. It is withdrawable by the
Safe owners at any time; it is not undoable.

### Reversible by owner action
- The entire `Policy` (all 14 fields), `runner`, `executor` and `epoch` — `fence()` then
  `activate()` at a higher epoch. Consumption and timestamps are preserved by design.
- Role membership — revocable by the Safe.
- Installed allowances — `setAllowance` again as an owner act.
- Safe funding — withdrawable by the owners at any time.
- Everything at steps 1–8. Nothing before the broadcast commits you to it.

---

## Approved by the owner, 2026-09-18

Every recommendation in the table above was approved. Two items have since been resolved:

- **`newRunner` = `0xEc31ACd93c694c21Db63918B442c73C224080A83`.** Generated 2026-09-18 with
  `eth_account.Account.create()` (os.urandom-backed). The private key was written directly
  to `~/.held/runner-b.key` with mode `0600` under `umask 077`, outside the repository, and
  **was never printed**. `O_EXCL` was used so an existing key could not be clobbered.
  Verified: the file derives exactly this address, and `RunnerSigner` resolves it through
  `env:HELD_RUNNER_KEY` and records only the reference, not the material.

  To use it: `export HELD_RUNNER_KEY="$(cat ~/.held/runner-b.key)"` in the shell that runs
  the ceremony. Never in git, logs, fixtures or recovery exports (V4 §7).

- **`newExecutor` — attempted and NOT resolvable here.** See below.

## `newExecutor`: why it must come from you

Checked, read-only, on 2026-09-18:

| Source | Result |
|---|---|
| `docs.keeperhub.com/api` (reference index) | **No** endpoint under wallets, organization or accounts returns a wallet address |
| `docs.keeperhub.com/api/api-keys` | Documents only `/api/keys` and `/api/api-keys` |
| `docs.keeperhub.com/wallet-management/turnkey` | Documents the UI location; no REST equivalent |
| `docs.keeperhub.com/api/direct-execution` | A simulate response *does* carry `from` = "the org's wallet address used as the sender" |

The simulate route was **not** used. It would require a POST to the execution route against
a contract that does not exist; the documentation says simulation runs `estimateGas` and
`call` against the chain, so a non-existent target is expected to fail before any `from` is
returned. Firing it anyway would be exactly the invalid-target probe this project already
corrected itself for over-claiming from once. Decisive in any case: the organisation key
type is documented as **"Not accepted on user-account, wallet write, OAuth-account-bound,
or per-user endpoints."**

**Obtain it from: KeeperHub web UI → Settings → Organization → Wallets**, for chain 8453.

## Still genuinely open

| | What | Blocked on |
|---|---|---|
| 1 | `newExecutor` | **B2** — owner reads it from the UI path above. No programmatic substitute exists |
| 2 | `SAFE`, `ROLES`, `CONTROLLER` addresses | Outputs of steps 1, 2 and 4 — gated on B4 |
| 3 | Authorization to deploy and spend | **B4** |
