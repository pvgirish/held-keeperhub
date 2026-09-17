#!/usr/bin/env bash
# The hero workflow, against the REAL pinned Base-mainnet fork.
#
# EVIDENCE GRADE: REAL LOCAL FORK. An anvil fork has no finality and is not public. This
# demonstrates the handover mechanism; it is not a public-chain execution.
set -uo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
PY="${PY:-$HOME/venv312/bin/python}"

./fixtures/with_fork.sh bash -c '
  set -uo pipefail
  export PATH="$HOME/.foundry/bin:$PATH"
  for s in 01_deploy_safe_and_roles 02_enable_module_and_fund 03_scope_role \
           03b_bind_allowance_and_build_history 03d_deploy_paused_controller; do
    bash ./fixtures/scripts/$s.sh >/tmp/held_hero_$s.log 2>&1 \
      || { echo "fixture $s failed"; tail -20 /tmp/held_hero_$s.log; exit 1; }
  done
  . /tmp/held_fixture.env
  # Everything the live authority collection needs. The hero demo collects the bounded
  # inventory FOR REAL at the fence, so every input the collector reads must be present.
  # Missing them used to surface as a stale report being read off disk.
  # NOTE: no apostrophes in this block -- it lives inside a single-quoted bash -c string.
  export HELD_SAFE="$SAFE" HELD_ROLES="$ROLES" HELD_CONTROLLER="$HELD_CONTROLLER"
  export HELD_ROLE_KEY="$ROLE_KEY" HELD_ALLOW_KEY="$ALLOW_KEY"
  export HELD_INSTALL_MANIFEST="${HELD_INSTALL_MANIFEST:-}"
  export HELD_RUNNER="${HELD_RUNNER:-}" HELD_EXECUTOR="${HELD_EXECUTOR:-}"
  exec '"$PY"' script/hero_demo.py'
rc=$?
echo
if [ $rc -eq 0 ]; then
  echo "hero-demo: PASS (REAL LOCAL FORK; not public-chain evidence)"
else
  echo "hero-demo: FAIL"
fi
exit $rc
