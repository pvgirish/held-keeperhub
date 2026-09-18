#!/usr/bin/env bash
# Measure the REAL gas the M1 mainnet ceremony would cost, by running it.
#
# `evidence/P03/public-action-request.json` says a finite gas ceiling must be fixed and
# stated before request B is made, and that it is "deliberately NOT guessed now". This
# script is how it stops being a guess: it runs the actual bootstrap ceremony against the
# pinned Base-mainnet fork and reads `gasUsed` out of the receipts.
#
# It reuses the EXISTING fixture scripts rather than reimplementing the ceremony, so what
# is measured is the same sequence P02/P03 already exercise, not a parallel description of
# it that could drift.
#
# Measurement method: after the ceremony, every block the fork produced past the pinned
# block is walked and every transaction's receipt is read. Nothing is attributed by name
# or assumed; the numbers come from receipts.
#
# WHAT THIS IS NOT: a mainnet transaction. Nothing here leaves the local fork, nothing is
# deployed publicly and nothing is spent. A fork's gas accounting is the real EVM's, but
# mainnet base fee and priority fee are separate live inputs, priced by
# script/price_mainnet_gas.py.
#
# ORDERING. This REWRITES evidence/P03/mainnet-gas-measurement.json from scratch, so it
# drops the `gas_execute_supply` that script/measure_execute_supply_gas.sh folds in. Run
# them in that order -- `make m1-cost` does. Running this one alone afterwards is safe but
# lossy: the pricer falls back to the flagged 1,200,000 upper bound and re-labels it "NOT
# MEASURED", rather than carrying a stale number forward silently.
set -uo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
OUT="$HERE/evidence/P03/mainnet-gas-measurement.json"

./fixtures/with_fork.sh bash -c '
  set -uo pipefail
  export PATH="$HOME/.foundry/bin:$PATH"
  . ./fixtures/fork.env

  for s in 01_deploy_safe_and_roles 02_enable_module_and_fund 03_scope_role \
           03b_bind_allowance_and_build_history 03d_deploy_paused_controller; do
    echo "--- fixture $s" >&2
    bash ./fixtures/scripts/$s.sh >/tmp/held_gas_$s.log 2>&1 || {
      echo "fixture $s FAILED; see /tmp/held_gas_$s.log" >&2; exit 1; }
  done

  # Walk every block the ceremony produced and read the receipts, straight off JSON-RPC.
  # Not via `cast --json`: foundry 1.8.1 wraps that in a {schema_version,success,data}
  # envelope, and the first version of this walk read the wrapper and reported a ceremony
  # costing zero gas. See script/walk_fork_receipts.py.
  LATEST=$(cast block-number --rpc-url "$HELD_BASE_RPC")
  echo "--- walking blocks $((FORK_BLOCK+1))..$LATEST" >&2
  '"${PY:-$HOME/venv312/bin/python}"' script/walk_fork_receipts.py \
      "$HELD_BASE_RPC" "$((FORK_BLOCK+1))" "$LATEST"
' > "$OUT.raw" 2>/tmp/held_gas_run.log
rc=$?

if [ $rc -ne 0 ]; then
  echo "gas measurement FAILED — see /tmp/held_gas_run.log" >&2
  tail -20 /tmp/held_gas_run.log >&2
  exit 1
fi

"${PY:-$HOME/venv312/bin/python}" - "$OUT.raw" "$OUT" <<'PY'
import json, sys
raw, out = sys.argv[1], sys.argv[2]
with open(raw) as fh:
    d = json.load(fh)
txs = d["transactions"]
if not txs:
    # Unreachable: walk_fork_receipts.py already refuses. Asserted anyway, because a
    # ceremony that reports zero gas is the one number that must never be written.
    print("REFUSED: no transactions measured; a zero-gas ceremony did not happen.")
    sys.exit(1)
deploys = [t for t in txs if t.get("contractAddress")]
total = sum(t["gasUsed"] for t in txs)
record = {
  "schema": "held.mainnet-gas-measurement.v1",
  "what": "The M1 bootstrap ceremony, run against the pinned Base-mainnet fork, with gasUsed "
          "read out of the receipts. Measured, not estimated.",
  "not": "NOT a mainnet transaction. Nothing was deployed publicly and nothing was spent.",
  "covers": "Fixture scripts 01, 02, 03, 03b and 03d: Safe deployment, Roles module deployment "
            "and enablement, role scoping, non-refilling allowance binding with genuine "
            "consumption history, and the paused controller deployment. It does NOT cover the "
            "executeSupply broadcast, which KeeperHub's own wallet pays for.",
  "fork_block": d["first_block"] - 1,
  "transaction_count": len(txs),
  "contract_deployments": len(deploys),
  "gas_total_ceremony": total,
  "gas_max_single_tx": max(t["gasUsed"] for t in txs),
  "transactions": txs,
}
with open(out, "w") as fh:
    json.dump(record, fh, indent=1)
    fh.write("\n")
print(f"transactions      : {len(txs)} ({len(deploys)} contract deployments)")
print(f"ceremony gas total: {total:,}")
print(f"largest single tx : {record['gas_max_single_tx']:,}")
print(f"written           : {out}")
PY
rc=$?
# The raw walk is an intermediate; the parsed record above is the evidence. Keep it only
# when the parse failed, where it is the thing you would want to look at.
[ $rc -eq 0 ] && rm -f "$OUT.raw"
exit $rc
