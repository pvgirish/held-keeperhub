# Development checkpoint — Held V4

**Git history begins here.** All earlier development happened locally in this worktree
before the repository was pushed. Nothing is backdated, no past phase commits are
fabricated, and no contributor is invented. Earlier states are documented by dated
archives kept outside this tree; they were never git commits and are not presented as
such.

**Nothing below is independently accepted.** Claude authored and ran this work; self-testing
is not acceptance.

**Executor attribution.** The implementation session ran 2026-09-15 19:07 → 2026-09-16 11:31
UTC and every assistant entry in it records model `claude-opus-5`. That comes from the
session transcript's **runtime metadata**, not from the `Co-Authored-By` trailer — a commit
label is not evidence of which model served a session. No second agent contributed.

**Review status, 2026-09-17.** The reviewer inspected the source of `67eed71` and
reproduced its behaviour: see `docs/plan/REVIEW-67eed71.md`. It confirmed a set of repairs
(preserved, not redone) and raised findings N1–N3 and B1–B4, **all of which are now closed
and regressed**. That was an external review of one commit's adapter and collector; it is
not acceptance of any phase, and the corrections it prompted have themselves not been
reviewed by anyone but their author.

## Status at this checkpoint

| Phase | Status |
|---|---|
| **P00** — route evidence + measured native baseline | Local gates reported passing. **Independent acceptance pending.** |
| **P01** — types, identity, journal, result/ack | Local gates reported passing (31 tests). **Independent acceptance pending.** |
| **P02** — typed controller + native Roles enforcement | Local gates reported passing (50 tests in three stages), including property/fuzz coverage and the exact Morpho rounding/share-effect contract. **Independent acceptance pending.** |
| **P03** — native interception → signing → KeeperHub → reconciliation | **PARTIAL.** 163 local tests + 16 composed checks. The 67eed71 review's local findings **N1–N3 and B1–B4 are closed and regressed** (2026-09-17); the composed PUBLIC execution remains blocked on **L10**. Neither stubbed nor simulated. **Independent acceptance pending for everything, including the corrections.** |
| **P04** — authority inventory, owner fencing, change, handover | **PARTIAL PREPARATION** — fork contract tests only; the required runtime service does not exist. |
| **P05** — the private operator console | **PARTIAL PREPARATION** — interface prototype, not connected to real service state. |

This is a checkpoint, not a claim of phase completion.

**Corrected 2026-09-17.** An earlier version of this table said P03's local half was
*finished* and that P04 was the next task. Both were wrong, in two separate ways:

1. **The test count was stale** (89). It was **130** at `67eed71`, and is **163** now that
   the review's regressions are in. All counts in this file were re-run on 2026-09-17.
2. **The local half was not finished.** The external review of this very commit
   (`docs/plan/REVIEW-67eed71.md`) found the native recovery contract still had unenforced
   boundaries and the bootstrap rehearsal never verified the controller-only Roles
   installation. Its probes were rerun here on 2026-09-17 and **every finding reproduced**
   before anything was changed. All seven are now closed with regressions that assert the
   refusal; see `evidence/P03/acceptance.json` under `review_67eed71`.

So **"L10 is the only blocker" was false while those were open.** With them closed, L10 is
again the outstanding external dependency for the hosted half — but closing them is not
acceptance: Claude authored and ran the corrections too.

The composed public-execution evidence that Criterion 2 needs still does not exist: no
contract is deployed, no funds are spent, and the authenticated KeeperHub route has never
been called.

## What is implemented

- `contracts/src/HeldController.sol` — paused-by-default typed controller. Two typed entry
  shapes only (no generic executor), current-epoch EIP-712 runner authorization plus a
  configured executor route, monotonic consumption counters, normal/restoration lanes with
  separate Zodiac roles and separate non-refilling allowance keys, activation-consistency
  guards, ordinary `CALL` sequence through Roles with every nested status and token return
  checked, and exact effect readback.
- `packages/core/held_core/` — unsigned base units, canonical cross-language encoding,
  the three V4 §4 identities, durable SQLite journal/outbox, and a result/ack boundary that
  commits the consumer state update and the acknowledgement in one transaction.
- `fixtures/scripts/` — reproducible Base-mainnet fork fixture: real 2-of-3 Safe, real
  Zodiac Roles module, genuine consumption history, quota isolation, the nine frozen native
  baseline scenarios and the competent-native controls.
- `probes/` — native SDK seam, configuration and recovery probes against the pinned Almanak
  revision `6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938`.

## Tests actually run, and where the evidence is

| Command | Result | Evidence |
|---|---|---|
| `HELD_PRICE_MODE=testing-only make check-phase-00` | PASS (6 gates) | `evidence/P00/`, `docs/baseline/native-measurements.json` |
| `make check-phase-01` | PASS, 31 tests | `evidence/P01/report.md`, `tests/core/run_tests.py` |
| `make check-phase-02` | PASS, 50 tests in three stages | `evidence/P02/report.md` |
| `make check-phase-03-local` | PASS, **163** tests in eight files | `evidence/P03/acceptance.json` |
| `make check-phase-03-composed` | PASS, **16** checks (3 fork tests + 5 Python), local only | `evidence/P03/acceptance.json` |
| `make check-phase-03` | **INCOMPLETE by design** — runs every local check, then exits non-zero because the hosted execution has not been performed | `evidence/P03/acceptance.json` |
| `docs/plan/review-67eed71/test_native_checkpoint.py` | 12 cases — 9 fixed controls pass, **3 findings reproduced** | `docs/plan/review-67eed71/PROVENANCE.md` |
| `docs/plan/review-67eed71/test_bootstrap_collector.py` | 12 cases — 8 correct rejections, **4 FALSE PERMITTED** | `docs/plan/review-67eed71/PROVENANCE.md` |

Every row above was run on 2026-09-17 against the working tree, with
`HELD_PRICE_MODE=testing-only`. The two reviewer probes reproduce the pre-fix behaviour
against the packet's frozen copies of the sources, verified by Git blob hash; their exit
status is not a phase gate, and they use a synthetic journal and scripted `cast` responses
with no SDK, Forge, fork or RPC. The live equivalents are the P03 local and composed gates
and `make check-bootstrap-rehearsal`.

`check-phase-02` stage 0 is 14 **property/fuzz** tests against an independent reference
predicate (256 runs each, pinned seed). Stage 1 is 4 **labelled adversarial mock** tests
(reentrancy, ERC20 returning false, cleanup failing after the economic action). Stage 2 is
32 tests against the **real pinned** Base-mainnet Safe, Zodiac Roles, Morpho Blue and
native USDC on a fork. The evidence classes are kept separate on purpose and must not be
conflated.

`check-phase-03-local` is 17 interception + 9 native-bundle (against the REAL pinned
compiler) + 18 signing + 28 KeeperHub client + 18 submission binding/reconciliation + 20
crash-restart recovery + 15 native decision/recovery + 38 bootstrap-collector decisions =
**163**. The collector suite runs the real collector as a subprocess against a scripted
`cast` shim and includes positive controls; the native decision/recovery suite uses a
synthetic journal and machine and is a control-flow test, not a substitute for the composed
run.
Every KeeperHub test runs against `OfflineTransport`, which stamps `hosted=false`; **none of
them establish L10**, and three exist specifically to prove a local result cannot be filed as
if they did.

Two cross-language checks run in opposite directions. The action hash goes Python →
Solidity via `fixtures/crosslang-vectors.json`, which carries its own provenance and is
only written when the imported SDK tree matches the pin. The envelope digest cannot go
that way — it commits to the domain separator and therefore to the controller's address —
so the fork publishes what it built to `fixtures/generated/signing-vector.json` and the
Python signer reproduces the signature **byte for byte**.

## Still pending

1. **Independent review of the N1–N3 / B1–B4 corrections.** They are closed and regressed,
   but self-testing is not acceptance. `RESUME.md` carries the full catalogue of what each
   finding was; `evidence/P03/acceptance.json` records how each was closed.
2. P06 composed adversarial faults, P07 install/release evidence, P08 assembly. **P04 and P05
   are partial preparation, not done** — P04 has fork contract tests but no runtime service;
   P05 is an unconnected interface prototype.
3. **L10** — authenticated KeeperHub organisation caller/payer. Blocks P03's public
   execution. Nothing about it is stubbed or simulated, and executing
   `evidence/P03/execution-manifest.json` would additionally require authorization to
   deploy a contract and spend funds, which has not been given.
4. Independent review of every phase. The review of `67eed71` covers that one commit's
   native adapter and collector; it is not phase acceptance and grants no repository write,
   public action, credential use or spending.

## Open unknowns recorded rather than guessed

- KeeperHub's catalog exposes an internal string chain id alongside the numeric `chainId`.
  Which one `POST /api/execute/contract-call` expects cannot be established without an org
  credential. Held sends `chainId`; the alternative is recorded in the client.
- The authenticated response schema has not been observed, so the execution id and
  transaction hash fields are read defensively.

## Exact next task

**Corrected 2026-09-17 — this said "P04" and that was wrong.** P04 is not blocked by L10,
which is what made it look next, but it is not next: the review of this commit left local
P03 work open, and P04's own record already reads PARTIAL PREPARATION.

**Updated 2026-09-17: N1–N3 and B1–B4 are done.** The next task is the bounded
L10 / public-action request, once the corrections have been independently reviewed.
`evidence/P03/execution-manifest.json` is the concrete public execution, written before the
fact; executing it needs authorization to deploy a contract and spend funds, which has not
been given.

Do not require full P04 early and do not reopen P00's native comparison.

## Reproducing

External dependencies are not vendored. See `docs/decisions/environment-setup.md` and
`RESUME.md`. Solidity dependencies are pinned git submodules:

```bash
git submodule update --init --recursive
forge build
```

Toolchain: solc 0.8.28 with `via_ir`, optimizer 200 runs; OpenZeppelin v5.1.0; forge-std
v1.16.2; foundry 1.8.1 (1.8.3 observed locally). The Python side needs CPython 3.12 and the pinned Almanak SDK.

See `SECURITY-NOTES.md` regarding the Anvil development keys present in the fixtures.
