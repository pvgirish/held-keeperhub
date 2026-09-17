# Held V4 — resume here

Handoff **2026-09-17**. Claude is sole implementation writer. **Independent review is
pending for everything in this tree — nothing here is accepted.**

> **Read this box before anything else.** Two earlier "Next:" lines in this file and in
> `CHECKPOINT.md` were stale and pointed at already-finished phases. They are corrected
> below. Do not resume from a phase heading; resume from **Next task**, below.

Read in this order: this file's **Status** and **Next task** → `evidence/P03/acceptance.json`
(authoritative P03 record) → `evidence/continuous-run.md` → `docs/decisions/advantage-review.md`
(the V4 §9 decision that gates P01) → `evidence/P00/report.md` (full history) →
`docs/decisions/route-evidence.json` (route layers).

## Who executed this, and on what evidence

**Claude Code is the sole executor.** The implementation session ran **2026-09-15 19:07 →
2026-09-16 11:31 UTC** and every assistant entry in it records model `claude-opus-5`. That
attribution comes from the **session transcript's own runtime metadata**, not from the
`Co-Authored-By` trailer on the commits — a commit label is not evidence of which model
served a session. No other agent contributed: `~/.glm` holds configuration only, with no
session history and no reference to this tree, and the Codex sessions that touch this
worktree all predate the work described here.

## Status at 2026-09-17

**Checkpoint `67eed71` was the state this handover found.** Since then the review of that
commit has been executed; `main` is ahead. Working tree clean, nothing unpushed.

| Phase | Status |
|---|---|
| **P00** | Local gates reported passing. Independent acceptance pending. |
| **P01** | Local gates reported passing (31 tests). Independent acceptance pending. |
| **P02** | Local gates reported passing (50 tests, three stages). Independent acceptance pending. |
| **P03** | **PARTIAL.** The 67eed71 review's local findings are closed and regressed; **L10 outstanding**. Nothing independently accepted. |
| **P04** | **PARTIAL PREPARATION** — fork contract tests only; the runtime inventory/handover service does not exist. |
| **P05** | **PARTIAL PREPARATION** — interface prototype, not connected to real service state. |

P04 and P05 are *preparation*, not completed dependent phases. Do not read their commits as
phase completion.

### Test counts

**172 local** and **16 composed**, all re-run on 2026-09-17 — see the gate block further
down. At `67eed71` it was 130; `CHECKPOINT.md`'s older figure of 89 was already superseded
then. Self-testing is not acceptance, whoever runs it.

## Review history — two distinct reviews, do not conflate

1. **Review of `1b07557`** — found replaceable native bindings, wrong-machine acceptance,
   uncommitted-state verification and false bootstrap verdicts.
2. **Commit `67eed71`** — implemented that review. Those specific fixes are **done**; the
   subsequent review credited them. **Do not redo them.**
3. **Review of `67eed71` itself** — examined the updated code and identified *remaining*
   native-recovery and installation/checklist gaps, catalogued as **N1–N3** and **B1–B4**.

**Item 3 arrived on 2026-09-17 and is now stored in this repository**: the review text is
`docs/plan/REVIEW-67eed71.md`, and its packet — digests, the reviewer's two runnable probes
and the reviewer's own recorded results — is `docs/plan/review-67eed71/`, with provenance in
`docs/plan/review-67eed71/PROVENANCE.md`. It had been sitting outside this tree, which is the
whole reason the handover drifted. **It is not Claude's own work; it is the external
reviewer's.**

The packet carries the two source files it executed, with Git blob hashes. Both match this
repository at `67eed71` exactly and are byte-identical to the working tree, so the findings
are against current code, not a stale snapshot.

**Both probes were rerun in this tree on 2026-09-17. Every finding reproduced; every
confirmed-fixed control still passed.** Details and the case-by-case table are in
`PROVENANCE.md`. Note the reviewer's own limit: these probes use a synthetic journal and
machine and scripted `cast` responses, run no SDK/Forge/fork/RPC, and **their exit status is
not a phase gate**. Closing the findings needs the real entry points and live fork readbacks.

### The review's catalogue — ALL SEVEN CLOSED 2026-09-17, pending independent review

**Every finding below was reproduced against the committed code before anything was
changed, and each is now closed with a regression that asserts the REFUSAL rather than a
changed value.** The fixes the review explicitly confirms — 9 native and 8 collector
controls — were preserved, not redone; they are kept as an explicit `PRESERVED` group in
`tests/integration/test_p03_native_checkpoint.py`.

Commits: `1f912de` (N1–N3), `05197d0` (B1), `1639397` (B2–B4), and a second-pass commit
closing twelve fail-open holes found by reviewing those corrections in a fresh context —
including a `SetAuthorization` decoder that could not read real `cast logs` output at all,
so the B4 discovery path was inert against live data. Per-finding detail is in
`evidence/P03/acceptance.json` under `review_67eed71` and `review_67eed71.second_pass`.

**Closing these is not acceptance.** Claude authored and ran this work too. The catalogue
is kept below in full because it says what was wrong and why, which is what a later
reviewer needs.



**N — finish the native recovery contract**

- **N1.** `NativeStateMachineConsumer.needs_execution()` calls `self.machine.step()` directly,
  with neither `require_authoritative()` nor any lifecycle distinction for an object mutated
  by a failed apply. Reproduced: after a valid apply whose SQL transaction rolls back there is
  no durable snapshot and `_authoritative` is false, yet `needs_execution()` still returns a
  decision. **Do not** simply demand a committed COMPLETED snapshot before every initial call —
  a clean PREPARING/VALIDATING machine must stay usable under its bound pre-dispatch
  lifecycle. Distinguish clean initial work from dirty post-apply state, enforce it
  unavoidably at the entry point the running adapter uses, and after a persistence failure
  discard/restore from durable state rather than letting a caller reuse the mutated machine.
- **N2.** `restore()` checks only that a terminal snapshot has *some* acknowledgement and
  *some* binding. Reproduced: operation O is CONFIRMED and bound to A while a committed
  snapshot holds B plus a COMPLETED ack — `restore()` reports `intent_id=A`, `complete=True`,
  `inconsistent=[]`, no work required. Also reproduced: with a binding but no durable
  operation row, `restore(..., build_machine=...)` builds a machine and returns work-needed —
  lost local history must not become permission for fresh work. Validate operation, bound
  decision identity/type, snapshot identity, actual ack/result identity and any permitted
  terminal/tombstone case coherently. Do not smooth an inconsistent record into a completed
  marker.
- **N3.** In `tests/integration/test_p03_composed.py` a new native machine is still created in
  the later test named "the producing native decision is BOUND…", after request construction
  and reconciliation. A requirement in a docstring does not change execution order. The
  original producer must create or reopen **one stable decision before its work is
  admitted/claimed**, carried through the same operation and durable journal to delivery, with
  a fresh execution context for restart. Preserve the economic bytes and the EIP-712 scope
  checks.

**B — finish the initial-activation rehearsal**

- **B1.** `fixtures/scripts/03d_deploy_paused_controller.sh` constructs the controller then
  sends `enableModule(controller)` straight to the Safe. It assigns **neither Zodiac Role**,
  configures **no** restoration/normal condition trees, sets **none** of the five native
  budgets and does not retire the legacy native role member. The already-tested
  `HeldForkHarness.setUp()` does all of that. Enabling a contract as a Safe module is not
  membership in the intended restricted Roles. The review does **not** demonstrate an
  arbitrary-call bypass — the controller's entry points are typed — but it does establish that
  this is not the controller-only Roles route and that the checklist never verified that
  route. Reuse/export the tested installation into a local pre-activation path, keep the
  controller paused, record declared candidate terms separately from zero/default policy, copy
  no native historical consumption into Held, and leave the P00 native baseline untouched.
- **B2.** The collector reads only the environment `ALLOW_KEY`. It does not read the
  controller's role/allowance keys, discover or verify both Roles' members and conditions,
  inspect all five native remaining budgets, or compare the intended market ID and lineage.
  Five zeroed controller counters are not five native allowance checks. The generated
  seven-section COMPLETE artifact still shows only `held-supply-cap` with 20,000 remaining
  from old native history while Held's counters are zero, and its identities section records
  Safe/Roles owners rather than the selected runner/executor identities. Build a
  clause-to-evidence table over **all** V4 §6 / P03 item 6 obligations at once. Missing
  required configuration is INCOMPLETE, never inferred. A field appearing in a report is not
  proof it is checked. This does not mean building the full P04 service.
- **B3.** The unchanged collector returned `PERMITTED BY THIS CHECKLIST` for four inputs:
  an unreviewed nonzero Safe fallback handler; a readable unsupported Safe version
  (`0.0.0-unsupported`); a successful `cast` returning `not-a-valid-log-response`; and an
  allowance tuple whose balance is `not-a-number`. Validate typed decoded values against
  supported implementations, not merely non-`None` output. Preserve legitimate empty history
  while distinguishing it from malformed, incomplete or truncated log data.
- **B4.** The collector requests all Morpho logs and regex-extracts the last 20 bytes of every
  32-byte word; the declared `SET_AUTH_TOPIC` is unused. The committed artifact accordingly
  contains truncated market IDs and unrelated hashes as "candidates". Switch to the pinned
  event ABI/topic, structured logs, a real Safe authorizer check, creation-to-observation
  coverage and per-candidate mapping readback at the same block. Keep provenance per
  candidate, separate history success from completeness from compatible live grants, and add
  genuine grant/revoke and unrelated-event controls.

**Consequence for the handover, now resolved:** "L10 is the only blocker" was wrong while
N1–N3 and B1–B4 were open. With them closed, **L10 is once again the outstanding external
dependency for P03's hosted half** — but P03 is still not accepted, and nothing here has
been independently reviewed.

## Gate state after the corrections

```
make check-phase-03-local           172 tests   (was 130)
  interception 17 · native-bundle 9 · signing 18 · KeeperHub 28 · submission 18
  · crash/restart recovery 20 · native decision/recovery 19 (new)
  · bootstrap-collector decisions 43 (was 20)
make check-phase-03-composed        16 checks, PASS on the pinned fork
make check-bootstrap-rehearsal      9 sections COMPLETE, 14/14 obligations (fork only)
make check-phase-02                 50 tests, three stages, PASS
make check-phase-04                 10 tests, PASS
make check-phase-03                 INCOMPLETE by design — L10
```

The composed run's action hash is `0x51bb5c6557d3ea42…`, byte-identical to the one recorded
before this work, so driving the lifecycle from the real producer did not change the
economic bytes. Every run needs `HELD_PRICE_MODE=testing-only` and `PY=~/venv312/bin/python`.

## Review 1 and its repairs (2026-09-18)

An independent review of the Pass-1 work found ten defects, **all ten confirmed** — none
were rejected. The two most serious were ways the handover could advance with no evidence
at all: `reconcile()` believed a caller-supplied empty list, and `clear_authority()`
accepted any duck-typed object (which the hero demo *constructed* when the report was
missing). The demo's "ambiguous operation" had also never been submitted, and the
replacement export reported `usable: true` while carrying nothing.

All are repaired in `c5aa22e`, each with a named acceptance regression. Two Pass-1 claims
are WITHDRAWN and kept visible (W5, W6 in the claim ledger). Details per finding are in that
commit message and in `docs/submission/CLAIM-LEDGER.md`.

## Next task

**Independent review of the N1–N3 / B1–B4 work**, then the bounded L10 / public-action
request. `evidence/P03/execution-manifest.json` is the concrete public execution, written
before the fact as a commitment; executing it needs authorization to deploy a contract and
spend funds, which has not been given.

P04's runtime authority service and P05's connected console remain PARTIAL PREPARATION and
are the phase work after that.

Not authorized by that review: full P04 early, reopening P00's native comparison, public
deployment, funding, broadcast, publication, billing or routing-hook changes, blanket
credential use, or a deadline-driven product cut. Request A remains a single separately
owner-authorized read-only credential check, which is **not** L10 satisfaction.

Do not restart P00/P01, redesign the product, or rewrite the locked V4/A1 plan. Do not mark a
finding resolved because a gate passes.

## History — superseded, kept for the record

The previous handoff's "Next: P02" line was written on 2026-09-16 before P02 and the P03
local work landed, and is **superseded**. Its substantive observations remain valid and are
retained here:

P00's six gates were green including required work 6 (real in-process SDK reconfiguration +
recovery). P01's nine declared cases ran on the pinned Base-mainnet fork, plus the
**competent-native controls** for I2 and I6 required by V4 §9 / A1. Each case separates
`experiment_result` from `workflow_outcome`: **9 experiments PASS**, but workflow outcomes are
6 ACHIEVED, 1 ACHIEVED-AFTER-RECOVERY, **2 NOT ACHIEVED** (I2, I6 naive — both closed by the
competent controls) and 1 PARTIAL (I9, L10).

Read `docs/decisions/advantage-review.md` rev 2 before controller work: the I6 advantage claim
is **withdrawn**, and no ceremony or signature saving is claimed anywhere. The surviving
hypothesis is the activation-time consistency guard, specified in
`docs/contracts/controller-interface.md` and still **unproven**.

Representative native comparator: **13 ceremonies / 26 signatures / 17 transactions**
(competent I2 and I6 substituted). The as-run totals 15/30/20 include the naive diagnostic
controls and must not be quoted as the native path's cost.

## Dependencies that live OUTSIDE this tree

This archive is the `held/` worktree only. These were **absent at session start** and were
rebuilt from `docs/decisions/environment-setup.md`. Expect to rebuild them again.

| What | Where it lived | Pin | Rebuild |
|---|---|---|---|
| Almanak SDK | `~/src/sdk` | rev `6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938` — **verified equal** | `git clone https://github.com/almanak-co/sdk.git && git checkout <rev>` |
| Python 3.12 venv | `~/venv312` | CPython 3.12 via `uv`; this run got **3.12.12**, manifest observed 3.12.13 | `uv python install 3.12 && uv venv --python 3.12 ~/venv312 && uv pip install --python ~/venv312/bin/python -e ~/src/sdk` |
| Foundry | `~/.foundry/bin` | **not pinned** — observed 1.8.1 / `982849d3` here; see Environment notes | From the GitHub release — `foundryup` is unusable, `foundry.paradigm.xyz` is blocked. Asset names use `arm64`, **not** `aarch64`. |

Zodiac Roles (`~/src/roles`, for reading enum values) is also absent and was not needed —
the condition operators were read from the live contract's behaviour instead.

The Makefile takes `PY` and `SDK` as overrides, so nothing is hardcoded to those paths. The
gates run under system Python 3.9 too, **except** `gate-tests` and `check-probe`, which need the
venv's `eth_abi` and the SDK.

## Environment notes

- **Foundry — resolved, and an earlier claim withdrawn.** Foundry is **not** a required pin. It
  appears only under `toolchain_observed` (a block whose `_note` says these are observations);
  `pinned_sources` has no foundry entry and `check_manifests.py` never reads one. The 1.8.3 /
  `cae51ad4` record is a truthful observation of a *different* machine and its sha256 is a
  Linux artifact. This run used 1.8.1 / `982849d3` on Darwin arm64. No re-pin is outstanding.
- **Base RPC.** The manifest's "ALL Base RPC hosts 403 at gateway" does not hold here.
  `https://mainnet.base.org` answers and the pinned fork loads in under five seconds. Treat the
  old blanket blocker as history.

## Resume command

```bash
cd <ha>/held
./fixtures/with_fork.sh bash -c '
  for s in 01_deploy_safe_and_roles 02_enable_module_and_fund 03_scope_role 03b_bind_allowance_and_build_history; do
    bash ./fixtures/scripts/$s.sh
  done
  bash ./fixtures/scripts/03c_quota_isolation.sh
  bash ./fixtures/scripts/04_scenarios.sh
  bash ./fixtures/scripts/05_native_competent_controls.sh
  python3 probes/assemble_baseline.py'
```

Steps 01–03b are idempotent and rebuild the whole fixture on a fresh fork in about 90 seconds.
**They must run in one invocation**: each shell call gets its own network namespace with
`--die-with-parent`, so a background anvil cannot survive between calls. `with_fork.sh` refuses
to hand over a fork whose chain id, block or Morpho code does not match `fixtures/fork.env`.

Every case takes an `evm_snapshot` and reverts, so controls cannot leak into measurements and
the canonical 30,000-used / 20,000-remaining start is re-asserted before each case.

## Gate state

```
make gate-tests                                21/21 hold
make check-manifests                           PASS
make check-probe                               PASS with HELD_PRICE_MODE=testing-only; FAIL without (correct)
make check-native-workflow                     PASS  - real in-process SDK recovery, 0 mismatches
make check-baseline                            PASS  - 9 cases + 2 competent-native controls
HELD_PRICE_MODE=testing-only make check-phase-00   PASS
make check-phase-01                            PASS  - 31/31 contract tests
```

## Open blocker

**L10** — authenticated KeeperHub caller/payer preflight. Needs an org API key. Blocks the P03
composed-execution step and the hosted half of I9. Does **not** block P01, P02 or any other
local work.

## What is in here and what it is worth

Every identity in the fixtures is an **anvil deterministic test account** — public, well-known,
local-fork only, never real custody. There are no credentials, no real private keys, no private
RPC URLs and no dependency caches in this tree. The only RPC referenced is the public
`https://mainnet.base.org`.

Synthetic probe stubs under `probes/checks/` are **checker fixtures**. They are never SDK, fork
or chain evidence.

Morpho supply **shares are not constant** across rebuilds — they depend on market state at
execution time. Never pin a share count to force a pass.
