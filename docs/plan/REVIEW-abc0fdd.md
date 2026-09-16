# Held — source review at abc0fdd and consolidated continuation

**Reviewed commit:** `abc0fdd3e832538900045961574ccb2887734e07`, `pvgirish/held-keeperhub`, main.
**Review basis:** latest uploaded execution report; read-only GitHub source inspection; original Locked V4 including A1, the original P00–P08 prompts and the continuous-execution directive; current official KeeperHub direct-execution documentation.
**Verification boundary:** this is an independent source/requirements review. The reviewer has NOT rerun the reported Forge, SDK, browser or Python suites at this commit. The regression scenarios below are tasks to execute, not reported reproduction results. No hosted request, public transaction, credential change or repository mutation was made by the reviewer.

## Decision

Preserve every pushed commit and working component. Do not restart P00/P01, repeat solved compiler construction work, or redesign Held. But do not call P03's local integration, P04, or P05 complete, and do not begin the measured P06 comparison against incomplete runtime services.

Resume with the concrete P03 defects below. Retain P04/P05 work as partial local preparation and regression assets; do not delete it. Required public P03 evidence remains a substantive prerequisite for complete P04 progression under the unchanged plan. Independent preparation is permitted, but is not a dependency waiver.

## 0. Restore the source of truth before editing

The accompanying `authoritative_plan/` directory contains unchanged Locked V4/A1, the phase map, every original phase prompt and the continuous directive, with SHA-256 checksums. These were recovered from the user-supplied original archive, not reconstructed from the implementation.

Place a versioned unchanged copy under the live repository's `docs/plan/` (or an equally clear location), record its digests, and update the current checkpoint's pointers. Compare with any newer authorized plan before writing. Do not overwrite newer work or treat old C5/C8 resume pointers in historical instructions as the current task.

Standing overrides remain: Claude is the sole executor; ChatGPT is architect/reviewer; authorized continuous local execution replaces per-patch/per-phase permission requests. Historical Codex/GLM routing in the original prompts is not active. Private GitHub commits/pushes are authorized. Public visibility, releases, deployments, funding, spending and broadcasting require separate specific authorization.

V4 section 8 explicitly supplies the four views:
1. Terms.
2. Activity.
3. Change & handover.
4. Authority & export.

The related jobs may be expressed in user-friendly language, but the required views and behaviors need not be guessed. No amendment accepting a substitute enumeration or waiving P03's public prerequisite is established by the material available to this review. If an actual later user amendment exists, preserve its exact text and reconcile it explicitly rather than inferring authorization.

## 1. Preserve the progress that is now evidenced

- Exact recognized native status handling, missing-verdict rejection and ordinary FAILED+safety-refusal classification are present in `native_boundary.py`. Declared intent is compared with decoded action family.
- The report's return-tuple/share-readback checks, identical-envelope recovery and added cross-language signer evidence are useful progress. Preserve their source and actual run records. They do not establish the complete submitted request/native result loop by themselves.
- The earlier A1/A2 operating/refill, Roles conditions, count consumption and non-vacuous withdrawal-property fixes stay closed as previously reviewed. Do not redo them absent a new concrete regression.
- Do not spend a new cycle re-proving I2/I6 native controls, revisiting Foundry observation-versus-pin, or analyzing the old VM::deployCode anomaly. Keep that explanation scoped to what was observed.

## 2. P03-C1 — the client is not yet implementing the documented wire contract

**Files:** `adapter/held_adapter/execution/keeperhub.py`, related integration tests and execution manifest.

At this commit:
- `ContractCallRequest.to_payload()` builds `chainId`, `to`, `data`, `value`, `idempotencyKey`, and metadata.
- `_headers()` never sets `Idempotency-Key`.
- `EXECUTION_PATH` is `/api/execute/{execution_id}`, with no `/status` suffix.
- `_classify()` collapses every 409 into IN_PROGRESS and every 2xx into ACCEPTED.
- `_send()` retries ambiguous network errors and 5xx. Without the documented idempotency header this is not evidence of protected provider retry behavior.

The current official contract-call documentation names `contractAddress`, `chainId`, `functionName` (or its documented alias), `functionArgs` and ABI representation, a separate `Idempotency-Key` header, and the `/status` poll route. It distinguishes conflicting bodies from requests already in progress. The numeric chain ID is documented; the code's internal-catalog-ID uncertainty is not something that requires an org key to resolve.

**Required repair:** verify the actual request handler/official schema; implement that contract rather than inventing raw-calldata aliases. Use explicit ABI/function arguments that reproduce the expected controller calldata exactly, and retain the encoded-byte equality check. Preserve simulation/broadcast distinction and endpoint support. Separate conflict, in-progress, deterministic simulation refusal, ambiguous broadcast, failed on-chain receipt and unknown outcome. A transport flag or HTTP 2xx is not a completed simulation, authenticated caller/payer proof, or economic success.

**Regressions:** inspect outgoing headers/body/path with a recording offline transport; exercise both documented 409 bodies; timeouts/5xx followed by retry must retain the identical persisted request and key; missing/contradictory success evidence must not become success; retain provider errors without leaking credentials. Honor documented pacing rather than silently shortening a Retry-After value.

**Source:** https://docs.keeperhub.com/api/direct-execution (request, idempotency, simulation, status sections; reread 16 September 2026). Keep documented schema evidence distinct from an authenticated live test. This review itself did not perform one.

## 3. P03-C2 — a pending attempt does not make the operation non-sendable

**Files:** `submit.py`, `packages/core/held_core/journal.py`.

`record_attempt_before_send()` commits an attempt with state PENDING but leaves the operation AUTHORIZED. `Submitter.submit()` changes the operation to DISPATCHED only after `client.broadcast()` returns and the result is recorded. AUTHORIZED belongs to `_SENDABLE`; submit does not inspect unresolved attempts and normally generates a new UUID attempt/key.

**Crash trace to reproduce:**
1. Authorize operation O and persist attempt A.
2. Let the transport receive the request, then terminate the caller before returning/recording its result.
3. Reopen the actual SQLite database in a fresh process.
4. Verify O is currently AUTHORIZED with a PENDING attempt.
5. Call submit again. The current path can generate attempt B and a second network request instead of blocking/recovering A.

This is an integration-level crash hole, not proof the controller allows two successful executions of the same operation ID. The controller's consumed-ID defense should still reject an already-consumed ID; duplicate submission, gas expenditure, request identity and incorrect recovery/UI state remain real concerns.

**Required repair:** atomically claim the operation for dispatch and persist the immutable request/key/attempt before I/O. Reopening must identify the unresolved original attempt and follow the permitted reconciliation/retry rules, not create a fresh key. Prevent concurrent submitters from both claiming new attempts. Persist the bytes/body needed for exact replay; an envelope hash alone is not a replayable request. Keep simulation observations separate from ambiguous economic-send attempts.

**Regressions:** actual SQLite close/reopen and process termination before send, after remote acceptance, before send-result write, and before operation-state update; two concurrent callers; expired cache; same ID after definite nonexecution; no duplicate network send while uncertainty is unresolved. Test the HTTP console's reading of this state too: it must not say 'nothing was sent' for a pending ambiguous attempt.

## 4. P03-C3 — the signed authorization is not bound to the request being sent

**File:** `submit.py::Submitter.submit()`.

The method receives `admitted`, `envelope`, and arbitrary `calldata` separately. It calls `auth = signer.sign(envelope)`, records auth's hash/reference, and then sends the caller-supplied calldata. It does not use the resulting signature to build that calldata or prove the calldata contains the same admitted operation/envelope/signature. It also lacks a visible admitted-operation/envelope binding check at this boundary.

**Required repair:** construct the only permitted typed controller invocation after signing, using the verified admitted action and exactly that authorization. Alternatively, a separately supplied encoded request must be fully decoded and matched before it can leave. Match chain, controller, Safe, lineage, operation ID, economic hash, epoch/policy, signer and concrete action. No arbitrary runtime executor should be introduced to accommodate encoding.

**Regressions:** mismatch each independent input; record network-call count zero for rejection. Test actual Python-generated request arguments and signature against the deployed local controller and exact native economic bytes. The prior independent digest/vector checks are valuable but do not substitute for this connected invocation.

## 5. P03-C4 — reconciliation uses a caller-provided expected hash instead of its durable binding

**File:** `submit.py::Submitter.reconcile(operation_id, payload_hash, chain)`.

The method loads the journal operation but compares the chain marker with the method argument `payload_hash`, not with `op.payload_hash`. A caller passing Q for an operation durably bound to P can make a chain marker Q match and drive CONFIRMED. Reject a caller/durable-binding mismatch and compare with the authoritative stored binding.

The ChainReader protocol currently returns only a marker string. A complete native-result path still needs verified chain/controller scope, the applicable block/hash/finality evidence, receipt/economic correlation and the real native consumer/ack contract. Do not treat a bare marker from an arbitrary reader as full finalized evidence or call a local journal transition native acknowledgement.

**Regressions:** mismatched caller hash; correct marker on wrong chain/controller; unfinalized/reorganized evidence; uncertain zero marker; persisted native callback/ack crash and duplicate delivery. A definite failure must carry the appropriate nonexecution evidence, not be inferred from an arbitrary HTTP/transport error. Never silently rebind a stored operation.

## 6. P04 — contract examples are not the requested runtime inventory/handover service

The phase gate runs `HeldAuthority.t.sol`. Its inventory test tries a fixed set of known actors. It does not implement a reusable finalized-common-block scanner of Safe owners/modules/guard/fallback, Roles paths, reconstructed Morpho grants, token/Permit2 paths and missing history. Passing known positive/negative actor examples cannot establish exhaustive supported inventory.

The original P04 requires a bounded authority report, owner transaction builder, restartable handover state machine and replacement export with native checkpoints. The designated `packages/authority`, `packages/handover` artifacts are not present under packages at this commit (only core is listed). Do not substitute test helpers and prose owner steps for runtime services. Reuse the working contract tests as regression coverage while implementing the original artifacts in the correct scope.

`test_RunnerReplacementMidFlightLeavesNothingToGuess()` signs operation `ho-1`, then executes `ho-1-again` after handover. That does not establish reauthorization of the SAME operation. Repair this test to retain the original ID and payload, resolve the old attempt with the appropriate finalized fence/nonexecution evidence, and change only the authorization epoch/runner as permitted.

A refusal from a call addressed to Roles describes that contract's authority boundary; it does not by itself prove the caller is or is not a module on the Safe. Read and label both module managers separately before retaining the report's 'module on the Safe' statement.

The unchanged plan requires actual composed/public P03 evidence before complete dependent P04 progression. Preserve later-phase work as partial preparation; do not claim the prerequisite is waived because accepted=false is recorded.

## 7. P05 — useful prototype, not a connected private operator product

**Files:** `console/run.py`, `console/held_console/state.py`, `console/held_console/app.py`.

### 7.1 Source of truth and truthful status

`run.py` always constructs `Console(demonstration_state, journal)`. Its docstring mentions `--state-source` but the argument parser defines only `--journal` and `--port`. Thus the supplied entry point has no real chain-state source. It can combine a real journal with fixed demonstration balances and Active/epoch=3 state.

The dashboard page does not receive the promised demonstration banner. A label in source comments is not a label shown to the operator. Mark demonstrations unmistakably and do not make demo mode the apparent connected product.

Build the actual state provider over the validated services, including provenance, finality, data completeness and scope. Show unavailable/INCOMPLETE data rather than an Active badge from hardcoded data. Missing native_remaining entries are currently silently skipped by drift(); absent evidence must not be treated as agreement.

### 7.2 Four specified views and owner approvals

Implement Terms; Activity; Change & handover; Authority & export from V4 section 8. Retain useful language from J1–J4 but do not let it replace the original required behavior.

PreparedChange currently contains descriptions and instructions, not an unsigned owner transaction/candidate bound to live expected state. Generating an unsigned Safe transaction does not give the console owner keys or owner authority. Keep owner signatures in the customer's Safe tools and supply the usable preparation/readback flow.

The actual limit form asks for base units even though the report claims human-readable input. Provide explicit typed decimal/unit input and exact conversion with validation; internal base units remain in diagnostics/storage.

### 7.3 Scope, export and real service integration

LiveState has no organization, chain, lineage or finalized-block fields. Login alone is not verification that the configured journal, state provider, request and exported operations belong to the intended Safe/lineage. Implement the original single-organization binding and wrong-Safe/lineage tests, not multi-tenant product expansion.

`export()` emits unresolved operations and attempts. It does not export the tombstones its own docstring promises, nor the complete native checkpoint/configuration/finality/quota/authority context required for replacement recovery. Implement and test the required recoverable export; do not merely add fields claiming data that has not been collected.

### 7.4 Additional concrete connected-runtime regression

Journal opens SQLite with the default same-thread restriction. `run.py` constructs that Journal in the main thread, while `serve()` uses ThreadingHTTPServer and authenticated handlers read the same Journal in request threads. Test a real authenticated HTTP request with --journal, not only an EmptyJournal or direct same-thread handler call. Use a safe per-request/worker connection and transactional design; do not blindly turn off thread checks without addressing concurrency.

Test ordinary and interrupted jobs with real service fixtures at normal/narrow widths. Independent usability remains unestablished; no V3 interview-count programme or invented customer adoption is required.

## 8. Public manifest: a template is not a bounded spending request

The current execution manifest lists deployment before the Safe/Role constructor dependencies are established; it leaves actual caller/payer, addresses, economic amount and numeric policy/gas limits unresolved. Its idempotency statement inherits the client mismatch. It omits the cleanup call from its inner-call list even while describing cleanup elsewhere.

Preserve it as a template. Produce an executable, internally ordered and bounded action manifest once local composition is correct. Resolve/predict any address dependencies explicitly, specify the verified route and finite proposed amounts/cost ceilings, and request only missing access/owner authorization at the actual boundary. Do not ask for secrets in chat or imply creation of a key authorizes public deployment/spending. Successful simulation alone is not proof of the actual broadcast caller/payer for every routing mode.

## 9. Execution order and stopping rule

1. Read and install the authoritative planning corpus and current review pointers. Record a requirement-to-runtime-artifact matrix, not a test-count completion rule.
2. Repair P03-C1–C4 and connect one genuine LOCAL native producer -> admitted action -> signature -> exact typed request -> controller effect -> durable/native result and recovery flow. Label offline transport/fault injection clearly.
3. Preserve the P04/P05 partial work. Finish genuinely independent services/preparation without claiming the missing P03 prerequisite or later phase acceptance. No substantive dependency is silently waived.
4. Prepare the correct bounded L10/public-action request. Stop for actual missing credentials, owner action, spending permission, or an observed execution limit after ready independent work is exhausted.
5. After the required actual P03 route is established under specific authorization, finish original P04/P05 against that route. Then run P06's fair comparison of complete workflows and original fault boundaries.

The existing continuous authorization remains in force. Do not end at a routine report with 'say the word'. Commit and push coherent fixes privately; retain public-action restrictions and independent acceptance pending. Do not manufacture a P06 result against a prototype while calling it the full Held workflow.

## Source pointers

Repository paths above are relative to `pvgirish/held-keeperhub` at the reviewed SHA. Key source URLs:
- https://github.com/pvgirish/held-keeperhub/blob/abc0fdd3e832538900045961574ccb2887734e07/adapter/held_adapter/execution/keeperhub.py
- https://github.com/pvgirish/held-keeperhub/blob/abc0fdd3e832538900045961574ccb2887734e07/adapter/held_adapter/execution/submit.py
- https://github.com/pvgirish/held-keeperhub/blob/abc0fdd3e832538900045961574ccb2887734e07/packages/core/held_core/journal.py
- https://github.com/pvgirish/held-keeperhub/blob/abc0fdd3e832538900045961574ccb2887734e07/test/contracts/HeldAuthority.t.sol
- https://github.com/pvgirish/held-keeperhub/blob/abc0fdd3e832538900045961574ccb2887734e07/console/run.py
- https://github.com/pvgirish/held-keeperhub/blob/abc0fdd3e832538900045961574ccb2887734e07/console/held_console/state.py
- https://github.com/pvgirish/held-keeperhub/blob/abc0fdd3e832538900045961574ccb2887734e07/console/held_console/app.py
- https://github.com/pvgirish/held-keeperhub/blob/abc0fdd3e832538900045961574ccb2887734e07/evidence/P03/execution-manifest.json
- https://docs.keeperhub.com/api/direct-execution

Source findings are not claims of successful exploitation, deployment, actual funds loss or a full security audit. Preserve the distinction between a function test, local composition, authenticated hosted behavior, public execution, independent review and customer value.
