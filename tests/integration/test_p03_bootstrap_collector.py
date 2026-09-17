"""Does the bootstrap collector actually refuse what it claims to refuse?

The previous collector reported COMPLETE in fourteen situations that should have blocked.
Its prose claimed the checks; its predicates did not make them. A checklist whose failure
path is untested is a claim, not a control.

METHOD. The real `script/collect_bootstrap_evidence.py` is executed as a subprocess with
a scripted `cast` shim placed first on PATH. The collector is unmodified -- it is the file
that runs in the rehearsal. What is synthetic is the CHAIN RESPONSES, which is the only
way to present a guard that will not read, or a Roles module owned by someone else,
without corrupting a real fixture.

These are collector-DECISION tests. They say nothing about the actual fork's
configuration; the live readback is `make check-bootstrap-rehearsal`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
COLLECTOR = os.path.join(ROOT, "script", "collect_bootstrap_evidence.py")

_UNSET = object()

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

SAFE = "0x08deeda0ba1eb4b6b4b5cc4dd0c4bc689ea37180"
ROLES = "0x5fbdb2315678afecb367f032d93f642f64180aa3"
CONTROLLER = "0x5615deb798bb3e4dfa0139dfa1b3d433cc23b72f"
MORPHO = "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb"
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
ZERO32 = "0x" + "00" * 32
ROLE_KEY = "0x" + "11" * 32
ALLOW_KEY = "0x" + "22" * 32


def test(name):
    def deco(fn):
        try:
            fn()
            PASSED.append(name)
            print(f"ok    {name}")
        except Exception:
            import traceback
            FAILED.append((name, traceback.format_exc()))
            print(f"FAIL  {name}")
        return fn
    return deco


# The DECLARED installation the baseline describes. Keys are distinct per dimension so a
# collector that reads one quota and reports five cannot pass.
NORMAL_ROLE = "0x" + "11" * 32
RESTORE_ROLE = "0x" + "33" * 32
SUPPLY_KEY = "0x" + "22" * 32
WITHDRAW_KEY = "0x" + "44" * 32
RESTORE_KEY = "0x" + "55" * 32
NORMAL_COUNT_KEY = "0x" + "66" * 32
RESTORE_COUNT_KEY = "0x" + "77" * 32
MARKET_ID = "0x" + "88" * 32
LINEAGE = "0x" + "99" * 32
RUNNER = "0x3333333333333333333333333333333333333333"
EXECUTOR = "0x4444444444444444444444444444444444444444"
RETIRED = "0x5555555555555555555555555555555555555555"

# Sentinels the shim returns for each encode, so the three role probes can be told apart
# inside the eth_call payload.
CD_SUPPLY = "0x" + "a1" * 8
CD_WITHDRAW_OK = "0x" + "b2" * 8
CD_WITHDRAW_BAD = "0x" + "c3" * 8
EXEC_SUPPLY = "0x" + "d4" * 8
EXEC_WITHDRAW_OK = "0x" + "e5" * 8
EXEC_WITHDRAW_BAD = "0x" + "f6" * 8

NO_MEMBERSHIP = "0xfd8e9f28"
CONDITION_VIOLATION = "0xd0a9bf58"
MODULE_TX_FAILED = "0xd27b44a9"


def manifest() -> dict:
    """The declared installation written before activation."""
    return {
        "safe": SAFE, "roles": ROLES, "controller": CONTROLLER, "retiredMember": RETIRED,
        "morpho": MORPHO, "usdc": USDC, "marketId": MARKET_ID, "lineage": LINEAGE,
        "normalRole": NORMAL_ROLE, "restorationRole": RESTORE_ROLE,
        "supplyAmountKey": SUPPLY_KEY, "normalWithdrawKey": WITHDRAW_KEY,
        "restorationKey": RESTORE_KEY, "normalCountKey": NORMAL_COUNT_KEY,
        "restorationCountKey": RESTORE_COUNT_KEY,
        "supplyAmountLimit": 50000000000, "normalWithdrawLimit": 50000000000,
        "restorationLimit": 10000000000, "normalCountLimit": 10, "restorationCountLimit": 5,
        "approvalValueBound": 40000000000,
    }


def allowance(balance: int) -> str:
    """refill, maxRefill, period, balance, timestamp — non-refilling, fully available."""
    return f"0\n{balance}\n0\n{balance}\n0"


def baseline() -> dict[str, str]:
    """Responses describing a clean, supported installation."""
    return {
        "block-number": "51353228",
        "chain-id": "8453",
        "block": "0x" + "ab" * 32,
        f"call {SAFE} getOwners": f"[{SAFE}, 0x1111111111111111111111111111111111111111, "
                                  "0x2222222222222222222222222222222222222222]",
        f"call {SAFE} getThreshold": "2",
        f"call {SAFE} VERSION": "1.4.1",
        f"call {SAFE} getModulesPaginated": f"[{ROLES}, {CONTROLLER}]\n0x0000000000000000000000000000000000000001",
        f"storage {SAFE} 0x4a204f62": ZERO32,
        f"storage {SAFE} 0x6c9a6c4a": ZERO32,
        f"call {ROLES} owner": SAFE,
        f"call {ROLES} avatar": SAFE,
        f"call {ROLES} target": SAFE,
        # ALL FIVE budgets, each under its own key and matching its declared limit.
        f"call {ROLES} allowances {SUPPLY_KEY}": allowance(50000000000),
        f"call {ROLES} allowances {WITHDRAW_KEY}": allowance(50000000000),
        f"call {ROLES} allowances {RESTORE_KEY}": allowance(10000000000),
        f"call {ROLES} allowances {NORMAL_COUNT_KEY}": allowance(10),
        f"call {ROLES} allowances {RESTORE_COUNT_KEY}": allowance(5),
        "logs": "",
        f"call {MORPHO} isAuthorized": "false",
        f"call {USDC} allowance": "0",
        f"call {CONTROLLER} active": "false",
        f"call {CONTROLLER} epoch": "0",
        f"call {CONTROLLER} safe": SAFE,
        f"call {CONTROLLER} roles": ROLES,
        f"call {CONTROLLER} morpho": MORPHO,
        f"call {CONTROLLER} token": USDC,
        f"call {CONTROLLER} owner": SAFE,
        f"call {CONTROLLER} marketId": MARKET_ID,
        f"call {CONTROLLER} lineage": LINEAGE,
        f"call {CONTROLLER} normalRoleKey": NORMAL_ROLE,
        f"call {CONTROLLER} restorationRoleKey": RESTORE_ROLE,
        f"call {CONTROLLER} supplyAllowanceKey": SUPPLY_KEY,
        f"call {CONTROLLER} normalWithdrawAllowanceKey": WITHDRAW_KEY,
        f"call {CONTROLLER} restorationAllowanceKey": RESTORE_KEY,
        f"call {CONTROLLER} normalCountKey": NORMAL_COUNT_KEY,
        f"call {CONTROLLER} restorationCountKey": RESTORE_COUNT_KEY,
        f"call {CONTROLLER} usedSupply": "0",
        f"call {CONTROLLER} usedNormalWithdraw": "0",
        f"call {CONTROLLER} usedRestoration": "0",
        f"call {CONTROLLER} normalCount": "0",
        f"call {CONTROLLER} restorationCount": "0",
        # Encodings, MOST SPECIFIC FIRST (the shim takes the first substring match).
        # Only the wrong-receiver withdraw names the retired member, which is what tells
        # the two withdraw encodings apart.
        f"~calldata~{RETIRED}": CD_WITHDRAW_BAD,
        "~calldata~withdraw(": CD_WITHDRAW_OK,
        "~calldata~supply(": CD_SUPPLY,
        f"~calldata~{CD_SUPPLY}": EXEC_SUPPLY,
        f"~calldata~{CD_WITHDRAW_OK}": EXEC_WITHDRAW_OK,
        f"~calldata~{CD_WITHDRAW_BAD}": EXEC_WITHDRAW_BAD,
        # The role probes, again most specific first: the retired member's probe carries
        # the SAME inner calldata as the controller's supply probe and is distinguished
        # only by the eth_call `from`, so it must be matched before it.
        #
        # The controller is a member of both roles and the trees permit the intended
        # shapes. Its supply probe returns ModuleTransactionFailed -- Roles allowed the
        # call and Morpho reverted, because a Safe at rest holds no USDC approval. That is
        # a PASS for a permission checklist and must not read as a condition failure.
        f"~rpc~{RETIRED}": "__ERR__Error: execution reverted: custom error "
                           f"{NO_MEMBERSHIP}, data: \"{NO_MEMBERSHIP}\"",
        f"~rpc~{EXEC_SUPPLY}": "__ERR__Error: execution reverted: custom error "
                               f"{MODULE_TX_FAILED}, data: \"{MODULE_TX_FAILED}\"",
        f"~rpc~{EXEC_WITHDRAW_OK}": "0x" + "0" * 63 + "1",
        f"~rpc~{EXEC_WITHDRAW_BAD}": "__ERR__Error: execution reverted: custom error "
                                     f"{CONDITION_VIOLATION}, data: \"{CONDITION_VIOLATION}07\"",
    }


def run(responses: dict[str, str], *, manifest_override=_UNSET,
        env_override: dict[str, str] | None = None) -> tuple[int, dict]:
    """Run the REAL collector with a scripted cast shim."""
    with tempfile.TemporaryDirectory() as d:
        shim = os.path.join(d, "cast")
        table = os.path.join(d, "responses.json")
        with open(table, "w") as fh:
            json.dump(responses, fh)
        with open(shim, "w") as fh:
            fh.write(f'''#!/usr/bin/env python3
import json, sys
table = json.load(open({table!r}))
args = sys.argv[1:]
# The COMMAND word must match exactly; later words may prefix-match so a key can say
# "call <addr> getOwners" without repeating the full ABI signature. Prefix-matching the
# command too made `cast block ...` collide with the `block-number` entry.
words = [a for a in args if not a.startswith("--")]
joined = " ".join(args)
best, best_len = None, -1

# "~<cmd>~<substring>" matches when the command is <cmd> and <substring> appears anywhere
# in the argv. Needed for the role probes: their eth_call payload is a JSON blob whose
# distinguishing part is the encoded calldata, which no positional key can address.
# Substring matches score below word matches so an exact key always wins.
for key, val in table.items():
    if key.startswith("~"):
        _, cmd, sub = key.split("~", 2)
        if words and words[0] == cmd and sub in joined and best_len < 0:
            best, best_len = val, 0
        continue
    parts = key.split()
    if len(parts) > len(words) or parts[0] != words[0]:
        continue
    if all(words[i].lower().startswith(p.lower()) or p.lower().startswith(words[i].lower())
           for i, p in enumerate(parts[1:], start=1)):
        if len(parts) > best_len:
            best, best_len = val, len(parts)
if best is None:
    sys.exit(1)          # an unscripted read FAILS, which is the honest default
if best == "__FAIL__":
    sys.exit(1)
if best.startswith("__ERR__"):
    # A node-style failure: message on stderr, non-zero exit. This is how a revert is
    # presented to the collector, and the collector must classify it by SELECTOR.
    sys.stderr.write(best[len("__ERR__"):] + chr(10))
    sys.exit(1)
print(best)
''')
        os.chmod(shim, 0o755)

        work = os.path.join(d, "work")
        os.makedirs(os.path.join(work, "evidence", "P03"), exist_ok=True)

        manifest_path = os.path.join(d, "install-manifest.json")
        if manifest_override is not _UNSET:
            if manifest_override is not None:
                with open(manifest_path, "w") as fh:
                    json.dump(manifest_override, fh)
        else:
            with open(manifest_path, "w") as fh:
                json.dump(manifest(), fh)

        env = dict(os.environ)
        env["PATH"] = d + os.pathsep + env["PATH"]
        env.update({
            "HELD_BASE_RPC": "http://127.0.0.1:1",  # never contacted; the shim answers
            "HELD_SAFE": SAFE, "HELD_ROLES": ROLES,
            "HELD_ROLE_KEY": ROLE_KEY, "HELD_ALLOW_KEY": ALLOW_KEY,
            "HELD_CONTROLLER": CONTROLLER,
            "HELD_INSTALL_MANIFEST": manifest_path,
            "HELD_RUNNER": RUNNER, "HELD_EXECUTOR": EXECUTOR,
        })
        for k, v in (env_override or {}).items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        for stray in ("HELD_RUNNER_A", "HELD_RUNNER_B"):
            env.pop(stray, None)
        proc = subprocess.run([sys.executable, COLLECTOR], env=env, cwd=work,
                              capture_output=True, text=True)
        out = os.path.join(work, "evidence", "P03", "bootstrap-rehearsal.json")
        data = json.load(open(out)) if os.path.exists(out) else {}
        return proc.returncode, data


def expect_blocked(label: str, mutate, *, manifest_override=_UNSET) -> None:
    r = baseline()
    mutate(r)
    code, data = run(r, manifest_override=manifest_override)
    verdict = (data.get("verdict") or {}).get("activation_would_be")
    assert code == 1, (
        f"{label}: collector exited 0 and returned {verdict!r}; it should BLOCK. "
        f"incomplete={((data.get('verdict') or {}).get('incomplete_sections'))}")


# ------------------------------------------------------------ positive control --
@test("CONTROL: a clean supported installation is PERMITTED")
def _():
    code, data = run(baseline())
    assert code == 0, (
        f"the baseline blocked on {data.get('verdict', {}).get('incomplete_sections')} — "
        "a checklist that blocks everything proves as little as one that blocks nothing")
    assert data["verdict"]["activation_would_be"] == "PERMITTED BY THIS CHECKLIST"
    assert data["observation"]["all_state_reads_pinned_to_block"] is True


# ---------------------------------------------- the fourteen false PERMITTEDs --
@test("REGRESSION: an unreadable Safe guard blocks")
def _():
    expect_blocked("unreadable guard",
                   lambda r: r.__setitem__(f"storage {SAFE} 0x4a204f62", "__FAIL__"))


@test("REGRESSION: an unreadable fallback handler blocks")
def _():
    expect_blocked("unreadable fallback",
                   lambda r: r.__setitem__(f"storage {SAFE} 0x6c9a6c4a", "__FAIL__"))


@test("REGRESSION: an unexpectedly SET guard blocks")
def _():
    expect_blocked("guard set", lambda r: r.__setitem__(
        f"storage {SAFE} 0x4a204f62", "0x" + "00" * 12 + "dd" * 20))


@test("REGRESSION: a Roles module whose owner is not the Safe blocks")
def _():
    expect_blocked("roles owner", lambda r: r.__setitem__(
        f"call {ROLES} owner", "0x" + "de" * 20))


@test("REGRESSION: an unreadable Roles avatar blocks")
def _():
    expect_blocked("roles avatar", lambda r: r.__setitem__(f"call {ROLES} avatar", "__FAIL__"))


@test("REGRESSION: a Roles target pointing elsewhere blocks")
def _():
    expect_blocked("roles target", lambda r: r.__setitem__(
        f"call {ROLES} target", "0x" + "de" * 20))


@test("REGRESSION: a Roles module not enabled on the Safe blocks")
def _():
    expect_blocked("roles not a module", lambda r: r.__setitem__(
        f"call {SAFE} getModulesPaginated",
        f"[{CONTROLLER}]\n0x0000000000000000000000000000000000000001"))


@test("REGRESSION: an unrecognised extra module blocks")
def _():
    expect_blocked("extra module", lambda r: r.__setitem__(
        f"call {SAFE} getModulesPaginated",
        f"[{ROLES}, {CONTROLLER}, {USDC}]\n0x0000000000000000000000000000000000000001"))


@test("REGRESSION: a different chain id blocks")
def _():
    expect_blocked("chain id", lambda r: r.__setitem__("chain-id", "1"))


@test("REGRESSION: an unreadable observation block hash blocks")
def _():
    expect_blocked("block hash", lambda r: r.__setitem__("block", "__FAIL__"))


@test("REGRESSION: a malformed Morpho grant result blocks, and is never read as False")
def _():
    expect_blocked("malformed grant", lambda r: r.__setitem__(
        f"call {MORPHO} isAuthorized", "0x1"))


@test("REGRESSION: a threshold outside the declared profile blocks")
def _():
    expect_blocked("threshold", lambda r: r.__setitem__(f"call {SAFE} getThreshold", "1"))


@test("REGRESSION: unreadable authorization history blocks")
def _():
    expect_blocked("history unreadable", lambda r: r.__setitem__("logs", "__FAIL__"))


@test("REGRESSION: an unreadable token allowance blocks, and is not read as zero")
def _():
    expect_blocked("allowance unreadable",
                   lambda r: r.__setitem__(f"call {USDC} allowance", "__FAIL__"))


# ------------------------------------------- the controller-specific additions --
def _run_without_controller(responses):
    with tempfile.TemporaryDirectory() as d:
        table = os.path.join(d, "r.json")
        json.dump(responses, open(table, "w"))
        shim = os.path.join(d, "cast")
        open(shim, "w").write(f'''#!/usr/bin/env python3
import json,sys
t=json.load(open({table!r})); w=[a for a in sys.argv[1:] if not a.startswith("--")]
b,bl=None,-1
for k,v in t.items():
    p=k.split()
    if len(p)>len(w) or p[0]!=w[0]: continue
    if all(w[i].lower().startswith(x.lower()) or x.lower().startswith(w[i].lower()) for i,x in enumerate(p[1:],start=1)):
        if len(p)>bl: b,bl=v,len(p)
if b is None or b=="__FAIL__": sys.exit(1)
print(b)
''')
        os.chmod(shim, 0o755)
        env = dict(os.environ); env["PATH"] = d + os.pathsep + env["PATH"]
        env.update({"HELD_BASE_RPC": "http://127.0.0.1:1", "HELD_SAFE": SAFE,
                    "HELD_ROLES": ROLES, "HELD_ROLE_KEY": ROLE_KEY,
                    "HELD_ALLOW_KEY": ALLOW_KEY})
        env.pop("HELD_CONTROLLER", None)
        work = os.path.join(d, "w"); os.makedirs(os.path.join(work, "evidence", "P03"))
        p = subprocess.run([sys.executable, COLLECTOR], env=env, cwd=work,
                           capture_output=True, text=True)
        out = os.path.join(work, "evidence", "P03", "bootstrap-rehearsal.json")
        return p.returncode, (json.load(open(out)) if os.path.exists(out) else {})


@test("REGRESSION: no controller supplied blocks — the old rehearsal ran without one")
def _():
    code, data = _run_without_controller(baseline())
    assert code == 1, "a rehearsal with no Held installation reported PERMITTED"
    assert "held_controller" in data["verdict"]["incomplete_sections"]


@test("REGRESSION: an ACTIVE controller is not a fresh installation")
def _():
    expect_blocked("already active",
                   lambda r: r.__setitem__(f"call {CONTROLLER} active", "true"))


@test("REGRESSION: a controller bound to another Safe blocks")
def _():
    expect_blocked("bound elsewhere", lambda r: r.__setitem__(
        f"call {CONTROLLER} safe", "0x" + "de" * 20))


@test("REGRESSION: non-zero prior consumption is not a fresh installation")
def _():
    expect_blocked("consumption", lambda r: r.__setitem__(
        f"call {CONTROLLER} usedSupply", "30000000000"))


# ------------------------------------------------- discovery beyond the list ---
@test("REGRESSION: a grant to an address found only in HISTORY blocks")
def _():
    # The old collector probed a hand-supplied list, so a grant to anyone outside it was
    # never queried and the checklist permitted. Candidates now come from the Safe's
    # bounded authorization history as well.
    outsider = "0x" + "ee" * 20
    def mutate(r):
        r["logs"] = ("address: " + MORPHO + "\ntopics: 0x" + "00" * 32 +
                     "\n0x" + "00" * 12 + outsider[2:] + "\ndata: 0x")
        r[f"call {MORPHO} isAuthorized"] = "false"
        r[f"call {MORPHO} isAuthorized {SAFE} {outsider}"] = "true"
    expect_blocked("history-derived grant", mutate)


# ===================================================================================
# The review of 67eed71: four inputs the collector still PERMITTED, plus the coverage
# it did not have. Every one of these reproduced against the committed collector before
# the fix; each asserts the BLOCK, not merely a changed field.
# ===================================================================================

# ------------------------------- B3: readable is not the same as approved --------
@test("B3: an unreviewed nonzero Safe fallback handler blocks")
def _():
    # It was READ and then never judged. A fallback handler extends the Safe's call
    # surface to code nobody in this profile reviewed.
    expect_blocked("nonzero fallback", lambda r: r.update({
        f"storage {SAFE} 0x6c9a6c4a": "0x" + "00" * 12 + "ab" * 20}))


@test("B3: a readable but UNSUPPORTED Safe implementation version blocks")
def _():
    expect_blocked("unsupported version",
                   lambda r: r.update({f"call {SAFE} VERSION": "0.0.0-unsupported"}))


@test("B3: a successful cast returning garbage where logs belong blocks")
def _():
    # returncode 0 with an undecodable body. "The command worked" is not "the answer is
    # usable", and this used to pass straight through as readable history.
    expect_blocked("garbled logs", lambda r: r.update({"logs": "not-a-valid-log-response"}))


@test("B3: an allowance balance that is not a number blocks, and is never read as zero")
def _():
    expect_blocked("malformed quota", lambda r: r.update({
        f"call {ROLES} allowances {SUPPLY_KEY}": "0\n50000000000\n0\nnot-a-number\n0"}))


@test("B3 CONTROL: legitimately EMPTY history is not confused with garbled history")
def _():
    # The counterpart to the garbled-logs test. A Safe that has never granted anything is
    # a clean installation, and must still pass -- otherwise the fix above is just a
    # checklist that refuses everything.
    r = baseline()
    r["logs"] = ""
    code, data = run(r)
    assert code == 0, (
        f"an empty authorization range was treated as a failure: "
        f"{data.get('verdict', {}).get('incomplete_sections')}")
    assert data["morpho_grants"]["history_range"]["wellformed"] is True


# --------------------- B4: decode the pinned event, do not scrape words ----------
def _log(topic: str, authorizer: str, authorized: str) -> str:
    """One event-shaped log entry, in the shape `cast logs` prints."""
    pad = lambda a: "0x" + "0" * 24 + a[2:].lower()  # noqa: E731
    return ("- address: " + MORPHO + "\n"
            "  topics: [\n"
            f"    {topic}\n"
            f"    {pad(SAFE)}\n"
            f"    {pad(authorizer)}\n"
            f"    {pad(authorized)}\n"
            "  ]\n"
            "  data: 0x" + "0" * 63 + "1\n")


SET_AUTH_TOPIC = "0xd5e969f01efe921d3f766bdebad25f0a05e3f237311f56482bf132d0326309c0"
UNRELATED_TOPIC = "0x" + "1a" * 32
OUTSIDER = "0x9999999999999999999999999999999999999999"


@test("B4: a decoded grant to an outsider is discovered from history and blocks")
def _():
    # The address appears ONLY in the event log. Discovery has to find it, and the mapping
    # readback has to confirm it, or a grant nobody listed is never queried.
    def mutate(r):
        r["logs"] = _log(SET_AUTH_TOPIC, SAFE, OUTSIDER)
        r[f"call {MORPHO} isAuthorized"] = "false"
        r[f"call {MORPHO} isAuthorized {SAFE} {OUTSIDER}"] = "true"
    expect_blocked("decoded outsider grant", mutate)


@test("B4 CONTROL: an event authorized by a DIFFERENT Safe is not our history")
def _():
    # Morpho's authorization mapping is per-authorizer. An event whose authorizer is some
    # other account says nothing about this Safe, and must not become our candidate.
    r = baseline()
    r["logs"] = _log(SET_AUTH_TOPIC, OUTSIDER, OUTSIDER)
    code, data = run(r)
    assert code == 0, (
        f"another Safe's authorization event blocked us: "
        f"{data.get('verdict', {}).get('incomplete_sections')}")
    assert data["morpho_grants"]["events_for_this_safe"] == 0
    assert not any(k.startswith("history_") for k in data["morpho_grants"]["candidates"])


@test("B4 CONTROL: an unrelated Morpho event is not scraped for addresses")
def _():
    # This is what the old implementation did wrong: it regex-extracted the last 20 bytes
    # of every 32-byte word in every Morpho log, so unrelated events donated truncated
    # market ids and hashes as "candidates".
    r = baseline()
    r["logs"] = _log(UNRELATED_TOPIC, SAFE, OUTSIDER)
    code, data = run(r)
    assert code == 1, "a log that is not a SetAuthorization event was silently accepted"
    assert data["morpho_grants"]["malformed_entries"], (
        "an entry with the wrong topic should be reported as malformed, not decoded")
    assert not any(k.startswith("history_") for k in data["morpho_grants"]["candidates"]), (
        "an address was scraped out of an unrelated event")


# ------------------- B2: the FULL declared installation, not one quota -----------
@test("B2: a missing declared installation blocks rather than being inferred")
def _():
    expect_blocked("no manifest", lambda r: None, manifest_override=None)


@test("B2: each of the five budgets is read under its own key")
def _():
    # One generic allowance answer used to satisfy the whole section. Now every dimension
    # is read separately, so any single one being wrong must block.
    for label, key, good in (
        ("supply", SUPPLY_KEY, 50000000000),
        ("normal withdraw", WITHDRAW_KEY, 50000000000),
        ("restoration", RESTORE_KEY, 10000000000),
        ("normal count", NORMAL_COUNT_KEY, 10),
        ("restoration count", RESTORE_COUNT_KEY, 5),
    ):
        expect_blocked(f"{label} budget below the declared limit",
                       lambda r, k=key, g=good: r.update({
                           f"call {ROLES} allowances {k}": allowance(g - 1)}))


@test("B2: a REFILLING budget blocks — the quota would replenish itself")
def _():
    expect_blocked("refilling supply budget", lambda r: r.update({
        f"call {ROLES} allowances {SUPPLY_KEY}": "1000\n50000000000\n3600\n50000000000\n0"}))


@test("B2: a controller bound to budget keys the installation never configured blocks")
def _():
    # Exactly the 03d defect: the controller carried its own keys, nothing on the Roles
    # side configured them, and reading them back returned zero for every dimension.
    expect_blocked("controller key mismatch", lambda r: r.update({
        f"call {CONTROLLER} restorationAllowanceKey": "0x" + "ee" * 32}))


@test("B2: a controller whose market or lineage is not the declared one blocks")
def _():
    expect_blocked("wrong market",
                   lambda r: r.update({f"call {CONTROLLER} marketId": "0x" + "ee" * 32}))
    expect_blocked("wrong lineage",
                   lambda r: r.update({f"call {CONTROLLER} lineage": "0x" + "ee" * 32}))


@test("B2: an installation with no SELECTED operating identities blocks")
def _():
    # The old section reported the Safe's owners and called itself complete. Owners are a
    # different clause, already covered by the safe section.
    code, data = run(baseline(), env_override={"HELD_RUNNER": None})
    assert code == 1, "an installation with no selected runner reported complete"
    assert "runner" in data["identities"]["missing"], data["identities"]
    assert data["identities"]["public_chain_facts"]["safe_owners"], (
        "the owners are still reported -- they are a different clause, not this one")


# ------------- B2: membership and conditions, with both directions covered -------
@test("B2: a controller that is NOT a member of a configured role blocks")
def _():
    expect_blocked("controller not a member", lambda r: r.update({
        f"~rpc~{EXEC_WITHDRAW_OK}": "__ERR__Error: execution reverted: custom error "
                                    f"{NO_MEMBERSHIP}, data: \"{NO_MEMBERSHIP}\""}))


@test("B2: a condition tree that PERMITS the wrong receiver blocks")
def _():
    # The negative direction. A tree that permits everything is not a restriction, and a
    # probe set that never expects a refusal could not tell.
    expect_blocked("wrong receiver permitted", lambda r: r.update({
        f"~rpc~{EXEC_WITHDRAW_BAD}": "0x" + "0" * 63 + "1"}))


@test("B2: an unrecognised revert is UNREADABLE, not filed as a condition refusal")
def _():
    # Guessing here is how an unconfigured tree would have looked like a working one.
    expect_blocked("unknown revert", lambda r: r.update({
        f"~rpc~{EXEC_WITHDRAW_BAD}": "__ERR__Error: execution reverted: custom error "
                                     "0xdeadbeef, data: \"0xdeadbeef\""}))


@test("B2: a probe the sender cannot even pay for is UNREADABLE, not a refusal")
def _():
    # The failure mode that produced four UNREADABLE probes while this was being built:
    # the controller held no gas, so eth_call never reached the Roles module. That must
    # not read as "the installation refuses", which would be a false clean bill.
    expect_blocked("probe could not run", lambda r: r.update({
        f"~rpc~{EXEC_SUPPLY}": "__ERR__Error: server returned an error response: "
                               "error code -32003: Insufficient funds for gas * price + value"}))


def main() -> int:
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"P03 bootstrap collector: FAIL ({len(FAILED)}/{len(PASSED)+len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} bootstrap-collector decision tests held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
