#!/usr/bin/env bash
# Negative tests for the P00 gates. Runs entirely in a temp workspace.
# NEVER writes to docs/baseline/ in the real tree.
set -u
HELD="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${PY:-$HOME/venv312/bin/python}"
T=$(mktemp -d) || exit 1
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/probes/checks" "$T/docs/baseline" "$T/ev"
cp "$HELD"/probes/checks/check_*.py "$T/probes/checks/"
cp "$HELD"/docs/baseline/comparison-protocol.md "$HELD"/docs/baseline/native-runbook.md "$T/docs/baseline/"
cp "$HELD"/project-manifest.json "$T/"
printf 'x%.0s' $(seq 1 200) > "$T/ev/real.log"
cd "$T"
SHA=$(sha256sum docs/baseline/comparison-protocol.md | awk '{print $1}')
fails=0
expect_fail() { # $1 label
  if "$PY" probes/checks/check_baseline.py >/dev/null 2>&1; then
    echo "NEGATIVE TEST LEAKED: $1 was ACCEPTED"; fails=$((fails+1))
  else echo "ok (rejected): $1"; fi
}
"$PY" - "$SHA" <<'PY'
import json,sys
ints=[{"id":f"NOT-PREDECLARED-{i}","outcome":"ok","recovery_effort":"low","evidence_path":"ev"} for i in range(9)]
json.dump({"protocol_sha256":sys.argv[1],"ceremonies":1,"individual_signatures":2,"submitted_transactions":1,
 "manual_steps":14,"stores_touched":6,"residual_authority":"none","environment":{},"pinned_revisions":{},
 "protocol_frozen_before_run":True,"raw_evidence_paths":["ev/real.log"],"commands_log":"ev/real.log",
 "interruptions":ints}, open("docs/baseline/native-measurements.json","w"))
PY
expect_fail "undeclared ids + directory evidence + empty environment"
echo "---"; [ $fails -eq 0 ] && echo "all negative tests held" || { echo "$fails LEAK(S)"; exit 1; }
