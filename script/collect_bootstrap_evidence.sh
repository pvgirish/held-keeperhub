#!/usr/bin/env bash
# P03 required work 6 — the bounded bootstrap checklist, collected MANUALLY.
#
# REHEARSAL ONLY. This runs against the Base-mainnet FORK fixture. It is:
#   * NOT public-Safe activation evidence. The public installation will need its own
#     bounded collection and readback against its own addresses before any authorized
#     activation, and the fork's addresses and conclusions cannot stand in for it.
#   * NOT the P04 automated authority service. This is a hand-driven collection that P04
#     is later meant to automate and generalise. Nothing here claims that product exists.
#   * NOT finality evidence. An anvil fork has no meaningful finality; the block is the
#     pinned fork block and is labelled as such.
#
# V4 §6 requires, at ONE stated block, reported SEPARATELY:
#   1. Safe ownership/threshold/implementation; enabled modules, guard, fallback.
#   2. Roles implementation, role members, target/argument conditions, allowance state.
#   3. Morpho grants, confirmed by mapping readback.
#   4. Relevant token approvals and delegated spend paths.
#   5. Runner/executor identities, with attested control kept DISTINCT from chain facts.
#
# A section with unreadable or unrecognised data is INCOMPLETE and blocks activation.
# That is the point: the checklist must be able to fail.
set -uo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
OUT="evidence/P03/bootstrap-rehearsal.json"

./fixtures/with_fork.sh bash -c '
  set -uo pipefail
  export PATH="$HOME/.foundry/bin:$PATH"
  for s in 01_deploy_safe_and_roles 02_enable_module_and_fund 03_scope_role \
           03b_bind_allowance_and_build_history 03d_deploy_paused_controller; do
    bash ./fixtures/scripts/$s.sh >/tmp/held_boot_$s.log 2>&1 || { echo "fixture $s failed"; exit 1; }
  done
  . /tmp/held_fixture.env
  export HELD_SAFE="$SAFE" HELD_ROLES="$ROLES" HELD_ROLE_KEY="$ROLE_KEY" HELD_ALLOW_KEY="$ALLOW_KEY"
  export HELD_CONTROLLER="${HELD_CONTROLLER:-}"
  # The DECLARED installation and the SELECTED operating identities. Absent, the checklist
  # reports INCOMPLETE rather than inferring them from whatever it happens to read.
  export HELD_INSTALL_MANIFEST="${HELD_INSTALL_MANIFEST:-}"
  export HELD_RUNNER="${HELD_RUNNER:-}" HELD_EXECUTOR="${HELD_EXECUTOR:-}"
  exec "${PY:-$HOME/venv312/bin/python}" script/collect_bootstrap_evidence.py
' | tee /tmp/held_bootstrap.log

rc=${PIPESTATUS[0]}
echo
if [ $rc -eq 0 ]; then
  echo "bootstrap rehearsal: COMPLETE for every declared section (fork only)"
else
  echo "bootstrap rehearsal: INCOMPLETE — see $OUT. Activation would be blocked."
fi
exit $rc
