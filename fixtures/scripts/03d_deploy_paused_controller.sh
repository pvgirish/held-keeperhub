#!/usr/bin/env bash
# Deploy the Held controller PAUSED onto the fork, so the bootstrap rehearsal inspects
# the actual installation rather than only the P00 native Safe/Roles fixture.
#
# It is deployed and NOT activated: V4 §6 requires a paused, never-active controller at
# epoch 0 with zero consumption before initial activation. Nothing here activates it.
set -euo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
. /tmp/held_fixture.env

MORPHO=0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb
USDC=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
COLL=0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452
ORACLE=0xD7A1abA119a236Fea5BBC5cAC6836465cbe9289A
IRM=0x46415998764C29aB2a25CbeA6254146D50D22687
LLTV=860000000000000000
LINEAGE=0x0000000000000000000000000000000000000000000000000000000000000011
DEPLOYER_PK=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80

MARKET_ID=$(cast keccak "$(cast abi-encode 'f(address,address,address,address,uint256)' \
  "$USDC" "$COLL" "$ORACLE" "$IRM" "$LLTV")")

# Distinct keys per budget dimension, as the controller's Keys struct requires.
RESTORE_ROLE=$(cast keccak "held.restoration.role")
WITHDRAW_KEY=$(cast keccak "held.normal.withdraw")
RESTORE_KEY=$(cast keccak "held.restoration.amount")
NORMAL_COUNT=$(cast keccak "held.normal.count")
RESTORE_COUNT=$(cast keccak "held.restoration.count")

OUT=$(forge create contracts/src/HeldController.sol:HeldController \
  --rpc-url "$HELD_BASE_RPC" --private-key "$DEPLOYER_PK" --broadcast \
  --constructor-args "$SAFE" "$ROLES" "$MORPHO" "$USDC" "$MARKET_ID" "$LINEAGE" \
  "($ROLE_KEY,$RESTORE_ROLE,$ALLOW_KEY,$WITHDRAW_KEY,$RESTORE_KEY,$NORMAL_COUNT,$RESTORE_COUNT)" \
  2>&1) || { echo "$OUT"; exit 1; }

CONTROLLER=$(echo "$OUT" | grep -oE "Deployed to: 0x[0-9a-fA-F]{40}" | awk '{print $3}')
[ -n "$CONTROLLER" ] || { echo "deploy failed"; echo "$OUT"; exit 1; }

# Enable it as a Safe module so the installation is the one the checklist inspects.
cast rpc anvil_impersonateAccount "$SAFE" --rpc-url "$HELD_BASE_RPC" >/dev/null
cast rpc anvil_setBalance "$SAFE" 0xDE0B6B3A7640000 --rpc-url "$HELD_BASE_RPC" >/dev/null
cast send "$SAFE" "enableModule(address)" "$CONTROLLER" \
  --from "$SAFE" --unlocked --rpc-url "$HELD_BASE_RPC" >/dev/null

echo "export HELD_CONTROLLER=$CONTROLLER" >> /tmp/held_fixture.env
echo "paused controller deployed at $CONTROLLER (active=$(cast call "$CONTROLLER" 'active()(bool)' --rpc-url "$HELD_BASE_RPC"))"
