# Evidence index

One row per important claim, with the command that produces it and the grade it carries.
Claim IDs match [`CLAIM-LEDGER.md`](CLAIM-LEDGER.md).

Revision: `git rev-parse HEAD` at the time of reading. Every row below was produced on
**2026-09-17** against the working tree, with `HELD_PRICE_MODE=testing-only` and
`PY=~/venv312/bin/python`.

| Claim | Evidence | Grade | Command | Path | Status |
|---|---|---|---|---|---|
| P1, P17 | Real pinned Almanak compiler and state machine | REAL OFFLINE SDK | `make check-phase-03-local` | `tests/integration/test_p03_native_bundle.py` | 9 pass |
| P1 | Strict `ActionBundle` interception | REAL OFFLINE SDK | `make check-phase-03-local` | `tests/integration/test_p03_interception.py` | 17 pass |
| P4 | EIP-712 runner authorization | SYNTHETIC + REAL LOCAL FORK | `make check-phase-03-local` | `tests/integration/test_p03_signing.py` | 18 pass |
| P8, P18 | KeeperHub wire contract, documented schema only | SYNTHETIC | `make check-phase-03-local` | `tests/integration/test_p03_keeperhub.py` | 46 pass, **L10 NOT established** |
| P7 | Durable claim before any I/O, incl. real SIGKILL | SYNTHETIC | `make check-phase-03-local` | `tests/integration/test_p03_submit.py` | 18 pass |
| P9 | Crash/restart recovery, no duplicate send | SYNTHETIC | `make check-phase-03-local` | `tests/integration/test_p03_recovery.py` | 20 pass |
| — | Native decision/recovery lifecycle | SYNTHETIC | `make check-phase-03-local` | `tests/integration/test_p03_native_checkpoint.py` | 19 pass |
| P15, P28 | Bootstrap collector fails closed | SYNTHETIC | `make check-phase-03-local` | `tests/integration/test_p03_bootstrap_collector.py` | 45 pass |
| P2, P3, P9, P17 | Composed local run, real controller on fork | REAL LOCAL FORK | `make check-phase-03-composed` | `evidence/P03/acceptance.json` | 16 checks |
| P5, P6 | Controller + Roles against real pinned contracts | REAL LOCAL FORK | `make check-phase-02` | `evidence/P02/report.md` | 50 pass, 3 stages |
| P15 | Live bounded inventory readback, **initial** mode | REAL LOCAL FORK | `make check-bootstrap-rehearsal` | `evidence/P03/bootstrap-rehearsal.json` | 9 sections, 14/14 obligations |
| P15, P28 | Live bounded inventory readback, **handover** mode | REAL LOCAL FORK | `make hero-demo` | `evidence/P03/bootstrap-handover.json` | mid-life controller, paused, budget spent |
| P11, P13, P14, P16, P21–P27 | Handover machine, owner tx, reconciliation, export, config identity | SYNTHETIC | `make check-phase-04` | `tests/handover/test_handover_machine.py` | 39 pass |
| P15 | Authority inventory interpretation | SYNTHETIC | `make check-phase-04` | `tests/authority/test_authority_inventory.py` | 7 pass |
| — | Authority/fencing on the fork | REAL LOCAL FORK | `make check-phase-04` | `test/contracts/HeldAuthority.t.sol` | 10 pass |
| **P10, P11, P12** | **The hero workflow, end to end** | **REAL LOCAL FORK** | `make hero-demo` | `evidence/P04/hero-demo-trace.json` | **12 steps** |
| P16 | Replacement export, no key material | REAL LOCAL FORK | `make hero-demo` | `evidence/P04/hero-demo-replacement-export.json` | usable=true |
| P20 | Operator console + live views | SYNTHETIC | `make check-phase-05` | `tests/integration/test_p05_console.py`, `test_p05_live_views.py` | 30 + 14 pass |
| **P29** | **The ACTUAL HTTP console in live mode** | **REAL LOCAL FORK** | `make console-live` | `script/console_live_check.py` | auth, CSRF, 4 views, live policy, dead RPC, stale scope, redaction |
| **C1–C5** | **Measured native-vs-Held comparison** | **REAL LOCAL FORK** | `make p06-comparison` | `evidence/P06/comparison.json` | parity asserted, both branches, real MultiSend |
| **P30** | **The authenticated KeeperHub organisation route accepts Held's credential** | **AUTHENTICATED HOSTED** | `make check-l10-route-proof` | `evidence/P03/l10-route-proof.json` | 200, `hosted=true`, scope `mcp:read` |
| — | M1 ceremony gas, by running the real ceremony | REAL LOCAL FORK | `make m1-cost` | `evidence/P03/mainnet-gas-measurement.json` | 7,587,624 gas over 33 receipts |
| — | M1 `executeSupply` gas, on the composed run's own bytes | REAL LOCAL FORK | `make m1-cost` | `evidence/P03/mainnet-gas-measurement.json` → `gas_execute_supply_detail` | **474,975** — *fork-measured, NOT a public receipt* |
| — | M1 cost ceiling, priced on live Base fees + Chainlink | LIVE READ-ONLY CHAIN READ | `make m1-cost` | `evidence/P03/m1-cost-ceiling.json` | ≈$2.60 at 3× headroom; **excludes Base L1 data fee** |
| — | M1 step 3 / step 7 parameters, prepared on paper | NOT EXECUTED — PREPARATION | — | `docs/submission/M1-PARAMETER-SHEET.md` | 7 unresolved; `newExecutor` blocked on B2 |
| — | M1 owner decisions, approved 2026-09-18 | NOT EXECUTED — PREPARATION | — | `docs/submission/M1-OWNER-DECISION-SHEET.md` | all values approved; runner B generated |
| — | M1 irreversible-action preflight | NOT EXECUTED — PREPARATION | — | `docs/submission/M1-IRREVERSIBLE-PREFLIGHT.md` | 14 actions; **one irreversible** |
| — | M1 pre-broadcast gate, fail-closed | SYNTHETIC (26 refusal tests) | `make check-phase-03-local` | `tests/integration/test_m1_prebroadcast_gate.py` | 26 pass; gate structurally cannot broadcast |
| — | M1 pre-broadcast gate, run against current state | NOT EXECUTED — PREPARATION | `make m1-prebroadcast-gate` | `evidence/M1/prebroadcast-gate.json` | **DO NOT BROADCAST** — 2 pass, 10 blocked |
| — | M1 mainnet evidence gate, fail-closed | SYNTHETIC (15 refusal tests) | `make check-phase-03-local` | `tests/integration/test_mainnet_evidence_gate.py` | 15 pass; fork evidence cannot satisfy a mainnet claim |
| — | M1 mainnet evidence gate, run against current state | LIVE READ-ONLY CHAIN READ | `make mainnet-evidence-gate` | `evidence/M1/mainnet-evidence-gate.json` | 11 labelled records, **0 confirmed on public Base** |
| — | Fill-on-execution templates for every public transaction | NOT EXECUTED — PREPARATION | `make emit-evidence-templates` | `evidence/M1/templates/` | 10 shells, all `PREPARED`, all sentinel-bearing |
| **—** | **The FULL M1 ceremony, rehearsed with the FINAL identities** | **REAL LOCAL FORK** | `make final-rehearsal` | `evidence/M1/final-fork-rehearsal.json` | **14 steps, 14/14 claims matched, 0 problems** |
| — | Production broadcast-scope gate | SYNTHETIC (24 refusal tests) | `make check-phase-03-local` | `tests/integration/test_p03_broadcast_capability.py` | 24 pass; a read-only key refuses before any journal write |
| — | Stale-version and contradiction audit | PREPARED | `make stale-audit` | `evidence/M1/stale-audit.json` | 0 findings |
| **M1, M2, P18, P19** | **KeeperHub public execution** | — | — | — | **NOT YET ESTABLISHED** |

P30 is the only row in this index at a grade above `REAL LOCAL FORK`, and it is worth
being precise about how little it carries. It is a claim about a **credential**, not about
an **execution**: the route accepts Held's key and tells us the key is scoped `mcp:read`.
Read-only keys cannot broadcast, so P30 does not move M1, M2, P18 or P19 one step, and the
`NOT YET ESTABLISHED` row is unchanged for that reason.

**Re-checked 2026-09-18.** The organisation lists two keys and one of them carries
`mcp:write`/`mcp:admin` — but it is **not** the key `$HELD_KEEPERHUB_API_KEY` resolves to,
which remains `mcp:read`. B1 is therefore still not cleared, deliberately.

**The blocker, stated correctly.** M1 is **not** blocked on obtaining a credential; that
question is settled in both directions — a read key is configured and validated, and a
write key exists unconfigured. M1 is open because **the public mainnet proof has not been
executed**: nothing is deployed, nothing is funded (funding/KYC is pending separately), and
nothing has been broadcast. See `CLAIM-LEDGER.md` § "Why M1 is open, stated precisely".

## The final fork rehearsal — what it settles, and what it cannot

`make final-rehearsal` runs the WHOLE M1 sequence on a fresh pinned Base fork using the
addresses that will actually appear on chain: the three real owners at threshold 2, runner
B, KeeperHub's managed signer, `saltNonce` 20260918. It is the first run in this project
where every owner act goes through a real 2-of-3 `execTransaction` rather than impersonating
the Safe — Safe's pre-validated signature form after a genuine `approveHash` from each
owner, which needs **no owner private key**. This session holds none and asked for none.

| Measured | Value |
|---|---|
| Safe deploy | 283,452 gas |
| Roles deploy | 190,822 gas |
| `enableModule(ROLES)`, 2-of-3 | 101,048 gas |
| The 15-action ceremony, 2-of-3 throughout | 2,410,896 gas execution + 1,583,472 approvals = **3,994,368** |
| `activate`, 2-of-3 | 308,029 gas |
| `executeSupply`, from the executor | **485,779 gas** |
| Bounded inventory | COMPLETE, 9 sections, block 51353263 |
| Safe balance after | 1.000000 USDC — the floor, untouched |
| Morpho position | 8,987,118,700,912 supply shares, `onBehalf` = Safe |
| Second attempt | refused, **`FloorViolated()`** |
| Replayed authorization | refused, **`OperationConsumed(bytes32)`**, counters unmoved |

**The 485,779 figure is the better one.** The 474,975 row above was measured on the
composed run's bytes through a `gasleft()` delta; this one is a real receipt for the whole
call through the real Safe and Roles path with the final identities. Both are fork
measurements and neither is a public receipt.

It settles nothing about Base. No address exists on chain, the USDC was written into fork
storage rather than transferred, and the executor path is KeeperHub-*equivalent* — the same
address sent the call, but no KeeperHub API was involved and no idempotency key was issued.
It is not evidence for M1, M2, P18 or P19, and `make mainnet-evidence-gate` refuses it as
such by design.

## The M1 cost rows carry a caveat that must travel with the number

The four M1 rows are **preparation, not execution**. Nothing in them is deployed, funded,
broadcast or submitted, and none of them is evidence for any claim in the ledger — they
exist so that a spending decision is made against measured numbers instead of guesses.

Specifically, on the **474,975** figure:

- It is **fork-measured, not a public receipt.** 447,799 execution gas from a `gasleft()`
  delta on the pinned Base-mainnet fork, plus 27,176 *computed* intrinsic gas over the real
  644-byte calldata. A receipt needs a real transaction, and there is none.
- It measures the **composed run's own bytes** — `fixtures/generated/composed-call.json`,
  built from the real pinned Almanak compiler output — not a reconstruction.
- It **errs high**: EIP-3529 refunds are applied at the end of a real transaction and can
  only make a receipt lower.
- **Base's L1 data fee is not included**, in this figure or in the ceremony figure, and so
  is not in the ≈$2.60 ceiling. Recorded as a known gap in
  `evidence/P03/m1-cost-ceiling.json`, not silently omitted.
- It replaced a **1,200,000 upper bound that was never measured**. The real cost is 40% of
  that bound.

## The hero demo trace

`evidence/P04/hero-demo-trace.json` is the machine-readable record of the 12 steps. The
numbers a judge would check:

| Fact | Value | Where |
|---|---|---|
| Budget actually spent by runner A | `12000000` (12 USDC) | step 2 |
| The interrupted operation | a REAL dispatched operation over a real socket; the server received it (idempotency header observed) and dropped the connection. Journal `UNKNOWN`, durable attempt `hero-interrupted-attempt-1` | step 3 |
| Handover blocker while unresolved | `UNRESOLVED:<real operation id>`, derived from the journal | step 5 |
| Reconciliation source | `consumed[operationId]` on chain | step 6 |
| Consumption carried across the handover | `[12000000, 0, 0, 1, 0]` | step 8 |
| `usedSupply` after handover | `12000000` — unchanged | step 10 |
| Remaining supply capacity | `49988000000` | step 10 |
| Runner A's stale attempt | rejected, `WrongEpoch(uint64,uint64)` `0x2b9264ec` | step 11 |

## Independent review artifacts

| Review | Target | Outcome | Path |
|---|---|---|---|
| `abc0fdd` | Earlier tree | Findings repaired | `docs/plan/REVIEW-abc0fdd.md` |
| `67eed71` | Native adapter + collector | 7 findings (N1–N3, B1–B4), all closed | `docs/plan/REVIEW-67eed71.md` |
| Second pass | The corrections themselves | 12 fail-open holes, all closed | `evidence/P03/acceptance.json` → `review_67eed71.second_pass` |

The second pass is worth noting for the reliability story: reviewing the corrections found
that the `SetAuthorization` decoder could not read real `cast logs` output at all, because it
indexed 32-byte words positionally and the block hash comes first. It passed only because
the test fixture emitted a simplified shape and the live range contains no such events.

## What is deliberately absent

- No `PUBLIC CHAIN` row exists. Nothing is deployed, funded or broadcast publicly.
- **Corrected 2026-09-18.** This used to read "No `AUTHENTICATED HOSTED` row exists. No
  organisation credential is present." Both clauses are now false: a credential is present
  and P30 is an `AUTHENTICATED HOSTED` row. What remains absent is any authenticated row
  about an **execution** — P30 is about a credential, and the credential is read-only.
- Every KeeperHub test runs against `OfflineTransport`, which stamps `hosted=false`.
  `SendResult.assert_hosted_evidence()` and `CredentialCheck.assert_hosted_evidence()` both
  refuse a non-hosted result, so no local fixture can be filed as an L10 pass. Four tests
  exist solely to prove that. The single live call, `make check-l10-route-proof`, is not part
  of any test gate and has no code path that can submit a contract call.
