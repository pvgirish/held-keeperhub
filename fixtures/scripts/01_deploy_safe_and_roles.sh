#!/usr/bin/env bash
# P00 fixture step 1: deploy a 2-of-3 Safe and a Zodiac Roles module on the pinned fork.
# Uses the REAL mainnet singletons and factories present in the fork - nothing is mocked.
set -uo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
R="${HELD_BASE_RPC:?run me through fixtures/with_fork.sh}"
OUT="${HELD_FIXTURE_OUT:-/tmp/held_fixture.env}"

SAFE_SINGLETON=0x41675C099F32341bf84BFc5382aF534df5C7461a
SAFE_FACTORY=0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67
ZODIAC_FACTORY=0x000000000000aDdB49795b0f9bA5BC298cDda236
ROLES_MASTERCOPY=0x9646fDAD06d3e24444381f44362a3B0eB343D337
ZERO=0x0000000000000000000000000000000000000000

# anvil deterministic accounts - LOCAL FIXTURE IDENTITIES ONLY, never real custody
OWNER1=0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
OWNER2=0x70997970C51812dc3A010C7d01b50e0d17dc79C8
OWNER3=0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC
RUNNER_A=0x90F79bf6EB2c4f870365E785982E1f101E93b906
RUNNER_B=0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65
PK1=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80

# pull a deployed address out of a receipt: last 20 bytes of the named event's data/topic
addr_from_receipt() { # $1 txhash  $2 emitter
  # Safe ProxyCreation(address indexed proxy, address singleton) and Zodiac
  # ModuleProxyCreation(address indexed proxy, address indexed masterCopy) BOTH
  # put the new proxy in topics[1]. Read that first; fall back to data.
  cast receipt "$1" --rpc-url "$R" --json 2>/dev/null | python3 -c '
import json,sys
r=json.load(sys.stdin); em=sys.argv[1].lower()
def words(h):
    h=h[2:] if h.startswith("0x") else h
    return [h[i:i+64] for i in range(0,len(h),64)]
for lg in r.get("logs",[]):
    if lg["address"].lower()!=em: continue
    ordered=lg.get("topics",[])[1:]+[lg.get("data","0x")]
    for c in ordered:
        for w in words(c):
            if len(w)==64 and w[:24]=="0"*24 and int(w,16)!=0:
                print("0x"+w[24:]); sys.exit()
' "$2"
}

echo "== deploying 2-of-3 fixture Safe =="
INIT=$(cast calldata "setup(address[],uint256,address,bytes,address,address,uint256,address)" \
  "[$OWNER1,$OWNER2,$OWNER3]" 2 "$ZERO" 0x "$ZERO" "$ZERO" 0 "$ZERO")
TX=$(cast send "$SAFE_FACTORY" "createProxyWithNonce(address,bytes,uint256)" \
  "$SAFE_SINGLETON" "$INIT" 20260915 --private-key "$PK1" --rpc-url "$R" --json 2>/dev/null \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["transactionHash"])')
SAFE=$(addr_from_receipt "$TX" "$SAFE_FACTORY")
echo "safe tx:   $TX"
echo "safe:      $SAFE"
[ -n "${SAFE:-}" ] && [ "$(cast code "$SAFE" --rpc-url "$R" 2>/dev/null | wc -c)" -gt 100 ] || {
  echo "SAFE DEPLOY FAILED"; exit 1; }
echo "owners:    $(cast call "$SAFE" "getOwners()(address[])" --rpc-url "$R" 2>/dev/null | tr -d '\n')"
echo "threshold: $(cast call "$SAFE" "getThreshold()(uint256)" --rpc-url "$R" 2>/dev/null)"

echo "== deploying Zodiac Roles module (owner/avatar/target = Safe) =="
RINIT=$(cast calldata "setUp(bytes)" "$(cast abi-encode "f(address,address,address)" "$SAFE" "$SAFE" "$SAFE")")
TX2=$(cast send "$ZODIAC_FACTORY" "deployModule(address,bytes,uint256)" \
  "$ROLES_MASTERCOPY" "$RINIT" 20260915 --private-key "$PK1" --rpc-url "$R" --json 2>/dev/null \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["transactionHash"])')
ROLES=$(addr_from_receipt "$TX2" "$ZODIAC_FACTORY")
echo "roles tx:  $TX2"
echo "roles:     $ROLES"
RCODE=$(cast code "$ROLES" --rpc-url "$R" 2>/dev/null | wc -c)
echo "roles codelen: $RCODE"
# a Zodiac module proxy is EIP-1167 minimal: ~93 chars of code, NOT a big contract.
# Verify it BEHAVES like the module instead of guessing from code length.
RAVATAR=$(cast call "$ROLES" "avatar()(address)" --rpc-url "$R" 2>/dev/null)
ROWNER=$(cast call "$ROLES" "owner()(address)" --rpc-url "$R" 2>/dev/null)
[ -n "${ROLES:-}" ] && [ "$RCODE" -gt 50 ] \
  && [ "$(echo "$RAVATAR" | tr A-Z a-z)" = "$(echo "$SAFE" | tr A-Z a-z)" ] \
  && [ "$(echo "$ROWNER" | tr A-Z a-z)" = "$(echo "$SAFE" | tr A-Z a-z)" ] || {
  echo "ROLES DEPLOY FAILED"; exit 1; }
echo "roles avatar: $RAVATAR"
echo "roles owner:  $ROWNER"

cat > "$OUT" <<ENV
SAFE=$SAFE
ROLES=$ROLES
SAFE_TX=$TX
ROLES_TX=$TX2
OWNER1=$OWNER1
OWNER2=$OWNER2
OWNER3=$OWNER3
RUNNER_A=$RUNNER_A
RUNNER_B=$RUNNER_B
ENV
echo "wrote $OUT"
