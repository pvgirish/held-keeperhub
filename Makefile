# Held — phase check targets. Real checks; a red gate is a red gate.
PY  ?= $(HOME)/venv312/bin/python
SDK ?= $(HOME)/src/sdk
export PY
export SDK

.PHONY: m1-cost check-plan-digests check-phase-00 check-phase-01 check-phase-02 check-phase-03-local check-phase-03 check-phase-03-composed check-l10-route-proof m1-prebroadcast-gate final-rehearsal mainnet-evidence-gate emit-evidence-templates stale-audit check-bootstrap-rehearsal check-phase-04 check-phase-05 check-manifests check-probe \
        check-baseline check-native-workflow gate-tests hero-demo clean-install submission-gate p06-comparison console-live freeze-candidate

check-phase-00:
	@rc=0; \
	$(MAKE) --no-print-directory check-plan-digests || rc=1; \
	$(MAKE) --no-print-directory gate-tests    || rc=1; \
	$(MAKE) --no-print-directory check-manifests || rc=1; \
	$(MAKE) --no-print-directory check-probe     || rc=1; \
	$(MAKE) --no-print-directory check-native-workflow || rc=1; \
	$(MAKE) --no-print-directory check-baseline  || rc=1; \
	echo "---"; \
	if [ $$rc -eq 0 ]; then echo "check-phase-00: PASS"; else echo "check-phase-00: FAIL (P00 incomplete)"; fi; \
	exit $$rc

## The authoritative plan corpus must not drift. Requirements live in docs/plan/, and a
## silent edit there would change what "done" means with nothing else noticing.
check-plan-digests:
	@$(PY) script/check_plan_digests.py

## meta-gate: the gates themselves must reject known-bad input
gate-tests:
	@$(PY) probes/checks/gate_tests.py

check-manifests:
	@$(PY) probes/checks/check_manifests.py

check-probe:
	@$(PY) probes/checks/check_probe.py

## P00 required work 6: native reconfiguration, the SDK's own recovery machinery,
## and the result-consumption boundary. Executes the REAL pinned SDK in-process.
check-native-workflow:
	@$(PY) probes/p00_native_workflow_probe.py

check-baseline:
	@$(PY) probes/checks/check_baseline.py

## P01: versioned types, operation identity, durable journal/outbox, result/ack.
check-phase-01:
	@$(PY) tests/core/run_tests.py

## P02: typed controller + native Roles enforcement, against the REAL pinned
## Safe/Roles/Morpho on a Base-mainnet fork. Builds the fixture and runs the suite
## inside ONE with_fork.sh invocation.
check-phase-02:
	@./script/run_p02_fork_tests.sh

## P04: authority inventory, owner fencing, change and handover, against the REAL
## pinned Safe/Roles/Morpho on the same Base-mainnet fork fixture as P02.
check-phase-04:
	@$(PY) tests/authority/test_authority_inventory.py
	@$(PY) tests/handover/test_handover_machine.py
	@./script/run_p04_fork_tests.sh

## The HERO WORKFLOW, end to end on the real fork: runner A active -> ambiguous
## operation -> handover refused -> reconcile -> owner fence -> inventory -> prepare B
## -> owner activation -> consumption preserved -> A refused -> B continues.
## REAL LOCAL FORK evidence. Not public-chain evidence.
hero-demo:
	@./script/run_hero_demo.sh

## P05: the console in REAL mode against a live fork, and against dead sources.
console-live:
	@./script/run_console_live_check.sh

## P06: the HELD half of the frozen handover comparison, measured on the fork against
## the native half in docs/baseline/native-measurements.json.
p06-comparison:
	@./script/run_p06_comparison.sh

## P07: can somebody else pick this up? Clones into an isolated directory and checks
## submodules, portability, committed secrets, documented environment and the gates that
## need no fork. External prerequisites (Foundry, CPython 3.12, the pinned SDK) are
## documented, not verified here.
clean-install:
	@$(PY) script/clean_install_check.py

## Freeze a pre-release candidate with explicit revision semantics.
freeze-candidate:
	@$(PY) script/freeze_candidate.py

## P08: the deterministic submission gate. Mandatory items are not waived by strong
## engineering, and readiness is not authorization.
submission-gate:
	@$(PY) script/submission_gate.py

## P05: the private operator console -- the four operator jobs, authentication and
## privacy, understandable owner approval, and the recovery export.
check-phase-05:
	@$(PY) tests/integration/test_p05_console.py
	@$(PY) tests/integration/test_p05_live_views.py

## P03 LOCAL HALF ONLY: native ActionBundle interception and envelope binding.
## This does NOT establish the hosted KeeperHub route. That gate needs an
## authenticated organisation caller/payer (L10) and is neither stubbed nor simulated.
##
## The signing check reproduces a vector the FORK suite writes
## (fixtures/generated/signing-vector.json), so check-phase-02 must have run against a
## live fork at least once. It fails loudly rather than skipping if the vector is absent.
check-phase-03-local:
	@$(PY) tests/integration/test_p03_interception.py
	@$(PY) tests/integration/test_p03_native_bundle.py
	@$(PY) tests/integration/test_p03_signing.py
	@$(PY) tests/integration/test_p03_keeperhub.py
	@$(PY) tests/integration/test_p03_submit.py
	@$(PY) tests/integration/test_p03_recovery.py
	@$(PY) tests/integration/test_p03_native_checkpoint.py
	@$(PY) tests/integration/test_p03_bootstrap_collector.py
	@$(PY) tests/integration/test_p03_broadcast_capability.py
	@$(PY) tests/integration/test_m1_prebroadcast_gate.py
	@$(PY) tests/integration/test_mainnet_evidence_gate.py

## P03 required work 6, REHEARSAL: the bounded bootstrap checklist collected manually
## against the FORK fixture. Not public-Safe activation evidence and not the P04
## automated authority service. Exits non-zero if any section is INCOMPLETE.
check-bootstrap-rehearsal:
	@./script/collect_bootstrap_evidence.sh

## The ONE target in this repository that talks to the real KeeperHub organisation route
## with a real credential. It performs an authenticated GET /api/keys: it broadcasts
## nothing, deploys nothing and spends nothing, and there is no path in it that can
## submit a contract call.
##
## It establishes that the credential is accepted and WHICH SCOPES it carries. It does
## NOT establish L10 (that needs a dry run against a deployed controller) and it does NOT
## establish M1 (a real transaction). Requires $HELD_KEEPERHUB_API_KEY and egress.
check-l10-route-proof:
	@$(PY) script/collect_route_proof.py

## The gate on the ONE irreversible action in this project: the M1 executeSupply
## broadcast. It judges the PREPARED request -- chain 8453, the declared controller, a
## supported entry point, arguments that re-encode to the signed calldata -- together with
## the executor the controller will accept and whether the configured credential can
## broadcast at all. It fails closed: an unevaluable check is BLOCKED and BLOCKED exits
## non-zero exactly as FAIL does.
##
## It cannot broadcast. NoBroadcastTransport refuses, at the wire boundary, any contract
## call that is not strictly simulate=true and any request carrying an Idempotency-Key,
## and NoBroadcastClient does not implement broadcast(). 26 regression tests hold those
## refusals (tests/integration/test_m1_prebroadcast_gate.py, in check-phase-03-local).
##
##   make m1-prebroadcast-gate ARGS="--journal PATH --attempt ID"
m1-prebroadcast-gate:
	@$(PY) script/m1_prebroadcast_gate.py $(ARGS)

## The FINAL M1 ceremony, rehearsed end to end on a fresh pinned Base fork with the FINAL
## identities: the three real owners at threshold 2, runner B, KeeperHub's managed signer,
## saltNonce 20260918. Every owner act goes through a real 2-of-3 execTransaction using
## Safe's pre-validated signature form after approveHash -- no owner private key is used,
## requested or held. Deploys nothing publicly, funds nothing, broadcasts nothing.
## REAL LOCAL FORK evidence. Not a public-chain result and never promotable to one.
final-rehearsal:
	@./script/run_final_rehearsal.sh

## Find the contradictions a reader would find first: broken paths and make targets,
## claims of absence that are now false, grade inflation, stale test counts, future dates.
## Exits non-zero on any finding -- a contradiction is not a warning.
stale-audit:
	@$(PY) script/stale_audit.py

## The evidence pack for the public execution, and the gate that keeps it honest.
## Every labelled record is checked; a record claiming PUBLIC MAINNET VERIFIED is re-read
## from a PUBLIC Base RPC and refused unless the transaction is really in Base's history.
## A fork record therefore cannot satisfy a mainnet claim, however it is labelled.
## Reads only. Deploys nothing, funds nothing, broadcasts nothing.
mainnet-evidence-gate:
	@$(PY) script/mainnet_evidence_gate.py

## (Re)write the fill-on-execution templates. They ship labelled PREPARED with FILL:
## sentinels; a template is never evidence.
emit-evidence-templates:
	@$(PY) script/mainnet_evidence_gate.py --emit

## Cost the M1 mainnet ceremony by RUNNING it against the pinned fork and reading gasUsed
## out of the receipts, then pricing that against live Base fees and the on-chain Chainlink
## ETH/USD feed. `evidence/P03/public-action-request.json` requires a finite, non-guessed
## gas ceiling before the public execution may be requested; this is how it stops being a
## guess. Nothing is deployed publicly and nothing is spent.
## Both halves are measured. The ceremony is what the OWNER EOA pays; the one executeSupply
## is what KEEPERHUB's wallet pays, and it is a separate script because it needs the
## composed run's own bytes rather than the fixture ceremony. The pricing step reads both
## out of evidence/P03/mainnet-gas-measurement.json, so it must come last.
##
## Needs HELD_PRICE_MODE=testing-only, because measuring executeSupply runs the composed
## producer to build the bytes it measures.
m1-cost:
	@./script/measure_mainnet_gas.sh
	@./script/measure_execute_supply_gas.sh

## The composed LOCAL run: real compiler -> admitted -> signed -> typed request ->
## executed by the REAL controller on the fork -> journal reconciled from that reading.
check-phase-03-composed:
	@./script/run_p03_composed.sh

## The phase prompt names this gate `check-phase-03`. It is NOT satisfied: the required
## composed hosted execution is blocked on L10. This alias runs every local check and
## then says so, so that invoking the prompt's own command cannot read as a pass.
check-phase-03:
	@$(MAKE) --no-print-directory check-phase-03-local
	@$(MAKE) --no-print-directory check-phase-03-composed
	@echo "---"
	@echo "check-phase-03: INCOMPLETE — local half passes; the required KeeperHub public"
	@echo "                execution (L10) has not been performed and is not simulated."
	@exit 1
