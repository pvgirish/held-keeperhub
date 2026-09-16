#!/usr/bin/env python3
"""Re-verify the restored authoritative plan against its recorded digests.

The corpus in docs/plan/ is the requirements source of truth. If it drifts -- edited,
truncated, partially restored -- requirements silently change and nothing else in the
build would notice. This is cheap and runs in every phase gate.
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "docs", "plan")


def main() -> int:
    manifest = os.path.join(BASE, "SHA256SUMS.json")
    if not os.path.exists(manifest):
        print("check-plan-digests: FAIL — docs/plan/SHA256SUMS.json is missing")
        return 1
    recorded = json.load(open(manifest))
    bad, missing = [], []
    for name, want in sorted(recorded.items()):
        path = os.path.join(BASE, name)
        if not os.path.exists(path):
            missing.append(name)
            continue
        got = hashlib.sha256(open(path, "rb").read()).hexdigest()
        if got != want:
            bad.append((name, want, got))

    for name in missing:
        print(f"  MISSING   {name}")
    for name, want, got in bad:
        print(f"  MISMATCH  {name}\n            recorded {want}\n            actual   {got}")

    if bad or missing:
        print(f"check-plan-digests: FAIL ({len(missing)} missing, {len(bad)} changed)")
        return 1
    print(f"check-plan-digests: PASS ({len(recorded)} files match the recorded manifest)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
