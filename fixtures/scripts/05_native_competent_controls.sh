#!/usr/bin/env bash
# P00 step 5: the COMPETENT-NATIVE controls for I2 and I6.
#
# WHY THIS EXISTS. The 04 scenarios ran one specific native procedure — a single
# batched change — and found two defects. That establishes what THAT procedure does.
# It does NOT establish that a competent native operator, using the same native tools
# and a runbook, cannot reach the correct outcome. V4 §9 forbids comparing against a
# knowingly weaker alternative ("Do not deliberately forget a native revocation and
# call the result representative"), and A1 puts this review BEFORE P01, not in P06.
#
# So each control here runs the complete competent native workflow and asks: does it
# actually close the defect, and what does it cost? A correct-but-more-expensive
# native recovery is a valid, admissible result. So is a native path that closes the
# gap for free — which would remove the claimed advantage entirely.
#
# The 04 traces are retained unchanged as omission/naive controls. Nothing is replaced.
set -uo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
R="${HELD_BASE_RPC:?run me through fixtures/with_fork.sh}"
. "${HELD_FIXTURE_OUT:-/tmp/held_fixture.env}"

MORPHO=0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb
USDC=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
MARKET_ID=0x13c42741a359ac4a8aa8287d2be109dcf28344484f91185f9a79bd5a805a55ae
MULTISEND=0x9641d764fc13c8B624c04430C7356C1C7C8102e2
Z=0x0000000000000000000000000000000000000000
PK1=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
PK2=0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d
PK_A=0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6
PK_B=0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a
PK_LEGACY=0x92db14e403b83dfe3df233f83dfa3a0d7096f21ca9b0d6d6b8d88b2b4ec1564e
LEGACY_AGENT=0x976EA74026E726554dB657fA54763abd0C3a0aa9
LOAN=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
COLL=0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452
ORACLE=0xD7A1abA119a236Fea5BBC5cAC6836465cbe9289A
IRM=0x46415998764C29aB2a25CbeA6254146D50D22687
LLTV=860000000000000000

CEILING_OLD=50000000000
CEILING_NEW=80000000000
REMAIN_OLD=20000000000

EVID="${HELD_EVIDENCE_DIR:-evidence/P00/baseline}"
mkdir -p "$EVID"

rpc() { cast rpc "$@" --rpc-url "$R" 2>/dev/null | tr -d '"'; }
allow_field() { cast call "$ROLES" "allowances(bytes32)(uint128,uint128,uint64,uint128,uint64)" \
  "$ALLOW_KEY" --rpc-url "$R" 2>/dev/null | sed -n "${1}p" | awk '{print $1}'; }
remaining() { allow_field 4; }
ceiling()   { allow_field 2; }
shares_of() { cast call "$MORPHO" "position(bytes32,address)(uint256,uint128,uint128)" \
  "$MARKET_ID" "$SAFE" --rpc-url "$R" 2>/dev/null | sed -n '1p' | awk '{print $1}'; }
is_morpho_auth() { cast call "$MORPHO" "isAuthorized(address,address)(bool)" "$SAFE" "$1" \
  --rpc-url "$R" 2>/dev/null; }
role_probe_raw() {
  cast call "$ROLES" "execTransactionWithRole(address,uint256,bytes,uint8,bytes32,bool)" \
    "$USDC" 0 "$(cast calldata "approve(address,uint256)" "$MORPHO" 0)" 0 "$ROLE_KEY" true \
    --from "$1" --rpc-url "$R" 2>&1 | tr '\n' ' '
}
is_member() { local o; o=$(role_probe_raw "$1")
  case "$o" in *NoMembership*|*NotAuthorized*) echo false ;; *) echo true ;; esac; }

safe_nonce() { cast call "$SAFE" "nonce()(uint256)" --rpc-url "$R" 2>/dev/null | awk '{print $1}'; }
safe_exec() { # $1 to $2 data $3 op -> status
  local n h s1 s2 out
  n=$(safe_nonce)
  h=$(cast call "$SAFE" \
    "getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,uint256)(bytes32)" \
    "$1" 0 "$2" "$3" 0 0 0 "$Z" "$Z" "$n" --rpc-url "$R" 2>/dev/null)
  s1=$(cast wallet sign --no-hash --private-key "$PK1" "$h" 2>/dev/null)
  s2=$(cast wallet sign --no-hash --private-key "$PK2" "$h" 2>/dev/null)
  out=$(cast send "$SAFE" \
    "execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)" \
    "$1" 0 "$2" "$3" 0 0 0 "$Z" "$Z" "0x${s2#0x}${s1#0x}" \
    --private-key "$PK1" --rpc-url "$R" --json 2>/dev/null)
  if [ -z "$out" ]; then echo REVERT; else
    echo "$out" | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])' 2>/dev/null || echo REVERT
  fi
}
ms_part() { local to d len; to=$(printf %s "${1#0x}" | tr 'A-F' 'a-f'); d="${2#0x}"; len=$(( ${#d} / 2 ))
  printf "00%s%064x%064x%s" "$to" 0 "$len" "$d"; }
cd_set_allow() { cast calldata "setAllowance(bytes32,uint128,uint128,uint128,uint64,uint64)" \
  "$ALLOW_KEY" "$1" "$2" 0 0 0; }
cd_assign() { cast calldata "assignRoles(address,bytes32[],bool[])" "$1" "[$ROLE_KEY]" "[$2]"; }
supply_cd() { cast calldata "supply((address,address,address,address,uint256),uint256,uint256,address,bytes)" \
  "($LOAN,$COLL,$ORACLE,$IRM,$LLTV)" "$1" 0 "$SAFE" 0x; }

echo "=============================================================="
echo "I2-competent — the full native fence / reconcile / activate order"
echo "=============================================================="
SNAP=$(rpc evm_snapshot)
[ "$(remaining)" = "$REMAIN_OLD" ] || { echo "ABORT: not canonical"; rpc evm_revert "$SNAP" >/dev/null; exit 1; }
echo "   canonical: ceiling $(ceiling), remaining $(remaining)"

# A pre-approves so its in-flight supply is a genuine, valid, authorised operation.
cast send "$ROLES" "execTransactionWithRole(address,uint256,bytes,uint8,bytes32,bool)" \
  "$USDC" 0 "$(cast calldata "approve(address,uint256)" "$MORPHO" 5000000000)" 0 "$ROLE_KEY" true \
  --private-key "$PK_A" --rpc-url "$R" >/dev/null 2>&1

rpc evm_setAutomine false >/dev/null
# Same forced hazardous ordering as I2: the in-flight supply outbids the fence.
TX_A=$(cast send "$ROLES" "execTransactionWithRole(address,uint256,bytes,uint8,bytes32,bool)" \
  "$MORPHO" 0 "$(supply_cd 5000000000)" 0 "$ROLE_KEY" true \
  --private-key "$PK_A" --rpc-url "$R" --gas-price 5000000000 --gas-limit 3000000 --async 2>/dev/null)

# CEREMONY 1 — fence ONLY. The competent runbook does not bundle the new ceiling with
# the fence, precisely because the correct ceiling is not knowable until the fence has
# settled and the in-flight work has been reconciled.
N=$(safe_nonce)
H=$(cast call "$SAFE" \
  "getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,uint256)(bytes32)" \
  "$ROLES" 0 "$(cd_assign "$RUNNER_A" false)" 0 0 0 0 "$Z" "$Z" "$N" --rpc-url "$R" 2>/dev/null)
S1=$(cast wallet sign --no-hash --private-key "$PK1" "$H" 2>/dev/null)
S2=$(cast wallet sign --no-hash --private-key "$PK2" "$H" 2>/dev/null)
TX_F=$(cast send "$SAFE" \
  "execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)" \
  "$ROLES" 0 "$(cd_assign "$RUNNER_A" false)" 0 0 0 0 "$Z" "$Z" "0x${S2#0x}${S1#0x}" \
  --private-key "$PK1" --rpc-url "$R" --gas-price 1000000000 --gas-limit 3000000 --async 2>/dev/null)
rpc evm_mine >/dev/null
rpc evm_setAutomine true >/dev/null

IDX_A=$(cast receipt "$TX_A" --rpc-url "$R" --json 2>/dev/null | python3 -c 'import json,sys;r=json.load(sys.stdin);print(int(r["transactionIndex"],16),r["status"])' 2>/dev/null || echo "none none")
IDX_F=$(cast receipt "$TX_F" --rpc-url "$R" --json 2>/dev/null | python3 -c 'import json,sys;r=json.load(sys.stdin);print(int(r["transactionIndex"],16),r["status"])' 2>/dev/null || echo "none none")
echo "   in-flight supply (index,status)=$IDX_A     fence (index,status)=$IDX_F"

# RECONCILE — read what ACTUALLY executed. This is the step the naive path skipped.
OBS_REMAIN=$(remaining)
OBS_USED=$(( CEILING_OLD - OBS_REMAIN ))
TARGET=$(( CEILING_NEW - OBS_USED ))
echo "   reconciled from chain: remaining=$OBS_REMAIN -> used=$OBS_USED -> correct new remaining=$TARGET"
A_FENCED=$(is_member "$RUNNER_A")
echo "   A fenced? $A_FENCED  (no further consumption can occur while preparing)"

# CEREMONY 2 — activate, computed from the reconciled figure, batched.
B2="$(ms_part "$ROLES" "$(cd_set_allow "$TARGET" "$CEILING_NEW")")"
B2="$B2$(ms_part "$ROLES" "$(cd_assign "$RUNNER_B" true)")"
ACT=$(safe_exec "$MULTISEND" "$(cast calldata "multiSend(bytes)" "0x$B2")" 1)
FIN_REMAIN=$(remaining); FIN_CEIL=$(ceiling)
echo "   activation $ACT -> ceiling $FIN_CEIL, remaining $FIN_REMAIN (want $TARGET)"
B_M=$(is_member "$RUNNER_B"); A_M=$(is_member "$RUNNER_A")
echo "   A member=$A_M  B member=$B_M"

I2C_OK=PASS
{ [ "$FIN_REMAIN" = "$TARGET" ] && [ "$FIN_CEIL" = "$CEILING_NEW" ] && \
  [ "$A_M" = "false" ] && [ "$B_M" = "true" ]; } || I2C_OK=FAIL
echo "   competent native workflow outcome: $I2C_OK"
rpc evm_revert "$SNAP" >/dev/null

cat > "$EVID/I2-competent-control.json" <<JSON
{
  "control": "I2-competent",
  "relates_to": "I2-ambiguous-submission",
  "question": "Does the COMPETENT native workflow lose consumption under an ambiguous in-flight submission, or does it only the naive single-batch procedure?",
  "procedure": "V4 §6 order, executed with native tools only: fence first as its own ceremony, let the block settle, READ the allowance actually consumed, derive the new remaining from that observation, then activate B in a second batched ceremony.",
  "forced_ordering": "in-flight supply at 5 gwei vs fence at 1 gwei, so the supply is mined first — the same hazardous interleaving as I2, disclosed as deliberate.",
  "in_flight_supply_index_status": "$IDX_A",
  "fence_index_status": "$IDX_F",
  "observed_remaining_after_fence": "$OBS_REMAIN",
  "derived_used": "$OBS_USED",
  "correct_new_remaining": "$TARGET",
  "final_remaining": "$FIN_REMAIN",
  "final_ceiling": "$FIN_CEIL",
  "a_member_final": "$A_M",
  "b_member_final": "$B_M",
  "ceremonies": 2, "individual_signatures": 4, "submitted_transactions": 2,
  "experiment_result": "$I2C_OK",
  "workflow_outcome": "$I2C_OK — the competent native workflow reaches the correct remaining capacity on the first attempt, with no wrong state ever committed",
  "finding": "The I2 defect is a property of the NAIVE single-batch procedure, not of the native tooling. Fencing first and deriving the new ceiling from the reconciled on-chain figure closes it completely. The cost is that the change cannot be one atomic ceremony: it necessarily becomes two (fence, then activate), because the correct value is unknowable until the fence has settled. Native pays 2 ceremonies / 4 signatures / 2 transactions and is correct; the naive path pays 2 / 4 / 3 and passes through a silently wrong state first.",
  "consequence_for_the_advantage_claim": "Held cannot claim a ceremony saving here. V4 §6 prescribes the same two-stage fence-then-activate order, so Held pays the same two ceremonies. The I2 hazard does not by itself justify a controller."
}
JSON
echo "   -> $EVID/I2-competent-control.json"

echo
echo "=============================================================="
echo "I6-competent — inventory, revoke in the same batch, verify behaviourally"
echo "=============================================================="
SNAP=$(rpc evm_snapshot)
[ "$(remaining)" = "$REMAIN_OLD" ] || { echo "ABORT: not canonical"; rpc evm_revert "$SNAP" >/dev/null; exit 1; }

# Fixture setup (NOT part of the measured change): the known legacy grant exists.
safe_exec "$MORPHO" "$(cast calldata "setAuthorization(address,bool)" "$LEGACY_AGENT" true)" 0 >/dev/null
cast rpc anvil_setBalance "$LEGACY_AGENT" 0xde0b6b3a7640000 --rpc-url "$R" >/dev/null 2>&1
echo "   fixture: legacy grant present, isAuthorized=$(is_morpho_auth "$LEGACY_AGENT")"

# Prove the grant is REALLY usable before revocation, inside a nested snapshot.
SNAP_IN=$(rpc evm_snapshot)
PRE_SHARES=$(shares_of)
LEG_BEFORE_ERR=$(cast call "$MORPHO" \
  "withdraw((address,address,address,address,uint256),uint256,uint256,address,address)" \
  "($LOAN,$COLL,$ORACLE,$IRM,$LLTV)" 1000000 0 "$SAFE" "$LEGACY_AGENT" \
  --from "$LEGACY_AGENT" --rpc-url "$R" 2>&1 | tr '\n' ' ' | sed 's/"/\\"/g' | cut -c1-160)
LEG_BEFORE=$(cast send "$MORPHO" \
  "withdraw((address,address,address,address,uint256),uint256,uint256,address,address)" \
  "($LOAN,$COLL,$ORACLE,$IRM,$LLTV)" 1000000 0 "$SAFE" "$LEGACY_AGENT" \
  --private-key "$PK_LEGACY" --rpc-url "$R" --json 2>/dev/null \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])' 2>/dev/null || echo REVERT)
POST_SHARES=$(shares_of)
echo "   legacy withdraw BEFORE revocation: $LEG_BEFORE   shares $PRE_SHARES -> $POST_SHARES"
rpc evm_revert "$SNAP_IN" >/dev/null

# INVENTORY — the competent operator checks for external grants before handing over.
DETECTED=$(is_morpho_auth "$LEGACY_AGENT")
echo "   inventory step detects the known grant: $DETECTED"

# ONE ceremony: ceiling + role swap + revocation, all in the same native batch.
B3="$(ms_part "$ROLES" "$(cd_set_allow 50000000000 "$CEILING_NEW")")"
B3="$B3$(ms_part "$ROLES" "$(cd_assign "$RUNNER_A" false)")"
B3="$B3$(ms_part "$ROLES" "$(cd_assign "$RUNNER_B" true)")"
B3="$B3$(ms_part "$MORPHO" "$(cast calldata "setAuthorization(address,bool)" "$LEGACY_AGENT" false)")"
BATCH=$(safe_exec "$MULTISEND" "$(cast calldata "multiSend(bytes)" "0x$B3")" 1)
AUTH_AFTER=$(is_morpho_auth "$LEGACY_AGENT")
echo "   single batched ceremony: $BATCH   isAuthorized now $AUTH_AFTER"

LEG_AFTER=$(cast send "$MORPHO" \
  "withdraw((address,address,address,address,uint256),uint256,uint256,address,address)" \
  "($LOAN,$COLL,$ORACLE,$IRM,$LLTV)" 1000000 0 "$SAFE" "$LEGACY_AGENT" \
  --private-key "$PK_LEGACY" --rpc-url "$R" --json 2>/dev/null \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])' 2>/dev/null || echo REVERT)
LEG_ERR=$(cast call "$MORPHO" \
  "withdraw((address,address,address,address,uint256),uint256,uint256,address,address)" \
  "($LOAN,$COLL,$ORACLE,$IRM,$LLTV)" 1000000 0 "$SAFE" "$LEGACY_AGENT" \
  --from "$LEGACY_AGENT" --rpc-url "$R" 2>&1 | tr '\n' ' ' | sed 's/"/\\"/g' | cut -c1-200)
echo "   legacy withdraw AFTER revocation: $LEG_AFTER"
echo "   revert text: $LEG_ERR"
FIN_REMAIN=$(remaining); A_M=$(is_member "$RUNNER_A"); B_M=$(is_member "$RUNNER_B")

I6C_OK=PASS
{ [ "$LEG_BEFORE" = "0x1" ] && [ "$DETECTED" = "true" ] && [ "$BATCH" = "0x1" ] && \
  [ "$AUTH_AFTER" = "false" ] && [ "$LEG_AFTER" = "REVERT" ] && \
  [ "$A_M" = "false" ] && [ "$B_M" = "true" ]; } || I6C_OK=FAIL
echo "   competent native workflow outcome: $I6C_OK"
rpc evm_revert "$SNAP" >/dev/null

cat > "$EVID/I6-competent-control.json" <<JSON
{
  "control": "I6-competent",
  "relates_to": "I6-legacy-grant-migration",
  "question": "The declared scenario is a KNOWN legacy grant. Does the competent native workflow — which knows about it — close it, and at what cost?",
  "procedure": "Inventory the Safe's Morpho authorizations, then include setAuthorization(legacy,false) in the SAME native MultiSend batch as the ceiling change and the role swap. Verify by readback and behaviourally.",
  "grant_usable_before_revocation": "$LEG_BEFORE",
  "pre_revocation_simulation": "$LEG_BEFORE_ERR",
  "probe_amount": "1000000 (1 USDC) — kept small so the test turns on AUTHORITY, not on the market's idle liquidity",
  "shares_moved_by_legacy_before": "$PRE_SHARES -> $POST_SHARES",
  "inventory_detected_grant": "$DETECTED",
  "batch_status": "$BATCH",
  "is_authorized_after": "$AUTH_AFTER",
  "legacy_withdraw_after_revocation": "$LEG_AFTER",
  "legacy_revert_text": "$LEG_ERR",
  "remaining_final": "$FIN_REMAIN",
  "a_member_final": "$A_M", "b_member_final": "$B_M",
  "ceremonies": 1, "individual_signatures": 2, "submitted_transactions": 1,
  "experiment_result": "$I6C_OK",
  "workflow_outcome": "$I6C_OK — the legacy grant is detected, revoked in the same ceremony as the handover, and the former agent's direct Morpho path is behaviourally dead",
  "finding": "The I6 defect is entirely an omission defect. Morpho's setAuthorization is an ordinary Safe-originated call, so a competent operator batches the revocation into the very same MultiSend as the ceiling change and the role swap. It costs ZERO extra ceremonies, signatures or transactions. The legacy agent provably could move the Safe's position beforehand and provably cannot afterwards.",
  "consequence_for_the_advantage_claim": "The I6 finding does NOT survive as evidence of a Held advantage. Native closes it for free once the grant is on the checklist, which the declared scenario stipulates it is. The 04 I6 trace is retained as an omission control only — it shows the cost of forgetting, not a native incapability."
}
JSON
echo "   -> $EVID/I6-competent-control.json"

echo
echo "=============================================================="
echo "canonical state after both controls: remaining $(remaining)  ceiling $(ceiling)"
echo "=============================================================="
[ "$I2C_OK" = "PASS" ] && [ "$I6C_OK" = "PASS" ]
