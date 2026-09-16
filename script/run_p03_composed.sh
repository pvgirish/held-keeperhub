#!/usr/bin/env bash
# The composed LOCAL run, in the order its dependencies require.
#
#   Pass 1 (fork)   : deploy the fixture and controller, publish the signing vector.
#                     Python cannot know the controller address before this.
#   Pass 2 (python) : real compiler -> admitted -> signed -> typed request -> calldata.
#   Pass 3 (fork)   : execute Held's OWN bytes against the real controller, publish the
#                     consumed[] reading.
#   Pass 4 (python) : reconcile the journal from that real reading, and prove recovery
#                     refuses to resend work that already executed.
#
# Passes 1 and 3 deploy the controller to the SAME address because each forge run starts
# from the same pinned fork block with the same deployer nonce. That is not assumed: pass
# 3's execution would fail signature verification if the address differed, since the
# EIP-712 domain separator commits to it.
#
# KeeperHub is NOT involved. The hosted route needs an organisation credential (L10) that
# does not exist, and is not simulated anywhere in this script.
set -uo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
PY="${PY:-$HOME/venv312/bin/python}"
rc=0

rm -f fixtures/generated/composed-call.json fixtures/generated/composed-result.json

./fixtures/with_fork.sh bash -c '
  set -uo pipefail
  export PATH="$HOME/.foundry/bin:$PATH"
  for s in 01_deploy_safe_and_roles 02_enable_module_and_fund 03_scope_role \
           03b_bind_allowance_and_build_history; do
    bash ./fixtures/scripts/$s.sh >/tmp/held_p03c_$s.log 2>&1 || { echo "fixture $s failed"; exit 1; }
  done
  . /tmp/held_fixture.env
  export HELD_SAFE="$SAFE" HELD_ROLES="$ROLES" HELD_ROLE_KEY="$ROLE_KEY" HELD_ALLOW_KEY="$ALLOW_KEY"

  echo "=== pass 1: publish the signing vector (controller address) ==="
  forge test --fork-url "$HELD_BASE_RPC" \
    --match-test test_WritesTheSigningVectorThePythonSignerMustReproduce -vv 2>&1 | tail -4
  [ "${PIPESTATUS[0]}" -eq 0 ] || exit 1

  echo "=== pass 2: build Held'"'"'s request from the admitted action ==="
  '"$PY"' tests/integration/test_p03_composed.py 2>&1 | grep -E "^ok|^FAIL|wrote|^all" || true
  [ -f fixtures/generated/composed-call.json ] || { echo "no composed call was built"; exit 1; }

  echo "=== pass 3: execute those bytes against the REAL controller ==="
  forge test --fork-url "$HELD_BASE_RPC" \
    --match-path "test/contracts/HeldComposed.t.sol" -vv 2>&1 | tail -8
  exit ${PIPESTATUS[0]}
' || rc=1

if [ $rc -eq 0 ]; then
  echo
  echo "=== pass 4: reconcile the journal from the real on-chain reading ==="
  "$PY" tests/integration/test_p03_composed.py || rc=1
fi

echo
if [ $rc -eq 0 ]; then
  echo "check-phase-03-composed: PASS (local composed run; KeeperHub/L10 NOT exercised)"
else
  echo "check-phase-03-composed: FAIL"
fi
exit $rc
