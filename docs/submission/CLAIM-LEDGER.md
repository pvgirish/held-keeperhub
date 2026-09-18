# Claim ledger

Every material claim Held makes, with its status. **No evidence, no factual claim.** Nothing
below may appear in a README, a video narration or a submission answer at a stronger status
than it carries here.

Status vocabulary:

| Status | Meaning |
|---|---|
| **VERIFIED** | Demonstrated by evidence of the stated grade, reproducible from this repository |
| **PARTIAL** | Partly demonstrated; the gap is stated |
| **NOT YET ESTABLISHED** | Believed, not shown. May not be asserted as fact anywhere |
| **WITHDRAWN** | Previously claimed, now retracted, kept so the retraction is visible |

Evidence grades are never promoted: `PUBLIC CHAIN` > `AUTHENTICATED HOSTED` >
`REAL LOCAL FORK` > `REAL OFFLINE SDK` > `SYNTHETIC`.

---

## Mandatory competition claims

| # | Claim | Status | Grade | Evidence |
|---|---|---|---|---|
| M1 | A real transaction executed through KeeperHub | **NOT YET ESTABLISHED** | — | No organisation credential exists in this environment. `evidence/P03/public-action-request.json` |
| M2 | The transaction corresponds to the integrated workflow | **NOT YET ESTABLISHED** | — | Depends on M1 |
| M3 | Source is public and accessible | PARTIAL | — | Repository is private; visibility change is not authorized |
| M4 | A working demo video | **NOT YET ESTABLISHED** | — | Runbook drafted, not recorded |

**M1 is a mandatory submission requirement. While it is NOT YET ESTABLISHED the entry is
incomplete under the official rules, regardless of the engineering below.**

## Product claims

| # | Claim | Status | Grade | Evidence |
|---|---|---|---|---|
| P1 | Held intercepts a real Almanak `ActionBundle` and admits exactly one supported action | VERIFIED | REAL OFFLINE SDK | `make check-phase-03-local` — 17 interception + 9 native-bundle tests against the pinned compiler |
| P2 | The operation identity is derived from the deployment's own scope | VERIFIED | REAL LOCAL FORK | `make check-phase-03-composed` — admitted id equals the fork's `actionHash` |
| P3 | The action hash agrees across Python and Solidity | VERIFIED | REAL LOCAL FORK | `fixtures/crosslang-vectors.json`; composed run's `consumed[]` is byte-identical |
| P4 | The runner envelope is EIP-712 and bound to the current epoch | VERIFIED | REAL LOCAL FORK | 18 signing tests; hero demo step 11 reverts `WrongEpoch` |
| P5 | The controller enforces customer limits independently of the adapter | VERIFIED | REAL LOCAL FORK | `make check-phase-02` — 32 fork tests against real Safe/Roles/Morpho |
| P6 | Zodiac Roles is an independent second defence, not a formality | VERIFIED | REAL LOCAL FORK | Tight condition trees; bootstrap rehearsal probes both roles, positive and negative |
| P7 | A dispatched operation is durable before any network I/O | VERIFIED | SYNTHETIC + REAL LOCAL FORK | 18 submission tests incl. a real SIGKILL mid-send; composed run |
| P8 | An ambiguous send is never treated as a failure | VERIFIED | SYNTHETIC | 28 KeeperHub wire-contract tests; all ambiguity maps to UNKNOWN |
| P9 | A confirmed operation is never resent | VERIFIED | REAL LOCAL FORK | Composed run pass 4: `resume()` refuses and resolves instead |
| P10 | Held's verified consumption survives a runner handover | VERIFIED | REAL LOCAL FORK | `make hero-demo` step 10 — 12000000 carried, remaining 49988000000 |
| P11 | A handover is refused while an operation is unresolved | VERIFIED | REAL OPERATION + DURABLE JOURNAL + REAL LOCAL TRANSPORT AMBIGUITY | `make hero-demo` steps 3+5 — the request travels over a real socket to a local server that receives it (idempotency header observed) and closes without responding; refused on a set derived from the journal. The server is local and is **not** KeeperHub; this is not hosted evidence. 39 handover tests |
| P12 | A retired runner cannot reuse its old authorization | VERIFIED | REAL LOCAL FORK | `make hero-demo` step 11 — behavioural, reverts `WrongEpoch` `0x2b9264ec` |
| P13 | Held never signs an owner transaction | VERIFIED | — | `packages/handover/held_handover/owner_tx.py` builds and describes only; no key path exists |
| P14 | An adapter that stops dispatching is not reported as a fence | VERIFIED | SYNTHETIC | `readback.py` four-way classification; handover guard test |
| P15 | The bounded authority inventory fails closed on unreadable evidence | VERIFIED | SYNTHETIC + REAL LOCAL FORK | 43 collector decision tests; `make check-bootstrap-rehearsal` |
| P16 | Runner B receives no key material | VERIFIED | SYNTHETIC | Export refuses key-shaped values; `hero-demo-replacement-export.json` |
| P21 | Reconciliation is derived from the durable journal, not supplied by a caller | VERIFIED | REAL LOCAL FORK | `make hero-demo` step 5; R1 regressions |
| P22 | Authority clearance requires an inventory scoped to THIS installation and no older than the fence | VERIFIED | SYNTHETIC + REAL LOCAL FORK | R2 regressions; `hero-demo` step 7 collects live in handover mode |
| P23 | A refusal survives a restart and its gate cannot be jumped | VERIFIED | SYNTHETIC | R3 regression |
| P24 | One controller reading is pinned to one block; finality is established, not asserted | VERIFIED | SYNTHETIC | R4 regressions |
| P25 | Activation is accepted only when every observable candidate field matches | VERIFIED | SYNTHETIC | R5 regression, 7 mutations |
| P26 | An export missing what B needs reports `usable=false` | VERIFIED | REAL LOCAL FORK | R7 regressions; live export has 3 checkpoints and 1 settled operation |
| P27 | The native configuration identity binds the full market, not just the chain and Safe | VERIFIED | SYNTHETIC | 14 mutations — loan token, collateral, oracle, IRM, LLTV, Morpho, lineage, controller, Safe, chain, SDK revision, price mode, execution profile, strategy config — each changes the digest |
| P28 | Handover-mode inventory still requires a PAUSED controller | VERIFIED | SYNTHETIC | `HELD_INVENTORY_MODE=handover` relaxes epoch-0 and zero-consumption only; an active controller blocks |
| P29 | The console renders the four V4 §8 views from live sources over HTTP | VERIFIED | REAL LOCAL FORK | `make console-live` drives `Console.handle()`: auth, CSRF, four views, live policy read off the controller, dead RPC → UNAVAILABLE with no substitution, out-of-scope stored inventory marked incomplete, redaction |
| P17 | The native Almanak state machine acknowledges Held's result | VERIFIED | REAL OFFLINE SDK | Composed run: the actual pinned consumer reaches COMPLETED |
| P18 | Held executes through KeeperHub | **NOT YET ESTABLISHED** | — | L10. The client is built and wire-tested against documented schema only |
| P19 | KeeperHub's server-side encoder reproduces Held's intended calldata | **NOT YET ESTABLISHED** | — | Needs one authenticated dry run |
| P20 | The operator console shows real service state | PARTIAL | SYNTHETIC | `--state-source live` implemented and refuses to fall back to demo data; HTML rendering of the four views is still prototype |

## Comparison claims

**MEASURED** on the fork against the frozen P00 native baseline: `make p06-comparison`,
recorded in [`evidence/P06/comparison.json`](../../evidence/P06/comparison.json).

The result does not favour Held on operator work, and is reported as it came out.

| # | Claim | Status | Grade | Evidence |
|---|---|---|---|---|
| C1 | Held reduces coordination work versus a competent native handover | **WITHDRAWN — measured false** | REAL LOCAL FORK | From the SAME 30,000-consumed starting state: clean change native 1/2/1 against Held 2/4/2; interrupted change **tie** at 2/4/2. Every ceremony is a real 2-of-3 `execTransaction`; the change is a real MultiSend on both sides |
| C2 | Held enforces an activation-time consistency guard native has no equivalent for | **VERIFIED** | REAL LOCAL FORK | Observed firing: `AllowanceDesynchronised(rolesRemaining, expected)` refused an activation whose raised ceiling the Zodiac allowance would not honour |
| C3 | One store answers whether a specific operation executed | **VERIFIED** | REAL LOCAL FORK | `consumed[operationId]` at a stated block, bound to the native decision by the journal. Native derives the budget correctly in aggregate but does not identify which operation ran |
| C4 | The system refuses to proceed while an outcome is unknown | **VERIFIED** | REAL LOCAL FORK | The comparison run raised a refusal naming the unresolved operation. Native has no per-operation record to refuse with; a competent operator supplies the discipline instead |
| C5 | Held costs more to set up and to trust | **VERIFIED — against Held** | REAL LOCAL FORK | A controller, two role memberships, five budgets and a durable journal, before any of the above is available |

## Withdrawn

| # | Claim | Why |
|---|---|---|
| W1 | Held saves ceremonies or signatures versus native tooling | **WITHDRAWN** at `docs/decisions/advantage-review.md` rev 2. No ceremony or signature saving is claimed anywhere |
| W2 | "All five bootstrap sections COMPLETE" (pre-`67eed71`) | **WITHDRAWN**. The readbacks were real; the completeness verdict drawn from them was not supported |
| W3 | "P03 local half complete" (pre-review) | **WITHDRAWN**. An external review found seven open findings; all are now closed but the phase is still PARTIAL |
| W4 | Held fences by stopping its adapter | **WITHDRAWN**. An adapter stop leaves the controller active; only `fence()` is a fence |
| W5 | "An operation becomes ambiguous" in the Pass-1 hero demo | **WITHDRAWN as stated then.** The id was a constructed constant that was never submitted. The demo now dispatches a real operation through the real Submitter with a transport that raises, so the claim is re-made on real evidence |
| W6 | Pass-1 `usable: true` on the replacement export | **WITHDRAWN.** It reported ready with zero checkpoints, zero settled operations and a placeholder digest. All three now block |
| W7 | The first P06 comparison | **WITHDRAWN.** Held started at 12 USDC consumed while native started at 30,000, only the interrupted branch ran, and `setAllowance`+`activate` were counted as one ceremony on the strength of a MultiSend never executed. Re-measured with asserted parity, both branches, and a real MultiSend |
| W8 | "the transport never returned" (Pass-2 hero demo) | **WITHDRAWN as stated then.** The transport was an in-process double. The request now travels over a real socket to a server that receives and drops it |

## Rule

A sentence may enter the README, the video or a submission answer only if it appears above
with status VERIFIED, and only at the grade recorded there. Anything PARTIAL must carry its
gap in the same breath. Anything NOT YET ESTABLISHED may be described as an intention, never
as a fact.
