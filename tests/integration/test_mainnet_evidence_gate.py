"""Can fork evidence be made to satisfy a mainnet claim?

The answer has to be no, and it has to be no for reasons that survive somebody trying. A
naming convention does not survive trying. A review checklist did not survive trying in
this project already. So the gate is attacked here the way a person in a hurry the night
before a deadline would attack it:

  * relabel a fork record as verified
  * fill the template in with plausible numbers
  * fill it in with a real-looking hash from somewhere else
  * point it at a block that sounds like mainnet
  * run it when the RPC is down and hope "unconfirmed" reads as "fine"

Every one of those must be REFUSED, and the last is the one that matters most: an
unreachable RPC must never be a pass. Fail-closed is not a preference here, it is the only
reading that is safe when the thing being decided is whether a mandatory competition claim
is proven.

The network is stubbed throughout, so these tests are deterministic and offline. The real
gate's confirming call is `eth_getTransactionReceipt` against a public Base RPC; what is
tested here is what the gate DOES with each possible answer.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "script"))

import mainnet_evidence_gate as gate  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

REAL_TX = "0x" + "ab" * 32
GOOD_BLOCK = gate.MIN_MAINNET_BLOCK + 50_000


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


class Chain:
    """A stand-in for public Base. `answer` is what eth_getTransactionReceipt returns."""

    def __init__(self, answer=None, error=None):
        self.answer = answer
        self.error = error
        self.asked: list[str] = []

    def __call__(self, method, params):
        self.asked.append(method)
        return (None, self.error) if self.error else (self.answer, None)


def judge(doc: dict, chain: Chain | None = None) -> tuple[str, str]:
    """Run ONE record through the gate and return (verdict, detail)."""
    chain = chain or Chain()
    real = gate.rpc_call
    gate.rpc_call = chain
    try:
        g = gate.Gate()
        import io
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            gate.verify_record(g, "/tmp/record.json", doc)
    finally:
        gate.rpc_call = real
    return g.findings[0]["verdict"], g.findings[0]["detail"]


def receipt(block: int = GOOD_BLOCK, status: str = "0x1") -> dict:
    return {"blockNumber": hex(block), "status": status}


def verified(**overrides) -> dict:
    """A record that claims public Base and is internally complete."""
    doc = {
        "schema": "held.public-transaction-record.v1",
        "label": gate.VERIFIED,
        "_status": "EXECUTED",
        "step": "12-execute-supply",
        "chainId": 8453,
        "receipt": {"transactionHash": REAL_TX, "blockNumber": GOOD_BLOCK,
                    "blockHash": "0x" + "cd" * 32, "gasUsed": 485779,
                    "effectiveGasPrice": 1000000, "status": "0x1",
                    "timestamp": "2026-09-20T00:00:00Z",
                    "explorer_url": f"https://basescan.org/tx/{REAL_TX}"},
    }
    doc.update(overrides)
    return doc


# ============================================== the attacks a deadline would suggest --
@test("relabelling a FORK record as verified is REFUSED")
def _():
    forked = verified()
    forked["receipt"]["blockNumber"] = gate.FORK_BLOCK + 40      # an anvil block
    v, d = judge(forked)
    assert v == "REFUSED", (v, d)
    assert "pinned fork block" in d, d


@test("the REAL fork rehearsal, relabelled, is REFUSED")
def _():
    path = os.path.join(ROOT, "evidence", "M1", "final-fork-rehearsal.json")
    if not os.path.exists(path):
        return
    with open(path) as fh:
        doc = json.load(fh)
    assert doc["label"] == gate.FORK, "the rehearsal must ship labelled FORK"
    v, _ = judge(doc)
    assert v == "ok", "a FORK record is fine as long as it claims nothing"

    doc["label"] = gate.VERIFIED                                  # the attack
    v, d = judge(doc)
    assert v == "REFUSED", (v, d)


@test("a template filled with plausible values is still REFUSED")
def _():
    doc = gate.template("12-execute-supply", "t", "KEEPERHUB", "executeSupply", True)
    doc["label"] = gate.VERIFIED
    doc["receipt"] = {f: "filled in" for f in gate.RECEIPT_FIELDS}
    doc["receipt"]["transactionHash"] = REAL_TX
    doc["receipt"]["blockNumber"] = GOOD_BLOCK
    doc["readback"] = {"what_must_be_true": "x", "observed": "y"}
    v, d = judge(doc)
    assert v == "REFUSED", (v, d)
    assert "template" in d.lower(), d


@test("a record still carrying FILL: sentinels is REFUSED")
def _():
    doc = verified(_status="EXECUTED")
    doc["readback"] = {"observed": f"{gate.SENTINEL}what was read"}
    v, d = judge(doc)
    assert v == "REFUSED", (v, d)
    assert "sentinel" in d.lower(), d


@test("a transaction that is not on public Base is REFUSED")
def _():
    v, d = judge(verified(), Chain(answer=None))
    assert v == "REFUSED", (v, d)
    assert "does not exist on public Base" in d, d


@test("an unreachable RPC is REFUSED, never quietly accepted")
def _():
    v, d = judge(verified(), Chain(error="URLError: connection refused"))
    assert v == "REFUSED", (v, d)
    assert "UNCONFIRMED" in d, d


@test("a receipt whose block disagrees with the record is REFUSED")
def _():
    v, d = judge(verified(), Chain(answer=receipt(block=GOOD_BLOCK + 9)))
    assert v == "REFUSED", (v, d)
    assert "public Base says" in d, d


@test("a FAILED transaction is REFUSED even though it exists")
def _():
    v, d = judge(verified(), Chain(answer=receipt(status="0x0")))
    assert v == "REFUSED", (v, d)
    assert "did not succeed" in d, d


@test("a malformed or missing transaction hash is REFUSED")
def _():
    for bad in (None, "", "0xdeadbeef", 12345, "not a hash"):
        doc = verified()
        doc["receipt"]["transactionHash"] = bad
        v, d = judge(doc)
        assert v == "REFUSED", (bad, v, d)


@test("an unknown label is REFUSED rather than ignored")
def _():
    for bad in ("MAINNET", "verified", "PUBLIC", None, "", "REAL LOCAL FORK"):
        v, d = judge(verified(label=bad))
        assert v == "REFUSED", (bad, v, d)


@test("a FORK record that does not disclaim mainnet proof is REFUSED")
def _():
    v, d = judge({"label": gate.FORK})
    assert v == "REFUSED", (v, d)
    v, _ = judge({"label": gate.FORK, "is_public_mainnet_proof": False})
    assert v == "ok"


# ================================================= and the honest path still works --
@test("a genuine public-Base transaction is CONFIRMED")
def _():
    chain = Chain(answer=receipt())
    v, d = judge(verified(), chain)
    assert v == "CONFIRMED", (v, d)
    assert chain.asked == ["eth_getTransactionReceipt"], chain.asked
    assert "re-read from public Base" in d, d


@test("confirmation requires asking the chain, not reading the file")
def _():
    # If the gate ever decided on the document alone, this would pass without the chain
    # ever being consulted. The assertion is that it is consulted.
    chain = Chain(answer=receipt())
    judge(verified(), chain)
    assert chain.asked, "the gate reached a verdict without asking public Base"


@test("every shipped template is PREPARED and sentinel-bearing")
def _():
    d = os.path.join(ROOT, "evidence", "M1", "templates")
    if not os.path.isdir(d):
        return
    names = [n for n in os.listdir(d) if n.endswith(".json")]
    assert names, "no templates on disk"
    for n in names:
        with open(os.path.join(d, n)) as fh:
            doc = json.load(fh)
        assert doc["label"] == gate.PREPARED, (n, doc["label"])
        assert doc["_status"].startswith("TEMPLATE"), n
        assert gate.has_sentinel(doc), f"{n} has no FILL: sentinel, so nothing is blank"
        assert judge(doc)[0] == "ok", n


@test("the M1 and M2 shells leave ONLY public-proof fields blank")
def _():
    for name in ("M1-report", "M2-report"):
        with open(os.path.join(ROOT, "evidence", "M1", "templates", f"{name}.json")) as fh:
            doc = json.load(fh)
        assert not gate.has_sentinel(doc["established_on_fork"]), (
            f"{name}: what the fork already established must not be blank")
        blanks = doc["blank_until_public_execution"]
        assert all(str(v).startswith(gate.SENTINEL) for v in blanks.values()), name
        assert "transactionHash" in blanks and "keeperhub_execution_id" in blanks, name


def main() -> int:
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"mainnet evidence gate: FAIL ({len(FAILED)}/{len(PASSED) + len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} mainnet-evidence-gate tests held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
