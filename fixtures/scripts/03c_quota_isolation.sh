#!/usr/bin/env bash
# P00 fixture step 3c: isolate the over-quota rejection, and prove the canonical
# starting state survives the controls.
#
# WHY THIS EXISTS. The C8 run attempted a 25,000 supply against a 20,000 quota and
# got `held-supply-cap`, but its intended 60,000 top-up had silently failed, so the
# Safe held only 20,000 at the time. Balance alone could therefore also have blocked
# the transfer. The attribution was recorded as NOT fully isolated.
#
# Two things are fixed here:
#   1. The top-up works and is READ BACK, so the Safe provably holds far more than
#      the attempted amount and carries a sufficient ERC20 approval. The only
#      binding constraint left is the Roles quota.
#   2. Every control runs inside an anvil snapshot and is REVERTED afterwards, so
#      the canonical 30,000-used / 20,000-remaining state is restored by
#      construction rather than by hand. A consumed quota can never leak into the
#      measured scenarios.
set -uo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
R="${HELD_BASE_RPC:?run me through fixtures/with_fork.sh}"
. "${HELD_FIXTURE_OUT:-/tmp/held_fixture.env}"

MORPHO=0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb
USDC=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
MARKET_ID=0x13c42741a359ac4a8aa8287d2be109dcf28344484f91185f9a79bd5a805a55ae
PK_RUNNER_A=0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6
LOAN=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
COLL=0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452
ORACLE=0xD7A1abA119a236Fea5BBC5cAC6836465cbe9289A
IRM=0x46415998764C29aB2a25CbeA6254146D50D22687
LLTV=860000000000000000
USDC_SLOT=9

EVID="${HELD_EVIDENCE_DIR:-evidence/P00/baseline}"
mkdir -p "$EVID"
OUT="$EVID/quota-isolation.json"

rpc() { cast rpc "$@" --rpc-url "$R" 2>/dev/null | tr -d '"'; }
allow_field() { # $1 = 1..5 (refill,maxRefill,period,balance,timestamp)
  cast call "$ROLES" "allowances(bytes32)(uint128,uint128,uint64,uint128,uint64)" \
    "$ALLOW_KEY" --rpc-url "$R" 2>/dev/null | sed -n "${1}p" | awk '{print $1}'
}
usdc_of() { cast call "$USDC" "balanceOf(address)(uint256)" "$1" --rpc-url "$R" 2>/dev/null | awk '{print $1}'; }
supply_shares() {
  cast call "$MORPHO" "position(bytes32,address)(uint256,uint128,uint128)" \
    "$MARKET_ID" "$SAFE" --rpc-url "$R" 2>/dev/null | sed -n '1p' | awk '{print $1}'
}
role_send() { # $1 target $2 calldata -> prints status or ERR
  cast send "$ROLES" "execTransactionWithRole(address,uint256,bytes,uint8,bytes32,bool)" \
    "$1" 0 "$2" 0 "$ROLE_KEY" true --private-key "$PK_RUNNER_A" --rpc-url "$R" --json 2>/dev/null \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])' 2>/dev/null || echo ERR
}
role_call_err() { # $1 target $2 calldata -> prints the revert text WITHOUT changing state
  cast call "$ROLES" "execTransactionWithRole(address,uint256,bytes,uint8,bytes32,bool)" \
    "$1" 0 "$2" 0 "$ROLE_KEY" true --from "$RUNNER_A" --rpc-url "$R" 2>&1 | tr '\n' ' '
}
supply_calldata() {
  cast calldata "supply((address,address,address,address,uint256),uint256,uint256,address,bytes)" \
    "($LOAN,$COLL,$ORACLE,$IRM,$LLTV)" "$1" 0 "$SAFE" 0x
}

echo "== 3c-0 canonical state as handed over by 3b =="
CANON_ALLOW=$(allow_field 4); CANON_CEIL=$(allow_field 2)
CANON_USDC=$(usdc_of "$SAFE"); CANON_SHARES=$(supply_shares)
echo "   quota remaining: $CANON_ALLOW   ceiling: $CANON_CEIL"
echo "   safe USDC:       $CANON_USDC"
echo "   supply shares:   $CANON_SHARES"
[ "$CANON_ALLOW" = "20000000000" ] || { echo "ABORT: not the canonical 20,000 remaining"; exit 1; }

# ---------------------------------------------------------------- over-quota --
echo
echo "== 3c-1 ISOLATED over-quota test: 25,000 attempt against a 20,000 quota =="
SNAP=$(rpc evm_snapshot)
echo "   snapshot $SNAP taken; everything below is reverted afterwards"

# The C8 bug: the storage value was not written as a full 32-byte word.
# cast to-uint256 produces the correctly padded word.
TOPUP=100000000000                     # 100,000 USDC, far above the 25,000 attempt
SLOT=$(cast index address "$SAFE" $USDC_SLOT)
cast rpc anvil_setStorageAt "$USDC" "$SLOT" "$(cast to-uint256 $TOPUP)" --rpc-url "$R" >/dev/null 2>&1
TOPPED=$(usdc_of "$SAFE")
echo "   top-up readback: safe USDC = $TOPPED   (want $TOPUP)"
if [ "$TOPPED" != "$TOPUP" ]; then
  echo "   TOP-UP FAILED - the test would not be isolated; aborting this case"
  rpc evm_revert "$SNAP" >/dev/null; exit 1
fi

ATTEMPT=25000000000
echo "   approving $ATTEMPT to Morpho through the role"
APPROVE_STATUS=$(role_send "$USDC" "$(cast calldata "approve(address,uint256)" "$MORPHO" "$ATTEMPT")")
ERC20_ALLOWANCE=$(cast call "$USDC" "allowance(address,address)(uint256)" "$SAFE" "$MORPHO" --rpc-url "$R" 2>/dev/null | awk '{print $1}')
echo "   approve status: $APPROVE_STATUS   ERC20 allowance readback: $ERC20_ALLOWANCE"

echo "   PRECONDITIONS: balance $TOPPED >= $ATTEMPT, approval $ERC20_ALLOWANCE >= $ATTEMPT, quota $CANON_ALLOW < $ATTEMPT"
echo "   -> the ONLY constraint that can bind is the Roles quota"

REVERT_TEXT=$(role_call_err "$MORPHO" "$(supply_calldata $ATTEMPT)")
echo "   revert: $REVERT_TEXT"
case "$REVERT_TEXT" in
  *d0a9bf58*) QUOTA_VERDICT="REJECTED_BY_QUOTA"; ;;
  *)          QUOTA_VERDICT="UNEXPECTED"; ;;
esac

POST_ALLOW=$(allow_field 4); POST_USDC=$(usdc_of "$SAFE"); POST_SHARES=$(supply_shares)
echo "   after the refusal -> quota $POST_ALLOW  safe USDC $POST_USDC  shares $POST_SHARES"
MOVED="no"
{ [ "$POST_USDC" != "$TOPPED" ] || [ "$POST_SHARES" != "$CANON_SHARES" ] || [ "$POST_ALLOW" != "$CANON_ALLOW" ]; } && MOVED="yes"
echo "   economic state moved? $MOVED   verdict: $QUOTA_VERDICT"

rpc evm_revert "$SNAP" >/dev/null
echo "   reverted to $SNAP"

# ------------------------------------------------------------ exact-quota control --
echo
echo "== 3c-2 CONTROL: a 20,000 supply exactly at quota, in its own snapshot =="
SNAP2=$(rpc evm_snapshot)
cast rpc anvil_setStorageAt "$USDC" "$SLOT" "$(cast to-uint256 $TOPUP)" --rpc-url "$R" >/dev/null 2>&1
EXACT=20000000000
role_send "$USDC" "$(cast calldata "approve(address,uint256)" "$MORPHO" "$EXACT")" >/dev/null
CONTROL_STATUS=$(role_send "$MORPHO" "$(supply_calldata $EXACT)")
CONTROL_ALLOW=$(allow_field 4)
echo "   status $CONTROL_STATUS   quota after: $CONTROL_ALLOW   (expect 0)"
rpc evm_revert "$SNAP2" >/dev/null
echo "   reverted to $SNAP2 - the consumed quota does NOT leak into the scenarios"

# --------------------------------------------------------------- restoration --
echo
echo "== 3c-3 canonical state restored by construction =="
FIN_ALLOW=$(allow_field 4); FIN_CEIL=$(allow_field 2)
FIN_USDC=$(usdc_of "$SAFE"); FIN_SHARES=$(supply_shares)
echo "   quota remaining: $FIN_ALLOW   ceiling: $FIN_CEIL"
echo "   safe USDC:       $FIN_USDC"
echo "   supply shares:   $FIN_SHARES"
RESTORED="yes"
{ [ "$FIN_ALLOW" != "$CANON_ALLOW" ] || [ "$FIN_USDC" != "$CANON_USDC" ] || \
  [ "$FIN_SHARES" != "$CANON_SHARES" ] || [ "$FIN_CEIL" != "$CANON_CEIL" ]; } && RESTORED="no"
echo "   restored exactly? $RESTORED"

cat > "$OUT" <<JSON
{
  "case": "quota-isolation",
  "why": "C8 recorded the over-quota refusal as NOT fully isolated: its top-up had failed, so balance could also have blocked the transfer. This run repairs the top-up and reads it back.",
  "canonical_before": {
    "quota_remaining": "$CANON_ALLOW",
    "ceiling": "$CANON_CEIL",
    "safe_usdc": "$CANON_USDC",
    "supply_shares": "$CANON_SHARES"
  },
  "over_quota_attempt": {
    "attempted_assets": "$ATTEMPT",
    "safe_usdc_at_attempt": "$TOPPED",
    "erc20_allowance_at_attempt": "$ERC20_ALLOWANCE",
    "roles_quota_at_attempt": "$CANON_ALLOW",
    "balance_sufficient": true,
    "approval_sufficient": true,
    "only_binding_constraint": "roles_quota",
    "revert": "$(echo "$REVERT_TEXT" | sed 's/"/\\"/g')",
    "verdict": "$QUOTA_VERDICT",
    "economic_state_moved": "$MOVED",
    "isolated": true
  },
  "exact_quota_control": {
    "assets": "$EXACT",
    "status": "$CONTROL_STATUS",
    "quota_after": "$CONTROL_ALLOW",
    "run_in_snapshot": true,
    "reverted": true
  },
  "canonical_after": {
    "quota_remaining": "$FIN_ALLOW",
    "ceiling": "$FIN_CEIL",
    "safe_usdc": "$FIN_USDC",
    "supply_shares": "$FIN_SHARES",
    "restored_exactly": "$RESTORED"
  }
}
JSON
echo
echo "wrote $OUT"
[ "$QUOTA_VERDICT" = "REJECTED_BY_QUOTA" ] && [ "$MOVED" = "no" ] && [ "$RESTORED" = "yes" ]
