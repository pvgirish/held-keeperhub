#!/usr/bin/env bash
# Deploy AND INSTALL the Held controller PAUSED onto the fork, through the tested route.
#
# What this used to do, and why it was wrong: it deployed the controller, sent
# `enableModule(controller)` to the Safe, and stopped. That is not the installation Held
# runs under. It assigned the controller to NEITHER Zodiac Role, configured no condition
# trees, set none of the five native budgets and never retired the previous runner. Worse,
# it derived its own budget keys here in bash ("held.restoration.role" and friends) while
# the tested installation used HeldInstall's, so the controller it deployed was bound to
# budget keys that nothing on the Roles side ever configured.
#
# The bootstrap checklist then inspected THAT. So the checklist verified a permission path
# the tests never exercised, and the tested path was never verified by the checklist.
#
# Now the whole thing is one owner act in script/solidity/InstallPausedHeld.s.sol, which
# calls the SAME HeldInstall.install() that test/contracts/HeldForkHarness.sol calls. If
# the two diverge, the P02 fork suite fails.
#
# It is deployed and NOT activated: V4 §6 requires a paused, never-active controller at
# epoch 0 with zero consumption before initial activation. Nothing here activates it.
set -euo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
. /tmp/held_fixture.env

# anvil account #1 — the P00 native runner, retired as part of installing the new lineage.
RUNNER_A=0x70997970C51812dc3A010C7d01b50e0d17dc79C8

cd "$(dirname "$0")/../.."

# The Safe is the owner of the Roles module and the avatar; every call in the script is an
# owner act, so the whole thing broadcasts as the impersonated Safe.
cast rpc anvil_impersonateAccount "$SAFE" --rpc-url "$HELD_BASE_RPC" >/dev/null
cast rpc anvil_setBalance "$SAFE" 0xDE0B6B3A7640000 --rpc-url "$HELD_BASE_RPC" >/dev/null

HELD_SAFE="$SAFE" HELD_ROLES="$ROLES" HELD_ROLE_KEY="$ROLE_KEY" HELD_ALLOW_KEY="$ALLOW_KEY" \
HELD_RETIRE_MEMBER="$RUNNER_A" \
  forge script script/solidity/InstallPausedHeld.s.sol:InstallPausedHeld \
    --rpc-url "$HELD_BASE_RPC" --broadcast --unlocked --sender "$SAFE" \
    >/tmp/held_install_paused.log 2>&1 || { tail -30 /tmp/held_install_paused.log; exit 1; }

MANIFEST=fixtures/generated/held-install-manifest.json
[ -f "$MANIFEST" ] || { echo "the install script wrote no manifest"; exit 1; }
CONTROLLER=$(python3 -c "import json;print(json.load(open('$MANIFEST'))['controller'])")
[ -n "$CONTROLLER" ] || { echo "no controller address in the manifest"; exit 1; }

echo "export HELD_CONTROLLER=$CONTROLLER" >> /tmp/held_fixture.env
echo "export HELD_INSTALL_MANIFEST=$(pwd)/$MANIFEST" >> /tmp/held_fixture.env

ACTIVE=$(cast call "$CONTROLLER" 'active()(bool)' --rpc-url "$HELD_BASE_RPC")
EPOCH=$(cast call "$CONTROLLER" 'epoch()(uint64)' --rpc-url "$HELD_BASE_RPC")
echo "paused controller installed at $CONTROLLER (active=$ACTIVE epoch=$EPOCH)"
echo "declared installation manifest: $MANIFEST"
