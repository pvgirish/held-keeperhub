#!/usr/bin/env python3
"""Turn the BuildOwnerCeremony dry run into the owner's action list.

`script/solidity/BuildOwnerCeremony.s.sol` runs the REAL `HeldInstall.install()` in
simulation and lets Forge record every transaction it would have sent. This reads that
record and emits one entry per owner action: destination, value, calldata, and the
`execTransaction` wrapper the Safe needs.

Nothing here encodes a condition tree or a budget by hand. If it did, it could drift from
the installation the tests exercise -- which is the defect the 67eed71 review found once
already. Every `data` field below came out of the tested installer.

WHAT THIS IS NOT: a broadcast. This writes a file. The owner signs and sends.
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = "BuildOwnerCeremony.s.sol"

# Safe v1.4.1 execTransaction, for the wrapper the owner actually signs.
EXEC_TX_SIG = ("execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,"
               "address,address,bytes)")


def _label(to: str, data: str, safe: str, roles: str, controller: str) -> str:
    """Name the action from its destination and selector. Labels are for the human."""
    sel = data[:10].lower()
    # Selectors computed with `cast sig`, not recalled. A wrong label on correct calldata
    # is how an owner signs the right bytes believing they are something else.
    known = {
        "0x610b5925": "enableModule(address)",
        "0x957ed2b3": "assignRoles(address,bytes32[],bool[])",
        "0x0c6c76b8": "scopeTarget(bytes32,address)",
        "0x7508dd98": "scopeFunction(bytes32,address,bytes4,(uint8,uint8,uint8,bytes)[],uint8)",
        "0xa8ec43ee": "setAllowance(bytes32,uint128,uint128,uint128,uint64,uint64)",
    }
    name = known.get(sel)
    if name is None:
        # An unrecognised selector is a stop, not a shrug: this pipeline is supposed to
        # know every call the tested installer makes.
        raise SystemExit(
            f"REFUSED: unrecognised selector {sel} calling {to}. The owner ceremony must "
            f"not contain a call this script cannot name.")
    where = {safe.lower(): "Safe", roles.lower(): "Roles",
             controller.lower(): "HeldController"}.get(to.lower(), to)
    return f"{where}.{name}"


def main() -> int:
    chain_id = os.environ.get("HELD_CHAIN_ID", "8453")
    safe = os.environ["HELD_SAFE"]
    roles = os.environ["HELD_ROLES"]
    controller = os.environ["HELD_CONTROLLER"]

    run_path = os.path.join(
        ROOT, "broadcast", SCRIPT, chain_id, "dry-run", "run-latest.json")
    if not os.path.exists(run_path):
        print(f"no dry run at {run_path}. Run the forge script WITHOUT --broadcast first.",
              file=sys.stderr)
        return 1
    with open(run_path) as fh:
        run = json.load(fh)

    txs = run.get("transactions") or []
    if not txs:
        # A ceremony of zero transactions is the one result that must never be written:
        # it would read as "nothing to sign" rather than "the capture failed".
        print("REFUSED: the dry run recorded no transactions.", file=sys.stderr)
        return 1

    actions = []
    for i, t in enumerate(txs, 1):
        tx = t.get("transaction") or {}
        to = tx.get("to")
        data = tx.get("input") or tx.get("data") or "0x"
        value = int(tx.get("value") or "0x0", 16) if isinstance(tx.get("value"), str) \
            else int(tx.get("value") or 0)
        if to is None:
            print(f"REFUSED: transaction {i} is a contract CREATION. This script is not "
                  f"supposed to deploy anything; the controller is deployed separately by "
                  f"the owner EOA.", file=sys.stderr)
            return 1
        if value != 0:
            print(f"REFUSED: transaction {i} carries value {value}. Every call in this "
                  f"ceremony must be non-payable.", file=sys.stderr)
            return 1

        actions.append({
            "n": i,
            "label": _label(to, data, safe, roles, controller),
            "chain_id": int(chain_id),
            "from": safe,
            "from_note": "the Safe. Send via execTransaction with 2-of-3 owner signatures.",
            "to": to,
            "value": "0",
            "data": data,
            "data_bytes": (len(data) - 2) // 2,
        })

    out = {
        "schema": "held.owner-ceremony.v1",
        "status": "NOT EXECUTED. This is calldata to be signed and sent by the Safe owners.",
        "provenance": (
            "Captured from a Forge dry run of script/solidity/BuildOwnerCeremony.s.sol, "
            "which calls the SAME HeldInstall.install() that test/contracts/"
            "HeldForkHarness.sol and the P02/P03 suites exercise. No condition tree, "
            "budget or key is re-encoded by hand anywhere in this pipeline."),
        "chain_id": int(chain_id),
        "safe": safe,
        "roles": roles,
        "controller": controller,
        "execTransaction_signature": EXEC_TX_SIG,
        "execTransaction_fixed_args": {
            "operation": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            "note": "value is 0 for every action; `to` and `data` come from each entry.",
        },
        "action_count": len(actions),
        "actions": actions,
    }

    dest = os.path.join(ROOT, "evidence", "M1", "owner-ceremony-calldata.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w") as fh:
        json.dump(out, fh, indent=1)
        fh.write("\n")

    print(f"chain {chain_id} · safe {safe}")
    print(f"{len(actions)} owner actions, every one value=0, every one from the Safe:")
    for a in actions:
        print(f"  {a['n']:2}. {a['label']:58} -> {a['to']}  ({a['data_bytes']} bytes)")
    print(f"\nwritten: {os.path.relpath(dest, ROOT)}")
    print("NOT EXECUTED. Nothing was sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
