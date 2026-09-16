"""G3 gate. Requires the NINE DECLARED cases, real files, real provenance.

Schema validity is necessary, never sufficient: this gate cannot prove a baseline
was run. It exists to make a careless or fabricated record fail loudly.
"""
import hashlib, json, os, sys, re

PROTO = "docs/baseline/comparison-protocol.md"
RUNBOOK = "docs/baseline/native-runbook.md"
MEAS = "docs/baseline/native-measurements.json"
MANIFEST = "project-manifest.json"

# The nine ids are fixed by the frozen protocol. Meaning travels with the id.
DECLARED = ["I1-clean", "I2-ambiguous-submission", "I3-stale-used-snapshot",
            "I4-policy-changed-midway", "I5-missing-archive-data",
            "I6-legacy-grant-migration", "I7-failed-cleanup",
            "I8-new-key-activation", "I9-delayed-callback-ack"]
MIN_EVIDENCE_BYTES = 64
failures = []


def fail(msg):
    failures.append(msg)


def real_file(path, label):
    """A regular, non-empty, non-trivial file. Not a directory, not a stub."""
    if not isinstance(path, str) or not path:
        fail(f"{label}: no path given"); return False
    if os.path.isdir(path):
        fail(f"{label}: path is a DIRECTORY, not a file: {path}"); return False
    if not os.path.isfile(path):
        fail(f"{label}: not a regular file: {path}"); return False
    size = os.path.getsize(path)
    if size < MIN_EVIDENCE_BYTES:
        fail(f"{label}: file is {size} bytes, below the {MIN_EVIDENCE_BYTES}-byte floor: {path}")
        return False
    return True


for f in (PROTO, RUNBOOK):
    if not os.path.isfile(f):
        fail(f"missing {f}")

if not os.path.isfile(MEAS):
    print("check-baseline: FAIL - native-measurements.json does not exist.")
    print("  The native baseline has NOT been run. This gate is correctly red.")
    sys.exit(1)

d = json.load(open(MEAS))

# --- provenance: the run must name the exact frozen protocol it ran under ---
proto_digest = hashlib.sha256(open(PROTO, "rb").read()).hexdigest()
if d.get("protocol_sha256") != proto_digest:
    fail(f"protocol_sha256 does not match the frozen protocol on disk "
         f"(recorded {str(d.get('protocol_sha256'))[:16]}..., actual {proto_digest[:16]}...)")

# --- the three counts stay three separate integers ---
for k in ("ceremonies", "individual_signatures", "submitted_transactions", "manual_steps",
          "stores_touched"):
    if not isinstance(d.get(k), int):
        fail(f"{k} must be an integer, got {type(d.get(k)).__name__}")

if not isinstance(d.get("residual_authority"), (str, list, dict)) or not d.get("residual_authority"):
    fail("residual_authority must be recorded and non-empty")

# --- environment and pinned revisions must carry real content, not empty shells ---
env = d.get("environment")
if not isinstance(env, dict) or not env:
    fail("environment must be a non-empty object")
else:
    for k in ("fork_rpc_host", "fork_block_number", "fork_block_hash", "chain_id", "foundry_version"):
        if not env.get(k):
            fail(f"environment.{k} is required (a fork must name its chain, block and hash)")
    if env.get("chain_id") not in (8453, "8453"):
        fail(f"environment.chain_id must be 8453 (Base mainnet), got {env.get('chain_id')!r}")
    bh = str(env.get("fork_block_hash", ""))
    if bh and not re.fullmatch(r"0x[0-9a-fA-F]{64}", bh):
        fail(f"environment.fork_block_hash is not a 32-byte hash: {bh}")

revs = d.get("pinned_revisions")
if not isinstance(revs, dict) or not revs:
    fail("pinned_revisions must be a non-empty object")
elif os.path.isfile(MANIFEST):
    want = json.load(open(MANIFEST))["pinned_sources"]["almanak_sdk"]["rev"]
    got = str(revs.get("almanak_sdk", ""))
    if got != want:
        fail(f"pinned_revisions.almanak_sdk {got[:12]!r} does not match the manifest {want[:12]!r}")

# --- the nine DECLARED cases, each exactly once, each with real evidence ---
ints = d.get("interruptions")
if not isinstance(ints, list):
    fail("interruptions must be a list")
else:
    ids = [str(c.get("id", "")) for c in ints if isinstance(c, dict)]
    for want in DECLARED:
        n = ids.count(want)
        if n != 1:
            fail(f"declared case {want} appears {n} times, must appear exactly once")
    for extra in sorted(set(ids) - set(DECLARED)):
        fail(f"case id {extra!r} is not one of the nine declared ids")
    for case in ints:
        if not isinstance(case, dict):
            fail("an interruption entry is not an object"); continue
        cid = case.get("id", "?")
        if not case.get("outcome"):
            fail(f"interruption[{cid}] missing outcome")
        # zero is a VALID recovery effort - test presence, not truthiness
        if "recovery_effort" not in case or case["recovery_effort"] is None:
            fail(f"interruption[{cid}] missing recovery_effort (0 is valid, absent is not)")
        real_file(case.get("evidence_path"), f"interruption[{cid}] evidence")

# --- raw evidence: real files, and a command log with exit codes ---
paths = d.get("raw_evidence_paths") or []
if not paths:
    fail("human-step counts need inspectable raw evidence")
for p in paths:
    real_file(p, "raw evidence")

cl = d.get("commands_log")
if not real_file(cl, "commands_log"):
    fail("a commands log with exit codes is required provenance for the run")

if d.get("protocol_frozen_before_run") is not True:
    fail("measurements must assert protocol_frozen_before_run: true")

if failures:
    for f in failures:
        print("FAIL:", f)
    print(f"check-baseline: FAIL ({len(failures)} problems)")
    sys.exit(1)
print("check-baseline: PASS")
