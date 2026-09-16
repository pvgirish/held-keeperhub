# P00 — report (PARTIAL. The phase is NOT accepted.)

Executor: Claude, sole executor by Girish's instruction of 2026-09-15, which overrides this pack's GLM dispatch arrangement. Astra reviews.

Because there was no GLM dispatch, `routing.jsonl` and `exact-session.json` do not exist and are not applicable. They have not been faked.

## What is done

**G1 — route evidence by layer.** `docs/decisions/route-evidence.json`. Ten layers, each with its own status and boundary.

**G4 — phase priority.** `docs/decisions/phase-priority.md`.

**G5 — source and toolchain manifest.** `project-manifest.json`.

**Anchor verification (prompt item 2, partial).** Reproduced independently from a fresh clone at the pinned SHA: `strategy_runner.py` is 13,533 lines; line 9228 is the `cast(ExecutionOrchestrator, ...)` single-chain path, and the `failed_submission_requires_reconciliation` / `submitted_transaction_hashes` import block follows immediately. The citation is sound.

## The decisive finding

Base Sepolia is **REJECTED for the supported profile**, and for a reason nobody had yet identified.

The SDK does not select a chain by chain ID. It crosses a chain **name** (`"base"`) with a `Network` enum (`MAINNET | TESTNET | SEPOLIA | ANVIL`). `TESTNET` routes to `SEPOLIA`; `rpc_provider.py:448` builds `{chain_key}-sepolia.g.alchemy.com`. So `base` + `sepolia` **does** resolve at the RPC layer, and the absence of the literal `84532` proves nothing on its own.

The block is one layer down. `MORPHO_BLUE`, `MORPHO_BLUE_TOKENS` and `MORPHO_MARKETS` in `almanak/connectors/morpho_blue/addresses.py` are keyed by **chain name only**, with no `Network` awareness anywhere in the file. So `base` + `sepolia` would speak to a Base Sepolia RPC while returning **Base mainnet** singleton, token and market parameters. Those markets do not exist there.

That is a demonstrated incompatibility — REJECTED, not BLOCKED-UNKNOWN.

**Second finding, and it is a warning about our own evidence.** The SDK's address registry states in its own comments that the vanity singleton `0xBBBB…FFCb` has **zero bytes of code on several chains**, and uses per-chain non-vanity singletons instead (lines 39, 58, 69, 89; registry corrected 2026-04-17). Morpho's registry listing that address for Base Sepolia is therefore **not** evidence that code is deployed there. An `eth_getCode` readback is required before anyone relies on L1.

This also supersedes the earlier "the Morpho plugin is mainnet-only" reasoning, which was wrong. The plugin never bound Held. The real constraint is the per-chain-name address registry.

## What this settles

- **Local verification vehicle:** `chain=base` + `Network.ANVIL`, forking Base **mainnet**. Correct addresses and local control at once. The SDK supports this natively.
- **Public criterion-2 evidence:** Base **mainnet**, small value. Requires explicit authorisation from Girish. **Not taken, not prepared for broadcast, in P00.**

## What is NOT done — P00 remains open

**G2 — native compile probe (prompt item 2).** BLOCKED on environment. The SDK is cloned and readable, but no probe has been run, so there is no genuine intent → ActionBundle → decoded core call → Safe account output. This is a hard P00 artifact and it is missing.

**G3 — measured native baseline (prompt items 5, 6, 7).** BLOCKED. **Foundry/anvil is not installed in either available environment** (device VM or cloud container), and the fork baseline needs a Safe with a Roles module and a funded position. Nothing has been measured. `docs/baseline/native-runbook.md`, `comparison-protocol.md` and `native-measurements.json` do not exist yet. No baseline numbers are claimed.

**Makefile / `make check-phase-00` (prompt item 8).** Not written. It would have nothing real to exercise until G2 and G3 exist, and a target that prints success unconditionally is forbidden by the common contract.

**Fixture Safe and bootstrap checklist (prompt item 4).** Not started.

**L10 — authenticated caller/payer preflight.** Not attempted; needs a KeeperHub org API key.

## The decision needed before P00 can continue

Installing Foundry is a toolchain change in one of the two environments. Per the common contract this is preparation rather than a public action, but it is worth a word before proceeding because the device VM's egress may or may not permit the installer.

Next permitted phase: **none.** P01 stays blocked until G2 and G3 close.

---

# P00 continuation — 2026-09-15, under standing execution authority

## Environment built

- Device VM had Python 3.10; the pinned SDK requires >= 3.12. Installed `uv`, fetched CPython 3.12.13, created `~/venv312`, installed the pinned SDK editable from `~/src/sdk` at `6e83e00edcae`. Works.

## G2 — native seam probe: PARTIAL, and it is real

`probes/p00_native_seam_probe.py` runs against the **real** pinned SDK. Nothing mocked. Output at `evidence/P00/native-seam-probe.json`. It establishes:

- The real Base Morpho registry resolves — singleton, USDC, and a real market set.
- A real `SupplyIntent(protocol="morpho_blue", chain="base", token="USDC", amount=100, market_id="0x13c42741a359ac4a8aa8287d2be109dcf28344484f91185f9a79bd5a805a55ae")` constructs and validates.
- The real validator **rejects** a Morpho supply intent with no `market_id`.
- `MorphoBlueCompiler.chains` includes `base`; `protocols` are `{morpho, morpho_blue}`.
- Flash-loan support is narrower: `{ethereum, base}`.

It stops, honestly, at the RPC boundary: `compile_supply` needs a `BaseCompilerContext` carrying a live web3 adapter. So the calldata-producing half of the seam is **not** exercised. That is recorded as BLOCKED, not glossed.

## SDK defect found

`tests/support` does not exist at the pinned revision, but `tests/conftest.py:39` imports it. **The SDK's own test suite cannot be collected from a clean clone at this revision** — 72 collection errors. Worth reporting upstream; it affects anyone reproducing against this rev.

## G6 — `make check-phase-00` written, and it is honestly red

Three real gates in `probes/checks/`, called from the Makefile. No unconditional success token.

```
check-manifests: PASS
check-probe:     PARTIAL -> exit 1 (offline seam verified; calldata half blocked on RPC)
check-baseline:  FAIL    -> exit 1 (native-measurements.json does not exist)
check-phase-00:  FAIL (P00 incomplete)
```

The gates earned their keep immediately: `check-probe` caught a real bug in my own probe, which was reading git HEAD from the wrong directory and silently reporting the wrong revision. Fixed, then re-run.

## Items 5 and 7 — protocol frozen

`docs/baseline/comparison-protocol.md` freezes the fixture, both paths' equal footing, the six measures kept separate, and **nine predeclared interruption points** — before any measurement exists. `docs/baseline/native-runbook.md` specifies the run.

## G3 — the hard blocker, and it is a policy denial

**Every Base RPC host is refused at the egress gateway, in both environments.** Verified, with the gateway's own log:

```
connect_rejected: gateway answered 403 to CONNECT (policy denial or upstream failure)
  mainnet.base.org:443
  base.llamarpc.com:443
  base-rpc.publicnode.com:443
  foundry.paradigm.xyz:443
```

Also refused from the device VM: `base-mainnet.g.alchemy.com`, `base-mainnet.infura.io`, `base.drpc.org`, `rpc.ankr.com`, `base.gateway.tenderly.co`.

This is a real denial, not a flaky installer, so per the standing instruction I stopped probing rather than hunting for a way around it.

**Consequence.** A Base mainnet fork cannot run. Without it there is no native baseline (G3), and `compile_supply` cannot produce calldata (G2's second half). Both gates stay red.

**Minimum permission needed:** outbound HTTPS to **one** Base mainnet RPC host. Any one of:
- `base-mainnet.g.alchemy.com` — preferred; the SDK builds Alchemy URLs natively and this also needs an Alchemy API key
- `mainnet.base.org` — public, no key, rate-limited
- `base-rpc.publicnode.com` — public, no key

Plus, for tooling: `foundry.paradigm.xyz` for the installer, **or** nothing extra — Foundry can come from its GitHub release, which is already reachable.

## Status

Gates: G1 PASS, G4 PASS, G5 PASS, G6 written and honestly red, G2 PARTIAL, G3 BLOCKED, G7 not started.

**P00 remains open. P01 stays blocked.** Nothing further is achievable on G2 or G3 without that RPC host.

---

# P00 continuation 2 — the three corrections applied

## 1. Foundry installed

`foundry.paradigm.xyz` is refused by the gateway, so `foundryup` is unusable. Installed from the GitHub release instead, which is reachable.

forge / anvil / cast **1.8.3**, commit `cae51ad458f6abb64852b7709eb784352429825d`. Archive sha256 verified against the published `.sha256`: `93fc23be…28e6d`. Asset names use `arm64`, not `aarch64` — the first attempt 404'd and returned a 9-byte "Not Found" body.

Anvil smoke tested standalone: chain id `31337`, block `0`. It works; it simply has nothing to fork.

Full reproducible steps in `docs/decisions/environment-setup.md`.

## 2. `check_probe.py` hardened — PASS now requires real calldata

The old version rejected `BLOCKED` and would have accepted any other status without ever looking at compiled output. That was too weak and the correction is right.

It now requires a `compile.supply.calldata` step and checks, per call:

- `to` matches `0x[0-9a-f]{40}`
- `data` matches `0x[0-9a-f]{8,}` — a real selector plus arguments
- the selector is not all zeroes
- **at least one call targets the Base Morpho singleton** read from the registry in the same run
- the calls were actually decoded

It also now requires `market_id` to be a real 32-byte hex id, not merely present. Absent a compile step, it reports PARTIAL and exits 1 — it cannot drift to green.

## 3. `check_baseline.py` hardened — and negative-tested

The old version counted nine entries and a non-empty path field. Both were gameable. It now requires:

- nine **distinct** interruption ids, not nine rows
- every interruption to carry `id`, `outcome`, `recovery_effort` and `evidence_path`
- **every evidence path to exist on disk**, and every raw evidence file to be non-empty
- ceremonies, signatures and transactions to be three separate integers
- `protocol_frozen_before_run: true`
- `environment` and `pinned_revisions` present

**Negative test run.** A plausible fake — correct keys, correct types, nine rows, `protocol_frozen_before_run: true` — was fed to the gate. It was rejected on two counts: only one distinct interruption id, and evidence paths pointing at files that do not exist. Exit 1.

The fake is quarantined at `evidence/P00/negative-tests/` with a README, deliberately not in `docs/baseline/`, where it could be mistaken for data. Note: deletion is not permitted in the connected folder, so it was moved rather than removed.

## Current gate state

```
check-manifests: PASS
check-probe:     PARTIAL -> exit 1   (calldata half blocked on RPC)
check-baseline:  FAIL    -> exit 1   (native-measurements.json does not exist)
check-phase-00:  FAIL (P00 incomplete)
```

## Correction accepted: one host is not the end of it

One reachable RPC removes the connectivity blocker. It does **not** guarantee the baseline can run. A rate-limited public endpoint can answer `eth_chainId` and still refuse historical state at a pinned block, which is exactly what a fork needs.

So when an endpoint arrives, before forking: confirm chain id **8453**, pin a block, and verify the endpoint serves `cast code` and `cast storage` **at that block**. Record the block number and hash. Commands are in `environment-setup.md` §4.

## Status

P00 remains open. The only external dependency is outbound HTTPS to one Base mainnet RPC host — and per Anthropic's documentation, a network-settings change does not apply to an existing session, so this needs a **fresh Cowork conversation with `ha` reconnected** afterwards. All artifacts here are on disk and a new session resumes from them.

---

# P00 continuation 3 — independent gate review corrections

An independent review found three problems. All three were real. All three are fixed and verified by positive **and** negative tests run in a temporary workspace.

## 1. The compile gate would have rejected a correct compilation

The worst of the three, and it was mine. `check_probe.py` did:

```python
morpho = str(by["registry.base.singleton"]["detail"]).lower()   # a whole DICT, stringified
...
if not any(morpho in t for t in seen_targets):                  # searched inside a 42-char address
```

`detail` is `{"morpho": "0xBBBB…", "bundler": "0x2305…"}`. Stringified, it can never be a substring of an address. **A real successful compilation would have failed this gate.** A check that can only ever fail is worse than no check — it would have sent a future session hunting for a compiler bug that did not exist.

Fixed: extract `detail["morpho"]`, validate it is an address, compare by normalised equality.

Decoding is now substantive too. A truthy `decoded` field proves nothing, so the gate now requires a decoded `supply` call whose **market id matches the intent**, whose **amount** is present and consistent at 6 decimals, and whose **`onBehalf` is the declared Safe**.

Verified in a temp workspace: a correct compiled call now **PASSES**. Four mutations each fail with a specific message — wrong target address, wrong market, wrong `onBehalf`, and decoded-but-no-supply-function.

## 2. The baseline gate accepted invalid evidence

The review's exact fake — nine `NOT-PREDECLARED-*` ids, a **directory** as every evidence path, empty `environment` and `pinned_revisions` — returned **PASS, exit 0**. And `recovery_effort: 0` was wrongly rejected as missing, when zero is a perfectly good result.

Fixed:

- The nine ids are now **declared in the frozen protocol** and required, each exactly once. Any other id is rejected by name.
- Every evidence path must be a regular file, non-empty, at least 64 bytes. Directories rejected explicitly.
- `environment` must name `fork_rpc_host`, `fork_block_number`, `fork_block_hash`, `chain_id` and `foundry_version`; chain id must be **8453**; the block hash must be 32 bytes.
- `pinned_revisions.almanak_sdk` must match `project-manifest.json`.
- `protocol_sha256` must match the sha256 of the frozen protocol **on disk**. A JSON flag asserting "frozen" is not provenance.
- A `commands_log` file with exit codes is required.
- Presence and value are now separate, so `recovery_effort: 0` is accepted.

Verified: the review's fake now fails with **29 problems**; zero-effort **passes**; a wrong chain id and a stale protocol digest are both caught.

## 3. Isolation and record sync

- Negative tests moved into `probes/checks/run_negative_tests.sh`, which builds a temp workspace and deletes it. The README no longer tells anyone to copy a fake into `docs/baseline/` — that instruction was dangerous and is gone.
- `project-manifest.json` and `acceptance.json` now record Foundry 1.8.3 installed and Python 3.12.13, with the first observations kept explicitly as history.
- `environment-setup.md` now separates **executed** sections from **section 4, which is pending** and has never been run.

## Correction to my own summary

I said "only one external dependency remains". That was wrong. RPC egress is the immediate blocker for the fork, but `route-evidence.json` **L10 — the authenticated KeeperHub caller/payer preflight — is still BLOCKED-UNKNOWN and not attempted.** An accessible Base RPC does not touch that row. Both are now recorded in `acceptance.json` under `remaining_external_dependencies`.

## Gate state

```
check-manifests: PASS
check-probe:     PARTIAL -> exit 1
check-baseline:  FAIL    -> exit 1
check-phase-00:  FAIL (P00 incomplete)
```

---

# P00 continuation 4 — eight more false-passes, and the root cause

An independent review ran 25 isolated checker tests. Seventeen behaved; **eight invalid probe variants still returned PASS**. All eight were real, and the diagnosis was the important part:

> The checker validated a **description** of the calldata without establishing that the description matched the bytes.

That is exactly what I built. `check_probe.py` regex-checked `calls[*].data` for shape, then trusted a **separate** `decoded` object. So `data` could read `0xdeadbeef` while `decoded` claimed a flawless supply, and the gate said PASS.

## The fix: decode the bytes, derive the truth

`check_probe.py` no longer reads any `decoded` field. It now:

1. Finds the call whose `to` equals the Morpho singleton read in the same run.
2. Requires selector `0xa99aad89` — `supply((address,address,address,address,uint256),uint256,uint256,address,bytes)`, computed from the signature, not copied.
3. ABI-decodes the **actual bytes** into MarketParams, assets, shares, onBehalf.
4. **Re-encodes the decoded MarketParams and takes the keccak**, deriving the market id from the bytes themselves, then compares that with the intent's market id. Tampered market params cannot survive this.
5. Requires `assets` to equal the exact raw units — 100 USDC is **100000000**, not 100 and not 1. My old expression `want.rstrip("0").rstrip(".")` turned `"100"` into `"1"`, which is how a 1-unit supply passed. Gone.
6. Requires `shares == 0`, since the supported shape supplies assets.
7. Requires the declared `safe` **unconditionally**. It used to be `elif det.get("safe")`, so omitting the field skipped the check entirely.
8. Rejects any compile status that is not a success status, before reaching the byte checks.
9. Matches the selector exactly, so `supplyCollateral` no longer slips past a `startswith("supply")`.

## The probe never actually compiled

The review caught this too, and it mattered more than the checker bugs: `p00_native_seam_probe.py` imported the compiler class, recorded its surface, and then emitted `BLOCKED` **unconditionally**. Restoring RPC would not have made it compile a single byte.

It now really attempts `MorphoBlueCompiler().compile_supply(ctx, intent)` and records either the real calls or the real exception. Current genuine result:

```
TypeError: Protocols cannot be instantiated
```

`CompilerServices` is a Protocol, not a concrete class. So there is real implementation work here beyond the RPC — a concrete services implementation is needed. That was invisible while the hardcoded BLOCKED was hiding it.

## The gate tests are now a preserved suite

`probes/checks/gate_tests.py` — twelve cases, each isolated in its own temp workspace, run by `make gate-tests` as part of `check-phase-00`. One positive, the eight reported false-passes, and three more I added (wrong market params in bytes, shares instead of assets, no call targeting Morpho).

```
all 12 gate tests held
```

The suite is a **meta-gate**: it checks that the gates reject known-bad input. If a future change weakens a gate, this goes red.

Synthetic probe stubs in that suite are checker fixtures. They are never SDK or fork evidence, and they never touch `docs/baseline/`.

## Also recorded

The SDK emits `SymbolTokenResolutionWarning` for `token="USDC"` — symbol references are deprecated and will be rejected in SDK 3.0.0. The build should use the token contract address or a CAIP-19 id.

## Status

P00 stays red. Real native compilation evidence is the next milestone, and it now needs both a concrete `CompilerServices` and a reachable Base RPC.

---

# P00 continuation 5 — real native compilation achieved

## I mis-reported the last failure, and the distinction matters

I said the compiler "was entered and returned a failure." It was not. `TypeError: Protocols cannot be instantiated` was raised while **I** hand-built a `BaseCompilerContext` — construction, before `compile_supply` was ever reached. Reporting it as a compiler failure replaced one misleading milestone with another, which is exactly the trap flagged.

The probe now records three stages separately: **constructed / compile_entered / returned**, and names the failure stage explicitly.

## Held does not need a services layer

`_ConnectorCompilerServices` already exists in the pinned SDK, bound to `IntentCompiler`. My "a concrete CompilerServices is needed" conclusion was wrong and would have had us rebuilding SDK internals. The probe now uses the public entry point: `IntentCompiler(...).compile(intent)`.

Its first honest failure was the SDK stating its own requirement:

```
ValueError: IntentCompiler requires a price_oracle for production use ...
or set config=IntentCompilerConfig(allow_placeholder_prices=True) for testing only
```

No prices were invented to clear it. The probe takes `HELD_PRICE_MODE`; `testing-only` supplies `{"USDC": 1}` and **labels itself in the output**. Default is `none`, which fails construction — correctly.

`use_as_collateral=False` is set explicitly, since the native helper branches on it.

## The real compiled bundle

`IntentCompiler.compile()` returned **SUCCESS** with two transactions, offline, no RPC:

| # | to | call |
|---|---|---|
| 0 | USDC `0x8335…2913` | `approve(0xBBBB…FFCb, 110000000)` |
| 1 | Morpho `0xBBBB…FFCb` | `supply(marketParams, 100000000, 0, Safe, "")` |

Decoded from the bytes: market params hash to the intent's market id; assets are exactly **100000000** raw units; shares 0; `onBehalf` is the declared Safe.

**Finding worth carrying into the build: the native compiler approves 110 USDC for a 100 USDC supply — 10% headroom.** Held's profile requires zero managed allowance at entry and exit, so the cleanup step must zero this residual approval. The gate reports it as a NOTE rather than a failure, because it is legitimate native behaviour, not a defect.

## Whole-bundle verification

The gate no longer finds one good supply and stops. Every call is accounted for against the declared profile:

- Any call that is neither a bounded USDC approve to Morpho nor the single Morpho supply is rejected as an unexpected transaction.
- Exactly one supply per bundle.
- Re-encoding must reproduce the calldata body exactly, so trailing bytes are caught.
- Callback data rejected.
- `value` must be zero.
- Approvals: right spender, not unlimited, not below the supplied amount.

## Tests

`make gate-tests` — **21 cases, all hold.** Two positives (the synthetic supply, and the real two-call bundle shape) and nineteen negatives, including the new bundle set: unrelated transfer after a valid supply, duplicate supplies, ETH value, unlimited approval, wrong spender, approval below amount, trailing bytes, callback data.

## Gate state

```
gate-tests:      21/21 hold
check-manifests: PASS
check-probe:     PASS with HELD_PRICE_MODE=testing-only   <- G2 compiled half satisfied
check-probe:     FAIL without it (construction refused)   <- correct
check-baseline:  FAIL - no native-measurements.json
check-phase-00:  FAIL (P00 incomplete)
```

## What this does and does not establish

It advances **G2**. It does **not** establish fork execution, the measured native baseline (G3), KeeperHub caller/payer (L10), or P00 acceptance. Compilation happened offline with a testing-only price config; that is not runtime evidence.

Evidence: `evidence/P00/native-seam-probe.json`, `gate-tests.log`, `commands.log`.

---

# P00 continuation 6 — the RPC blocker is gone; the fork runs

## Re-tested rather than assumed

`mainnet.base.org` now returns **405** to a GET, not 000. That is Method Not Allowed on a JSON-RPC endpoint — the CONNECT is getting through. The egress allowlist was changed.

Verified properly, not by a status code alone:

- `eth_chainId` → `0x2105` = **8453**, Base mainnet
- pinned block **51353212**, hash `0xe1933ad8acf0950c3992368ef1d1157b17af4d2e973e686d11b7b1235de68254`
- **archive reads work at that block**: `eth_getCode` and `eth_getStorageAt` both return historical state

Reachable from **both** the device VM and the cloud container.

## L2 resolved as a side effect

The SDK registry warned that the vanity singleton has zero code on several chains. On **Base mainnet** it does not: `eth_getCode` at `0xBBBB…FFCb` returns 31249 chars, and the wstETH/USDC market returns live state (totalSupplyAssets 2216674761849 raw USDC units). That row moves BLOCKED-UNKNOWN → VERIFIED, for Base mainnet only. Base Sepolia stays REJECTED on L6.

## The fork runs, with one real constraint

anvil forks Base at the pinned block and serves real Morpho code and live market state.

**Constraint found the hard way:** on this device each shell call runs in its own network namespace with `--die-with-parent`, so a background anvil **cannot survive between calls**. The fork must start, be used, and be torn down inside a single invocation.

`fixtures/with_fork.sh` makes that reproducible, and it **refuses** to hand over a fork whose chain id, block number, or Morpho code length does not match `fixtures/fork.env`. A wrong fork fails loudly instead of quietly producing wrong measurements.

## Price config is not an RPC problem

Ran the compile probe against the live fork both ways:

| price_mode | construct | compile |
|---|---|---|
| `none` | FAILED | BLOCKED |
| `testing-only` | OK | OK |

So `IntentCompiler`'s `price_oracle` requirement is a **configuration** requirement, not a network one. A testing-only price config is unavoidable for compilation and must always be labelled as such — it never becomes runtime evidence.

## Status

**G3 moves from BLOCKED to UNBLOCKED_NOT_RUN.** The vehicle exists and is self-verifying. The baseline itself has not run — it still needs a fixture Safe plus Zodiac Roles deployed on the fork, a funded starting position, and the nine predeclared interruption scenarios executed and measured.

**L10 is untouched.** The authenticated KeeperHub caller/payer preflight still needs an org API key. The RPC unblock does nothing for it.
