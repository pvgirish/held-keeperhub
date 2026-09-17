#!/usr/bin/env python3
"""Collect the bounded bootstrap checklist by READING the chain. Rehearsal only.

Every value is read with `cast` from the running fork, PINNED to one observation block.
Nothing is taken from the fixture scripts' own output: the checklist's job is to verify
the installation independently of whatever built it.

## Three separate questions, never conflated

An earlier version reported COMPLETE in fourteen scripted situations that should have
blocked. Its predicates did not check what the prose above them claimed. So every section
answers three questions separately and a failure of ANY of them blocks:

  READ        did the query return usable data at all?
  COMPLETE    is every required field present?
  COMPATIBLE  does it match the supported profile?

A section that cannot distinguish "read failed" from "read fine, value is wrong" cannot be
trusted to block, and V4 §6 says incomplete evidence blocks activation.

## Against the DECLARED installation, not against whatever is there

The review of 67eed71 found four more ways this still permitted what it should refuse: an
unreviewed nonzero fallback handler, an unsupported Safe version, a successful `cast`
returning garbage where logs should be, and an allowance tuple whose balance was not a
number. Each was read and then not judged. So:

  * Values are TYPED on the way in. `uint()` returns None for anything that is not a
    decimal integer, and None is unreadable -- never zero.
  * Implementations are matched against a declared supported profile. A readable value is
    not an approved one.
  * The `SetAuthorization` event is DECODED from its real topic, and the authorizer is
    checked to be this Safe. The previous code regex-scraped the last 20 bytes of every
    32-byte word in every Morpho log, which produced truncated market ids and unrelated
    hashes as "candidates" -- and its declared SET_AUTH_TOPIC constant was never used and
    was, in fact, the wrong hash.
  * The checklist reads the FULL declared installation -- both roles, their members and
    conditions, all five budgets, the market and the lineage -- from a manifest written
    before the fact. Required configuration that is missing is INCOMPLETE, never inferred.

## Scope, stated rather than implied

REHEARSAL against the Base-mainnet FORK. Not public-Safe activation evidence; not the P04
automated authority service; not finality evidence -- an anvil fork has none.
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
MANIFEST_PATH = os.environ.get("HELD_INSTALL_MANIFEST")

MORPHO = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
COLL = "0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452"
ORACLE = "0xD7A1abA119a236Fea5BBC5cAC6836465cbe9289A"
IRM = "0x46415998764C29aB2a25CbeA6254146D50D22687"
LLTV = 860000000000000000
PERMIT2 = "0x000000000022D473030F116dDEE9F6B43aC78BA3"
SENTINEL = "0x0000000000000000000000000000000000000001"
ZERO = "0x0000000000000000000000000000000000000000"

GUARD_SLOT = "0x4a204f620c8c5ccdca3fd54d003badd85ba500436a431f0cbda4f558c93c34c8"
FALLBACK_SLOT = "0x6c9a6c4a39284e37ed1cf53d337577d14212a4870fb976a4366c693b939918d5"

# The DECLARED supported profile. Deviations are incompatible, not merely interesting.
EXPECTED_CHAIN_ID = 8453
EXPECTED_THRESHOLD = 2
EXPECTED_OWNER_COUNT = 3
# A readable implementation is not an approved one. An unsupported version blocks.
SUPPORTED_SAFE_VERSIONS = {"1.4.1"}
# The fallback handler is part of the Safe's call surface. "Unset" is the reviewed profile
# here; an unreviewed handler is not allowed merely because its storage slot was readable.
SUPPORTED_FALLBACK_HANDLERS = {ZERO.lower()}

# Morpho: SetAuthorization(address indexed caller, address indexed authorizer,
#                          address indexed authorized, bool newIsAuthorized)
# Verified with `cast keccak "SetAuthorization(address,address,address,bool)"`. The
# constant this file used to carry (0xd4a0d2e7...) was not this hash and was never used.
SET_AUTH_TOPIC = "0xd5e969f01efe921d3f766bdebad25f0a05e3f237311f56482bf132d0326309c0"

# Roles v2 error selectors, each confirmed with `cast 4byte`. These are what make the
# permission layer separable from the economic one: a probe that only saw "execution
# reverted" would read a Safe with no token approval -- the required resting state -- as a
# condition failure, and would have reported the installation broken.
NO_MEMBERSHIP = "0xfd8e9f28"       # NoMembership()
CONDITION_VIOLATION = "0xd0a9bf58"  # ConditionViolation(uint8,bytes32)
MODULE_TX_FAILED = "0xd27b44a9"     # ModuleTransactionFailed()

# Roles let the call through; only the inner protocol call failed. For a permission
# checklist this is a PASS: membership and every condition were satisfied.
PERMITTED_OUTCOMES = ("PERMITTED", "PERMITTED_INNER_FAILED")

BLOCK: str | None = None
report: dict[str, Any] = {}
failures: list[str] = []
clauses: list[dict[str, Any]] = []
_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
_UINT = re.compile(r"^\d+$")
_B32 = re.compile(r"^0x[0-9a-fA-F]{64}$")


def cast(*args: str, pin: bool = True, allow_empty: bool = False) -> str | None:
    """Run cast against the observation block. None means the read FAILED.

    `allow_empty` distinguishes "the query failed" from "the query succeeded and there is
    nothing there". An empty LOG range is a real answer; an empty `call` result is not.
    Collapsing the two would make a failed read look like a clean installation.
    """
    cmd = ["cast", *args, "--rpc-url", RPC]
    if pin and BLOCK is not None and args[0] in ("call", "storage", "logs"):
        cmd += ["--block", BLOCK] if args[0] != "logs" else []
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        return None
    text = out.stdout.strip()
    if not text and not allow_empty:
        return None
    return text


def cast_local(*args: str) -> str | None:
    """Run a PURE cast subcommand -- one that encodes rather than queries.

    `cast calldata` takes no `--rpc-url` and errors if given one, which silently turned
    every probe encoding into None and made the membership section look like it simply had
    nothing to run.
    """
    out = subprocess.run(["cast", *args], capture_output=True, text=True)
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def section(name: str, *, read: bool, complete: bool, compatible: bool, **data: Any) -> None:
    ok = read and complete and compatible
    report[name] = {"read": read, "complete": complete, "compatible": compatible,
                    "verdict": "COMPLETE" if ok else "INCOMPLETE", **data}
    print(f"  [{'COMPLETE  ' if ok else 'INCOMPLETE'}] {name}"
          + ("" if ok else f"   (read={read} complete={complete} compatible={compatible})"))
    if not ok:
        failures.append(name)


def clause(obligation: str, *, section_name: str, satisfied: bool, evidence: str) -> None:
    """One V4 §6 / P03 item 6 obligation and the evidence for it.

    A field appearing in a report is not proof it is checked, so every obligation names
    the specific reading that answers it and whether that reading actually passed.
    """
    clauses.append({"obligation": obligation, "section": section_name,
                    "satisfied": satisfied, "evidence": evidence})


# ------------------------------------------------------------------- typed readers --
def uint(raw: str | None) -> int | None:
    """Strictly a decimal integer. Anything else is None -- NOT zero.

    `cast` prints a uint as "123" or "123 [1.23e2]"; a malformed response is whatever the
    contract returned. Reading 'not-a-number' as 0 is how a garbled quota passed as an
    empty one.
    """
    if raw is None:
        return None
    head = raw.strip().split()[0] if raw.strip() else ""
    return int(head) if _UINT.match(head) else None


def parse_bool(raw: str | None) -> bool | None:
    """Strictly boolean. Malformed output is None -- NOT False."""
    if raw is None:
        return None
    v = raw.strip().lower()
    if v in ("true", "false"):
        return v == "true"
    return None


def parse_addr(raw: str | None) -> str | None:
    if raw is None:
        return None
    head = raw.strip().split()[0] if raw.strip() else ""
    return head if _ADDR.match(head) else None


def parse_b32(raw: str | None) -> str | None:
    if raw is None:
        return None
    head = raw.strip().split()[0] if raw.strip() else ""
    return head.lower() if _B32.match(head) else None


def addr_from_word(word: str | None) -> str | None:
    if not word or not _B32.match(word.strip().split()[0] if word.strip() else ""):
        return None
    return "0x" + word.strip().split()[0][-40:]


def same(a: str | None, b: str | None) -> bool:
    return bool(a and b and a.lower() == b.lower())


def read_allowance(key: str) -> dict[str, Any]:
    """Read one native allowance, TYPED. Any non-numeric field makes it unreadable."""
    raw = cast("call", ROLES, "allowances(bytes32)(uint128,uint128,uint64,uint128,uint64)", key)
    if raw is None:
        return {"key": key, "readable": False, "reason": "the allowances() call failed"}
    parts = [uint(p) for p in raw.split("\n")]
    if len(parts) != 5 or any(p is None for p in parts):
        return {"key": key, "readable": False,
                "reason": f"allowances() returned {len(parts)} field(s) that did not all "
                          "parse as integers; a malformed quota is unreadable, not zero",
                "raw": raw}
    refill, max_refill, period, balance, timestamp = parts
    return {"key": key, "readable": True, "refill": refill, "maxRefill": max_refill,
            "period": period, "balance": balance, "timestamp": timestamp,
            "non_refilling": refill == 0 and period == 0}


def simulate_role_call(sender: str, target: str, inner: str, role_key: str) -> dict[str, Any]:
    """Ask the Roles module, read-only, whether this sender may make this exact call.

    This is how membership AND the condition tree are verified together. Roles v2 keeps
    membership in an internal mapping with no getter, so there is nothing to read back;
    what CAN be established is the behaviour that membership and the conditions produce.

    Returns the outcome class rather than a bare bool, because "refused for no membership"
    and "refused by a condition" are different findings and must not be merged.
    """
    data = cast_local("calldata",
                      "execTransactionWithRoleReturnData(address,uint256,bytes,uint8,bytes32,bool)",
                      target, "0", inner, "0", role_key, "true")
    if data is None:
        return {"outcome": "UNREADABLE", "reason": "could not encode the probe calldata"}
    payload = json.dumps({"from": sender, "to": ROLES, "data": data, "gasPrice": "0x0"})
    # eth_call takes a block QUANTITY (hex) or a tag; a decimal block number is rejected
    # outright by the node, which surfaces as UNREADABLE rather than as a false refusal.
    at = hex(uint(BLOCK)) if uint(BLOCK) is not None else "latest"
    out = subprocess.run(["cast", "rpc", "eth_call", payload, at,
                          "--rpc-url", RPC], capture_output=True, text=True)
    blob = (out.stdout + out.stderr).strip()
    if out.returncode == 0:
        return {"outcome": "PERMITTED"}
    detail = blob.split("\n")[0][:200]
    if NO_MEMBERSHIP in blob:
        return {"outcome": "NO_MEMBERSHIP", "selector": NO_MEMBERSHIP, "detail": detail}
    if CONDITION_VIOLATION in blob:
        return {"outcome": "REFUSED_BY_CONDITION", "selector": CONDITION_VIOLATION,
                "detail": detail}
    if MODULE_TX_FAILED in blob:
        # Membership and every condition passed; Morpho itself reverted. On a Safe at rest
        # that is expected -- the USDC approval is zero until an operation grants it.
        return {"outcome": "PERMITTED_INNER_FAILED", "selector": MODULE_TX_FAILED,
                "detail": detail}
    if "Insufficient funds" in blob:
        return {"outcome": "UNREADABLE",
                "reason": "the sender holds no gas, so the probe never reached the Roles "
                          "module; this cannot distinguish refusal from inability to ask"}
    # An unrecognised revert is NOT quietly filed as a condition refusal. Guessing here is
    # how an unconfigured tree would have looked like a working one.
    return {"outcome": "UNREADABLE",
            "reason": f"unrecognised revert, not classified: {detail}"}


def morpho_call(fn: str, *args: str) -> str | None:
    return cast("call", MORPHO, fn, *args)


# ------------------------------------------------------- 0. the observation point --
block = cast("block-number", pin=False)
chain_id = cast("chain-id", pin=False)
BLOCK = block
block_hash = cast("block", block, "--field", "hash", pin=False) if block else None

chain_ok = uint(chain_id) == EXPECTED_CHAIN_ID
section(
    "observation",
    read=block is not None and chain_id is not None,
    complete=block_hash is not None,
    compatible=chain_ok,
    block_number=uint(block),
    block_hash=block_hash,
    chain_id=uint(chain_id),
    expected_chain_id=EXPECTED_CHAIN_ID,
    all_state_reads_pinned_to_block=True,
    finality="NONE — anvil fork. This is the observation point, not finalized evidence.",
    scope="FORK REHEARSAL. Not the public installation, not the P04 automated service.",
)
clause("One stated observation block for every state read",
       section_name="observation", satisfied=chain_ok and block_hash is not None,
       evidence=f"block {block} on chain {chain_id}; every call/storage read pinned to it")

# ------------------------------------------- the DECLARED installation (manifest) --
# The checklist compares live state against terms stated BEFORE the fact. Without them it
# can only describe what it found, which is how "all five sections COMPLETE" was reported
# for an installation that had none of the five budgets configured.
manifest: dict[str, Any] = {}
manifest_error: str | None = None
if not MANIFEST_PATH:
    manifest_error = "HELD_INSTALL_MANIFEST is not set"
elif not os.path.exists(MANIFEST_PATH):
    manifest_error = f"{MANIFEST_PATH} does not exist"
else:
    try:
        with open(MANIFEST_PATH) as fh:
            manifest = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        manifest_error = f"{MANIFEST_PATH} could not be parsed: {exc}"

REQUIRED_MANIFEST = (
    "controller", "normalRole", "restorationRole", "supplyAmountKey", "normalWithdrawKey",
    "restorationKey", "normalCountKey", "restorationCountKey", "supplyAmountLimit",
    "normalWithdrawLimit", "restorationLimit", "normalCountLimit", "restorationCountLimit",
    "marketId", "lineage",
)
missing_terms = [k for k in REQUIRED_MANIFEST if k not in manifest]
section(
    "declared_installation",
    read=manifest_error is None,
    complete=not missing_terms,
    compatible=(manifest_error is None and not missing_terms
                and same(manifest.get("safe"), SAFE) and same(manifest.get("roles"), ROLES)),
    manifest_path=MANIFEST_PATH,
    error=manifest_error,
    missing_terms=missing_terms,
    declared=manifest,
    note="The candidate installation, declared before activation by "
         "script/solidity/InstallPausedHeld.s.sol. Required configuration that is absent "
         "is INCOMPLETE and blocks; it is never inferred from live state, because "
         "inferring it would make the comparison circular.",
)
clause("The intended installation is declared in advance, not inferred",
       section_name="declared_installation",
       satisfied=manifest_error is None and not missing_terms,
       evidence=f"{MANIFEST_PATH or 'no manifest'}: "
                f"{'all required terms present' if not missing_terms else f'missing {missing_terms}'}")

# --------------------------------------------------------- 1. Safe configuration --
owners_raw = cast("call", SAFE, "getOwners()(address[])")
threshold_raw = cast("call", SAFE, "getThreshold()(uint256)")
version_raw = cast("call", SAFE, "VERSION()(string)")
modules_raw = cast("call", SAFE, "getModulesPaginated(address,uint256)(address[],address)",
                   SENTINEL, "20")
guard_word = cast("storage", SAFE, GUARD_SLOT)
fallback_word = cast("storage", SAFE, FALLBACK_SLOT)

owners = [o.strip() for o in (owners_raw or "").strip("[]").replace("\n", "").split(",")
          if _ADDR.match(o.strip())]
modules = [m.strip() for m in (modules_raw or "").split("\n")[0].strip("[]").split(",")
           if _ADDR.match(m.strip())]
threshold = uint(threshold_raw)
version = version_raw.strip().strip('"') if version_raw else None
guard = addr_from_word(guard_word)
fallback = addr_from_word(fallback_word)

recognised = {SAFE.lower(), ROLES.lower()}
if CONTROLLER:
    recognised.add(CONTROLLER.lower())
unrecognised_modules = [m for m in modules if m.lower() not in recognised]
roles_enabled = any(same(m, ROLES) for m in modules)
version_supported = version in SUPPORTED_SAFE_VERSIONS
fallback_supported = fallback is not None and fallback.lower() in SUPPORTED_FALLBACK_HANDLERS

safe_read = all(x is not None for x in
                (owners_raw, threshold_raw, version_raw, modules_raw, guard_word, fallback_word))
section(
    "safe",
    read=safe_read,
    complete=bool(owners) and threshold is not None and guard is not None
    and fallback is not None and version is not None,
    compatible=(
        not unrecognised_modules
        and roles_enabled
        and threshold == EXPECTED_THRESHOLD
        and len(owners) == EXPECTED_OWNER_COUNT
        and same(guard, ZERO)
        and version_supported
        and fallback_supported
    ),
    owners=owners,
    owner_count=len(owners),
    expected_owner_count=EXPECTED_OWNER_COUNT,
    threshold=threshold,
    expected_threshold=EXPECTED_THRESHOLD,
    implementation_version=version,
    implementation_supported=version_supported,
    supported_versions=sorted(SUPPORTED_SAFE_VERSIONS),
    enabled_modules=modules,
    roles_module_enabled=roles_enabled,
    unrecognised_modules=unrecognised_modules,
    guard=guard,
    guard_is_unset=same(guard, ZERO),
    fallback_handler=fallback,
    fallback_supported=fallback_supported,
    supported_fallback_handlers=sorted(SUPPORTED_FALLBACK_HANDLERS),
    note="An UNREADABLE guard or fallback is INCOMPLETE, not 'absent'. A readable one is "
         "not thereby approved: an unreviewed fallback handler extends the Safe's call "
         "surface and an unsupported implementation version is outside the profile this "
         "checklist was written against. Both block (V4 §6).",
)
clause("Safe ownership, threshold and implementation are read and within the profile",
       section_name="safe",
       satisfied=threshold == EXPECTED_THRESHOLD and len(owners) == EXPECTED_OWNER_COUNT
       and version_supported,
       evidence=f"{len(owners)} owners, threshold {threshold}, version {version!r}")
clause("Enabled modules, guard and fallback handler are enumerated and judged",
       section_name="safe",
       satisfied=not unrecognised_modules and roles_enabled and same(guard, ZERO)
       and fallback_supported,
       evidence=f"modules {modules}; guard {guard}; fallback {fallback}")

# ------------------------------------------------------- 2. Roles configuration ---
roles_owner = parse_addr(cast("call", ROLES, "owner()(address)"))
roles_avatar = parse_addr(cast("call", ROLES, "avatar()(address)"))
roles_target = parse_addr(cast("call", ROLES, "target()(address)"))

# ALL FIVE native budget dimensions, from the DECLARED keys. Reading only the environment
# allowance was the defect: five zeroed controller counters are not five allowance checks.
budget_spec = [
    ("supply_amount", "supplyAmountKey", "supplyAmountLimit"),
    ("normal_withdraw_amount", "normalWithdrawKey", "normalWithdrawLimit"),
    ("restoration_amount", "restorationKey", "restorationLimit"),
    ("normal_count", "normalCountKey", "normalCountLimit"),
    ("restoration_count", "restorationCountKey", "restorationCountLimit"),
]
budgets: dict[str, Any] = {}
for label, key_field, limit_field in budget_spec:
    key = parse_b32(manifest.get(key_field))
    if key is None:
        budgets[label] = {"readable": False,
                          "reason": f"the manifest declares no usable {key_field}"}
        continue
    got = read_allowance(key)
    declared = manifest.get(limit_field)
    got["declared_limit"] = declared
    if got.get("readable"):
        got["matches_declared"] = (
            isinstance(declared, int) and got["balance"] == declared
            and got["maxRefill"] == declared)
    budgets[label] = got

budgets_readable = all(b.get("readable") for b in budgets.values())
budgets_match = all(b.get("matches_declared") for b in budgets.values())
budgets_non_refilling = all(b.get("non_refilling") for b in budgets.values())

roles_read = all(x is not None for x in (roles_owner, roles_avatar, roles_target)) and budgets_readable
section(
    "roles",
    read=roles_read,
    complete=len(budgets) == 5 and budgets_readable,
    compatible=(
        budgets_non_refilling
        and budgets_match
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
    environment_role_key=ROLE_KEY,
    environment_allowance_key=ALLOW_KEY,
    budgets=budgets,
    all_five_readable=budgets_readable,
    all_five_match_declared=budgets_match,
    all_five_non_refilling=budgets_non_refilling,
    note="All FIVE declared budget dimensions are read from the manifest's keys and "
         "compared with the declared limits. A tuple whose fields do not parse as "
         "integers is UNREADABLE, never zero. A refilling allowance is refused by the "
         "controller at activation; it is read back here rather than trusted.",
)
clause("Roles implementation owner/avatar/target belong to this Safe",
       section_name="roles",
       satisfied=same(roles_owner, SAFE) and same(roles_avatar, SAFE) and same(roles_target, SAFE),
       evidence=f"owner {roles_owner}, avatar {roles_avatar}, target {roles_target}")
clause("All five native amount/count budgets are read and match the declared installation",
       section_name="roles", satisfied=budgets_readable and budgets_match and budgets_non_refilling,
       evidence=f"{sum(1 for b in budgets.values() if b.get('readable'))}/5 readable, "
                f"{sum(1 for b in budgets.values() if b.get('matches_declared'))}/5 match, "
                f"{sum(1 for b in budgets.values() if b.get('non_refilling'))}/5 non-refilling")

# ------------------------------- 2b. both roles: members and condition trees ------
# Roles v2 has no membership getter, so membership and the condition tree are established
# TOGETHER by simulating the exact calls the installation is supposed to permit and refuse.
mp = f"({USDC},{COLL},{ORACLE},{IRM},{LLTV})"


def encode(sig: str, *args: str) -> str | None:
    return cast_local("calldata", sig, *args)


SUPPLY_SIG = "supply((address,address,address,address,uint256),uint256,uint256,address,bytes)"
WITHDRAW_SIG = "withdraw((address,address,address,address,uint256),uint256,uint256,address,address)"
probe_amount = "1000000"
outsider = manifest.get("retiredMember") or ZERO

role_probes: dict[str, Any] = {}
if CONTROLLER and manifest:
    normal_role = parse_b32(manifest.get("normalRole"))
    restore_role = parse_b32(manifest.get("restorationRole"))
    supply_ok = encode(SUPPLY_SIG, mp, probe_amount, "0", SAFE, "0x")
    withdraw_ok = encode(WITHDRAW_SIG, mp, probe_amount, "0", SAFE, SAFE)
    withdraw_bad = encode(WITHDRAW_SIG, mp, probe_amount, "0", SAFE, outsider)

    if normal_role and restore_role and supply_ok and withdraw_ok and withdraw_bad:
        role_probes["controller_normal_supply"] = {
            "expect": list(PERMITTED_OUTCOMES),
            "why": "the controller is the sole member of the normal role, and the supply tree "
                   "permits this exact shape. The Safe holds no USDC approval at rest, so "
                   "Morpho itself may revert -- that is PERMITTED_INNER_FAILED, not a "
                   "permission failure",
            **simulate_role_call(CONTROLLER, MORPHO, supply_ok, normal_role)}
        role_probes["controller_restoration_withdraw"] = {
            "expect": list(PERMITTED_OUTCOMES),
            "why": "the restoration lane is a separate role, also controller-only",
            **simulate_role_call(CONTROLLER, MORPHO, withdraw_ok, restore_role)}
        role_probes["controller_normal_withdraw_wrong_receiver"] = {
            "expect": ["REFUSED_BY_CONDITION"],
            "why": "the tight tree pins the receiver to the Safe. This is the CONDITION check "
                   "and it must fail with ConditionViolation -- distinct from a membership "
                   "failure and from an inner economic failure",
            **simulate_role_call(CONTROLLER, MORPHO, withdraw_bad, normal_role)}
        if outsider != ZERO:
            role_probes["retired_member_normal_supply"] = {
                "expect": ["NO_MEMBERSHIP"],
                "why": "the previous runner was retired as part of installing this lineage",
                **simulate_role_call(outsider, MORPHO, supply_ok, normal_role)}

probes_readable = bool(role_probes) and all(
    p["outcome"] != "UNREADABLE" for p in role_probes.values())
probes_as_expected = bool(role_probes) and all(
    p["outcome"] in p["expect"] for p in role_probes.values())
section(
    "roles_membership_and_conditions",
    read=probes_readable,
    complete=len(role_probes) >= 3,
    compatible=probes_as_expected,
    probes=role_probes,
    method="Read-only eth_call against the Roles module, from each candidate sender. Roles "
           "v2 keeps membership in an internal mapping with no getter, so what is "
           "established is the BEHAVIOUR that membership plus the condition tree produce. "
           "NO_MEMBERSHIP (0xfd8e9f28) and a condition revert are kept as distinct outcomes: "
           "collapsing them would let an unconfigured tree look like a refusal.",
    limitation="The probe needs the sender to hold gas, because eth_call is balance-checked. "
               "On the fork the controller is given dust for exactly this. A PUBLIC "
               "installation whose controller holds no ETH cannot run this probe, and this "
               "section would be INCOMPLETE there rather than silently passing.",
    note="Both roles are exercised, and a POSITIVE and a NEGATIVE case are required: a "
         "probe set that only ever refuses proves as little as one that only ever permits.",
)
clause("Both Zodiac roles have the intended member, and the condition trees bind",
       section_name="roles_membership_and_conditions",
       satisfied=probes_readable and probes_as_expected,
       evidence="; ".join(f"{k}={v['outcome']}" for k, v in role_probes.items()) or "no probes ran")

# ----------------------------- 3. Morpho grants: DECODED authorization history ----
# V4 §6 requires candidates from CANONICAL AUTHORIZATION HISTORY plus known identities,
# then mapping readback. The previous implementation asked for every Morpho log in the
# range and regex-extracted the last 20 bytes of every 32-byte word, which yielded
# truncated market ids and unrelated hashes as "candidates" -- broad over-collection is not
# a validated interpretation of authorization history.
FORK_BASE = uint(os.environ.get("HELD_FORK_BLOCK")) or 51353212
history_from = FORK_BASE
safe_topic = "0x" + "0" * 24 + SAFE[2:].lower()

# Filter on the real event topic AND on the authorizer being this Safe (topic2).
logs_raw = cast("logs", "--from-block", str(history_from), "--to-block", str(block or "latest"),
                "--address", MORPHO, SET_AUTH_TOPIC, pin=False, allow_empty=True)

history_read = logs_raw is not None
history_wellformed = True
history_events: list[dict[str, Any]] = []
history_malformed: list[str] = []

if logs_raw:
    # `cast logs` prints blocks of "key: value" lines per event. Parse structurally: an
    # event we cannot decode is MALFORMED, not something to scrape words out of.
    for blob in re.split(r"\n(?=- address:|address:)", logs_raw):
        if not blob.strip():
            continue
        topics = re.findall(r"0x[0-9a-fA-F]{64}", blob)
        if len(topics) < 4 or topics[0].lower() != SET_AUTH_TOPIC:
            history_malformed.append(blob.strip()[:160])
            history_wellformed = False
            continue
        _, _caller, authorizer, authorized = topics[0], topics[1], topics[2], topics[3]
        history_events.append({
            "authorizer": "0x" + authorizer[-40:],
            "authorized": "0x" + authorized[-40:],
            "is_this_safe": authorizer.lower() == safe_topic,
        })

# Candidates carry PROVENANCE: where each one came from.
candidates: dict[str, dict[str, str]] = {
    "safe_self": {"address": SAFE, "provenance": "known identity: the managed Safe"},
    "roles_module": {"address": ROLES, "provenance": "known identity: the Zodiac Roles module"},
}
if CONTROLLER:
    candidates["held_controller"] = {"address": CONTROLLER,
                                     "provenance": "known identity: the Held controller"}
for name in ("HELD_RUNNER_A", "HELD_RUNNER_B", "HELD_EXECUTOR"):
    if os.environ.get(name):
        candidates[name.lower()] = {"address": os.environ[name],
                                    "provenance": f"known identity: {name}"}
seen = {c["address"].lower() for c in candidates.values()}
for i, ev in enumerate(e for e in history_events if e["is_this_safe"]):
    if ev["authorized"].lower() not in seen:
        seen.add(ev["authorized"].lower())
        candidates[f"history_{i}"] = {
            "address": ev["authorized"],
            "provenance": "decoded SetAuthorization event with this Safe as authorizer"}

grants: dict[str, Any] = {}
unreadable: list[str] = []
for label, meta in candidates.items():
    val = parse_bool(morpho_call("isAuthorized(address,address)(bool)", SAFE, meta["address"]))
    if val is None:
        unreadable.append(label)
        grants[label] = "UNREADABLE"
    else:
        grants[label] = val

external = [k for k, v in grants.items() if v is True and k != "safe_self"]
section(
    "morpho_grants",
    read=history_read and not unreadable,
    complete=history_read and history_wellformed,
    compatible=not external,
    history_range={"from_block": history_from, "to_block": uint(block),
                   "readable": history_read, "wellformed": history_wellformed},
    topic=SET_AUTH_TOPIC,
    decoded_events=history_events,
    events_for_this_safe=sum(1 for e in history_events if e["is_this_safe"]),
    malformed_entries=history_malformed,
    candidates=candidates,
    grants=grants,
    unreadable=unreadable,
    external_delegates=external,
    note="Candidates come from DECODED SetAuthorization events whose authorizer is this "
         "Safe, plus known identities, then mapping readback at the observation block. "
         "Every candidate carries its provenance. An empty range is a legitimate answer "
         "and is distinguished from output that could not be decoded: the latter is "
         "MALFORMED and blocks. Malformed grant output is UNREADABLE, never False. "
         "BOUNDARY: completeness is bounded by the range above.",
)
clause("Morpho authorization history is decoded from the pinned event, not scraped",
       section_name="morpho_grants", satisfied=history_read and history_wellformed,
       evidence=f"topic {SET_AUTH_TOPIC[:12]}..., {len(history_events)} decoded event(s), "
                f"{len(history_malformed)} malformed")
clause("Every grant candidate is confirmed by mapping readback at the same block",
       section_name="morpho_grants", satisfied=not unreadable and not external,
       evidence=f"{len(candidates)} candidate(s) read back; external delegates {external}")

# ----------------------------------------------- 4. token approvals / Permit2 -----
approvals: dict[str, Any] = {}
approvals_unreadable: list[str] = []
spenders = [("morpho", MORPHO), ("roles", ROLES), ("permit2", PERMIT2)]
if CONTROLLER:
    spenders.append(("held_controller", CONTROLLER))
for label, spender in spenders:
    res = uint(cast("call", USDC, "allowance(address,address)(uint256)", SAFE, spender))
    if res is None:
        approvals_unreadable.append(label)
        approvals[label] = "UNREADABLE"
    else:
        approvals[label] = res

nonzero = [k for k, v in approvals.items() if isinstance(v, int) and v != 0]
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
         "requires it zero on entry and exit of every operation. An allowance that does "
         "not parse as an integer is UNREADABLE, not zero.",
)
clause("Relevant token approvals and delegated spend paths are enumerated",
       section_name="token_approvals", satisfied=not approvals_unreadable and not nonzero,
       evidence=f"USDC allowances {approvals}")

# ------------------------------------------- 5. the paused Held installation ------
if CONTROLLER:
    active = parse_bool(cast("call", CONTROLLER, "active()(bool)"))
    epoch = uint(cast("call", CONTROLLER, "epoch()(uint64)"))
    bound = {n: parse_addr(cast("call", CONTROLLER, f"{n}()(address)"))
             for n in ("safe", "roles", "morpho", "token", "owner")}
    scope = {n: parse_b32(cast("call", CONTROLLER, f"{n}()(bytes32)"))
             for n in ("marketId", "lineage")}
    # The controller's OWN key immutables, compared with the declared installation. The
    # old helper deployed a controller bound to keys nothing on the Roles side configured,
    # and reading those keys back would have returned zero for every dimension.
    key_fields = {
        "normalRoleKey": "normalRole", "restorationRoleKey": "restorationRole",
        "supplyAllowanceKey": "supplyAmountKey", "normalWithdrawAllowanceKey": "normalWithdrawKey",
        "restorationAllowanceKey": "restorationKey", "normalCountKey": "normalCountKey",
        "restorationCountKey": "restorationCountKey",
    }
    ckeys = {n: parse_b32(cast("call", CONTROLLER, f"{n}()(bytes32)")) for n in key_fields}
    key_mismatches = [n for n, field in key_fields.items()
                      if not same(ckeys.get(n), parse_b32(manifest.get(field)))]

    used = {n: uint(cast("call", CONTROLLER, f"{n}()(uint128)"))
            for n in ("usedSupply", "usedNormalWithdraw", "usedRestoration")}
    counts = {n: uint(cast("call", CONTROLLER, f"{n}()(uint64)"))
              for n in ("normalCount", "restorationCount")}
    consumption = {**used, **counts}
    zeroed = all(v == 0 for v in consumption.values())

    market_ok = same(scope.get("marketId"), parse_b32(manifest.get("marketId")))
    lineage_ok = same(scope.get("lineage"), parse_b32(manifest.get("lineage")))

    reads = [active, epoch, *bound.values(), *scope.values(), *ckeys.values(),
             *consumption.values()]
    section(
        "held_controller",
        read=all(v is not None for v in reads),
        complete=len(consumption) == 5 and len(ckeys) == 7 and all(v is not None for v in ckeys.values()),
        compatible=(
            active is False
            and epoch == 0
            and same(bound["safe"], SAFE) and same(bound["roles"], ROLES)
            and same(bound["morpho"], MORPHO) and same(bound["token"], USDC)
            and market_ok and lineage_ok
            and not key_mismatches
            and zeroed
        ),
        address=CONTROLLER,
        active=active,
        epoch=epoch,
        bindings=bound,
        scope=scope,
        market_matches_declared=market_ok,
        lineage_matches_declared=lineage_ok,
        controller_keys=ckeys,
        key_mismatches=key_mismatches,
        consumption=consumption,
        consumption_all_zero=zeroed,
        note="Initial activation requires a PAUSED, never-active controller at epoch 0 with "
             "zero consumption across ALL FIVE dimensions, immutable bindings pointing at "
             "this installation, and the market and lineage the installation declared "
             "(V4 §6). The controller's seven key immutables are compared with the declared "
             "keys: a controller bound to budget keys the Roles side never configured would "
             "read zero everywhere and look clean.",
    )
    clause("The controller is paused at epoch 0 with zero consumption in all five dimensions",
           section_name="held_controller", satisfied=active is False and epoch == 0 and zeroed,
           evidence=f"active={active}, epoch={epoch}, consumption={consumption}")
    clause("Controller scope, market, lineage and all seven budget keys match the declaration",
           section_name="held_controller",
           satisfied=market_ok and lineage_ok and not key_mismatches,
           evidence=f"market {market_ok}, lineage {lineage_ok}, key mismatches {key_mismatches}")
else:
    section(
        "held_controller",
        read=False, complete=False, compatible=False,
        address=None,
        note="NO HELD CONTROLLER SUPPLIED. A rehearsal that inspects only the P00 native "
             "Safe/Roles fixture cannot establish the paused initial state, immutable "
             "scope, controller-only roles or budget dimensions. Set HELD_CONTROLLER.",
    )
    clause("The controller is paused at epoch 0 with zero consumption in all five dimensions",
           section_name="held_controller", satisfied=False, evidence="no controller supplied")
    clause("Controller scope, market, lineage and all seven budget keys match the declaration",
           section_name="held_controller", satisfied=False, evidence="no controller supplied")

# ------------------------------------- 6. runner / executor identities -----------
# The SELECTED operating identities, not the Safe's owners. Recording owners here and
# calling it complete was the defect: owners are a different clause, already covered above.
selected = {name: os.environ.get(f"HELD_{name.upper()}")
            for name in ("runner", "executor")}
missing_identities = [k for k, v in selected.items() if not v]
section(
    "identities",
    read=safe_read,
    complete=not missing_identities,
    compatible=not missing_identities,
    selected_operating_identities=selected,
    missing=missing_identities,
    public_chain_facts={"safe_owners": owners, "threshold": threshold, "roles_owner": roles_owner},
    attested_not_verified={
        "statement": "Control of the runner and executor keys, and of any KeeperHub "
                     "organisation credential, is ATTESTED and NOT verified here.",
        "why": "Public chain data cannot prove private-key ownership. V4 §6 requires this "
               "distinction to be explicit rather than folded into the chain findings.",
        "fork_note": "Every key in this fixture is a well-known anvil account. It is not "
                     "custody and proves nothing about a production installation.",
    },
    note="An installation whose operating identities have not been SELECTED is incomplete, "
         "and says so, rather than reporting the Safe's owners and calling that the same "
         "question. The KeeperHub organisation identity is unresolved (L10), so this "
         "section is expected to be INCOMPLETE until it is chosen and separately attested.",
)
clause("Selected runner/executor identities are stated, with attested control kept distinct",
       section_name="identities", satisfied=not missing_identities,
       evidence=f"selected {selected}; missing {missing_identities}")

# -------------------------------------------------------------------- verdict ----
unsatisfied = [c["obligation"] for c in clauses if not c["satisfied"]]
report["clause_to_evidence"] = clauses
report["verdict"] = {
    "all_sections_complete": not failures,
    "incomplete_sections": failures,
    "obligations_total": len(clauses),
    "obligations_satisfied": len(clauses) - len(unsatisfied),
    "obligations_unsatisfied": unsatisfied,
    "activation_would_be": "BLOCKED" if failures else "PERMITTED BY THIS CHECKLIST",
    "important": "'PERMITTED BY THIS CHECKLIST' means the declared sections read clean at "
                 "this observation point on a FORK, within the declared history range. It "
                 "is not authorization, not finality, and not evidence about the public "
                 "installation.",
}

print()
print(f"clause-to-evidence: {len(clauses) - len(unsatisfied)}/{len(clauses)} obligations satisfied")
for c in clauses:
    if not c["satisfied"]:
        print(f"  UNSATISFIED  {c['obligation']}  ({c['evidence']})")
print()
print(f"verdict: {report['verdict']['activation_would_be']}")

os.makedirs("evidence/P03", exist_ok=True)
with open("evidence/P03/bootstrap-rehearsal.json", "w") as fh:
    json.dump(report, fh, indent=2, sort_keys=False)
    fh.write("\n")
print("wrote evidence/P03/bootstrap-rehearsal.json")

sys.exit(1 if failures else 0)
