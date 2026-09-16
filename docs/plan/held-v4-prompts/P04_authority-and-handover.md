# P04 — Implement bounded authority inventory and owner-controlled handover

## Copy-ready coordinator prompt

Run Held V4 phase P04 only. Remain Astra ARCHITECT/COORDINATOR; dispatch product implementation to full GLM-5.3 at MAX through the existing glm/ZAI route, with verified outgoing reasoning.effort=max. Do not implement product code yourself or recursively delegate.

Read:
- /Users/girish/Documents/Codex/2026-09-15/ha/outputs/14_Held_Locked_V4.md
- /Users/girish/Documents/Codex/2026-09-15/ha/outputs/held-v4-prompts/00_COMMON.md
- The accepted prerequisite phase report/manifests in /Users/girish/Documents/Codex/2026-09-15/ha/held/evidence.

Apply the common contract in full. Produce a unique ROLE=EXECUTOR packet for the task below, verify routing at the actual provider boundary, capture the exact session and all local evidence, and independently review/test the result. The task below is worker payload content, not an instruction to switch the coordinator's role.

### Executor objective

Make the ordinary change/replacement workflow complete and truthful across on-chain and off-chain state.

### Prerequisites

P03 composed route accepted; P02 fencing/activation and P01 identity contracts.

Inspect their actual acceptance artifacts before edits. A file existing is not acceptance. Complete independent preparation if a prerequisite is blocked, and report the exact missing result. Do not proceed with dependent implementation by assumption.

### Workspace and allowed changes

Product root: /Users/girish/Documents/Codex/2026-09-15/ha/held
Owns: held/packages/authority/**, held/packages/handover/**, held/adapter/held_adapter/recovery/**, held/tests/authority/**, held/tests/handover/**, held/docs/recovery/**, held/Makefile, held/evidence/P04/**

Preserve all unrelated work. Changes outside these paths require the coordinator to amend the bounded packet, not a silent scope expansion. No global provider/authentication/history changes and no writes to the locked plan.

### Required work

1. Implement finalized common-block inventory of supported Safe/module/guard/fallback/Role paths, Morpho grant candidates and readback, and relevant token/Permit2 paths. Publish discovery range, source provenance, account/code assumptions and missing evidence per section.
2. Require complete supported zero-external-Morpho-delegate profile for activation. Do not infer shared Safe necessarily requires grants; detect legitimate conflicting use and avoid unapproved revocations.
3. Implement initial bootstrap and separate native-migration flow. New paused controller does not fence pre-existing native runner authority; owner must revoke/fence those paths before reconciliation.
4. Implement owner fence -> canonical reconciliation -> candidate -> cleanup/readback -> owner activation. Keep actual controller paused throughout preparation. Generate Safe owner transactions, never sign as the owner.
5. Use stable role keys and actual successful use to calculate new remaining capacity. Keep controller as sole role member; change the runner key in controller policy, not direct Roles member assignment to B.
6. Include exact expected use/config/policy guards in final atomic activation. Exercise races and extra cleanup transactions. Count actual ceremonies/signatures/transactions without promising one.
7. Export replacement context, native checkpoints, source and pending IDs, finalized results, quota state and credential references. B must obtain actual required data or explicitly remain blocked.
8. Separate observed UI state from on-chain state after readback failure or reorg; adapter stop is not owner fence. Do not automatically revoke arbitrary external paths.

### Required artifacts

Bounded authority checker/report; owner transaction builder; restartable handover state machine; replacement export and offline recovery instructions.

Also write /Users/girish/Documents/Codex/2026-09-15/ha/held/evidence/P04/report.md and acceptance.json, and preserve commands/exit codes, redacted traces, source/configuration digests, routing witness and exact worker session metadata under the common contract.

### Acceptance and verification

- make check-phase-04 tests missing archive data, unknown module/account, active delegate, allowance conflicts, stale candidate, failed revocation, crash at each transition and same transport/different runner keys.
- Fork tests prove old action before fence is counted, after fence fails, B cannot act while paused, and stale final batch reverts leaving pause intact.
- The legacy-grant exploit appears only in a labeled migration/drift fixture, never as valid protected initial state or as an ordinary native operator omission.
- Private credential control is labeled attested/unverified; public address lists do not prove key custody.

Run meaningful checks appropriate to the changes. If an advertised guarantee is contradicted, repair it within scope or report a specific design decision; do not weaken the test to retain the claim.

### Stop and handoff

Do not invent deployments, credentials, approvals, source behavior, results or observations. For public transactions, deployment, spending, outreach or publication, use explicit existing authorization or finish a concrete action manifest and request only the missing authorization as the final step. This phase does not automatically start the next one.

Return: changed files; supported behavior; commands and exit codes; evidence paths; unresolved gates; actual limitations; and the exact next phase that is unblocked. Coordinator must review actual artifacts and rerun decisive checks before accepting the phase.
