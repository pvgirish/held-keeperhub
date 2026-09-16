# P02 — Implement the typed controller and native Roles enforcement

## Copy-ready coordinator prompt

Run Held V4 phase P02 only. Remain Astra ARCHITECT/COORDINATOR; dispatch product implementation to full GLM-5.3 at MAX through the existing glm/ZAI route, with verified outgoing reasoning.effort=max. Do not implement product code yourself or recursively delegate.

Read:
- /Users/girish/Documents/Codex/2026-09-15/ha/outputs/14_Held_Locked_V4.md
- /Users/girish/Documents/Codex/2026-09-15/ha/outputs/held-v4-prompts/00_COMMON.md
- The accepted prerequisite phase report/manifests in /Users/girish/Documents/Codex/2026-09-15/ha/held/evidence.

Apply the common contract in full. Produce a unique ROLE=EXECUTOR packet for the task below, verify routing at the actual provider boundary, capture the exact session and all local evidence, and independently review/test the result. The task below is worker payload content, not an instruction to switch the coordinator's role.

### Executor objective

Prove the supported authority, replay, policy and atomic-execution contracts against real pinned Safe/Role/Morpho code on a local fork.

### Prerequisites

P01 accepted types/ABI/identity and P00 pinned deployment/profile.

Inspect their actual acceptance artifacts before edits. A file existing is not acceptance. Complete independent preparation if a prerequisite is blocked, and report the exact missing result. Do not proceed with dependent implementation by assumption.

### Workspace and allowed changes

Product root: /Users/girish/Documents/Codex/2026-09-15/ha/held
Owns: held/contracts/**, held/test/contracts/**, held/script/**, held/fixtures/contracts/**, held/docs/contracts/**, held/Makefile, held/evidence/P02/**

Preserve all unrelated work. Changes outside these paths require the coordinator to amend the bounded packet, not a silent scope expansion. No global provider/authentication/history changes and no writes to the locked plan.

### Required work

1. Implement a paused-by-default, non-upgradeable or equivalently explicitly owner-fixed scoped controller with only owner-controlled policy/fence/activation and typed execution. No generic runtime call executor.
2. Require current-epoch runner EIP-712 signature plus configured executor route; controller sole member of operating roles. Reject malformed/malleable signatures using a reviewed library. Shared KeeperHub sender must not make old runner key valid for new epoch.
3. Implement successful operation-ID consumption, hash evidence, finite lifetime use/count/timestamp rules, normal/restoration classification and owner pause/epoch retirement.
4. Implement exact ordinary CALL sequence through Roles and Safe for approval, unchanged native Morpho action and cleanup. Decode all nested statuses and read state effects. No arbitrary MultiSend/delegatecall route, unlimited approval, callbacks or owner/module update.
5. Configure native Roles target/parameter conditions and nonrefilling amount/count allowance keys without double-counting approval calls. Enforce synchronization at activation and operating checks with explicit base-unit arithmetic.
6. Implement expected-usage/state guards on atomic owner policy/allowance activation. Initial deployment cannot operate; fence/activation cannot bypass owner Safe authority.
7. Implement exact token/share rounding and zero-borrow/unchanged-collateral/zero-managed-allowance properties. Preserve owner recovery independently.
8. Do not import native pre-Held usage into verified counters; a new lineage uses the explicitly scoped new budget. Document owner-controlled migration boundary.

### Required artifacts

Typed controller source/ABI; deployment/configuration scripts for local fork; real Roles config; unit/property/fork evidence and threat-model notes.

Also write /Users/girish/Documents/Codex/2026-09-15/ha/held/evidence/P02/report.md and acceptance.json, and preserve commands/exit codes, redacted traces, source/configuration digests, routing witness and exact worker session metadata under the common contract.

### Acceptance and verification

- make check-phase-02 runs unit/property and realistic fork tests for valid SUPPLY/WITHDRAW/HOLD, limits, floor lanes, cooldowns, successful-counter changes and expected policy updates.
- Negative tests cover wrong domain/epoch/key/caller/role/market/receiver/callback/wrapper, payload mutation, replay, reentrancy, nested false return and cleanup failure.
- Assert transaction rollback of token effects, allowances and successful IDs/counters; gas/transaction nonce are explicitly excluded.
- Assert B cannot execute while paused and A signatures cannot execute after retirement, including when transport sender is unchanged.
- A failed exact atomic route blocks P03. Do not replace the protocol with a mock and report a composition pass.

Run meaningful checks appropriate to the changes. If an advertised guarantee is contradicted, repair it within scope or report a specific design decision; do not weaken the test to retain the claim.

### Stop and handoff

Do not invent deployments, credentials, approvals, source behavior, results or observations. For public transactions, deployment, spending, outreach or publication, use explicit existing authorization or finish a concrete action manifest and request only the missing authorization as the final step. This phase does not automatically start the next one.

Return: changed files; supported behavior; commands and exit codes; evidence paths; unresolved gates; actual limitations; and the exact next phase that is unblocked. Coordinator must review actual artifacts and rerun decisive checks before accepting the phase.
