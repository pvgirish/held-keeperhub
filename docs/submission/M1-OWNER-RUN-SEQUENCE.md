# M1 owner-run sequence — steps 1 to 8

You sign and broadcast every transaction below from your own wallet. **This session holds
no owner or deployer key, has not asked for one, and will not accept one.** My part is to
produce the calldata, verify every precondition and readback, and stop on any mismatch.

**Status: NOTHING EXECUTED.** No transaction below has been signed or sent.

Chain for every action: **Base, chain id 8453.**

## Fixed identities

| | |
|---|---|
| `newRunner` | `0xEc31ACd93c694c21Db63918B442c73C224080A83` — signs only, never transacts, needs no ETH |
| `newExecutor` | `0x24192B75e297dC1c7a42DcB8C04227818E78acd0` — KeeperHub managed signer, EIP-55 valid, EOA, nonce 0 |
| `normalRole` | `0xa42add86bc83e750f3ba8a53e81130e2d15a08595fe423aaf8ee7235220647cf` |
| `supplyAmount` key | `0x771a9951d46e5791484c6fa37347ab116c902522956e3d9a9f33bd787ec63cb2` |
| `marketId` | `0x13c42741a359ac4a8aa8287d2be109dcf28344484f91185f9a79bd5a805a55ae` |
| `lineage` | `0x00…0011` |

## Canonical Base contracts — all verified to hold code at head (block 51460346)

| | Address |
|---|---|
| Safe singleton v1.4.1 | `0x41675C099F32341bf84BFc5382aF534df5C7461a` |
| SafeProxyFactory | `0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67` |
| Zodiac ModuleProxyFactory | `0x000000000000aDdB49795b0f9bA5BC298cDda236` |
| Zodiac Roles v2 mastercopy | `0x9646fDAD06d3e24444381f44362a3B0eB343D337` |
| Morpho Blue | `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` |
| USDC (native) | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` |

---

## Step 1 — deploy the 2-of-3 Safe

| | |
|---|---|
| from | **Owner A, `0x9c7bfBb4aBcF2C901a395B81cFcC3De4b214b522`** — see "On `from`" below |
| to | `0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67` (SafeProxyFactory) |
| value | 0 |
| function | `createProxyWithNonce(address _singleton, bytes initializer, uint256 saltNonce)` |
| `_singleton` | `0x41675C099F32341bf84BFc5382aF534df5C7461a` |
| `initializer` | `setup([0x9c7bfBb4aBcF2C901a395B81cFcC3De4b214b522, 0x29fcC6F012b580d4C67C128b8fDf84B105C9489C, 0xD1665C7F598d3905CF76698cd35cC459555926a0], 2, 0x0, 0x, 0x0, 0x0, 0, 0x0)` — **supplied 2026-09-18 and rehearsed on a fork** |
| `saltNonce` | `20260918` — the value the fork rehearsal used |
| expected gas | ~290,000 |
| reversible | yes — an unused Safe costs only the gas |

**Readback I will verify:** `getOwners()` equals your three addresses in order, `getThreshold()` = 2, `VERSION()` = `1.4.1`, and the proxy has code. **Evidence to capture:** tx hash, deployed **SAFE** address, explorer link.

---

## Step 2 — deploy the Roles module, then enable it on the Safe

### 2a — deploy (plain EOA transaction)

| | |
|---|---|
| from | **Owner A, `0x9c7bfBb4aBcF2C901a395B81cFcC3De4b214b522`** |
| to | `0x000000000000aDdB49795b0f9bA5BC298cDda236` (Zodiac ModuleProxyFactory) |
| value | 0 |
| function | `deployModule(address masterCopy, bytes initializer, uint256 saltNonce)` |
| `masterCopy` | `0x9646fDAD06d3e24444381f44362a3B0eB343D337` |
| `initializer` | `setUp(abi.encode(SAFE, SAFE, SAFE))` — owner, avatar and target all the Safe |
| expected gas | ~180,000 |
| reversible | yes |

**Readback:** `owner()`, `avatar()` and `target()` all equal **SAFE**. A Roles proxy is EIP-1167 minimal, so ~93 chars of code is correct — I verify behaviour, not code size. **Capture:** tx hash, **ROLES** address.

### 2b — enable it (Safe transaction, 2-of-3)

| | |
|---|---|
| from | **SAFE**, via `execTransaction`, 2 owner signatures |
| to | **SAFE** (self-call) |
| value | 0 |
| calldata | `enableModule(ROLES)` → `0x610b5925` + ROLES left-padded to 32 bytes |
| expected gas | ~77,000 |
| reversible | **yes** — `disableModule` |

**Readback:** `getModulesPaginated` includes ROLES. **Capture:** tx hash.

---

## Step 3 — commit the keys

No transaction. The two chosen keys above become constructor arguments at step 4 and are
**immutable from that point**. This is the last moment they can change without redeploying.

---

## Step 4 — deploy `HeldController` (plain EOA transaction)

| | |
|---|---|
| from | **Owner A, `0x9c7bfBb4aBcF2C901a395B81cFcC3De4b214b522`** — the deployer does **not** become the owner; the constructor takes `_owner` explicitly. Verified on the fork: an EOA-deployed controller reported `owner()` = the Safe |
| to | none — contract creation |
| value | 0 |
| data | `HeldController` creation bytecode + abi-encoded `(SAFE, ROLES, MORPHO, USDC, marketId, lineage, Keys)` |
| expected gas | ~3,400,000 |
| reversible | redeployable for ~$0.30, **but a new address changes the EIP-712 domain separator and invalidates every signed envelope** |

`Keys` in order: `normalRole`, `restorationRole` `0xad5e…49c9`, `supplyAmount`, `normalWithdrawAmount` `0x75b8…ba02`, `restorationAmount` `0x33b7…f680`, `normalCount` `0xd1a3…62ed`, `restorationCount` `0xe342…00dc`.

I will generate the exact creation data once SAFE and ROLES exist. **Readback:** `owner()` = SAFE, `roles()` = ROLES, `marketId()`, `lineage()`, all seven keys, `active()` = false, `epoch()` = 0, all five counters 0. **Capture:** tx hash, **CONTROLLER** address, full readback.

---

## Step 5 — the owner ceremony: 15 Safe transactions

Generated, not hand-written. `script/solidity/BuildOwnerCeremony.s.sol` runs the **same
`HeldInstall.install()`** the P02 and P03 suites exercise, in simulation, and Forge records
every call it emits; `script/build_owner_ceremony.py` turns that into the action list.
Nothing in this pipeline re-encodes a condition tree or a budget by hand — that drift is
exactly what the 67eed71 review caught once already.

**Validated end to end on the pinned fork**: an EOA-deployed controller, a real Safe and a
real Roles module produced 15 actions, every one `value = 0`, every one sent from the Safe.
Any selector the script cannot name is a hard stop, not a passthrough.

| # | Call | To | Gas |
|---|---|---|---|
| 1 | `enableModule(controller)` | SAFE | 77,058 |
| 2 | `assignRoles(controller, [normalRole], [true])` | ROLES | 115,384 |
| 3 | `assignRoles(controller, [restorationRole], [true])` | ROLES | 82,862 |
| 4 | `scopeTarget(normalRole, MORPHO)` | ROLES | 43,083 |
| 5 | `scopeTarget(normalRole, USDC)` | ROLES | 43,083 |
| 6 | `scopeFunction` — supply, tight tree | ROLES | 460,852 |
| 7 | `scopeFunction` — approve, value-bounded | ROLES | 189,814 |
| 8 | `setAllowance(supplyKey, 50,000e6, …)` | ROLES | 54,310 |
| 9 | `scopeFunction` — normal withdraw | ROLES | 485,027 |
| 10 | `setAllowance(withdrawKey, 50,000e6, …)` | ROLES | 105,697 |
| 11 | `scopeTarget(restorationRole, MORPHO)` | ROLES | 70,818 |
| 12 | `scopeFunction` — restoration withdraw | ROLES | 485,273 |
| 13 | `setAllowance(restorationKey, 10,000e6, …)` | ROLES | 105,697 |
| 14 | `setAllowance(normalCountKey, 10, …)` | ROLES | 105,599 |
| 15 | `setAllowance(restorationCountKey, 5, …)` | ROLES | 105,582 |

**Total ~2,530,139 gas.** Each is an `execTransaction` with `operation=0, safeTxGas=0,
baseGas=0, gasPrice=0, gasToken=0x0, refundReceiver=0x0` and 2-of-3 signatures. They can be
batched through Safe's MultiSend to save signing rounds; the order above must be preserved.

`retireMember` is `address(0)` — a fresh Safe has no prior runner, so no revocation call appears.

**Reversible:** yes throughout — roles revocable, allowances re-settable, module disableable. **Readback:** all five allowances non-refilling with balance = max at 50,000 / 50,000 / 10,000 USDC, 10, 5; the controller is the sole member of both roles. **Capture:** 15 tx hashes, `evidence/M1/owner-ceremony-calldata.json`.

---

## Step 6 — fund the Safe

| | |
|---|---|
| from | any funded address |
| to | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` (USDC) |
| calldata | `transfer(SAFE, 11000000)` |
| amount | **exactly 11.000000 USDC** |
| reversible | yes — owners can withdraw at any time |

**This exact figure matters.** Funding 10.000000 would revert `FloorViolated` at execution, after the gas is spent: `executeSupply` requires `amount ≤ balanceBefore − F` and `F` = 1 USDC. **Readback:** `balanceOf(SAFE)` = `11000000` exactly. **Capture:** tx hash, balance readback.

---

## Step 7 — bootstrap authority evidence

No transaction, no spend. I run the bounded checklist against the **real** Safe at a stated
finalized block. **Any INCOMPLETE section blocks activation (V4 §6)** — the 14/14 fork
rehearsal does not substitute for this. **Capture:** mainnet `bootstrap-rehearsal.json`, block number and hash.

---

## Step 8 — activation (Safe transaction, 2-of-3)

**The calldata is fully determined already** — the only unknown is the destination.

| | |
|---|---|
| from | **SAFE**, via `execTransaction`, 2 signatures |
| to | **CONTROLLER** (step 4 output) |
| value | 0 |
| selector | `0xbe6d7eb6` — `activate(uint64,uint32,address,address,(…14 fields),(…5 fields))` |
| size | 740 bytes |
| expected gas | ~250,000 |
| reversible | **yes** — `fence()` then re-activate at a higher epoch; consumption is preserved |

Decoded, verified by round-trip:

```
newEpoch         1
newPolicyVersion 1
newRunner        0xEc31ACd93c694c21Db63918B442c73C224080A83
newExecutor      0x24192B75e297dC1c7a42DcB8C04227818E78acd0
Policy           (Ls 50000000000, Ln 50000000000, Lr 10000000000,
                  Ms 10000000, Mn 100000000, Mr 1000000,
                  ms 10000000, mn 1000000, F 1000000, H 0,
                  Nn 10, Nr 5, dn 0, dr 0)
ExpectedState    (0, 0, 0, 0, 0)
```

Full calldata is in `evidence/M1/activate-calldata.json`.

**Readback:** `active()` = true, `epoch()` = 1, `policyVersion()` = 1, `runner()` = Runner B, **`executor()` = `0x2419…acd0`**, and every policy field equal to the above. **Capture:** tx hash, `Activated` event, full readback.

**Stop condition:** if `executor()` does not equal the KeeperHub address exactly, every `executeSupply` will revert `NotExecutor` until the controller is re-activated. Verify before moving on.

---

## Gas summary for the owner EOA

| Step | Gas |
|---|---|
| 1 Safe | ~290,000 |
| 2a Roles | ~180,000 |
| 4 Controller | ~3,400,000 |
| 2b + 5 ceremony | ~2,530,139 |
| 8 activation | ~250,000 |
| **Total** | **~6,650,000** |

Below the 7,587,624 measured fixture ceremony, which is a superset. The **0.002 ETH**
budget covers it at 3× headroom on observed Base fees, with room for the L1 data fee that
no gas figure includes.

---

## On `from` — and why no field is outstanding

`from` never appears in a transaction's signed calldata. For a plain EOA transaction it is
**recovered from the signature**, so your wallet supplies it by signing; for a Safe
transaction it is the relayer, and the Safe authorises on owner signatures rather than on
who submits. Every artifact in `evidence/M1/` therefore omits `from` by construction, and
an earlier checkpoint line reading "only the sending EOA is unfilled" was describing that
omission rather than a missing value. There was no unresolved field.

**Fixed and final:** Owner A, `0x9c7bfBb4aBcF2C901a395B81cFcC3De4b214b522`, sends steps 1,
2a and 4, and relays every Safe transaction. It is also the address that needs the ~0.002
ETH gas budget.

Two things follow, and both were verified on the fork:

- **The deployer does not acquire authority.** Safe ownership comes from the `initializer`
  and the controller's owner comes from its `_owner` constructor argument. An EOA-deployed
  controller reported `owner()` = the Safe.
- **Any funded address would work mechanically.** Naming Owner A is an operational choice —
  one funded address, one nonce sequence, one payer to reconcile — not a protocol
  requirement.

## Still outstanding — all external

Every parameter is now final. What remains is money and authorisation, not information.

1. **Gas for Owner A** — ~0.002 ETH on Base. Currently **0**.
2. **0.001 ETH for `0x24192B75e297dC1c7a42DcB8C04227818E78acd0`** — the KeeperHub managed
   signer that pays for the one broadcast. Currently **0**, verified at block 51460346.
3. **11.000000 USDC for the Safe** — the exact figure; 10.000000 would revert
   `FloorViolated()` at execution, after the gas is spent.
4. **The write-capable organisation key** swapped into `$HELD_KEEPERHUB_API_KEY` (step 11),
   and swapped back afterwards.
5. **Your explicit authorisation** to deploy, fund and broadcast.

Funding and KYC are pending separately. The whole sequence is rehearsed end to end against
these exact identities in `evidence/M1/final-fork-rehearsal.json` — 14 of 14 claims
matched, no owner private key used, requested or held.
