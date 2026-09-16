#!/usr/bin/env bash
# P00 fixture step 3: scope the operating role to Morpho supply/withdraw on the USDC market,
# set the NON-REFILLING allowance to 50,000 with 20,000 remaining (= 30,000 already used),
# and assign Runner A. All owner actions go through the real 2-of-3 Safe.
set -uo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
R="${HELD_BASE_RPC:?run me through fixtures/with_fork.sh}"
. "${HELD_FIXTURE_OUT:-/tmp/held_fixture.env}"
MORPHO=0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb
PK1=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
PK2=0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d
Z=0x0000000000000000000000000000000000000000
ROLE_KEY=$(cast format-bytes32-string "held-operator-v1")
ALLOW_KEY=$(cast format-bytes32-string "held-supply-cap")
echo "role key:  $ROLE_KEY"
echo "allow key: $ALLOW_KEY"

# run one owner action through the Safe with two signatures
safe_exec() { # $1 target  $2 calldata
  local NONCE TXH S1 S2 SIGS
  NONCE=$(cast call "$SAFE" "nonce()(uint256)" --rpc-url "$R" 2>/dev/null)
  TXH=$(cast call "$SAFE" \
    "getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,uint256)(bytes32)" \
    "$1" 0 "$2" 0 0 0 0 "$Z" "$Z" "$NONCE" --rpc-url "$R" 2>/dev/null)
  S1=$(cast wallet sign --no-hash --private-key "$PK1" "$TXH" 2>/dev/null)
  S2=$(cast wallet sign --no-hash --private-key "$PK2" "$TXH" 2>/dev/null)
  SIGS="0x${S2#0x}${S1#0x}"
  cast send "$SAFE" \
    "execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)" \
    "$1" 0 "$2" 0 0 0 0 "$Z" "$Z" "$SIGS" --private-key "$PK1" --rpc-url "$R" --json 2>/dev/null \
    | python3 -c 'import json,sys;r=json.load(sys.stdin);print(r["transactionHash"],r["status"])' 2>/dev/null
}

echo "== 3a assign Runner A to the role =="
safe_exec "$ROLES" "$(cast calldata "assignRoles(address,bytes32[],bool[])" "$RUNNER_A" "[$ROLE_KEY]" "[true]")"
echo "   member? $(cast call "$ROLES" "isModuleEnabled(address)(bool)" "$RUNNER_A" --rpc-url "$R" 2>/dev/null)"

echo "== 3b scope the target: Morpho =="
safe_exec "$ROLES" "$(cast calldata "scopeTarget(bytes32,address)" "$ROLE_KEY" "$MORPHO")"

echo "== 3c set a NON-REFILLING allowance: balance 20000 USDC, refill 0, period 0 =="
# setAllowance(key, balance, maxRefill, refill, period, timestamp)
safe_exec "$ROLES" "$(cast calldata "setAllowance(bytes32,uint128,uint128,uint128,uint64,uint64)" \
  "$ALLOW_KEY" 20000000000 20000000000 0 0 0)"
echo "   allowance: $(cast call "$ROLES" "allowances(bytes32)(uint128,uint128,uint128,uint64,uint64)" "$ALLOW_KEY" --rpc-url "$R" 2>/dev/null | tr '\n' ' ')"

cat >> "${HELD_FIXTURE_OUT:-/tmp/held_fixture.env}" <<ENV
ROLE_KEY=$ROLE_KEY
ALLOW_KEY=$ALLOW_KEY
ENV
echo "step 3 attempted - see readbacks above"
