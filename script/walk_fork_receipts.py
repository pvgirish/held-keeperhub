#!/usr/bin/env python3
"""Read every receipt a fork produced past its pinned block, straight off JSON-RPC.

## Why not `cast`

The first version of this parsed `cast block --json` / `cast receipt --json`. Foundry
1.8.1 wraps `--json` output in an envelope -- `{"schema_version":1,"success":true,
"data":{...}}` -- so `transactions` is not at the top level, and the walk quietly found
nothing and reported a ceremony costing zero gas.

That is the same shape of defect the 67eed71 review found in the `SetAuthorization` log
decoder: a parser that cannot read real `cast` output, passing because nothing asserted
it had read anything. So this talks to JSON-RPC directly. There is no `cast` output
format to drift against, and a zero-transaction walk is a hard error rather than a
cheerful total of nothing.
"""
from __future__ import annotations

import json
import sys
import urllib.request


def rpc(url: str, method: str, params: list) -> object:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read())
    if "error" in out:
        raise RuntimeError(f"{method}{params}: {out['error']}")
    return out["result"]


def main() -> int:
    url, first, last = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    txs = []
    for n in range(first, last + 1):
        block = rpc(url, "eth_getBlockByNumber", [hex(n), False])
        if block is None:
            raise RuntimeError(f"block {n} does not exist on {url}")
        for h in block.get("transactions") or []:
            r = rpc(url, "eth_getTransactionReceipt", [h])
            if r is None:
                raise RuntimeError(f"no receipt for {h}; refusing to total partial gas")
            txs.append({
                "block": int(r["blockNumber"], 16),
                "hash": h,
                "to": r.get("to"),
                "contractAddress": r.get("contractAddress"),
                "gasUsed": int(r["gasUsed"], 16),
                "status": int(r.get("status", "0x0"), 16),
            })

    if not txs:
        # A ceremony that costs nothing did not happen. Never report that as a total.
        raise RuntimeError(
            f"walked blocks {first}..{last} on {url} and found NO transactions. The "
            "ceremony either did not run or the walk is not reading the chain. Refusing "
            "to emit a zero-gas measurement.")

    failed = [t for t in txs if t["status"] != 1]
    if failed:
        raise RuntimeError(
            f"{len(failed)} transaction(s) reverted during the ceremony; a gas figure "
            f"measured from a failed run is not a cost ceiling. {failed}")

    json.dump({"first_block": first, "last_block": last, "transactions": txs}, sys.stdout, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
