#!/usr/bin/env bash
# The final M1 ceremony rehearsal, on a FRESH pinned Base fork, with the FINAL identities.
#
# Nothing here reaches a public chain. The fork is started, used and torn down inside this
# one invocation (see fixtures/with_fork.sh for why it has to be).
#
# The runner key is passed into the child environment from a file OUTSIDE the repository
# and is never printed, logged or written to evidence. If the file is absent the rehearsal
# still runs and says loudly that the runner identity was substituted.
set -uo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

RUNNER_B_KEY_FILE="${HELD_RUNNER_B_KEY_FILE:-$HOME/.held/runner-b.key}"
if [ -r "$RUNNER_B_KEY_FILE" ]; then
  HELD_RUNNER_B_KEY="$(tr -d '[:space:]' < "$RUNNER_B_KEY_FILE")"
  export HELD_RUNNER_B_KEY
  echo "runner B key: loaded from $RUNNER_B_KEY_FILE (value not shown)"
else
  echo "runner B key: NOT AVAILABLE at $RUNNER_B_KEY_FILE — the rehearsal will substitute"
  echo "              an anvil account and mark runner_is_final_identity=false"
fi

./fixtures/with_fork.sh "${PY:-$HOME/venv312/bin/python}" script/final_fork_rehearsal.py
rc=$?
echo
if [ $rc -eq 0 ]; then
  echo "final fork rehearsal: PASS (REAL LOCAL FORK — not a public-chain result)"
else
  echo "final fork rehearsal: FAIL — see evidence/M1/final-fork-rehearsal.json"
fi
exit $rc
