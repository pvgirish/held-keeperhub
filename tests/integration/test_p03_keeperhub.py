"""P03: the KeeperHub execution client.

SCOPE, stated plainly because this is the easiest place in the project to overclaim:
these tests establish that Held builds the right request, derives a stable execution
key, paces retries, and classifies responses correctly -- including the ones where the
outcome is genuinely unknown. They run entirely against `OfflineTransport`, which stamps
`hosted=False` on everything.

They do NOT establish L10. Nothing here shows that the authenticated KeeperHub
organisation caller/payer accepts Held's outer call. Several tests below exist
specifically to prove that a local result CANNOT be filed as if it did.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "packages", "core"))
sys.path.insert(0, os.path.join(ROOT, "adapter"))

from held_adapter.execution.keeperhub import (  # noqa: E402
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

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

API_ENV = "HELD_KEEPERHUB_API_KEY"
FAKE_CREDENTIAL = "kh_local_test_credential_not_real"
CONTROLLER = "0x3875311cc0d4017a033893a9653a0725378aca1c"
OP_ID = "0x" + "aa" * 32


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


def ok(body: dict, status: int = 200, headers: dict | None = None) -> HttpResponse:
    return HttpResponse(status, json.dumps(body).encode(), headers or {})


def request(attempt_id: str = "attempt-1") -> ContractCallRequest:
    return ContractCallRequest(
        chain_id=8453,
        to=CONTROLLER,
        calldata="0x" + "ab" * 200,
        execution_key=execution_key(OP_ID, attempt_id),
        operation_id=OP_ID,
        attempt_id=attempt_id,
    )


def client(responses, **kw) -> tuple[KeeperHubClient, OfflineTransport]:
    os.environ[API_ENV] = FAKE_CREDENTIAL
    t = OfflineTransport(responses)
    slept: list[float] = []
    c = KeeperHubClient(transport=t, sleep=slept.append, **kw)
    c._slept = slept  # type: ignore[attr-defined]
    return c, t


# ------------------------------------------------------------ L10 stays a gate --
@test("with no credential the client refuses and names L10")
def _():
    os.environ.pop(API_ENV, None)
    c = KeeperHubClient(transport=OfflineTransport([ok({})]))
    msg = expect(L10Blocked, c.broadcast, request())
    assert "L10" in msg and "not stubbed or simulated" in msg, msg


@test("an offline result can never be filed as hosted evidence")
def _():
    c, _ = client([ok({"executionId": "exec-1"})])
    r = c.broadcast(request())
    assert r.outcome is SendOutcome.ACCEPTED
    assert r.hosted is False, "OfflineTransport must never produce a hosted result"
    msg = expect(L10Blocked, r.assert_hosted_evidence)
    assert "does not show" in msg and "L10" in msg, msg


@test("hosted is set by the transport, not by an argument the caller controls")
def _():
    import dataclasses
    from held_adapter.execution.keeperhub import SendResult
    c, _ = client([ok({"executionId": "e"})])
    r = c.broadcast(request())
    # A caller CAN construct a lying copy -- but they have to do it explicitly, and the
    # client itself never offers hosted as an input.
    assert "hosted" not in {f.name for f in dataclasses.fields(ContractCallRequest)}
    assert dataclasses.replace(r, hosted=True).assert_hosted_evidence().hosted is True
    assert r.hosted is False


@test("a non-https origin cannot be a hosted transport")
def _():
    for bad in ("http://app.keeperhub.com", "http://localhost:8080", "https-ish://x"):
        msg = expect(KeeperHubError, HttpsTransport, bad)
        assert "https" in msg, msg
    assert HttpsTransport("https://app.keeperhub.com").hosted is True


@test("the credential is a reference, and never appears in a repr or a log line")
def _():
    ref = CredentialReference(f"env:{API_ENV}")
    assert ref.env_var == API_ENV
    assert_no_secrets(ref.ref, "credential_ref")
    assert "kh_local" not in repr(ref)

    c, _ = client([ok({})])
    assert FAKE_CREDENTIAL not in repr(c)
    redacted = KeeperHubClient.redact(c._headers())
    assert redacted["Authorization"] == "Bearer <redacted>"
    assert FAKE_CREDENTIAL not in json.dumps(redacted)


@test("a credential reference that carries the secret itself is refused")
def _():
    assert "secret itself" in expect(
        CredentialError, CredentialReference, "0x" + "ab" * 24)
    assert "env:NAME" in expect(CredentialError, CredentialReference, "file:/etc/keeperhub")


# ------------------------------------------------------------- execution keys --
@test("the execution key is stable per attempt and distinct per attempt")
def _():
    a1 = execution_key(OP_ID, "attempt-1")
    assert a1 == execution_key(OP_ID, "attempt-1"), "a retry must reuse the key to dedupe"
    assert a1 != execution_key(OP_ID, "attempt-2"), "a replacement attempt is a new send"
    other_op = "0x" + "bb" * 32
    assert a1 != execution_key(other_op, "attempt-1")
    assert len(a1) == 66 and a1.startswith("0x")


@test("the execution key is domain-separated from the operation id itself")
def _():
    assert execution_key(OP_ID, "attempt-1") != OP_ID
    assert "attempt_id" in expect(KeeperHubError, execution_key, OP_ID, "")
    assert "32 bytes" in expect(KeeperHubError, execution_key, "0xdeadbeef", "a")


# ------------------------------------------------------------------- requests --
@test("the request payload carries the idempotency key and Held's correlation fields")
def _():
    c, t = client([ok({"executionId": "exec-9"})])
    req = request()
    c.broadcast(req)
    sent = t.calls[0]["body"]
    assert sent["idempotencyKey"] == req.execution_key
    assert sent["chainId"] == 8453
    assert sent["to"] == CONTROLLER.lower()
    assert sent["value"] == "0"
    assert sent["simulate"] is False
    assert sent["metadata"]["heldOperationId"] == OP_ID
    assert sent["metadata"]["heldAttemptId"] == "attempt-1"
    assert t.calls[0]["url"].endswith("/api/execute/contract-call")


@test("a dry run is explicitly flagged and is not an execution")
def _():
    c, t = client([ok({"simulated": True})])
    r = c.dry_run(request())
    assert t.calls[0]["body"]["simulate"] is True
    assert r.tx_hash is None, "a dry run must not report a transaction hash"


@test("a malformed or payable request is refused before any network call")
def _():
    base = dict(chain_id=8453, to=CONTROLLER, execution_key=execution_key(OP_ID, "a"),
                operation_id=OP_ID, attempt_id="a")
    assert "non-payable" in expect(
        KeeperHubError, ContractCallRequest, calldata="0x" + "ab" * 200, value=1, **base)
    assert "0x-prefixed" in expect(
        KeeperHubError, ContractCallRequest, calldata="abcd", **base)
    assert "selector" in expect(
        KeeperHubError, ContractCallRequest, calldata="0xabc", **base)


# ------------------------------------------------------------- classification --
@test("a 2xx is ACCEPTED and surfaces the execution id")
def _():
    c, _ = client([ok({"executionId": "exec-42", "transactionHash": "0x" + "cd" * 32})])
    r = c.broadcast(request())
    assert r.outcome is SendOutcome.ACCEPTED
    assert r.execution_id == "exec-42"
    assert r.tx_hash == "0x" + "cd" * 32


@test("a 409 is IN_PROGRESS with the existing execution id, not a failure")
def _():
    c, t = client([ok({"executionId": "exec-existing", "message": "already in flight"}, 409)])
    r = c.broadcast(request())
    assert r.outcome is SendOutcome.IN_PROGRESS, "a conflict is the dedupe working"
    assert r.execution_id == "exec-existing"
    assert len(t.calls) == 1, "a conflict must not be retried; poll instead"


@test("401/403 is REJECTED and says L10, because that is what it means")
def _():
    for code in (401, 403):
        c, _ = client([ok({"message": "invalid organisation key"}, code)])
        r = c.broadcast(request())
        assert r.outcome is SendOutcome.REJECTED
        assert "L10" in (r.error or ""), r.error


@test("4xx client errors are REJECTED: definitively nothing was broadcast")
def _():
    for code in (400, 404, 422):
        c, _ = client([ok({"message": "bad"}, code)])
        assert c.broadcast(request()).outcome is SendOutcome.REJECTED


@test("a 5xx that never resolves is UNKNOWN, never REJECTED")
def _():
    c, t = client([ok({}, 502), ok({}, 502), ok({}, 503), ok({}, 500)])
    r = c.broadcast(request())
    assert r.outcome is SendOutcome.UNKNOWN, (
        "a server error may or may not have broadcast; calling it REJECTED is how the "
        "same operation gets executed twice"
    )
    assert len(t.calls) == 4 and r.attempts_made == 4


@test("a timeout or dropped connection is UNKNOWN, never 'not sent'")
def _():
    c, t = client([TimeoutError("read timed out"), ok({"executionId": "exec-late"})])
    r = c.broadcast(request())
    # It recovered here, but the point is the first failure did not become REJECTED.
    assert r.outcome is SendOutcome.ACCEPTED and len(t.calls) == 2

    c2, _ = client([TimeoutError("t")] * 4)
    r2 = c2.broadcast(request())
    assert r2.outcome is SendOutcome.UNKNOWN
    assert "TimeoutError" in (r2.error or "")


@test("an unrecognised status is UNKNOWN rather than assumed harmless")
def _():
    c, _ = client([ok({}, 418)])
    assert c.broadcast(request()).outcome is SendOutcome.UNKNOWN


@test("a retry reuses the SAME idempotency key, so KeeperHub can dedupe it")
def _():
    c, t = client([ok({}, 503), ok({"executionId": "exec-1"})])
    c.broadcast(request())
    keys = {call["body"]["idempotencyKey"] for call in t.calls}
    assert len(keys) == 1, f"retries must not mint new keys: {keys}"


# ------------------------------------------------------------------- backoff --
@test("retries back off exponentially and are capped")
def _():
    policy = BackoffPolicy(max_attempts=5, base_seconds=1.0, max_seconds=8.0, jitter=0.0)
    assert [policy.delay_for(i) for i in range(1, 6)] == [1.0, 2.0, 4.0, 8.0, 8.0]


@test("a server's Retry-After wins over our own guess")
def _():
    policy = BackoffPolicy(base_seconds=1.0, max_seconds=30.0, jitter=0.0)
    assert policy.delay_for(1, retry_after=7.5) == 7.5
    assert policy.delay_for(4, retry_after=2.0) == 2.0, "server pacing overrides ours"
    assert policy.delay_for(1, retry_after=1e9) == 30.0, "still capped"
    assert policy.delay_for(1, retry_after=-5) == 0.0


@test("a 429 is retried and honours Retry-After from the response")
def _():
    c, t = client(
        [ok({}, 429, {"Retry-After": "3"}), ok({"executionId": "exec-ok"})],
        backoff=BackoffPolicy(max_attempts=3, base_seconds=1.0, jitter=0.0),
    )
    r = c.broadcast(request())
    assert r.outcome is SendOutcome.ACCEPTED
    assert c._slept == [3.0], f"expected the server's 3s, got {c._slept}"
    assert len(t.calls) == 2


@test("jitter keeps retries from synchronising, and stays within bounds")
def _():
    policy = BackoffPolicy(base_seconds=4.0, max_seconds=60.0, jitter=0.25)
    seen = {round(policy.delay_for(2), 6) for _ in range(40)}
    assert len(seen) > 1, "no jitter applied"
    assert all(6.0 <= d <= 10.0 for d in seen), seen


# -------------------------------------------------------------------- polling --
@test("polling reads an execution by id and reports its receipt")
def _():
    c, t = client([ok({"executionId": "exec-7", "transactionHash": "0x" + "ef" * 32})])
    r = c.poll("exec-7")
    assert t.calls[0]["url"].endswith("/api/execute/exec-7")
    assert t.calls[0]["method"] == "GET"
    assert r.tx_hash == "0x" + "ef" * 32
    assert "execution_id is required" in expect(KeeperHubError, c.poll, "")


@test("a poll that errors leaves the outcome unknown rather than clearing the operation")
def _():
    c, _ = client([TimeoutError("t")] * 4)
    assert c.poll("exec-7").outcome is SendOutcome.UNKNOWN


@test("preflight uses the AUTHENTICATED route, never the public catalog")
def _():
    # The bug this pins down: /api/chains is public. Verified live -- it answers 200
    # with the full catalog and no credential at all. A preflight built on it would
    # have reported success for an invalid key and for no key, which is exactly the
    # vacuous pass L10 must not have.
    c, t = client([ok({"simulated": True})])
    c.preflight(request())
    assert t.calls[0]["url"].endswith("/api/execute/contract-call"), t.calls[0]["url"]
    assert t.calls[0]["method"] == "POST"
    assert t.calls[0]["body"]["simulate"] is True, "a preflight must not broadcast"
    assert "Authorization" in t.calls[0]["headers"]


@test("preflight resolves the credential, so it cannot pass vacuously")
def _():
    os.environ.pop(API_ENV, None)
    c = KeeperHubClient(transport=OfflineTransport([ok({})]))
    assert "L10" in expect(L10Blocked, c.preflight, request())

    c2, _ = client([ok({"simulated": True})])
    r = c2.preflight(request())
    assert r.outcome is SendOutcome.ACCEPTED
    assert r.hosted is False, "an offline preflight is not an L10 result"


@test("the public catalog is reachable without a credential, and says so")
def _():
    # Kept as its own method precisely so it cannot be mistaken for authentication.
    os.environ.pop(API_ENV, None)
    c = KeeperHubClient(transport=OfflineTransport([
        ok({"data": [{"chainId": 8453, "isEnabled": True}]})]))
    r = c.public_chain_catalog()  # no L10Blocked: it needs no credential
    assert r.outcome is SendOutcome.ACCEPTED
    assert r.hosted is False
    sent = c.transport.calls[0]
    assert "Authorization" not in sent["headers"], (
        "the public catalog must not carry the org credential")
    assert "L10" in expect(L10Blocked, r.assert_hosted_evidence)


def main() -> int:
    os.environ.pop(API_ENV, None)
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"P03 keeperhub: FAIL ({len(FAILED)}/{len(PASSED)+len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} P03 KeeperHub client tests held (L10 NOT established)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
