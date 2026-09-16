#!/usr/bin/env bash
# P00 fixture step 4: the NINE DECLARED interruption scenarios of the frozen
# comparison protocol, run against the native path on the pinned Base fork.
#
# THE OPERATION (identical in every case, per docs/baseline/comparison-protocol.md):
#   raise the cumulative supply ceiling 50,000 -> 80,000 USDC, and replace
#   operator A with operator B. 30,000 is already consumed, so the correct
#   remaining capacity afterwards is 50,000.
#
# THE NATIVE PATH GETS FULL CREDIT. The owner is a competent operator with a
# runbook: every owner action is batched through Safe MultiSendCallOnly 1.4.1 by
# delegatecall, so the clean change is ONE ceremony, TWO signatures, ONE
# submitted transaction. Native atomicity, native allowance semantics and native
# event history are all used as designed rather than reimplemented.
#
# ISOLATION. Every case takes an anvil snapshot, asserts the canonical starting
# state, runs, writes its evidence, and reverts. No case can inherit another's
# state, and the 30,000-used / 20,000-remaining start is re-asserted each time.
set -uo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
R="${HELD_BASE_RPC:?run me through fixtures/with_fork.sh}"
. "${HELD_FIXTURE_OUT:-/tmp/held_fixture.env}"

MORPHO=0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb
USDC=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
MARKET_ID=0x13c42741a359ac4a8aa8287d2be109dcf28344484f91185f9a79bd5a805a55ae
MULTISEND=0x9641d764fc13c8B624c04430C7356C1C7C8102e2   # MultiSendCallOnly 1.4.1
Z=0x0000000000000000000000000000000000000000
PK1=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
PK2=0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d
PK_A=0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6
PK_B=0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a
LEGACY_AGENT=0x976EA74026E726554dB657fA54763abd0C3a0aa9
LOAN=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
COLL=0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452
ORACLE=0xD7A1abA119a236Fea5BBC5cAC6836465cbe9289A
IRM=0x46415998764C29aB2a25CbeA6254146D50D22687
LLTV=860000000000000000

CEILING_OLD=50000000000
CEILING_NEW=80000000000
USED=30000000000
REMAIN_OLD=20000000000
REMAIN_NEW=50000000000

EVID="${HELD_EVIDENCE_DIR:-evidence/P00/baseline}"
mkdir -p "$EVID"
CMDLOG="$EVID/commands.log"
: > "$CMDLOG"
log() { echo "[$(date -u +%H:%M:%S)] $*" >> "$CMDLOG"; }

# ----------------------------------------------------------------- primitives --
rpc() { cast rpc "$@" --rpc-url "$R" 2>/dev/null | tr -d '"'; }
allow_field() { cast call "$ROLES" "allowances(bytes32)(uint128,uint128,uint64,uint128,uint64)" \
  "$ALLOW_KEY" --rpc-url "$R" 2>/dev/null | sed -n "${1}p" | awk '{print $1}'; }
remaining() { allow_field 4; }
ceiling()   { allow_field 2; }
usdc_of()   { cast call "$USDC" "balanceOf(address)(uint256)" "$1" --rpc-url "$R" 2>/dev/null | awk '{print $1}'; }
shares_of() { cast call "$MORPHO" "position(bytes32,address)(uint256,uint128,uint128)" \
  "$MARKET_ID" "$SAFE" --rpc-url "$R" 2>/dev/null | sed -n '1p' | awk '{print $1}'; }
# Role membership is NOT isModuleEnabled(). Zodiac's assignRoles(x,[key],[false]) drops the
# membership but leaves the module enabled, so isModuleEnabled() reports true for a fully
# retired operator — that readback is meaningless here. Membership lives in an internal mapping
# with no public getter, so probe it BEHAVIOURALLY: eth_call a scoped, zero-effect action as
# that address. Observed on the pinned fork, three distinct signals:
#     assigned member   -> returns 0x..01 (success)
#     never assigned    -> NotAuthorized(addr)
#     assignRoles false -> NoMembership
# No state is changed by an eth_call.
role_probe_raw() {
  cast call "$ROLES" "execTransactionWithRole(address,uint256,bytes,uint8,bytes32,bool)" \
    "$USDC" 0 "$(cast calldata "approve(address,uint256)" "$MORPHO" 0)" 0 "$ROLE_KEY" true \
    --from "$1" --rpc-url "$R" 2>&1 | tr '\n' ' '
}
# Deliberately NOT `role_probe_raw | grep -q`: grep -q exits on first match, the upstream
# process takes SIGPIPE, and under `set -o pipefail` the pipeline then reports 141. The test
# would read as false on a match AND on no match — it could only ever return one answer.
is_member() {
  local out; out=$(role_probe_raw "$1")
  case "$out" in
    *NoMembership*|*NotAuthorized*) echo false ;;
    *) echo true ;;
  esac
}
is_morpho_auth() { cast call "$MORPHO" "isAuthorized(address,address)(bool)" "$SAFE" "$1" \
  --rpc-url "$R" 2>/dev/null; }

safe_nonce() { cast call "$SAFE" "nonce()(uint256)" --rpc-url "$R" 2>/dev/null | awk '{print $1}'; }
safe_txhash() { # $1 to $2 data $3 op $4 nonce
  cast call "$SAFE" \
    "getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,uint256)(bytes32)" \
    "$1" 0 "$2" "$3" 0 0 0 "$Z" "$Z" "$4" --rpc-url "$R" 2>/dev/null
}
safe_sigs() { # $1 txhash  -> two owner signatures, ordered by ascending signer address
  local S1 S2
  S1=$(cast wallet sign --no-hash --private-key "$PK1" "$1" 2>/dev/null)
  S2=$(cast wallet sign --no-hash --private-key "$PK2" "$1" 2>/dev/null)
  echo "0x${S2#0x}${S1#0x}"
}
safe_submit() { # $1 to $2 data $3 op $4 sigs -> status (0x1/0x0) or REVERT
  local out
  out=$(cast send "$SAFE" \
    "execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)" \
    "$1" 0 "$2" "$3" 0 0 0 "$Z" "$Z" "$4" --private-key "$PK1" --rpc-url "$R" --json 2>/dev/null)
  if [ -z "$out" ]; then echo REVERT; else
    echo "$out" | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])' 2>/dev/null || echo REVERT
  fi
}
safe_exec() { # $1 to $2 data $3 op  -- prepare, sign and submit in one go
  local n h s
  n=$(safe_nonce); h=$(safe_txhash "$1" "$2" "$3" "$n"); s=$(safe_sigs "$h")
  safe_submit "$1" "$2" "$3" "$s"
}

ms_part() { # $1 to  $2 data -> one MultiSend record, hex, no 0x
  local to d len
  to=$(printf %s "${1#0x}" | tr 'A-F' 'a-f'); d="${2#0x}"; len=$(( ${#d} / 2 ))
  printf "00%s%064x%064x%s" "$to" 0 "$len" "$d"
}
cd_set_ceiling() { # $1 new remaining  $2 new ceiling
  cast calldata "setAllowance(bytes32,uint128,uint128,uint128,uint64,uint64)" \
    "$ALLOW_KEY" "$1" "$2" 0 0 0
}
cd_assign() { cast calldata "assignRoles(address,bytes32[],bool[])" "$1" "[$ROLE_KEY]" "[$2]"; }

# the canonical owner batch: raise the ceiling, retire A, activate B
change_batch() { # $1 remaining-to-write
  local b
  b="$(ms_part "$ROLES" "$(cd_set_ceiling "$1" "$CEILING_NEW")")"
  b="$b$(ms_part "$ROLES" "$(cd_assign "$RUNNER_A" false)")"
  b="$b$(ms_part "$ROLES" "$(cd_assign "$RUNNER_B" true)")"
  cast calldata "multiSend(bytes)" "0x$b"
}

supply_cd() { cast calldata "supply((address,address,address,address,uint256),uint256,uint256,address,bytes)" \
  "($LOAN,$COLL,$ORACLE,$IRM,$LLTV)" "$1" 0 "$SAFE" 0x; }
runner_supply() { # $1 pk  $2 amount -> status or REVERT
  local a out
  a=$(cast calldata "approve(address,uint256)" "$MORPHO" "$2")
  cast send "$ROLES" "execTransactionWithRole(address,uint256,bytes,uint8,bytes32,bool)" \
    "$USDC" 0 "$a" 0 "$ROLE_KEY" true --private-key "$1" --rpc-url "$R" >/dev/null 2>&1
  out=$(cast send "$ROLES" "execTransactionWithRole(address,uint256,bytes,uint8,bytes32,bool)" \
    "$MORPHO" 0 "$(supply_cd "$2")" 0 "$ROLE_KEY" true --private-key "$1" --rpc-url "$R" --json 2>/dev/null)
  if [ -z "$out" ]; then echo REVERT; else
    echo "$out" | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])' 2>/dev/null || echo REVERT
  fi
}

CANON_SHARES=""
assert_canonical() { # every case starts from the same declared state
  local r c u m
  r=$(remaining); c=$(ceiling); u=$(usdc_of "$SAFE"); m=$(is_member "$RUNNER_A")
  [ -z "$CANON_SHARES" ] && CANON_SHARES=$(shares_of)
  if [ "$r" != "$REMAIN_OLD" ] || [ "$c" != "$CEILING_OLD" ] || [ "$m" != "true" ]; then
    echo "   !! CANONICAL PRECONDITION FAILED: remaining=$r ceiling=$c A-member=$m"
    return 1
  fi
  echo "   precondition OK: ceiling $c, remaining $r (=$USED used), A is the operator, safe USDC $u"
  return 0
}

CASES_OK=0; CASES_RUN=0
# Three concepts that the first version of this harness ran together, and that a
# reviewer cannot reconstruct afterwards if they are merged:
#   experiment_result  - did the harness assertions hold? A test can PASS precisely
#                        because it successfully reproduced an UNSAFE state.
#   workflow_outcome   - was the owner's requested outcome actually achieved safely?
#   evidence_class /   - which real components were exercised, and what was therefore
#   unmeasured           NOT established by this case.
EXPERIMENT=""; WORKFLOW=""; COMPLETENESS="COMPLETE within the measured contract scope"
EVIDENCE_CLASS="local-fork contract behaviour against real Base-mainnet singletons (Safe 1.4.1, Zodiac Roles v2.1, MultiSendCallOnly 1.4.1, Morpho Blue, native USDC), driven by anvil/cast"
UNMEASURED="Almanak reconfiguration, native recovery machinery and native result consumption are NOT exercised by this case; the authenticated KeeperHub caller/payer boundary is blocked by L10"
emit() { # $1 id  $2 json-body, ending in '}'
  local body="${2%\}}"
  printf '%s,\n  "experiment_result": "%s",\n  "workflow_outcome": "%s",\n  "evidence_completeness": "%s",\n  "evidence_class": "%s",\n  "unmeasured": "%s"\n}\n' \
    "$body" "$EXPERIMENT" "$WORKFLOW" "$COMPLETENESS" "$EVIDENCE_CLASS" "$UNMEASURED" > "$EVID/$1.json"
  echo "   -> $EVID/$1.json  [experiment=$EXPERIMENT | workflow=${WORKFLOW%% *}]"
}

run_case() { # $1 id  $2 description
  CASES_RUN=$((CASES_RUN+1))
  echo
  echo "=============================================================="
  echo "$1 — $2"
  echo "=============================================================="
  log "CASE $1 begin"
  SNAP=$(rpc evm_snapshot)
  assert_canonical || { echo "   ABORT"; rpc evm_revert "$SNAP" >/dev/null; return 1; }
}
end_case() {
  rpc evm_revert "$SNAP" >/dev/null
  log "CASE $1 end, reverted $SNAP"
  echo "   [reverted to $SNAP — canonical state intact for the next case]"
  CASES_OK=$((CASES_OK+1))
}

# =============================================================== I1-clean =====
run_case I1-clean "ordinary change, no interruption"
STATUS=$(safe_exec "$MULTISEND" "$(change_batch $REMAIN_NEW)" 1)
R_AFT=$(remaining); C_AFT=$(ceiling); A_M=$(is_member "$RUNNER_A"); B_M=$(is_member "$RUNNER_B")
echo "   batch status $STATUS -> ceiling $C_AFT, remaining $R_AFT, A member=$A_M, B member=$B_M"
B_SUP=$(runner_supply "$PK_B" 1000000000); echo "   B can supply 1,000: $B_SUP"
A_SUP=$(runner_supply "$PK_A" 1000000000); echo "   A attempts 1,000 after retirement: $A_SUP"
OUT1=PASS
{ [ "$STATUS" = "0x1" ] && [ "$R_AFT" = "$REMAIN_NEW" ] && [ "$C_AFT" = "$CEILING_NEW" ] && \
  [ "$A_M" = "false" ] && [ "$B_M" = "true" ] && [ "$B_SUP" = "0x1" ] && [ "$A_SUP" = "REVERT" ]; } || OUT1=FAIL
EXPERIMENT="$OUT1"
WORKFLOW="ACHIEVED - ceiling raised to 80,000 with the 30,000 consumption preserved, A retired, B operating"
emit I1-clean "{
  \"id\": \"I1-clean\",
  \"condition\": \"Ordinary change, no interruption.\",
  \"native_method\": \"One Safe MultiSendCallOnly delegatecall carrying setAllowance + assignRoles(A,false) + assignRoles(B,true).\",
  \"ceremonies\": 1, \"individual_signatures\": 2, \"submitted_transactions\": 1, \"manual_steps\": 5,
  \"steps\": [\"read allowance and membership\",\"build the 3-call batch\",\"owner 1 signs\",\"owner 2 signs\",\"submit and read back\"],
  \"batch_status\": \"$STATUS\",
  \"ceiling_after\": \"$C_AFT\", \"remaining_after\": \"$R_AFT\",
  \"a_member_after\": \"$A_M\", \"b_member_after\": \"$B_M\",
  \"b_supply_after\": \"$B_SUP\", \"a_supply_after\": \"$A_SUP\",
  \"outcome\": \"$OUT1 — ceiling raised to 80,000 with the 30,000 history preserved, A retired, B operating\",
  \"recovery_effort\": 0
}"
end_case I1-clean "$OUT1"

# ================================================ I2-ambiguous-submission =====
run_case I2-ambiguous-submission "a prior supply broadcast but unconfirmed at fence time"
cast send "$ROLES" "execTransactionWithRole(address,uint256,bytes,uint8,bytes32,bool)" \
  "$USDC" 0 "$(cast calldata "approve(address,uint256)" "$MORPHO" 5000000000)" 0 "$ROLE_KEY" true \
  --private-key "$PK_A" --rpc-url "$R" >/dev/null 2>&1
rpc evm_setAutomine false >/dev/null
echo "   automine off — both transactions now sit in the mempool together"
# Mempool ordering is not guaranteed, and an unforced run flips between orderings from one
# execution to the next. A baseline has to be reproducible, so the HAZARDOUS interleaving is
# forced by gas price: the runner's in-flight supply outbids the owner's fence and is mined
# first. That is precisely the condition this declared case exists to measure.
TX_A=$(cast send "$ROLES" "execTransactionWithRole(address,uint256,bytes,uint8,bytes32,bool)" \
  "$MORPHO" 0 "$(supply_cd 5000000000)" 0 "$ROLE_KEY" true \
  --private-key "$PK_A" --rpc-url "$R" --gas-price 5000000000 --async 2>/dev/null)
N=$(safe_nonce); H=$(safe_txhash "$MULTISEND" "$(change_batch $REMAIN_NEW)" 1 "$N"); S=$(safe_sigs "$H")
TX_O=$(cast send "$SAFE" \
  "execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)" \
  "$MULTISEND" 0 "$(change_batch $REMAIN_NEW)" 1 0 0 0 "$Z" "$Z" "$S" \
  --private-key "$PK1" --rpc-url "$R" --gas-price 1000000000 --async 2>/dev/null)
echo "   A's supply  $TX_A"
echo "   owner fence $TX_O"
rpc evm_mine >/dev/null
rpc evm_setAutomine true >/dev/null
IDX_A=$(cast receipt "$TX_A" --rpc-url "$R" --json 2>/dev/null | python3 -c 'import json,sys;r=json.load(sys.stdin);print(int(r["transactionIndex"],16),r["status"])' 2>/dev/null || echo "none")
IDX_O=$(cast receipt "$TX_O" --rpc-url "$R" --json 2>/dev/null | python3 -c 'import json,sys;r=json.load(sys.stdin);print(int(r["transactionIndex"],16),r["status"])' 2>/dev/null || echo "none")
echo "   mined: A's supply (index,status)=$IDX_A   owner fence (index,status)=$IDX_O"
R_MID=$(remaining)
echo "   remaining after the block: $R_MID"
# reconcile: what was ACTUALLY consumed, versus what the owner assumed
SHARES_MID=$(shares_of)
if [ "${IDX_A%% *}" -lt "${IDX_O%% *}" ] 2>/dev/null && [ "${IDX_A##* }" = "0x1" ]; then
  ORDER="supply-landed-before-fence"; TRUE_USED=35000000000; CORRECT_REMAIN=45000000000
else
  ORDER="fence-landed-first"; TRUE_USED=$USED; CORRECT_REMAIN=$REMAIN_NEW
fi
echo "   observed order: $ORDER — true consumed = $TRUE_USED, correct remaining = $CORRECT_REMAIN"
REC=0
if [ "$R_MID" != "$CORRECT_REMAIN" ]; then
  echo "   MISMATCH: the owner's batch wrote $R_MID from a pre-fence assumption. A second ceremony is required."
  safe_exec "$ROLES" "$(cd_set_ceiling "$CORRECT_REMAIN" "$CEILING_NEW")" 0 >/dev/null
  REC=1
fi
R_FIN=$(remaining)
OUT2=PASS; [ "$R_FIN" = "$CORRECT_REMAIN" ] || OUT2=FAIL
echo "   reconciled remaining: $R_FIN (want $CORRECT_REMAIN)  extra ceremonies: $REC"
EXPERIMENT="$OUT2"
WORKFLOW="NOT ACHIEVED by this naive single-batch procedure - 5,000 of real consumption was silently regranted and only a second corrective ceremony repaired it. The competent fence-then-reconcile order DOES achieve it: see I2-competent-control.json. This case is retained as the naive control."
emit I2-ambiguous-submission "{
  \"id\": \"I2-ambiguous-submission\",
  \"role\": \"DIAGNOSTIC CONTROL - the naive procedure. Superseded for the representative native comparison by I2-competent-control.json; retained to show the cost of the omission, never counted in native totals.\",
  \"condition\": \"A prior submission broadcast but unconfirmed at fence time.\",
  \"native_method\": \"anvil automine disabled so the runner's supply and the owner's fence contend in one block; order observed from receipt transactionIndex, then reconciled against the allowance actually consumed.\",
  \"ceremonies\": $((1+REC)), \"individual_signatures\": $(( (1+REC)*2 )), \"submitted_transactions\": $((2+REC)), \"manual_steps\": $((7+REC*3)),
  \"runner_tx\": \"$TX_A\", \"owner_tx\": \"$TX_O\",
  \"runner_index_status\": \"$IDX_A\", \"owner_index_status\": \"$IDX_O\",
  \"observed_order\": \"$ORDER\",
  \"ordering_forced_by\": \"gas price — runner 5 gwei vs owner 1 gwei, so the in-flight supply is mined first. Unforced runs flip between orderings; the hazardous one is selected deliberately and is the condition this case declares.\",
  \"remaining_written_by_batch\": \"$R_MID\",
  \"true_consumed\": \"$TRUE_USED\", \"correct_remaining\": \"$CORRECT_REMAIN\", \"remaining_final\": \"$R_FIN\",
  \"supply_shares_after\": \"$SHARES_MID\",
  \"finding\": \"setAllowance writes an absolute remaining value. A supply confirming in the same block as the fence is silently overwritten, so consumption can be erased unless the owner re-reads after finality and reconciles.\",
  \"outcome\": \"$OUT2 — resolved, but only by re-reading after the block and issuing a correcting ceremony\",
  \"recovery_effort\": $REC
}"
end_case I2-ambiguous-submission "$OUT2"

# ==================================================== I3-stale-used-snapshot ==
run_case I3-stale-used-snapshot "a stale Used snapshot at preparation time"
SNAP_READ=$(remaining)
echo "   operator snapshots remaining = $SNAP_READ and computes the new value as 80,000 - 30,000 = 50,000"
SUP=$(runner_supply "$PK_A" 5000000000)
echo "   meanwhile A legitimately supplies 5,000: $SUP   remaining now $(remaining)"
LIVE=$(remaining)
DRIFT=no; [ "$LIVE" != "$SNAP_READ" ] && DRIFT=yes
echo "   pre-submission re-read detects drift? $DRIFT ($SNAP_READ -> $LIVE)"
WOULD_BE=$REMAIN_NEW
CORRECTED=$(( CEILING_NEW - (CEILING_OLD - LIVE) ))
echo "   stale value would write $WOULD_BE; corrected value is $CORRECTED"
STATUS=$(safe_exec "$MULTISEND" "$(change_batch $CORRECTED)" 1)
R_FIN=$(remaining)
OUT3=PASS; { [ "$STATUS" = "0x1" ] && [ "$R_FIN" = "$CORRECTED" ] && [ "$DRIFT" = "yes" ]; } || OUT3=FAIL
echo "   batch $STATUS -> remaining $R_FIN"
EXPERIMENT="$OUT3"
WORKFLOW="ACHIEVED - drift detected by a re-read before signing, so no wrong state was ever committed"
emit I3-stale-used-snapshot "{
  \"id\": \"I3-stale-used-snapshot\",
  \"condition\": \"A stale Used snapshot at preparation time.\",
  \"native_method\": \"Snapshot the allowance, let a legitimate 5,000 supply confirm, then re-read immediately before signing and recompute the absolute remaining value.\",
  \"ceremonies\": 1, \"individual_signatures\": 2, \"submitted_transactions\": 2, \"manual_steps\": 7,
  \"steps\": [\"snapshot remaining\",\"(runner supplies 5,000)\",\"re-read remaining\",\"compare and detect drift\",\"recompute\",\"sign x2\",\"submit and read back\"],
  \"snapshot_remaining\": \"$SNAP_READ\", \"live_remaining\": \"$LIVE\", \"drift_detected\": \"$DRIFT\",
  \"stale_value_would_write\": \"$WOULD_BE\", \"corrected_value\": \"$CORRECTED\", \"remaining_final\": \"$R_FIN\",
  \"finding\": \"The hazard is real but natively detectable: one extra read before signing is sufficient, because remaining capacity is authoritative on-chain state rather than a derived off-chain figure. An operator who skips that read silently regrants 5,000 of spent capacity.\",
  \"outcome\": \"$OUT3 — drift detected before signing; no wrong state was ever committed\",
  \"recovery_effort\": 1
}"
end_case I3-stale-used-snapshot "$OUT3"

# =================================================== I4-policy-changed-midway =
run_case I4-policy-changed-midway "policy changed between preparation and activation"
N_PREP=$(safe_nonce)
H_PREP=$(safe_txhash "$MULTISEND" "$(change_batch $REMAIN_NEW)" 1 "$N_PREP")
S_PREP=$(safe_sigs "$H_PREP")
echo "   prepared and signed the change batch at nonce $N_PREP"
INTERVENE=$(safe_exec "$ROLES" "$(cd_set_ceiling 15000000000 "$CEILING_OLD")" 0)
echo "   owner then independently tightens remaining to 15,000: $INTERVENE (consumes nonce $N_PREP)"
STALE=$(safe_submit "$MULTISEND" "$(change_batch $REMAIN_NEW)" 1 "$S_PREP")
R_AFT=$(remaining)
echo "   stale preparation submitted: $STALE   remaining still $R_AFT"
REPREP=0
if [ "$STALE" != "0x1" ]; then
  N2=$(safe_nonce); H2=$(safe_txhash "$MULTISEND" "$(change_batch 65000000000)" 1 "$N2"); S2=$(safe_sigs "$H2")
  RE=$(safe_submit "$MULTISEND" "$(change_batch 65000000000)" 1 "$S2"); REPREP=1
  echo "   re-prepared at nonce $N2 against the new policy: $RE"
fi
R_FIN=$(remaining); A_M=$(is_member "$RUNNER_A")
OUT4=PASS; { [ "$STALE" != "0x1" ] && [ "$A_M" = "false" ]; } || OUT4=FAIL
EXPERIMENT="$OUT4"
WORKFLOW="ACHIEVED - the Safe nonce refused the stale activation outright and re-preparation succeeded"
emit I4-policy-changed-midway "{
  \"id\": \"I4-policy-changed-midway\",
  \"condition\": \"Policy changed between preparation and activation.\",
  \"native_method\": \"Sign the batch at Safe nonce N, let an independent owner action consume nonce N, then submit the prepared batch.\",
  \"ceremonies\": $((2+REPREP)), \"individual_signatures\": $(( (2+REPREP)*2 )), \"submitted_transactions\": $((3+REPREP)), \"manual_steps\": $((8+REPREP*3)),
  \"prepared_at_nonce\": \"$N_PREP\", \"intervening_change_status\": \"$INTERVENE\",
  \"stale_submission_status\": \"$STALE\", \"remaining_after_stale_attempt\": \"$R_AFT\",
  \"re_prepared\": $REPREP, \"remaining_final\": \"$R_FIN\", \"a_member_final\": \"$A_M\",
  \"finding\": \"The Safe nonce already binds a preparation to the state it was prepared against. A stale activation cannot execute — it fails signature recovery outright. This is a genuine native safety property and is credited as such.\",
  \"outcome\": \"$OUT4 — stale activation refused by the Safe nonce; re-preparation required\",
  \"recovery_effort\": $REPREP
}"
end_case I4-policy-changed-midway "$OUT4"

# ==================================================== I5-missing-archive-data =
run_case I5-missing-archive-data "archive data missing for part of the history"
HEAD=$(cast block-number --rpc-url "$R" 2>/dev/null)
FORK_AT=51353212
SUPPLY_TOPIC=$(cast keccak "Supply(bytes32,address,address,uint256,uint256)" 2>/dev/null)
sum_supplies() { # $1 fromBlock
  cast logs --from-block "$1" --to-block "$HEAD" --address "$MORPHO" \
    "$SUPPLY_TOPIC" "$MARKET_ID" --rpc-url "$R" --json 2>/dev/null | python3 -c '
import json,sys
try: logs=json.load(sys.stdin)
except Exception: print("0 0"); sys.exit()
safe=sys.argv[1].lower(); tot=0; n=0
for l in logs:
    tps=l.get("topics",[])
    if len(tps)<4 or tps[3][-40:].lower()!=safe[-40:]: continue
    d=l.get("data","0x")[2:]
    if len(d)>=64: tot+=int(d[:64],16); n+=1
print(n,tot)' "$SAFE"
}
FULL=$(sum_supplies "$FORK_AT")
echo "   full local range: (events, assets) = $FULL"
TRUNC_FROM=$(( HEAD - 2 ))
PARTIAL=$(sum_supplies "$TRUNC_FROM")
echo "   truncated range (archive missing below $TRUNC_FROM): (events, assets) = $PARTIAL"
STATE_REMAIN=$(remaining); STATE_CEIL=$(ceiling)
STATE_USED=$(( STATE_CEIL - STATE_REMAIN ))
echo "   consumption from STATE alone (ceiling - remaining): $STATE_USED — needs no history at all"
FULL_ASSETS=${FULL##* }; PART_ASSETS=${PARTIAL##* }
RECON=no; [ "$FULL_ASSETS" = "$USED" ] && RECON=yes
ATTRIB=no; [ "$PART_ASSETS" = "$USED" ] && ATTRIB=yes
STATUS=$(safe_exec "$MULTISEND" "$(change_batch $REMAIN_NEW)" 1)
R_FIN=$(remaining)
OUT5=PASS; { [ "$STATE_USED" = "$USED" ] && [ "$RECON" = "yes" ] && [ "$ATTRIB" = "no" ] && [ "$STATUS" = "0x1" ]; } || OUT5=FAIL
EXPERIMENT="$OUT5"
WORKFLOW="ACHIEVED - the change completed; total consumption stayed recoverable from state, only per-operation attribution degraded"
emit I5-missing-archive-data "{
  \"id\": \"I5-missing-archive-data\",
  \"condition\": \"Archive data missing for part of the history.\",
  \"native_method\": \"Reconstruct consumption two ways: from Morpho Supply logs filtered to the Safe, and from Roles allowance state. Then truncate the log range to simulate a missing archive and compare.\",
  \"ceremonies\": 1, \"individual_signatures\": 2, \"submitted_transactions\": 1, \"manual_steps\": 6,
  \"supply_topic0\": \"$SUPPLY_TOPIC\",
  \"full_range_events_and_assets\": \"$FULL\",
  \"truncated_range_events_and_assets\": \"$PARTIAL\",
  \"consumption_from_state_only\": \"$STATE_USED\",
  \"history_reconstructs_total\": \"$RECON\",
  \"truncated_history_reconstructs_total\": \"$ATTRIB\",
  \"remaining_final\": \"$R_FIN\",
  \"finding\": \"Missing archive data does NOT block the change. A non-refilling Zodiac allowance carries consumption in current state — ceiling minus remaining gives 30,000 with no history access whatsoever. History is needed only to ATTRIBUTE consumption to individual operations, and that is what degrades when the archive is truncated.\",
  \"outcome\": \"$OUT5 — total consumption recoverable from state; per-operation attribution is what is lost\",
  \"recovery_effort\": 1
}"
end_case I5-missing-archive-data "$OUT5"

# =================================================== I6-legacy-grant-migration =
run_case I6-legacy-grant-migration "a known legacy Morpho grant — labelled migration fixture"
GRANT=$(safe_exec "$MORPHO" "$(cast calldata "setAuthorization(address,bool)" "$LEGACY_AGENT" true)" 0)
AUTH_BEFORE=$(is_morpho_auth "$LEGACY_AGENT")
echo "   legacy agent authorised on Morpho: $GRANT  isAuthorized=$AUTH_BEFORE"
STATUS=$(safe_exec "$MULTISEND" "$(change_batch $REMAIN_NEW)" 1)
AUTH_AFTER_SWAP=$(is_morpho_auth "$LEGACY_AGENT")
echo "   after the A->B swap: A member=$(is_member "$RUNNER_A")  legacy still authorised=$AUTH_AFTER_SWAP"
B2="$(ms_part "$MORPHO" "$(cast calldata "setAuthorization(address,bool)" "$LEGACY_AGENT" false)")"
REVOKE=$(safe_exec "$MULTISEND" "$(cast calldata "multiSend(bytes)" "0x$B2")" 1)
AUTH_FINAL=$(is_morpho_auth "$LEGACY_AGENT")
echo "   explicit revocation: $REVOKE  isAuthorized=$AUTH_FINAL"
OUT6=PASS; { [ "$AUTH_BEFORE" = "true" ] && [ "$AUTH_AFTER_SWAP" = "true" ] && [ "$AUTH_FINAL" = "false" ]; } || OUT6=FAIL
EXPERIMENT="$OUT6"
WORKFLOW="NOT ACHIEVED by the role swap alone - the known legacy Morpho grant survived the handover as live independent authority. The competent workflow revokes it in the SAME batch at zero extra cost: see I6-competent-control.json. This case is retained as the omission control."
emit I6-legacy-grant-migration "{
  \"id\": \"I6-legacy-grant-migration\",
  \"role\": \"DIAGNOSTIC CONTROL - the naive procedure. Superseded for the representative native comparison by I6-competent-control.json; retained to show the cost of the omission, never counted in native totals.\",
  \"condition\": \"A known legacy Morpho grant — labelled migration fixture, not the protected baseline.\",
  \"native_method\": \"Grant Morpho setAuthorization to a legacy agent, run the A->B handover, then read isAuthorized to test whether the handover fenced it.\",
  \"ceremonies\": 3, \"individual_signatures\": 6, \"submitted_transactions\": 3, \"manual_steps\": 9,
  \"legacy_agent\": \"$LEGACY_AGENT\",
  \"authorized_before\": \"$AUTH_BEFORE\",
  \"authorized_after_role_swap\": \"$AUTH_AFTER_SWAP\",
  \"authorized_after_explicit_revocation\": \"$AUTH_FINAL\",
  \"finding\": \"Replacing the Roles operator does NOT touch a Morpho-level authorization. The legacy agent keeps a fully independent on-chain path to move the Safe's position after the handover completes. Only an explicit setAuthorization(false) closes it, and nothing in the role swap surfaces that it is outstanding — it has to be on the inventory checklist or it is missed.\",
  \"outcome\": \"$OUT6 — handover alone leaves the legacy grant live; a separate owner revocation is required\",
  \"recovery_effort\": 1
}"
end_case I6-legacy-grant-migration "$OUT6"

# ========================================================== I7-failed-cleanup =
run_case I7-failed-cleanup "a cleanup transaction fails"
echo "   A first leaves a standing approval behind — this is the thing cleanup has to remove"
cast send "$ROLES" "execTransactionWithRole(address,uint256,bytes,uint8,bytes32,bool)" \
  "$USDC" 0 "$(cast calldata "approve(address,uint256)" "$MORPHO" 5000000000)" 0 "$ROLE_KEY" true \
  --private-key "$PK_A" --rpc-url "$R" >/dev/null 2>&1
ERC20_BEFORE=$(cast call "$USDC" "allowance(address,address)(uint256)" "$SAFE" "$MORPHO" --rpc-url "$R" 2>/dev/null | awk '{print $1}')
echo "   residual approval before cleanup: $ERC20_BEFORE"
echo "   operator fences A FIRST, then tries to run the approval cleanup through A's route"
FENCE=$(safe_exec "$ROLES" "$(cd_assign "$RUNNER_A" false)" 0)
echo "   fence: $FENCE   A member=$(is_member "$RUNNER_A")"
CLEAN=$(cast send "$ROLES" "execTransactionWithRole(address,uint256,bytes,uint8,bytes32,bool)" \
  "$USDC" 0 "$(cast calldata "approve(address,uint256)" "$MORPHO" 0)" 0 "$ROLE_KEY" true \
  --private-key "$PK_A" --rpc-url "$R" --json 2>/dev/null \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])' 2>/dev/null || echo REVERT)
ERC20_LEFT=$(cast call "$USDC" "allowance(address,address)(uint256)" "$SAFE" "$MORPHO" --rpc-url "$R" 2>/dev/null | awk '{print $1}')
echo "   cleanup through the retired route: $CLEAN   residual ERC20 approval: $ERC20_LEFT"
RETRY=$(safe_exec "$USDC" "$(cast calldata "approve(address,uint256)" "$MORPHO" 0)" 0)
ERC20_FIN=$(cast call "$USDC" "allowance(address,address)(uint256)" "$SAFE" "$MORPHO" --rpc-url "$R" 2>/dev/null | awk '{print $1}')
echo "   retry via owner authority through the Safe: $RETRY   residual approval now: $ERC20_FIN"
OUT7=PASS
{ [ "$CLEAN" = "REVERT" ] && [ "$ERC20_BEFORE" = "5000000000" ] && \
  [ "$ERC20_LEFT" = "$ERC20_BEFORE" ] && [ "$ERC20_FIN" = "0" ]; } || OUT7=FAIL
EXPERIMENT="$OUT7"
WORKFLOW="ACHIEVED AFTER RECOVERY - the mis-ordered cleanup failed loudly and owner authority completed it at the cost of one extra ceremony"
emit I7-failed-cleanup "{
  \"id\": \"I7-failed-cleanup\",
  \"condition\": \"A cleanup transaction fails.\",
  \"native_method\": \"Fence A first, then attempt the ERC20 approval cleanup through A's now-revoked role route; observe the failure and recover through owner authority.\",
  \"ceremonies\": 2, \"individual_signatures\": 4, \"submitted_transactions\": 3, \"manual_steps\": 8,
  \"fence_status\": \"$FENCE\",
  \"residual_approval_before_cleanup\": \"$ERC20_BEFORE\",
  \"cleanup_through_retired_route\": \"$CLEAN\",
  \"residual_approval_after_failed_cleanup\": \"$ERC20_LEFT\",
  \"retry_via_owner_status\": \"$RETRY\",
  \"residual_approval_final\": \"$ERC20_FIN\",
  \"finding\": \"Cleanup ordering is load-bearing. Fencing the operator before running its cleanup strands the residual approval: the route that was supposed to zero it has just been revoked. The failure is loud (the transaction reverts) so it cannot pass unnoticed, but recovery costs a full owner ceremony. Cleanup must precede the fence, or be batched into it.\",
  \"outcome\": \"$OUT7 — cleanup failed loudly and was recovered through owner authority\",
  \"recovery_effort\": 1
}"
end_case I7-failed-cleanup "$OUT7"

# ====================================================== I8-new-key-activation =
run_case I8-new-key-activation "new-key activation with the old key still holding credentials"
STATUS=$(safe_exec "$MULTISEND" "$(change_batch $REMAIN_NEW)" 1)
A_BAL=$(cast balance "$RUNNER_A" --rpc-url "$R" 2>/dev/null)
A_TRY=$(runner_supply "$PK_A" 1000000000)
B_TRY=$(runner_supply "$PK_B" 1000000000)
A_M=$(is_member "$RUNNER_A"); B_M=$(is_member "$RUNNER_B")
A_PROBE=$(role_probe_raw "$RUNNER_A" | sed 's/"/\\"/g' | cut -c1-240)
echo "   A still holds its key and $A_BAL wei of gas; supply attempt: $A_TRY (member=$A_M)"
echo "   B supply attempt: $B_TRY (member=$B_M)"
OUT8=PASS; { [ "$A_TRY" = "REVERT" ] && [ "$B_TRY" = "0x1" ] && [ "$A_M" = "false" ]; } || OUT8=FAIL
EXPERIMENT="$OUT8"
WORKFLOW="ACHIEVED - the old key is retired on-chain while still holding its credentials"
emit I8-new-key-activation "{
  \"id\": \"I8-new-key-activation\",
  \"condition\": \"New-key activation with the old key still holding credentials.\",
  \"native_method\": \"Complete the handover, then have A — which still holds its private key and gas — attempt the same supply it was previously authorised for.\",
  \"ceremonies\": 1, \"individual_signatures\": 2, \"submitted_transactions\": 1, \"manual_steps\": 6,
  \"old_key_gas_balance_wei\": \"$A_BAL\",
  \"old_key_membership_probe_revert\": \"$A_PROBE\",
  \"old_key_supply_attempt\": \"$A_TRY\", \"new_key_supply_attempt\": \"$B_TRY\",
  \"a_member_final\": \"$A_M\", \"b_member_final\": \"$B_M\",
  \"finding\": \"Retiring role membership is sufficient on-chain. A keeps its key, its gas and its ability to broadcast, but has no authorised path: the module rejects it. Residual authority is credential-level only, and the native mechanism already removes the on-chain half in the same batch as the ceiling change.\",
  \"outcome\": \"$OUT8 — old key fully retired on-chain while still holding its credentials\",
  \"recovery_effort\": 0
}"
end_case I8-new-key-activation "$OUT8"

# ==================================================== I9-delayed-callback-ack =
run_case I9-delayed-callback-ack "delayed callback acknowledgement"
STATUS=$(safe_exec "$MULTISEND" "$(change_batch $REMAIN_NEW)" 1)
SUP=$(runner_supply "$PK_B" 3000000000)
R1=$(remaining); S1V=$(shares_of)
sleep 1
R2=$(remaining); S2V=$(shares_of)
R3=$(remaining); S3V=$(shares_of)
echo "   supply $SUP; three independent re-reads of the same settled operation:"
echo "     remaining $R1 / $R2 / $R3"
echo "     shares    $S1V / $S2V / $S3V"
IDEM=yes
{ [ "$R1" = "$R2" ] && [ "$R2" = "$R3" ] && [ "$S1V" = "$S2V" ] && [ "$S2V" = "$S3V" ]; } || IDEM=no
OUT9=PARTIAL
{ [ "$SUP" = "0x1" ] && [ "$IDEM" = "yes" ]; } || OUT9=FAIL
UNMEASURED="The hosted callback/acknowledgement half: whether a delayed ack is retried, duplicated or dropped by the real Almanak/KeeperHub result pipeline. Requires an authenticated KeeperHub organisation route (L10). On-chain idempotence is NOT a substitute for business-operation replay protection across that boundary."
EXPERIMENT="$OUT9"
WORKFLOW="ACHIEVED within the measured on-chain scope - the settled operation re-reads identically, so a late acknowledgement cannot double-consume quota or double-count shares"
COMPLETENESS="PARTIAL - the hosted callback/acknowledgement half is NOT measured (L10). This is an evidence-completeness gap, not a separate workflow outcome."
emit I9-delayed-callback-ack "{
  \"id\": \"I9-delayed-callback-ack\",
  \"condition\": \"Delayed callback acknowledgement.\",
  \"native_method\": \"On-chain half only: settle an operation, then re-read its effects repeatedly to test whether a late or duplicated acknowledgement could change economic state.\",
  \"ceremonies\": 1, \"individual_signatures\": 2, \"submitted_transactions\": 2, \"manual_steps\": 6,
  \"supply_status\": \"$SUP\",
  \"repeated_reads_remaining\": [\"$R1\", \"$R2\", \"$R3\"],
  \"repeated_reads_shares\": [\"$S1V\", \"$S2V\", \"$S3V\"],
  \"onchain_reads_idempotent\": \"$IDEM\",
  \"blocked_step\": \"Actual Almanak/KeeperHub callback delivery and acknowledgement semantics — whether a delayed ack is retried, duplicated or dropped — requires an authenticated KeeperHub organisation caller/payer route. That is blocker L10 and no org API key is available. NOT simulated and NOT inferred.\",
  \"what_is_established\": \"The on-chain half is idempotent: a settled operation re-reads identically, so a late acknowledgement cannot double-consume quota or double-count shares. The economic state does not depend on callback timing.\",
  \"what_is_not_established\": \"Whether the native off-chain result pipeline loses, duplicates or stalls the result when the callback is delayed, and what operator work that costs.\",
  \"finding\": \"Half of this case is genuinely unavailable at P00. Recording the on-chain invariant is honest; recording a hosted callback measurement would not be.\",
  \"outcome\": \"$OUT9 — on-chain idempotence demonstrated; the hosted callback half is blocked by L10\",
  \"recovery_effort\": 0
}"
end_case I9-delayed-callback-ack "$OUT9"

echo
echo "=============================================================="
echo "cases run: $CASES_RUN   completed and reverted cleanly: $CASES_OK"
echo "final canonical check:"
echo "   remaining $(remaining)  ceiling $(ceiling)  A member $(is_member "$RUNNER_A")  B member $(is_member "$RUNNER_B")"
echo "evidence in $EVID"
