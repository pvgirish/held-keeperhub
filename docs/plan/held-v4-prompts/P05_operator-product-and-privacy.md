# P05 — Deliver the usable private operator product

## Copy-ready coordinator prompt

Run Held V4 phase P05 only. Remain Astra ARCHITECT/COORDINATOR; dispatch product implementation to full GLM-5.3 at HIGH through the existing glm/ZAI route, with verified outgoing reasoning.effort=high. Do not implement product code yourself or recursively delegate.

Read:
- /Users/girish/Documents/Codex/2026-09-15/ha/outputs/14_Held_Locked_V4.md
- /Users/girish/Documents/Codex/2026-09-15/ha/outputs/held-v4-prompts/00_COMMON.md
- The accepted prerequisite phase report/manifests in /Users/girish/Documents/Codex/2026-09-15/ha/held/evidence.

Apply the common contract in full. Produce a unique ROLE=EXECUTOR packet for the task below, verify routing at the actual provider boundary, capture the exact session and all local evidence, and independently review/test the result. The task below is worker payload content, not an instruction to switch the coordinator's role.

### Executor objective

Make terms, ordinary operation, change, interruption and replacement understandable and safe to operate without the author.

### Prerequisites

P04 working authority/change/recovery services and accepted typed APIs.

Inspect their actual acceptance artifacts before edits. A file existing is not acceptance. Complete independent preparation if a prerequisite is blocked, and report the exact missing result. Do not proceed with dependent implementation by assumption.

### Workspace and allowed changes

Product root: /Users/girish/Documents/Codex/2026-09-15/ha/held
Owns: held/apps/console/**, held/packages/server/**, held/packages/export/**, held/tests/product/**, held/tests/privacy/**, held/docs/operator/**, held/Makefile, held/evidence/P05/**

Preserve all unrelated work. Changes outside these paths require the coordinator to amend the bounded packet, not a silent scope expansion. No global provider/authentication/history changes and no writes to the locked plan.

### Required work

1. Build the four V4 views: Terms; Activity; Change & handover; Authority & export. Use existing real service state. Never hardcode a happy-path demo, fake receipt or completion badge.
2. Show current ceiling/Used/Remaining and exact differences before owner action, plus the pending business operation and required next action. Keep ABI/provider mechanics in diagnostics.
3. Separate HOLD, refusal, submitted, execution unknown, reverted, executed verified and outcome failure. Show on-chain fence/activation status separately from adapter readiness and report completeness.
4. Implement single-organization self-hosted authentication/authorization and Safe/lineage binding. Keep private data server-side, no anonymous private API, no default support access or telemetry.
5. Implement credential-reference storage, log redaction, inspectable export and retention/deletion policy that preserves required replay tombstones. Do not claim deletion of public chain data.
6. Document normal operation, owner approvals, resolving INCOMPLETE, recovery without Held services, and safe shutdown. No payment subscriptions, marketplace or new feature scope.
7. Use existing SDK/configuration settings and runnable examples; report real setup errors with precise remediation.

### Required artifacts

Working private console/API; operator instructions; privacy/data-flow/retention specification; safe recovery/export interface.

Also write /Users/girish/Documents/Codex/2026-09-15/ha/held/evidence/P05/report.md and acceptance.json, and preserve commands/exit codes, redacted traces, source/configuration digests, routing witness and exact worker session metadata under the common contract.

### Acceptance and verification

- make check-phase-05 exercises meaningful operator flows on actual service fixtures, wrong-Safe/lineage access, unauthorized owner actions, secret leakage, exported references and safe error messages.
- Visually inspect the views at normal and narrow widths. Verify the ordinary job and one interrupted handover without opening developer diagnostics.
- No cosmetic-only test suite is required; test user decisions, authorization and truthful status.
- Missing relevant inventory blocks the affected action. Restoring evidence resumes the correct pending flow rather than starting a new operation.

Run meaningful checks appropriate to the changes. If an advertised guarantee is contradicted, repair it within scope or report a specific design decision; do not weaken the test to retain the claim.

### Stop and handoff

Do not invent deployments, credentials, approvals, source behavior, results or observations. For public transactions, deployment, spending, outreach or publication, use explicit existing authorization or finish a concrete action manifest and request only the missing authorization as the final step. This phase does not automatically start the next one.

Return: changed files; supported behavior; commands and exit codes; evidence paths; unresolved gates; actual limitations; and the exact next phase that is unblocked. Coordinator must review actual artifacts and rerun decisive checks before accepting the phase.
