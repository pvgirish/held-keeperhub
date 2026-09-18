# M1 execution runbook

The ordered, costed path from where the repository actually is to **M1 — a real transaction
executed through KeeperHub**. Written before the fact, so the execution can be checked
against a prior commitment rather than described afterwards.

**Nothing in here has been executed.** No contract is deployed, no funds are moved, and no
authorization to do either has been given. The numbers are measured; the decision is not
made.

## Where M1 actually stands

| | |
|---|---|
| Credential | **Exists, and the authenticated route accepts it.** `make check-l10-route-proof` → 200, `hosted=true` |
| Credential scope | **`mcp:read`** — read and simulate only. **Cannot broadcast** |
| Deployed controller | **None**, on any public chain |
| Funded Safe | **None** |
| M1 | **NOT YET ESTABLISHED**, and unreachable on the current credential |

The credential closed request A of `evidence/P03/public-action-request.json`. It did not
close L10, whose question is about the controller call, and it did not move M1 at all.

## The four things only you can clear

| | What | Why it blocks |
|---|---|---|
| **B1** | A KeeperHub key scoped `mcp:write` or `mcp:admin` | `mcp:read` cannot broadcast. Held refuses a broadcast on a read-only scope *before* sending it |
| **B2** | The organisation's **Turnkey wallet address** on Base, funded with ETH | KeeperHub broadcasts from that wallet. `executeSupply` reverts `NotExecutor` unless `msg.sender == executor`, and `executor` is fixed at `activate()`. **This address is a required input to step 7** |
| **B3** | A funded owner EOA on Base, and a fixed USDC amount | The EOA pays the ceremony. The amount must be agreed, not inherited from the fixture's 100 USDC |
| **B4** | Explicit authorization to deploy and spend | Choosing to escalate is not that authorization |

**B2 is the one that is easy to get wrong.** It is newly established and it is not in any
earlier version of this plan: there are **two separate gas payers**. The owner EOA pays the
ceremony; KeeperHub's own Turnkey wallet pays the one `executeSupply` broadcast. Funding one
does not fund the other, and activating against the wrong executor address yields a
controller that refuses every call until it is re-activated. It costs gas, not funds.

## What it costs

Measured, not estimated: `script/measure_mainnet_gas.sh` ran the real ceremony against the
pinned Base-mainnet fork and read `gasUsed` out of 33 receipts;
`script/measure_execute_supply_gas.sh` then measured the one `executeSupply` on the same
fork; `script/price_mainnet_gas.py` priced both against live Base fees and the on-chain
Chainlink ETH/USD feed.

| | Gas | At the observed price |
|---|---|---|
| Ceremony (Safe, Roles, controller, scoping, allowances, activation) | 7,587,624 measured | ~$0.82 |
| One `executeSupply` | 474,975 measured | ~$0.05 |
| **Ceiling at 3× headroom** | | **0.000989 ETH owner EOA + 0.000062 ETH KeeperHub wallet ≈ $2.60** |

**Updated 2026-09-18.** The `executeSupply` row previously read *1,200,000 upper bound, not
measured*. It is now measured, and it came in at **40% of that bound**. The prices moved
too — the ceremony's dollar figure rose while its gas did not, because the priority fee at
the new snapshot was higher.

Three honest caveats on those numbers:

- The 7,587,624 is the **fixture** ceremony, which is a *superset* of the minimal mainnet
  path — it also builds consumption history and a quota-isolation case. For a ceiling that
  errs in the right direction. It is not the exact mainnet figure.
- The 474,975 is **447,799 fork-measured execution gas + 27,176 computed intrinsic gas**
  over the real 644-byte calldata. It measures the *same bytes the composed run executes*,
  built from the real pinned compiler output. It is **not a receipt** — a receipt needs a
  real transaction, which on the fork would require the controller deployed and activated
  on anvil rather than inside the forge VM, with the calldata rebuilt against that address
  because the EIP-712 domain separator commits to it. That path was not invented for a
  five-cent figure. It **errs high**: EIP-3529 refunds are applied at the end of a real
  transaction and can only make a receipt lower.
- **Neither figure includes Base's L1 data fee.** Base is an OP-stack chain and charges one
  on top of `gasUsed × gasPrice`. It is recorded as a known gap in
  `evidence/P03/m1-cost-ceiling.json` rather than quietly omitted, and should be settled
  before the ceremony begins.

The prices are a snapshot and are stale immediately; re-run `script/price_mainnet_gas.py`
before the ceremony. The gas is stable, the price is not.

**Gas is not the real decision.** At under a dollar, the decision is the USDC amount and the
willingness to hold a Morpho position. That USDC is *capital, not spend*: the Safe owns the
position, `onBehalf` is the Safe, and a withdraw can only pay the Safe.

## The ordered path

Dependency-correct. The controller's constructor takes the Safe and the Roles module, and
its EIP-712 domain separator commits to its own address, so no envelope can be signed before
step 4 exists.

| # | Action | Depends on | Spends | Reversible |
|---|---|---|---|---|
| 1 | Deploy or identify the 2-of-3 customer Safe | — | gas | yes |
| 2 | Deploy the Zodiac Roles module, enable it on the Safe | 1 | gas | yes |
| 3 | Choose role keys and non-refilling allowance keys | 2 | — | yes |
| 4 | Deploy `HeldController` (paused at construction) | 1, 2, 3 | gas | yes |
| 5 | Owner ceremony: scope targets and conditions, bind **non-refilling** allowances, assign the controller as sole role member | 4 | gas | yes — role revocable |
| 6 | Fund the Safe with the agreed USDC | — | the amount | yes — owners can withdraw |
| 7 | Owner activation with explicit `ExpectedState`, the reviewed authority inventory, **and the KeeperHub Turnkey wallet as `executor`** | 5, 6, **B2** | gas | yes — re-activatable |
| 8 | Authenticated **simulate** preflight against the real controller | B1 (read is enough), 7 | nothing | n/a |
| 9 | Broadcast the one supply | 8 passing, **B1 with write scope** | gas + moves USDC into Morpho | **no** — the position exists; withdrawable, not undoable |

Step 8 is the first step that produces genuine evidence about **L10's actual question**, and
about **P19** (whether KeeperHub's server-side encoder reproduces Held's intended calldata).
Both are currently NOT YET ESTABLISHED.

## Stop conditions

Inherited from `evidence/P03/public-action-request.json` and still in force:

- The authenticated preflight returns 401 or 403 → **record it and stop.** That is a real
  L10 answer and does not justify retrying on a different route.
- KeeperHub's server-side encoding differs from Held's intended calldata → **stop** and
  settle the encoder question before any broadcast.
- The authority inventory reports any INCOMPLETE section → activation is blocked by V4 §6.
- Any step's readback disagrees with what was intended → stop.

## What M1 would and would not then support

M1 verified would make `| M1 |` in the claim ledger VERIFIED at grade `PUBLIC CHAIN`, and
would unblock P18. It would **not** by itself establish **M2** (that the transaction
corresponds to the integrated workflow), which is a separate claim with its own evidence,
and it has no bearing on M3 or M4.
