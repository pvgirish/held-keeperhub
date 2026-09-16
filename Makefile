# Held — phase check targets. Real checks; a red gate is a red gate.
PY  ?= $(HOME)/venv312/bin/python
SDK ?= $(HOME)/src/sdk
export PY
export SDK

.PHONY: check-plan-digests check-phase-00 check-phase-01 check-phase-02 check-phase-03-local check-phase-03 check-phase-03-composed check-phase-04 check-phase-05 check-manifests check-probe \
        check-baseline check-native-workflow gate-tests

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
	@./script/run_p04_fork_tests.sh

## P05: the private operator console -- the four operator jobs, authentication and
## privacy, understandable owner approval, and the recovery export.
check-phase-05:
	@$(PY) tests/integration/test_p05_console.py

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
