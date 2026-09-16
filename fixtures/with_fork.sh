#!/usr/bin/env bash
# Run a command against a pinned Base-mainnet anvil fork.
#
# WHY A WRAPPER: on this device each shell call runs in its own network
# namespace with --die-with-parent, so a background anvil CANNOT survive
# between calls. The fork must be started, used and torn down inside ONE
# invocation. This script makes that reproducible.
#
#   ./fixtures/with_fork.sh <command...>
# The fork RPC is exported as HELD_BASE_RPC.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$HERE/fork.env"
export PATH="$HOME/.foundry/bin:$PATH"
PORT="${HELD_FORK_PORT:-8545}"

anvil --fork-url "$BASE_RPC" --fork-block-number "$FORK_BLOCK" \
      --port "$PORT" --host 127.0.0.1 --silent &
ANVIL_PID=$!
cleanup() { kill "$ANVIL_PID" 2>/dev/null; wait "$ANVIL_PID" 2>/dev/null; }
trap cleanup EXIT

RPC="http://127.0.0.1:$PORT"
for _ in $(seq 1 25); do
  sleep 3
  cast chain-id --rpc-url "$RPC" >/dev/null 2>&1 && break
done

# refuse to hand over a fork that is not what fork.env pins
got_chain=$(cast chain-id --rpc-url "$RPC" 2>/dev/null)
got_block=$(cast block-number --rpc-url "$RPC" 2>/dev/null)
if [ "$got_chain" != "$CHAIN_ID" ]; then
  echo "FORK REFUSED: chain id $got_chain != pinned $CHAIN_ID" >&2; exit 1; fi
if [ "$got_block" != "$FORK_BLOCK" ]; then
  echo "FORK REFUSED: block $got_block != pinned $FORK_BLOCK" >&2; exit 1; fi
code_len=$(cast code "$MORPHO" --rpc-url "$RPC" 2>/dev/null | wc -c)
if [ "$code_len" -lt 1000 ]; then
  echo "FORK REFUSED: Morpho has no code at $MORPHO (len $code_len)" >&2; exit 1; fi

echo "fork ready: chain $got_chain, block $got_block, morpho code ${code_len} chars" >&2
export HELD_BASE_RPC="$RPC"
"$@"
