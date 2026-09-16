"""P03-C1: the KeeperHub client against the DOCUMENTED wire contract.

SCOPE, stated plainly because this is the easiest place in the project to overclaim:
these tests establish that Held builds the documented request, sets the documented
headers, polls the documented path, and reads the documented answers -- including the
ones where the outcome is genuinely unknown. They run against `OfflineTransport`, which
stamps `hosted=False` on everything.

They do NOT establish L10. Nothing here shows that the authenticated KeeperHub
organisation caller/payer accepts Held's call, and they are not evidence that the
documented schema matches the live handler. They are evidence that Held implements the
published contract. Three tests exist specifically to prove a local result cannot be
filed as if it were more.

Contract source: https://docs.keeperhub.com/api/direct-execution, reread 2026-09-16.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "packages", "core"))
sys.path.insert(0, os.path.join(ROOT, "adapter"))
sys.path.insert(0, HERE)

from held_adapter.execution.controller_abi import (  # noqa: E402
    ControllerAbiError,
    encode_call,
    function_abi,
)
from held_adapter.execution.keeperhub import (  # noqa: E402
    CODE_IDEMPOTENCY_CONFLICT,
    CODE_IDEMPOTENCY_IN_PROGRESS,
    IDEMPOTENCY_HEADER,
    POLL_HINT_HEADER,
    BackoffPolicy,
    ContractCallRequest,
    CredentialError,
    CredentialReference,
    HttpResponse,
    HttpsTransport,
    KeeperHubClient,
    KeeperHubError,
    L10Blocked,
    OfflineTransport,
    SendOutcome,
    execution_key,
)
from held_core.journal import assert_no_secrets  # noqa: E402

from p03_fixtures import (  # noqa: E402
    API_ENV, CHAIN_ID, CONTROLLER, FAKE_CREDENTIAL, MARKET_PARAMS, OP_HEX, RUNNER, SAFE,
    accepted, response,
)

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


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


ENV_ARG = (
    bytes(32), bytes(32), bytes(32), 1, SAFE.lower(), bytes(32), 1, 1, RUNNER.lower(),
)


def request(simulate: bool = False) -> ContractCallRequest:
    args = [ENV_ARG, MARKET_PARAMS, 100_000_000, bytes(65)]
    return ContractCallRequest(
        chain_id=CHAIN_ID, contract_address=CONTROLLER, function_name="executeSupply",
        function_args=args, abi=function_abi("executeSupply"),
        expected_calldata=encode_call("executeSupply", args), simulate=simulate)


KEY = execution_key(OP_HEX, "attempt-1")


def client(responses, **kw):
    os.environ[API_ENV] = FAKE_CREDENTIAL
    t = OfflineTransport(responses)
    slept: list[float] = []
    c = KeeperHubClient(transport=t, sleep=slept.append, **kw)
    c._slept = slept
    return c, t


# ------------------------------------------------- C1: the documented request --
@test("C1: the body uses contractAddress/functionName/functionArgs/abi, not to/data")
def _():
    c, t = client([accepted()])
    c.broadcast(request(), KEY)
    body = t.calls[0]["body"]
    assert body["contractAddress"] == CONTROLLER.lower()
    assert body["chainId"] == CHAIN_ID
    assert body["functionName"] == "executeSupply"
    assert body["value"] == "0"
    assert body["simulate"] is False
    # Documented as JSON STRINGS, not nested JSON objects.
    assert isinstance(body["functionArgs"], str), "functionArgs must be a JSON string"
    assert isinstance(body["abi"], str), "abi must be a JSON string"
    json.loads(body["functionArgs"]); json.loads(body["abi"])
    # The invented raw-call aliases must be gone.
    assert "to" not in body and "data" not in body, body
    assert "idempotencyKey" not in body, "idempotency is a HEADER, never a body field"


@test("C1: the idempotency key travels in the Idempotency-Key HEADER")
def _():
    c, t = client([accepted()])
    c.broadcast(request(), KEY)
    assert t.calls[0]["headers"][IDEMPOTENCY_HEADER] == KEY
    # The whole point of the repair: retrying without this header is unprotected.
    assert "broadcast requires an Idempotency-Key" in expect(
        KeeperHubError, c.broadcast, request(), "")


@test("C1: polling uses /api/execute/{id}/status and reads the poll hint")
def _():
    c, t = client([response({"executionId": "exec-7"}, 200, {POLL_HINT_HEADER: "0"})])
    r = c.poll("exec-7")
    assert t.calls[0]["url"].endswith("/api/execute/exec-7/status"), t.calls[0]["url"]
    assert t.calls[0]["method"] == "GET"
    assert r.poll_hint_seconds == 0 and r.terminal, "a hint of 0 means terminal"
    assert "execution_id is required" in expect(KeeperHubError, c.poll, "")


@test("C1: 202 Accepted is the documented write success")
def _():
    c, _ = client([accepted("exec-42", "0x" + "cd" * 32)])
    r = c.broadcast(request(), KEY)
    assert r.outcome is SendOutcome.ACCEPTED and r.status_code == 202
    assert r.execution_id == "exec-42" and r.tx_hash == "0x" + "cd" * 32


@test("C1: the two documented 409 codes are opposite situations, not one branch")
def _():
    c, t = client([response(
        {"code": CODE_IDEMPOTENCY_IN_PROGRESS, "executionId": "exec-9", "retryable": True},
        409)])
    r = c.broadcast(request(), KEY)
    assert r.outcome is SendOutcome.IN_PROGRESS
    assert r.execution_id == "exec-9" and r.retryable is True
    assert len(t.calls) == 1, "an in-progress conflict must not be resent"

    c2, t2 = client([response(
        {"code": CODE_IDEMPOTENCY_CONFLICT, "retryable": False,
         "message": "same key, different body"}, 409)])
    r2 = c2.broadcast(request(), KEY)
    assert r2.outcome is SendOutcome.IDEMPOTENCY_CONFLICT, (
        "a conflicting body is a determinism bug in our own request, not something to poll")
    assert r2.retryable is False
    assert "non-deterministic" in (r2.error or "")
    assert len(t2.calls) == 1, "a conflict must never be retried"

    # An undocumented 409 code is not something to guess about.
    c3, _ = client([response({"code": "something_new"}, 409)])
    assert c3.broadcast(request(), KEY).outcome is SendOutcome.UNKNOWN


@test("C1 REGRESSION: the DOCUMENTED simulation response is SIMULATED, not ACCEPTED")
def _():
    # The defect: the classifier looked for `simulated: true` / `simulation` -- fields I
    # invented and then tested against my own invention. The documented response is
    # {"success": true, "status": "simulated", "wouldRevert": false}, which that check
    # missed entirely, so a dry run was recorded as an economic execution.
    c, t = client([response(
        {"success": True, "status": "simulated", "wouldRevert": False}, 200)])
    r = c.dry_run(request(simulate=True))
    assert t.calls[0]["body"]["simulate"] is True
    assert r.outcome is SendOutcome.SIMULATED, (
        f"the documented simulation shape classified as {r.outcome.value}")
    assert r.tx_hash is None


@test("C1 REGRESSION: a positive preflight requires the AFFIRMATIVE documented fields")
def _():
    # Rejecting only an empty object was not enough: {"success": false} and a bare
    # {"status": "simulated"} still classified as SIMULATED -- a green light assembled
    # from a missing verdict.
    cases = {
        '{}': ({}, SendOutcome.UNKNOWN),
        'success=false': ({"success": False}, SendOutcome.REJECTED),
        'status only': ({"status": "simulated"}, SendOutcome.UNKNOWN),
        'no wouldRevert': ({"success": True, "status": "simulated"}, SendOutcome.UNKNOWN),
        'documented ok': ({"success": True, "status": "simulated", "wouldRevert": False},
                          SendOutcome.SIMULATED),
        'wrong status': ({"success": True, "status": "executed", "wouldRevert": False},
                         SendOutcome.UNKNOWN),
    }
    for label, (body, expected) in cases.items():
        c, _ = client([response(body, 200)])
        got = c.dry_run(request(simulate=True)).outcome
        assert got is expected, f"{label}: expected {expected.value}, got {got.value}"


@test("C1: a simulation predicting a revert is REJECTED, not a green light")
def _():
    c, _ = client([response(
        {"success": True, "status": "simulated", "wouldRevert": True,
         "revertReason": "AmountOutOfRange()"}, 200)])
    r = c.dry_run(request(simulate=True))
    assert r.outcome is SendOutcome.REJECTED, (
        "a successful simulation reporting a failing call must not read as SIMULATED-ok")
    assert "wouldRevert=True" in (r.error or "") and "AmountOutOfRange" in (r.error or "")


@test("C1: request mode and response mode must agree")
def _():
    # A broadcast that comes back simulated, or a simulation that comes back as something
    # else, is a contradiction. Neither may be recorded as a settled outcome.
    c, _ = client([response({"success": True, "status": "simulated"}, 202)])
    r = c.broadcast(request(), KEY)
    assert r.outcome is SendOutcome.UNKNOWN and "disagree" in (r.error or "")

    c2, _ = client([response(
        {"success": True, "status": "executed", "wouldRevert": False}, 200)])
    r2 = c2.dry_run(request(simulate=True))
    assert r2.outcome is SendOutcome.UNKNOWN
    assert "asked to simulate" in (r2.error or "")


@test("C1: the invented `simulated: true` shape no longer passes as a preflight")
def _():
    # This shape was MY invention, never documented. It is still recognised for the
    # contradiction check on a broadcast, but on a simulate request it carries no
    # affirmative verdict and must not be a green light.
    c, _ = client([response({"simulated": True}, 200)])
    r = c.dry_run(request(simulate=True))
    assert r.outcome is SendOutcome.UNKNOWN, r.outcome
    assert "missing" in (r.error or "")



@test("C1: simulate is part of the request identity, not a transit flag")
def _():
    c, _ = client([response({}, 200)])
    assert "simulate=True" in expect(KeeperHubError, c.dry_run, request(simulate=False))
    assert "simulate=False" in expect(KeeperHubError, c.broadcast, request(simulate=True), KEY)


@test("C1: simulate is a strict boolean, as the API requires")
def _():
    for bad in ("true", 1, None, 0):
        assert "strict boolean" in expect(
            KeeperHubError, ContractCallRequest,
            chain_id=CHAIN_ID, contract_address=CONTROLLER, function_name="executeSupply",
            function_args=[ENV_ARG, MARKET_PARAMS, 1, bytes(65)],
            abi=function_abi("executeSupply"), expected_calldata="0xab", simulate=bad)


@test("C1: 403 names scope and spending cap, not only a bad credential")
def _():
    c, _ = client([response({"message": "insufficient scope"}, 403)])
    r = c.broadcast(request(), KEY)
    assert r.outcome is SendOutcome.REJECTED
    assert "spending cap" in (r.error or "") and "mcp:write" in (r.error or "")

    c2, _ = client([response({"message": "bad key"}, 401)])
    assert "L10" in (c2.broadcast(request(), KEY).error or "")


@test("C1: a documented Retry-After is obeyed, never shortened")
def _():
    policy = BackoffPolicy(base_seconds=1.0, max_seconds=30.0, jitter=0.0)
    assert policy.delay_for(1, retry_after=7.5) == 7.5
    # The old code capped this at max_seconds, silently shortening the pacing the
    # server asked for -- which is how a client earns a harder rate limit.
    assert policy.delay_for(1, retry_after=120.0) == 120.0, "server pacing was shortened"
    assert policy.delay_for(1, retry_after=-5) == 0.0
    # Our own guess is still bounded.
    assert [policy.delay_for(i) for i in range(1, 6)] == [1.0, 2.0, 4.0, 8.0, 16.0]


@test("C1: a 429 is retried under the same key, honouring Retry-After")
def _():
    c, t = client([response({}, 429, {"Retry-After": "3"}), accepted()],
                  backoff=BackoffPolicy(max_attempts=3, base_seconds=1.0, jitter=0.0))
    r = c.broadcast(request(), KEY)
    assert r.outcome is SendOutcome.ACCEPTED
    assert c._slept == [3.0], f"expected the server's 3s, got {c._slept}"
    keys = {call["headers"][IDEMPOTENCY_HEADER] for call in t.calls}
    assert keys == {KEY}, f"retries must reuse the key: {keys}"
    bodies = {json.dumps(call["body"], sort_keys=True) for call in t.calls}
    assert len(bodies) == 1, "the body changed between retries"


# ------------------------------------------------------------ L10 stays a gate --
@test("with no credential the client refuses and names L10")
def _():
    os.environ.pop(API_ENV, None)
    c = KeeperHubClient(transport=OfflineTransport([accepted()]))
    msg = expect(L10Blocked, c.broadcast, request(), KEY)
    assert "L10" in msg and "not stubbed or simulated" in msg, msg


@test("an offline result can never be filed as hosted evidence")
def _():
    c, _ = client([accepted()])
    r = c.broadcast(request(), KEY)
    assert r.hosted is False
    msg = expect(L10Blocked, r.assert_hosted_evidence)
    assert "does not show" in msg and "L10" in msg, msg


@test("a non-https origin cannot be a hosted transport")
def _():
    for bad in ("http://app.keeperhub.com", "http://localhost:8080", "https-ish://x"):
        assert "https" in expect(KeeperHubError, HttpsTransport, bad)
    assert HttpsTransport("https://app.keeperhub.com").hosted is True


@test("preflight uses the AUTHENTICATED route in simulate mode, never the public catalog")
def _():
    # /api/chains is public -- verified live, it answers 200 with no credential at all.
    # A preflight built on it would have "passed" for an invalid key and for no key.
    c, t = client([response({"simulated": True}, 200)])
    c.preflight(request(simulate=True))
    assert t.calls[0]["url"].endswith("/api/execute/contract-call")
    assert t.calls[0]["method"] == "POST"
    assert t.calls[0]["body"]["simulate"] is True, "a preflight must not broadcast"
    assert "Authorization" in t.calls[0]["headers"]

    os.environ.pop(API_ENV, None)
    c2 = KeeperHubClient(transport=OfflineTransport([accepted()]))
    assert "L10" in expect(L10Blocked, c2.preflight, request(simulate=True))


@test("the public catalog is reachable without a credential, and says so")
def _():
    os.environ.pop(API_ENV, None)
    c = KeeperHubClient(transport=OfflineTransport([response({"data": []}, 200)]))
    r = c.public_chain_catalog()
    assert r.outcome is SendOutcome.ACCEPTED and r.hosted is False
    assert "Authorization" not in c.transport.calls[0]["headers"]
    assert "L10" in expect(L10Blocked, r.assert_hosted_evidence)


@test("the credential is a reference, and never appears in a repr or a log line")
def _():
    ref = CredentialReference(f"env:{API_ENV}")
    assert_no_secrets(ref.ref, "credential_ref")
    assert "kh_local" not in repr(ref)
    c, _ = client([accepted()])
    assert FAKE_CREDENTIAL not in repr(c)
    redacted = KeeperHubClient.redact(c._headers(KEY))
    assert redacted["Authorization"] == "Bearer <redacted>"
    assert redacted[IDEMPOTENCY_HEADER] == KEY, "the key is not a secret and aids debugging"
    assert FAKE_CREDENTIAL not in json.dumps(redacted)


@test("a credential reference that carries the secret itself is refused")
def _():
    assert "secret itself" in expect(CredentialError, CredentialReference, "0x" + "ab" * 24)
    assert "env:NAME" in expect(CredentialError, CredentialReference, "file:/etc/keeperhub")


# ------------------------------------------------------------- execution keys --
@test("the execution key is stable per attempt and distinct per attempt")
def _():
    a1 = execution_key(OP_HEX, "attempt-1")
    assert a1 == execution_key(OP_HEX, "attempt-1"), "a retry must reuse the key"
    assert a1 != execution_key(OP_HEX, "attempt-2"), "a replacement attempt is a new send"
    assert a1 != execution_key("0x" + "bb" * 32, "attempt-1")
    assert len(a1) == 66 and a1 != OP_HEX
    assert "attempt_id" in expect(KeeperHubError, execution_key, OP_HEX, "")
    assert "32 bytes" in expect(KeeperHubError, execution_key, "0xdeadbeef", "a")


# ------------------------------------------------------------- classification --
@test("4xx client errors are REJECTED: definitively nothing was broadcast")
def _():
    for code in (400, 404, 422):
        c, _ = client([response({"message": "bad"}, code)])
        assert c.broadcast(request(), KEY).outcome is SendOutcome.REJECTED


@test("a 5xx that never resolves is UNKNOWN, never REJECTED")
def _():
    c, t = client([response({}, 502), response({}, 502), response({}, 503), response({}, 500)])
    r = c.broadcast(request(), KEY)
    assert r.outcome is SendOutcome.UNKNOWN, (
        "a server error may or may not have broadcast; REJECTED is how one operation "
        "gets executed twice")
    assert len(t.calls) == 4 and r.attempts_made == 4


@test("a timeout or dropped connection is UNKNOWN, never 'not sent'")
def _():
    c, t = client([TimeoutError("read timed out"), accepted("exec-late")])
    assert c.broadcast(request(), KEY).outcome is SendOutcome.ACCEPTED
    assert len(t.calls) == 2
    c2, _ = client([TimeoutError("t")] * 4)
    r2 = c2.broadcast(request(), KEY)
    assert r2.outcome is SendOutcome.UNKNOWN and "TimeoutError" in (r2.error or "")


@test("an unrecognised status is UNKNOWN rather than assumed harmless")
def _():
    c, _ = client([response({}, 418)])
    assert c.broadcast(request(), KEY).outcome is SendOutcome.UNKNOWN


@test("a payable request is refused before any network call")
def _():
    args = [ENV_ARG, MARKET_PARAMS, 1, bytes(65)]
    assert "non-payable" in expect(
        KeeperHubError, ContractCallRequest,
        chain_id=CHAIN_ID, contract_address=CONTROLLER, function_name="executeSupply",
        function_args=args, abi=function_abi("executeSupply"),
        expected_calldata=encode_call("executeSupply", args), value_ether="0.5")


def main() -> int:
    os.environ.pop(API_ENV, None)
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"P03 keeperhub: FAIL ({len(FAILED)}/{len(PASSED)+len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} P03 KeeperHub wire-contract tests held (L10 NOT established)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
