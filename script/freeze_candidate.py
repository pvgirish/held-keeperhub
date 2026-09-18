#!/usr/bin/env python3
"""Freeze a candidate with EXPLICIT revision semantics.

A manifest cannot certify the commit that contains it -- the digest of a file changes when
the file is written. An earlier artifact simply recorded a `sha` that was the commit BEFORE
the one carrying the manifest, which invited exactly the confusion it was meant to prevent.

So the semantics are named rather than implied:

  source_revision    the commit whose SOURCE the gates were run against, and which a judge
                     should review. This is the meaningful one.
  evidence_revision  the commit whose evidence/ artifacts these digests cover. Usually the
                     same as source_revision.
  manifest_commit    filled in AFTER this file is committed, by `--stamp`. Until then it is
                     null, because it cannot be known.
  release_tag        set only when a tag is actually created.

Run once to write the manifest, commit it, then run with `--stamp <sha>` to record the
commit that carries it.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "evidence", "release", "pre-release-candidate.json")

ARTIFACTS = (
    "evidence/P04/hero-demo-trace.json",
    "evidence/P04/hero-demo-replacement-export.json",
    "evidence/P06/comparison.json",
    "evidence/P06/acceptance.json",
    "evidence/P03/acceptance.json",
    "evidence/P03/bootstrap-rehearsal.json",
    "docs/baseline/native-measurements.json",
)


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(os.path.join(ROOT, path), "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--stamp":
        with open(OUT) as fh:
            m = json.load(fh)
        m["manifest_commit"] = sys.argv[2]
        m["_stamped"] = ("manifest_commit is the commit that CARRIES this file. It is "
                         "necessarily later than source_revision and evidence_revision, "
                         "which is why it is stamped in a second step rather than "
                         "self-certified.")
        with open(OUT, "w") as fh:
            json.dump(m, fh, indent=2)
            fh.write("\n")
        print(f"stamped manifest_commit = {sys.argv[2][:12]}")
        return 0

    head = git("rev-parse", "HEAD")
    manifest = {
        "record": "held.pre-release-candidate.v2",
        "_status": "PRE-RELEASE. NOT a final submission candidate: the mandatory KeeperHub "
                   "execution (M1) does not exist, so no final candidate can honestly be "
                   "frozen. Named and digested so evidence cannot drift against a changed "
                   "source tree.",
        "_revision_semantics": {
            "source_revision": "the commit whose SOURCE the gates ran against. This is what "
                               "a judge reviews.",
            "evidence_revision": "the commit whose evidence/ artifacts these digests cover.",
            "manifest_commit": "the commit carrying this file. Necessarily later; stamped "
                               "in a second step with --stamp, never self-certified.",
            "release_tag": "set only when a tag is actually created.",
        },
        "source_revision": head,
        "evidence_revision": head,
        "manifest_commit": None,
        "release_tag": None,
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "tree_clean": git("status", "--porcelain") == "",
        "evidence_digests": {a: sha256(a) for a in ARTIFACTS if os.path.exists(
            os.path.join(ROOT, a))},
        "pinned": {
            "almanak_sdk": "6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938",
            "fork_block": 51353212,
            "chain_id": 8453,
            "solc": "0.8.28 via_ir, optimizer 200",
        },
        "public_evidence": {
            "keeperhub_execution_id": None,
            "transaction_hash": None,
            "chain": None,
            "status": "NOT YET ESTABLISHED — no organisation credential in this environment",
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    print(f"source_revision = {head[:12]} | digests = "
          f"{len(manifest['evidence_digests'])} | manifest_commit = null (stamp after commit)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
