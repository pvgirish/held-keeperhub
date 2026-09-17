# Held: review of 67eed71 and bounded continuation

Reviewed revision: `67eed7193f5fe9472d8c2f1876dfb10c7e400f9a`.
Repository: `pvgirish/held-keeperhub`, private. This packet does not authorize repository writes by the reviewer, public actions, credential use or spending.

## Decision

Preserve the commit. Several prior failures are repaired and should not be repeated. The two advertised contracts are nevertheless not complete: native decision recovery still has unenforced boundaries, and the bootstrap rehearsal does not verify the complete controller-only Roles installation required for initial activation.

This is a continuation of P03 required work 4 and 6, not a new product specification or a request for the full P04 service. The source of truth remains the unchanged V4/A1 corpus and continuous-execution directive now in `docs/plan/`. Check the live tree for subsequent fixes before applying this review.

## Evidence and limits of this review

The reviewer read the committed adapter, collector, deployment script, composed test, fork harness and generated bootstrap record through the connected GitHub tool. The complete `native_result.py` and `collect_bootstrap_evidence.py` were recovered from the tool responses and matched to Git blob hashes before execution:

- Native adapter: `6b3299a0de956e076b59183c9a570105a2a34310`.
- Collector: `637f1717b9b2b55ad9f05388b6eff03eb46a9b9e`.

Two scripts in this packet execute those exact files. There are 12 native-adapter cases and 12 collector cases. The adapter tests use real temporary SQLite transactions/close-and-reopen with a synthetic journal dependency and synthetic machine. The collector tests replace `subprocess.run` with scripted `cast` responses and isolate filesystem writes in temporary directories. They do not run the actual Almanak SDK, production Held Journal, Forge, a fork or RPC. No key, signer, provider call or transaction is used. They establish the displayed control flow, not public deployments, financial effects or a full security audit.

## Confirmed corrections: preserve

The native tests demonstrate identical binding reopen, conflict on changed identity/type, rejection of machine B before mutation under an A binding, no replacement machine for CONFIRMED/UNKNOWN/DISPATCHED without a native snapshot, correct reopen of a matching completed/acked snapshot, and inability of the separate verification connection to see an uncommitted snapshot. The terminal-snapshot-without-ack case also blocks.

Collector controls now reject an unreadable guard, foreign Roles owner, wrong chain, malformed grant mapping response, active controller and missing controller. The history-derived candidate control reaches mapping readback and refuses an authorized external address. Every executed `call` and `storage` request in these cases carries the observation block.

Do not revert or redo those repairs.

## N: finish the native recovery contract

### N1. Enforce dirty-object authority through the public decision method

`NativeStateMachineConsumer.needs_execution()` still calls `self.machine.step()` directly. It does not use `require_authoritative()` or a lifecycle distinction for an object mutated by a failed apply.

Executed case: a valid identity-bound apply advances the synthetic machine, then the surrounding SQL transaction rolls back. There is no durable snapshot; `_authoritative` is false. Nevertheless, `needs_execution()` returns a decision rather than refusing the dirty object.

Do not simply require a committed COMPLETED snapshot before every initial call: a legitimate, clean PREPARING/VALIDATING machine must still be usable under its bound pre-dispatch lifecycle. Distinguish clean initial work from dirty/uncommitted post-apply state, and make the enforcement unavoidable at the entry point used by the running adapter. After persistence failure, discard/restore/recover using the durable state; do not let the caller accidentally reuse the mutated machine.

### N2. Validate the checkpoint relationship during restore, not only apply

`restore()` only checks that a terminal snapshot has some acknowledgement and some decision binding. It does not compare the snapshot's `held_bound_decision`/native identity to the binding, nor does `complete` require a matching authoritative operation/result relationship.

Executed inconsistent-checkpoint case: operation O is CONFIRMED and bound to A; a deliberately constructed committed snapshot contains B plus a COMPLETED acknowledgement. `restore()` reports `intent_id=A`, `complete=True`, `inconsistent=[]` and no work required. This is a recovery/import-consistency test, not proof the new write-once binding API creates that mismatch normally.

Executed missing-history case: there is a native binding but no durable operation row; `restore(..., build_machine=...)` builds a machine and returns work-needed. Lost local history must not silently turn into permission for fresh work. Handle the supported tombstone/recovery-index cases explicitly; block evidence gaps rather than inventing an operation.

Validate the operation, bound decision identity/type, snapshot identity, actual acknowledgement/result identity and any permitted terminal/tombstone case coherently. Use the existing supported scope and retention contract. Do not smooth an inconsistent record into a completed marker.

### N3. Bind the producer before dispatch in the actual composed lifecycle

Source review of `tests/integration/test_p03_composed.py` still finds a new native machine created in the later test named “the producing native decision is BOUND...”, after the request-construction and same-journal reconciliation tests. Reading a requirement into a test's docstring does not change execution order.

The fixed binding helper is useful, but the original producer must create or reopen one stable decision BEFORE its work is admitted/claimed. Use the actual produced bundle/decision binding, the same operation and durable journal through delivery, and a fresh execution context for restart. Preserve the economic bytes and current EIP-712 scope checks.

Completion evidence: one trace, with stable decision ID and operation ID recorded before any submit; actual native consumer delivery for that bound decision; failed post-advance persistence blocks dirty reuse; pre-commit interruption remains recoverable; post-commit reopen returns completed without constructing economic work; deliberately inconsistent or missing recovery records block. Keep the completed-marker design where appropriate. A general SDK deserializer or full hosted strategy scheduler is not requested.

## B: finish the initial-activation rehearsal

### B1. The deployment helper wires a different permission path from the tested route

`fixtures/scripts/03d_deploy_paused_controller.sh` constructs the controller and then sends `enableModule(controller)` directly to the Safe. It does not assign the controller to either Zodiac Role, configure restoration/normal condition trees, set all five native budgets or retire the legacy native role member.

That differs from the existing, tested `HeldForkHarness.setUp()`, which assigns the controller to the normal and restoration Roles, revokes the old runner's Role membership, applies the tight supply/withdraw/approval conditions and configures all five amount/count allowances.

Enabling a contract directly as a Safe module is not equivalent to making it a member of the intended restricted Zodiac Roles. The current controller has typed entry points; this review does NOT demonstrate exploitation of an arbitrary-call bypass. It does establish that this installation is not the intended controller-only Roles route and that the checklist has not verified that route.

Reuse/export the existing tested installation configuration into a local pre-activation deployment path. Keep the controller paused. Record the declared candidate terms separately from currently zero/default controller policy. Do not copy native historical consumption into Held. Keep the native P00 baseline untouched.

### B2. The collector still checks one quota, not the full declared installation

The current collector reads only the environment `ALLOW_KEY`. It does not read the controller's role/allowance keys, discover/verify both Roles' members and conditions, inspect all five native remaining budgets, or compare the intended market ID and lineage. Its five zeroed controller counters are not five native allowance checks.

The generated seven-section COMPLETE artifact still shows only `held-supply-cap` with 20,000 remaining from the old native history while Held's own counters are zero. Its identities section records Safe owners and Roles owner, not the selected runner/executor identities or an explicit incomplete candidate state.

P03's pre-activation collection must be based on the full intended installation/candidate configuration. Required missing configuration should be INCOMPLETE, not inferred. This does not mean deploy a full P04 authority service. A bounded manifest, real owner setup, deterministic readback and manual evidence are allowed.

Create a clause-to-evidence table using ALL original V4 §6/P03 item 6 obligations at once: implementation identity, owner/threshold, module path, guard/fallback profile, both Roles and members/conditions, all amount/count budgets, controller scope, grants/delegated spend paths, selected public identities and separately attested credential control. A field appearing in a report is not proof it is checked.

### B3. Remaining decision-parser failures reproduced

The exact unchanged collector returned `PERMITTED BY THIS CHECKLIST` for:

1. An unreviewed nonzero Safe fallback handler.
2. A readable unsupported Safe version (`0.0.0-unsupported`).
3. A successful `cast` process returning `not-a-valid-log-response`.
4. An allowance tuple whose balance is `not-a-number`.

The positive and previously fixed controls still behave correctly. Expected rejections follow the declared supported-profile and required usable-data contract. These tests do not establish that the actual Safe/Roles contracts returned those values.

Validate typed decoded values and supported implementations, not just non-None output. An unknown fallback implementation is not automatically allowed merely because its storage slot was readable. Preserve legitimate empty history, but distinguish it from malformed, incomplete or truncated log data.

### B4. Decode authorization history rather than scraping every word

The current collector requests all Morpho logs and regex-extracts every 32-byte hex word's last 20 bytes. The declared `SET_AUTH_TOPIC` is unused. It does not decode/filter the pinned authorization event, check the authorizer is this Safe, or validate structured event records. The committed artifact contains candidates that are visibly truncated market IDs, numeric data and other hashes, consistent with this implementation.

Broad over-collection may discover an authorized address, but it is not a validated interpretation of canonical authorization history. Switch to the pinned event ABI/topic, structured logs, actual Safe authorizer, creation-to-observation coverage and per-candidate mapping readback at the same block. Preserve provenance for every candidate, including known identities. Distinguish history success, completeness and compatible live grants; fail on required gaps. Include genuine event-shaped grant/revoke controls and unrelated-event controls.

For the dedicated public Safe later, collect against its own creation/installation history and finalized observation, not the fork's hardcoded lower bound. No public action is authorized now.

## Execution order and permissions

1. Read this review and reconcile it against the live branch. Preserve all pushed history and confirmed fixes.
2. Close N1–N3 using the actual production entry points/journal plus actual pinned native consumer. Use this packet's synthetic probes to reproduce/localize, not to replace integration evidence.
3. Correct the paused deployment wiring and complete B1–B4 with original-checklist coverage, live fork readbacks, typed history tests and positive controls. Do not require full P04 early; do not reopen P00's native comparison.
4. Re-run affected checks and the connected local trace; preserve observations, missing evidence and independent-review status separately. Reconcile the phase records and supersede erroneous COMPLETE verdicts without deleting history.
5. Commit and push coherent changes privately. Continue authorized, dependency-ready work. Stop only for actual missing access/permission or execution limits, not after each patch.

Request A remains one separately owner-authorized read-only credential check, not blanket credential use or full L10 satisfaction. No public deployment, funding, broadcast, publication, billing change, routing-hook change, deadline-driven product cut or redesign is authorized by this review.

## Reproduction

From the unzipped packet directory:

```sh
python test_native_checkpoint.py
python test_bootstrap_collector.py
```

The probes verify source Git blobs before loading/executing. They print observations and write `native_probe_results.json` / `collector_probe_results.json`. Their exit status is not a phase gate: they are reproductions of known behavior. Their baseline models do not prove a real valid installation; the executor must run the actual connected implementation.
