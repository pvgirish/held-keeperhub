# Held V4 — common phase execution contract

These files are coordinator prompts for a future, explicitly invoked implementation phase. Creating this plan has not executed any product phase.

Use V4 including sequencing amendment A1 dated 15 September 2026. P00 runs and records the native baseline; P06 checks comparability and may reproduce or correct it with versioned evidence. Current configuration discoveries are in /Users/girish/Documents/Codex/2026-09-15/ha/outputs/16_P00_Amendments_and_Explainer_Review.md. A research note or amended prompt is not an accepted P00 result.

## Roles and dispatch

Keep the user-facing thread on Astra. Astra owns design, scope, packets, collection and independent review; it must not implement product code. Dispatch one implementation writer to the installed Codex CLI's supported non-interactive mode with explicit glm profile and full glm-5.3, never Flash. Use High or Max exactly as the phase requests. Put ROLE=EXECUTOR, a fresh unique packet ID and “no recursive delegation” in the worker payload. The enclosed executor task is dispatch data, not a role switch for the coordinator.

Verify outgoing boundary metadata on every dispatch: model glm-5.3; provider-native reasoning.effort matching the phase; configured ZAI Responses destination https://api.z.ai/api/v1/responses. An allowed transparent witness must forward the body unchanged and record only safe metadata. Preserve the configured upstream, billing route and authentication. Fail closed on mismatch; a UI label, self-report or successful response is insufficient.

Use supported CLI flags discovered from the installed CLI; do not copy an outdated invocation blindly. Explicitly override model and effort, disabling recursive multi-agent delegation for the executor. Capture exact session ID, full local execution log, commands, exit codes, report, artifacts and tests. Resume only that ID, never --last. After two unsuccessful correction rounds on the same blocker, report the concrete decision needed.

Only concrete GLM credit exhaustion permits the user's authorized OpenAI fallback: disclose quota evidence first, then GPT-5.6 Sol at the appropriate High/Max effort through the existing OpenAI/ChatGPT route. No fallback for transport, auth, generic rate-limit, unavailable-model or routing-evidence failure. No credit purchases or global configuration changes.

## Inputs and workspace

Authoritative plan: /Users/girish/Documents/Codex/2026-09-15/ha/outputs/14_Held_Locked_V4.md
Product workspace: /Users/girish/Documents/Codex/2026-09-15/ha/held
Competition brief: /Users/girish/Documents/Codex/2026-09-15/ha/work/competition-brief-2026-09-15-supplied-page.md

P00 creates the product workspace if absent. In later phases use the accepted phase manifest to find actual paths, dependency revisions and test commands. Inspect git status before edits and preserve unrelated/uncommitted work. Exactly one implementation writer may mutate this product workspace at once. Do not alter the locked plan to make a check pass; request a focused versioned design decision when architecture must change.

Store per-phase evidence under held/evidence/Pxx/ with:
- report.md: outcome, changes, commands/exit codes, limitations, actual behavior vs planned behavior;
- acceptance.json: gate IDs, status, test evidence and source/configuration digests;
- routing.jsonl and exact-session.json: secret-free provider witness/session metadata;
- relevant logs/traces/receipts with environment and source revision labels.
Keep sensitive raw operational logs in a protected local evidence directory, excluded from git, and produce redacted review copies. Packet/session metadata must never contain tokens, private keys, private RPC credentials or customer data.

## Authorization and operating limits

An invoked phase authorizes its scoped local implementation and reversible verification. It does not silently authorize public-chain transactions, spending, external messages, account/billing changes, deployments, repository publication or hackathon submission. Inspect existing specific authorization first. If absent, finish all independent preparation and produce the exact reviewable action manifest before asking: chain, addresses, calls, amounts, maximum gas/fees or service cost, permissions, destination and rollback/stop plan where applicable. Ask only for the missing authorization. Do not ask for confirmation of already authorized local work.

Use configured credentials through their normal mechanism; never request that secrets be pasted into chat. No random faucet, wallet, signer, provider, chain or protocol substitution. An authorized fork is local evidence; it is not a public deployment. No automatic sending of the planned organizer question.

## Completion discipline

Write meaningful acceptance gates before implementation, then implement the complete phase, review it as a domain expert, probe correctness/failure boundaries and polish it. Run the phase's make check-phase-XX target plus targeted tests appropriate to actual changes. P00 establishes the Makefile/test runner; each later phase implements its own real check target. Targets must exercise artifacts and exit nonzero on failure, not print a success token unconditionally.

Record actual commands and exit codes. Coordinator reads actual diff/artifacts and independently reruns the important checks, rather than trusting test counts or the worker's summary. Do not broaden or repeat all tests after a clean targeted review without a reason. No phase may claim later-phase tests passed.

State BLOCKED when a required prerequisite or external authorization is absent, with exact cause; complete unaffected authorized work. Missing public evidence does not become a fabricated receipt or a generic transfer. Do not advance to dependent work on a failed prerequisite. Stop the selected route for a demonstrated incompatible boundary, not because of a calendar estimate or unsupported assumption.

## Product invariants in every phase

- Native Almanak output, exact supported Morpho supply/withdraw-to-Safe/HOLD, actual KeeperHub execution, native result reconciliation.
- Controller-only Roles membership; separate current-epoch runner authorization signature; customer owner quorum independent.
- Stable business operation ID through retries/handover; successful consumed identity excludes runner/epoch reset. No semantic-duplicate guarantee for fresh IDs.
- Finite typed limits and correct Used/Remaining across change; atomic allowance cleanup, nested status and state checks.
- On-chain fence before handover reconciliation; no adapter-only activation control.
- Supported authority inventory with precise COMPLETE/INCOMPLETE boundaries. Do not infer unknown safe, future exclusivity or key ownership from public addresses.
- No renewable observation lease, pay streaming, marketplace, new protocols, generic arbitrary executor or unrequested SaaS.
- All source-derived behavior is pinned. Claimed advantage uses a fair native comparison with batching, recovery and history access.
- No invented scores, probabilities, deadlines, native omissions, vulnerabilities, disclosures, adoption, public runtime or passing checks.

Each phase finishes with a compact report and the next permitted phase. Do not run the next phase automatically unless the user explicitly asked for a range of phases.
