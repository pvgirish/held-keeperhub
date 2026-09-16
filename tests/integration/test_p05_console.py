"""P05: the private operator console.

Covers the four operator jobs, authentication and privacy, owner-approval legibility and
the recovery export. The jobs are named explicitly in the test names so that if the
locked V4 wording differs from the derivation recorded in held_console/state.py, the
mismatch is visible here rather than buried.

The four jobs, derived from the locked product sentence:
  J1 run the strategy under customer-approved limits
  J2 change those limits under owner approval
  J3 replace the runner
  J4 resolve an interrupted operation without guessing what it did
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "packages", "core"))
sys.path.insert(0, os.path.join(ROOT, "console"))

from held_console.app import (  # noqa: E402
    SESSION_COOKIE,
    Console,
    ConsoleError,
    ConsoleNotPrivate,
    Sessions,
    esc,
    serve,
)
from held_console.state import (  # noqa: E402
    Budget,
    Job,
    LiveState,
    prepare_limit_change,
    prepare_runner_replacement,
    read_interruptions,
    usdc,
)
from held_core.journal import Journal, OperationState  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

SECRET_ENV = "HELD_CONSOLE_SECRET"
SECRET = "a-sufficiently-long-console-secret"
SAFE = "0x08deEDA0Ba1eb4B6B4b5cc4DD0c4BC689EA37180"
CONTROLLER = "0x3875311cc0d4017a033893a9653a0725378aca1c"
RUNNER = "0x90F79bf6EB2c4f870365E785982E1f101E93b906"
NEW_RUNNER = "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65"
EXECUTOR = "0x976EA74026E726554dB657fA54763abd0C3a0aa9"


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


def expect(exc_type, fn, *a, **k) -> str:
    try:
        fn(*a, **k)
    except exc_type as e:
        return str(e)
    raise AssertionError(f"expected {exc_type.__name__}, nothing raised")


def live(active=True, used_supply=5_000_000_000, native=None) -> LiveState:
    return LiveState(
        controller=CONTROLLER, safe=SAFE, active=active, epoch=3, policy_version=1,
        runner=RUNNER, executor=EXECUTOR,
        budgets=[
            Budget("supply", 50_000_000_000, used_supply),
            Budget("normal_withdraw", 20_000_000_000, 0),
            Budget("restoration", 10_000_000_000, 0),
            Budget("normal_count", 100, 3, unit="operations"),
        ],
        native_remaining=native if native is not None else {
            "supply": 50_000_000_000 - used_supply,
            "normal_withdraw": 20_000_000_000,
            "restoration": 10_000_000_000,
            "normal_count": 97,
        },
        cooldowns={"normal": 3600, "restoration": 0},
    )


class Jrnl:
    """A journal stub exposing only what the console reads."""

    def __init__(self, ops=(), attempts=None):
        self._ops = list(ops)
        self._attempts = attempts or {}

    def unresolved(self):
        return self._ops

    def attempts_for(self, oid):
        return self._attempts.get(oid, [])


class Op:
    def __init__(self, oid, state, epoch=3):
        self.operation_id = oid
        self.payload_hash = "0x" + "cc" * 32
        self.state = state
        self.epoch = epoch
        self.source_decision_id = "decision-1"
        self.action_index = 0


def console(journal=None, state_fn=None) -> Console:
    os.environ[SECRET_ENV] = SECRET
    return Console(state_fn or live, journal or Jrnl(), secret_ref=f"env:{SECRET_ENV}")


def signed_in(c: Console) -> str:
    token = c.login(SECRET)
    assert token
    return token


def get(c: Console, path: str, cookie=None, form=None, method="GET"):
    return c.handle(method, path, {}, form or {}, cookie)


# ------------------------------------------------------ authentication & privacy --
@test("every route except login is private; an unauthenticated caller sees nothing")
def _():
    c = console(Jrnl([Op("0x" + "aa" * 32, OperationState.UNKNOWN)]))
    for path in ("/", "/limits", "/runner", "/interrupted", "/export", "/prepared.json"):
        status, headers, body = get(c, path)
        assert status == 302 and headers["Location"] == "/login", (path, status)
        assert body == b"", f"{path} leaked a body to an unauthenticated caller"


@test("a wrong secret is refused, and the check is constant-time")
def _():
    import inspect
    from held_console import app
    c = console()
    assert c.login("wrong") is None
    assert c.login("") is None
    assert c.login(SECRET) is not None
    # A plain == would leak the secret by timing to a local attacker.
    assert "compare_digest" in inspect.getsource(app.Console.login)


@test("the console secret is a reference, and a weak or absent one is refused")
def _():
    os.environ.pop(SECRET_ENV, None)
    assert "unset" in expect(ConsoleError, Console, live, Jrnl(), secret_ref=f"env:{SECRET_ENV}")
    os.environ[SECRET_ENV] = "short"
    assert "16 characters" in expect(
        ConsoleError, Console, live, Jrnl(), secret_ref=f"env:{SECRET_ENV}")
    os.environ[SECRET_ENV] = SECRET
    assert "env:NAME" in expect(ConsoleError, Console, live, Jrnl(), secret_ref=SECRET)


@test("the console refuses to bind anywhere but localhost without an explicit override")
def _():
    c = console()
    msg = expect(ConsoleNotPrivate, serve, c, "0.0.0.0", 8799)
    assert "different threat model" in msg, msg
    srv = serve(c, "127.0.0.1", 0)
    srv.server_close()


@test("sessions expire, and a stale cookie is not a session")
def _():
    now = [1000.0]
    s = Sessions(ttl=60, now=lambda: now[0])
    tok = s.create()
    assert s.get(tok) is not None
    now[0] += 61
    assert s.get(tok) is None, "an expired session must not authenticate"
    assert s.get("not-a-token") is None
    assert s.get(None) is None


@test("state-changing forms require a CSRF token bound to the session")
def _():
    c = console()
    tok = signed_in(c)
    csrf = c.sessions.get(tok)["csrf"]

    status, _, body = get(c, "/limits", tok, {"ceiling_supply": ["1"]}, "POST")
    assert status == 403 and b"CSRF" in body, "a POST with no CSRF token was accepted"

    status, _, body = get(c, "/limits", tok,
                          {"csrf": ["wrong"], "ceiling_supply": ["1"]}, "POST")
    assert status == 403, "a POST with a wrong CSRF token was accepted"

    status, _, body = get(c, "/limits", tok,
                          {"csrf": [csrf], "ceiling_supply": ["1000000000"]}, "POST")
    assert status == 200 and b"What changes" in body


@test("interpolated values are escaped, so state cannot inject markup")
def _():
    hostile = "<script>alert(1)</script>"
    assert "<script>" not in esc(hostile)
    c = console(state_fn=lambda: LiveState(
        controller=hostile, safe=SAFE, active=True, epoch=1, policy_version=1,
        runner=hostile, executor=EXECUTOR, budgets=[Budget("supply", 10, 1)],
        native_remaining={"supply": 9}, cooldowns={"normal": 0}))
    tok = signed_in(c)
    _, _, body = get(c, "/", tok)
    assert b"<script>alert" not in body
    assert b"&lt;script&gt;" in body


@test("responses carry the headers a funds-facing console should carry")
def _():
    # Asserted against the handler source: the header block is written once, and a
    # regression there would silently weaken every page.
    import inspect
    from held_console import app
    src = inspect.getsource(app.make_handler)
    for header in ("X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy",
                   "Content-Security-Policy", "HttpOnly", ):
        assert header in src or header in inspect.getsource(app.Console.handle), header


# -------------------------------------------------------------------------- J1 --
@test("J1: the dashboard shows limits, usage and remaining budget in readable units")
def _():
    c = console()
    tok = signed_in(c)
    _, _, body = get(c, "/", tok)
    text = body.decode()
    assert "50,000.000000" in text, "ceiling not rendered in USDC"
    assert "5,000.000000" in text, "usage not rendered in USDC"
    assert "45,000.000000" in text, "remaining not computed"
    # Raw base units to an owner approving a limit is how somebody approves 1000x.
    assert "50000000000" not in text


@test("J1: the console names its own authority as none")
def _():
    c = console()
    _, _, body = get(c, "/", signed_in(c))
    text = body.decode()
    assert "holds no keys" in text and "broadcasts nothing" in text
    assert RUNNER.lower() in text.lower() and EXECUTOR.lower() in text.lower()


@test("J1: a fenced controller says so, and says history is preserved")
def _():
    c = console(state_fn=lambda: live(active=False))
    _, _, body = get(c, "/", signed_in(c))
    text = body.decode()
    assert "Fenced" in text
    assert "preserved" in text and "reset" in text


@test("J1: disagreement between Held and the Zodiac allowance is SHOWN, not averaged")
def _():
    drifted = dict(supply=44_000_000_000, normal_withdraw=20_000_000_000,
                   restoration=10_000_000_000, normal_count=97)
    c = console(state_fn=lambda: live(native=drifted))
    _, _, body = get(c, "/", signed_in(c))
    text = body.decode()
    assert "disagree" in text
    assert "refuses to operate" in text
    assert live(native=drifted).drift(), "the drift computation itself found nothing"


# -------------------------------------------------------------------------- J2 --
@test("J2: a limit change is described in plain language before approval")
def _():
    change = prepare_limit_change(live(), {"supply": 8_000_000_000})
    assert change.job is Job.CHANGE_LIMITS
    joined = " ".join(change.lines)
    assert "LOWERED" in joined, joined
    assert "50,000.000000" in joined and "8,000.000000" in joined
    assert "3,000.000000" in joined, "the owner must see what is left, not just the ceiling"


@test("J2: what does NOT change is stated, because that is the real question")
def _():
    change = prepare_limit_change(live(), {"supply": 8_000_000_000})
    unchanged = " ".join(change.unchanged)
    assert "carries forward" in unchanged or "carry forward" in unchanged
    assert "not a reset" in unchanged
    assert "replayed" in unchanged


@test("J2: a ceiling below what is already spent is warned about, not discovered later")
def _():
    change = prepare_limit_change(live(used_supply=5_000_000_000), {"supply": 4_000_000_000})
    warn = " ".join(change.warnings)
    assert "BELOW" in warn and "CeilingBelowConsumption" in warn, warn
    assert "never reset" in warn


@test("J2: the console cannot apply the change, and says who must")
def _():
    change = prepare_limit_change(live(), {"supply": 8_000_000_000})
    assert change.to_record()["executed_by_console"] is False
    steps = " ".join(change.owner_steps)
    assert "Fence" in steps and "Activate" in steps and "NEW epoch" in steps
    assert "allowance" in steps, "re-syncing the native quota must be an explicit step"


@test("J2: an unchanged ceiling produces no noise")
def _():
    change = prepare_limit_change(live(), {"supply": 50_000_000_000})
    assert change.lines == ["No limit changes."]


# -------------------------------------------------------------------------- J3 --
@test("J3: replacing the runner explains that every old signature is retired")
def _():
    change = prepare_runner_replacement(live(), NEW_RUNNER)
    assert change.job is Job.REPLACE_RUNNER
    joined = " ".join(change.lines)
    assert NEW_RUNNER in joined and "epoch advances" in joined
    assert "retires every signature" in joined


@test("J3: in-flight work is called out, and described as knowable rather than lost")
def _():
    change = prepare_runner_replacement(live(), NEW_RUNNER, in_flight=[{"operation_id": "0xaa"}])
    warn = " ".join(change.warnings)
    assert "CANNOT execute" in warn
    assert "guessed" in warn, "the product claim is specifically about not guessing"
    assert "consumed" in warn and "first execution" in warn


@test("J3: replacing a runner with itself is flagged as a no-op")
def _():
    change = prepare_runner_replacement(live(), RUNNER.lower())
    assert any("same as the current one" in w for w in change.warnings)


@test("J3: consumption history is listed as unchanged by a runner swap")
def _():
    change = prepare_runner_replacement(live(), NEW_RUNNER)
    assert any("carries forward" in u for u in change.unchanged)


# -------------------------------------------------------------------------- J4 --
@test("J4: an UNKNOWN operation is read as 'may or may not have executed', not as failure")
def _():
    j = Jrnl([Op("0x" + "aa" * 32, OperationState.UNKNOWN)])
    items = read_interruptions(j)
    assert len(items) == 1
    assert "NOT 'it failed'" in items[0].what_is_known
    assert "consumed[operationId]" in items[0].what_to_do
    assert "Do not resend" in items[0].what_to_do
    assert items[0].resolved is False


@test("J4: every unresolved state gets a reading, and the answer is always the chain")
def _():
    j = Jrnl([Op("0x" + "aa" * 32, OperationState.UNKNOWN),
              Op("0x" + "bb" * 32, OperationState.DISPATCHED),
              Op("0x" + "cc" * 32, OperationState.AUTHORIZED)])
    items = read_interruptions(j)
    assert len(items) == 3
    for i in items:
        assert i.what_is_known and i.what_to_do
    dispatched = [i for i in items if i.state == "DISPATCHED"][0]
    assert "only answer" in dispatched.what_to_do


@test("J4: the page says the executor's status is never the answer")
def _():
    c = console(Jrnl([Op("0x" + "aa" * 32, OperationState.UNKNOWN)]))
    _, _, body = get(c, "/interrupted", signed_in(c))
    text = body.decode()
    assert "consumed[operationId]" in text
    assert "never the executor" in text and "never a retry" in text


@test("J4: nothing unresolved says so plainly rather than showing an empty table")
def _():
    c = console(Jrnl([]))
    _, _, body = get(c, "/interrupted", signed_in(c))
    assert b"Nothing is unresolved" in body


@test("J4: the dashboard surfaces unresolved work before new work is started")
def _():
    c = console(Jrnl([Op("0x" + "aa" * 32, OperationState.UNKNOWN)]))
    _, _, body = get(c, "/", signed_in(c))
    assert b"need resolving" in body


# -------------------------------------------------------------- recovery export --
@test("the recovery export carries what a restart needs, and no secrets")
def _():
    with tempfile.TemporaryDirectory() as d:
        j = Journal(os.path.join(d, "held.sqlite"))
        oid = "0x" + "aa" * 32
        j.create_or_reopen(oid, "0x" + "cc" * 32, "decision-1", 0, 3)
        j.transition(oid, OperationState.AUTHORIZED, epoch=3)
        j.record_attempt_before_send(
            attempt_id="attempt-1", operation_id=oid, envelope_hash="0x" + "dd" * 32,
            epoch=3, runner=RUNNER, signer_ref="env:HELD_RUNNER_KEY")

        c = console(j)
        export = c.export()
        blob = json.dumps(export)

        assert export["schema"] == "held.recovery-export.v1"
        assert len(export["unresolved_operations"]) == 1
        op = export["unresolved_operations"][0]
        assert op["operation_id"] == oid and op["payload_hash"] == "0x" + "cc" * 32
        assert op["attempts"][0]["signer_ref"] == "env:HELD_RUNNER_KEY"
        assert "how_to_resume" in export and len(export["how_to_resume"]) == 4
        # References only. The journal refuses key material, and the export repeats that.
        assert "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6" not in blob
        assert SECRET not in blob, "the console secret reached the export"


@test("the export tells the operator how to resolve each case, including the ambiguous one")
def _():
    with tempfile.TemporaryDirectory() as d:
        j = Journal(os.path.join(d, "held.sqlite"))
        steps = " ".join(console(j).export()["how_to_resume"])
        assert "Never re-execute" in steps
        assert "may still be in flight" in steps and "Do not resend" in steps
        assert "new epoch" in steps


@test("the export is served only to an authenticated session")
def _():
    c = console()
    status, headers, _ = get(c, "/export")
    assert status == 302 and headers["Location"] == "/login"
    status, headers, body = get(c, "/export", signed_in(c))
    assert status == 200 and headers["Content-Type"] == "application/json"
    json.loads(body)


def main() -> int:
    os.environ.pop(SECRET_ENV, None)
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"P05 console: FAIL ({len(FAILED)}/{len(PASSED)+len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} P05 console tests held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
