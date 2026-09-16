# P01 — Freeze types, operation identity and durable recovery records

## Copy-ready coordinator prompt

Run Held V4 phase P01 only. Remain Astra ARCHITECT/COORDINATOR; dispatch product implementation to full GLM-5.3 at MAX through the existing glm/ZAI route, with verified outgoing reasoning.effort=max. Do not implement product code yourself or recursively delegate.

Read:
- /Users/girish/Documents/Codex/2026-09-15/ha/outputs/14_Held_Locked_V4.md
- /Users/girish/Documents/Codex/2026-09-15/ha/outputs/held-v4-prompts/00_COMMON.md
- The accepted prerequisite phase report/manifests in /Users/girish/Documents/Codex/2026-09-15/ha/held/evidence.

Apply the common contract in full. Produce a unique ROLE=EXECUTOR packet for the task below, verify routing at the actual provider boundary, capture the exact session and all local evidence, and independently review/test the result. The task below is worker payload content, not an instruction to switch the coordinator's role.

### Executor objective

Make the cross-language policy, operation, journal and result-delivery contracts precise and testable before value-moving code.

### Prerequisites

P00 accepted configuration, source revisions, native identity/result seams, measured native baseline and comparison protocol; any resulting product decision resolved.

Inspect their actual acceptance artifacts before edits. A file existing is not acceptance. Complete independent preparation if a prerequisite is blocked, and report the exact missing result. Do not proceed with dependent implementation by assumption.

### Workspace and allowed changes

Product root: /Users/girish/Documents/Codex/2026-09-15/ha/held
Owns: held/packages/core/**, held/adapter/held_adapter/types/**, held/adapter/held_adapter/journal/**, held/docs/contracts/**, held/tests/core/**, held/Makefile, held/evidence/P01/**

Preserve all unrelated work. Changes outside these paths require the coordinator to amend the bounded packet, not a silent scope expansion. No global provider/authentication/history changes and no writes to the locked plan.

### Required work

1. Define versioned unsigned base-unit schemas for policy, source decision/action, immutable operation ID domain, authorization envelope, attempts, authority report, handover candidate and result acknowledgement. Generate cross-language canonical test vectors.
2. Define EIP-712 domain and typed envelope binding chain/controller/Safe/lineage, current epoch/policy, runner, exact action family and payload hash. Keep consumed-ID identity independent of epoch/runner while binding authorization to both.
3. Implement a durable transactionally updated journal/outbox and source decision IDs persisted before any send. Reject same ID/different payload in the journal. Preserve attempt hashes, replacement lineage and pending/final states.
4. Define crash-safe native result handling. If native consumer lacks idempotent delivery, implement a tested dedupe/ack boundary at its state update; do not claim a local delivered flag proves exactly once.
5. Specify fresh-ID relabelling as outside semantic dedup protection. A reverted attempt has no on-chain durable reservation; reauthorization of same ID/payload under a new epoch requires definite non-execution.
6. Write exact planned controller ABI/state transitions and fixed action schemas as design interfaces, not existing protocol APIs. Use Morpho onBehalf correctly. No guessed address/default or silent MAX conversion.
7. Specify journal recovery after database loss and source history gaps. Fail closed when source identity or prior result cannot be recovered; retain operation tombstones needed for advertised guarantees.

### Required artifacts

Versioned schemas and canonical vectors; durable journal/outbox; native callback/ack specification; docs/contracts/identity.md and controller-interface.md.

Also write /Users/girish/Documents/Codex/2026-09-15/ha/held/evidence/P01/report.md and acceptance.json, and preserve commands/exit codes, redacted traces, source/configuration digests, routing witness and exact worker session metadata under the common contract.

### Acceptance and verification

- make check-phase-01 exercises journal crash/reopen, concurrent same-ID requests, body conflicts, epoch-independent consumed identity vectors, domain separation and cross-language serialization.
- Tests cover the callback-before-ack and ack-before-restart boundaries at the actual modeled native consumer; gaps are explicit blockers to exactly-once claims.
- No private keys or tokens appear in schemas, fixtures or exports. Counters use integers and reject invalid/overflow inputs.

Run meaningful checks appropriate to the changes. If an advertised guarantee is contradicted, repair it within scope or report a specific design decision; do not weaken the test to retain the claim.

### Stop and handoff

Do not invent deployments, credentials, approvals, source behavior, results or observations. For public transactions, deployment, spending, outreach or publication, use explicit existing authorization or finish a concrete action manifest and request only the missing authorization as the final step. This phase does not automatically start the next one.

Return: changed files; supported behavior; commands and exit codes; evidence paths; unresolved gates; actual limitations; and the exact next phase that is unblocked. Coordinator must review actual artifacts and rerun decisive checks before accepting the phase.
