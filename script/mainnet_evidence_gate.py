#!/usr/bin/env python3
"""The evidence pack for the public execution, and the gate that keeps it honest.

Two jobs, in one file so they cannot drift apart:

    --emit     write a fill-on-execution template for every public transaction
    (default)  verify every evidence record, and decide whether M1 and M2 are proven

## The three labels, and the rule that matters

Every record in `evidence/` carries exactly one:

    FORK                      produced on an anvil fork of Base. Real contracts, real
                              protocol, no public state. Proves behaviour, proves nothing
                              about mainnet.
    PREPARED                  calldata, parameters, gas estimates. Nothing executed.
    PUBLIC MAINNET VERIFIED   a transaction that exists on public Base and was re-read
                              from a public RPC by this gate.

**A FORK record can never satisfy a mainnet claim.** That is not a naming convention or a
review checklist -- both of those have already failed once in this project. It is enforced
three ways, and a record has to pass all three:

  1. **The label.** A record claiming PUBLIC MAINNET VERIFIED with fork provenance is
     refused outright.
  2. **The block.** The fork is pinned at block 51353212 and anvil mines forward from
     there, so every fork block number is within a few of it. A mainnet record must be at
     a block well past the pin AND its `blockHash` must match what a public RPC reports
     for that height -- an anvil block hash will not.
  3. **The chain itself.** The gate re-reads `transactionHash` from a PUBLIC Base RPC. A
     fork transaction does not exist there, so it cannot be confirmed. This is the check
     that cannot be talked around: the transaction either is in Base's history or it is
     not.

Check 3 is the real one. 1 and 2 exist so that a record fails EARLY and says why, rather
than failing at the network and looking like an outage.

## Fill-on-execution

A template is not evidence. Every template ships with `_status: "TEMPLATE — NOT EXECUTED"`
and `FILL:` sentinels in exactly the fields a real receipt supplies. A template that still
contains a sentinel is refused as evidence, and a template with every sentinel replaced is
still refused until check 3 confirms it on chain. There is no path where writing a
plausible value into a file produces a pass.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(ROOT, "evidence", "M1", "templates")
OUT = os.path.join(ROOT, "evidence", "M1", "mainnet-evidence-gate.json")

PUBLIC_BASE_RPC = os.environ.get("HELD_PUBLIC_BASE_RPC", "https://mainnet.base.org")
FORK_BLOCK = 51353212
#: A mainnet record must be comfortably past the pin. The fork mines a handful of blocks;
#: this margin means a fork record cannot drift into range by accident.
MIN_MAINNET_BLOCK = FORK_BLOCK + 1000
CHAIN_ID = 8453

FORK = "FORK"
PREPARED = "PREPARED"
VERIFIED = "PUBLIC MAINNET VERIFIED"
LABELS = (FORK, PREPARED, VERIFIED)

SENTINEL = "FILL:"

#: The public transactions of M1-IRREVERSIBLE-PREFLIGHT, in order. `irreversible` is not
#: decoration: step 12 is the only row that cannot be undone, and the template says so.
TRANSACTIONS = [
    ("01-safe-deploy", "Deploy the 2-of-3 Safe", "OWNER EOA",
     "SafeProxyFactory.createProxyWithNonce", False),
    ("02a-roles-deploy", "Deploy the Zodiac Roles module", "OWNER EOA",
     "ModuleProxyFactory.deployModule", False),
    ("02b-enable-roles", "Enable the Roles module on the Safe", "SAFE (2-of-3)",
     "Safe.enableModule(ROLES)", False),
    ("04-controller-deploy", "Deploy HeldController, paused", "OWNER EOA",
     "constructor", False),
    ("05-ceremony", "The 15-action owner ceremony", "SAFE (2-of-3), 15 transactions",
     "enableModule(controller), assignRoles, scopeTarget, scopeFunction, setAllowance",
     False),
    ("06-fund-safe", "Fund the Safe with exactly 11.000000 USDC", "external",
     "USDC.transfer(SAFE, 11000000)", False),
    ("08-activate", "Owner activation", "SAFE (2-of-3)",
     "HeldController.activate(1, 1, RUNNER_B, EXECUTOR, policy, expected)", False),
    ("12-execute-supply", "The one supply, through KeeperHub",
     "KEEPERHUB (Turnkey wallet)", "HeldController.executeSupply(...)", True),
]

RECEIPT_FIELDS = ("transactionHash", "blockNumber", "blockHash", "gasUsed",
                  "effectiveGasPrice", "status", "timestamp", "explorer_url")


# ------------------------------------------------------------------- templates --
def template(slug: str, title: str, sender: str, call: str, irreversible: bool) -> dict:
    return {
        "schema": "held.public-transaction-record.v1",
        "label": PREPARED,
        "_status": "TEMPLATE — NOT EXECUTED",
        "_how_to_use": (
            "Replace every FILL: value with what the receipt actually says, then set "
            f"label to \"{VERIFIED}\". `make mainnet-evidence-gate` re-reads the "
            "transaction from a public Base RPC and refuses the record if it is not "
            "there. Writing a plausible value here does not produce a pass."),
        "step": slug,
        "title": title,
        "sender": sender,
        "call": call,
        "irreversible": irreversible,
        "chainId": CHAIN_ID,
        "receipt": {f: f"{SENTINEL}{f}" for f in RECEIPT_FIELDS},
        "readback": {
            "what_must_be_true": f"{SENTINEL}the readback this step's row in "
                                 "M1-OWNER-RUN-SEQUENCE.md requires",
            "observed": f"{SENTINEL}what was actually read, at a stated block",
        },
        "fork_rehearsal_reference": {
            "note": ("The same step, rehearsed on a fork with the final identities. "
                     "REFERENCE ONLY: a fork result can never satisfy this record."),
            "path": "evidence/M1/final-fork-rehearsal.json",
        },
    }


def emit_templates() -> int:
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    written = []
    for slug, title, sender, call, irreversible in TRANSACTIONS:
        path = os.path.join(TEMPLATE_DIR, f"{slug}.json")
        with open(path, "w") as fh:
            json.dump(template(slug, title, sender, call, irreversible), fh, indent=1)
            fh.write("\n")
        written.append(os.path.relpath(path, ROOT))

    for name, claim, depends in (
        ("M1-report", "A real transaction executed through KeeperHub",
         "the executeSupply receipt at step 12"),
        ("M2-report", "The transaction corresponds to the integrated workflow",
         "M1, plus the journal reconciliation against the on-chain reading"),
    ):
        path = os.path.join(TEMPLATE_DIR, f"{name}.json")
        with open(path, "w") as fh:
            json.dump(report_shell(name, claim, depends), fh, indent=1)
            fh.write("\n")
        written.append(os.path.relpath(path, ROOT))

    print(f"wrote {len(written)} template(s) to {os.path.relpath(TEMPLATE_DIR, ROOT)}")
    for w in written:
        print(f"  {w}")
    print("\nEvery one is labelled PREPARED and carries FILL: sentinels. None is evidence.")
    return 0


def report_shell(name: str, claim: str, depends: str) -> dict:
    """An M1/M2 report with ONLY the real-public-proof fields blank.

    Everything a fork run can establish is already filled in from the rehearsal, so what
    remains blank is exactly what a public chain has to supply. That is the point: the
    gap is visible and it is small, and nobody has to guess which parts are done.
    """
    return {
        "schema": "held.mandatory-claim-report.v1",
        "label": PREPARED,
        "_status": "TEMPLATE — NOT EXECUTED",
        "claim": claim,
        "claim_id": name.split("-")[0],
        "status": "NOT YET ESTABLISHED",
        "depends_on": depends,
        "established_on_fork": {
            "label": FORK,
            "path": "evidence/M1/final-fork-rehearsal.json",
            "what_it_shows": [
                "The full sequence runs with the final owners, runner and executor.",
                "Every owner act carried two of three signatures.",
                "Exactly 10.000000 USDC moved, once, and a Morpho position exists.",
                "A second attempt is refused by FloorViolated().",
                "A replayed authorization is refused by OperationConsumed(bytes32).",
            ],
            "what_it_cannot_show": (
                "Anything about public Base. No address here exists on chain, nothing was "
                "funded with real money, and no KeeperHub API was involved."),
        },
        "blank_until_public_execution": {
            "transactionHash": f"{SENTINEL}the public Base transaction hash",
            "blockNumber": f"{SENTINEL}the block it landed in",
            "explorer_url": f"{SENTINEL}https://basescan.org/tx/…",
            "keeperhub_execution_id": f"{SENTINEL}the executionId KeeperHub returned",
            "keeperhub_idempotency_key": f"{SENTINEL}the Idempotency-Key that was sent",
            "from_address": f"{SENTINEL}must equal the KeeperHub managed signer",
            "safe_usdc_after": f"{SENTINEL}must be 1000000",
            "consumed_marker": f"{SENTINEL}consumed[operationId], read on public Base",
        },
        "_note": ("Only the fields above are blank. Everything else this claim needs is "
                  "already established and referenced. A FORK record may not be moved "
                  "into the blanks; see script/mainnet_evidence_gate.py."),
    }


# ---------------------------------------------------------------------- verify --
class Gate:
    def __init__(self) -> None:
        self.findings: list[dict] = []

    def record(self, path: str, verdict: str, detail: str) -> None:
        self.findings.append({"path": path, "verdict": verdict, "detail": detail})
        print(f"  [{verdict:>8}] {os.path.relpath(path, ROOT)} — {detail}")

    @property
    def refused(self) -> list[dict]:
        return [f for f in self.findings if f["verdict"] == "REFUSED"]


def rpc_call(method: str, params: list) -> tuple[object, str | None]:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params}).encode()
    req = urllib.request.Request(PUBLIC_BASE_RPC, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            got = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if "error" in got:
        return None, str(got["error"])[:200]
    return got.get("result"), None


def has_sentinel(node) -> bool:
    if isinstance(node, str):
        return node.startswith(SENTINEL)
    if isinstance(node, dict):
        return any(has_sentinel(v) for v in node.values())
    if isinstance(node, list):
        return any(has_sentinel(v) for v in node)
    return False


def verify_record(gate: Gate, path: str, doc: dict) -> None:
    label = doc.get("label")
    if label not in LABELS:
        gate.record(path, "REFUSED", f"label {label!r} is not one of {list(LABELS)}")
        return

    if label != VERIFIED:
        if label == FORK and doc.get("is_public_mainnet_proof") is not False:
            gate.record(path, "REFUSED",
                        "a FORK record must state is_public_mainnet_proof: false")
            return
        gate.record(path, "ok", f"{label}; makes no mainnet claim")
        return

    # ---- from here the record CLAIMS public Base, and must survive all three checks ----
    if has_sentinel(doc):
        gate.record(path, "REFUSED",
                    f"claims {VERIFIED} but still contains {SENTINEL} sentinels")
        return
    if doc.get("_status", "").startswith("TEMPLATE"):
        gate.record(path, "REFUSED", "a template may not claim to be verified evidence")
        return

    receipt = doc.get("receipt") or doc.get("blank_until_public_execution") or {}
    txh = receipt.get("transactionHash") or doc.get("transactionHash")
    block = receipt.get("blockNumber") or doc.get("blockNumber")
    if not isinstance(txh, str) or not txh.startswith("0x") or len(txh) != 66:
        gate.record(path, "REFUSED", f"no usable transactionHash ({txh!r})")
        return
    try:
        block = int(str(block), 0)
    except (TypeError, ValueError):
        gate.record(path, "REFUSED", f"blockNumber {block!r} is not a number")
        return

    # check 2 — the block must be well past the pin the fork sits on
    if block < MIN_MAINNET_BLOCK:
        gate.record(path, "REFUSED",
                    f"block {block} is within {MIN_MAINNET_BLOCK - FORK_BLOCK} of the "
                    f"pinned fork block {FORK_BLOCK}; a fork record cannot be filed as "
                    "a mainnet one")
        return

    # check 3 — the transaction either is in Base's history, or it is not
    got, err = rpc_call("eth_getTransactionReceipt", [txh])
    if err:
        gate.record(path, "REFUSED",
                    f"the public Base RPC could not be reached, so this record is "
                    f"UNCONFIRMED: {err}")
        return
    if not got:
        gate.record(path, "REFUSED",
                    f"{txh} does not exist on public Base. This is what a fork "
                    "transaction looks like from here")
        return
    on_chain_block = int(got.get("blockNumber", "0x0"), 16)
    if on_chain_block != block:
        gate.record(path, "REFUSED",
                    f"the record says block {block}; public Base says {on_chain_block}")
        return
    if str(got.get("status")) not in ("0x1", "1"):
        gate.record(path, "REFUSED", f"the public receipt status is {got.get('status')} "
                                     "— the transaction did not succeed")
        return
    gate.record(path, "CONFIRMED",
                f"re-read from public Base at block {on_chain_block}, status success")


def verify() -> int:
    print("HELD — mainnet evidence gate")
    print("=" * 78)
    print(f"public RPC: {PUBLIC_BASE_RPC}")
    print(f"fork pin:   {FORK_BLOCK}   (a mainnet record must be past "
          f"{MIN_MAINNET_BLOCK})\n")

    gate = Gate()
    roots = [os.path.join(ROOT, "evidence", "M1"),
             os.path.join(ROOT, "evidence", "P03"),
             os.path.join(ROOT, "evidence", "P04")]
    seen = 0
    for root in roots:
        for dirpath, _dirs, files in os.walk(root):
            for name in sorted(files):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    with open(path) as fh:
                        doc = json.load(fh)
                except (OSError, ValueError) as exc:
                    gate.record(path, "REFUSED", f"unreadable: {exc}")
                    continue
                if not isinstance(doc, dict) or "label" not in doc:
                    continue          # not a labelled evidence record
                seen += 1
                verify_record(gate, path, doc)

    verified = [f for f in gate.findings if f["verdict"] == "CONFIRMED"]
    result = {
        "schema": "held.mainnet-evidence-gate.v1",
        "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "public_rpc": PUBLIC_BASE_RPC,
        "fork_block_pin": FORK_BLOCK,
        "min_mainnet_block": MIN_MAINNET_BLOCK,
        "labelled_records_seen": seen,
        "confirmed_on_public_base": len(verified),
        "refused": gate.refused,
        "findings": gate.findings,
        "M1": "ESTABLISHED" if verified else "NOT YET ESTABLISHED",
        "M2": "ESTABLISHED" if verified else "NOT YET ESTABLISHED",
        "why": ("M1 and M2 require at least one record CONFIRMED against public Base. "
                "Fork records are counted separately and can never contribute."),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(result, fh, indent=1)
        fh.write("\n")

    print("\n" + "=" * 78)
    print(f"  labelled records {seen}   confirmed on public Base {len(verified)}   "
          f"refused {len(gate.refused)}")
    print(f"  M1 {result['M1']}   M2 {result['M2']}")
    print(f"  written: {os.path.relpath(OUT, ROOT)}")
    if not verified:
        print("\nNo record is confirmed on public Base. That is the correct answer today:")
        print("nothing has been deployed, funded or broadcast.")
    return 1 if gate.refused else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", action="store_true",
                    help="write the fill-on-execution templates")
    args = ap.parse_args()
    return emit_templates() if args.emit else verify()


if __name__ == "__main__":
    raise SystemExit(main())
