#!/usr/bin/env python3
"""The complete M1 ceremony, rehearsed on a fresh pinned fork with the FINAL identities.

Every earlier fork run used anvil's deterministic accounts. This one uses the addresses
that will actually appear on Base: the three real owners, the real runner B, and
KeeperHub's real managed signer. Nothing about the sequence is simplified for the
rehearsal, because the point is to find what breaks BEFORE money is involved.

## What is different from every previous fork run, and why it matters

Previous fixtures impersonated the SAFE and broadcast the whole installation as it. That
is a fork-only shortcut and it skips the thing most likely to go wrong on mainnet: on
Base, the Safe is a contract, and every one of the 15 ceremony actions has to arrive
through `execTransaction` carrying two of three owner signatures. A rehearsal that
impersonates the Safe proves the calldata is right and proves nothing about the governance
path that has to carry it.

So this runs the REAL Safe path. Each owner action is:

    getTransactionHash(...) -> owner B approveHash -> owner A approveHash -> execTransaction

using Safe's pre-validated signature form (`v = 1`, `r = owner`, `s = 0`), which requires
the owner to have called `approveHash` from their own address and requires NO private key.
That matters here beyond convenience: **this session holds no owner key and asks for
none.** Impersonation on a fork is not a signature and cannot become one.

## What this establishes, and what it cannot

EVIDENCE GRADE: **REAL LOCAL FORK.** It establishes that the sequence, the calldata, the
budgets, the activation guards and the two refusals behave as the submission claims, with
the final addresses. It establishes nothing about any public chain: no contract here has
an address on Base, nothing is funded with real money, and the USDC is written directly
into the fork's storage. It is a rehearsal, and the report says so on every row.

The one substitution is stated rather than hidden: if `$HELD_RUNNER_B_KEY` is absent the
run falls back to an anvil account for the runner signature and marks
`runner_is_final_identity: false`, because a rehearsal that quietly swapped an identity
would be worse than one that could not run.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("adapter", "packages/core", "packages/handover", "packages/authority", "script"):
    sys.path.insert(0, os.path.join(ROOT, p))

RPC = os.environ["HELD_BASE_RPC"]
FOUNDRY = {"PATH": f"{os.path.expanduser('~')}/.foundry/bin:{os.environ.get('PATH', '')}"}

# ------------------------------------------------------------- FINAL identities --
OWNER_A = "0x9c7bfBb4aBcF2C901a395B81cFcC3De4b214b522"
OWNER_B = "0x29fcC6F012b580d4C67C128b8fDf84B105C9489C"
OWNER_C = "0xD1665C7F598d3905CF76698cd35cC459555926a0"
THRESHOLD = 2
RUNNER_B = "0xEc31ACd93c694c21Db63918B442c73C224080A83"
EXECUTOR = "0x24192B75e297dC1c7a42DcB8C04227818E78acd0"
SALT_NONCE = 20260918

# Canonical Base contracts, present in the fork because it is a fork of Base.
SAFE_SINGLETON = "0x41675C099F32341bf84BFc5382aF534df5C7461a"
SAFE_FACTORY = "0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67"
ZODIAC_FACTORY = "0x000000000000aDdB49795b0f9bA5BC298cDda236"
ROLES_MASTERCOPY = "0x9646fDAD06d3e24444381f44362a3B0eB343D337"
MORPHO = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
COLL = "0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452"
ORACLE = "0xD7A1abA119a236Fea5BBC5cAC6836465cbe9289A"
IRM = "0x46415998764C29aB2a25CbeA6254146D50D22687"
LLTV = 860000000000000000
MARKET = (USDC, COLL, ORACLE, IRM, LLTV)
MARKET_ID = "0x13c42741a359ac4a8aa8287d2be109dcf28344484f91185f9a79bd5a805a55ae"
LINEAGE = "0x" + "0" * 62 + "11"
ZERO = "0x" + "0" * 40
USDC_SLOT = 9

# The two keys the owner committed in advance; immutable in the controller's constructor
# from the moment it is deployed (M1-IRREVERSIBLE-PREFLIGHT step 3).
NORMAL_ROLE = "0xa42add86bc83e750f3ba8a53e81130e2d15a08595fe423aaf8ee7235220647cf"
SUPPLY_KEY = "0x771a9951d46e5791484c6fa37347ab116c902522956e3d9a9f33bd787ec63cb2"

# The approved activation policy, M1-OWNER-RUN-SEQUENCE step 8.
POLICY = dict(Ls=50_000_000_000, Ln=50_000_000_000, Lr=10_000_000_000,
              Ms=10_000_000, Mn=100_000_000, Mr=1_000_000,
              ms=10_000_000, mn=1_000_000, F=1_000_000, H=0,
              Nn=10, Nr=5, dn=0, dr=0)
POLICY_ORDER = ("Ls", "Ln", "Lr", "Ms", "Mn", "Mr", "ms", "mn", "F", "H",
                "Nn", "Nr", "dn", "dr")

SAFE_FUNDING = 11_000_000      # exactly 11.000000 USDC, and the figure matters
SUPPLY_AMOUNT = 10_000_000     # the one supply

# A funded anvil account, used ONLY to pay gas for deployments and to relay
# execTransaction. It owns nothing, signs nothing, and holds no authority: the Safe's
# owners are the three real addresses above, and every owner act is approved by them.
RELAY_PK = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
RELAY = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FALLBACK_RUNNER_KEY = "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6"
FALLBACK_RUNNER = "0x90F79bf6EB2c4f870365E785982E1f101E93b906"

OUT = os.path.join(ROOT, "evidence", "M1", "final-fork-rehearsal.json")

RECORD: dict = {
    "schema": "held.final-fork-rehearsal.v1",
    "evidence_grade": "REAL LOCAL FORK",
    "label": "FORK",
    "is_public_mainnet_proof": False,
    "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "identities": {"ownerA": OWNER_A, "ownerB": OWNER_B, "ownerC": OWNER_C,
                   "threshold": THRESHOLD, "runnerB": RUNNER_B, "executor": EXECUTOR,
                   "saltNonce": SALT_NONCE},
    "steps": [], "addresses": {}, "gas": {}, "state": {}, "refusals": {},
    "claim_comparison": [], "problems": [],
}


class RehearsalFailed(Exception):
    pass


def step(name: str, **fields) -> None:
    RECORD["steps"].append({"step": name, **fields})
    detail = " ".join(f"{k}={v}" for k, v in fields.items() if k != "gas")
    print(f"  [ok] {name}" + (f" — {detail}" if detail else ""))


def problem(what: str) -> None:
    RECORD["problems"].append(what)
    print(f"  [PROBLEM] {what}")


# ----------------------------------------------------------------------- cast --
def cast(*args: str, check: bool = True) -> str:
    out = subprocess.run(["cast", *args, "--rpc-url", RPC], capture_output=True,
                         text=True, env={**os.environ, **FOUNDRY})
    if check and out.returncode != 0:
        raise RehearsalFailed(f"cast {' '.join(args[:3])}: {out.stderr.strip()[:300]}")
    return out.stdout.strip()


def cast_local(*args: str) -> str:
    out = subprocess.run(["cast", *args], capture_output=True, text=True,
                         env={**os.environ, **FOUNDRY})
    if out.returncode != 0:
        raise RehearsalFailed(f"cast {' '.join(args[:2])}: {out.stderr.strip()[:300]}")
    return out.stdout.strip()


def uint(raw: str) -> int:
    return int(raw.split()[0]) if raw else 0


def rpc(method: str, *params: str) -> str:
    return cast("rpc", method, *params)


def impersonate(addr: str, ether: str = "0xDE0B6B3A7640000") -> None:
    rpc("anvil_impersonateAccount", addr)
    rpc("anvil_setBalance", addr, ether)


def send_from(sender: str, to: str, sig: str, *args: str) -> dict:
    """A transaction from an IMPERSONATED account. No key exists for these addresses."""
    cmd = ["cast", "send", to, sig, *args, "--from", sender, "--unlocked",
           "--rpc-url", RPC, "--json"]
    out = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **FOUNDRY})
    if out.returncode != 0 or not out.stdout.strip():
        raise RehearsalFailed(f"send from {sender[:10]} to {to[:10]} {sig[:30]}: "
                              f"{out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


def send_key(pk: str, to: str, sig: str, *args: str) -> dict:
    cmd = ["cast", "send", to, sig, *args, "--private-key", pk, "--rpc-url", RPC, "--json"]
    out = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **FOUNDRY})
    if out.returncode != 0 or not out.stdout.strip():
        why = (out.stderr or "").strip() or (out.stdout or "").strip()
        raise RehearsalFailed(f"send to {to[:10]} {sig[:30]}: {why[:600] or 'no output'}")
    return json.loads(out.stdout)


def succeeded(receipt: dict) -> bool:
    return str(receipt.get("status")) in ("0x1", "1", "success", "true")


def gas_of(receipt: dict) -> int:
    raw = receipt.get("gasUsed", 0)
    return int(raw, 16) if isinstance(raw, str) and raw.startswith("0x") else int(raw)


def addr_from_receipt(txhash: str, emitter: str) -> str:
    """The new proxy from a ProxyCreation / ModuleProxyCreation log."""
    r = json.loads(cast("receipt", txhash, "--json"))
    for lg in r.get("logs", []):
        if lg["address"].lower() != emitter.lower():
            continue
        for chunk in list(lg.get("topics", [])[1:]) + [lg.get("data", "0x")]:
            h = chunk[2:] if chunk.startswith("0x") else chunk
            for i in range(0, len(h), 64):
                w = h[i:i + 64]
                if len(w) == 64 and w[:24] == "0" * 24 and int(w, 16) != 0:
                    return "0x" + w[24:]
    raise RehearsalFailed(f"no deployed address in receipt {txhash}")


# ------------------------------------------------- the REAL 2-of-3 owner path --
SAFE_TXHASH_SIG = ("getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,"
                   "uint256,address,address,uint256)(bytes32)")
SAFE_EXEC_SIG = ("execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,"
                 "address,address,bytes)")


def prevalidated(owners: list[str]) -> str:
    """Safe's pre-validated signature form: v=1, r=owner, s=0, sorted ascending.

    This is the form Safe accepts when the owner has already called `approveHash` from
    their own address. It needs NO private key, which is the whole reason the real owner
    addresses can appear in a rehearsal at all.
    """
    parts = []
    for owner in sorted(owners, key=lambda a: int(a, 16)):
        parts.append(f"{int(owner, 16):064x}" + "0" * 64 + "01")
    return "0x" + "".join(parts)


def owner_ceremony(safe: str, to: str, data: str, *, label: str, operation: int = 0) -> dict:
    """ONE owner act: two of three owners approve the hash, then it executes."""
    nonce = str(uint(cast("call", safe, "nonce()(uint256)")))
    txh = cast("call", safe, SAFE_TXHASH_SIG, to, "0", data, str(operation),
               "0", "0", "0", ZERO, ZERO, nonce).split()[0]

    approvals = []
    for owner in (OWNER_B, OWNER_A):
        r = send_from(owner, safe, "approveHash(bytes32)", txh)
        if not succeeded(r):
            raise RehearsalFailed(f"{label}: {owner} could not approve {txh}")
        approvals.append({"owner": owner, "gas": gas_of(r)})
        # The Safe must record the approval, or the pre-validated signature is worthless.
        if uint(cast("call", safe, "approvedHashes(address,bytes32)(uint256)", owner, txh)) != 1:
            raise RehearsalFailed(f"{label}: {owner}'s approval was not recorded")

    receipt = send_key(RELAY_PK, safe, SAFE_EXEC_SIG, to, "0", data, str(operation),
                       "0", "0", "0", ZERO, ZERO, prevalidated([OWNER_A, OWNER_B]))
    if not succeeded(receipt):
        raise RehearsalFailed(f"{label}: execTransaction reverted")
    return {"label": label, "safe_tx_hash": txh, "tx": receipt.get("transactionHash"),
            "gas": gas_of(receipt), "approvals": approvals,
            "signers": sorted([OWNER_A, OWNER_B], key=lambda a: int(a, 16))}


# ====================================================================== phases --
def phase_fork() -> None:
    print("\n0. the fork")
    chain = uint(cast("chain-id"))
    block = uint(cast("block-number"))
    if chain != 8453:
        raise RehearsalFailed(f"chain {chain} is not Base mainnet")
    if len(cast("code", MORPHO)) < 1000:
        raise RehearsalFailed("Morpho has no code; this is not a Base fork")
    RECORD["fork"] = {"chain_id": chain, "block_number": block,
                      "morpho_has_code": True,
                      "note": "an anvil fork of Base. No finality, no public state."}
    step("fork verified", chain=chain, block=block)


def phase_safe() -> str:
    print("\n1. the 2-of-3 Safe, with the final owners")
    init = cast_local(
        "calldata", "setup(address[],uint256,address,bytes,address,address,uint256,address)",
        f"[{OWNER_A},{OWNER_B},{OWNER_C}]", str(THRESHOLD), ZERO, "0x", ZERO, ZERO, "0", ZERO)
    r = send_key(RELAY_PK, SAFE_FACTORY, "createProxyWithNonce(address,bytes,uint256)",
                 SAFE_SINGLETON, init, str(SALT_NONCE))
    safe = addr_from_receipt(r["transactionHash"], SAFE_FACTORY)

    owners = cast("call", safe, "getOwners()(address[])")
    threshold = uint(cast("call", safe, "getThreshold()(uint256)"))
    version = cast("call", safe, "VERSION()(string)").strip('"')
    got = [o.strip().lower() for o in owners.strip("[]").split(",") if o.strip()]
    want = {OWNER_A.lower(), OWNER_B.lower(), OWNER_C.lower()}
    if set(got) != want:
        raise RehearsalFailed(f"Safe owners {got} are not the three final owners")
    if threshold != THRESHOLD:
        raise RehearsalFailed(f"threshold {threshold} != {THRESHOLD}")

    RECORD["addresses"]["safe"] = safe
    RECORD["gas"]["safe_deploy"] = gas_of(r)
    RECORD["state"]["safe"] = {"owners": got, "threshold": threshold, "version": version,
                               "saltNonce": SALT_NONCE}
    step("Safe deployed", safe=safe, owners=len(got), threshold=threshold, version=version)
    return safe


def phase_roles(safe: str) -> str:
    print("\n2. the Zodiac Roles module")
    inner = cast_local("abi-encode", "f(address,address,address)", safe, safe, safe)
    rinit = cast_local("calldata", "setUp(bytes)", inner)
    r = send_key(RELAY_PK, ZODIAC_FACTORY, "deployModule(address,bytes,uint256)",
                 ROLES_MASTERCOPY, rinit, str(SALT_NONCE))
    roles = addr_from_receipt(r["transactionHash"], ZODIAC_FACTORY)

    for name, getter in (("owner", "owner()(address)"), ("avatar", "avatar()(address)"),
                         ("target", "target()(address)")):
        got = cast("call", roles, getter).lower()
        if got != safe.lower():
            raise RehearsalFailed(f"Roles {name} is {got}, not the Safe")

    RECORD["addresses"]["roles"] = roles
    RECORD["gas"]["roles_deploy"] = gas_of(r)
    RECORD["state"]["roles"] = {"owner": safe, "avatar": safe, "target": safe}
    step("Roles deployed", roles=roles)
    return roles


def phase_controller(safe: str, roles: str) -> str:
    print("\n3. the controller, deployed PAUSED")
    keys = (NORMAL_ROLE,
            cast_local("keccak", "held-restoration-v1"),
            SUPPLY_KEY,
            cast_local("keccak", "held-withdraw-cap"),
            cast_local("keccak", "held-restoration-cap"),
            cast_local("keccak", "held-normal-count"),
            cast_local("keccak", "held-restoration-count"))
    out = subprocess.run(
        ["forge", "create", "contracts/src/HeldController.sol:HeldController",
         "--rpc-url", RPC, "--private-key", RELAY_PK, "--broadcast", "--json",
         "--constructor-args", safe, roles, MORPHO, USDC, MARKET_ID, LINEAGE,
         "(" + ",".join(keys) + ")"],
        capture_output=True, text=True, cwd=ROOT, env={**os.environ, **FOUNDRY})
    if out.returncode != 0:
        raise RehearsalFailed(f"controller deploy: {(out.stderr or out.stdout).strip()[:400]}")
    # forge interleaves compiler progress with the result, and pretty-prints the JSON
    # across several lines, so take everything from the first brace.
    controller = None
    brace = out.stdout.find("{")
    if brace >= 0:
        try:
            controller = json.loads(out.stdout[brace:]).get("deployedTo")
        except ValueError:
            controller = None
    if not controller:
        raise RehearsalFailed(
            f"forge create printed no deployedTo. stdout: {out.stdout.strip()[-400:]}")

    active = cast("call", controller, "active()(bool)").lower()
    epoch = uint(cast("call", controller, "epoch()(uint64)"))
    if active != "false" or epoch != 0:
        raise RehearsalFailed(f"controller is active={active} epoch={epoch}; deployment "
                              "must not be authorisation")
    for counter in ("usedSupply", "usedNormalWithdraw", "usedRestoration",
                    "normalCount", "restorationCount"):
        if uint(cast("call", controller, f"{counter}()(uint128)")) != 0:
            raise RehearsalFailed(f"{counter} is not zero on a fresh controller")

    # Fork-only dust so the bounded inventory's read-only role simulation can run; anvil
    # charges gas even for eth_call. The controller never spends ETH in production.
    rpc("anvil_setBalance", controller, "0xDE0B6B3A7640000")

    RECORD["addresses"]["controller"] = controller
    RECORD["state"]["controller_at_deploy"] = {"active": False, "epoch": 0,
                                               "all_counters": 0, "owner": safe}
    step("controller deployed paused", controller=controller, active="false", epoch=0)
    return controller


def phase_enable_roles(safe: str, roles: str) -> dict:
    """Owner run-sequence step 2b, and a 2-of-3 act in its own right.

    Deliberately NOT folded into the 15-action ceremony: the ceremony is built by
    simulating the tested installer, and the installer takes an already-enabled Roles
    module as a precondition. Enabling it here keeps the ceremony's action count equal to
    what the owner sheet says it is.
    """
    print("\n4. enable the Roles module on the Safe — one 2-of-3 owner act")
    data = cast_local("calldata", "enableModule(address)", roles)
    act = owner_ceremony(safe, safe, data, label="enableModule(ROLES)")
    if cast("call", safe, "isModuleEnabled(address)(bool)", roles).lower() != "true":
        raise RehearsalFailed("the Roles module is not enabled after the owner act")
    RECORD["gas"]["enable_roles"] = act["gas"]
    step("Roles enabled", gas=act["gas"], signers=2)
    return act


def phase_ceremony(safe: str, roles: str, controller: str) -> list[dict]:
    print("\n5. the 15-action owner ceremony, every action 2-of-3")
    env = {**os.environ, **FOUNDRY, "HELD_SAFE": safe, "HELD_ROLES": roles,
           "HELD_CONTROLLER": controller, "HELD_ROLE_KEY": NORMAL_ROLE,
           "HELD_ALLOW_KEY": SUPPLY_KEY, "HELD_CHAIN_ID": "8453"}
    # The builder SIMULATES the installation as the Safe in order to record the calldata,
    # and anvil charges the simulated sender for gas. Dust so the dry run can execute; the
    # real ceremony below is paid by whoever relays `execTransaction`, not by the Safe.
    rpc("anvil_setBalance", safe, "0xDE0B6B3A7640000")
    built = subprocess.run(
        ["forge", "script", "script/solidity/BuildOwnerCeremony.s.sol:BuildOwnerCeremony",
         "--rpc-url", RPC, "--sender", safe, "--unlocked"],
        capture_output=True, text=True, cwd=ROOT, env=env)
    if built.returncode != 0:
        raise RehearsalFailed(
            f"ceremony build: {(built.stderr or built.stdout).strip()[-500:]}")
    made = subprocess.run([sys.executable, "script/build_owner_ceremony.py"],
                          capture_output=True, text=True, cwd=ROOT, env=env)
    if made.returncode != 0:
        raise RehearsalFailed(f"ceremony extract: {made.stderr.strip()[:400]}")
    with open(os.path.join(ROOT, "evidence", "M1", "owner-ceremony-calldata.json")) as fh:
        ceremony = json.load(fh)
    if ceremony["action_count"] != 15:
        raise RehearsalFailed(f"{ceremony['action_count']} ceremony actions, expected 15")
    if ceremony["controller"].lower() != controller.lower():
        raise RehearsalFailed("the ceremony was built against a different controller")
    actions = [{"label": a["label"], "to": a["to"], "data": a["data"]}
               for a in ceremony["actions"]]

    executed = []
    for i, a in enumerate(actions, 1):
        result = owner_ceremony(safe, a["to"], a["data"], label=f"{i:02d} {a['label']}")
        executed.append(result)
        print(f"     {i:2d}/15 {a['label'][:58]:58s} gas {result['gas']:>7,}")

    if cast("call", safe, "isModuleEnabled(address)(bool)", controller).lower() != "true":
        raise RehearsalFailed("the controller is not enabled as a Safe module")
    RECORD["gas"]["ceremony_total"] = sum(a["gas"] for a in executed) + sum(
        ap["gas"] for a in executed for ap in a["approvals"])
    RECORD["gas"]["ceremony_exec_only"] = sum(a["gas"] for a in executed)
    RECORD["state"]["ceremony"] = {"actions": len(executed), "threshold_used": THRESHOLD,
                                   "signers": executed[0]["signers"]}
    step("ceremony complete", actions=len(executed),
         gas=RECORD["gas"]["ceremony_total"])
    return executed


def phase_allowances(roles: str) -> dict:
    print("\n6. the five native budgets, read back off Roles")
    keys = {
        "supply": SUPPLY_KEY,
        "normal_withdraw": cast_local("keccak", "held-withdraw-cap"),
        "restoration": cast_local("keccak", "held-restoration-cap"),
        "normal_count": cast_local("keccak", "held-normal-count"),
        "restoration_count": cast_local("keccak", "held-restoration-count"),
    }
    expected = {"supply": 50_000_000_000, "normal_withdraw": 50_000_000_000,
                "restoration": 10_000_000_000, "normal_count": 10, "restoration_count": 5}
    out = {}
    for name, key in keys.items():
        # Zodiac Roles v2 returns (refill, maxRefill, period, balance, timestamp) -- the
        # struct order, NOT the setAllowance argument order. Reading it in argument order
        # made every budget look empty and every one look refilling.
        raw = cast("call", roles,
                   "allowances(bytes32)(uint128,uint128,uint64,uint128,uint64)", key)
        nums = [uint(x) for x in raw.split("\n") if x.strip()]
        refill, maxrefill, period, balance = nums[0], nums[1], nums[2], nums[3]
        out[name] = {"balance": balance, "maxRefill": maxrefill, "refill": refill,
                     "period": period, "non_refilling": period == 0 and refill == 0}
        if balance != expected[name]:
            problem(f"{name} allowance is {balance}, expected {expected[name]}")
        if not out[name]["non_refilling"]:
            problem(f"{name} allowance refills (period={period}); it must not")
        print(f"     {name:18s} {balance:>14,}  non-refilling={out[name]['non_refilling']}")
    RECORD["state"]["allowances"] = out
    step("budgets bound", count=len(out), all_non_refilling=all(
        v["non_refilling"] for v in out.values()))
    return out


def write_manifest(safe: str, roles: str, controller: str) -> str:
    """The DECLARED installation, written so the inventory has something to bind to.

    The bounded checklist refuses to infer the installation from whatever it happens to
    read -- a report with no declared installation is unusable, not merely weaker. The
    fork fixture gets this from `InstallPausedHeld.s.sol`; the ceremony builder does not
    write one, because on mainnet the owner declares it. Same keys, same meaning.
    """
    manifest = {
        "safe": safe, "roles": roles, "controller": controller,
        "retiredMember": ZERO, "morpho": MORPHO, "usdc": USDC,
        "marketId": MARKET_ID, "lineage": LINEAGE,
        "normalRole": NORMAL_ROLE,
        "restorationRole": cast_local("keccak", "held-restoration-v1"),
        "supplyAmountKey": SUPPLY_KEY,
        "normalWithdrawKey": cast_local("keccak", "held-withdraw-cap"),
        "restorationKey": cast_local("keccak", "held-restoration-cap"),
        "normalCountKey": cast_local("keccak", "held-normal-count"),
        "restorationCountKey": cast_local("keccak", "held-restoration-count"),
        "supplyAmountLimit": 50_000_000_000,
        "normalWithdrawLimit": 50_000_000_000,
        "restorationLimit": 10_000_000_000,
        "normalCountLimit": 10,
        "restorationCountLimit": 5,
        "approvalValueBound": 40_000_000_000,
        "_note": ("DECLARED candidate installation for the FINAL FORK REHEARSAL. The "
                  "amount/count limits are the NATIVE Roles allowances this installation "
                  "configures; the controller's own policy is zero until activation. Not "
                  "a reading of live state -- the checklist reads that separately and "
                  "compares."),
    }
    path = os.path.join(ROOT, "fixtures", "generated", "final-rehearsal-manifest.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(manifest, fh, indent=1)
        fh.write("\n")
    return path


def phase_fund(safe: str) -> int:
    print("\n7. funding the Safe with exactly 11.000000 USDC")
    slot = cast_local("index", "address", safe, str(USDC_SLOT))
    rpc("anvil_setStorageAt", USDC, slot, "0x" + f"{SAFE_FUNDING:064x}")
    bal = uint(cast("call", USDC, "balanceOf(address)(uint256)", safe))
    if bal != SAFE_FUNDING:
        raise RehearsalFailed(f"Safe holds {bal}, expected exactly {SAFE_FUNDING}")
    RECORD["state"]["safe_usdc_at_funding"] = bal
    step("Safe funded", usdc=bal,
         note="fork storage write, NOT a transfer; no real USDC moved")
    return bal


def phase_authority(safe: str, roles: str, controller: str) -> dict:
    print("\n8. the bounded authority inventory, before activation")
    from held_authority import collect

    env = {"HELD_SAFE": safe, "HELD_ROLES": roles, "HELD_CONTROLLER": controller,
           "HELD_ROLE_KEY": NORMAL_ROLE, "HELD_ALLOW_KEY": SUPPLY_KEY,
           "HELD_INSTALL_MANIFEST": write_manifest(safe, roles, controller),
           "HELD_RUNNER": RUNNER_B, "HELD_EXECUTOR": EXECUTOR,
           "HELD_INVENTORY_MODE": "initial", "HELD_BASE_RPC": RPC,
           "HELD_INVENTORY_OUT": os.path.join("evidence", "M1", "final-rehearsal-inventory.json")}
    try:
        inv = collect(env=env, python=sys.executable)
    except Exception as exc:  # noqa: BLE001
        problem(f"the bounded inventory could not be collected: {exc}")
        RECORD["state"]["inventory"] = {"collected": False, "reason": str(exc)[:300]}
        return {}

    summary = {"complete": inv.complete, "sections": inv.section_count,
               "incomplete": inv.incomplete_sections,
               "external_delegates": inv.external_delegates,
               "unsatisfied": inv.unsatisfied_obligations,
               "block_number": inv.block_number, "grade": inv.evidence_grade}
    if not inv.complete:
        problem(f"inventory INCOMPLETE: {inv.incomplete_sections}. On mainnet this blocks "
                "activation")
    if inv.evidence_grade != "REAL LOCAL FORK":
        problem(f"the fork inventory graded itself {inv.evidence_grade}")
    RECORD["state"]["inventory"] = summary
    step("authority readback", complete=inv.complete, sections=inv.section_count,
         grade=inv.evidence_grade)
    return summary


# Selectors computed with `cast sig`, not recalled. Naming the refusal matters: "it
# reverted" is much weaker evidence than "it reverted with FloorViolated()", which says
# WHICH guard refused and therefore whether the guard under test is the one that fired.
CONTROLLER_ERRORS = {
    "0xc647c7a5": "OperationConsumed(bytes32)",
    "0x6575b1e1": "FloorViolated()",
    "0x2b9264ec": "WrongEpoch(uint64,uint64)",
    "0xc1f407ce": "WrongPolicyVersion(uint32,uint32)",
    "0x5cd5d233": "BadSignature()",
    "0xc4dbbd03": "WrongScope()",
    "0x6f982dc5": "WrongFamily()",
    "0x1d6e22b9": "PayloadMismatch()",
    "0xc64200e9": "AmountOutOfRange()",
    "0x20caa94a": "CeilingExceeded()",
    "0x5f8080f7": "CountExhausted()",
    "0xaa9a98df": "CooldownActive()",
    "0xd0b63180": "HoldIsNotExecutable()",
    "0x30cd7471": "NotOwner()",
    "0xc32d1d76": "NotExecutor()",
    "0x9e87fac8": "Paused()",
    "0xf9be60a2": "AlreadyActive()",
    "0x9c9413a1": "StaleActivation()",
    "0x5a0785e7": "AllowanceDesynchronised(uint256,uint256)",
    "0xdfc365cd": "AllowanceRefillsNotPermitted(bytes32,uint128,uint64)",
    "0x141bd18e": "AllowanceNotConsumed(bytes32,uint256,uint256,uint256)",
    "0x7206b469": "EntryAllowanceNotZero()",
    "0x49edf744": "ExitAllowanceNotZero()",
    "0x92bf27cc": "BorrowSharesPresent()",
    "0xc506c077": "CollateralChanged()",
    "0xc883f128": "NestedCallFailed(address)",
    "0x9dbff4df": "TokenReturnedFalse(address)",
    "0xaf69b506": "UnexpectedReturnShape(uint256)",
    "0xb3838263": "EffectNotObserved(string)",
    "0x9e6b687a": "ReportedEffectMismatch(string,uint256,uint256)",
}


def named_revert(stderr: str) -> str:
    for sel, name in CONTROLLER_ERRORS.items():
        if sel in stderr:
            return name
    import re
    for m in re.finditer(r"0x[0-9a-fA-F]{8}", stderr):
        sel = m.group(0).lower()
        if sel in CONTROLLER_ERRORS:
            return CONTROLLER_ERRORS[sel]
    m = re.search(r'data:\s*"(0x[0-9a-fA-F]{8})', stderr)
    if m:
        return f"custom error {m.group(1)}"
    for word in ("FloorViolated", "AllowanceExceeded", "AlreadyConsumed", "OverMax",
                 "Paused", "NotExecutor", "revert"):
        if word.lower() in stderr.lower():
            return word
    return "unnamed revert"


def phase_activate(safe: str, controller: str) -> dict:
    print("\n9. activation — the only act that turns the controller on")
    policy = "(" + ",".join(str(POLICY[k]) for k in POLICY_ORDER) + ")"
    expected = "(0,0,0,0,0)"
    data = cast_local(
        "calldata",
        "activate(uint64,uint32,address,address,"
        "(uint128,uint128,uint128,uint128,uint128,uint128,uint128,uint128,uint128,uint128,"
        # ExpectedState's last two fields are uint64, not uint128. Writing them as uint128
        # produced selector 0x3ef016e1 instead of 0xbe6d7eb6, so the call matched no
        # function and reverted with EMPTY data -- which looks nothing like a guard firing
        # and is why this needed a simulation to diagnose at all.
        "uint64,uint64,uint64,uint64),(uint128,uint128,uint128,uint64,uint64))",
        "1", "1", RUNNER_B, EXECUTOR, policy, expected)

    # Simulate from the Safe FIRST. Safe swallows the inner revert and reports GS013,
    # which says only "the inner call failed" -- useless for telling an activation guard
    # apart from a malformed argument. This surfaces the controller's own error.
    sim = subprocess.run(["cast", "call", controller, data, "--from", safe,
                          "--rpc-url", RPC], capture_output=True, text=True,
                         env={**os.environ, **FOUNDRY})
    if sim.returncode != 0:
        raise RehearsalFailed(
            f"activate would revert: {named_revert(sim.stderr)} — "
            f"{sim.stderr.strip()[:400]}")

    act = owner_ceremony(safe, controller, data, label="activate")

    state = {
        "active": cast("call", controller, "active()(bool)").lower() == "true",
        "epoch": uint(cast("call", controller, "epoch()(uint64)")),
        "policyVersion": uint(cast("call", controller, "policyVersion()(uint32)")),
        "runner": cast("call", controller, "runner()(address)"),
        "executor": cast("call", controller, "executor()(address)"),
    }
    if not state["active"] or state["epoch"] != 1 or state["policyVersion"] != 1:
        raise RehearsalFailed(f"activation readback wrong: {state}")
    if state["runner"].lower() != RUNNER_B.lower():
        raise RehearsalFailed(f"runner is {state['runner']}, not runner B")
    if state["executor"].lower() != EXECUTOR.lower():
        raise RehearsalFailed(f"executor is {state['executor']}, not KeeperHub's signer")

    RECORD["gas"]["activate"] = act["gas"]
    RECORD["state"]["controller_after_activation"] = state
    RECORD["state"]["policy"] = dict(POLICY)
    step("activated", epoch=1, runner=state["runner"], executor=state["executor"],
         gas=act["gas"])
    return state


def build_supply(safe: str, controller: str, *, amount: int, decision_id: str,
                 epoch: int, runner: str, key_env: str):
    """An admitted operation, a runner-signed envelope, and the controller calldata."""
    from eth_abi import encode as abi_encode
    from eth_utils import keccak

    from held_adapter.execution.controller_abi import build_execute_call
    from held_adapter.execution.interceptor import Profile, admit_bundle
    from held_adapter.signing.runner_signer import RunnerSigner
    from held_core.identity import AuthorizationEnvelope

    profile = Profile(chain_id=8453, controller=controller, safe=safe, lineage=LINEAGE,
                      morpho=MORPHO, token=USDC, market_params=MARKET)
    bundle = {"safe": safe, "calls": [
        {"to": USDC, "value": 0, "data": "0x095ea7b3" + abi_encode(
            ["address", "uint256"], [MORPHO, amount]).hex()},
        {"to": MORPHO, "value": 0, "data": "0xa99aad89" + abi_encode(
            ["(address,address,address,address,uint256)", "uint256", "uint256",
             "address", "bytes"], [MARKET, amount, 0, safe.lower(), b""]).hex()},
    ]}
    admitted = admit_bundle(bundle, profile, decision_id, 0)
    env = AuthorizationEnvelope(
        scope=profile.scope(), operation_id=admitted.operation_id,
        source_identity_hash=keccak(decision_id.encode()),
        payload_hash=admitted.payload_hash, action_family=admitted.action.family,
        epoch=epoch, policy_version=1, runner=runner)
    signed = RunnerSigner(f"env:{key_env}", runner).sign(env)
    _fn, _args, calldata = build_execute_call(admitted, env, signed.signature, MARKET)
    return admitted, env, calldata


def executor_send(controller: str, calldata: str) -> tuple[bool, str, dict | None]:
    """The KeeperHub-EQUIVALENT path: the real executor address sends the outer call.

    On Base this transaction is built and broadcast by KeeperHub's managed wallet. Here it
    comes from the same address, impersonated. That models the caller the controller
    checks -- and the controller's `onlyExecutor` check is the thing under test -- but it
    is NOT KeeperHub: no KeeperHub API was involved, no idempotency key was issued, and
    nothing here is evidence about the hosted route.
    """
    out = subprocess.run(
        ["cast", "send", controller, calldata, "--from", EXECUTOR, "--unlocked",
         "--rpc-url", RPC, "--json"],
        capture_output=True, text=True, env={**os.environ, **FOUNDRY})
    if out.returncode == 0 and out.stdout.strip():
        r = json.loads(out.stdout)
        return succeeded(r), "", r
    # `cast send` reports a gas-estimation failure without the revert payload, so the
    # selector is lost and every refusal reads as "unnamed revert". Re-run it as a CALL to
    # recover the controller's own error. "It reverted" is much weaker evidence than
    # "it reverted with FloorViolated()", and which guard fired is the thing under test.
    sim = subprocess.run(
        ["cast", "call", controller, calldata, "--from", EXECUTOR, "--rpc-url", RPC],
        capture_output=True, text=True, env={**os.environ, **FOUNDRY})
    detail = (sim.stderr or "").strip() or (out.stderr or "").strip()
    return False, detail[:600], None




def phase_execute(safe: str, controller: str, runner: str, key_env: str) -> dict:
    print("\n10-12. the supply, the refusals, and the replay")
    before = uint(cast("call", USDC, "balanceOf(address)(uint256)", safe))

    admitted, env, calldata = build_supply(
        safe, controller, amount=SUPPLY_AMOUNT, decision_id="m1-rehearsal-supply-1",
        epoch=1, runner=runner, key_env=key_env)
    oid = "0x" + bytes(admitted.operation_id).hex()
    step("runner envelope signed", operation=oid[:18] + "...", runner=runner, epoch=1)

    ok, err, receipt = executor_send(controller, calldata)
    if not ok:
        raise RehearsalFailed(f"the first supply failed: {named_revert(err)} — {err[:200]}")
    after = uint(cast("call", USDC, "balanceOf(address)(uint256)", safe))
    gas = gas_of(receipt)
    RECORD["gas"]["execute_supply"] = gas

    used = uint(cast("call", controller, "usedSupply()(uint128)"))
    count = uint(cast("call", controller, "normalCount()(uint128)"))
    marker = cast("call", controller, "consumed(bytes32)(bytes32)", oid).split()[0]
    position = cast("call", MORPHO, "position(bytes32,address)(uint256,uint128,uint128)",
                    MARKET_ID, safe)
    supply_shares = uint(position)

    result = {
        "operation_id": oid,
        "tx": receipt.get("transactionHash"),
        "gas": gas,
        "safe_usdc_before": before,
        "safe_usdc_after": after,
        "moved": before - after,
        "usedSupply": used,
        "normalCount": count,
        "consumed_marker": marker,
        "morpho_supply_shares": supply_shares,
    }
    for label, got, want in (("moved", before - after, SUPPLY_AMOUNT),
                             ("usedSupply", used, SUPPLY_AMOUNT),
                             ("normalCount", count, 1),
                             ("safe balance after", after, SAFE_FUNDING - SUPPLY_AMOUNT)):
        if got != want:
            problem(f"{label} is {got}, expected {want}")
    if marker == "0x" + "0" * 64:
        problem("consumed[operationId] is zero after a successful execution")
    if supply_shares == 0:
        problem("Morpho reports no supply position for the Safe")
    RECORD["state"]["first_supply"] = result
    step("first supply executed", moved=result["moved"], usedSupply=used,
         normalCount=count, shares=supply_shares, gas=gas)

    # ---- the SECOND attempt, a genuinely new operation, must be refused ----
    _a2, _e2, calldata2 = build_supply(
        safe, controller, amount=SUPPLY_AMOUNT, decision_id="m1-rehearsal-supply-2",
        epoch=1, runner=runner, key_env=key_env)
    ok2, err2, _ = executor_send(controller, calldata2)
    second = {"succeeded": ok2, "revert": named_revert(err2), "raw": err2[:300],
              "safe_usdc": uint(cast("call", USDC, "balanceOf(address)(uint256)", safe)),
              "why_expected": (
                  "the Safe holds 1.000000 USDC and the floor F is 1.000000 USDC, so "
                  "`amount <= balanceBefore - F` admits nothing. The supply allowance is "
                  "not the binding constraint here: 49,990 USDC of a non-refilling 50,000 "
                  "remains.")}
    if ok2:
        problem("the SECOND supply succeeded. It must be refused — the floor is breached")
    elif second["revert"] != "FloorViolated()":
        problem(f"the second attempt was refused by {second['revert']}, not FloorViolated(). "
                "A refusal by the wrong guard is not the behaviour being claimed")
    RECORD["refusals"]["second_attempt"] = second
    step("second attempt refused", reason=second["revert"])

    # ---- the SAME envelope again: idempotency at the controller ----
    ok3, err3, _ = executor_send(controller, calldata)
    replay = {"succeeded": ok3, "revert": named_revert(err3), "raw": err3[:300],
              "usedSupply_after": uint(cast("call", controller, "usedSupply()(uint128)")),
              "normalCount_after": uint(cast("call", controller, "normalCount()(uint128)"))}
    if ok3:
        problem("a REPLAY of the identical authorization executed a second time")
    elif replay["revert"] != "OperationConsumed(bytes32)":
        problem(f"the replay was refused by {replay['revert']}, not OperationConsumed. "
                "Idempotency must be the reason, not a side effect of something else")
    if replay["usedSupply_after"] != SUPPLY_AMOUNT or replay["normalCount_after"] != 1:
        problem(f"the replay moved the counters: {replay}")
    RECORD["refusals"]["replay_same_envelope"] = replay
    step("replay refused, counters unmoved", reason=replay["revert"],
         usedSupply=replay["usedSupply_after"])

    final_balance = uint(cast("call", USDC, "balanceOf(address)(uint256)", safe))
    RECORD["state"]["safe_usdc_final"] = final_balance
    RECORD["state"]["morpho_position"] = {"supply_shares": supply_shares,
                                          "onBehalf": safe, "market": MARKET_ID}
    return result


# ------------------------------------------------ compare against the claims --
def compare_claims() -> None:
    print("\n13. every result against the submission claims")
    s = RECORD["state"]
    checks = [
        ("Safe is 2-of-3 with the three final owners",
         s["safe"]["threshold"] == 2 and len(s["safe"]["owners"]) == 3),
        ("every owner act carried two of three signatures",
         s["ceremony"]["threshold_used"] == 2 and len(s["ceremony"]["signers"]) == 2),
        ("the ceremony is 15 actions, as the owner sheet says",
         s["ceremony"]["actions"] == 15),
        ("the Roles module was enabled by its own 2-of-3 owner act",
         "enable_roles" in RECORD["gas"]),
        ("the controller is deployed paused at epoch 0, all counters zero",
         s["controller_at_deploy"]["active"] is False),
        ("all five budgets are NON-REFILLING",
         all(v["non_refilling"] for v in s["allowances"].values())),
        ("the Safe was funded with exactly 11.000000 USDC",
         s["safe_usdc_at_funding"] == 11_000_000),
        ("activation set epoch 1, runner B and KeeperHub's executor",
         s["controller_after_activation"]["epoch"] == 1),
        ("exactly 10.000000 USDC moved, once",
         s["first_supply"]["moved"] == 10_000_000 and s["first_supply"]["normalCount"] == 1),
        ("a Morpho position exists on behalf of the Safe",
         s["first_supply"]["morpho_supply_shares"] > 0),
        ("the second attempt was refused by the FLOOR guard, by name",
         RECORD["refusals"]["second_attempt"]["revert"] == "FloorViolated()"),
        ("a replayed authorization was refused by OperationConsumed and moved no counter",
         RECORD["refusals"]["replay_same_envelope"]["revert"] == "OperationConsumed(bytes32)"
         and RECORD["refusals"]["replay_same_envelope"]["usedSupply_after"] == 10_000_000),
        ("the Safe's final balance is 1.000000 USDC — the floor, untouched",
         s["safe_usdc_final"] == 1_000_000),
        ("no row of this rehearsal is graded above REAL LOCAL FORK",
         RECORD["evidence_grade"] == "REAL LOCAL FORK"),
    ]
    for claim, held in checks:
        RECORD["claim_comparison"].append({"claim": claim, "held": bool(held)})
        print(f"  [{'MATCH' if held else 'MISMATCH'}] {claim}")
        if not held:
            problem(f"claim does not match the rehearsal: {claim}")


def main() -> int:
    started = time.time()
    print("HELD — FINAL FORK REHEARSAL (M1 ceremony, final identities)")
    print("=" * 78)
    print("REAL LOCAL FORK. Nothing here exists on any public chain.")

    runner, key_env = RUNNER_B, "HELD_RUNNER_B_KEY"
    if not os.environ.get("HELD_RUNNER_B_KEY"):
        runner, key_env = FALLBACK_RUNNER, "HELD_FALLBACK_RUNNER_KEY"
        os.environ["HELD_FALLBACK_RUNNER_KEY"] = FALLBACK_RUNNER_KEY
        problem("$HELD_RUNNER_B_KEY is absent, so the envelope was signed by an anvil "
                "account instead of runner B. The signing path is exercised; the final "
                "runner IDENTITY is not.")
    RECORD["runner_is_final_identity"] = runner.lower() == RUNNER_B.lower()
    RECORD["identities"]["runner_used"] = runner

    try:
        phase_fork()
        for who in (OWNER_A, OWNER_B, OWNER_C, EXECUTOR):
            impersonate(who)
        safe = phase_safe()
        roles = phase_roles(safe)
        controller = phase_controller(safe, roles)
        phase_enable_roles(safe, roles)
        phase_ceremony(safe, roles, controller)
        phase_allowances(roles)
        phase_fund(safe)
        phase_authority(safe, roles, controller)
        phase_activate(safe, controller)
        phase_execute(safe, controller, runner, key_env)
        compare_claims()
        RECORD["completed"] = True
    except RehearsalFailed as exc:
        RECORD["completed"] = False
        problem(f"REHEARSAL HALTED: {exc}")
        print(f"\n  [HALTED] {exc}")
    except Exception as exc:  # noqa: BLE001
        RECORD["completed"] = False
        import traceback
        problem(f"REHEARSAL CRASHED: {type(exc).__name__}: {exc}")
        print("\n" + traceback.format_exc()[-1800:])

    RECORD["elapsed_seconds"] = round(time.time() - started, 1)
    RECORD["boundaries"] = [
        "REAL LOCAL FORK. No address here exists on Base. Nothing was funded with real "
        "money; the USDC was written into fork storage, not transferred.",
        "The owner actions used Safe's pre-validated signature form after a real "
        "approveHash from each impersonated owner. No owner private key was used, "
        "requested or held.",
        "The executor path is KeeperHub-EQUIVALENT, not KeeperHub: the same address sent "
        "the call, but no KeeperHub API was involved and no idempotency key was issued. "
        "This is not evidence for M1, M2, P18 or P19.",
        "An anvil fork has no finality, so no row may be promoted to PUBLIC CHAIN.",
    ]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(RECORD, fh, indent=1)
        fh.write("\n")

    print("\n" + "=" * 78)
    matched = sum(1 for c in RECORD["claim_comparison"] if c["held"])
    print(f"  steps {len(RECORD['steps'])}   claims matched {matched}/"
          f"{len(RECORD['claim_comparison'])}   problems {len(RECORD['problems'])}")
    print(f"  written: {os.path.relpath(OUT, ROOT)}")
    if RECORD["problems"]:
        print("\nPROBLEMS:")
        for p in RECORD["problems"]:
            print(f"  - {p}")
    ok = RECORD.get("completed") and not RECORD["problems"]
    print(f"\nFINAL FORK REHEARSAL: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
