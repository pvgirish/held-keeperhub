#!/usr/bin/env python3
"""Find the contradictions a reader would find, before a judge does.

A repository that has been corrected three times accumulates sentences that were true when
written. They are the most damaging kind of error in a submission, because each one is
evidence that the rest of the document cannot be trusted either -- and unlike a bug, no
test fails when one appears.

This is mechanical. It does not read for tone or completeness; it looks for statements
that can be checked against the repository as it is now:

  * **broken pointers** — a documented path or `make` target that does not exist
  * **claims of absence that are now false** — "no credential exists" survived in
    `docs/ENVIRONMENT.md` for a day after one did
  * **grade inflation** — any document asserting PUBLIC CHAIN evidence while M1 is
    unestablished
  * **the M1 blocker story** — M1 is open because nothing has been executed publicly, NOT
    because a credential is missing. The second reading was wrong and was corrected; this
    keeps it corrected.
  * **counted claims** — "N tests" in a document against what the suites actually print
  * **dates** — an "as of" date in the future, or a recorded date after today

Every finding names the file and line. Exit non-zero if any is found: a contradiction is
not a warning, because the reader cannot tell which of the two statements to believe.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "evidence", "M1", "stale-audit.json")
TODAY = date.today()

FINDINGS: list[dict] = []


def finding(kind: str, path: str, line: int, detail: str, quote: str = "") -> None:
    FINDINGS.append({"kind": kind, "file": os.path.relpath(path, ROOT), "line": line,
                     "detail": detail, "quote": quote[:160]})


def docs() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT,
                         capture_output=True, text=True).stdout.split()
    # Untracked submission material counts too -- it is what a judge would read.
    for d in ("docs/submission", "docs"):
        full = os.path.join(ROOT, d)
        for dirpath, _dirs, files in os.walk(full):
            for f in files:
                rel = os.path.relpath(os.path.join(dirpath, f), ROOT)
                if f.endswith(".md") and rel not in out:
                    out.append(rel)
    if "README.md" not in out:
        out.append("README.md")
    return sorted(set(out))


def lines_of(rel: str):
    path = os.path.join(ROOT, rel)
    try:
        with open(path, errors="replace") as fh:
            return path, fh.read().splitlines()
    except OSError:
        return path, []


# ------------------------------------------------------------------- the checks --
def check_pointers(rel: str, path: str, lines: list[str]) -> None:
    """Every `path/like/this` and `make target` a document names must exist."""
    targets = set()
    mk = os.path.join(ROOT, "Makefile")
    if os.path.exists(mk):
        with open(mk) as fh:
            targets = set(re.findall(r"^([a-z0-9][a-z0-9-]*):", fh.read(), re.M))

    for i, line in enumerate(lines, 1):
        for m in re.finditer(r"`make ([a-z0-9][a-z0-9-]*)`", line):
            if m.group(1) not in targets:
                finding("broken-make-target", path, i,
                        f"`make {m.group(1)}` is not a target in the Makefile", line)
        for m in re.finditer(r"`((?:docs|script|evidence|tests|packages|adapter|console|"
                             r"contracts|fixtures|test)/[A-Za-z0-9_./-]+)`", line):
            p = m.group(1).rstrip(".,;:")
            if p.endswith("/"):
                continue
            if not os.path.exists(os.path.join(ROOT, p)):
                # A path with a glob or a placeholder segment is not a claim about a file.
                if any(c in p for c in "*?<>") or "…" in p:
                    continue
                # A line whose whole point is that the path is MISSING is not stale; the
                # P00 report says exactly that about the SDK's own test helpers.
                if re.search(r"does not exist|is absent|missing|cannot be collected",
                             line, re.I):
                    continue
                finding("broken-path", path, i, f"`{p}` does not exist", line)


ABSENCE_PATTERNS = [
    (r"[Dd]oes not exist in this environment", "HELD_KEEPERHUB_API_KEY",
     "the organisation credential now exists and is validated (P30)"),
    (r"[Nn]o organisation credential is present", None,
     "a credential is present; see evidence/P03/l10-route-proof.json"),
    (r"[Nn]o `?AUTHENTICATED HOSTED`? row exists", None,
     "P30 is an AUTHENTICATED HOSTED row"),
    (r"blocked on (obtaining )?(an? )?`?mcp:read", None,
     "M1 is not credential-blocked; the read key is configured and validated"),
    (r"three owner addresses are not supplied", None,
     "the three final owners were supplied on 2026-09-18"),
    (r"address not yet supplied", None,
     "the owner and runner addresses were supplied on 2026-09-18"),
]


def check_absence_claims(rel: str, path: str, lines: list[str]) -> None:
    for i, line in enumerate(lines, 1):
        for pattern, near, why in ABSENCE_PATTERNS:
            if not re.search(pattern, line):
                continue
            if near and near not in line:
                continue
            # A line that is explicitly quoting the old wording to correct it is fine.
            if re.search(r"used to read|previously read|corrected|was wrong|no longer",
                         line, re.I):
                continue
            finding("stale-absence-claim", path, i, why, line)


def check_grades(rel: str, path: str, lines: list[str], m1_open: bool) -> None:
    if not m1_open:
        return
    for i, line in enumerate(lines, 1):
        if "PUBLIC CHAIN" not in line:
            continue
        # Naming the grade in order to say it is absent is the correct usage.
        if re.search(r"\bno\b|\bnone\b|not |never |absent|cannot|may not|would|"
                     r"refus|above|promot|grade[s]? are|>|yet", line, re.I):
            continue
        finding("grade-inflation", path, i,
                "asserts PUBLIC CHAIN evidence while M1 is NOT YET ESTABLISHED", line)


def check_dates(rel: str, path: str, lines: list[str]) -> None:
    for i, line in enumerate(lines, 1):
        for m in re.finditer(r"\b(20\d\d)-(\d\d)-(\d\d)\b", line):
            try:
                when = datetime.strptime(m.group(0), "%Y-%m-%d").date()
            except ValueError:
                continue
            if when > TODAY:
                finding("future-date", path, i,
                        f"{m.group(0)} is in the future (today is {TODAY})", line)


def check_counts() -> None:
    """Numbers a document asserts about the suites, against what the suites print."""
    index = os.path.join(ROOT, "docs", "submission", "EVIDENCE-INDEX.md")
    if not os.path.exists(index):
        return
    with open(index) as fh:
        text = fh.read()

    claimed = {}
    for m in re.finditer(r"`(tests/[A-Za-z0-9_./]+\.py)`[^|]*\|\s*\*?\*?(\d+)\s*pass", text):
        claimed[m.group(1)] = int(m.group(2))
    for m in re.finditer(r"\|\s*`?(tests/[A-Za-z0-9_./]+\.py)`?[^|]*\|\s*(\d+)\s*pass", text):
        claimed.setdefault(m.group(1), int(m.group(2)))

    for rel, want in sorted(claimed.items()):
        full = os.path.join(ROOT, rel)
        if not os.path.exists(full):
            finding("broken-path", index, 0, f"`{rel}` does not exist")
            continue
        run = subprocess.run([sys.executable, full], cwd=ROOT, capture_output=True,
                             text=True, env={**os.environ,
                                             "HELD_PRICE_MODE": "testing-only"})
        m = re.search(r"all (\d+) ", run.stdout)
        if not m:
            continue
        got = int(m.group(1))
        if got != want:
            finding("stale-count", index, 0,
                    f"{rel}: the index says {want} pass, the suite reports {got}")


def m1_is_open() -> bool:
    ledger = os.path.join(ROOT, "docs", "submission", "CLAIM-LEDGER.md")
    if not os.path.exists(ledger):
        return True
    with open(ledger) as fh:
        for line in fh:
            if line.startswith("| M1 "):
                return "NOT YET ESTABLISHED" in line
    return True


def main() -> int:
    print("HELD — stale-version and contradiction audit")
    print("=" * 78)
    m1_open = m1_is_open()
    print(f"M1 open: {m1_open}   today: {TODAY}\n")

    for rel in docs():
        path, lines = lines_of(rel)
        if not lines:
            continue
        check_pointers(rel, path, lines)
        check_absence_claims(rel, path, lines)
        check_grades(rel, path, lines, m1_open)
        check_dates(rel, path, lines)

    print("counted claims — running the suites the evidence index names")
    check_counts()

    by_kind: dict[str, int] = {}
    for f in FINDINGS:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1

    if FINDINGS:
        print()
        for f in sorted(FINDINGS, key=lambda x: (x["kind"], x["file"], x["line"])):
            where = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
            print(f"  [{f['kind']}] {where}")
            print(f"      {f['detail']}")
            if f["quote"]:
                print(f"      > {f['quote'].strip()}")
    else:
        print("\n  no contradictions found")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump({"schema": "held.stale-audit.v1", "label": "PREPARED",
                   "audited_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "m1_open": m1_open, "counts": by_kind,
                   "findings": FINDINGS}, fh, indent=1)
        fh.write("\n")

    print("\n" + "=" * 78)
    print(f"  {len(FINDINGS)} finding(s)  {by_kind or ''}")
    print(f"  written: {os.path.relpath(OUT, ROOT)}")
    return 1 if FINDINGS else 0


if __name__ == "__main__":
    raise SystemExit(main())
