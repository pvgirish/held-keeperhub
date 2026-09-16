#!/usr/bin/env bash
# P02 acceptance, in TWO clearly separated evidence classes.
#
#   Stage 0 — PROPERTY/FUZZ, local. Checks the controller against an INDEPENDENT
#             reference predicate across the input space, not just at chosen points.
#
#   Stage 1 — ADVERSARIAL, local, no fork. Labelled hostile mock fixtures for branches
#             that well-behaved contracts cannot reach: reentrancy, an ERC20 returning
#             false, and cleanup failing AFTER the economic action ran. No result here
#             may be described as native USDC / real Roles / real Morpho behaviour.
#
#   Stage 2 — REAL PINNED ROUTE, on a Base-mainnet fork, on top of the genuine 2-of-3
#             Safe + Zodiac Roles fixture built by fixtures/scripts/01..03b.
#
# They are run separately on purpose: P02 asks for unit/property tests AND realistic fork
# tests, not for every adversarial fixture to run under --fork-url.
#
# There is also an unresolved combined-configuration failure. ESTABLISHED: the adversarial
# suite passes standalone; the real-route suite passes on the fork; the combined
# configuration fails, with forge falling back to `VM::deployCode` for the adversarial test
# contract and the subsequent call reverting with zero gas (trace in
# evidence/P02/adversarial-fork-trace.txt). NOT ESTABLISHED: the precise cause. The
# executor's diagnosis is a harness/test-contract-size interaction rather than a controller
# defect, but no minimal reproduction has been built, so that remains a diagnosis rather
# than a proven root cause. Both stages build from the same controller source and compiler
# settings, and failure in EITHER stage fails this command.
set -uo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

rc=0

echo "=== stage 0: property / fuzz suite (local, reference-predicate equivalence) ==="
forge test --match-path "test/contracts/property/*" -vv 2>&1 | tail -12 || rc=1
[ "${PIPESTATUS[0]:-0}" -eq 0 ] || rc=1

echo
echo "=== stage 1: adversarial fixtures (local, NOT the production profile) ==="
forge test --match-path "test/contracts/adversarial/*" -vv 2>&1 | tail -20 || rc=1
[ "${PIPESTATUS[0]:-0}" -eq 0 ] || rc=1

echo
echo "=== stage 2: real pinned Safe / Roles / Morpho on a Base-mainnet fork ==="
./fixtures/with_fork.sh bash -c '
  set -uo pipefail
  export PATH="$HOME/.foundry/bin:$PATH"
  for s in 01_deploy_safe_and_roles 02_enable_module_and_fund 03_scope_role \
           03b_bind_allowance_and_build_history; do
    bash ./fixtures/scripts/$s.sh >/tmp/held_p02_$s.log 2>&1 || { echo "fixture $s failed"; exit 1; }
  done
  . /tmp/held_fixture.env

  # The fixture leaves the NATIVE lineage in place (30,000 consumed). The tests install a
  # SEPARATE Held lineage on top and start its counters at zero; the native history is
  # deliberately not imported (V4 §6).
  export HELD_SAFE="$SAFE"
  export HELD_ROLES="$ROLES"
  export HELD_ROLE_KEY="$ROLE_KEY"
  export HELD_ALLOW_KEY="$ALLOW_KEY"
  echo "fixture: safe=$SAFE roles=$ROLES"

  forge test --fork-url "$HELD_BASE_RPC" --match-path "test/contracts/HeldController.t.sol" -vv 2>&1 | tail -40
  exit ${PIPESTATUS[0]}
' || rc=1

echo
if [ $rc -eq 0 ]; then echo "check-phase-02: PASS (all three stages)"; else echo "check-phase-02: FAIL"; fi
exit $rc
