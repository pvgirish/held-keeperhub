"""Reproducible gate test suite. Positive + one isolated negative per defect.

Runs entirely in a temp workspace. NEVER writes to docs/baseline/ in the real tree.
Synthetic probe output here is a CHECKER fixture - it is never SDK or fork evidence.
"""
import json, os, shutil, subprocess, sys, tempfile, hashlib

HELD = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PY_BIN = os.path.expanduser(os.environ.get("PY", "~/venv312/bin/python"))
SDK = os.path.expanduser(os.environ.get("SDK", "~/src/sdk"))
MORPHO = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
SAFE = "0x1234567890123456789012345678901234567890"
MARKET = "0x13c42741a359ac4a8aa8287d2be109dcf28344484f91185f9a79bd5a805a55ae"
MP = ("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452",
      "0xD7A1abA119a236Fea5BBC5cAC6836465cbe9289A", "0x46415998764C29aB2a25CbeA6254146D50D22687",
      860000000000000000)
SEL = "0xa99aad89"


def build_supply_calldata(mp=MP, assets=100_000_000, shares=0, on_behalf=SAFE):
    from eth_abi import encode
    body = encode(["(address,address,address,address,uint256)", "uint256", "uint256", "address", "bytes"],
                  [mp, assets, shares, on_behalf, b""])
    return SEL + body.hex()


def build_supply_calldata_with_callback():
    from eth_abi import encode
    body = encode(["(address,address,address,address,uint256)", "uint256", "uint256", "address", "bytes"],
                  [MP, 100_000_000, 0, SAFE, b"\x01\x02\x03"])
    return SEL + body.hex()


def probe_stub(compile_step):
    return json.dumps({"pinned_rev": "6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938", "steps": [
        {"step": "registry.base.singleton", "status": "OK",
         "detail": {"morpho": MORPHO, "bundler": "0x23055618898e202386e6c13955a58D3C68200BFB"}},
        {"step": "registry.base.market_count", "status": "OK", "detail": 5},
        {"step": "intent.supply.construct", "status": "OK",
         "detail": {"market_id": MARKET, "amount": "100"}},
        {"step": "intent.validator.market_id_required", "status": "OK (correctly rejected)", "detail": "ValidationError"},
        {"step": "compiler.chains", "status": "OK", "detail": ["base", "ethereum"]},
        compile_step]})


def run_probe_gate(compile_step):
    t = tempfile.mkdtemp()
    try:
        os.makedirs(f"{t}/probes/checks")
        shutil.copy(f"{HELD}/probes/checks/check_probe.py", f"{t}/probes/checks/")
        with open(f"{t}/probes/p00_native_seam_probe.py", "w") as f:
            f.write("import sys\nsys.stdout.write(%r)\n" % probe_stub(compile_step))
        r = subprocess.run([PY_BIN, "probes/checks/check_probe.py"], cwd=t,
                           capture_output=True, text=True, env={**os.environ, "SDK": SDK, "PY": PY_BIN})
        return r.returncode, (r.stdout + r.stderr).strip()
    finally:
        shutil.rmtree(t, ignore_errors=True)


def ok(calls=None, safe=SAFE, status="OK"):
    return {"step": "compile.supply.calldata", "status": status,
            "detail": {"safe": safe, "calls": calls if calls is not None
                       else [{"to": MORPHO, "data": build_supply_calldata()}]}}


CASES = []
def case(name, step, want_pass):
    CASES.append((name, step, want_pass))

case("POSITIVE: correct bytes, correct market, exact raw units, correct Safe", ok(), True)
# the eight false-passes the independent review found
case("NEG data is 0xdeadbeef with plausible decoded alongside",
     {"step": "compile.supply.calldata", "status": "OK", "detail": {"safe": SAFE,
      "calls": [{"to": MORPHO, "data": "0xdeadbeef"}],
      "decoded": [{"function": "supply", "args": {"market_id": MARKET, "assets": "100000000", "onBehalf": SAFE}}]}}, False)
case("NEG amount tampered in bytes, decoded field left correct",
     {"step": "compile.supply.calldata", "status": "OK", "detail": {"safe": SAFE,
      "calls": [{"to": MORPHO, "data": build_supply_calldata(assets=1)}],
      "decoded": [{"function": "supply", "args": {"market_id": MARKET, "assets": "100000000", "onBehalf": SAFE}}]}}, False)
case("NEG declared Safe omitted entirely", ok(safe=None), False)
case("NEG onBehalf is an arbitrary beneficiary",
     ok([{"to": MORPHO, "data": build_supply_calldata(on_behalf="0x9999999999999999999999999999999999999999")}]), False)
case("NEG 100 raw units instead of 100000000",
     ok([{"to": MORPHO, "data": build_supply_calldata(assets=100)}]), False)
case("NEG 1 raw unit instead of 100000000",
     ok([{"to": MORPHO, "data": build_supply_calldata(assets=1)}]), False)
case("NEG compile status FAIL", ok(status="FAIL"), False)
case("NEG supplyCollateral selector instead of supply",
     ok([{"to": MORPHO, "data": "0x238d6579" + build_supply_calldata()[10:]}]), False)
# extra coverage
case("NEG wrong market params in bytes",
     ok([{"to": MORPHO, "data": build_supply_calldata(mp=(MP[0], MP[1], MP[2], MP[3], 770000000000000000))}]), False)
case("NEG shares set instead of assets",
     ok([{"to": MORPHO, "data": build_supply_calldata(assets=0, shares=100_000_000)}]), False)
# bundle-completeness regressions (continuation 5)
USDC_T = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
def approve(spender=MORPHO, amount=110_000_000):
    from eth_abi import encode
    return "0x095ea7b3" + encode(["address", "uint256"], [spender, amount]).hex()

case("POSITIVE: real two-call bundle (bounded approve + supply)",
     ok([{"to": USDC_T, "data": approve(), "value": 0},
         {"to": MORPHO, "data": build_supply_calldata(), "value": 0}]), True)
case("NEG valid supply followed by an UNRELATED transfer",
     ok([{"to": MORPHO, "data": build_supply_calldata()},
         {"to": USDC_T, "data": "0xa9059cbb" + "0"*128}]), False)
case("NEG duplicate supply calls in one bundle",
     ok([{"to": MORPHO, "data": build_supply_calldata()},
         {"to": MORPHO, "data": build_supply_calldata()}]), False)
case("NEG call carries ETH value",
     ok([{"to": MORPHO, "data": build_supply_calldata(), "value": 1}]), False)
case("NEG UNLIMITED approval",
     ok([{"to": USDC_T, "data": approve(amount=2**256-1)},
         {"to": MORPHO, "data": build_supply_calldata()}]), False)
case("NEG approval to the wrong spender",
     ok([{"to": USDC_T, "data": approve(spender="0xdead000000000000000000000000000000000001")},
         {"to": MORPHO, "data": build_supply_calldata()}]), False)
case("NEG approval below the supplied amount",
     ok([{"to": USDC_T, "data": approve(amount=1)},
         {"to": MORPHO, "data": build_supply_calldata()}]), False)
case("NEG trailing bytes appended to supply calldata",
     ok([{"to": MORPHO, "data": build_supply_calldata() + "deadbeef"}]), False)
case("NEG supply carries callback data",
     ok([{"to": MORPHO, "data": build_supply_calldata_with_callback()}]), False)

case("NEG no call targets Morpho",
     ok([{"to": "0xdead000000000000000000000000000000000001", "data": build_supply_calldata()}]), False)

leaks = 0
for name, step, want_pass in CASES:
    rc, out = run_probe_gate(step)
    passed = (rc == 0)
    good = (passed == want_pass)
    if not good:
        leaks += 1
    print(f"{'ok  ' if good else 'LEAK'}  {name}")
    if not good:
        print("       ->", out.replace("\n", " | ")[:200])

print("---")
if leaks:
    print(f"{leaks} GATE LEAK(S)"); sys.exit(1)
print(f"all {len(CASES)} gate tests held")
