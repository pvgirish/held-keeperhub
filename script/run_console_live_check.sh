#!/usr/bin/env bash
set -uo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
HERE="$(cd "$(dirname "$0")/.." && pwd)"; cd "$HERE"
PY="${PY:-$HOME/venv312/bin/python}"
./fixtures/with_fork.sh bash -c '
  set -uo pipefail
  export PATH="$HOME/.foundry/bin:$PATH"
  for s in 01_deploy_safe_and_roles 02_enable_module_and_fund 03_scope_role \
           03b_bind_allowance_and_build_history 03d_deploy_paused_controller; do
    bash ./fixtures/scripts/$s.sh >/tmp/held_cl_$s.log 2>&1 || { echo "fixture $s failed"; exit 1; }
  done
  . /tmp/held_fixture.env
  # NOTE: no apostrophes in this block -- single-quoted bash -c string.
  export HELD_SAFE="$SAFE" HELD_ROLES="$ROLES" HELD_CONTROLLER="$HELD_CONTROLLER"
  export HELD_ROLE_KEY="$ROLE_KEY" HELD_ALLOW_KEY="$ALLOW_KEY"
  export HELD_CONSOLE_SECRET=local-check-secret-not-a-real-one
  exec '"$PY"' script/console_live_check.py'
