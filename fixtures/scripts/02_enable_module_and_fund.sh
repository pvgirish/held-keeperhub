#!/usr/bin/env bash
# P00 fixture step 2: enable the Roles module on the Safe (real 2-of-3 Safe tx) and fund with USDC.
set -uo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
R="${HELD_BASE_RPC:?run me through fixtures/with_fork.sh}"
. "${HELD_FIXTURE_OUT:-/tmp/held_fixture.env}"
USDC=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
PK1=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
PK2=0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d

echo "== enabling module $ROLES on safe $SAFE (2-of-3) =="
DATA=$(cast calldata "enableModule(address)" "$ROLES")
NONCE=$(cast call "$SAFE" "nonce()(uint256)" --rpc-url "$R" 2>/dev/null)
Z=0x0000000000000000000000000000000000000000
TXHASH=$(cast call "$SAFE" \
  "getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,uint256)(bytes32)" \
  "$SAFE" 0 "$DATA" 0 0 0 0 "$Z" "$Z" "$NONCE" --rpc-url "$R" 2>/dev/null)
echo "safe tx hash: $TXHASH  (nonce $NONCE)"

# two owner signatures over the Safe tx hash, concatenated in ascending owner order
S1=$(cast wallet sign --no-hash --private-key "$PK1" "$TXHASH" 2>/dev/null)
S2=$(cast wallet sign --no-hash --private-key "$PK2" "$TXHASH" 2>/dev/null)
# owner3 (0x3C44) > owner2 (0x7099) > owner1 (0xf39F)? sort by address ascending:
# 0x3C44... < 0x7099... < 0xf39F...  -> we signed with owner1 and owner2, so order is owner2 then owner1
SIGS="0x${S2#0x}${S1#0x}"
cast send "$SAFE" \
  "execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)" \
  "$SAFE" 0 "$DATA" 0 0 0 0 "$Z" "$Z" "$SIGS" \
  --private-key "$PK1" --rpc-url "$R" >/dev/null 2>&1
ENABLED=$(cast call "$SAFE" "isModuleEnabled(address)(bool)" "$ROLES" --rpc-url "$R" 2>/dev/null)
echo "module enabled: $ENABLED"
[ "$ENABLED" = "true" ] || { echo "ENABLE MODULE FAILED"; exit 1; }

echo "== funding the Safe with USDC on the fork =="
# find the USDC balance storage slot for the Safe, then set it directly (fork-local only)
for SLOT in 0 1 2 3 4 5 6 7 8 9; do
  KEY=$(cast index address "$SAFE" "$SLOT")
  cast rpc anvil_setStorageAt "$USDC" "$KEY" \
    0x0000000000000000000000000000000000000000000000000000000ba43b7400 --rpc-url "$R" >/dev/null 2>&1
  BAL=$(cast call "$USDC" "balanceOf(address)(uint256)" "$SAFE" --rpc-url "$R" 2>/dev/null | awk '{print $1}')
  if [ "${BAL:-0}" != "0" ]; then echo "usdc balance slot = $SLOT"; break; fi
done
echo "safe USDC balance: $(cast call "$USDC" "balanceOf(address)(uint256)" "$SAFE" --rpc-url "$R" 2>/dev/null)"
cast rpc anvil_setBalance "$SAFE" 0xde0b6b3a7640000 --rpc-url "$R" >/dev/null 2>&1
echo "safe ETH balance:  $(cast balance "$SAFE" --rpc-url "$R" 2>/dev/null)"

cat >> "${HELD_FIXTURE_OUT:-/tmp/held_fixture.env}" <<ENV
MODULE_ENABLED=$ENABLED
USDC_SLOT=${SLOT:-unknown}
ENV
echo "step 2 done"
