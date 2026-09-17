#!/usr/bin/env python3
"""P07: can somebody else pick this up?

Clones the repository into an isolated temporary directory and checks what an outside
developer would actually hit. Deliberately does NOT reuse this working tree, because a
working tree hides exactly the problems this is looking for: files that were never
committed, dependencies that happen to be present, absolute paths that happen to resolve.

What it establishes:
  * the repository clones and its submodules are pinned and resolvable
  * no source file depends on a private absolute path
  * no secret is committed
  * every environment variable the code requires is documented
  * the pure-Python gates run from the clone

What it does NOT establish: that a fresh machine has Foundry, CPython 3.12 and the pinned
Almanak SDK. Those are external and documented; this check states them as prerequisites
rather than pretending to verify them.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

problems: list[str] = []
notes: list[str] = []


def check(name: str, passed: bool, detail: str) -> None:
    print(f"  [{'PASS' if passed else 'FAIL'}] {name} — {detail}")
    if not passed:
        problems.append(f"{name}: {detail}")


def run(cmd: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def main() -> int:
    print("HELD — clean install check (P07)")
    print("=" * 74)

    with tempfile.TemporaryDirectory() as tmp:
        clone = os.path.join(tmp, "held")
        print(f"\nCloning into an isolated directory")
        r = run(["git", "clone", "--quiet", ROOT, clone], cwd=tmp)
        if r.returncode != 0:
            check("clone", False, r.stderr.strip()[:200])
            return 1
        check("clone", True, "the repository clones from its own history")

        # -------------------------------------------------------------- submodules --
        gitmodules = os.path.join(clone, ".gitmodules")
        if os.path.exists(gitmodules):
            r = run(["git", "submodule", "status"], cwd=clone)
            entries = [ln for ln in r.stdout.splitlines() if ln.strip()]
            check("submodules-declared", bool(entries),
                  f"{len(entries)} submodule(s) declared and pinned")
            unpinned = [e for e in entries if e.startswith("-")]
            notes.append(f"{len(unpinned)} submodule(s) not checked out in the clone "
                         "(expected: `git submodule update --init --recursive`)")
        else:
            check("submodules-declared", False, "no .gitmodules, but lib/ is used")

        # --------------------------------------------------- no private absolute paths --
        print("\nPortability")
        offenders: list[str] = []
        home = os.path.expanduser("~")
        user = os.path.basename(home)
        src_files = run(["git", "ls-files", "*.py", "*.sh", "*.sol", "Makefile"],
                        cwd=clone).stdout.split()
        for rel in src_files:
            full = os.path.join(clone, rel)
            try:
                with open(full, errors="replace") as fh:
                    body = fh.read()
            except OSError:
                continue
            # A hardcoded /Users/<name>/ path makes the repository unusable elsewhere.
            for m in re.finditer(r"/Users/[A-Za-z0-9._-]+/", body):
                # $HOME and ~ expansions are fine; a literal path is not.
                offenders.append(f"{rel}: {m.group(0)}")
        check("no-private-paths", not offenders,
              "no source file hardcodes a private home directory"
              if not offenders else f"{len(offenders)}: {offenders[:3]}")

        # ------------------------------------------------------------------ secrets --
        print("\nSecrets")
        leaked: list[str] = []
        # Anvil's deterministic keys are public and documented; anything else 32-byte and
        # key-shaped in a non-fixture file is suspicious.
        anvil = {
            "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
            "59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
            "5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
            "7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
            "47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a",
            "8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba",
            "92db14e403b83dfe3df233f83dfa3a0d7096f21ca9b0d6d6b8d88b2b4ec1564e",
            "4bbbf85ce3377467afe5d46f804f221813b2bb87f24d81f60f1fcdbf7cbf4356",
            "dbda1821b80551c9d65939329250298aa3472ba22feea921c0cf5d620ea67b97",
            "2a871d0798f97d79848a013d4936a73bf4cc922c825d33c1cf7073dff6d409c6",
        }
        for rel in src_files:
            try:
                with open(os.path.join(clone, rel), errors="replace") as fh:
                    body = fh.read()
            except OSError:
                continue
            for m in re.finditer(r"0x([0-9a-fA-F]{64})\b", body):
                if m.group(1).lower() in anvil:
                    continue
                # A 32-byte constant is usually a hash, key id or selector. Only flag it
                # where the surrounding line calls it a private key.
                line = body[:m.start()].rsplit("\n", 1)[-1] + m.group(0)
                if re.search(r"(private[_ ]?key|PK_|secret|mnemonic)", line, re.I):
                    leaked.append(f"{rel}: {line.strip()[:80]}")
        check("no-committed-secrets", not leaked,
              "no non-anvil key material in tracked source"
              if not leaked else f"{len(leaked)}: {leaked[:2]}")

        # ------------------------------------------------- environment documentation --
        print("\nEnvironment")
        required: set[str] = set()
        for rel in src_files:
            try:
                with open(os.path.join(clone, rel), errors="replace") as fh:
                    body = fh.read()
            except OSError:
                continue
            required |= set(re.findall(r'os\.environ\["(HELD_[A-Z0-9_]+)"\]', body))
        docs = ""
        for d in ("README.md", "RESUME.md", "docs/ENVIRONMENT.md",
                  "docs/decisions/environment-setup.md",
                  "docs/submission/DEMO-RUNBOOK.md", "Makefile",
                  "script/run_hero_demo.sh", "script/collect_bootstrap_evidence.sh"):
            p = os.path.join(clone, d)
            if os.path.exists(p):
                with open(p, errors="replace") as fh:
                    docs += fh.read()
        undocumented = sorted(v for v in required if v not in docs)
        check("env-documented", not undocumented,
              f"{len(required)} required HELD_* variable(s), all documented"
              if not undocumented else f"undocumented: {undocumented}")

        # ------------------------------------------------- pure-Python gates from clone --
        print("\nGates that need no fork")
        py = sys.executable
        for rel in ("tests/handover/test_handover_machine.py",
                    "tests/authority/test_authority_inventory.py",
                    "tests/integration/test_p05_live_views.py"):
            r = run([py, rel], cwd=clone)
            tail = (r.stdout.strip().splitlines() or ["(no output)"])[-1]
            check(os.path.basename(rel), r.returncode == 0, tail[:96])

        # ----------------------------------------------------------- entry points --
        print("\nEntry points a newcomer would try")
        for target in ("hero-demo", "check-phase-04", "check-phase-05"):
            r = run(["make", "-n", target], cwd=clone)
            check(f"make {target}", r.returncode == 0,
                  "declared in the Makefile" if r.returncode == 0
                  else r.stderr.strip()[:96])

    print("\n" + "=" * 74)
    for n in notes:
        print(f"  note: {n}")
    print("\nPREREQUISITES NOT VERIFIED HERE (external, documented):")
    print("  CPython 3.12, Foundry, and the pinned Almanak SDK at")
    print("  6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938. See docs/decisions/environment-setup.md")
    if problems:
        print(f"\nclean-install: FAIL ({len(problems)} problem(s))")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nclean-install: PASS (isolated clone; external prerequisites assumed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
