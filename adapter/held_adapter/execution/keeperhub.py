"""The KeeperHub execution client: the outer caller/payer route.

Held signs an authorization envelope and then needs somebody to land the controller call
on chain. That is KeeperHub's `POST /api/execute/contract-call` route (route-evidence L4:
the Morpho plugin is not used).

## This module implements the DOCUMENTED contract, not an invented one

An earlier version of this file sent `to` and `data`, put `idempotencyKey` in the JSON
body, polled `/api/execute/{id}`, and collapsed every 409 into "in progress". None of
that matches the published API. The most serious consequence was not the wrong field
names: the client **retried ambiguous failures while sending no idempotency header at
all**, so the retry was not protected by the mechanism its own comments claimed.

The documented contract, from https://docs.keeperhub.com/api/direct-execution
(reread 2026-09-16):

  * Body: `contractAddress`, `chainId`, `functionName` (alias `abiFunction`),
    `functionArgs` (JSON array **as a string**), `abi` (JSON **string**), `value`
    (decimal string in ETHER units), `gasLimitMultiplier`, `simulate` (STRICT boolean --
    `"true"` and `1` are rejected with 400).
  * Idempotency: the `Idempotency-Key` HEADER only, 24-hour window. No body field.
  * Poll: `GET /api/execute/{executionId}/status`, returning `X-Poll-Interval-Hint`
    (`0` means terminal).
  * Success: `200` for reads, `202 Accepted` for writes.
  * `409` carries a `code`: `idempotency_conflict` (same key, DIFFERENT body) or
    `idempotency_in_progress` (same key, still processing). These are opposite
    situations and must not share a branch.
  * `403` is insufficient scope OR spending cap exceeded -- not only a bad credential.
  * `429` carries `Retry-After`; the limit is 60 requests/minute/key.
  * Scopes: `mcp:read` permits dry-run only; `mcp:write` is required to broadcast.

## Why `idempotency_conflict` is a hard failure

It means we reused a key with a different body. Held derives the key from the operation
and attempt, and derives the body from the admitted action -- so if the server sees a
different body under the same key, one of those is not deterministic. Retrying cannot
help and would be actively wrong. It is surfaced as its own outcome so it can never be
mistaken for "already in flight, just poll".

## L10 is a gate, not a setting

`L10-authenticated-caller-payer` is BLOCKED-UNKNOWN. Only `HttpsTransport` can produce a
hosted result; `OfflineTransport` stamps `hosted=False`; `assert_hosted_evidence()`
refuses a non-hosted result. A local test of this module establishes that Held forms the
documented request and reads the documented answers. It does not establish L10.

## Why the outcome vocabulary is what it is

The dangerous failure is not "the send failed" but "the send may or may not have
happened". Timeouts, dropped connections and ambiguous 5xx all leave an operation whose
on-chain outcome is unknown, and treating that as "not sent" is how one operation gets
executed twice. `UNKNOWN` exists so that case has a name and cannot collapse into
`REJECTED`.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence

from eth_utils import keccak

from held_core.canonical import hex32, normalize_address

DEFAULT_BASE_URL = "https://app.keeperhub.com"
CONTRACT_CALL_PATH = "/api/execute/contract-call"
CHAINS_PATH = "/api/chains"
STATUS_PATH = "/api/execute/{execution_id}/status"

IDEMPOTENCY_HEADER = "Idempotency-Key"
POLL_HINT_HEADER = "X-Poll-Interval-Hint"

# The documented idempotency window. Past it, the server no longer dedupes, so a resend
# is a genuinely new submission and must be preceded by an on-chain consumption check.
IDEMPOTENCY_WINDOW_SECONDS = 24 * 3600

# Documented 409 codes. Opposite meanings; never merge these branches.
CODE_IDEMPOTENCY_CONFLICT = "idempotency_conflict"
CODE_IDEMPOTENCY_IN_PROGRESS = "idempotency_in_progress"

# The documented successful-simulation status. A simulation response is
# `{"success": true, "status": "simulated", "wouldRevert": false}`.
STATUS_SIMULATED = "simulated"

# Domain tag so an execution key can never collide with an operation id or payload hash.
EXECUTION_KEY_DOMAIN = b"held.keeperhub.execution-key.v1"

_KEY_SHAPED = re.compile(r"(?:^|[^0-9a-zA-Z])(?:0x)?[0-9a-fA-F]{40,}(?:$|[^0-9a-zA-Z])")


class KeeperHubError(Exception):
    """A KeeperHub interaction failed in a way the caller must handle."""


class L10Blocked(KeeperHubError):
    """The authenticated organisation route is not available."""


class CredentialError(KeeperHubError):
    """The credential reference is malformed, secret-shaped, or points at nothing."""


class RequestIntegrityError(KeeperHubError):
    """The request would not encode to the calldata it is supposed to carry."""


class SendOutcome(str, Enum):
    """What is known about a submission. `UNKNOWN` is the whole point."""

    ACCEPTED = "ACCEPTED"                # 202 (write) / 200 (read); KeeperHub owns it
    SIMULATED = "SIMULATED"              # a dry run succeeded; NOT an execution
    IN_PROGRESS = "IN_PROGRESS"          # same key still processing; poll, do not resend
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"  # same key, DIFFERENT body: a bug
    REJECTED = "REJECTED"                # definitively refused; nothing was broadcast
    UNKNOWN = "UNKNOWN"                  # may or may not have broadcast. NEVER "not sent"


# Definitively-refused statuses: the request was understood and declined, so nothing was
# broadcast. Anything NOT listed leaves the outcome unknown.
_DEFINITIVE_REJECTION = frozenset({400, 401, 403, 404, 422})


@dataclass(frozen=True)
class CredentialReference:
    """Where the org API key lives. Never what it is."""

    ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.ref, str):
            raise CredentialError("credential reference must be a string")
        if _KEY_SHAPED.search(self.ref):
            raise CredentialError(
                "credential reference looks like the secret itself. Pass 'env:NAME' so "
                "only the NAME is ever persisted."
            )
        if not self.ref.startswith("env:"):
            raise CredentialError(f"credential reference must be 'env:NAME'; got {self.ref!r}")

    @property
    def env_var(self) -> str:
        return self.ref.split(":", 1)[1]

    def __repr__(self) -> str:
        return f"CredentialReference({self.ref!r})"

    def resolve(self) -> str:
        value = os.environ.get(self.env_var)
        if not value:
            raise L10Blocked(
                f"L10 is not satisfied: ${self.env_var} is unset, so there is no "
                "authenticated KeeperHub organisation caller/payer. This gate is not "
                "stubbed or simulated; without a real org credential the hosted route "
                "cannot be exercised."
            )
        return value


def execution_key(operation_id: bytes | str, attempt_id: str) -> str:
    """The value sent as the `Idempotency-Key` header.

    Bound to the ATTEMPT, not just the operation. Retrying the same attempt after a
    timeout must reuse the key so KeeperHub collapses it; a deliberately new attempt
    (after a definitive rejection, under a new epoch) is a different send and gets a
    different key. Keying on the operation alone would make a legitimate replacement
    attempt indistinguishable from a duplicate.
    """
    if isinstance(operation_id, str):
        operation_id = bytes.fromhex(
            operation_id[2:] if operation_id.startswith("0x") else operation_id
        )
    if not isinstance(operation_id, bytes) or len(operation_id) != 32:
        raise KeeperHubError("operation_id: expected 32 bytes")
    if not attempt_id or not isinstance(attempt_id, str):
        raise KeeperHubError("attempt_id: expected a non-empty string")
    return hex32(keccak(EXECUTION_KEY_DOMAIN + operation_id + attempt_id.encode()))


@dataclass(frozen=True)
class ContractCallRequest:
    """One outer call, in the documented schema.

    `expected_calldata` is not sent. It is the calldata these arguments MUST encode to,
    and `verify_encoding()` checks that locally before anything leaves. Sending
    `functionName`/`functionArgs` hands encoding to the server, so without this check
    Held would be trusting a remote encoder to reproduce the bytes the runner signed
    over.
    """

    chain_id: int
    contract_address: str
    function_name: str
    function_args: Sequence[Any]
    abi: Sequence[Mapping[str, Any]]
    expected_calldata: str
    value_ether: str = "0"
    simulate: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "contract_address", normalize_address(self.contract_address, "contractAddress")
        )
        if not isinstance(self.simulate, bool):
            # The API rejects a non-boolean with 400; catching it here keeps a
            # construction bug from consuming a request against the rate limit.
            raise KeeperHubError("simulate must be a strict boolean (documented)")
        if not isinstance(self.expected_calldata, str) or not self.expected_calldata.startswith("0x"):
            raise KeeperHubError("expected_calldata must be 0x-prefixed hex")
        if self.value_ether != "0":
            # The controller entry points are non-payable. `value` is documented in
            # ETHER units, not base units, so a mistake here is a large one.
            raise KeeperHubError("value must be \"0\": the controller entry points are non-payable")

    def verify_encoding(self) -> None:
        """Re-encode the arguments and require the expected calldata, byte for byte.

        The documented API takes `functionName`/`functionArgs`, so the SERVER encodes.
        The runner's signature commits to an action hash the controller recomputes from
        the arguments it actually receives, which means a divergent encoding would be
        discovered on chain, after an execution had been spent. This proves locally that
        these arguments are the ones that produce the intended calldata.

        It does NOT prove KeeperHub's encoder agrees. That needs one authenticated dry
        run and is blocked on L10.
        """
        from .controller_abi import decode_and_match

        decode_and_match(self.expected_calldata, self.function_name, self.function_args)

    def to_payload(self) -> dict[str, Any]:
        """The documented body. `functionArgs` and `abi` are JSON STRINGS."""
        return {
            "contractAddress": self.contract_address,
            "chainId": self.chain_id,
            "functionName": self.function_name,
            "functionArgs": json.dumps(_jsonable(self.function_args)),
            "abi": json.dumps(_jsonable(self.abi)),
            "value": self.value_ether,
            "simulate": self.simulate,
        }


def _jsonable(value: Any) -> Any:
    """Render bytes as 0x-hex and ints as decimal strings for JSON transport.

    Large uint256 values must not become JSON numbers: they exceed IEEE-754 exact
    integer range and a JSON parser is free to mangle them.
    """
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Mapping):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


@dataclass(frozen=True)
class SendResult:
    outcome: SendOutcome
    hosted: bool                 # set by the transport, never by an argument
    status_code: int | None = None
    execution_id: str | None = None
    tx_hash: str | None = None
    error: str | None = None
    error_code: str | None = None
    retryable: bool | None = None
    poll_hint_seconds: float | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)
    attempts_made: int = 1

    @property
    def terminal(self) -> bool:
        """A documented poll hint of 0 means the execution has reached a final state."""
        return self.poll_hint_seconds == 0

    def assert_hosted_evidence(self) -> "SendResult":
        if not self.hosted:
            raise L10Blocked(
                "this result came from a non-hosted transport, so it is evidence about "
                "request construction and response parsing ONLY. It does not show that "
                "the authenticated KeeperHub route accepts Held's call (L10)."
            )
        return self


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)

    def json(self) -> dict[str, Any]:
        if not self.body:
            return {}
        try:
            parsed = json.loads(self.body)
        except (ValueError, UnicodeDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {"data": parsed}

    def header(self, name: str) -> str | None:
        for k, v in self.headers.items():
            if k.lower() == name.lower():
                return v
        return None


class Transport(Protocol):
    hosted: bool

    def request(self, method: str, url: str, *, headers: Mapping[str, str],
                body: bytes | None, timeout: float) -> HttpResponse: ...


class HttpsTransport:
    """The ONLY transport that can produce hosted evidence."""

    hosted = True

    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        if not base_url.startswith("https://"):
            raise KeeperHubError(
                f"hosted transport requires an https:// origin; got {base_url!r}. A "
                "non-https origin cannot carry an org credential and cannot be hosted "
                "evidence."
            )
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, url: str, *, headers: Mapping[str, str],
                body: bytes | None, timeout: float) -> HttpResponse:
        import requests

        resp = requests.request(method, url, headers=dict(headers), data=body, timeout=timeout)
        return HttpResponse(resp.status_code, resp.content, dict(resp.headers))


class OfflineTransport:
    """Canned responses for exercising construction and parsing. NEVER hosted."""

    hosted = False

    def __init__(self, responses: list[HttpResponse | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, *, headers: Mapping[str, str],
                body: bytes | None, timeout: float) -> HttpResponse:
        self.calls.append({
            "method": method, "url": url, "headers": dict(headers),
            "body": json.loads(body) if body else None,
        })
        if not self._responses:
            raise KeeperHubError("OfflineTransport ran out of scripted responses")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


@dataclass
class BackoffPolicy:
    """Retry pacing. A documented `Retry-After` is obeyed, never shortened."""

    max_attempts: int = 4
    base_seconds: float = 0.5
    max_seconds: float = 30.0
    jitter: float = 0.25

    def delay_for(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None:
            # NOT capped by max_seconds. Capping silently shortens the pacing the
            # server asked for, which is how a client earns a harder rate limit.
            # max_seconds bounds OUR guess; it does not overrule the server.
            return max(retry_after, 0.0)
        raw = min(self.base_seconds * (2 ** max(attempt - 1, 0)), self.max_seconds)
        return raw * (1.0 + random.uniform(-self.jitter, self.jitter))


def _retry_after_seconds(resp: HttpResponse) -> float | None:
    raw = resp.header("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class KeeperHubClient:
    """Builds, sends and classifies KeeperHub executions."""

    def __init__(
        self,
        credential_ref: CredentialReference | str = "env:HELD_KEEPERHUB_API_KEY",
        *,
        transport: Transport | None = None,
        base_url: str = DEFAULT_BASE_URL,
        backoff: BackoffPolicy | None = None,
        timeout: float = 30.0,
        sleep=time.sleep,
    ) -> None:
        self.credential = (
            credential_ref if isinstance(credential_ref, CredentialReference)
            else CredentialReference(credential_ref)
        )
        self.transport = transport or HttpsTransport(base_url)
        self.base_url = base_url.rstrip("/")
        self.backoff = backoff or BackoffPolicy()
        self.timeout = timeout
        self._sleep = sleep

    def __repr__(self) -> str:
        return (
            f"KeeperHubClient(ref={self.credential.ref!r}, "
            f"transport={type(self.transport).__name__}, hosted={self.transport.hosted})"
        )

    # ------------------------------------------------------------------ headers --
    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.credential.resolve()}",
            "Content-Type": "application/json",
            "User-Agent": "held/0.1 (+keeperhub-agent-economy)",
        }
        if idempotency_key:
            h[IDEMPOTENCY_HEADER] = idempotency_key
        return h

    def _public_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "User-Agent": "held/0.1 (+keeperhub-agent-economy)",
        }

    @staticmethod
    def redact(headers: Mapping[str, str]) -> dict[str, str]:
        """Headers safe to log or journal. The credential never appears."""
        return {
            k: ("Bearer <redacted>" if k.lower() == "authorization" else v)
            for k, v in headers.items()
        }

    # ---------------------------------------------------------------- preflight --
    def public_chain_catalog(self) -> SendResult:
        """GET /api/chains. UNAUTHENTICATED, and not an L10 check.

        Verified live: this endpoint answers 200 with the full catalog whether or not a
        credential is sent, so a 200 here says nothing about the organisation route.
        Exposed as its own method so nobody reaches for it as a substitute preflight.
        """
        return self._send("GET", CHAINS_PATH, None, None, authenticated=False)

    def preflight(self, probe: ContractCallRequest) -> SendResult:
        """The L10 check: a SIMULATE-mode call on the authenticated route.

        An earlier version used GET /api/chains, which is public -- it answers 200 with
        no credential at all, so the preflight would have "passed" for an invalid key and
        for no key. A dry run needs only the documented `mcp:read` scope and broadcasts
        nothing, while still proving the org credential is accepted.
        """
        return self.dry_run(probe)

    # --------------------------------------------------------------- submission --
    def dry_run(self, request: ContractCallRequest, idempotency_key: str | None = None) -> SendResult:
        """Ask KeeperHub to validate without broadcasting. Needs only `mcp:read`."""
        if not request.simulate:
            raise KeeperHubError(
                "dry_run requires a request built with simulate=True. The flag is part "
                "of the signed-over request identity, not something to flip in transit."
            )
        request.verify_encoding()
        return self._send("POST", CONTRACT_CALL_PATH, request.to_payload(), idempotency_key,
                          simulate_requested=True)

    def broadcast(self, request: ContractCallRequest, idempotency_key: str) -> SendResult:
        """Submit for real. Requires `mcp:write` and an idempotency key."""
        if request.simulate:
            raise KeeperHubError("broadcast requires simulate=False")
        if not idempotency_key:
            raise KeeperHubError(
                "broadcast requires an Idempotency-Key. Retrying an ambiguous send "
                "without one is an unprotected duplicate submission."
            )
        request.verify_encoding()
        return self._send("POST", CONTRACT_CALL_PATH, request.to_payload(), idempotency_key)

    def poll(self, execution_id: str) -> SendResult:
        if not execution_id:
            raise KeeperHubError("execution_id is required to poll")
        return self._send("GET", STATUS_PATH.format(execution_id=execution_id), None, None)

    # ------------------------------------------------------------------ sending --
    def _send(self, method: str, path: str, payload: Mapping[str, Any] | None,
              idempotency_key: str | None, *, authenticated: bool = True,
              simulate_requested: bool = False) -> SendResult:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode() if payload is not None else None
        headers = self._headers(idempotency_key) if authenticated else self._public_headers()
        last: SendResult | None = None

        for attempt in range(1, self.backoff.max_attempts + 1):
            try:
                resp = self.transport.request(
                    method, url, headers=headers, body=body, timeout=self.timeout)
            except Exception as exc:  # timeout, connection reset, DNS, TLS
                # The request may have reached KeeperHub and been acted on. Calling this
                # "not sent" is exactly how an operation gets executed twice.
                last = SendResult(
                    SendOutcome.UNKNOWN, self.transport.hosted,
                    error=f"{type(exc).__name__}: {exc}", attempts_made=attempt)
                if attempt < self.backoff.max_attempts:
                    self._sleep(self.backoff.delay_for(attempt))
                    continue
                return last

            result = self._classify(resp, attempt, simulate_requested)

            # An in-progress conflict is retryable by POLLING, not by resending; the
            # caller does that. Only rate limits and ambiguous server errors are resent,
            # and always under the identical key and body.
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                last = result
                if attempt < self.backoff.max_attempts:
                    self._sleep(self.backoff.delay_for(attempt, _retry_after_seconds(resp)))
                    continue
                return last

            return result

        return last or SendResult(SendOutcome.UNKNOWN, self.transport.hosted)

    def _classify(self, resp: HttpResponse, attempts_made: int,
                  simulate_requested: bool = False) -> SendResult:
        data = resp.json()
        hosted = self.transport.hosted
        execution_id = data.get("executionId") or data.get("id")
        tx_hash = data.get("transactionHash") or data.get("txHash")
        code = data.get("code")
        retryable = data.get("retryable")
        hint = resp.header(POLL_HINT_HEADER)
        poll_hint = None
        if hint is not None:
            try:
                poll_hint = float(hint)
            except (TypeError, ValueError):
                poll_hint = None

        def make(outcome: SendOutcome, **kw) -> SendResult:
            return SendResult(
                outcome, hosted, resp.status_code, execution_id, tx_hash,
                error_code=code, retryable=retryable, poll_hint_seconds=poll_hint,
                raw=data, attempts_made=attempts_made, **kw)

        if 200 <= resp.status_code < 300:
            # A simulation is NOT an execution, and the classification must not depend on
            # guessing the response shape.
            #
            # The previous version looked for `simulated: true` / `simulation` -- fields I
            # invented, and then tested against my own invention. The DOCUMENTED successful
            # simulation is `{"success": true, "status": "simulated", "wouldRevert": false}`,
            # which that check missed entirely and classified as ACCEPTED: a dry run
            # recorded as an economic execution.
            #
            # The primary signal is now the REQUEST mode, which Held always knows, with the
            # documented status as confirmation. A response that disagrees with the mode we
            # asked for is a contradiction, not something to resolve silently.
            status_text = str(data.get("status") or "").lower()
            looks_simulated = (
                status_text == STATUS_SIMULATED
                or data.get("simulated") is True
                or data.get("simulation") is not None
            )
            if simulate_requested or looks_simulated:
                if simulate_requested and not looks_simulated and status_text:
                    return make(
                        SendOutcome.UNKNOWN,
                        error=(
                            f"asked to simulate but the response reports status "
                            f"{status_text!r}. Refusing to record this as either a "
                            "simulation or an execution."))
                if looks_simulated and not simulate_requested:
                    return make(
                        SendOutcome.UNKNOWN,
                        error=("a broadcast returned a SIMULATED response; the request "
                               "mode and the response disagree, so the on-chain outcome "
                               "is unknown."))
                result = make(SendOutcome.SIMULATED)
                if data.get("wouldRevert") is True:
                    # A simulation that predicts a revert is a successful simulation
                    # reporting a failing call. It must never look like a green light.
                    return make(SendOutcome.REJECTED,
                                error=("simulation reports wouldRevert=true: the call "
                                       "would fail on chain. "
                                       f"{data.get('revertReason') or data.get('message') or ''}"
                                       ).strip())
                return result
            return make(SendOutcome.ACCEPTED)

        if resp.status_code == 409:
            if code == CODE_IDEMPOTENCY_CONFLICT:
                # Same key, DIFFERENT body. Held derives both deterministically, so this
                # says one of them is not deterministic. Retrying cannot fix it.
                return make(
                    SendOutcome.IDEMPOTENCY_CONFLICT,
                    error=(
                        "idempotency_conflict: this key was used with a different body. "
                        "Held derives the key from (operation, attempt) and the body from "
                        "the admitted action, so this indicates a non-deterministic "
                        "request, not a duplicate to poll. "
                        f"{data.get('message') or ''}".strip()
                    ))
            if code == CODE_IDEMPOTENCY_IN_PROGRESS:
                return make(SendOutcome.IN_PROGRESS,
                            error=data.get("message") or "already in flight under this key")
            # A 409 with no documented code is not something to guess about.
            return make(SendOutcome.UNKNOWN,
                        error=f"unrecognised 409 (code={code!r}): {data.get('message')}")

        if resp.status_code == 401:
            return make(SendOutcome.REJECTED,
                        error=f"L10: the organisation credential was rejected (401). "
                              f"{data.get('message') or ''}".strip())

        if resp.status_code == 403:
            # Documented as insufficient scope OR spending cap exceeded. These need
            # different operator responses, so the message keeps them apart.
            return make(SendOutcome.REJECTED,
                        error=(
                            "403: insufficient scope or spending cap exceeded. Broadcast "
                            "needs mcp:write; mcp:read permits dry runs only. "
                            f"{data.get('message') or ''}".strip()))

        if resp.status_code in _DEFINITIVE_REJECTION:
            return make(SendOutcome.REJECTED,
                        error=data.get("message") or data.get("error")
                        or resp.body[:200].decode(errors="replace"))

        # Anything else -- including every 5xx -- leaves the outcome genuinely unknown.
        return make(SendOutcome.UNKNOWN,
                    error=data.get("message") or data.get("error") or f"HTTP {resp.status_code}")
