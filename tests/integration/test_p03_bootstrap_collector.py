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
        f"call {ROLES} allowances": "0\n50000000000\n0\n50000000000\n0",
        f"call {ROLES} owner": SAFE,
        f"call {ROLES} avatar": SAFE,
        f"call {ROLES} target": SAFE,
        "logs": "",
        f"call {MORPHO} isAuthorized": "false",
        f"call {USDC} allowance": "0",
        f"call {CONTROLLER} active": "false",
        f"call {CONTROLLER} epoch": "0",
        f"call {CONTROLLER} safe": SAFE,
        f"call {CONTROLLER} roles": ROLES,
        f"call {CONTROLLER} morpho": MORPHO,
        f"call {CONTROLLER} token": USDC,
        f"call {CONTROLLER} usedSupply": "0",
        f"call {CONTROLLER} usedNormalWithdraw": "0",
        f"call {CONTROLLER} usedRestoration": "0",
        f"call {CONTROLLER} normalCount": "0",
        f"call {CONTROLLER} restorationCount": "0",
    }


def run(responses: dict[str, str]) -> tuple[int, dict]:
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
best, best_len = None, -1
for key, val in table.items():
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
print(best)
''')
        os.chmod(shim, 0o755)

        env = dict(os.environ)
        env["PATH"] = d + os.pathsep + env["PATH"]
        env.update({
            "HELD_BASE_RPC": "http://127.0.0.1:1",  # never contacted; the shim answers
            "HELD_SAFE": SAFE, "HELD_ROLES": ROLES,
            "HELD_ROLE_KEY": ROLE_KEY, "HELD_ALLOW_KEY": ALLOW_KEY,
            "HELD_CONTROLLER": CONTROLLER,
        })
        for stray in ("HELD_RUNNER_A", "HELD_RUNNER_B", "HELD_EXECUTOR"):
            env.pop(stray, None)

        work = os.path.join(d, "work")
        os.makedirs(os.path.join(work, "evidence", "P03"), exist_ok=True)
        proc = subprocess.run([sys.executable, COLLECTOR], env=env, cwd=work,
                              capture_output=True, text=True)
        out = os.path.join(work, "evidence", "P03", "bootstrap-rehearsal.json")
        data = json.load(open(out)) if os.path.exists(out) else {}
        return proc.returncode, data


def expect_blocked(label: str, mutate) -> None:
    r = baseline()
    mutate(r)
    code, data = run(r)
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
