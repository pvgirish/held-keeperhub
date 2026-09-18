"""The private operator console: an authenticated, local, read-and-prepare surface.

Stdlib only, server-rendered HTML. No framework, no build step, no package manager. The
console is a security surface over a customer's funds, so its whole dependency tree
should be readable in an afternoon.

## Private means private

  * Binds to 127.0.0.1. Binding anywhere else requires `allow_public_bind=True` and logs
    a warning, because a console reachable from the network is a different product with a
    different threat model.
  * Every route except the login form requires a session cookie derived from a shared
    secret held by REFERENCE (`env:NAME`), compared with `hmac.compare_digest`.
  * State-changing forms carry a CSRF token bound to the session.
  * Every value interpolated into HTML is escaped. There is no template engine to get
    this wrong in an unfamiliar way.

## It holds no keys and broadcasts nothing

The console cannot fence, activate, sign or send. Those are owner and runner authorities,
and a console that held them would be a fourth authority over customer funds that the P04
inventory does not contain. What it does is READ state and PREPARE a described owner
action, which the owner then executes in their own Safe.

This is also what makes owner approval understandable: the owner approves "the supply
ceiling drops from 50,000 to 8,000 USDC, 5,000 is already spent, so 3,000 remains, and
nothing else changes" -- not a calldata blob.

## Recovery export

`/export` emits the durable state needed to resume elsewhere: operations, attempts and
tombstones. It is scrubbed through the journal's own secret guard, and it carries signer
REFERENCES, never key material.
"""
from __future__ import annotations

import hmac
import html
import json
import os
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlparse

from .state import (
    Interruption,
    Job,
    LiveState,
    PreparedChange,
    duration,
    prepare_limit_change,
    prepare_runner_replacement,
    read_interruptions,
    usdc,
)

SESSION_COOKIE = "held_console_session"
SESSION_TTL_SECONDS = 3600


class ConsoleError(Exception):
    pass


class ConsoleNotPrivate(ConsoleError):
    """Refused a configuration that would expose the console."""


def _secret_from_reference(ref: str) -> str:
    """Resolve the console secret from an env:NAME reference. Never a literal."""
    if not isinstance(ref, str) or not ref.startswith("env:"):
        raise ConsoleError(
            f"console secret must be an 'env:NAME' reference; got {ref!r}. A literal "
            "secret in a config file is the thing this indirection exists to prevent."
        )
    name = ref.split(":", 1)[1]
    value = os.environ.get(name)
    if not value:
        raise ConsoleError(f"${name} is unset, so the console has no way to authenticate")
    if len(value) < 16:
        raise ConsoleError(
            f"${name} is shorter than 16 characters. This is the only thing standing "
            "between a local process and the operator console."
        )
    return value


class Sessions:
    """In-memory sessions. Deliberately not persisted: a restart logs everyone out."""

    def __init__(self, ttl: int = SESSION_TTL_SECONDS, now: Callable[[], float] = time.time) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._ttl = ttl
        self._now = now

    def create(self) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = {"created": self._now(), "csrf": secrets.token_urlsafe(24)}
        return token

    def get(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        s = self._sessions.get(token)
        if s is None:
            return None
        if self._now() - s["created"] > self._ttl:
            del self._sessions[token]
            return None
        return s

    def check_csrf(self, token: str | None, csrf: str | None) -> bool:
        s = self.get(token)
        if s is None or not csrf:
            return False
        return hmac.compare_digest(s["csrf"], csrf)


# ------------------------------------------------------------------------ HTML --

def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


_STYLE = """
body{font:15px/1.5 system-ui,sans-serif;margin:0;background:#12141a;color:#e6e8ee}
main{max-width:920px;margin:0 auto;padding:24px}
h1{font-size:20px;margin:0 0 4px} h2{font-size:16px;margin:28px 0 8px}
.bar{background:#1b1f2a;padding:12px 16px;border-bottom:1px solid #2a3040}
.card{background:#1b1f2a;border:1px solid #2a3040;border-radius:8px;padding:16px;margin:12px 0}
.fenced{border-color:#8a6d1f;background:#241f14}
.warn{border-color:#8a2f2f;background:#241616}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #2a3040}
th{color:#9aa3b8;font-weight:600;font-size:13px}
.right{text-align:right} code{background:#0e1016;padding:1px 5px;border-radius:4px;font-size:13px}
.muted{color:#9aa3b8} .never{color:#ff9d9d}
input,button{font:inherit;padding:7px 10px;border-radius:6px;border:1px solid #2a3040;
  background:#0e1016;color:#e6e8ee}
button{background:#2b3burn;cursor:pointer}
ul{margin:6px 0;padding-left:20px} li{margin:3px 0}
/* The default link colour failed against this background badly enough that the
   operator-action links were close to invisible. Found by looking at the rendered
   page, not by reading the CSS. */
a{color:#8ab4ff} a:visited{color:#b9a4ff} a:hover{color:#cfe0ff}
button:hover{background:#3a4770}
input:focus,button:focus{outline:2px solid #8ab4ff;outline-offset:1px}
""".replace("#2b3burn", "#2b3350")


def page(title: str, body: str, *, banner: str = "") -> bytes:
    return (
        "<!doctype html><meta charset=utf-8>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{esc(title)} — Held</title><style>{_STYLE}</style>"
        f"<div class=bar><strong>Held</strong> <span class=muted>operator console — "
        f"private, read &amp; prepare only</span></div>"
        f"<main>{banner}{body}</main>"
    ).encode()


def _budget_table(state: LiveState) -> str:
    rows = "".join(
        "<tr><td>{name}</td><td class=right>{used}</td><td class=right>{ceiling}</td>"
        "<td class=right>{remaining}</td><td class=muted>{unit}</td></tr>".format(
            **{k: esc(v) for k, v in b.render().items()}
        )
        for b in state.budgets
    )
    return (
        "<table><tr><th>Budget</th><th class=right>Used</th><th class=right>Ceiling</th>"
        f"<th class=right>Remaining</th><th>Unit</th></tr>{rows}</table>"
    )


def render_dashboard(state: LiveState, interruptions: list[Interruption]) -> str:
    """J1: run the strategy under customer-approved limits."""
    banner = ""
    if not state.active:
        banner = (
            "<div class='card fenced'><strong>Fenced.</strong> The runner cannot execute. "
            "Consumption history is preserved and nothing has been reset.</div>"
        )
    drift = state.drift()
    if drift:
        banner += (
            "<div class='card warn'><strong>Held and the Zodiac allowances disagree.</strong>"
            "<ul>" + "".join(f"<li>{esc(d)}</li>" for d in drift) + "</ul>"
            "The controller refuses to operate until they agree. This is shown, not "
            "reconciled away.</div>"
        )
    unresolved = [i for i in interruptions if not i.resolved]
    if unresolved:
        banner += (
            f"<div class='card warn'><strong>{len(unresolved)} operation(s) need "
            "resolving</strong> before new work should start. See "
            "<a href='/interrupted'>interrupted operations</a>.</div>"
        )

    cooldowns = "".join(
        f"<li>{esc(k)}: {esc(duration(v))}</li>" for k, v in state.cooldowns.items()
    )
    return banner + (
        f"<h1>{esc(state.status_line)}</h1>"
        f"<p class=muted>Controller <code>{esc(state.controller)}</code> · "
        f"Safe <code>{esc(state.safe)}</code></p>"
        "<h2>Customer-approved limits</h2>"
        f"{_budget_table(state)}"
        f"<h2>Cooldowns</h2><ul>{cooldowns}</ul>"
        "<h2>Authorities</h2><ul>"
        f"<li>Runner (authorizes by signature): <code>{esc(state.runner)}</code></li>"
        f"<li>Executor (may call, cannot authorize): <code>{esc(state.executor)}</code></li>"
        f"<li>Owner (may fence and activate): the Safe, <code>{esc(state.safe)}</code></li>"
        "<li class=never>This console: none. It holds no keys and broadcasts nothing.</li>"
        "</ul>"
        "<h2>Operator actions</h2><ul>"
        "<li><a href='/limits'>Change limits</a> — prepares an owner action</li>"
        "<li><a href='/runner'>Replace the runner</a> — prepares an owner action</li>"
        "<li><a href='/interrupted'>Resolve an interrupted operation</a></li>"
        "<li><a href='/export'>Recovery export</a> — durable state, no secrets</li>"
        "</ul>"
    )


def _render_views(views: dict) -> str:
    """The four V4 section 8 views, each carrying its own truthfulness.

    A view that could not be built renders as a stated failure, not as a blank panel and
    never as demonstration numbers. The evidence grade is shown on every one, because a
    figure without its grade invites exactly the promotion this project refuses.
    """
    order = (("terms", "Terms"), ("activity", "Activity"),
             ("unresolved", "Unresolved / recovery"), ("authority", "Authority &amp; handover"))
    out = ["<h1>Operator views</h1>"]
    for key, title in order:
        v = views.get(key)
        if v is None:
            continue
        if not v.loaded:
            out.append(
                f"<section><h2>{title}</h2>"
                f"<p class=b>UNAVAILABLE — {esc(v.summary)}</p>"
                + "".join(f"<p class=b>{esc(p)}</p>" for p in v.problems)
                + "<p><small>No substitute data is shown. Fix the source.</small></p>"
                "</section>")
            continue
        rows = "".join(
            "<tr>" + "".join(f"<td>{esc(val)}</td>" for val in r.values()) + "</tr>"
            for r in v.rows)
        head = ("<tr>" + "".join(f"<th>{esc(k)}</th>" for k in v.rows[0]) + "</tr>"
                if v.rows else "")
        problems = "".join(f"<li>{esc(p)}</li>" for p in v.problems)
        out.append(
            f"<section><h2>{title}</h2>"
            f"<p><strong>evidence grade:</strong> {esc(v.grade)}</p>"
            f"<p>{esc(v.summary)}</p>"
            + (f"<table>{head}{rows}</table>" if v.rows else "<p><em>nothing to show</em></p>")
            + (f"<ul class=b>{problems}</ul>" if problems else "")
            + "</section>")
    return "".join(out)


def render_prepared(change: PreparedChange, csrf: str, back: str) -> str:
    def ul(items, cls=""):
        return f"<ul class='{cls}'>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"

    warn = ""
    if change.warnings:
        warn = f"<div class='card warn'><strong>Before you approve</strong>{ul(change.warnings)}</div>"
    return (
        f"<h1>{esc(change.title)}</h1>"
        f"{warn}"
        f"<div class=card><h2>What changes</h2>{ul(change.lines)}"
        f"<h2>What does NOT change</h2>{ul(change.unchanged)}</div>"
        f"<div class=card><h2>How to apply it</h2>"
        "<p class=muted>The console cannot perform any of these. They are owner actions on "
        "the Safe, and you execute them there.</p>"
        f"{ul(change.owner_steps)}</div>"
        f"<p><a href='{esc(back)}'>Back</a> · "
        f"<a href='/prepared.json?csrf={esc(csrf)}'>Download this description</a></p>"
    )


def render_interruptions(items: list[Interruption]) -> str:
    """J4: resolve an interrupted operation without guessing what it did."""
    if not items:
        return (
            "<h1>Interrupted operations</h1>"
            "<div class=card>Nothing is unresolved. Every operation is either confirmed "
            "on chain or definitively not executed.</div>"
        )
    rows = "".join(
        "<tr><td><code>{oid}</code></td><td>{state}</td><td class=right>{epoch}</td>"
        "<td class=right>{attempts}</td><td>{known}<br><span class=muted>{todo}</span></td></tr>".format(
            oid=esc(i.operation_id[:18] + "…"), state=esc(i.state), epoch=esc(i.epoch),
            attempts=esc(i.attempts), known=esc(i.what_is_known), todo=esc(i.what_to_do),
        )
        for i in items
    )
    return (
        "<h1>Interrupted operations</h1>"
        "<p class=muted>An unknown outcome is not a failure. The answer is always "
        "<code>consumed[operationId]</code> on the controller — never the executor's "
        "status, and never a retry.</p>"
        "<table><tr><th>Operation</th><th>State</th><th class=right>Epoch</th>"
        f"<th class=right>Attempts</th><th>Reading</th></tr>{rows}</table>"
    )


# ----------------------------------------------------------------------- server --

class Console:
    """Routing and policy. Kept out of the handler so it can be tested without sockets."""

    def __init__(
        self,
        state_provider: Callable[[], LiveState],
        journal,
        *,
        secret_ref: str = "env:HELD_CONSOLE_SECRET",
        sessions: Sessions | None = None,
    ) -> None:
        self._state = state_provider
        self._journal = journal
        self._secret = _secret_from_reference(secret_ref)
        self.sessions = sessions or Sessions()
        self._last_prepared: PreparedChange | None = None
        # Set by run.py in live mode: a callable returning the four V4 section 8 views
        # assembled from REAL sources. Absent in demo mode, where the banner says so.
        self.views: Callable[[], dict] | None = None

    # ---- auth
    def login(self, password: str) -> str | None:
        # compare_digest, not ==, so a wrong secret cannot be recovered by timing.
        if hmac.compare_digest(password or "", self._secret):
            return self.sessions.create()
        return None

    def handle(self, method: str, path: str, query: Mapping[str, list[str]],
               form: Mapping[str, list[str]], cookie: str | None) -> tuple[int, dict, bytes]:
        session = self.sessions.get(cookie)

        if path == "/login":
            if method == "POST":
                token = self.login((form.get("password") or [""])[0])
                if token:
                    return (302, {"Location": "/",
                                  "Set-Cookie": f"{SESSION_COOKIE}={token}; HttpOnly; "
                                                f"SameSite=Strict; Path=/"}, b"")
                return 401, {}, page("Sign in", _login_form("Incorrect."))
            return 200, {}, page("Sign in", _login_form())

        if session is None:
            # Everything else is private. No read-only peek, no partial render.
            return 302, {"Location": "/login"}, b""

        csrf = session["csrf"]

        if path == "/":
            return 200, {}, page(
                "Console",
                render_dashboard(self._state(), read_interruptions(self._journal)),
            )

        if path == "/interrupted":
            return 200, {}, page(
                "Interrupted", render_interruptions(read_interruptions(self._journal)))

        if path == "/limits":
            if method == "POST":
                if not self.sessions.check_csrf(cookie, (form.get("csrf") or [None])[0]):
                    return 403, {}, page("Refused", "<h1>CSRF token missing or wrong</h1>")
                new = {}
                for k, v in form.items():
                    if k.startswith("ceiling_") and v and v[0].strip():
                        new[k[len("ceiling_"):]] = int(v[0])
                self._last_prepared = prepare_limit_change(self._state(), new)
                return 200, {}, page("Prepared",
                                     render_prepared(self._last_prepared, csrf, "/limits"))
            return 200, {}, page("Change limits", _limits_form(self._state(), csrf))

        if path == "/runner":
            if method == "POST":
                if not self.sessions.check_csrf(cookie, (form.get("csrf") or [None])[0]):
                    return 403, {}, page("Refused", "<h1>CSRF token missing or wrong</h1>")
                new_runner = (form.get("runner") or [""])[0].strip()
                in_flight = [i.to_record() for i in read_interruptions(self._journal)
                             if not i.resolved]
                self._last_prepared = prepare_runner_replacement(
                    self._state(), new_runner, in_flight)
                return 200, {}, page("Prepared",
                                     render_prepared(self._last_prepared, csrf, "/runner"))
            return 200, {}, page("Replace runner", _runner_form(self._state(), csrf))

        if path == "/views":
            if self.views is None:
                return 200, {}, page(
                    "Operator views",
                    "<p class=b>DEMONSTRATION STATE — no live sources are configured, so "
                    "the four operator views are not available. Start the console with "
                    "<code>--state-source live</code>.</p>")
            return 200, {}, page("Operator views", _render_views(self.views()))

        if path == "/views.json":
            if self.views is None:
                return 404, {"Content-Type": "application/json"}, b'{"error":"demo mode"}'
            body = json.dumps({k: v.to_dict() for k, v in self.views().items()},
                              indent=2).encode()
            return 200, {"Content-Type": "application/json"}, body

        if path == "/prepared.json":
            if self._last_prepared is None:
                return 404, {}, b"{}"
            body = json.dumps(self._last_prepared.to_record(), indent=1).encode()
            return 200, {"Content-Type": "application/json"}, body

        if path == "/export":
            body = json.dumps(self.export(), indent=1).encode()
            return (200, {"Content-Type": "application/json",
                          "Content-Disposition": "attachment; filename=held-recovery.json"}, body)

        return 404, {}, page("Not found", "<h1>Not found</h1>")

    # ---- recovery export
    def export(self) -> dict[str, Any]:
        """Durable state needed to resume elsewhere. References only, never material."""
        ops = []
        for op in self._journal.unresolved():
            ops.append({
                "operation_id": op.operation_id,
                "payload_hash": op.payload_hash,
                "state": op.state.value,
                "epoch": op.epoch,
                "source_decision_id": op.source_decision_id,
                "action_index": op.action_index,
                "attempts": [
                    {k: v for k, v in a.items() if k != "id"}
                    for a in self._journal.attempts_for(op.operation_id)
                ],
            })
        return {
            "schema": "held.recovery-export.v1",
            "note": (
                "Signer and credential fields are REFERENCES (env:NAME, keystore:path). "
                "No key material, no API credential and no passphrase is present, and the "
                "journal refuses to store any."
            ),
            "unresolved_operations": ops,
            "how_to_resume": [
                "For each operation, read consumed[operationId] on the controller.",
                "Equal to payload_hash: it executed. Never re-execute it.",
                "Zero AND the send was definitively refused: it did not execute; the same "
                "id and payload may be reauthorized under a new epoch.",
                "Zero and the send was ambiguous: it may still be in flight. Re-read. Do "
                "not resend.",
            ],
        }


def _login_form(error: str = "") -> str:
    err = f"<div class='card warn'>{esc(error)}</div>" if error else ""
    return (
        f"<h1>Sign in</h1>{err}"
        "<form method=post action=/login class=card>"
        "<input type=password name=password autofocus placeholder='Console secret'> "
        "<button type=submit>Sign in</button></form>"
        "<p class=muted>The console is private and binds to localhost. It holds no keys "
        "and cannot move funds.</p>"
    )


def _limits_form(state: LiveState, csrf: str) -> str:
    fields = "".join(
        f"<tr><td>{esc(b.name)}</td><td class=muted>{esc(b.render()['ceiling'])} "
        f"({esc(b.unit)})</td><td><input name='ceiling_{esc(b.name)}' "
        f"placeholder='base units' inputmode=numeric></td></tr>"
        for b in state.budgets
    )
    return (
        "<h1>Change customer-approved limits</h1>"
        "<p class=muted>Enter new ceilings in base units. You will see a plain-language "
        "description before anything is approved, and the console cannot apply it.</p>"
        f"<form method=post action=/limits class=card>"
        f"<input type=hidden name=csrf value='{esc(csrf)}'>"
        "<table><tr><th>Budget</th><th>Current</th><th>New ceiling</th></tr>"
        f"{fields}</table><p><button type=submit>Describe this change</button></p></form>"
        "<p><a href='/'>Back</a></p>"
    )


def _runner_form(state: LiveState, csrf: str) -> str:
    return (
        "<h1>Replace the runner</h1>"
        f"<p class=muted>Current runner <code>{esc(state.runner)}</code>.</p>"
        f"<form method=post action=/runner class=card>"
        f"<input type=hidden name=csrf value='{esc(csrf)}'>"
        "<input name=runner placeholder='0x… new runner address' size=46> "
        "<button type=submit>Describe this change</button></form>"
        "<p><a href='/'>Back</a></p>"
    )


def make_handler(console: Console):
    class Handler(BaseHTTPRequestHandler):
        server_version = "held-console"

        def _dispatch(self, method: str) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            form: dict[str, list[str]] = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            cookie = None
            raw = self.headers.get("Cookie") or ""
            for part in raw.split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    if k == SESSION_COOKIE:
                        cookie = v
            status, headers, body = console.handle(
                method, parsed.path, query, form, cookie)
            self.send_response(status)
            self.send_header("Content-Type", headers.pop("Content-Type", "text/html; charset=utf-8"))
            self.send_header("Content-Length", str(len(body)))
            # A console over customer funds should not be framed, sniffed or referred out.
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            self._dispatch("GET")

        def do_POST(self):  # noqa: N802
            self._dispatch("POST")

        def log_message(self, fmt, *args):
            # The default logs the full request line. Query strings can carry a CSRF
            # token, so paths are logged without them.
            path = urlparse(self.path).path
            print(f"held-console {self.command} {path}")

    return Handler


def serve(console: Console, host: str = "127.0.0.1", port: int = 8799,
          *, allow_public_bind: bool = False) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost", "::1") and not allow_public_bind:
        raise ConsoleNotPrivate(
            f"refusing to bind the operator console to {host}. A console reachable from "
            "the network is a different product with a different threat model. Pass "
            "allow_public_bind=True only with authentication and transport you have "
            "actually reviewed."
        )
    return ThreadingHTTPServer((host, port), make_handler(console))
