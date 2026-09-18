#!/usr/bin/env python3
"""M1 pre-broadcast gate: everything that must hold before the one irreversible send.

`docs/submission/M1-IRREVERSIBLE-PREFLIGHT.md` has exactly one irreversible row — step 12,
the `executeSupply` broadcast. Every other step is reversible or costs nothing. This file
is the machine-checkable form of "may step 12 proceed", and it answers NO by default.

## Fail-closed, and what that means here

An unevaluable check is NOT a pass. A missing controller address, an unreachable RPC, an
unset credential and a wrong scope all produce a non-zero exit, and each is reported as
BLOCKED or FAIL separately so the operator can tell "we could not look" from "we looked
and it was wrong". A gate that degraded an unreadable input to a pass would be worse than
no gate, because it would be consulted.

## It cannot broadcast, structurally

`NoBroadcastTransport` wraps the real transport and refuses, at the wire boundary, any
POST to the contract-call path that is not `simulate: true`, and any request carrying an
`Idempotency-Key` (a dry run needs none; a broadcast requires one). `NoBroadcastClient`
additionally removes `broadcast()` from the type. Neither is a promise in a comment —
this file has no code path that can submit a real execution, and check `no-broadcast`
records what the transport actually saw.

## What it establishes, and what it does not

It establishes that the prepared request is the Held execution it claims to be, aimed at
the declared controller on Base, that the configured credential really can broadcast, and
that the executor Held expects is the executor the controller will accept.

It does NOT establish that the call succeeds. That needs the authenticated SIMULATE
preflight (step 10), whose `wouldRevert` and `from` are the first real L10 and P19
evidence. This gate is a precondition for that, not a substitute.

EVIDENCE GRADE: whatever its weakest evaluated input carries. The credential check is
AUTHENTICATED HOSTED; the controller readback is PUBLIC CHAIN when finalized. The gate
never promotes a grade and never files a result the transport did not produce.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("adapter", "packages/core", "packages/handover"):
    sys.path.insert(0, os.path.join(ROOT, p))

from held_adapter.execution.controller_abi import (  # noqa: E402
    EXECUTE_SUPPLY,
    EXECUTE_WITHDRAW,
    ControllerAbiError,
    decode_and_match,
)
from held_adapter.execution.keeperhub import (  # noqa: E402
    BROADCAST_SCOPES,
    CONTRACT_CALL_PATH,
    DEFAULT_BASE_URL,
    IDEMPOTENCY_HEADER,
    CredentialReference,
    HttpsTransport,
    KeeperHubClient,
    KeeperHubError,
    L10Blocked,
)

#: M1 is a Base mainnet proof. Not a parameter — a different chain is a different claim.
EXPECTED_CHAIN_ID = 8453

#: KeeperHub's managed (Turnkey) signer, supplied by the owner on 2026-09-18 and recorded
#: in `docs/submission/M1-IRREVERSIBLE-PREFLIGHT.md`. This is the address that pays for and
#: sends the one broadcast, and the address the controller must already hold as `executor`.
EXPECTED_EXECUTOR = "0x24192B75e297dC1c7a42DcB8C04227818E78acd0"

#: The documented contract-call body. An extra or missing key means the payload was not
#: built by `ContractCallRequest.to_payload()`, and nothing else may be sent as Held's.
PAYLOAD_KEYS = {"contractAddress", "chainId", "functionName", "functionArgs", "abi",
                "value", "simulate"}

SUPPORTED_FUNCTIONS = (EXECUTE_SUPPLY, EXECUTE_WITHDRAW)

OUT = os.path.join(ROOT, "evidence", "M1", "prebroadcast-gate.json")

PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"


class GateRefusal(Exception):
    """The gate itself tried to do something it is not allowed to do."""


# ------------------------------------------------------------------ no broadcast --
class NoBroadcastTransport:
    """A real transport that physically cannot carry a broadcast.

    The refusal is at the wire boundary rather than in the caller, so it holds however
    the client is driven — including by a future edit to this file that forgets.
    """

    def __init__(self, inner) -> None:
        self.inner = inner
        self.observed: list[dict[str, object]] = []
        self.refusals: list[str] = []

    @property
    def hosted(self) -> bool:
        return self.inner.hosted

    def request(self, method, url, *, headers, body, timeout):
        self._refuse_if_broadcasting(method, url, headers, body)
        self.observed.append({"method": method, "path": _path_of(url),
                              "carried_idempotency_key": IDEMPOTENCY_HEADER in headers})
        return self.inner.request(method, url, headers=headers, body=body, timeout=timeout)

    def _refuse_if_broadcasting(self, method, url, headers, body) -> None:
        if IDEMPOTENCY_HEADER in headers:
            self._refuse(f"a request carrying {IDEMPOTENCY_HEADER} is a broadcast; this "
                         "gate never sends one")
        if not (method.upper() == "POST" and _path_of(url) == CONTRACT_CALL_PATH):
            return
        try:
            payload = json.loads(body or b"{}")
        except (ValueError, TypeError):
            self._refuse("an unparseable contract-call body cannot be shown to be a "
                         "simulation, so it is refused")
            return
        if payload.get("simulate") is not True:
            self._refuse(f"simulate={payload.get('simulate')!r}: a contract call that is "
                         "not strictly simulate=true would broadcast")

    def _refuse(self, why: str) -> None:
        self.refusals.append(why)
        raise GateRefusal(why)


class NoBroadcastClient(KeeperHubClient):
    """`broadcast` removed from the type, so the capability is absent, not merely unused."""

    def broadcast(self, request, idempotency_key):  # noqa: ARG002
        raise GateRefusal(
            "this client cannot broadcast. The pre-broadcast gate decides WHETHER the "
            "broadcast may happen; it is never the thing that performs it.")


def _path_of(url: str) -> str:
    rest = url.split("://", 1)[-1]
    return "/" + rest.split("/", 1)[1] if "/" in rest else "/"


# ------------------------------------------------------------------------ report --
class Report:
    def __init__(self, quiet: bool = False) -> None:
        self.checks: list[dict[str, object]] = []
        self.quiet = quiet          # the regression suite drives the checks directly

    def record(self, name: str, verdict: str, detail: str, **extra) -> str:
        self.checks.append({"check": name, "verdict": verdict, "detail": detail, **extra})
        if not self.quiet:
            print(f"  [{verdict:>7}] {name} — {detail}")
        return verdict

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c["verdict"] == PASS for c in self.checks)

    def counts(self) -> dict[str, int]:
        out = {PASS: 0, FAIL: 0, BLOCKED: 0}
        for c in self.checks:
            out[str(c["verdict"])] += 1
        return out


# ------------------------------------------------------------------ the request --
def load_request(args) -> tuple[dict | None, str | None, str | None]:
    """Return (payload, calldata, why_not).

    The authoritative artifact is the journal row: `claim_for_dispatch` persists the exact
    body and calldata in the same transaction that marks the operation DISPATCHED, so the
    thing checked here is the thing that would be resent, not a reconstruction of it.
    """
    if args.journal:
        if not args.attempt:
            return None, None, "--journal needs --attempt"
        try:
            from held_core.journal import Journal

            db = Journal(args.journal)
            row = db._db.execute(  # noqa: SLF001 - read-only accessor, as the console uses
                "SELECT request_body, calldata, kind FROM attempts WHERE attempt_id=?",
                (args.attempt,)).fetchone()
        except Exception as exc:  # noqa: BLE001
            return None, None, f"the journal could not be read: {exc}"
        if row is None:
            return None, None, f"no attempt {args.attempt} in {args.journal}"
        if row["kind"] != "BROADCAST":
            return None, None, (f"attempt {args.attempt} is kind={row['kind']}; only a "
                                "BROADCAST attempt is a pre-broadcast subject")
        try:
            return json.loads(row["request_body"]), row["calldata"], None
        except ValueError as exc:
            return None, None, f"the persisted request body is not JSON: {exc}"

    if not args.request:
        return None, None, ("no prepared request. Pass --journal PATH --attempt ID (the "
                            "authoritative source) or --request FILE")
    try:
        with open(args.request) as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, None, f"{args.request}: {exc}"
    payload = doc.get("request_body", doc) if isinstance(doc, dict) else None
    if not isinstance(payload, dict):
        return None, None, f"{args.request}: no contract-call body found"
    calldata = doc.get("calldata") if isinstance(doc, dict) else None
    return payload, calldata, None


# ------------------------------------------------------------------------ checks --
def check_payload(rep: Report, payload: dict | None, calldata: str | None,
                  why_not: str | None, controller: str | None) -> None:
    if payload is None:
        for name in ("request-present", "payload-schema", "chain-8453", "controller-target",
                     "function-supported", "calldata-reencodes", "value-zero",
                     "payload-is-a-broadcast"):
            rep.record(name, BLOCKED, why_not or "no request to inspect")
        return
    rep.record("request-present", PASS, "the prepared contract-call body was read")

    keys = set(payload)
    rep.record("payload-schema", PASS if keys == PAYLOAD_KEYS else FAIL,
               "exactly the documented contract-call body"
               if keys == PAYLOAD_KEYS else
               f"unexpected {sorted(keys - PAYLOAD_KEYS)}, missing {sorted(PAYLOAD_KEYS - keys)}")

    chain = payload.get("chainId")
    rep.record("chain-8453", PASS if chain == EXPECTED_CHAIN_ID else FAIL,
               f"chainId={chain!r}" + ("" if chain == EXPECTED_CHAIN_ID
                                       else f", expected {EXPECTED_CHAIN_ID} (Base mainnet)"),
               observed=chain, expected=EXPECTED_CHAIN_ID)

    target = payload.get("contractAddress")
    if not controller:
        rep.record("controller-target", BLOCKED,
                   "$HELD_M1_CONTROLLER is unset, so the target cannot be compared to the "
                   "declared installation. An unchecked target is an unchecked call",
                   observed=target)
    else:
        same = isinstance(target, str) and target.lower() == controller.lower()
        rep.record("controller-target", PASS if same else FAIL,
                   f"target {target} is the declared controller" if same
                   else f"target {target} is NOT the declared controller {controller}",
                   observed=target, expected=controller)

    fn = payload.get("functionName")
    rep.record("function-supported", PASS if fn in SUPPORTED_FUNCTIONS else FAIL,
               f"functionName={fn!r}" + ("" if fn in SUPPORTED_FUNCTIONS
                                         else f", expected one of {list(SUPPORTED_FUNCTIONS)}"),
               observed=fn)

    if not calldata:
        rep.record("calldata-reencodes", BLOCKED,
                   "no expected calldata alongside the request, so the server-side encoding "
                   "cannot be pinned to bytes the runner signed over")
    else:
        try:
            args = json.loads(payload.get("functionArgs") or "null")
            decode_and_match(calldata, fn, args)
        except (ControllerAbiError, KeeperHubError, ValueError, TypeError) as exc:
            rep.record("calldata-reencodes", FAIL,
                       f"the arguments do not re-encode to the signed calldata: {exc}")
        else:
            rep.record("calldata-reencodes", PASS,
                       "functionArgs re-encode to the expected calldata, byte for byte")

    value = payload.get("value")
    rep.record("value-zero", PASS if value == "0" else FAIL,
               f"value={value!r}" + ("" if value == "0"
                                     else " — the controller entry points are non-payable"))

    sim = payload.get("simulate")
    rep.record("payload-is-a-broadcast", PASS if sim is False else FAIL,
               "simulate=false: this body is the real submission, which is what a "
               "pre-broadcast gate must be judging" if sim is False
               else f"simulate={sim!r}: a simulation is not the subject of this gate")


def check_executor(rep: Report, controller: str | None, rpc: str | None) -> None:
    declared = os.environ.get("HELD_M1_EXECUTOR", EXPECTED_EXECUTOR)
    matches = declared.lower() == EXPECTED_EXECUTOR.lower()
    rep.record("executor-declared", PASS if matches else FAIL,
               f"{EXPECTED_EXECUTOR} — KeeperHub's managed signer" if matches
               else f"$HELD_M1_EXECUTOR is {declared}, not the recorded {EXPECTED_EXECUTOR}",
               expected=EXPECTED_EXECUTOR, observed=declared)

    if not controller or not rpc:
        rep.record("executor-on-chain", BLOCKED,
                   "needs $HELD_M1_CONTROLLER and $HELD_BASE_RPC. Until the controller is "
                   "deployed and activated there is no on-chain executor to compare, and "
                   "the declared value stands unconfirmed")
        return
    try:
        from held_handover.readback import read_controller_state
        from held_handover.sources import CastControllerSource

        reading = read_controller_state(
            CastControllerSource(rpc), controller=controller,
            expected_chain_id=EXPECTED_CHAIN_ID, adapter_dispatching=False)
    except Exception as exc:  # noqa: BLE001
        rep.record("executor-on-chain", BLOCKED,
                   f"the controller could not be read: {type(exc).__name__}: {exc}")
        return

    on_chain = reading.executor
    if not on_chain:
        rep.record("executor-on-chain", BLOCKED,
                   "the controller did not answer executor(); the reading is incomplete")
        return
    same = on_chain.lower() == EXPECTED_EXECUTOR.lower()
    rep.record("executor-on-chain", PASS if same else FAIL,
               f"controller executor() = {on_chain}" + ("" if same else
               f", which is NOT the expected {EXPECTED_EXECUTOR}. KeeperHub would send from "
               "a wallet the controller refuses"),
               observed=on_chain, expected=EXPECTED_EXECUTOR,
               active=reading.active, epoch=reading.epoch)


def check_credential(rep: Report, base_url: str) -> NoBroadcastTransport | None:
    """The live scope check. Read-only; it lists keys and broadcasts nothing."""
    transport = NoBroadcastTransport(HttpsTransport(base_url))
    try:
        client = NoBroadcastClient(
            CredentialReference("env:HELD_KEEPERHUB_API_KEY"),
            transport=transport, base_url=base_url)
        check = client.organisation_keys()
    except L10Blocked as exc:
        rep.record("credential-write-scope", BLOCKED, str(exc))
        return transport
    except GateRefusal:
        raise
    except Exception as exc:  # noqa: BLE001
        rep.record("credential-write-scope", BLOCKED,
                   f"the organisation route could not be reached: {type(exc).__name__}: {exc}")
        return transport

    if not check.hosted:
        rep.record("credential-write-scope", BLOCKED,
                   "the credential check did not come from a hosted transport, so it says "
                   "nothing about the real organisation route")
        return transport
    if not check.valid:
        rep.record("credential-write-scope", FAIL,
                   f"the credential is not established as valid "
                   f"(status={check.status_code}, matched={check.matched})",
                   **check.to_evidence())
        return transport
    if not check.can_broadcast:
        rep.record("credential-write-scope", FAIL,
                   f"the configured credential carries {list(check.scopes)}. Broadcasting "
                   f"requires one of {list(BROADCAST_SCOPES)}. This is the deliberate "
                   "read-only posture, not a fault — the gate says NO because the key "
                   "genuinely cannot send",
                   **check.to_evidence())
        return transport
    rep.record("credential-write-scope", PASS,
               f"the configured credential carries {list(check.scopes)} and can broadcast",
               **check.to_evidence())
    return transport


def check_no_broadcast(rep: Report, transport: NoBroadcastTransport | None) -> None:
    if transport is None:
        rep.record("no-broadcast", BLOCKED, "no transport was constructed")
        return
    broadcasts = [r for r in transport.observed
                  if r["path"] == CONTRACT_CALL_PATH or r["carried_idempotency_key"]]
    rep.record("no-broadcast", PASS if not broadcasts else FAIL,
               f"{len(transport.observed)} request(s) left this gate, none of them a "
               "contract call and none carrying an idempotency key" if not broadcasts
               else f"{len(broadcasts)} broadcast-shaped request(s) escaped",
               requests=transport.observed, refusals=transport.refusals)


# -------------------------------------------------------------------------- main --
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--journal", help="durable journal holding the prepared attempt")
    ap.add_argument("--attempt", help="attempt id of the BROADCAST attempt to judge")
    ap.add_argument("--request", help="JSON file with the prepared body (and calldata)")
    args = ap.parse_args()

    controller = os.environ.get("HELD_M1_CONTROLLER") or None
    rpc = os.environ.get("HELD_BASE_RPC") or None
    base_url = os.environ.get("HELD_KEEPERHUB_BASE_URL", DEFAULT_BASE_URL)

    print("HELD — M1 pre-broadcast gate")
    print("=" * 78)
    print("Answers one question: may the single irreversible executeSupply proceed?")
    print("An unevaluable check is not a pass.\n")

    rep = Report()
    payload, calldata, why_not = load_request(args)

    print("The prepared request")
    check_payload(rep, payload, calldata, why_not, controller)
    print("\nThe executor")
    check_executor(rep, controller, rpc)
    print("\nThe credential")
    transport = check_credential(rep, base_url)
    print("\nThis gate's own conduct")
    check_no_broadcast(rep, transport)

    counts = rep.counts()
    record = {
        "schema": "held.m1-prebroadcast-gate.v1",
        "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "question": "May the single irreversible executeSupply broadcast proceed?",
        "verdict": "PROCEED" if rep.passed else "DO NOT BROADCAST",
        "expected": {"chain_id": EXPECTED_CHAIN_ID, "executor": EXPECTED_EXECUTOR,
                     "broadcast_scopes": list(BROADCAST_SCOPES),
                     "credential_ref": "env:HELD_KEEPERHUB_API_KEY"},
        "counts": counts,
        "checks": rep.checks,
        "boundaries": [
            "A PASS here is permission to attempt, not a prediction of success. Whether "
            "the call reverts is answered by the authenticated SIMULATE preflight "
            "(M1-IRREVERSIBLE-PREFLIGHT step 10), which this gate does not perform.",
            "This gate has no code path that can broadcast: NoBroadcastTransport refuses a "
            "non-simulate contract call and any request carrying an idempotency key, and "
            "NoBroadcastClient does not implement broadcast().",
            "BLOCKED is not a soft pass. The exit status treats it exactly as a failure.",
        ],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(record, fh, indent=1)
        fh.write("\n")

    print("\n" + "=" * 78)
    print(f"  PASS {counts[PASS]}   FAIL {counts[FAIL]}   BLOCKED {counts[BLOCKED]}")
    print(f"  verdict: {record['verdict']}")
    print(f"  written: {os.path.relpath(OUT, ROOT)}")
    if not rep.passed:
        print("\nThe gate refuses. Nothing was sent, and nothing may be broadcast while any")
        print("check above is FAIL or BLOCKED.")
        return 1
    print("\nEvery check passed. This is permission to run the authenticated SIMULATE")
    print("preflight and then, on explicit owner authorization, step 12. It is not itself")
    print("that authorization.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateRefusal as exc:
        print(f"\nGATE REFUSAL — the gate attempted something it may not do: {exc}",
              file=sys.stderr)
        raise SystemExit(2) from None
