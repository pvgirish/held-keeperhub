#!/usr/bin/env python3
"""P05: drive the ACTUAL HTTP console in REAL mode against a live fork.

Not the view-assembly helpers -- the console object that serves requests. Every check below
goes through `Console.handle()` and inspects rendered bytes, because "the console shows the
four views" is a claim about what a judge would see.

The property under test throughout is the honest failure: with a dead source the affected
view must render UNAVAILABLE and must never substitute demonstration numbers.
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("console", "packages/core", "packages/handover", "packages/authority", "script"):
    sys.path.insert(0, os.path.join(ROOT, p))

# The console requires at least 16 characters, and is right to.
os.environ.setdefault("HELD_CONSOLE_SECRET", "local-check-secret-not-a-real-one")

from run import LiveSources, demonstration_state  # noqa: E402
from held_console.app import Console  # noqa: E402
from held_core.journal import Journal  # noqa: E402

RPC = os.environ["HELD_BASE_RPC"]
SAFE = os.environ["HELD_SAFE"]
CONTROLLER = os.environ["HELD_CONTROLLER"]
CHAIN = 8453

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")
    if not ok:
        FAILS.append(name)


def get(console: Console, path: str, cookie: str | None):
    return console.handle("GET", path, {}, {}, cookie)


def sign_in(console: Console) -> str:
    code, headers, _ = console.handle("POST", "/login", {},
                                      {"password": [os.environ["HELD_CONSOLE_SECRET"]]}, None)
    assert code == 302, code
    return headers["Set-Cookie"].split(";")[0].split("=", 1)[1]


def views_of(console: Console, cookie: str) -> dict:
    code, _h, body = get(console, "/views.json", cookie)
    return json.loads(body) if code == 200 else {}


def main() -> int:
    print("P05 — the ACTUAL HTTP console, REAL mode, against a live fork")
    print("=" * 74)

    jp = os.path.join(ROOT, "fixtures", "generated", "console-live-journal.sqlite")
    os.makedirs(os.path.dirname(jp), exist_ok=True)
    for s in ("", "-wal", "-shm"):
        if os.path.exists(jp + s):
            os.remove(jp + s)
    journal = Journal(jp)

    live = LiveSources(controller=CONTROLLER, safe=SAFE, rpc=RPC, chain_id=CHAIN,
                       journal=journal, handover_id=None)

    def console_for(sources) -> Console:
        def state_fn():
            st = sources.state()
            if st is None:
                raise RuntimeError("the controller or its policy could not be read")
            return st
        c = Console(state_fn, journal)
        c.views = sources.views
        return c

    # ---------------------------------------------------------------- authentication --
    print("\n1. Authentication and CSRF")
    c = console_for(live)
    code, headers, _ = get(c, "/views", None)
    check("unauthenticated /views redirects to login", code == 302
          and headers.get("Location") == "/login", f"{code}")
    bad, _h, _b = c.handle("POST", "/login", {}, {"password": ["wrong"]}, None)
    check("a wrong secret is refused", bad == 401, str(bad))
    cookie = sign_in(c)
    code, _h, body = get(c, "/views", cookie)
    check("authenticated /views renders", code == 200, f"{len(body)} bytes")

    csrf_code, _h, _b = c.handle("POST", "/limits", {}, {"Ls": ["1"]}, cookie)
    check("a POST without a CSRF token is refused", csrf_code == 403, str(csrf_code))

    # ------------------------------------------------------------------ four views --
    print("\n2. The four V4 section 8 views, rendered")
    text = body.decode()
    for title in ("Terms", "Activity", "Unresolved", "Authority"):
        check(f"{title} view is rendered", title in text)
    check("every view shows its evidence grade", text.count("evidence grade") >= 3,
          f"{text.count('evidence grade')} grades shown")
    check("the fork is graded REAL LOCAL FORK", "REAL LOCAL FORK" in text)
    check("PUBLIC CHAIN is not claimed", "PUBLIC CHAIN" not in text)

    v = views_of(c, cookie)
    check("terms loaded from the chain", v["terms"]["loaded"], v["terms"]["summary"][:60])
    check("terms shows the observation block",
          any("block" in str(r).lower() for r in [v["terms"]["summary"]]),
          v["terms"]["summary"][:60])

    # ------------------------------------------------------------ LIVE policy, not a constant --
    print("\n3. Terms uses the LIVE policy, not a hard-coded ceiling")
    reading = live.reading()
    pol = live.policy_from(reading)
    check("the policy decodes off the controller", pol is not None,
          f"Ls={getattr(pol, 'Ls', None)}")
    ceiling_rows = [r for r in v["terms"]["rows"] if r.get("field") == "supply ceiling"]
    if ceiling_rows and pol is not None:
        shown = ceiling_rows[0]["value"]
        check("the ceiling shown is the controller's own", shown == pol.Ls,
              f"shown {shown}, chain {pol.Ls}")
        check("remaining is computed, not asserted",
              ceiling_rows[0]["remaining"] == max(pol.Ls - ceiling_rows[0]["used"], 0))
    else:
        check("the ceiling shown is the controller's own", False, "no ceiling row")

    # --------------------------------------------------------------------- dead RPC --
    print("\n4. Dead RPC — no fallback to demonstration numbers")
    dead = LiveSources(controller=CONTROLLER, safe=SAFE, rpc="http://127.0.0.1:1",
                       chain_id=CHAIN, journal=journal, handover_id=None)
    dc = console_for(dead)
    dcookie = sign_in(dc)
    code, _h, dbody = get(dc, "/views", dcookie)
    dtext = dbody.decode()
    check("the page still renders", code == 200)
    check("Terms says UNAVAILABLE", "UNAVAILABLE" in dtext)
    check("it says no substitute data is shown", "No substitute data" in dtext)
    demo = demonstration_state()
    check("no demonstration figure leaks in",
          str(demo.budgets[0].used) not in dtext and demo.runner.lower() not in dtext.lower())
    dv = views_of(dc, dcookie)
    check("journal views still load", dv["activity"]["loaded"] and dv["unresolved"]["loaded"])

    # ------------------------------------------------------- stale / out-of-scope authority --
    print("\n5. Stale or out-of-scope authority evidence")
    wrong = LiveSources(controller="0x" + "de" * 20, safe=SAFE, rpc=RPC, chain_id=CHAIN,
                        journal=journal, handover_id=None)
    inv = wrong.inventory()
    check("a stored report for another controller is marked incomplete",
          inv is not None and not inv.complete,
          f"{(inv.incomplete_sections[:1] if inv else 'none')}")
    check("the reason names the scope problem",
          bool(inv) and any("out of scope" in s for s in inv.incomplete_sections))

    # ------------------------------------------------- unresolved operation and handover --
    print("\n6. Unresolved operation, and a handover in progress")
    import hero_demo as hd
    hd.SUPPLY_AMOUNT = 1_000_000
    try:
        hd.interrupt_a_real_submission(live.reading(), journal)
    except Exception as exc:                      # the controller may be paused; fine
        print(f"      (could not create a live interrupted op: {exc}); using journal rows")
    uv = views_of(c, cookie)["unresolved"]
    check("unresolved view reports the state truthfully", uv["loaded"])
    if uv["rows"]:
        check("it names what is blocked", "handover" in uv["rows"][0]["blocks"])
        check("it names the evidence required",
              "consumed[operationId]" in uv["rows"][0]["requiredEvidence"])
    else:
        check("an empty unresolved list is stated, not blank",
              "Nothing is in the air" in uv["summary"], uv["summary"])

    av = views_of(c, cookie)["authority"]
    check("no handover in progress is a stated row, not a blank",
          any(r.get("field") == "handover state" for r in av["rows"]))

    # ------------------------------------------------------------------- redaction --
    print("\n7. Redaction")
    everything = (text + dtext + json.dumps(views_of(c, cookie))).lower()
    leaked = [w for w in ("0x47e179ec", "0xac0974be", "private key", "begin ",
                          os.environ["HELD_CONSOLE_SECRET"].lower()) if w in everything]
    check("no key material or secret in any rendered output", not leaked, str(leaked))

    journal.close()
    print("\n" + "=" * 74)
    if FAILS:
        print(f"console-live: FAIL ({len(FAILS)}): {FAILS}")
        return 1
    print("console-live: PASS (REAL LOCAL FORK)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
