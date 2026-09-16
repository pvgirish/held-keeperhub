#!/usr/bin/env bash
# P04 acceptance: authority inventory, owner fencing, change and handover.
#
# Runs against the SAME real pinned Base-mainnet fixture as P02 -- a genuine 2-of-3 Safe
# 1.4.1, a real Zodiac Roles v2.1 module, real Morpho Blue and native USDC on an anvil
# fork. Nothing is mocked here; there is no adversarial stage in this phase.
#
# The fixture wiring is shared with P02 through test/contracts/HeldForkHarness.sol, so
# the two suites cannot drift apart.
set -uo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

rc=0
echo "=== P04: authority, fencing, change and handover on a Base-mainnet fork ==="
./fixtures/with_fork.sh bash -c '
  set -uo pipefail
  export PATH="$HOME/.foundry/bin:$PATH"
  for s in 01_deploy_safe_and_roles 02_enable_module_and_fund 03_scope_role \
           03b_bind_allowance_and_build_history; do
    bash ./fixtures/scripts/$s.sh >/tmp/held_p04_$s.log 2>&1 || { echo "fixture $s failed"; exit 1; }
  done
  . /tmp/held_fixture.env
  export HELD_SAFE="$SAFE" HELD_ROLES="$ROLES" HELD_ROLE_KEY="$ROLE_KEY" HELD_ALLOW_KEY="$ALLOW_KEY"
  echo "fixture: safe=$SAFE roles=$ROLES"
  forge test --fork-url "$HELD_BASE_RPC" --match-path "test/contracts/HeldAuthority.t.sol" -vv 2>&1 | tail -30
  exit ${PIPESTATUS[0]}
' || rc=1

echo
if [ $rc -eq 0 ]; then echo "check-phase-04: PASS"; else echo "check-phase-04: FAIL"; fi
exit $rc
