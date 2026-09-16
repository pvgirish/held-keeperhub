"""The KeeperHub execution client: the outer caller/payer route.

Held signs an authorization envelope and then needs somebody to actually land the
controller call on chain. That is KeeperHub's generic
`POST /api/execute/contract-call` route (route-evidence L4: the Morpho plugin is not
used). This module builds that request, sends it, and classifies what came back.

## L10 is a gate, not a setting

`L10-authenticated-caller-payer` is BLOCKED-UNKNOWN: whether the authenticated
organisation caller/payer accepts Held's outer call has never been tested, because it
needs an org API key this project does not have. The public chain catalog (L3) does not
prove it.

So this module is built so that L10 cannot be quietly satisfied by a fixture:

  * There is exactly ONE transport that can produce a hosted result, `HttpsTransport`,
    and it talks to a real https:// origin with a real credential.
  * Every result carries `hosted`, set from the transport that produced it, not from an
    argument. `OfflineTransport` exists for exercising request construction and response
    parsing and stamps `hosted=False` on everything it touches.
  * `assert_hosted_evidence()` refuses a non-hosted result, so a local fixture cannot be
    filed as evidence that the hosted route works.

A local test of this module establishes that Held forms the right request and reads the
answer correctly. It does not establish L10 and must never be described as doing so.

## Why the outcome vocabulary is what it is

The dangerous failure is not "the send failed". It is "the send may or may not have
happened". A timeout, a dropped connection or an ambiguous 5xx all leave an operation
whose on-chain outcome is unknown, and treating that as "not sent" is how the same
operation gets executed twice. `SendOutcome.UNKNOWN` exists so that case has a name and
cannot collapse into `REJECTED`.

A 409 is likewise not a failure: it means this execution key is already in flight, which
is the idempotency mechanism working. It returns `IN_PROGRESS` with the existing
execution id so the caller polls rather than resends.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol

from eth_utils import keccak

from held_core.canonical import hex32, normalize_address

DEFAULT_BASE_URL = "https://app.keeperhub.com"
CONTRACT_CALL_PATH = "/api/execute/contract-call"
CHAINS_PATH = "/api/chains"
EXECUTION_PATH = "/api/execute/{execution_id}"

# The catalog exposes an internal string `id` per chain (e.g. "9wr4m6zv2dwflb1trbzsx")
# alongside the numeric chainId. Which of the two the contract-call route expects is NOT
# established -- that route needs an org credential to call. Held sends `chainId`, and if
# the authenticated route turns out to want the internal id this is the field to change.
# Recorded rather than guessed silently.
CHAIN_ID_FIELD_UNVERIFIED = True

# Domain tag so an execution key can never collide with an operation id or a payload
# hash if one is ever pasted into the wrong field.
EXECUTION_KEY_DOMAIN = b"held.keeperhub.execution-key.v1"

_KEY_SHAPED = re.compile(r"(?:^|[^0-9a-zA-Z])(?:0x)?[0-9a-fA-F]{40,}(?:$|[^0-9a-zA-Z])")


class KeeperHubError(Exception):
    """A KeeperHub interaction failed in a way the caller must handle."""


class L10Blocked(KeeperHubError):
    """The authenticated organisation route is not available.

    Named after the route-evidence layer on purpose: this is the open gate, and it is
    never satisfied by a local fixture.
    """


class CredentialError(KeeperHubError):
    """The credential reference is malformed, key-shaped, or points at nothing."""


class ExecutionInProgress(KeeperHubError):
    """This execution key is already in flight. Poll; do not resend."""

    def __init__(self, execution_id: str | None, message: str) -> None:
        super().__init__(message)
        self.execution_id = execution_id


class SendOutcome(str, Enum):
    """What is known about a submission. `UNKNOWN` is the whole point."""

    ACCEPTED = "ACCEPTED"        # KeeperHub owns it; an execution id exists
    IN_PROGRESS = "IN_PROGRESS"  # already in flight under this execution key
    REJECTED = "REJECTED"        # definitively refused; nothing was broadcast
    UNKNOWN = "UNKNOWN"          # may or may not have been broadcast. NEVER "not sent".


# Definitively-refused statuses. Anything not listed is treated as UNKNOWN, because a
# status we do not recognise is not evidence that nothing happened.
_DEFINITIVE_REJECTION = frozenset({400, 401, 403, 404, 422})


@dataclass(frozen=True)
class CredentialReference:
    """Where the org API key lives. Never what it is. Mirrors the signer's discipline."""

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
            raise CredentialError(
                f"credential reference must be 'env:NAME'; got {self.ref!r}"
            )

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
    """The idempotency key KeeperHub dedupes on.

    Bound to the ATTEMPT, not just the operation. Retrying the same attempt after a
    timeout must reuse the key so KeeperHub collapses it; a deliberately new attempt
    (after a definitive rejection, or under a new epoch) is a different send and gets a
    different key. Keying on the operation alone would make a legitimate replacement
    attempt indistinguishable from a duplicate.
    """
    if isinstance(operation_id, str):
        operation_id = bytes.fromhex(operation_id[2:] if operation_id.startswith("0x") else operation_id)
    if not isinstance(operation_id, bytes) or len(operation_id) != 32:
        raise KeeperHubError("operation_id: expected 32 bytes")
    if not attempt_id or not isinstance(attempt_id, str):
        raise KeeperHubError("attempt_id: expected a non-empty string")
    return hex32(keccak(EXECUTION_KEY_DOMAIN + operation_id + attempt_id.encode()))


@dataclass(frozen=True)
class ContractCallRequest:
    """One outer call for KeeperHub to make on Held's behalf."""

    chain_id: int
    to: str
    calldata: str
    execution_key: str
    operation_id: str
    attempt_id: str
    value: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "to", normalize_address(self.to, "to"))
        if not isinstance(self.calldata, str) or not self.calldata.startswith("0x"):
            raise KeeperHubError("calldata must be a 0x-prefixed hex string")
        if len(self.calldata) % 2 or len(self.calldata) < 10:
            raise KeeperHubError("calldata is not a whole number of bytes with a selector")
        if self.value != 0:
            # Held's controller entry points are non-payable, so a non-zero value is a
            # construction bug, and paying ETH is not something to discover in a receipt.
            raise KeeperHubError("value must be 0: the controller entry points are non-payable")

    def to_payload(self) -> dict[str, Any]:
        return {
            "chainId": self.chain_id,
            "to": self.to,
            "data": self.calldata,
            "value": str(self.value),
            "idempotencyKey": self.execution_key,
            # Held's own correlation fields, echoed back on polling so a receipt can be
            # tied to the journal row without trusting ordering.
            "metadata": {
                "heldOperationId": self.operation_id,
                "heldAttemptId": self.attempt_id,
            },
        }


@dataclass(frozen=True)
class SendResult:
    outcome: SendOutcome
    hosted: bool                 # set by the transport, never by an argument
    status_code: int | None = None
    execution_id: str | None = None
    tx_hash: str | None = None
    error: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)
    attempts_made: int = 1

    def assert_hosted_evidence(self) -> "SendResult":
        """Refuse to let a local fixture stand in for the hosted route."""
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


class Transport(Protocol):
    hosted: bool

    def request(
        self, method: str, url: str, *, headers: Mapping[str, str], body: bytes | None, timeout: float
    ) -> HttpResponse: ...


class HttpsTransport:
    """The ONLY transport that can produce hosted evidence.

    Requires an https:// origin. Plain http would put the org credential on the wire in
    clear, and a http://localhost stand-in is exactly the shape of thing that would let
    a local fixture masquerade as the hosted route.
    """

    hosted = True

    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        if not base_url.startswith("https://"):
            raise KeeperHubError(
                f"hosted transport requires an https:// origin; got {base_url!r}. A "
                "non-https origin cannot carry an org credential and cannot be hosted "
                "evidence."
            )
        self.base_url = base_url.rstrip("/")

    def request(
        self, method: str, url: str, *, headers: Mapping[str, str], body: bytes | None, timeout: float
    ) -> HttpResponse:
        import requests

        resp = requests.request(
            method, url, headers=dict(headers), data=body, timeout=timeout
        )
        return HttpResponse(resp.status_code, resp.content, dict(resp.headers))


class OfflineTransport:
    """Canned responses for exercising construction and parsing. NEVER hosted.

    Everything it produces is stamped `hosted=False`, so `assert_hosted_evidence()`
    rejects it. It exists so the retry, conflict and classification logic can be tested
    without inventing a KeeperHub that answers the way we hope.
    """

    hosted = False

    def __init__(self, responses: list[HttpResponse | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(
        self, method: str, url: str, *, headers: Mapping[str, str], body: bytes | None, timeout: float
    ) -> HttpResponse:
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
    """Retry pacing. `Retry-After` from the server always wins over our own guess."""

    max_attempts: int = 4
    base_seconds: float = 0.5
    max_seconds: float = 30.0
    jitter: float = 0.25

    def delay_for(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return min(max(retry_after, 0.0), self.max_seconds)
        raw = min(self.base_seconds * (2 ** max(attempt - 1, 0)), self.max_seconds)
        return raw * (1.0 + random.uniform(-self.jitter, self.jitter))


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    for name, value in headers.items():
        if name.lower() == "retry-after":
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


class KeeperHubClient:
    """Builds, sends and classifies KeeperHub executions.

    The client never decides *whether* to send. That belongs to the journal, which must
    have recorded the attempt before any network I/O so a crash mid-send leaves an
    outcome-unknown row rather than a silent gap.
    """

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
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.credential.resolve()}",
            "Content-Type": "application/json",
            "User-Agent": "held/0.1 (+keeperhub-agent-economy)",
        }

    def _public_headers(self) -> dict[str, str]:
        """Headers for an explicitly unauthenticated endpoint. Carries no credential."""
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
        Route-evidence L3 already recorded exactly this boundary. It is exposed as its
        own method so nobody reaches for it as a substitute for `preflight`.
        """
        return self._send("GET", CHAINS_PATH, None, authenticated=False)

    def preflight(self, probe: ContractCallRequest) -> SendResult:
        """The L10 check: does the AUTHENTICATED organisation route accept Held's call?

        This must hit an endpoint that actually requires the credential. An earlier
        version of this method used GET /api/chains, which is public -- it returns 200
        with no credential at all, so "preflight passed" would have been true of an
        invalid key and of no key. That is precisely the vacuous check L10 is supposed
        to be protected from.

        So the preflight is a SIMULATE-mode contract call: same route, same auth, and
        no broadcast. A 401/403 is the real negative answer; a 2xx is the first genuine
        evidence about L10 this project would have.
        """
        return self.dry_run(probe)

    # --------------------------------------------------------------- submission --
    def dry_run(self, request: ContractCallRequest) -> SendResult:
        """Ask KeeperHub to validate without broadcasting.

        A dry run that succeeds is NOT an execution: it returns no tx hash and consumes
        no operation. The flag is sent explicitly rather than by omitting something.
        """
        payload = dict(request.to_payload())
        payload["simulate"] = True
        return self._send("POST", CONTRACT_CALL_PATH, payload)

    def broadcast(self, request: ContractCallRequest) -> SendResult:
        """Submit for real. The caller must have journaled the attempt first."""
        payload = dict(request.to_payload())
        payload["simulate"] = False
        return self._send("POST", CONTRACT_CALL_PATH, payload)

    def poll(self, execution_id: str) -> SendResult:
        if not execution_id:
            raise KeeperHubError("execution_id is required to poll")
        return self._send("GET", EXECUTION_PATH.format(execution_id=execution_id), None)

    # ------------------------------------------------------------------ sending --
    def _send(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None,
        *,
        authenticated: bool = True,
    ) -> SendResult:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode() if payload is not None else None
        # Resolving the credential is what raises L10Blocked when there is none, so an
        # authenticated call can never proceed credential-less.
        headers = self._headers() if authenticated else self._public_headers()
        last: SendResult | None = None

        for attempt in range(1, self.backoff.max_attempts + 1):
            try:
                resp = self.transport.request(
                    method, url, headers=headers, body=body, timeout=self.timeout
                )
            except Exception as exc:  # timeout, connection reset, DNS, TLS
                # The request may have reached KeeperHub and been acted on. Calling this
                # "not sent" is exactly how an operation gets executed twice.
                last = SendResult(
                    SendOutcome.UNKNOWN, self.transport.hosted,
                    error=f"{type(exc).__name__}: {exc}", attempts_made=attempt,
                )
                if attempt < self.backoff.max_attempts:
                    self._sleep(self.backoff.delay_for(attempt))
                    continue
                return last

            result = self._classify(resp, attempt)

            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                last = result
                if attempt < self.backoff.max_attempts:
                    self._sleep(
                        self.backoff.delay_for(attempt, _retry_after_seconds(resp.headers))
                    )
                    continue
                return last

            return result

        return last or SendResult(SendOutcome.UNKNOWN, self.transport.hosted)

    def _classify(self, resp: HttpResponse, attempts_made: int) -> SendResult:
        data = resp.json()
        hosted = self.transport.hosted
        execution_id = data.get("executionId") or data.get("id")
        tx_hash = data.get("transactionHash") or data.get("txHash")

        if 200 <= resp.status_code < 300:
            return SendResult(
                SendOutcome.ACCEPTED, hosted, resp.status_code, execution_id, tx_hash,
                raw=data, attempts_made=attempts_made,
            )

        if resp.status_code == 409:
            # The idempotency key is already in flight. This is the dedupe working, not
            # a failure: resending would be the mistake.
            return SendResult(
                SendOutcome.IN_PROGRESS, hosted, 409, execution_id, tx_hash,
                error=data.get("message") or data.get("error"),
                raw=data, attempts_made=attempts_made,
            )

        if resp.status_code == 401 or resp.status_code == 403:
            return SendResult(
                SendOutcome.REJECTED, hosted, resp.status_code,
                error=(
                    f"L10: the organisation credential was refused ({resp.status_code}). "
                    f"{data.get('message') or data.get('error') or ''}".strip()
                ),
                raw=data, attempts_made=attempts_made,
            )

        if resp.status_code in _DEFINITIVE_REJECTION:
            return SendResult(
                SendOutcome.REJECTED, hosted, resp.status_code,
                error=data.get("message") or data.get("error") or resp.body[:200].decode(errors="replace"),
                raw=data, attempts_made=attempts_made,
            )

        # Anything else -- including every 5xx -- leaves the outcome genuinely unknown.
        return SendResult(
            SendOutcome.UNKNOWN, hosted, resp.status_code, execution_id, tx_hash,
            error=data.get("message") or data.get("error") or f"HTTP {resp.status_code}",
            raw=data, attempts_made=attempts_made,
        )
