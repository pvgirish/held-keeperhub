# P03 — Connect native Almanak execution through KeeperHub

## Copy-ready coordinator prompt

Run Held V4 phase P03 only. Remain Astra ARCHITECT/COORDINATOR; dispatch product implementation to full GLM-5.3 at MAX through the existing glm/ZAI route, with verified outgoing reasoning.effort=max. Do not implement product code yourself or recursively delegate.

Read:
- /Users/girish/Documents/Codex/2026-09-15/ha/outputs/14_Held_Locked_V4.md
- /Users/girish/Documents/Codex/2026-09-15/ha/outputs/held-v4-prompts/00_COMMON.md
- The accepted prerequisite phase report/manifests in /Users/girish/Documents/Codex/2026-09-15/ha/held/evidence.

Apply the common contract in full. Produce a unique ROLE=EXECUTOR packet for the task below, verify routing at the actual provider boundary, capture the exact session and all local evidence, and independently review/test the result. The task below is worker payload content, not an instruction to switch the coordinator's role.

### Executor objective

Deliver the exact native integration in both its successful and uncertain-outcome paths.

### Prerequisites

P02 accepted fork controller/Role path and P01 journal/native result contract.

Inspect their actual acceptance artifacts before edits. A file existing is not acceptance. Complete independent preparation if a prerequisite is blocked, and report the exact missing result. Do not proceed with dependent implementation by assumption.

### Workspace and allowed changes

Product root: /Users/girish/Documents/Codex/2026-09-15/ha/held
Owns: held/adapter/held_adapter/execution/**, held/adapter/held_adapter/signing/**, held/packages/keeperhub/**, held/examples/**, held/tests/integration/**, held/docs/integration/**, held/Makefile, held/evidence/P03/**

Preserve all unrelated work. Changes outside these paths require the coordinator to amend the bounded packet, not a silent scope expansion. No global provider/authentication/history changes and no writes to the locked plan.

### Required work

1. Implement pre-wrapping ActionBundle interception preserving actual native compilation and risk checks. Decode against P01/P02 fixed shapes and compare approved bytes.
2. Sign the authorization envelope with the current runner key through its configured secret mechanism. Submit the exact outer call through KeeperHub using the resolved caller/payer route.
3. Implement supported dry-run versus broadcast behavior, stable execution key/body, rate-limit/backoff handling, conflict and in-progress semantics, polling and receipt/effect reconciliation. Never use a simulate flag on an unsupported endpoint.
4. Integrate the durable journal with actual native result/dedupe acknowledgement. Preserve original IDs after restart and after the KeeperHub cache window; query controller consumption before any resend.
5. Capture a genuine native strategy run, ActionBundle, exact bytes, KeeperHub execution record, actual sender/caller chain, controller event, Safe/Morpho effects and native result.
6. Before any public activation, complete P00's bounded bootstrap checklist against the actual dedicated fixture Safe at a stated finalized block/hash, with independent readback and owner authority. Manual evidence collection is permitted; incomplete evidence blocks activation. Do not claim P04 automated inventory exists yet.
7. Prepare a concrete public execution manifest and complete local checks first. Use specific existing authorization or request only missing authorization for deployment/funding/transaction. Local-fork proof remains labeled until the actual hosted/public path runs.
8. No alternate wallet, simplified deposit script, replacement protocol or provider/billing change to get a green result.

### Required artifacts

Native adapter and KeeperHub client; integration/configuration docs; exact successful and interrupted traces; public receipt bundle when authorized.

Also write /Users/girish/Documents/Codex/2026-09-15/ha/held/evidence/P03/report.md and acceptance.json, and preserve commands/exit codes, redacted traces, source/configuration digests, routing witness and exact worker session metadata under the common contract.

### Acceptance and verification

- make check-phase-03 runs deterministic integration tests for native success, HOLD, semantic refusal, timeout/server-acceptance ambiguity, conflicting keys, unknown receipt and original-operation recovery.
- Actual composed trace shows correct inner effects and one logical native result. Outer status alone is insufficient.
- The initial activation evidence includes the complete supported authority profile, exact Roles configuration, zero unmanaged grants/approvals and independent readback. A fresh Safe address alone is not proof of this profile.
- The public evidence acceptance requires a real KeeperHub-executed supported protocol action with explorer link and execution ID. If external authorization/access is missing, mark that gate blocked and do not claim P03 complete.
- Beyond-cache tests can simulate service cache expiry locally and must be labeled accordingly; do not claim an elapsed real-world 24-hour test unless performed.

Run meaningful checks appropriate to the changes. If an advertised guarantee is contradicted, repair it within scope or report a specific design decision; do not weaken the test to retain the claim.

### Stop and handoff

Do not invent deployments, credentials, approvals, source behavior, results or observations. For public transactions, deployment, spending, outreach or publication, use explicit existing authorization or finish a concrete action manifest and request only the missing authorization as the final step. This phase does not automatically start the next one.

Return: changed files; supported behavior; commands and exit codes; evidence paths; unresolved gates; actual limitations; and the exact next phase that is unblocked. Coordinator must review actual artifacts and rerun decisive checks before accepting the phase.
