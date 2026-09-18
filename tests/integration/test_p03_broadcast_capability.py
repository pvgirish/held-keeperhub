"""Does the PRODUCTION broadcast path ask whether the credential may broadcast?

`CredentialCheck.assert_can_broadcast()` was written, documented and tested, and then
called by nothing outside its own tests. `Submitter.submit` created a journal row, minted
an idempotency key, claimed the operation as DISPATCHED and sent -- and only then would a
read-only key have earned a documented 403. Nothing bad had happened, because the key
question had a safe answer. That is not the same as having asked it.

METHOD. The real `Submitter`, over a REAL SQLite journal, with a transport that reports
`hosted=True` so the capability is established the way it would be in production. The
question every test asks is the same one: **what is in the journal, and what left the
process, when the answer is anything other than yes?**

The answer must always be: nothing, and nothing.

  * A refusal must leave the journal byte-identical to how it was found. Not "recoverable",
    not "cleaned up afterwards" -- untouched. An operation row that exists because a send
    was attempted is an operation somebody has to resolve, and resolving it costs a chain
    read at best and an owner ceremony at worst.
  * A refusal must be RETRY-SAFE. The identical call, run again once the credential can
    broadcast, must succeed with no intervening repair. If a refusal needed cleanup it
    would be a worse failure than the 403 it replaced.
  * "No" and "could not ask" must be the same refusal. A caller that had to tell them apart
    before deciding not to spend money would eventually get it wrong.

Nothing here touches the network.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in ("adapter", "packages/core", "tests/integration"):
    sys.path.insert(0, os.path.join(ROOT, p))

from p03_fixtures import (  # noqa: E402
    API_ENV,
    CONTROLLER,
    FAKE_CREDENTIAL,
    MARKET_PARAMS,
    RUNNER,
    RUNNER_KEY,
    Admitted,
    accepted,
    envelope,
    response,
    rig,
)

from held_adapter.execution.keeperhub import (  # noqa: E402
    CONTRACT_CALL_PATH,
    HttpResponse,
    KeeperHubClient,
    KeeperHubError,
    OfflineTransport,
    SendOutcome,
)
from held_adapter.execution.submit import (  # noqa: E402
    AssumedBroadcastCapability,
    BroadcastCapability,
    BroadcastNotPermitted,
    Submitter,
)
from held_adapter.signing.runner_signer import RunnerSigner  # noqa: E402
from held_core.journal import Journal  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def test(name):
    def deco(fn):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                fn(os.path.join(tmp, "j.db"))
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
    except exc_type as exc:
        return str(exc)
    raise AssertionError(f"expected {exc_type.__name__}, nothing was raised")


# ------------------------------------------------------------------- transports --
class Hosted(OfflineTransport):
    """Scripted responses that claim to be hosted.

    Production establishes a capability over `HttpsTransport`. Asserting on a transport
    that reports `hosted=False` would test a path the capability check rejects outright,
    so these tests lie about exactly one thing and nothing else.
    """

    hosted = True


def keys_page(scope: str, *, prefix: str | None = None, total_pages: int = 1) -> HttpResponse:
    """One page of the documented organisation key listing."""
    return response({
        "items": [{"keyPrefix": prefix or FAKE_CREDENTIAL[:12], "scope": scope,
                   "createdByRole": "owner", "expiresAt": None}],
        "meta": {"totalPages": total_pages},
    })


def submitter(path: str, transport, *, capability=None, attempt="attempt-1"):
    os.environ[API_ENV] = FAKE_CREDENTIAL
    os.environ["HELD_RUNNER_KEY"] = RUNNER_KEY
    j = Journal(path)
    c = KeeperHubClient(transport=transport, sleep=lambda _: None)
    s = RunnerSigner("env:HELD_RUNNER_KEY", RUNNER)
    return j, Submitter(j, c, s, CONTROLLER, 8453, MARKET_PARAMS,
                        new_attempt_id=lambda: attempt, capability=capability)


def journal_state(j: Journal) -> dict:
    """Everything a refusal must not have touched."""
    ops = j._db.execute(  # noqa: SLF001 - read-only accessor
        "SELECT operation_id, state, epoch FROM operations ORDER BY operation_id").fetchall()
    att = j._db.execute(  # noqa: SLF001
        "SELECT attempt_id, state, idempotency_key FROM attempts").fetchall()
    return {"operations": [dict(r) for r in ops], "attempts": [dict(r) for r in att]}


def broadcasts(transport) -> list:
    """Requests that were broadcast-shaped, whatever the transport did with them."""
    return [c for c in transport.calls
            if CONTRACT_CALL_PATH in c["url"] and not (c["body"] or {}).get("simulate")]


# ========================================================= the scope decides it --
@test("a read-only key refuses the production broadcast path")
def _(path):
    t = Hosted([keys_page("mcp:read")])
    j, sub = submitter(path, t)
    msg = expect(BroadcastNotPermitted, sub.submit, Admitted(), envelope())
    assert "mcp:read" in msg, msg
    assert "mcp:write" in msg and "mcp:admin" in msg, (
        "the refusal must say what scope WOULD work", msg)
    assert broadcasts(t) == [], "a broadcast left the process on a read-only key"


@test("a write key passes the capability gate and broadcasts")
def _(path):
    t = Hosted([keys_page("mcp:read,mcp:write"), accepted("exec-w")])
    j, sub = submitter(path, t)
    s = sub.submit(Admitted(), envelope())
    assert s.send.outcome is SendOutcome.ACCEPTED, s.send
    assert len(broadcasts(t)) == 1, broadcasts(t)


@test("an admin key passes the capability gate and broadcasts")
def _(path):
    t = Hosted([keys_page("mcp:read,mcp:admin"), accepted("exec-a")])
    j, sub = submitter(path, t)
    s = sub.submit(Admitted(), envelope())
    assert s.send.outcome is SendOutcome.ACCEPTED, s.send
    assert len(broadcasts(t)) == 1, broadcasts(t)


@test("scope order and spacing do not decide a broadcast")
def _(path):
    for scope in ("mcp:admin", " mcp:write , mcp:read ", "mcp:write mcp:read",
                  "mcp:read,mcp:write,mcp:admin"):
        with tempfile.TemporaryDirectory() as tmp:
            t = Hosted([keys_page(scope), accepted("exec-x")])
            _, sub = submitter(os.path.join(tmp, "j.db"), t)
            assert sub.submit(Admitted(), envelope()).send.outcome is SendOutcome.ACCEPTED, scope


@test("a scope that merely CONTAINS the word write does not pass")
def _(path):
    for scope in ("mcp:readwrite", "mcp:write-pending", "write", "mcp:writeish"):
        with tempfile.TemporaryDirectory() as tmp:
            t = Hosted([keys_page(scope)])
            _, sub = submitter(os.path.join(tmp, "j.db"), t)
            expect(BroadcastNotPermitted, sub.submit, Admitted(), envelope())
            assert broadcasts(t) == [], scope


# ================================================ cannot verify => cannot broadcast --
@test("an unset credential fails closed")
def _(path):
    t = Hosted([keys_page("mcp:write")])
    j, sub = submitter(path, t)
    os.environ.pop(API_ENV, None)
    try:
        msg = expect(BroadcastNotPermitted, sub.submit, Admitted(), envelope())
    finally:
        os.environ[API_ENV] = FAKE_CREDENTIAL
    assert "L10" in msg or "unset" in msg, msg
    assert t.calls == [], "no request should be built for an unresolvable credential"


@test("a network failure during the capability check fails closed")
def _(path):
    t = Hosted([ConnectionError("connection reset by peer")] * 4)
    j, sub = submitter(path, t)
    msg = expect(BroadcastNotPermitted, sub.submit, Admitted(), envelope())
    assert "could not be reached" in msg, msg
    assert "could not be established" in msg, msg
    assert broadcasts(t) == []


@test("401 and 403 on the listing fail closed")
def _(path):
    for status in (401, 403, 500):
        with tempfile.TemporaryDirectory() as tmp:
            t = Hosted([response({"error": "no"}, status)] * 6)
            _, sub = submitter(os.path.join(tmp, "j.db"), t)
            expect(BroadcastNotPermitted, sub.submit, Admitted(), envelope())
            assert broadcasts(t) == [], status


@test("an unrecognisable listing fails closed rather than being read optimistically")
def _(path):
    for body in ({"keys": [{"scope": "mcp:write"}]}, {"items": "everything"}, {}):
        with tempfile.TemporaryDirectory() as tmp:
            t = Hosted([response(body)])
            _, sub = submitter(os.path.join(tmp, "j.db"), t)
            expect(BroadcastNotPermitted, sub.submit, Admitted(), envelope())


@test("a credential absent from the organisation's own listing fails closed")
def _(path):
    # Authenticated enough to read the listing, but not in it. A contradiction, and
    # certainly not a licence to spend.
    t = Hosted([keys_page("mcp:write", prefix="kh_some_other_key_")])
    j, sub = submitter(path, t)
    msg = expect(BroadcastNotPermitted, sub.submit, Admitted(), envelope())
    assert "not established as valid" in msg or "not among" in msg, msg


@test("a non-hosted answer cannot establish a capability")
def _(path):
    # Identical bytes, identical scopes -- the only difference is a transport that cannot
    # be shown to have spoken to KeeperHub. OfflineTransport can be handed any response.
    t = OfflineTransport([keys_page("mcp:read,mcp:write"), accepted("exec-n")])
    j, sub = submitter(path, t)
    msg = expect(BroadcastNotPermitted, sub.submit, Admitted(), envelope())
    assert "non-hosted" in msg, msg
    assert broadcasts(t) == []


# ====================================================== the default is fail-closed --
@test("the DEFAULT submitter verifies: no capability argument is not a bypass")
def _(path):
    j, t, sub = rig([accepted()], path=path, use_default_capability=True)
    assert isinstance(sub.capability, BroadcastCapability), sub.capability
    # The offline fixture transport has no key listing scripted, so the check fails and
    # the submission refuses. That is the whole point: forgetting to configure the
    # capability refuses, it does not send.
    expect(BroadcastNotPermitted, sub.submit, Admitted(), envelope())
    assert broadcasts(t) == []


@test("an assumed capability is refused against the real hosted route")
def _(path):
    os.environ[API_ENV] = FAKE_CREDENTIAL
    c = KeeperHubClient(transport=Hosted([]), sleep=lambda _: None)
    msg = expect(
        BroadcastNotPermitted, Submitter,
        Journal(path), c, RunnerSigner("env:HELD_RUNNER_KEY", RUNNER),
        CONTROLLER, 8453, MARKET_PARAMS,
        capability=AssumedBroadcastCapability("a fork rehearsal, allegedly"))
    assert "ASSUMED" in msg and "never declared by the caller" in msg, msg


@test("an assumed capability must state a reason")
def _(path):
    for bad in ("", None, 0):
        expect(BroadcastNotPermitted, AssumedBroadcastCapability, bad)


# ==================================================== the journal is left untouched --
@test("a refusal leaves the journal byte-identical to how it was found")
def _(path):
    t = Hosted([keys_page("mcp:read")])
    j, sub = submitter(path, t)
    before = journal_state(j)
    assert before == {"operations": [], "attempts": []}, before
    expect(BroadcastNotPermitted, sub.submit, Admitted(), envelope())
    assert journal_state(j) == before, (
        "the refusal created journal state. An operation row that exists because a send "
        "was attempted is an operation somebody has to resolve")


@test("a refusal mints no idempotency key and claims no attempt")
def _(path):
    t = Hosted([response({"error": "no"}, 403)] * 6)
    j, sub = submitter(path, t)
    expect(BroadcastNotPermitted, sub.submit, Admitted(), envelope())
    assert journal_state(j)["attempts"] == []


@test("a refusal is RETRY-SAFE: the identical call succeeds once the key can broadcast")
def _(path):
    t = Hosted([keys_page("mcp:read")])
    j, sub = submitter(path, t)
    expect(BroadcastNotPermitted, sub.submit, Admitted(), envelope())

    # Same journal file, same operation, same envelope, same attempt id. No repair step,
    # no reconciliation, no fencing -- the refusal cost nothing to undo because it changed
    # nothing.
    t2 = Hosted([keys_page("mcp:write"), accepted("exec-retry")])
    _, sub2 = submitter(path, t2)
    s = sub2.submit(Admitted(), envelope())
    assert s.send.outcome is SendOutcome.ACCEPTED, s.send
    assert len(journal_state(j)["attempts"]) == 1, journal_state(j)


@test("repeated refusals do not accumulate state")
def _(path):
    for _ in range(4):
        t = Hosted([keys_page("mcp:read")])
        j, sub = submitter(path, t)
        expect(BroadcastNotPermitted, sub.submit, Admitted(), envelope())
    assert journal_state(j) == {"operations": [], "attempts": []}


# ================================================================== ordering holds --
@test("the capability is required BEFORE the first journal write, not merely before send")
def _(path):
    # If the check ran later, `create_or_reopen` would have written an operation row and
    # this would see one. The ordering is the property, so it is asserted directly.
    t = Hosted([keys_page("mcp:read")])
    j, sub = submitter(path, t)
    seen = {}
    real = j.create_or_reopen

    def spy(*a, **k):
        seen["created"] = True
        return real(*a, **k)

    j.create_or_reopen = spy
    expect(BroadcastNotPermitted, sub.submit, Admitted(), envelope())
    assert "created" not in seen, "the journal was mutated before the capability was known"


@test("no broadcast-shaped request leaves before the check passes")
def _(path):
    t = Hosted([keys_page("mcp:read")])
    j, sub = submitter(path, t)
    expect(BroadcastNotPermitted, sub.submit, Admitted(), envelope())
    # The ONLY thing that left was the GET that asked the question.
    assert len(t.calls) == 1, t.calls
    assert t.calls[0]["method"] == "GET", t.calls[0]
    assert "/api/keys" in t.calls[0]["url"], t.calls[0]


@test("the capability is verified once and cached only on success")
def _(path):
    t = Hosted([keys_page("mcp:write"), accepted("e1"), accepted("e2")])
    j, sub = submitter(path, t, attempt="a1")
    sub.submit(Admitted(), envelope())
    listings = [c for c in t.calls if "/api/keys" in c["url"]]
    assert len(listings) == 1, listings
    sub.capability.require()          # already verified: asks nothing further
    assert len([c for c in t.calls if "/api/keys" in c["url"]]) == 1


@test("a failed capability check is NOT cached as a refusal")
def _(path):
    t = Hosted([ConnectionError("reset")] * 4 + [keys_page("mcp:write")])
    j, sub = submitter(path, t)
    expect(BroadcastNotPermitted, sub.capability.require)
    # A transient fault must not become a sticky no. Asking again asks again.
    sub.capability.require()
    assert sub.capability._verified is True  # noqa: SLF001


# ============================================================ resume is gated too --
@test("resume refuses to resend on a read-only key")
def _(path):
    # Build a real unresolved attempt with a capable key, then resume with a read-only one.
    t = Hosted([keys_page("mcp:write"), HttpResponse(500, b"{}", {})] * 1
               + [HttpResponse(500, b"{}", {})] * 5)
    j, sub = submitter(path, t, attempt="resume-attempt")
    s = sub.submit(Admitted(), envelope())
    assert s.send.outcome is SendOutcome.UNKNOWN, s.send

    t2 = Hosted([keys_page("mcp:read")])
    _, sub2 = submitter(path, t2, attempt="resume-attempt")
    msg = expect(BroadcastNotPermitted, sub2.resume, s.operation_id)
    assert "mcp:read" in msg, msg
    assert broadcasts(t2) == [], "resume broadcast on a read-only key"


@test("reconciliation still works on a read-only key")
def _(path):
    # Everything above the send in resume() is reconciliation, and a read-only credential
    # must not be prevented from resolving an operation it can no longer send. Gating
    # resume() at its top would have taken that away.
    from p03_fixtures import PAYLOAD_HEX, Chain

    t = Hosted([keys_page("mcp:write")] + [HttpResponse(500, b"{}", {})] * 6)
    j, sub = submitter(path, t, attempt="rec-attempt")
    s = sub.submit(Admitted(), envelope())
    assert s.send.outcome is SendOutcome.UNKNOWN, s.send

    t2 = Hosted([keys_page("mcp:read")])
    _, sub2 = submitter(path, t2, attempt="rec-attempt")
    chain = Chain(marker=PAYLOAD_HEX, controller_epoch=1)
    state = sub2.reconcile(s.operation_id, PAYLOAD_HEX, chain)
    assert state is not None, "a read-only key could not reconcile"
    assert [c for c in t2.calls if "/api/keys" in c["url"]] == [], (
        "reconciliation asked about broadcast scope; it never broadcasts")


def main() -> int:
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"P03 broadcast capability: FAIL ({len(FAILED)}/{len(PASSED) + len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} production broadcast-capability tests held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
