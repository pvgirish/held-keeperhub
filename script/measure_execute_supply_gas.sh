#!/usr/bin/env bash
# Measure the ONE `executeSupply` the M1 execution would broadcast, and fold the figure
# into the gas measurement the cost ceiling is priced from.
#
# `script/measure_mainnet_gas.sh` measures the owner's CEREMONY and says so explicitly:
# "It does NOT cover the executeSupply broadcast, which KeeperHub's own wallet pays for."
# That figure was therefore left at an unmeasured 1,200,000 upper bound, flagged in
# `evidence/P03/m1-cost-ceiling.json` and in `evidence/P03/public-action-request.json` as
# something to replace before request B is granted. This is the replacement.
#
# It measures the SAME bytes the composed run executes -- `fixtures/generated/
# composed-call.json`, built from the real pinned Almanak compiler output -- so the number
# describes the call that would actually be broadcast, not a reconstruction of it.
#
# Passes 1 and 2 are the composed run's own first two passes, for the same reason it has
# them: Python cannot know the controller address until the fork has deployed it, and the
# EIP-712 domain separator commits to that address.
#
# WHAT THIS IS NOT: a mainnet transaction, and not a receipt. See the header of
# test/contracts/HeldExecuteSupplyGas.t.sol for exactly what the two recorded components
# are and what they leave out. Nothing here leaves the local fork, nothing is deployed
# publicly and nothing is spent.
set -uo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
PY="${PY:-$HOME/venv312/bin/python}"
GAS_FILE="$HERE/fixtures/generated/execute-supply-gas.json"
MEASUREMENT="$HERE/evidence/P03/mainnet-gas-measurement.json"

# A stale file from an earlier run must not be able to survive a failed measurement and be
# folded in as if this run had produced it.
rm -f "$GAS_FILE"

# Same reset as the composed run: a reused journal makes pass 2 collide with its own live
# claim from the previous run, which is correct behaviour triggered by stale state.
rm -f fixtures/generated/composed-call.json \
      fixtures/generated/composed-journal.sqlite \
      fixtures/generated/composed-journal.sqlite-wal \
      fixtures/generated/composed-journal.sqlite-shm

./fixtures/with_fork.sh bash -c '
  set -uo pipefail
  export PATH="$HOME/.foundry/bin:$PATH"
  for s in 01_deploy_safe_and_roles 02_enable_module_and_fund 03_scope_role \
           03b_bind_allowance_and_build_history; do
    bash ./fixtures/scripts/$s.sh >/tmp/held_gas_es_$s.log 2>&1 || {
      echo "fixture $s failed; see /tmp/held_gas_es_$s.log"; exit 1; }
  done
  . /tmp/held_fixture.env
  export HELD_SAFE="$SAFE" HELD_ROLES="$ROLES" HELD_ROLE_KEY="$ROLE_KEY" HELD_ALLOW_KEY="$ALLOW_KEY"

  echo "=== pass 1: publish the signing vector (controller address) ==="
  forge test --fork-url "$HELD_BASE_RPC" \
    --match-test test_WritesTheSigningVectorThePythonSignerMustReproduce -vv 2>&1 | tail -3
  [ "${PIPESTATUS[0]}" -eq 0 ] || exit 1

  echo "=== pass 2: build Held'"'"'s request from the admitted action ==="
  '"$PY"' tests/integration/test_p03_composed.py 2>&1 | grep -E "^ok |^FAIL |wrote composed|^all " || true
  [ -f fixtures/generated/composed-call.json ] || { echo "no composed call was built"; exit 1; }

  echo "=== pass 3: measure the executeSupply those bytes perform ==="
  forge test --fork-url "$HELD_BASE_RPC" \
    --match-path "test/contracts/HeldExecuteSupplyGas.t.sol" -vv 2>&1 | tail -12
  exit ${PIPESTATUS[0]}
'
rc=$?
[ $rc -eq 0 ] || { echo "executeSupply gas measurement FAILED" >&2; exit 1; }

"$PY" - "$GAS_FILE" "$MEASUREMENT" <<'PY'
import json, sys
gas_file, measurement = sys.argv[1], sys.argv[2]

with open(gas_file) as fh:
    g = json.load(fh)

total = int(g["total_gas"])
execution = int(g["execution_gas"])
intrinsic = int(g["intrinsic_gas"])
if total != execution + intrinsic:
    raise SystemExit("REFUSED: the recorded total is not its own two components.")
if execution <= 0:
    raise SystemExit("REFUSED: an executeSupply costing zero execution gas did not happen.")

with open(measurement) as fh:
    m = json.load(fh)

m["gas_execute_supply"] = total
m["gas_execute_supply_detail"] = {
    "execution_gas": execution,
    "execution_gas_source": "a gasleft() delta across the outer call in "
                            "test/contracts/HeldExecuteSupplyGas.t.sol, executing "
                            "fixtures/generated/composed-call.json -- the real pinned "
                            "compiler's bytes -- against the real controller on the "
                            "pinned Base-mainnet fork.",
    "intrinsic_gas": intrinsic,
    "intrinsic_gas_source": f"COMPUTED, not measured: 21000 + 16 per non-zero and 4 per "
                            f"zero byte over the {g['calldata_bytes']} calldata bytes "
                            f"(EIP-2028). A gasleft() delta cannot observe it.",
    "calldata_bytes": g["calldata_bytes"],
    "amount": g["amount"],
    "fork_block": g["fork_block"],
    "supersedes": {
        "value": g["superseded_upper_bound"],
        "was": "NOT MEASURED -- a stated upper bound.",
    },
    "not_a_receipt": "A receipt needs a real transaction. Producing one on the fork would "
                     "require the controller deployed AND activated on anvil rather than "
                     "inside the forge VM, with the composed calldata rebuilt against that "
                     "address, because the EIP-712 domain separator commits to it. That "
                     "path was not invented for a figure of this size.",
    "errs_high_by_design": "EIP-3529 storage refunds are applied at the end of a real "
                           "transaction and can only make a receipt LOWER than this.",
    "known_gap_l1_data_fee": "Base is an OP-stack chain and charges an L1 data fee on top "
                             "of gasUsed * gasPrice. It is not part of any gas figure and "
                             "is NOT included here -- exactly as it is not included in the "
                             "ceremony measurement above. Recorded as a gap, not omitted.",
}
with open(measurement, "w") as fh:
    json.dump(m, fh, indent=1)
    fh.write("\n")

print(f"executeSupply execution gas : {execution:,}")
print(f"executeSupply intrinsic gas : {intrinsic:,}  (computed, {g['calldata_bytes']} bytes)")
print(f"executeSupply total gas     : {total:,}   (replaces the unmeasured "
      f"{g['superseded_upper_bound']:,})")
print(f"folded into                 : {measurement}")
PY
rc=$?
[ $rc -eq 0 ] || exit 1

echo
echo "=== re-pricing the ceiling against live Base conditions ==="
exec "$PY" script/price_mainnet_gas.py
