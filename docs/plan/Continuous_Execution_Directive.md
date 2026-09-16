# Held V4 — continuous Claude execution, P00 through P08

## 1. Run-wide instruction

Girish has supplied the complete locked plan and all phase prompts, has replaced Codex/GLM execution with Claude, and now explicitly asks for continuous execution through the remaining phases, stopping only when further authorized progress genuinely requires outside input.

**Execute the remaining P00–P08 range, not another isolated P00 patch.** Finish each ready phase's implementation and meaningful verification; preserve its checkpoint; then continue without requesting permission for the next already-authorized local task. Do not end a response merely because a bug was fixed, a checker passed, a report was written, or the next phase prompt exists.

This is a prospective execution-process override, not evidence that any phase has already passed. It changes phase invocation, routine handoff cadence, and the timing of coordinator review. It does not change V4's product, material prerequisites, evidence standards, external-action permissions, or deadline exclusion.

## 2. Sources and precedence

Use the existing local sources; do not ask Girish to resend the plan:

- `ha/outputs/14_Held_Locked_V4.md`, including sequencing amendment A1.
- `ha/outputs/15_Held_V4_Phases_and_Prompts.md`.
- `ha/outputs/held-v4-prompts/00_COMMON.md` and all P00–P08 files.
- `ha/outputs/16_P00_Amendments_and_Explainer_Review.md`.
- The live `ha/held/` worktree, current evidence and manifests, and applicable live `AGENTS.md` / `CLAUDE.md` instructions.
- Latest C5 source/evidence, including `ha/outputs/held_P00_c5_handoff.tar.gz` if present. Compare the archive to the worktree; do not overwrite newer work with it.

This instruction supersedes only older procedural requirements for “P00 only,” one new user invocation per phase, return-after-each-patch, Codex/GLM dispatch, and mandatory coordinator round trips before every local continuation. Record this as `held/docs/decisions/EXEC-01-continuous-execution.md`; preserve the original locked files and document any actual instruction conflict.

Claude is the sole implementation writer. Astra remains the architect and independent reviewer. Do not invoke unavailable workers, invent routing witnesses, change model/provider/billing, or create another concurrent writer. A genuinely available separate read-only review context may inspect artifacts; its identity and actual work must be recorded. Self-review is not independent review.

## 3. Review timing: checkpoints are not automatic stops

The original pack requires coordinator acceptance before dependent phases. For this explicitly requested range, that **administrative review checkpoint is deferred for reversible local implementation**, provided all substantive prerequisites for the next phase actually have evidence and required technical checks pass.

Maintain separate fields or an equivalent explicit ledger:

- `implementation_status`: not started / in progress / locally verified / blocked.
- `evidence_status`: recorded separately for synthetic, real offline SDK, local fork, authenticated hosted, public-chain and clean-checkout evidence.
- `independent_review_status`: pending / accepted / changes required, naming a real reviewer when applicable.
- `next_authorized_local_phase`: justified by this run-wide directive and the substantive prerequisites actually satisfied.

Do not set `accepted=true`, call a phase independently accepted, or claim production/release readiness merely because you intend to continue. Keep final coordinator acceptance pending where it has not occurred. Do not modify a failed evidence check to obtain a green phase. Expose genuine technical results separately from a pending administrative review condition when necessary.

Only the coordinator round-trip is deferred. A missing native baseline, unsupported configuration, failed fork invariant, absent required P03 composed execution, incomplete authority evidence, or unresolved product decision is not an administrative review condition. These remain blockers to dependent work. Requirements for independent state readback, meaningful tests, and P07 separate-session replication also remain.

At a real blocker or the end of the authorized range, deliver one complete artifact package for Astra's independent review. Astra may require repairs to provisionally completed phases. No public activation, publication, spending or submission becomes authorized by this review-timing change.

## 4. Resume from C5, without another checker-only loop

The latest report describes real offline `IntentCompiler.compile()` SUCCESS, two native transactions, byte-based whole-bundle validation and 21 regression cases. These results are reported, not independently accepted in Chat: the C5 archive path was named but that archive was not attached here.

Inspect and rerun the available C5 artifacts in your environment. Preserve passing corrections. Keep testing-only price configuration clearly separate from runtime evidence. Record genuine compiler stages and complete output. Retain the observed native approval headroom as a finding; do not rewrite native output or demand Held's future cleanup wrapper from the unmodified P00 bundle.

If the decisive checks remain sound, move to the rest of P00. Do not repeatedly expand checker tests without a concrete uncovered requirement, changed code, or reproduced defect. A gate suite supports real work; it does not replace the native baseline or the product.

The old claim that every successful compilation requires RPC is no longer supported by the reported C5 run. RPC/fork state is still a distinct prerequisite for the measured fork baseline. Keep KeeperHub authenticated caller/payer L10 distinct from both.

## 5. Complete P00 as a phase

Reconcile the live gate ledger, not just the older uploaded acceptance snapshot. Complete all authorized P00 work:

1. Preserve pinned source/profile/toolchain and license provenance, native identity/interception/result seams, and genuine compilation output.
2. Complete configuration and route evidence by layer. Distinguish public catalog/registry facts, finalized code/market/token readback, supported SDK configuration, authenticated caller/payer preflight, and later actual P03 execution. An honestly documented unknown is not a verified fact; if it is necessary to configuration feasibility, it remains a blocker.
3. Complete the bounded dedicated fixture Safe bootstrap checklist, owner/Role assumptions, history requirements and explicit setup plan. Do not leave this work unstarted merely because another gate is blocked. P00 defines the checklist; P03 requires actual complete activation evidence.
4. Use a permitted, configured Base state source to run the realistic local fork. Check the actual current environment rather than assuming the historical egress failure still holds. If a policy denial remains, record it and the minimum permitted access needed; do not cycle through hosts or evade the restriction.
5. Preserve the frozen native comparison protocol and run its declared scenarios using real native components. Record raw steps, environment/block/source identity, results and measurements. Validate inspectable raw evidence, not only measurement JSON. No fabricated counts, mock substitute, or Held controller in the native baseline.
6. Review whether a meaningful proposed Held benefit remains over the competent native workflow. An absent/contradicted advantage requires a focused product decision before P01, not a forced win.
7. Run meaningful phase checks and reconcile manifests, report and gate evidence. Supply all remaining authorization/access requests as concrete action manifests, after independent preparation.

**P01 does not start without the actual P00 native baseline and required configuration evidence.** The C5 compilation result advances only what it proves.

## 6. Execute the existing phases, in order

The descriptions below are navigation aids. Read each complete original phase prompt and retain its required artifacts, allowed paths and acceptance conditions.

| Phase | Complete outcome | Substantive continuation condition |
|---|---|---|
| P00 | Native route/configuration evidence and measured native baseline | Necessary configuration, real baseline, raw evidence and product-decision requirements satisfied. |
| P01 | Versioned cross-language types, stable operation identity, durable journal/outbox and native result/ack contract | Identity, concurrency, crash/restart, payload conflict and modeled consumer boundaries genuinely tested. |
| P02 | Typed controller, native Roles configuration, finite counters and atomic approval/action/cleanup | Exact route and invariants pass against real pinned Safe/Role/Morpho components on a realistic fork. |
| P03 | Native Almanak to KeeperHub to controller/Role/Safe/Morpho and back to native result, including uncertainty/recovery | Required real composed trace, inner effects, activation evidence and actual KeeperHub public execution established under applicable authorization. Local mocks do not close this gate. |
| P04 | Supported authority inventory, owner fence, reconciliation, cleanup, activation and recoverable handover | Real prerequisite route established; incomplete history, races, stale state and former-runner behavior tested. |
| P05 | Private usable console, real service APIs, configuration and recovery export | Four specified views, truthful state, authentication/privacy and ordinary/interrupted operator jobs verified. Do not replace with a CLI without a product amendment. |
| P06 | Composed adversarial tests and fair native-versus-Held comparison | Critical defects resolved; raw comparison and claim ledger complete; any material failed-advantage decision resolved. Ties/tradeoffs are allowed evidence, not failed arithmetic. |
| P07 | Clean installation/replication, reusable integration, documentation, CI and traceable release manifest | Genuine clean checkout and required separate-session replication with assistance disclosed; evidence and secret/license checks complete. This is technical replication, not invented customer adoption. |
| P08 | Submission preparation, recorded working demo, live rehearsal, Q&A and evidence/access checks | Claims and mandatory artifacts verified against the real release. Publication/submission remains a distinct specifically authorized action. |

The canonical plan ends at **P08**, not P007. P07 is independent installation/release evidence. P08 is submission and demonstration preparation. No V3 interview counts, pay streaming, renewable observation leases, marketplace, or deadline-driven cuts may be reintroduced.

## 7. Continuous-work loop

For every ready task:

1. Read its prerequisite artifacts and source evidence.
2. Implement within the correct phase-owned paths; preserve unrelated work.
3. Run targeted meaningful checks, including real positive cases and relevant isolated failures.
4. Diagnose and repair ordinary implementation failures within scope. Do not stop simply because a dependency must be installed through an already-permitted route, a compiler fails, a test is red, or documentation needs updating.
5. Record the real diff, commands, exit codes, environment and evidence.
6. Check phase completeness rather than test count. If complete for local progression under section 3, checkpoint it and continue to the next authorized phase.
7. If a material gate is blocked, finish every unaffected authorized preparation task first. Do not mark dependent implementation ready by assuming the missing outcome.

Maintain `held/evidence/continuous-run.md` with current task, per-phase state, evidence references, remaining blockers and exact next command/task. Send brief progress updates during active execution without asking “shall I continue?” after each milestone.

Avoid uncontrolled retry loops: diagnose repeated identical failures, distinguish code/configuration defects from access/policy failures, and surface a specific decision when further permitted attempts cannot supply the missing input. Do not revive the old per-patch handoff simply because two ordinary test edits were needed.

## 8. Stop only for a concrete reason

A stop is warranted when all remaining ready work requires one of the following:

- Access/credential/environment capability genuinely unavailable through existing authorized mechanisms, such as a confirmed RPC policy block or missing KeeperHub org scope. Never ask for secrets in chat.
- A required external action without specific authorization: spending, public deployment/activation/transaction, owner signature, outbound message, repository publication, upload or submission.
- A demonstrated incompatible configuration, unresolved material product decision, or required architecture change outside V4. Do not remove safeguards or substitute a different protocol to continue.
- A substantive dependency that cannot be verified, including P00's native baseline or P03's actual route.
- An actually unavailable separate-session replication capability when the P07 requirement is reached.
- An execution/context/tool limit that really prevents more work, or completion of the entire authorized range.

At P03, actual public evidence is required before the dependent P04 phase under the unchanged plan. Finish local integration tests, manifest preparation and other genuinely independent work before asking for the missing permission/access. Do not turn the authorization boundary into a silent dependency waiver.

A missing public-action permission blocks that action, not all possible local preparation. Prepare exact calls/addresses/chain, value, cost limits, permissions, artifact destinations and rollback/stop conditions before requesting only the missing authorization. Use existing specific authorization when valid; this broad multi-phase request is not unlimited transaction authority.

## 9. Return one decision-ready handoff

At the real stop or completion, provide:

- Completed, locally verified, independently reviewed and blocked phases, clearly distinguished.
- The precise blocking gate and observed failure, not a general claim that “RPC is needed” or “P00 is red.”
- Commands and exit codes, relevant redacted trace, attempts and diagnosis.
- All independent preparation completed and why the remaining tasks depend on the blocker.
- The single smallest decision/access/action needed, or a consolidated manifest when multiple known independent authorizations are needed.
- A secret-free archive containing updated source/tests/docs, diff, original and new evidence, current phase manifests, run ledger and file hashes. Exclude secrets, private RPC URLs, virtual environments and dependency trees.
- Exact resume location and next permitted phase/task. Do not provide only a prose summary or an inaccessible local filename as though Chat received the archive.

**Continue now from the live C5 state. The next deliverable is the remaining real P00 work and then the rest of the authorized phase range wherever its prerequisites permit—not another request for permission to work.**
