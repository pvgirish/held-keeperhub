#!/usr/bin/env bash
# P00 fixture step 3b: bind the Morpho supply `assets` parameter to the allowance key,
# start from the ORIGINAL 50,000 budget, then build the 30,000 used history by REAL execution.
#
# CORRECTION (recorded): configuring balance=20,000 does NOT establish 30,000 successfully
# used. `balance` is unused allowance; it can be set by hand. The only honest way to reach
# "30,000 used" is to execute 30,000 of real supplies through the scoped route and watch the
# allowance fall 50,000 -> 20,000 by consumption.
set -uo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
R="${HELD_BASE_RPC:?run me through fixtures/with_fork.sh}"
. "${HELD_FIXTURE_OUT:-/tmp/held_fixture.env}"
MORPHO=0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb
USDC=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
PK1=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
PK2=0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d
PK_RUNNER_A=0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6
Z=0x0000000000000000000000000000000000000000
SUPPLY_SEL=0xa99aad89
APPROVE_SEL=0x095ea7b3
# market params for the pinned wstETH/USDC market
LOAN=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
COLL=0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452
ORACLE=0xD7A1abA119a236Fea5BBC5cAC6836465cbe9289A
IRM=0x46415998764C29aB2a25CbeA6254146D50D22687
LLTV=860000000000000000

safe_exec() { # $1 target $2 calldata -> prints "txhash status"
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
allowance_balance() {
  cast call "$ROLES" "allowances(bytes32)(uint128,uint128,uint128,uint64,uint64)" \
    "$ALLOW_KEY" --rpc-url "$R" 2>/dev/null | sed -n '4p' | awk '{print $1}'
}

echo "== 3b-1 reset the allowance to the ORIGINAL 50,000 budget =="
safe_exec "$ROLES" "$(cast calldata "setAllowance(bytes32,uint128,uint128,uint128,uint64,uint64)" \
  "$ALLOW_KEY" 50000000000 50000000000 0 0 0)" >/dev/null
echo "   allowance balance now: $(allowance_balance)"

echo "== 3b-2 scope supply(): bind param[1] assets to the allowance key =="
# AbiType: Static=1 Dynamic=2 Tuple=3 Calldata=5 | Operator: Pass=0 Matches=5 WithinAllowance=28
CV=$(cast abi-encode "f(bytes32)" "$ALLOW_KEY")
COND="[(0,5,5,0x),(0,3,0,0x),(0,1,28,$CV),(0,1,0,0x),(0,1,0,0x),(0,2,0,0x),(1,1,0,0x),(1,1,0,0x),(1,1,0,0x),(1,1,0,0x),(1,1,0,0x)]"
OUT=$(safe_exec "$ROLES" "$(cast calldata \
  "scopeFunction(bytes32,address,bytes4,(uint8,uint8,uint8,bytes)[],uint8)" \
  "$ROLE_KEY" "$MORPHO" "$SUPPLY_SEL" "$COND" 0 2>/dev/null)")
echo "   scopeFunction supply: ${OUT:-FAILED-TO-ENCODE}"

echo "== 3b-3 scope USDC.approve(), bounded to Morpho as the only spender =="
# scopeTarget sets Clearance.Function, so EVERY function must then be scoped explicitly.
# Scoping the target without scoping approve is why the first attempt reverted FunctionNotAllowed.
OUT2=$(safe_exec "$ROLES" "$(cast calldata "scopeTarget(bytes32,address)" "$ROLE_KEY" "$USDC" 2>/dev/null)")
echo "   scopeTarget USDC: ${OUT2:-FAILED}"
CV_MORPHO=$(cast abi-encode "f(address)" "$MORPHO")
COND_APPROVE="[(0,5,5,0x),(0,1,16,$CV_MORPHO),(0,1,0,0x)]"
OUT3=$(safe_exec "$ROLES" "$(cast calldata \
  "scopeFunction(bytes32,address,bytes4,(uint8,uint8,uint8,bytes)[],uint8)" \
  "$ROLE_KEY" "$USDC" "$APPROVE_SEL" "$COND_APPROVE" 0 2>/dev/null)")
echo "   scopeFunction approve (spender must be Morpho): ${OUT3:-FAILED}"

echo "== 3b-3b fund Runner A for gas =="
cast rpc anvil_setBalance "$RUNNER_A" 0xde0b6b3a7640000 --rpc-url "$R" >/dev/null 2>&1

echo "== 3b-4 build REAL history: execute 30,000 USDC of supply through the scoped route =="
for CHUNK in 10000000000 10000000000 10000000000; do
  A=$(cast calldata "approve(address,uint256)" "$MORPHO" "$CHUNK")
  cast send "$ROLES" "execTransactionWithRole(address,uint256,bytes,uint8,bytes32,bool)" \
    "$USDC" 0 "$A" 0 "$ROLE_KEY" true --private-key "$PK_RUNNER_A" --rpc-url "$R" >/dev/null 2>&1
  S=$(cast calldata "supply((address,address,address,address,uint256),uint256,uint256,address,bytes)" \
    "($LOAN,$COLL,$ORACLE,$IRM,$LLTV)" "$CHUNK" 0 "$SAFE" 0x)
  RES=$(cast send "$ROLES" "execTransactionWithRole(address,uint256,bytes,uint8,bytes32,bool)" \
    "$MORPHO" 0 "$S" 0 "$ROLE_KEY" true --private-key "$PK_RUNNER_A" --rpc-url "$R" --json 2>/dev/null \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])' 2>/dev/null)
  echo "   supply $CHUNK -> status ${RES:-ERR}   allowance now: $(allowance_balance)"
done

echo "== 3b-5 readback =="
echo "   allowance remaining: $(allowance_balance)   (expect 20000000000)"
echo "   safe USDC balance:   $(cast call "$USDC" "balanceOf(address)(uint256)" "$SAFE" --rpc-url "$R" 2>/dev/null | awk '{print $1}')"
echo "   morpho position:     $(cast call "$MORPHO" "position(bytes32,address)(uint256,uint128,uint128)" \
  0x13c42741a359ac4a8aa8287d2be109dcf28344484f91185f9a79bd5a805a55ae "$SAFE" --rpc-url "$R" 2>/dev/null | tr '\n' ' ')"
