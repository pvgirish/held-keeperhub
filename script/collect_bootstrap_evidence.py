#!/usr/bin/env python3
"""Collect the bounded bootstrap checklist by READING the chain. Rehearsal only.

Every value here is read with `cast` from the running fork. Nothing is asserted from the
fixture scripts' own output, because the point of the checklist is to verify the
installation independently of whatever built it.

Each section records `complete` separately. A section that could not be read, or that
found something outside the supported profile, is INCOMPLETE and the run exits non-zero:
V4 §6 says incomplete evidence blocks activation, so a checklist that cannot fail would
be decoration.

What this deliberately does NOT do:
  * claim finality (an anvil fork has none),
  * claim anything about the eventual PUBLIC installation,
  * treat private credential control as a chain fact.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

RPC = os.environ["HELD_BASE_RPC"]
SAFE = os.environ["HELD_SAFE"]
ROLES = os.environ["HELD_ROLES"]
ROLE_KEY = os.environ["HELD_ROLE_KEY"]
ALLOW_KEY = os.environ["HELD_ALLOW_KEY"]

MORPHO = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
PERMIT2 = "0x000000000022D473030F116dDEE9F6B43aC78BA3"
SENTINEL = "0x0000000000000000000000000000000000000001"

# EIP-1967-style Safe slots: guard and fallback handler are stored at these keccak slots.
GUARD_SLOT = "0x4a204f620c8c5ccdca3fd54d003badd85ba500436a431f0cbda4f558c93c34c8"
FALLBACK_SLOT = "0x6c9a6c4a39284e37ed1cf53d337577d14212a4870fb976a4366c693b939918d5"

# Identities the fixture knows about. Anything OUTSIDE this set that holds authority is
# an unrecognised path, which V4 §6 says prevents protected activation.
KNOWN = {
    "safe": SAFE,
    "roles": ROLES,
    "morpho": MORPHO,
    "usdc": USDC,
}

report: dict[str, Any] = {}
failures: list[str] = []


def cast(*args: str) -> str | None:
    out = subprocess.run(["cast", *args, "--rpc-url", RPC],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def section(name: str, complete: bool, **data: Any) -> None:
    report[name] = {"complete": complete, **data}
    mark = "COMPLETE  " if complete else "INCOMPLETE"
    print(f"  [{mark}] {name}")
    if not complete:
        failures.append(name)


def addr(word: str | None) -> str | None:
    """Last 20 bytes of a 32-byte storage word."""
    if not word or len(word) < 42:
        return None
    return "0x" + word[-40:]


# ------------------------------------------------------------------ 0. the block --
block = cast("block-number")
block_hash = cast("block", block or "latest", "--field", "hash") if block else None
chain_id = cast("chain-id")
print(f"\nBootstrap rehearsal at fork block {block} ({chain_id=})")
report["observation"] = {
    "block_number": int(block) if block else None,
    "block_hash": block_hash,
    "chain_id": int(chain_id) if chain_id else None,
    "finality": "NONE — anvil fork. This is the observation point, not finalized "
                "evidence. A public installation must state a finalized block/hash.",
    "scope": "FORK REHEARSAL. Not the public installation, not the P04 automated service.",
}

# --------------------------------------------------- 1. Safe owners / modules -----
owners_raw = cast("call", SAFE, "getOwners()(address[])")
threshold = cast("call", SAFE, "getThreshold()(uint256)")
version = cast("call", SAFE, "VERSION()(string)")
modules_raw = cast("call", SAFE, f"getModulesPaginated(address,uint256)(address[],address)",
                   SENTINEL, "20")
guard = addr(cast("storage", SAFE, GUARD_SLOT))
fallback = addr(cast("storage", SAFE, FALLBACK_SLOT))

owners = []
if owners_raw:
    owners = [o.strip() for o in owners_raw.strip("[]").replace("\n", "").split(",") if o.strip()]
modules = []
if modules_raw:
    first = modules_raw.split("\n")[0]
    modules = [m.strip() for m in first.strip("[]").split(",") if m.strip()]

known_lower = {v.lower() for v in KNOWN.values()}
unrecognised_modules = [m for m in modules if m.lower() not in known_lower]

section(
    "safe",
    complete=bool(owners) and threshold is not None and version is not None
    and modules_raw is not None and not unrecognised_modules,
    owners=owners,
    threshold=int(threshold.split()[0]) if threshold else None,
    implementation_version=version,
    enabled_modules=modules,
    unrecognised_modules=unrecognised_modules,
    guard=guard,
    guard_is_set=bool(guard and int(guard, 16) != 0),
    fallback_handler=fallback,
    note="An unrecognised enabled module is an unrecognised delegated path and blocks "
         "protected activation (V4 §6).",
)

# ------------------------------------------------------- 2. Roles configuration ---
allowance = cast("call", ROLES, "allowances(bytes32)(uint128,uint128,uint64,uint128,uint64)",
                 ALLOW_KEY)
roles_owner = cast("call", ROLES, "owner()(address)")
roles_avatar = cast("call", ROLES, "avatar()(address)")
roles_target = cast("call", ROLES, "target()(address)")

alw = [p.strip().split()[0] for p in allowance.split("\n")] if allowance else []
refill, max_refill, period, balance, timestamp = (alw + [None] * 5)[:5]
non_refilling = refill == "0" and period == "0"

section(
    "roles",
    complete=allowance is not None and roles_owner is not None and non_refilling,
    module=ROLES,
    owner=roles_owner,
    avatar=roles_avatar,
    target=roles_target,
    role_key=ROLE_KEY,
    allowance_key=ALLOW_KEY,
    allowance={"refill": refill, "maxRefill": max_refill, "period": period,
               "balance": balance, "timestamp": timestamp},
    non_refilling=non_refilling,
    note="A refilling allowance is refused by the controller at activation AND during "
         "operation. Read back here rather than trusted from the setup script.",
)

# ------------------------------------------------- 3. Morpho grants (readback) ----
# Morpho's authorization mapping is global across markets within a deployment. A Safe
# acting for ITSELF needs no external delegate, so the supported profile is: no external
# authorized party at all.
probe_identities = {
    "safe_self": SAFE,
    "roles_module": ROLES,
}
for name in ("HELD_RUNNER_A", "HELD_RUNNER_B", "HELD_EXECUTOR"):
    if os.environ.get(name):
        probe_identities[name.lower()] = os.environ[name]

grants: dict[str, Any] = {}
readable = True
for label, who in probe_identities.items():
    res = cast("call", MORPHO, "isAuthorized(address,address)(bool)", SAFE, who)
    if res is None:
        readable = False
        grants[label] = "UNREADABLE"
    else:
        grants[label] = res.lower() == "true"

external = [k for k, v in grants.items() if v is True and k != "safe_self"]
section(
    "morpho_grants",
    complete=readable and not external,
    checked=probe_identities,
    grants=grants,
    external_delegates=external,
    note="Confirmed by mapping readback, not by history alone. BOUNDARY: this checks the "
         "identities listed above. It does not and cannot enumerate every address that "
         "might hold a grant, so completeness is within the declared discovery set.",
)

# ----------------------------------------------- 4. token approvals / Permit2 -----
approvals: dict[str, Any] = {}
for label, spender in (("morpho", MORPHO), ("roles", ROLES), ("permit2", PERMIT2)):
    res = cast("call", USDC, "allowance(address,address)(uint256)", SAFE, spender)
    approvals[label] = res.split()[0] if res else "UNREADABLE"

nonzero = [k for k, v in approvals.items() if v not in ("0", "UNREADABLE")]
section(
    "token_approvals",
    complete=all(v != "UNREADABLE" for v in approvals.values()) and not nonzero,
    token=USDC,
    allowances=approvals,
    nonzero=nonzero,
    note="The managed Safe->Morpho allowance must be zero at rest; the controller also "
         "requires it zero on entry and exit of every operation.",
)

# ------------------------------------- 5. runner / executor identities -----------
# PUBLIC CHAIN FACTS and ATTESTED CONTROL are recorded separately and never merged.
section(
    "identities",
    complete=True,
    public_chain_facts={
        "safe_owners": owners,
        "threshold": int(threshold.split()[0]) if threshold else None,
        "roles_owner": roles_owner,
    },
    attested_not_verified={
        "statement": "Control of the runner and executor keys, and of any KeeperHub "
                     "organisation credential, is ATTESTED and NOT verified here.",
        "why": "Public chain data cannot prove private-key ownership. V4 §6 requires this "
               "distinction to be explicit rather than folded into the chain findings.",
        "fork_note": "Every key in this fixture is a well-known anvil account. It is not "
                     "custody and proves nothing about a production installation.",
    },
)

# -------------------------------------------------------------------- verdict ----
report["verdict"] = {
    "all_sections_complete": not failures,
    "incomplete_sections": failures,
    "activation_would_be": "BLOCKED" if failures else "PERMITTED BY THIS CHECKLIST",
    "important": "'PERMITTED BY THIS CHECKLIST' means the declared sections read clean at "
                 "this observation point on a FORK. It is not authorization, not finality, "
                 "and not evidence about the public installation.",
}

os.makedirs("evidence/P03", exist_ok=True)
with open("evidence/P03/bootstrap-rehearsal.json", "w") as fh:
    json.dump(report, fh, indent=1)

print(f"\nverdict: {report['verdict']['activation_would_be']}")
if failures:
    print(f"incomplete: {failures}")
print("wrote evidence/P03/bootstrap-rehearsal.json")
sys.exit(1 if failures else 0)
