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
| P8, P18 | KeeperHub wire contract, documented schema only | SYNTHETIC | `make check-phase-03-local` | `tests/integration/test_p03_keeperhub.py` | 28 pass, **L10 NOT established** |
| P7 | Durable claim before any I/O, incl. real SIGKILL | SYNTHETIC | `make check-phase-03-local` | `tests/integration/test_p03_submit.py` | 18 pass |
| P9 | Crash/restart recovery, no duplicate send | SYNTHETIC | `make check-phase-03-local` | `tests/integration/test_p03_recovery.py` | 20 pass |
| — | Native decision/recovery lifecycle | SYNTHETIC | `make check-phase-03-local` | `tests/integration/test_p03_native_checkpoint.py` | 19 pass |
| P15 | Bootstrap collector fails closed | SYNTHETIC | `make check-phase-03-local` | `tests/integration/test_p03_bootstrap_collector.py` | 43 pass |
| P2, P3, P9, P17 | Composed local run, real controller on fork | REAL LOCAL FORK | `make check-phase-03-composed` | `evidence/P03/acceptance.json` | 16 checks |
| P5, P6 | Controller + Roles against real pinned contracts | REAL LOCAL FORK | `make check-phase-02` | `evidence/P02/report.md` | 50 pass, 3 stages |
| P15 | Live bounded inventory readback | REAL LOCAL FORK | `make check-bootstrap-rehearsal` | `evidence/P03/bootstrap-rehearsal.json` | 9 sections, 14/14 obligations |
| P11, P13, P14, P16 | Handover machine, owner tx, export | SYNTHETIC | `make check-phase-04` | `tests/handover/test_handover_machine.py` | 22 pass |
| P15 | Authority inventory interpretation | SYNTHETIC | `make check-phase-04` | `tests/authority/test_authority_inventory.py` | 7 pass |
| — | Authority/fencing on the fork | REAL LOCAL FORK | `make check-phase-04` | `test/contracts/HeldAuthority.t.sol` | 10 pass |
| **P10, P11, P12** | **The hero workflow, end to end** | **REAL LOCAL FORK** | `make hero-demo` | `evidence/P04/hero-demo-trace.json` | **12 steps** |
| P16 | Replacement export, no key material | REAL LOCAL FORK | `make hero-demo` | `evidence/P04/hero-demo-replacement-export.json` | usable=true |
| P20 | Operator console | SYNTHETIC | `make check-phase-05` | `tests/integration/test_p05_console.py` | prototype |
| **M1, M2, P18, P19** | **KeeperHub public execution** | — | — | — | **NOT YET ESTABLISHED** |

## The hero demo trace

`evidence/P04/hero-demo-trace.json` is the machine-readable record of the 12 steps. The
numbers a judge would check:

| Fact | Value | Where |
|---|---|---|
| Budget actually spent by runner A | `12000000` (12 USDC) | step 2 |
| Handover blocker while unresolved | `UNRESOLVED:0x7e7e…` | step 5 |
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
- No `AUTHENTICATED HOSTED` row exists. No organisation credential is present.
- Every KeeperHub test runs against `OfflineTransport`, which stamps `hosted=false`.
  `SendResult.assert_hosted_evidence()` refuses a non-hosted result, so no local fixture can
  be filed as an L10 pass. Three tests exist solely to prove that.
