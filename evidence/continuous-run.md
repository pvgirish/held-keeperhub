# Continuous run ledger

Updated 2026-09-16. Checkpoint identity: the live worktree at the hashes recorded in `evidence/P00/baseline/ARCHIVE.sha256`. Claude is sole implementation writer. Independent review is
**pending** throughout — nothing below is independently accepted.

## Per-phase state

| Phase | implementation | evidence kind | independent review |
|---|---|---|---|
| P00 | **complete — six gates green** | real offline SDK compile, **real in-process SDK reconfiguration + recovery**, real Base-mainnet fork execution | pending |
| P01 | **implemented, 31/31 contract tests hold** | pure local contracts + real SDK recovery agreement | pending |
| P02–P08 | not started | — | pending |

## P00 gate ledger

`HELD_PRICE_MODE=testing-only make check-phase-00` → **PASS**

| Gate | State | Evidence |
|---|---|---|
| G1 route evidence | PASS | `docs/decisions/route-evidence.json`, 12 layers |
| G2 native compile | PASS (offline, testing-only prices) | `evidence/P00/native-seam-probe.json` |
| G3 native baseline | **PASS — nine cases run** | `docs/baseline/native-measurements.json`, `evidence/P00/baseline/` |
| G4 phase priority | PASS | `docs/decisions/phase-priority.md` |
| G5 manifests | PASS | `project-manifest.json` |
| G6 gate tests | PASS 21/21 | `probes/checks/gate_tests.py` |
| G7 fixture bootstrap | PASS — starting state reached by real execution | `fixtures/scripts/01…03b` |
| G8 native workflow | **PASS — required work 6** | `evidence/P00/native-workflow-probe.json` |

## Environment of record

Produced on Darwin arm64, a device that is **neither** the `device_vm` nor the
`cloud_container` in the manifest.

- **Foundry — RESOLVED, not a discrepancy.** An earlier claim that this run violated a 1.8.3
  pin is **withdrawn**. Foundry appears in the manifest only under `toolchain_observed`, whose
  own `_note` says these are observations kept as history. `pinned_sources` has no foundry
  entry, and `check_manifests.py` enforces the SDK revision and route layers only — it never
  reads a foundry version. The 1.8.3 / `cae51ad4` record is a truthful observation of a
  different machine, preserved unchanged; its sha256 is a Linux artifact and must not be
  applied to this Darwin arm64 binary. This run used 1.8.1 / `982849d3`, recorded with its
  path and platform. No re-pin decision is outstanding.
- **Base RPC.** The manifest's "ALL Base RPC hosts 403 at gateway" does not hold here.
  `https://mainnet.base.org` answers and the pinned fork block loads in under five seconds.
  History, not a current blocker.
- `~/src/sdk`, `~/venv312` and `~/src/roles` were **absent** at session start and were rebuilt
  from `docs/decisions/environment-setup.md`. SDK rev verified equal to the pin (`6e83e00e`).
  Venv is CPython 3.12.12 where the manifest observed 3.12.13.

## The two C8 checks, both now closed

### A. The over-quota refusal is now isolated

C8 recorded this as **not** isolated: its intended top-up had silently failed (the storage
value was not written as a full 32-byte word), so the Safe held only 20,000 and balance could
equally have blocked a 25,000 transfer.

`fixtures/scripts/03c_quota_isolation.sh` repairs it and reads everything back before
attempting anything:

| precondition | value | binding? |
|---|---|---|
| Safe USDC balance | 100,000 | no |
| ERC20 approval to Morpho | 25,000 | no |
| Roles supply quota | 20,000 | **yes** |

A 25,000 supply then reverts with `ConditionViolation(17, 0x68656c642d737570706c792d636170)` —
the second argument decodes to the ASCII `held-supply-cap`, so the refusal **names the
allowance key**. Quota, Safe balance and Morpho shares are all unchanged afterwards: no
economic movement. The exact-quota 20,000 control succeeds and drives the allowance to 0.

### B. The canonical state is restored by construction, not by hand

Every control and every case runs inside an `evm_snapshot` and is reverted. The exact-quota
control that consumes the remaining quota therefore **cannot** leak into the measured
scenarios. The canonical 30,000-used / 20,000-remaining start is re-asserted before each case
and re-checked at the end of the run. The concern was an unverified state requirement; it is
now structurally satisfied rather than argued.

## G3 — the nine declared cases

All nine ran on the pinned fork, each exactly once, each with its own evidence file.
**9 experiments PASS** (I9 PARTIAL), but that counts harness assertions, not customer
outcomes — two of these experiments pass *because they successfully reproduced an unsafe
state*. Workflow outcomes: 6 ACHIEVED, 1 ACHIEVED-AFTER-RECOVERY, 2 NOT ACHIEVED, 1 PARTIAL.
The operation is identical in every case: raise the ceiling 50,000 → 80,000 and replace
operator A with operator B.

The native path is given full credit — the owner change goes through Safe MultiSendCallOnly
1.4.1 by delegatecall, so the clean change costs **1 ceremony, 2 signatures, 1 transaction**.

| id | outcome | recovery | what it established |
|---|---|---|---|
| I1-clean | PASS | 0 | Ceiling raised with the 30,000 history preserved; A retired, B operating. |
| I2-ambiguous-submission | PASS / workflow **NOT ACHIEVED** | 1 | `setAllowance` writes an *absolute* remaining value, so a supply confirming in the same block as the fence is silently overwritten and 5,000 of consumption is regranted. **This is a defect of the naive single-batch procedure, not of native tooling** — the competent control closes it. |
| I3-stale-used-snapshot | PASS | 1 | Real hazard, but natively detectable: one re-read before signing is enough, because remaining capacity is authoritative on-chain state. |
| I4-policy-changed-midway | PASS | 1 | **Native safety win.** The Safe nonce already binds a preparation to the state it was prepared against; a stale activation fails signature recovery outright. |
| I5-missing-archive-data | PASS | 1 | Missing archive does **not** block the change: a non-refilling allowance carries consumption in current state (ceiling − remaining = 30,000) with no history at all. Only per-operation *attribution* degrades. |
| I6-legacy-grant-migration | PASS / workflow **NOT ACHIEVED** | 1 | Replacing the Roles operator does not touch a Morpho `setAuthorization` grant, so the legacy agent keeps an independent on-chain path. **Retained as an omission control only** — the competent workflow revokes it in the same batch for free. |
| I7-failed-cleanup | PASS | 1 | Cleanup ordering is load-bearing: fencing A before running its cleanup strands a 5,000 approval, because the route meant to zero it was just revoked. Fails loudly; costs an owner ceremony. |
| I8-new-key-activation | PASS | 0 | Retiring role membership is sufficient on-chain. A keeps key and gas but the module returns `NoMembership`. |
| I9-delayed-callback-ack | **PARTIAL** | 0 | On-chain half idempotent: a settled operation re-reads identically, so a late ack cannot double-consume. Hosted callback semantics need an authenticated KeeperHub org route — **L10** — and were neither simulated nor inferred. |

## The comparator was corrected before P01, not in P06

An earlier revision deferred testing the simple native remedies for I2 and I6 to P06. That was
wrong and is withdrawn: V4 §9 requires a *competent* native comparator, and A1 places the
review **before** P01. `05_native_competent_controls.sh` now runs the full competent workflow
for both, on the same fork, from the same canonical state.

| | naive procedure (04) | competent workflow (05) |
|---|---|---|
| **I2** | workflow NOT ACHIEVED — 5,000 regranted, repaired by a second ceremony. 2/4/3. | workflow **ACHIEVED first time** — fence, settle, read actual consumption, derive ceiling, activate. 2/4/2. |
| **I6** | workflow NOT ACHIEVED — grant survived the handover. | workflow **ACHIEVED at zero extra cost** — revocation batched into the same MultiSend. 1/2/1. |

Both are behavioural. The legacy agent provably moved the Safe's Morpho position before
revocation (shares fell) and reverts with `unauthorized` after. I2's in-flight supply genuinely
landed before the fence, and the arithmetic followed what executed: used 35,000 → remaining
45,000, never a forced 50,000.

**Consequence.** The I6 advantage claim is withdrawn outright. The I2 claim survives only as
the activation-time consistency guard V4 §5 already specifies, and carries **no** ceremony or
signature saving — V4 §6 makes Held pay the same two-stage cost. See
`docs/decisions/advantage-review.md` revision 2.

## Test success, workflow success and evidence completeness are now separate

Each case records `experiment_result`, `workflow_outcome`, `evidence_class` and `unmeasured`.
A PASS can mean the harness successfully reproduced an **unsafe** state. Across the nine:
**9 experiments PASS**, but workflow outcomes are 6 ACHIEVED, 1 ACHIEVED-AFTER-RECOVERY,
**2 NOT ACHIEVED** (I2, I6 naive) and 1 PARTIAL.

**Scope of "native" here.** These cases exercise real contract behaviour — Safe 1.4.1, Zodiac
Roles v2.1, MultiSendCallOnly 1.4.1, Morpho Blue, native USDC — driven by anvil/cast. They do
**not** exercise Almanak reconfiguration, native recovery machinery or native result
consumption. Those parts of the frozen protocol remain unmeasured, and the operator-work counts
are contract-level action counts, not a human-factors study. I9's hosted callback half is
unmeasured under L10; on-chain idempotence is **not** business-operation replay protection.

## Required work 2 and 6: the native WORKFLOW, not merely native components

**Revision 2. An earlier claim is withdrawn.** Revision 1 asserted "native reconfiguration"
because two `StrategyConfig` objects produced different digests. That establishes nothing:
`StrategyConfig` declares `extra="allow"` and has **no** supply/ceiling/limit/allowance field
among its 20 fields, so a digest delta can reflect a field no native component ever reads.
Running native *helpers* is also not the same as exercising the native *workflow*.

`probes/p00_native_workflow_probe.py` (rev 2) now keeps three evidence classes apart.

### A. Native configuration cost of the measured task — source-grounded

| change | native Almanak config cost |
|---|---|
| ceiling 50,000 → 80,000 | **0 steps.** The ceiling is Zodiac Roles state on-chain. There is no Almanak field for it. **Native is credited with a no-op** — inventing one to mirror the Roles allowance would manufacture native work the real workflow does not require. |
| operator A → B | **1 env/wallet-mapping change + 1 PROCESS RESTART.** The identity comes from `ALMANAK_PLATFORM_WALLETS` via `safe_signer_service_config_from_env`, and `load_config()` is documented as a *boot* surface — "called once after loading the relevant dotenv source". **There is no live reload API.** |

The real loader was executed across two boots with the mapping changed between them, and
consumed the change — an actual consumer reading effective values, not a schema digest.

### B. Native-only recovery workflow — no Held code participates

**Revision 3 withdraws two further claims of mine.**

**(i) A reload is not a decision.** Revision 2 stopped at "the reconciliation marker
survived a reload", which is only a persistence round trip. The native callable
`almanak.framework.cli.execution_recovery.assess_replay_barrier(progress, statuses)` now
consumes the reopened record and returns the verdict itself:

| input | native verdict | native reason |
|---|---|---|
| reopened ambiguous record | **releasable = False** | *"at least one submitted transaction is confirmed, pending, unknown, or unobserved"* |
| control: gateway-proved NOT_ATTEMPTED | releasable = True | *"gateway proved submission was not attempted"* |

The control matters: a callable that always says no would prove nothing. Held asserts
nothing about either verdict. The restart is also described accurately now — serialisation,
object drop and reload **within one process**, not an OS process restart.

**(ii) `set_receipt` was never L10-blocked.** Revision 2 claimed it needed a gateway client
and an org key. That was wrong. At the pin `set_receipt` is a local assignment and `step()`
evaluates it. Section B3 now drives a real `IntentStateMachine` with a real
`TransactionReceipt`: **`IntentState.VALIDATING_SUPPLY → IntentState.COMPLETED`**, locally,
with no credential. The blocker that did appear was a type error in my own fixture.

**Intent-scope boundary, checked live.** `single_chain_recovery._original_intent()` gates on
`isinstance(intent, SwapIntent | LPOpenIntent)`. A real `SupplyIntent` evaluates **False**,
so Morpho supply is **ineligible for automatic recovery by design** and falls to
`_operator_reconciliation(...)` → `EXECUTION_PENDING`. Recorded as found: native preserves
uncertainty and blocks automatic rebroadcast. That is **not** a defect, is **not** reported
as one, and no automatic finalisation was invented or forced.

The runner's own `ExecutionProgress` restart record carries three mutually exclusive markers:
`failed_at_step_index` (never broadcast, re-execute), `accounting_pending_step_index`
(broadcast confirmed, do **not** re-broadcast), and `reconciliation_required_step_index`
(hashes retained, receipts untrustworthy — terminal, **never** auto re-execute).

For the ambiguous I2-style case the native predicate returns
`requires_reconciliation=True, proves_revert=False`, so the contract sets the terminal
marker. The record was then persisted, **every in-memory object dropped, and reloaded**:

- submitted transaction identity **survived** the restart;
- the reconciliation marker **survived**;
- the reopened record **would not authorise an automatic resend**.

That is native recovery behaviour established without any Held component — the distinction
the previous revision failed to make.

### A note on the configuration claim

The operator swap now asserts the **effective signing EOA** resolved by
`SafeWalletMapping.get_config(safe)` changed A→B (Roles address unchanged), not merely that
an environment string differs. The restart cost is scoped to *the configuration tested
here*; the source establishes construction and caching, not a universal absence of reload
mechanisms in every deployment.

### C. Held adapter compatibility — relabelled

The six predicate→journal mappings (0 mismatches) are a **Held test**, not native baseline
evidence. They show Held adopts the native verdict rather than inventing its own.

### Not established

A full live runner cycle, and `state_machine.set_receipt` / `_single_chain_handle_success`,
need a constructed strategy and gateway client — **L10**. Failed-result objects are
constructed fixtures (deterministic fault injection, labelled); the predicates, record types
and documented contract are native.

## Reporting, reconciled

- **Nine canonical scenario IDs, nine workflow outcomes.** An earlier summary listed ten
  by double-counting I7; withdrawn. Now: 5 ACHIEVED, 1 ACHIEVED-AFTER-RECOVERY,
  2 NOT ACHIEVED, 1 ACHIEVED-within-measured-scope.
- **Evidence completeness is a separate axis**: 8 complete, 1 PARTIAL (I9's hosted half,
  L10). I9's partiality is a completeness gap, not a tenth workflow outcome.
- **Representative native comparator = 13 ceremonies / 26 signatures / 17 transactions**,
  substituting the competent I2 and I6 controls. The as-run totals (15/30/20) include the
  naive traces and must **not** be quoted as the native path's cost. Both naive traces now
  carry an explicit `role: DIAGNOSTIC CONTROL` field.
- The two competent controls stay **distinct** from the nine canonical IDs.

## Fixture bugs found by readback — now four

1. **Receipt parsing read `data` before `topics`** — both factory events index the new proxy in
   `topics[1]`, so the *singleton* address was being recorded as the Safe.
2. **Code-length check rejected a correct deploy** — a Zodiac module proxy is EIP-1167 minimal
   (~93 chars), so `>100` failed a good deployment. Replaced with a behavioural check.
3. **Hand-written bytes32 keys were the wrong length** — 68 and 67 characters instead of 66.
   Now generated with `cast format-bytes32-string`.
4. **`is_member` asserted on the wrong thing, then on a broken pipeline.** Two compounding
   errors in one helper:
   - It called `isModuleEnabled()`. Zodiac's `assignRoles(x,[key],[false])` drops membership but
     leaves the module **enabled**, so a fully retired operator still read as `true`. Same class
     as bug 2: asserting on a proxy for the thing instead of the thing itself.
   - The behavioural replacement used `role_probe_raw | grep -q`. `grep -q` exits on first
     match, the upstream process takes SIGPIPE, and under `set -o pipefail` the pipeline reports
     141 — so the test read false on a match *and* on no match. It could only ever return one
     answer. Caught because the readback disagreed with observed behaviour: the probe said A was
     still a member while A's supply was reverting.

   Membership is now read by simulation, with three distinct observed signals: assigned member →
   success, never assigned → `NotAuthorized(addr)`, `assignRoles false` → `NoMembership`.

Every one of these was caught because results are read back from chain rather than trusting the
send. Note also that Morpho supply **shares are not a constant** across rebuilds
(`26961356932996913` in C8, `26961356740091981` here) — they depend on market state at
execution. Do not pin a share count to force a pass.

## Blockers

- **L10** — authenticated KeeperHub caller/payer preflight. Needs an org API key. Blocks the
  P03 composed execution step and the hosted half of I9. Does **not** block local fixture work.

## Next

**P02** — typed controller, real Roles enforcement, atomic action/approval cleanup.

**P01 is implemented**: `make check-phase-01` → 31/31. Versioned unsigned base-unit types
(bool and float rejected outright), canonical cross-language encoding (amounts as decimal
strings so a uint256 cannot become a double), an operation ID **independent of epoch and
runner** while the EIP-712 envelope binds both, a durable SQLite journal/outbox written
before any network I/O, and a result/ack boundary that commits the consumer state update
and the acknowledgement in **one transaction**. The EIP-712 hashing is cross-checked
against `eth_account`, not trusted. Exactly-once is claimed only *at the consumer*, never
from a local delivered flag.

Its substantive prerequisites were met: a real measured P00 baseline against a
**competent** comparator, and a resolved before-P01 product decision.

That decision is **provisional continuation on a materially narrowed hypothesis**
(`docs/decisions/advantage-review.md` rev 2): the I6 claim is withdrawn outright, and the I2
claim survives only as the activation-time consistency guard V4 §5 already specifies, with no
ceremony or signature saving claimed. V4 itself is not narrowed — journal, result contract,
scoped authority workflow and console all remain in scope.

## Resume

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

HELD_PRICE_MODE=testing-only make check-phase-00     # expect PASS
```

Steps 01–03b are idempotent and rebuild the whole fixture on a fresh fork in about 90 seconds.
They must run in **one** invocation: each shell call gets its own network namespace with
`--die-with-parent`, so a background anvil cannot survive between calls. `with_fork.sh` refuses
to hand over a fork whose chain id, block or Morpho code does not match `fixtures/fork.env`.

## 2026-09-16 — abc0fdd review reconciled; P03 C1-C4 repaired; composed local run connected

**Routing note.** A stale TalentGum `UserPromptSubmit` hook claimed this session; the user
confirmed it is Held/KeeperHub. Cause identified and reported, not worked around: a stale
session-state file plus an `OTHER_PROJECT_MARKERS` list that does not know "held" or
"keeperhub", so follow-up persistence kept re-asserting. Nothing was disabled.

**Authoritative plan restored.** `docs/plan/` now holds V4+A1, the phase map, the
continuous-execution directive and all P00-P08 prompts, verified 13/13 against the
packet's SHA256SUMS. `make check-plan-digests` re-verifies on every P00 run. This closes
the hole that produced the P05 derivation mistake.

**P03 C1-C4 repaired**, each with regressions:
- C1 documented wire contract (Idempotency-Key header, /status poll, 409 code split,
  202, strict-boolean simulate). Three further defects found while verifying: 403 covers
  spending-cap, the backoff was shortening a server Retry-After, and a 200 simulation was
  read as ACCEPTED.
- C2 atomic dispatch claim; verified by SQLite close/reopen AND a real SIGKILL mid-send.
- C3 the request is constructed from the signature, not handed in alongside it.
- C4 reconciliation uses the journal's durable binding and scoped, finalized evidence.

**Composed local run connected.** Real compiler -> admitted -> signed -> typed request ->
executed verbatim by the real controller on the fork -> consumed[] read back -> journal
CONFIRMED from that reading -> recovery refuses to resend. The on-chain consumed payload
is byte-identical to the action hash Python computed from the compiler output.

**Reclassified.** P03 PARTIAL (L10 open). P04 and P05 PARTIAL PREPARATION: their tests and
prototype are preserved and pass, but the runtime authority/handover service, owner
transaction builder, restartable handover machine, V4 section 8 views and real service
state do not exist, and both depend on a P03 route that does not.

**Two review defects fixed rather than only noted.** P04's handover test reused the SAME
operation id and payload; the console no longer says "nothing was sent" when a claimed
attempt is outstanding.

**Next / blocked.** `evidence/P03/public-action-request.json` is the bounded request.
Request A is credential-only, spends nothing, and is what converts L10 from
BLOCKED-UNKNOWN into a fact. Request B (public deployment/spending) is deliberately NOT
made yet: it is blocked on request A and on P04's missing authority inventory.
