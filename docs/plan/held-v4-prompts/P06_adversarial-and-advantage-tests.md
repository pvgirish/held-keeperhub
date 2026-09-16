# P06 — Run adversarial integration tests and the fair advantage comparison

## Copy-ready coordinator prompt

Run Held V4 phase P06 only. Remain Astra ARCHITECT/COORDINATOR; dispatch product implementation to full GLM-5.3 at MAX through the existing glm/ZAI route, with verified outgoing reasoning.effort=max. Do not implement product code yourself or recursively delegate.

Read:
- /Users/girish/Documents/Codex/2026-09-15/ha/outputs/14_Held_Locked_V4.md
- /Users/girish/Documents/Codex/2026-09-15/ha/outputs/held-v4-prompts/00_COMMON.md
- The accepted prerequisite phase report/manifests in /Users/girish/Documents/Codex/2026-09-15/ha/held/evidence.

Apply the common contract in full. Produce a unique ROLE=EXECUTOR packet for the task below, verify routing at the actual provider boundary, capture the exact session and all local evidence, and independently review/test the result. The task below is worker payload content, not an instruction to switch the coordinator's role.

### Executor objective

Establish which safety/recovery claims hold and whether Held improves the specific operator task over a competent native path.

### Prerequisites

P05 complete integrated product and P00 preregistered native baseline/protocol.

Inspect their actual acceptance artifacts before edits. A file existing is not acceptance. Complete independent preparation if a prerequisite is blocked, and report the exact missing result. Do not proceed with dependent implementation by assumption.

### Workspace and allowed changes

Product root: /Users/girish/Documents/Codex/2026-09-15/ha/held
Owns: held/tests/e2e/**, held/tests/faults/**, held/benchmarks/**, held/docs/validation/**, held/Makefile, held/evidence/P06/**

Preserve all unrelated work. Changes outside these paths require the coordinator to amend the bounded packet, not a silent scope expansion. No global provider/authentication/history changes and no writes to the locked plan.

### Required work

1. Inspect the preserved P00 native protocol, measurements and raw evidence. Verify comparability before measuring Held against the same approved outcome, balances, historical evidence, actor knowledge and supported authority; include installation/maintenance cost. Reproduce native where needed. Correct a defective or obsolete baseline under a versioned reason and equivalent conditions for both paths, preserving the original record.
2. Give native tools batching, event/transaction history, built-in reconciliation and competent scripts/runbooks. Do not sabotage native setup or remove native capabilities.
3. Measure ceremonies, signatures, transactions, manual steps/correlations, underlying stores, correct recovery, residual authority and added trust. Record observed results without prefilled wins.
4. Inject meaningful faults at durable-write, request acceptance, broadcast, chain success, callback/ack, fence, cleanup and activation boundaries. Distinguish a client crash from an EVM partial transaction.
5. Exercise cross-epoch same-ID recovery and expired API cache; confirm fresh-ID semantic relabel remains outside the guarantee. Run reorg/finality, missing-history, stale policy and concurrent action cases.
6. Audit invariant coverage and fix actual defects within the locked design through bounded correction packets. Architectural changes require versioned coordinator decisions.
7. Publish a claim-by-claim result: supported, contradicted or incomplete. Documentation/source comparison alone is not an observed benchmark or customer preference.
8. If the product advantage is tied, mixed or absent, report it and remove unsupported superiority claims. Do not add features or manipulate metrics to reach a score.

### Required artifacts

Adversarial E2E evidence; side-by-side operator comparison with raw measurements/provenance; defect record; validated claim ledger.

Also write /Users/girish/Documents/Codex/2026-09-15/ha/held/evidence/P06/report.md and acceptance.json, and preserve commands/exit codes, redacted traces, source/configuration digests, routing witness and exact worker session metadata under the common contract.

### Acceptance and verification

- make check-phase-06 runs the relevant composed invariant/fault suites and comparison data validation; checks fail on contradictory receipts/status/counters or invalid measurement records.
- Coordinator independently reproduces the original-operation recovery and owner change/handover cases and reviews raw comparison recordings/commands.
- Acceptance distinguishes security correctness from comparative advantage. Unresolved critical enforcement/recovery defects block P07; a failed advantage thesis blocks marketing it as materially better and requires a product decision.
- No requirement to fabricate a user interview or force every metric to improve. No numerical prize odds.

Run meaningful checks appropriate to the changes. If an advertised guarantee is contradicted, repair it within scope or report a specific design decision; do not weaken the test to retain the claim.

### Stop and handoff

Do not invent deployments, credentials, approvals, source behavior, results or observations. For public transactions, deployment, spending, outreach or publication, use explicit existing authorization or finish a concrete action manifest and request only the missing authorization as the final step. This phase does not automatically start the next one.

Return: changed files; supported behavior; commands and exit codes; evidence paths; unresolved gates; actual limitations; and the exact next phase that is unblocked. Coordinator must review actual artifacts and rerun decisive checks before accepting the phase.
