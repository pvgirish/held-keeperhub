# M1 irreversible-action preflight

Every action that would be taken, in execution order, with its signer, destination, spend,
expected result, reversibility and the evidence it produces.

**Status: NOT EXECUTED. No action below has been performed.** Written before the fact so
the execution can be checked against a prior commitment rather than described afterwards.

Approved parameters are in `M1-OWNER-DECISION-SHEET.md`. Gas figures come from
`evidence/P03/m1-cost-ceiling.json` (measured; the `executeSupply` row is fork-measured,
not a public receipt, and excludes Base's L1 data fee).

**Two blockers remain and both are the owner's.** See the end of this file.

---

## Signers

| Label | What it is | Holds |
|---|---|---|
| **OWNER** | The 2-of-3 customer Safe, acting through its owner EOAs | Pays every ceremony transaction. ETH on Base |
| **DEPLOYER** | An owner EOA sending deployment transactions | Same pot as OWNER in practice |
| **RUNNER B** | `0xEc31ACd93c694c21Db63918B442c73C224080A83` — generated 2026-09-18, key at `~/.held/runner-b.key` (0600), referenced only as `env:HELD_RUNNER_KEY` | Signs the EIP-712 envelope. **Spends nothing, never touches chain** |
| **KEEPERHUB** | The organisation's managed signer on Base — `0x24192B75e297dC1c7a42DcB8C04227818E78acd0`, supplied by the owner 2026-09-18. **B2 address half RESOLVED**; EIP-55 checksum valid; confirmed an EOA (no code) at nonce 0 on chain 8453 | Pays the one `executeSupply` broadcast |
| **OWNER A / DEPLOYER** | `0x9c7bfBb4aBcF2C901a395B81cFcC3De4b214b522` — supplied 2026-09-18 | Pays and submits every ceremony transaction |
| **OWNER B** | `0x29fcC6F012b580d4C67C128b8fDf84B105C9489C` | Co-signer only. **Needs no ETH** |
| **OWNER C** | `0xD1665C7F598d3905CF76698cd35cC459555926a0` | Co-signer only. **Needs no ETH** |

## Safe configuration

**2-of-3**, owners in this order: Owner A, Owner B, Owner C. Any two signatures authorise a
Safe transaction; only the *submitting* owner spends gas, which is why B and C need none.

**This session holds no owner private key or keystore password, has not requested one, and
will not accept one.** The ceremony is owner-run: I produce calldata and verify readbacks.

## Preflight gate result, 2026-09-18 — STOPPED AT STEP 0b

Run before any irreversible action, against `https://mainnet.base.org` at block 51460346:

| Check | Result |
|---|---|
| Chain is Base / 8453 | **PASS** — `cast chain-id` = 8453 |
| `newExecutor` well-formed and an EOA | **PASS** — EIP-55 valid, no code, nonce 0 |
| `newExecutor` funded ≥ 0.001 ETH | **FAIL — 0 ETH** |
| `newRunner` matches the generated key | **PASS** — `0xEc31ACd93c694c21Db63918B442c73C224080A83` |
| Owner EOA address supplied | **PASS** — Owner A, 2026-09-18 |
| Safe owner set (3 owners for 2-of-3) | **PASS** — supplied and verified |
| All five identities checksum-valid, EOAs, distinct | **PASS** — block 51460702 |
| **Owner A funded ≥ 0.002 ETH** | **FAIL — 0 ETH** |
| Deployer signing capability present | **n/a — owner-run.** By design this session has no key |

**Stopped before step 1. No transaction was constructed, signed or sent.**

### Address verification, block 51460702

| Role | Address | Checksum | Code | Nonce | Balance |
|---|---|---|---|---|---|
| Owner A / deployer | `0x9c7bfBb4aBcF2C901a395B81cFcC3De4b214b522` | valid | none (EOA) | 0 | **0 ETH** |
| Owner B | `0x29fcC6F012b580d4C67C128b8fDf84B105C9489C` | valid | none (EOA) | 0 | 0 ETH |
| Owner C | `0xD1665C7F598d3905CF76698cd35cC459555926a0` | valid | none (EOA) | 0 | 0 ETH |
| KeeperHub executor | `0x24192B75e297dC1c7a42DcB8C04227818E78acd0` | valid | none (EOA) | 0 | **0 ETH** |
| Runner B | `0xEc31ACd93c694c21Db63918B442c73C224080A83` | valid | none (EOA) | 0 | 0 ETH — correct, it never transacts |

All five distinct. No duplicates.

---

## The sequence

| # | Action | Signer | Destination | Spends | Expected result / state | Reversible | Evidence produced |
|---|---|---|---|---|---|---|---|
| 0a | Read the Turnkey wallet address from KeeperHub UI (Settings → Organization → Wallets) | owner, manually | — | nothing | `newExecutor` fixed | n/a | recorded in the activation record |
| 0b | Fund the owner EOA | external | owner EOA | **0.002 ETH** | EOA funded on Base | yes — withdrawable | balance readback |
| 0c | Fund the KeeperHub Turnkey wallet | via KeeperHub | Turnkey wallet | **0.001 ETH** | broadcast pot funded | yes | KeeperHub UI |
| 1 | Deploy / identify the 2-of-3 Safe | DEPLOYER | new contract | gas | **SAFE** address; 3 owners, threshold 2 | yes | deployment receipt |
| 2 | Deploy Zodiac Roles module; `enableModule` on the Safe | DEPLOYER, then OWNER | new contract, then SAFE | gas | **ROLES** address; owner/avatar/target all = SAFE | yes — module disableable | receipts |
| 3 | Commit the two chosen keys | — | — | nothing | `normalRole` = `0xa42add86…47cf`, `supplyAmount` = `0x771a9951…3cb2` | **NO — constructor immutable from step 4** | the parameter sheet |
| 4 | Deploy `HeldController` | DEPLOYER | new contract | gas | **CONTROLLER** address, `active=false`, `epoch=0`, all five counters 0 | yes — redeploy (~$0.30), but a new address invalidates every signed envelope | receipt + readback |
| 5 | Owner ceremony — `InstallPausedHeld`: scope targets and conditions, bind the five non-refilling allowances, controller as sole member of both roles, `retireMember = address(0)` | OWNER | ROLES | gas | Controller is sole role member; 5/5 allowances non-refilling at 50,000 / 50,000 / 10,000 USDC, 10, 5 | yes — role revocable, allowances re-settable | install manifest |
| 6 | Fund the Safe | external | SAFE | **11.000000 USDC** | Safe USDC balance = 11.000000 | yes — owners withdraw at any time | balance readback |
| 7 | **Bootstrap authority evidence** against the real Safe at a stated finalized block | read-only | — | nothing | 9 sections COMPLETE, 14/14 obligations | n/a | `bootstrap-rehearsal.json` (mainnet) |
| 8 | Owner activation | OWNER | CONTROLLER | gas | `active=true`, `epoch=1`, `policyVersion=1`, `runner`=RUNNER B, `executor`=Turnkey wallet, policy as approved | yes — `fence()` then re-activate at a higher epoch; consumption preserved | `Activated` event + readback |
| 9 | Build and sign the envelope | RUNNER B | — | nothing | EIP-712 signature over the operation | yes — nothing sent | journal entry, claim written before I/O |
| 10 | **Authenticated SIMULATE preflight** | `env:HELD_KEEPERHUB_API_KEY` (`mcp:read`) | KeeperHub `/api/execute/contract-call`, `simulate: true` | **nothing** | `success`, `wouldRevert: false`, `from` = Turnkey wallet, gas estimate | n/a — no state change | **first real L10 and P19 evidence** |
| 11 | Swap in the write-capable key (**B1**) | owner | environment only | nothing | `HELD_KEEPERHUB_API_KEY` resolves to the `mcp:write` key | yes — swap back | re-run `make check-l10-route-proof` |
| 12 | **Broadcast the one supply** | KEEPERHUB (Turnkey wallet) | CONTROLLER `executeSupply` | **gas (~474,975) + moves 10.000000 USDC into Morpho** | Safe debited exactly 10 USDC; Morpho position created `onBehalf` = SAFE; `usedSupply`=10e6; `normalCount`=1; `consumed[opId]` written | **NO** | tx hash, receipt, **M1** |
| 13 | Reconcile the journal from the on-chain reading | local | — | nothing | operation CONFIRMED against the real `consumed[]` reading | n/a | reconciliation record, **M2 input** |

**Step 12 is the only irreversible action.** Everything at steps 0–11 is reversible or
costs nothing but gas. After step 12 the Morpho position exists; it is withdrawable by the
Safe owners at any time, but it is not undoable.

---

## Stop conditions, still in force

Inherited from `evidence/P03/public-action-request.json`:

- Step 10 returns 401 or 403 → **record it and stop.** That is a real L10 answer and does
  not justify retrying on a different route.
- KeeperHub's server-side encoding differs from Held's intended calldata → **stop** and
  settle the encoder question before any broadcast.
- Step 7 reports any INCOMPLETE section → activation is blocked by V4 §6.
- Any step's readback disagrees with what was intended → stop.

Additional, from the constraints found while preparing this:

- Safe USDC balance is not exactly 11.000000 before step 12 → stop. Funding below
  `amount + F` reverts `FloorViolated` after the gas is spent.
- The activated `executor` does not equal the address read at step 0a → stop. Every call
  will revert `NotExecutor` until re-activation.

---

## What is still blocking

| | Blocker | Owner | Why it cannot be cleared here |
|---|---|---|---|
| **B2** | KeeperHub Turnkey wallet address | you | No documented REST endpoint returns it, and the `kh_` organisation key is documented as not accepted on wallet endpoints. UI only: **Settings → Organization → Wallets** |
| **B4** | Explicit authorization to deploy and spend | you | Not given |

B1 is deliberately deferred to step 11 and is not needed before it. B3 is decided
(10 USDC) and its funding amounts are fixed above.
