"""Does the M1 pre-broadcast gate actually refuse, and can it broadcast by accident?

METHOD. The gate's own components, driven directly. Two properties matter, and they are
both negative:

  1. **It cannot broadcast.** Not "it does not" — it must have no code path that can. The
     transport is driven with broadcast-shaped requests and must raise on every one.
  2. **An unevaluable check is not a pass.** A missing input, an unreadable source and a
     non-hosted credential answer must all produce BLOCKED, and BLOCKED must be treated by
     the exit status exactly as a failure.

The positive path is covered too, because a gate that refused everything would also pass
property 2 while being useless: a correctly prepared Base-mainnet `executeSupply` body has
to produce PASS on every payload check.

Nothing here touches the network. The one credential test substitutes an offline transport
precisely to prove that a non-hosted answer is refused rather than filed.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in ("adapter", "packages/core", "script"):
    sys.path.insert(0, os.path.join(ROOT, p))

import m1_prebroadcast_gate as gate  # noqa: E402
from held_adapter.execution.controller_abi import encode_call  # noqa: E402
from held_adapter.execution.keeperhub import (  # noqa: E402
    CONTRACT_CALL_PATH,
    IDEMPOTENCY_HEADER,
    KEYS_PATH,
    HttpResponse,
    OfflineTransport,
)

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

BASE = "https://app.keeperhub.com"
CONTROLLER = "0x3875311Cc0D4017A033893A9653a0725378acA1c"
SAFE = "0x08deEDA0Ba1eb4B6B4b5cc4DD0c4BC689EA37180"
RUNNER = "0x90F79bf6EB2c4f870365E785982E1f101E93b906"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH = "0x4200000000000000000000000000000000000006"


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
    except exc_type as exc:
        return str(exc)
    raise AssertionError(f"expected {exc_type.__name__}, nothing was raised")


# --------------------------------------------------------------- request fixture --
def envelope_args():
    """A well-formed executeSupply argument list, in the JSON-transport forms."""
    return [
        ["0x" + "11" * 32, "0x" + "22" * 32, "0x" + "33" * 32, "1",
         SAFE, "0x" + "00" * 31 + "11", "1", "1", RUNNER],
        [USDC, WETH, "0x" + "44" * 20, "0x" + "55" * 20, "860000000000000000"],
        "10000000",
        "0x" + "ab" * 65,
    ]


def payload(**overrides):
    args = overrides.pop("args", envelope_args())
    body = {
        "contractAddress": CONTROLLER,
        "chainId": 8453,
        "functionName": "executeSupply",
        "functionArgs": json.dumps(args),
        "abi": "[]",
        "value": "0",
        "simulate": False,
    }
    body.update(overrides)
    return body


def calldata_for(args=None) -> str:
    return encode_call("executeSupply", args or envelope_args())


def verdicts(rep) -> dict[str, str]:
    return {str(c["check"]): str(c["verdict"]) for c in rep.checks}


def run_payload(controller=CONTROLLER, calldata=None, **overrides):
    rep = gate.Report(quiet=True)
    body = payload(**overrides)
    gate.check_payload(rep, body, calldata if calldata is not None else calldata_for(),
                       None, controller)
    return verdicts(rep)


# ================================================== 1. it cannot broadcast, at all --
class Inner:
    hosted = True

    def __init__(self):
        self.calls = []

    def request(self, method, url, *, headers, body, timeout):
        self.calls.append((method, url))
        return HttpResponse(200, {}, b"{}")


@test("transport refuses a non-simulate contract call")
def _():
    inner = Inner()
    t = gate.NoBroadcastTransport(inner)
    msg = expect(gate.GateRefusal, t.request, "POST", BASE + CONTRACT_CALL_PATH,
                 headers={}, body=json.dumps(payload()).encode(), timeout=5)
    assert "broadcast" in msg.lower(), msg
    assert inner.calls == [], "the refused request must never reach the wire"


@test("transport refuses simulate absent, null or the STRING 'true'")
def _():
    inner = Inner()
    t = gate.NoBroadcastTransport(inner)
    for bad in ({}, {"simulate": None}, {"simulate": "true"}, {"simulate": 1}):
        expect(gate.GateRefusal, t.request, "POST", BASE + CONTRACT_CALL_PATH,
               headers={}, body=json.dumps(bad).encode(), timeout=5)
    assert inner.calls == [], inner.calls


@test("transport refuses ANY request carrying an idempotency key")
def _():
    inner = Inner()
    t = gate.NoBroadcastTransport(inner)
    # Even a GET, and even one that could not possibly broadcast: carrying the header at
    # all means the caller thinks it is submitting something.
    msg = expect(gate.GateRefusal, t.request, "GET", BASE + KEYS_PATH,
                 headers={IDEMPOTENCY_HEADER: "0xdead"}, body=None, timeout=5)
    assert IDEMPOTENCY_HEADER in msg, msg
    assert inner.calls == [], inner.calls


@test("transport refuses an unparseable contract-call body")
def _():
    t = gate.NoBroadcastTransport(Inner())
    expect(gate.GateRefusal, t.request, "POST", BASE + CONTRACT_CALL_PATH,
           headers={}, body=b"not json", timeout=5)


@test("transport allows a read and a true simulation")
def _():
    inner = Inner()
    t = gate.NoBroadcastTransport(inner)
    t.request("GET", BASE + KEYS_PATH, headers={}, body=None, timeout=5)
    t.request("POST", BASE + CONTRACT_CALL_PATH, headers={},
              body=json.dumps(payload(simulate=True)).encode(), timeout=5)
    assert len(inner.calls) == 2, inner.calls
    assert t.refusals == [], t.refusals


@test("the client has no broadcast capability")
def _():
    c = gate.NoBroadcastClient("env:HELD_KEEPERHUB_API_KEY",
                               transport=gate.NoBroadcastTransport(Inner()))
    msg = expect(gate.GateRefusal, c.broadcast, object(), "0xkey")
    assert "cannot broadcast" in msg, msg


@test("no-broadcast check reports what the transport really saw")
def _():
    inner = Inner()
    t = gate.NoBroadcastTransport(inner)
    t.request("GET", BASE + KEYS_PATH, headers={}, body=None, timeout=5)
    rep = gate.Report(quiet=True)
    gate.check_no_broadcast(rep, t)
    assert verdicts(rep)["no-broadcast"] == gate.PASS

    # A contract call that somehow got through must be reported as an escape, even though
    # the transport would have refused it. The check is an independent witness.
    t.observed.append({"method": "POST", "path": CONTRACT_CALL_PATH,
                       "carried_idempotency_key": False})
    rep2 = gate.Report(quiet=True)
    gate.check_no_broadcast(rep2, t)
    assert verdicts(rep2)["no-broadcast"] == gate.FAIL


# ============================================ 2. an unevaluable check is not a pass --
@test("a missing request BLOCKS every payload check")
def _():
    rep = gate.Report(quiet=True)
    gate.check_payload(rep, None, None, "no prepared request", CONTROLLER)
    v = verdicts(rep)
    assert v and all(x == gate.BLOCKED for x in v.values()), v


@test("an unset controller BLOCKS the target check rather than skipping it")
def _():
    v = run_payload(controller=None)
    assert v["controller-target"] == gate.BLOCKED, v
    assert v["chain-8453"] == gate.PASS, "other checks still run"


@test("missing calldata BLOCKS the re-encoding check")
def _():
    v = run_payload(calldata="")
    assert v["calldata-reencodes"] == gate.BLOCKED, v


@test("an undeployed controller BLOCKS the on-chain executor check")
def _():
    rep = gate.Report(quiet=True)
    gate.check_executor(rep, None, None)
    v = verdicts(rep)
    assert v["executor-declared"] == gate.PASS, v
    assert v["executor-on-chain"] == gate.BLOCKED, (
        "the declared executor standing alone is not confirmation")


@test("a non-hosted credential answer is BLOCKED, never filed as a pass")
def _():
    # A 200 listing with mcp:write from an OFFLINE transport. If the gate graded on the
    # payload alone this would read as a clean PASS -- which is exactly the promotion the
    # evidence grades exist to prevent.
    body = json.dumps({"keys": [{"keyPrefix": "kh_live_x", "scopes": "mcp:read,mcp:write"}]})
    os.environ["HELD_KEEPERHUB_API_KEY"] = "kh_not_a_real_key_fixture_only"
    real = gate.HttpsTransport
    gate.HttpsTransport = lambda base_url=BASE: OfflineTransport(
        [HttpResponse(200, {}, body.encode())])
    try:
        rep = gate.Report(quiet=True)
        gate.check_credential(rep, BASE)
    finally:
        gate.HttpsTransport = real
        os.environ.pop("HELD_KEEPERHUB_API_KEY", None)
    assert verdicts(rep)["credential-write-scope"] == gate.BLOCKED, rep.checks


@test("an unset credential BLOCKS the scope check")
def _():
    os.environ.pop("HELD_KEEPERHUB_API_KEY", None)
    rep = gate.Report(quiet=True)
    gate.check_credential(rep, BASE)
    v = verdicts(rep)
    assert v["credential-write-scope"] == gate.BLOCKED, v
    assert "L10" in str(rep.checks[0]["detail"]), rep.checks


@test("BLOCKED is not a soft pass: the report does not pass")
def _():
    rep = gate.Report(quiet=True)
    rep.record("a", gate.PASS, "")
    rep.record("b", gate.BLOCKED, "")
    assert not rep.passed
    assert rep.counts() == {gate.PASS: 1, gate.FAIL: 0, gate.BLOCKED: 1}


@test("an empty report does not pass either")
def _():
    assert not gate.Report(quiet=True).passed, "vacuous truth is not permission to spend money"


# ============================================================ 3. it catches wrongness --
@test("a correctly prepared Base executeSupply passes every payload check")
def _():
    v = run_payload()
    assert all(x == gate.PASS for x in v.values()), v


@test("the wrong chain FAILS")
def _():
    for bad in (1, 84532, "8453", None):
        v = run_payload(chainId=bad)
        assert v["chain-8453"] == gate.FAIL, (bad, v)


@test("a target that is not the declared controller FAILS")
def _():
    v = run_payload(contractAddress=SAFE)
    assert v["controller-target"] == gate.FAIL, v


@test("target comparison ignores checksum case but not identity")
def _():
    v = run_payload(contractAddress=CONTROLLER.lower())
    assert v["controller-target"] == gate.PASS, v


@test("an unsupported function FAILS")
def _():
    for bad in ("transfer", "execute", "", None):
        v = run_payload(functionName=bad)
        assert v["function-supported"] == gate.FAIL, (bad, v)


@test("arguments that do not re-encode to the signed calldata FAIL")
def _():
    tampered = envelope_args()
    tampered[2] = "20000000"                      # 10 USDC becomes 20
    v = run_payload(args=tampered, calldata=calldata_for())
    assert v["calldata-reencodes"] == gate.FAIL, v


@test("a non-zero value FAILS")
def _():
    for bad in ("1", "0.001", 0, None):
        v = run_payload(value=bad)
        assert v["value-zero"] == gate.FAIL, (bad, v)


@test("a simulation is not the subject of a pre-broadcast gate")
def _():
    v = run_payload(simulate=True)
    assert v["payload-is-a-broadcast"] == gate.FAIL, v


@test("an extra or missing payload key FAILS the schema")
def _():
    v = run_payload(gasLimit="500000")
    assert v["payload-schema"] == gate.FAIL, v
    rep = gate.Report(quiet=True)
    short = payload()
    del short["abi"]
    gate.check_payload(rep, short, calldata_for(), None, CONTROLLER)
    assert verdicts(rep)["payload-schema"] == gate.FAIL


@test("a wrong declared executor FAILS")
def _():
    os.environ["HELD_M1_EXECUTOR"] = SAFE
    try:
        rep = gate.Report(quiet=True)
        gate.check_executor(rep, None, None)
    finally:
        os.environ.pop("HELD_M1_EXECUTOR", None)
    assert verdicts(rep)["executor-declared"] == gate.FAIL, rep.checks


@test("the expected executor is the one the owner recorded")
def _():
    assert gate.EXPECTED_EXECUTOR == "0x24192B75e297dC1c7a42DcB8C04227818E78acd0"
    assert gate.EXPECTED_CHAIN_ID == 8453


def main() -> int:
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"M1 pre-broadcast gate: FAIL ({len(FAILED)}/{len(PASSED) + len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} M1 pre-broadcast gate tests held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
