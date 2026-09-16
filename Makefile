# Held — phase check targets. Real checks; a red gate is a red gate.
PY  ?= $(HOME)/venv312/bin/python
SDK ?= $(HOME)/src/sdk
export PY
export SDK

.PHONY: check-phase-00 check-phase-01 check-phase-02 check-phase-03-local check-manifests check-probe \
        check-baseline check-native-workflow gate-tests

check-phase-00:
	@rc=0; \
	$(MAKE) --no-print-directory gate-tests    || rc=1; \
	$(MAKE) --no-print-directory check-manifests || rc=1; \
	$(MAKE) --no-print-directory check-probe     || rc=1; \
	$(MAKE) --no-print-directory check-native-workflow || rc=1; \
	$(MAKE) --no-print-directory check-baseline  || rc=1; \
	echo "---"; \
	if [ $$rc -eq 0 ]; then echo "check-phase-00: PASS"; else echo "check-phase-00: FAIL (P00 incomplete)"; fi; \
	exit $$rc

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
