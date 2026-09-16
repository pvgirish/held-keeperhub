#!/usr/bin/env python3
"""Collect the bounded bootstrap checklist by READING the chain. Rehearsal only.

Every value is read with `cast` from the running fork, PINNED to one observation block.
Nothing is taken from the fixture scripts' own output: the checklist's job is to verify
the installation independently of whatever built it.

## Three separate questions, never conflated

An earlier version of this collector reported COMPLETE in 14 scripted situations that
should have blocked -- an unreadable guard, a Roles module whose owner was not the Safe,
a Roles module not actually enabled on the Safe, a mismatched chain id, malformed grant
output. Its predicates simply did not check the things the prose above them claimed. So
every section now answers three questions separately and a failure of ANY of them blocks:

  READ        did the query return usable data at all?
  COMPLETE    is every required field present?
  COMPATIBLE  does it match the supported profile?

A section that cannot distinguish "read failed" from "read fine, value is wrong" cannot
be trusted to block, and V4 §6 says incomplete evidence blocks activation.

## Scope, stated rather than implied

REHEARSAL against the Base-mainnet FORK. Not public-Safe activation evidence; not the
P04 automated authority service; not finality evidence -- an anvil fork has none.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Any

RPC = os.environ["HELD_BASE_RPC"]
SAFE = os.environ["HELD_SAFE"]
ROLES = os.environ["HELD_ROLES"]
ROLE_KEY = os.environ["HELD_ROLE_KEY"]
ALLOW_KEY = os.environ["HELD_ALLOW_KEY"]
CONTROLLER = os.environ.get("HELD_CONTROLLER")  # the paused Held installation, if deployed

MORPHO = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
PERMIT2 = "0x000000000022D473030F116dDEE9F6B43aC78BA3"
SENTINEL = "0x0000000000000000000000000000000000000001"
ZERO = "0x0000000000000000000000000000000000000000"

GUARD_SLOT = "0x4a204f620c8c5ccdca3fd54d003badd85ba500436a431f0cbda4f558c93c34c8"
FALLBACK_SLOT = "0x6c9a6c4a39284e37ed1cf53d337577d14212a4870fb976a4366c693b939918d5"

# The DECLARED supported profile for this fixture. Deviations are incompatible, not
# merely interesting.
EXPECTED_CHAIN_ID = 8453
EXPECTED_THRESHOLD = 2
EXPECTED_OWNER_COUNT = 3

BLOCK: str | None = None
report: dict[str, Any] = {}
failures: list[str] = []
_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")


def cast(*args: str, pin: bool = True, allow_empty: bool = False) -> str | None:
    """Run cast against the observation block. None means the read FAILED.

    `allow_empty` distinguishes "the query failed" from "the query succeeded and there is
    nothing there". An empty LOG range is a real answer; an empty `call` result is not.
    Collapsing the two would make a failed read look like a clean installation.
    """
    cmd = ["cast", *args, "--rpc-url", RPC]
    if pin and BLOCK is not None and args[0] in ("call", "storage"):
        cmd += ["--block", BLOCK]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        return None
    text = out.stdout.strip()
    if not text and not allow_empty:
        return None
    return text


def section(name: str, *, read: bool, complete: bool, compatible: bool, **data: Any) -> None:
    ok = read and complete and compatible
    report[name] = {"read": read, "complete": complete, "compatible": compatible,
                    "verdict": "COMPLETE" if ok else "INCOMPLETE", **data}
    print(f"  [{'COMPLETE  ' if ok else 'INCOMPLETE'}] {name}"
          + ("" if ok else f"   (read={read} complete={complete} compatible={compatible})"))
    if not ok:
        failures.append(name)


def addr_from_word(word: str | None) -> str | None:
    if not word or len(word) < 42:
        return None
    return "0x" + word[-40:]


def parse_bool(raw: str | None) -> bool | None:
    """Strictly boolean. Malformed output is None -- NOT False."""
    if raw is None:
        return None
    v = raw.strip().lower()
    if v in ("true", "false"):
        return v == "true"
    return None


def same(a: str | None, b: str | None) -> bool:
    return bool(a and b and a.lower() == b.lower())


# ------------------------------------------------------- 0. the observation point --
block = cast("block-number", pin=False)
chain_id = cast("chain-id", pin=False)
BLOCK = block
block_hash = cast("block", block, "--field", "hash", pin=False) if block else None

chain_ok = chain_id is not None and int(chain_id) == EXPECTED_CHAIN_ID
section(
    "observation",
    read=block is not None and chain_id is not None,
    complete=block_hash is not None,
    compatible=chain_ok,
    block_number=int(block) if block else None,
    block_hash=block_hash,
    chain_id=int(chain_id) if chain_id else None,
    expected_chain_id=EXPECTED_CHAIN_ID,
    all_state_reads_pinned_to_block=True,
    finality="NONE — anvil fork. This is the observation point, not finalized evidence.",
    scope="FORK REHEARSAL. Not the public installation, not the P04 automated service.",
)

# --------------------------------------------------------- 1. Safe configuration --
owners_raw = cast("call", SAFE, "getOwners()(address[])")
threshold_raw = cast("call", SAFE, "getThreshold()(uint256)")
version = cast("call", SAFE, "VERSION()(string)")
modules_raw = cast("call", SAFE, "getModulesPaginated(address,uint256)(address[],address)",
                   SENTINEL, "20")
guard_word = cast("storage", SAFE, GUARD_SLOT)
fallback_word = cast("storage", SAFE, FALLBACK_SLOT)

owners = [o.strip() for o in (owners_raw or "").strip("[]").replace("\n", "").split(",") if o.strip()]
modules = [m.strip() for m in (modules_raw or "").split("\n")[0].strip("[]").split(",") if m.strip()]
threshold = int(threshold_raw.split()[0]) if threshold_raw else None
guard = addr_from_word(guard_word)
fallback = addr_from_word(fallback_word)

# The controller is expected among the modules only once it is deployed AND enabled.
recognised = {SAFE.lower(), ROLES.lower()}
if CONTROLLER:
    recognised.add(CONTROLLER.lower())
unrecognised_modules = [m for m in modules if m.lower() not in recognised]
roles_enabled = any(same(m, ROLES) for m in modules)

safe_read = all(x is not None for x in
                (owners_raw, threshold_raw, version, modules_raw, guard_word, fallback_word))
section(
    "safe",
    read=safe_read,
    complete=bool(owners) and threshold is not None and guard is not None and fallback is not None,
    compatible=(
        not unrecognised_modules
        and roles_enabled
        and threshold == EXPECTED_THRESHOLD
        and len(owners) == EXPECTED_OWNER_COUNT
        and same(guard, ZERO)
    ),
    owners=owners,
    owner_count=len(owners),
    expected_owner_count=EXPECTED_OWNER_COUNT,
    threshold=threshold,
    expected_threshold=EXPECTED_THRESHOLD,
    implementation_version=version,
    enabled_modules=modules,
    roles_module_enabled=roles_enabled,
    unrecognised_modules=unrecognised_modules,
    guard=guard,
    guard_is_unset=same(guard, ZERO),
    fallback_handler=fallback,
    note="An UNREADABLE guard or fallback is INCOMPLETE, not 'absent'. An unrecognised "
         "enabled module, a guard that is set, a Roles module that is not actually "
         "enabled, or a threshold/owner count outside the declared profile are all "
         "incompatible and block activation (V4 §6).",
)

# ------------------------------------------------------- 2. Roles configuration ---
allowance_raw = cast("call", ROLES, "allowances(bytes32)(uint128,uint128,uint64,uint128,uint64)",
                     ALLOW_KEY)
roles_owner = cast("call", ROLES, "owner()(address)")
roles_avatar = cast("call", ROLES, "avatar()(address)")
roles_target = cast("call", ROLES, "target()(address)")

alw = [p.strip().split()[0] for p in allowance_raw.split("\n")] if allowance_raw else []
refill, max_refill, period, balance, timestamp = (alw + [None] * 5)[:5]
non_refilling = refill == "0" and period == "0"

roles_read = all(x is not None for x in (allowance_raw, roles_owner, roles_avatar, roles_target))
section(
    "roles",
    read=roles_read,
    complete=len(alw) == 5,
    compatible=(
        non_refilling
        and same(roles_owner, SAFE)
        and same(roles_avatar, SAFE)
        and same(roles_target, SAFE)
    ),
    module=ROLES,
    owner=roles_owner,
    avatar=roles_avatar,
    target=roles_target,
    owner_is_safe=same(roles_owner, SAFE),
    avatar_is_safe=same(roles_avatar, SAFE),
    target_is_safe=same(roles_target, SAFE),
    role_key=ROLE_KEY,
    allowance_key=ALLOW_KEY,
    allowance={"refill": refill, "maxRefill": max_refill, "period": period,
               "balance": balance, "timestamp": timestamp},
    non_refilling=non_refilling,
    note="A Roles module whose owner/avatar/target is not the Safe is not this Safe's "
         "module, however well configured it looks. A refilling allowance is refused by "
         "the controller at activation and during operation; read back here rather than "
         "trusted from the setup script.",
)

# ----------------------------------- 3. Morpho grants: history-derived candidates --
# V4 §6 requires candidates from CANONICAL AUTHORIZATION HISTORY plus known identities,
# then mapping readback. Probing a short supplied list is not discovery: a grant to an
# address nobody thought to list is exactly the case that matters.
#
# Morpho emits SetAuthorization(caller, authorizer, authorized, newIsAuthorized). The
# bounded range is the dedicated Safe's own lifetime, floored at the fork's pinned base
# block -- this fixture has no pre-fork history of its own.
SET_AUTH_TOPIC = "0xd4a0d2e71c8a48c73b64c0f9a30d76c4d18cb0e9b12f1f6ec3ba2b9a5e5b2b2a"
FORK_BASE = int(os.environ.get("HELD_FORK_BLOCK", "51353212"))

history_from = FORK_BASE
logs_raw = cast("logs", "--from-block", str(history_from), "--to-block", str(block or "latest"),
                "--address", MORPHO, pin=False, allow_empty=True)
history_read = logs_raw is not None

# Candidates: every address seen in the Safe's authorization history, plus known parties.
candidates: dict[str, str] = {"safe_self": SAFE, "roles_module": ROLES}
if CONTROLLER:
    candidates["held_controller"] = CONTROLLER
for name in ("HELD_RUNNER_A", "HELD_RUNNER_B", "HELD_EXECUTOR"):
    if os.environ.get(name):
        candidates[name.lower()] = os.environ[name]

history_addresses: list[str] = []
if logs_raw:
    for word in re.findall(r"0x[0-9a-fA-F]{64}", logs_raw):
        maybe = "0x" + word[-40:]
        if int(maybe, 16) != 0 and maybe.lower() not in {v.lower() for v in candidates.values()}:
            history_addresses.append(maybe)
for i, a in enumerate(dict.fromkeys(history_addresses)):
    candidates[f"history_{i}"] = a

grants: dict[str, Any] = {}
unreadable: list[str] = []
for label, who in candidates.items():
    val = parse_bool(cast("call", MORPHO, "isAuthorized(address,address)(bool)", SAFE, who))
    if val is None:
        unreadable.append(label)
        grants[label] = "UNREADABLE"
    else:
        grants[label] = val

external = [k for k, v in grants.items() if v is True and k != "safe_self"]
section(
    "morpho_grants",
    read=history_read and not unreadable,
    complete=history_read,
    compatible=not external,
    history_range={"from_block": history_from, "to_block": int(block) if block else None,
                   "readable": history_read},
    candidates=candidates,
    candidates_from_history=len(history_addresses),
    grants=grants,
    unreadable=unreadable,
    external_delegates=external,
    note="Candidates come from the Safe's bounded authorization history PLUS known "
         "identities, then mapping readback -- not from a hand-supplied list. Malformed "
         "output is UNREADABLE, never False. BOUNDARY: completeness is bounded by the "
         "history range above; this does not enumerate every address on the chain.",
)

# ----------------------------------------------- 4. token approvals / Permit2 -----
approvals: dict[str, Any] = {}
approvals_unreadable: list[str] = []
spenders = [("morpho", MORPHO), ("roles", ROLES), ("permit2", PERMIT2)]
if CONTROLLER:
    spenders.append(("held_controller", CONTROLLER))
for label, spender in spenders:
    res = cast("call", USDC, "allowance(address,address)(uint256)", SAFE, spender)
    if res is None:
        approvals_unreadable.append(label)
        approvals[label] = "UNREADABLE"
    else:
        approvals[label] = res.split()[0]

nonzero = [k for k, v in approvals.items() if v not in ("0", "UNREADABLE")]
section(
    "token_approvals",
    read=not approvals_unreadable,
    complete=not approvals_unreadable,
    compatible=not nonzero,
    token=USDC,
    allowances=approvals,
    unreadable=approvals_unreadable,
    nonzero=nonzero,
    note="The managed Safe->Morpho allowance must be zero at rest; the controller also "
         "requires it zero on entry and exit of every operation.",
)

# ------------------------------------------- 5. the paused Held installation ------
if CONTROLLER:
    active = parse_bool(cast("call", CONTROLLER, "active()(bool)"))
    epoch = cast("call", CONTROLLER, "epoch()(uint64)")
    c_safe = cast("call", CONTROLLER, "safe()(address)")
    c_roles = cast("call", CONTROLLER, "roles()(address)")
    c_morpho = cast("call", CONTROLLER, "morpho()(address)")
    c_token = cast("call", CONTROLLER, "token()(address)")
    used = {n: cast("call", CONTROLLER, f"{n}()(uint128)")
            for n in ("usedSupply", "usedNormalWithdraw", "usedRestoration")}
    counts = {n: cast("call", CONTROLLER, f"{n}()(uint64)")
              for n in ("normalCount", "restorationCount")}
    reads = [active, epoch, c_safe, c_roles, c_morpho, c_token,
             *used.values(), *counts.values()]
    zeroed = all(v is not None and v.split()[0] == "0" for v in
                 list(used.values()) + list(counts.values()))
    section(
        "held_controller",
        read=all(v is not None for v in reads),
        complete=len(used) == 3 and len(counts) == 2,
        compatible=(
            active is False
            and epoch is not None and epoch.split()[0] == "0"
            and same(c_safe, SAFE) and same(c_roles, ROLES)
            and same(c_morpho, MORPHO) and same(c_token, USDC)
            and zeroed
        ),
        address=CONTROLLER,
        active=active,
        epoch=epoch,
        bindings={"safe": c_safe, "roles": c_roles, "morpho": c_morpho, "token": c_token},
        consumption={**used, **counts},
        consumption_all_zero=zeroed,
        note="Initial activation requires a PAUSED, never-active controller at epoch 0 "
             "with zero consumption and immutable bindings pointing at this installation "
             "(V4 §6). A controller that is already active, or bound elsewhere, is not a "
             "fresh installation.",
    )
else:
    section(
        "held_controller",
        read=False, complete=False, compatible=False,
        address=None,
        note="NO HELD CONTROLLER SUPPLIED. The previous rehearsal inspected only the P00 "
             "native Safe/Roles fixture and still reported COMPLETE, which could not "
             "establish the paused initial state, immutable scope, controller-only roles "
             "or budget dimensions it claimed. Set HELD_CONTROLLER to the deployed paused "
             "installation.",
    )

# ------------------------------------- 6. runner / executor identities -----------
section(
    "identities",
    read=safe_read,
    complete=bool(owners) and roles_owner is not None,
    compatible=True,
    public_chain_facts={"safe_owners": owners, "threshold": threshold,
                        "roles_owner": roles_owner},
    attested_not_verified={
        "statement": "Control of the runner and executor keys, and of any KeeperHub "
                     "organisation credential, is ATTESTED and NOT verified here.",
        "why": "Public chain data cannot prove private-key ownership. V4 §6 requires this "
               "distinction to be explicit rather than folded into the chain findings.",
        "fork_note": "Every key in this fixture is a well-known anvil account. It is not "
                     "custody and proves nothing about a production installation.",
    },
    note="Completeness here depends on the SAFE section's reads; it is no longer hardcoded "
         "True, which made this section incapable of failing.",
)

# -------------------------------------------------------------------- verdict ----
report["verdict"] = {
    "all_sections_complete": not failures,
    "incomplete_sections": failures,
    "activation_would_be": "BLOCKED" if failures else "PERMITTED BY THIS CHECKLIST",
    "important": "'PERMITTED BY THIS CHECKLIST' means the declared sections read clean at "
                 "this observation point on a FORK, within the declared history range. It "
                 "is not authorization, not finality, and not evidence about the public "
                 "installation.",
}

os.makedirs("evidence/P03", exist_ok=True)
with open("evidence/P03/bootstrap-rehearsal.json", "w") as fh:
    json.dump(report, fh, indent=1)

print(f"\nverdict: {report['verdict']['activation_would_be']}")
if failures:
    print(f"incomplete: {failures}")
print("wrote evidence/P03/bootstrap-rehearsal.json")
sys.exit(1 if failures else 0)
