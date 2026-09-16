# P00 — Verify the route and measure the native baseline

## Copy-ready coordinator prompt

Run Held V4 phase P00 only. Remain Astra ARCHITECT/COORDINATOR; dispatch product implementation to full GLM-5.3 at HIGH through the existing glm/ZAI route, with verified outgoing reasoning.effort=high. Do not implement product code yourself or recursively delegate.

Read:
- /Users/girish/Documents/Codex/2026-09-15/ha/outputs/14_Held_Locked_V4.md
- /Users/girish/Documents/Codex/2026-09-15/ha/outputs/held-v4-prompts/00_COMMON.md
- The accepted prerequisite phase report/manifests in /Users/girish/Documents/Codex/2026-09-15/ha/held/evidence.

Apply the common contract in full. Produce a unique ROLE=EXECUTOR packet for the task below, verify routing at the actual provider boundary, capture the exact session and all local evidence, and independently review/test the result. The task below is worker payload content, not an instruction to switch the coordinator's role.

### Executor objective

Establish an evidence-backed candidate route and native execution seam, then run a preregistered competent native baseline before implementing the controller.

### Prerequisites

The locked V4 plan including amendment A1. Inspect and preserve any existing P00 work; this prompt does not establish that the phase has completed.

Inspect their actual acceptance artifacts before edits. A file existing is not acceptance. Complete independent preparation if a prerequisite is blocked, and report the exact missing result. Do not proceed with dependent implementation by assumption.

### Workspace and allowed changes

Product root: /Users/girish/Documents/Codex/2026-09-15/ha/held
Owns: held/docs/baseline/**, held/docs/decisions/**, held/fixtures/**, held/probes/**, held/Makefile, held/project-manifest.json, held/evidence/P00/**

Preserve all unrelated work. Changes outside these paths require the coordinator to amend the bounded packet, not a silent scope expansion. No global provider/authentication/history changes and no writes to the locked plan.

### Required work

1. Inspect existing workspace; create held/ without overwriting unrelated work. Pin SDK, KeeperHub API/documentation, Roles, Safe, Morpho and toolchain revisions. Record exact source paths and license/reuse constraints. Preserve user deadline exclusion.
2. Trace native strategy decision identity, compiler, pre-wrapping execution seam, risk validation and native result consumer. Resolve the configuration factory and signing path, not only class constructors. Produce a small native compile/probe output using the actual SDK. Verify the pinned strategy_runner.py#L9228 citation and nearby reconciliation semantics; the A1 evidence already confirms that file has 13,533 lines and that the anchor exists at revision 6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938. No hand-coded replacement strategy.
3. Settle route feasibility by evidence layer, before controller implementation. Carry forward the 15 September A1 findings: the public KeeperHub catalog returned Base Sepolia 84532 enabled/testnet; Morpho official addresses list 0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb on Base Sepolia; the Morpho plugin lists Ethereum/Base, while V4 uses the distinct generic /api/execute/contract-call route. Verify current GET /api/chains and the official registry; an alias table is not an exhaustive enabled catalog. Then read chain ID, finalized block/hash, contract bytecode, exact market/token parameters and decimals, market availability, native SDK chain/compiler configuration and Safe/Role compatibility. Verify the actual org caller/payer, key scope, direct-call method, provider caps, ABI handling and available preflight separately; catalog presence does not prove them. Record VERIFIED, SUPPORTED, BLOCKED-UNKNOWN or REJECTED for each layer in docs/decisions/route-evidence.json. Missing documentation is not proof of absence. Base Sepolia failure alone does not rule out all testnets. Any alternate testnet needs the same native profile evidence and a recorded profile decision. If no suitable testnet route is established, prepare the conditional small-value Base-mainnet option with a concrete action/fee/funding manifest and only the missing authorization; mainnet is not a hackathon rule. Documentation/read-only feasibility is the P00 gate; actual implemented execution remains P03. No substitute transfer, fake deployment, assumed funded wallet or silent chain/provider switch.
4. Define runner EIP-712 authorization separate from KeeperHub outer sender. Identify a dedicated owner-controlled fixture Safe with available history, or an explicit setup/funding plan, and complete the bounded bootstrap checklist. P03 may collect actual evidence manually before P04 automates inventory; it may not activate on INCOMPLETE. A generic transfer is an optional authorized access smoke test, never Held route acceptance.
5. Before either measured run, freeze the baseline runbook, fixture, requested change/handover outcome, actor knowledge, measures and meaningful interruption points. Give native batching, available allowance/event history, native recovery and competent authority checks full credit. Separate a valid protected starting profile from legacy-grant migration. Measure owner ceremonies, individual signatures, submitted transactions, manual tools/screens/commands and correlated fields, underlying stores, residual authority, recovery effort and added setup/trust. Do not call this blinded: the Held design is already known.
6. Run the native half now on a realistic labeled local fork using real native components: Safe/Role updates and batching, Almanak reconfiguration and existing recovery, Morpho readback and available history. Record the full operation and predeclared interruptions, raw observations, commands/recordings, environment and versioned measurements in docs/baseline/native-measurements.json. No Held controller or invented Held result. This local baseline is not public KeeperHub transaction evidence, and it authorizes no public writes.
7. Preserve the original baseline protocol and results. Review whether meaningful coordination or recovery benefit remains; if native already meets the proposed outcome with no material unresolved benefit, record a product decision before P01. P06 verifies comparability and runs Held, with necessary native reproduction or corrections allowed under a recorded versioned reason and equivalent conditions for both paths. Never freeze a mistaken benchmark forever or manufacture a win.
8. Establish Makefile/test infrastructure and source/profile manifests. Create explicit fork fixtures with labeled illustrative amounts; never describe a fixture as a live customer or mined public run.
9. Write docs/decisions/phase-priority.md: P03 supplies mandatory composed transaction proof; P02/P04 safety and handover dependencies remain required; P06 demonstrates reliability and P07 demonstrates developer reuse, both built throughout earlier phases. P08 must assemble and verify the source, working video and transaction links; a P03 receipt alone does not make an entry ready to submit. A blocked dependency triggers a bounded decision and independent preparation, not a silent stall or automatic skip. P05 remains the private console. A CLI alternative requires a versioned product amendment preserving all four jobs, owner-approval clarity, authentication/privacy, recovery export and tested usability. No claim a CLI automatically equals a console, no deadline-based cut, and no presumed score advantage.

### Required artifacts

docs/baseline/native-runbook.md; docs/baseline/comparison-protocol.md; docs/baseline/native-measurements.json with raw evidence; docs/decisions/configuration.md; docs/decisions/route-evidence.json; docs/decisions/phase-priority.md; project-manifest.json; reproducible SDK compile probe and fixture provenance.

Also write /Users/girish/Documents/Codex/2026-09-15/ha/held/evidence/P00/report.md and acceptance.json, and preserve commands/exit codes, redacted traces, source/configuration digests, routing witness and exact worker session metadata under the common contract.

### Acceptance and verification

- make check-phase-00 validates pinned source/profile manifests, executes the native compile probe and validates/reproduces the native baseline checks. Output shows genuine intent, ActionBundle, decoded core call and customer Safe account. Merely validating hand-entered measurement JSON is insufficient; human-step counts also need inspectable raw evidence.
- Source-level route report identifies interception and native result boundary, actual API method and caller/payer assumptions. Mark each unproved hosted behavior explicitly.
- Baseline ran under the preregistered protocol with the same safety objective and native batching/recovery credit. Record observations without prefilled wins; unresolved product advantage receives a decision before P01.
- Hard exit: a viable source/API/readback/native-compiler configuration is established and its remaining runtime/authorization assumptions are named. Missing decisive evidence is BLOCKED-UNKNOWN, a demonstrated incompatibility is REJECTED; neither becomes a false no-deployment claim. A failed configuration gate blocks dependent P01 work, not the whole event.
- Registry entry, chain catalog, bytecode/market readback, authenticated caller/payer preflight and actual P03 broadcast are separate evidence rows. P00 cannot certify a controller route that has not been implemented. Public authorization needs are concrete and no public write occurs merely because this baseline phase was invoked.

Run meaningful checks appropriate to the changes. If an advertised guarantee is contradicted, repair it within scope or report a specific design decision; do not weaken the test to retain the claim.

### Stop and handoff

Do not invent deployments, credentials, approvals, source behavior, results or observations. For public transactions, deployment, spending, outreach or publication, use explicit existing authorization or finish a concrete action manifest and request only the missing authorization as the final step. This phase does not automatically start the next one.

Return: changed files; supported behavior; commands and exit codes; evidence paths; unresolved gates; actual limitations; and the exact next phase that is unblocked. Coordinator must review actual artifacts and rerun decisive checks before accepting the phase.
