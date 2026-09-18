#!/usr/bin/env python3
"""Price the measured M1 ceremony gas against LIVE Base mainnet conditions.

`script/measure_mainnet_gas.sh` answers "how much gas", by running the ceremony on the
pinned fork and reading the receipts. This answers "what does that gas cost right now",
and the two are kept apart on purpose: gas used is a property of the code and is stable,
while the price of it is a live market number that is stale the moment it is written.

## Both inputs are read on chain, not from a price API

  * Base fee and priority fee: `eth_feeHistory` against the public Base RPC.
  * ETH/USD: the Chainlink ETH/USD aggregator on Base, read directly. A third-party
    price endpoint would put an unauthenticated off-chain source inside a number that
    gates a spending decision; the feed the chain itself uses is better.

## What this produces

A CEILING, not an estimate. A ceiling that is exceeded in practice is a ceiling that did
not do its job, so the headroom multiple is explicit and stated in the output rather than
folded invisibly into a single number.

Nothing here spends anything. Every call is a read.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RPC = os.environ.get("HELD_BASE_RPC_PUBLIC", "https://mainnet.base.org")

# Chainlink ETH/USD on Base. 8 decimals. Read-only.
CHAINLINK_ETH_USD = "0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70"
LATEST_ROUND_DATA = "0xfeaf968c"  # latestRoundData()

# The headroom the ceiling carries over the measured cost at the observed price. Base fees
# move; a ceiling with no headroom would fail on an ordinary busy block.
HEADROOM = 3.0

MEASUREMENT = os.path.join(ROOT, "evidence", "P03", "mainnet-gas-measurement.json")
OUT = os.path.join(ROOT, "evidence", "P03", "m1-cost-ceiling.json")


def rpc(method: str, params: list) -> object:
    # `requests`, not urllib: the public Base endpoint sits behind Cloudflare and answers
    # a bare urllib client with 403. Same reason the KeeperHub client uses requests.
    resp = requests.post(
        RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers={"User-Agent": "held/0.1 (+gas-costing)"}, timeout=30)
    resp.raise_for_status()
    out = resp.json()
    if "error" in out:
        raise RuntimeError(f"{method}: {out['error']}")
    return out["result"]


def main() -> int:
    if not os.path.exists(MEASUREMENT):
        print(f"no gas measurement at {MEASUREMENT}. Run script/measure_mainnet_gas.sh first.")
        return 1
    with open(MEASUREMENT) as fh:
        m = json.load(fh)

    block = int(rpc("eth_blockNumber", []), 16)
    chain_id = int(rpc("eth_chainId", []), 16)
    if chain_id != 8453:
        print(f"REFUSED: {RPC} reports chain {chain_id}, not Base mainnet (8453).")
        return 1

    # 20 blocks of history, and the 90th percentile of priority fees within them: a
    # ceiling built on the median would be exceeded roughly half the time.
    hist = rpc("eth_feeHistory", [hex(20), "latest", [50, 90]])
    base_fees = [int(x, 16) for x in hist["baseFeePerGas"]]
    rewards = [[int(x, 16) for x in r] for r in hist.get("reward") or []]
    base_fee = max(base_fees)
    prio_p90 = max((r[1] for r in rewards if len(r) > 1), default=0)
    gas_price_wei = base_fee + prio_p90

    raw = rpc("eth_call", [{"to": CHAINLINK_ETH_USD, "data": LATEST_ROUND_DATA}, "latest"])
    # latestRoundData() -> (uint80, int256 answer, uint256, uint256 updatedAt, uint80)
    words = [raw[2:][i:i + 64] for i in range(0, len(raw[2:]), 64)]
    eth_usd = int(words[1], 16) / 1e8
    updated_at = int(words[3], 16)
    age_s = int(datetime.now(timezone.utc).timestamp()) - updated_at
    if not (100 < eth_usd < 100_000):
        print(f"REFUSED: implausible ETH/USD {eth_usd}; not pricing a spend off it.")
        return 1

    ceremony_gas = m["gas_total_ceremony"]
    # The one KeeperHub execution is NOT in the ceremony measurement: it is broadcast by
    # KeeperHub's org wallet, not by the owner EOA, and is therefore a separate pot.
    execute_gas = m.get("gas_execute_supply") or 1_200_000
    execute_measured = "gas_execute_supply" in m

    def usd(gas: int) -> float:
        return gas * gas_price_wei / 1e18 * eth_usd

    record = {
        "schema": "held.m1-cost-ceiling.v1",
        "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "A COSTING, NOT AN AUTHORIZATION. Nothing here has been spent or approved.",
        "live_inputs": {
            "rpc": RPC,
            "chain_id": chain_id,
            "block": block,
            "base_fee_wei_max_of_20": base_fee,
            "priority_fee_wei_p90": prio_p90,
            "gas_price_wei_used": gas_price_wei,
            "eth_usd": round(eth_usd, 2),
            "eth_usd_source": f"Chainlink ETH/USD aggregator {CHAINLINK_ETH_USD} on Base",
            "eth_usd_age_seconds": age_s,
        },
        "measured_gas": {
            "ceremony_total": ceremony_gas,
            "ceremony_source": "evidence/P03/mainnet-gas-measurement.json — receipts from the "
                               "real ceremony on the pinned Base-mainnet fork",
            "one_execute_supply": execute_gas,
            "one_execute_supply_source": (
                "evidence/P03/mainnet-gas-measurement.json — the real pinned compiler's own "
                "bytes executed against the real controller on the pinned Base-mainnet fork. "
                "See gas_execute_supply_detail there: it is fork-measured execution gas plus "
                "COMPUTED intrinsic gas, it is NOT a receipt, and it errs high."
                if execute_measured else
                "NOT MEASURED — a stated upper bound, flagged so it cannot be read as a "
                "measurement. The composed fork run executes this call and the figure should "
                "be replaced with its receipt before request B is granted."),
            **({"one_execute_supply_detail": m["gas_execute_supply_detail"]}
               if "gas_execute_supply_detail" in m else {}),
        },
        "two_separate_gas_payers": {
            "owner_eoa": "Pays the ceremony: Safe, Roles module and controller deployment, "
                         "the owner scoping ceremony, and activation. Must be funded with ETH "
                         "on Base before step 1.",
            "keeperhub_org_turnkey_wallet": "Pays the ONE executeSupply broadcast. KeeperHub "
                                            "documents that transactions are broadcast from the "
                                            "organisation's Turnkey wallet and that it must hold "
                                            "enough ETH on the chain. This is a second pot and is "
                                            "funded through KeeperHub, not by this repository.",
        },
        "cost_at_observed_price_usd": {
            "ceremony": round(usd(ceremony_gas), 2),
            "one_execute_supply": round(usd(execute_gas), 2),
            "total": round(usd(ceremony_gas + execute_gas), 2),
        },
        "proposed_ceilings": {
            "headroom_multiple": HEADROOM,
            "why": "Base fees move. A ceiling with no headroom is exceeded by an ordinary busy "
                   "block, and a ceiling that is routinely exceeded stops being a control.",
            "owner_eoa_eth": round(ceremony_gas * gas_price_wei / 1e18 * HEADROOM, 6),
            "owner_eoa_usd": round(usd(ceremony_gas) * HEADROOM, 2),
            "keeperhub_wallet_eth": round(execute_gas * gas_price_wei / 1e18 * HEADROOM, 6),
            "keeperhub_wallet_usd": round(usd(execute_gas) * HEADROOM, 2),
            "total_gas_usd": round(usd(ceremony_gas + execute_gas) * HEADROOM, 2),
        },
        "not_included": {
            "usdc_supplied": "The supplied USDC is NOT a cost. It remains customer-owned: the "
                             "Safe owns the Morpho position, onBehalf is the Safe, and a "
                             "withdraw can only pay the Safe. It is capital at protocol risk, "
                             "not spend, and its amount is a separate decision.",
            "price_volatility": "This is a snapshot. It is stale immediately and must be re-run "
                                "before the ceremony actually begins.",
        },
    }

    with open(OUT, "w") as fh:
        json.dump(record, fh, indent=1)
        fh.write("\n")

    c = record["cost_at_observed_price_usd"]
    p = record["proposed_ceilings"]
    print(f"Base block {block}, gas price {gas_price_wei / 1e9:.4f} gwei, "
          f"ETH ${eth_usd:,.2f} (feed age {age_s}s)")
    print(f"  ceremony        {ceremony_gas:>10,} gas   ${c['ceremony']:>8,.2f}")
    print(f"  one executeSupply {execute_gas:>8,} gas   ${c['one_execute_supply']:>8,.2f}"
          f"{'' if execute_measured else '   (UPPER BOUND, not measured)'}")
    print(f"  total                          ${c['total']:>8,.2f}")
    print(f"\nProposed ceilings at {HEADROOM}x headroom:")
    print(f"  owner EOA          {p['owner_eoa_eth']:.6f} ETH  (${p['owner_eoa_usd']:,.2f})")
    print(f"  KeeperHub wallet   {p['keeperhub_wallet_eth']:.6f} ETH  (${p['keeperhub_wallet_usd']:,.2f})")
    print(f"\nwritten: {os.path.relpath(OUT, ROOT)}")
    print("This is a costing. It authorizes nothing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
