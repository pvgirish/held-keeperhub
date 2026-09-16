"""G2 gate.

The previous versions trusted a `decoded` object supplied alongside the calldata.
That is the whole defect: it validated a DESCRIPTION of the bytes, so calldata could
read 0xdeadbeef while the description claimed a perfect supply.

This version decodes the ACTUAL BYTES with the pinned ABI and derives the market id by
re-encoding and hashing the decoded MarketParams. Any `decoded` field in the probe output
is advisory only and is never trusted.
"""
import json, subprocess, sys, os, re

REV = "6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938"
ADDR = re.compile(r"0x[0-9a-fA-F]{40}")
B32 = re.compile(r"0x[0-9a-fA-F]{64}")
# supply((address,address,address,address,uint256),uint256,uint256,address,bytes)
SUPPLY_SELECTOR = "0xa99aad89"
SUPPLY_TYPES = ["(address,address,address,address,uint256)", "uint256", "uint256", "address", "bytes"]
USDC_DECIMALS = 6

sdk = os.path.expanduser(os.environ.get("SDK", "~/src/sdk"))
py = os.path.expanduser(os.environ.get("PY", "~/venv312/bin/python"))
failures = []
APPROVAL_NOTES = []
def fail(m): failures.append(m)
def norm(a): return str(a).strip().lower()

if not os.path.isdir(sdk):
    print("FAIL: SDK clone missing at", sdk); sys.exit(1)
head = subprocess.run(["git", "-C", sdk, "rev-parse", "HEAD"],
                      capture_output=True, text=True).stdout.strip()
if head != REV:
    print("FAIL: SDK at", head, "not pinned rev", REV); sys.exit(1)

res = subprocess.run([py, "probes/p00_native_seam_probe.py"], capture_output=True, text=True)
if res.returncode != 0:
    print("FAIL: probe crashed\n", res.stderr[-800:]); sys.exit(1)
d = json.loads(res.stdout)
by = {s["step"]: s for s in d["steps"]}

# ---------------- offline half ----------------
if d.get("pinned_rev") != REV:
    fail(f"probe ran against {d.get('pinned_rev')}, not the pinned rev")

singleton = by["registry.base.singleton"]["detail"]
morpho_addr = singleton.get("morpho") if isinstance(singleton, dict) else None
if not morpho_addr or not ADDR.fullmatch(str(morpho_addr)):
    fail(f"registry.base.singleton.detail.morpho is not an address: {morpho_addr!r}")
    morpho_addr = None
if by["registry.base.market_count"]["detail"] < 1:
    fail("no Base markets in the registry")

ci = by["intent.supply.construct"]
if not ci["status"].startswith("OK"):
    fail("real SupplyIntent did not construct")
intent = ci.get("detail") or {}
market_id = str(intent.get("market_id", ""))
if not B32.fullmatch(market_id):
    fail(f"market_id is not a real 32-byte id: {market_id!r}")
if not by["intent.validator.market_id_required"]["status"].startswith("OK"):
    fail("market_id validator did not reject a missing id")
if "base" not in by["compiler.chains"]["detail"]:
    fail("compiler does not claim base")

if failures:
    for f in failures: print("FAIL:", f)
    print("check-probe: FAIL (offline half broken)"); sys.exit(1)

# ---------------- compiled half ----------------
comp = by.get("compile.supply.calldata")
if comp is None:
    print("check-probe: PARTIAL - offline seam verified; no compile step recorded."); sys.exit(1)

status = str(comp.get("status", ""))
if status == "BLOCKED":
    print("check-probe: PARTIAL - offline seam verified against the real pinned SDK.")
    print("  Compiled-calldata half NOT satisfied:", str(comp.get("detail"))[:170]); sys.exit(1)
# a FAIL/ERROR compile must never reach the byte checks
if not re.match(r"^(OK|SUCCESS)\b", status, re.I):
    print(f"FAIL: compile step status is {status!r}, not a success status")
    print("check-probe: FAIL"); sys.exit(1)

det = comp.get("detail") or {}
calls = det.get("calls")
if not isinstance(calls, list) or not calls:
    print("FAIL: compile step present but produced no calls"); sys.exit(1)

# the declared Safe is REQUIRED - never a conditional check
safe = det.get("safe")
if not safe or not ADDR.fullmatch(str(safe)):
    fail(f"compile detail must declare the Safe as an address; got {safe!r}")

try:
    from eth_abi import decode as abi_decode, encode as abi_encode
    from eth_utils import keccak
except ImportError:
    print("FAIL: eth_abi/eth_utils unavailable - cannot decode bytes, so cannot verify"); sys.exit(1)

# WHOLE-BUNDLE verification. Every call must be accounted for against the declared
# profile. Finding one correct supply and ignoring the rest is not verification.
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
APPROVE_SEL = "0x095ea7b3"
supply_count = 0
want = None
try:
    want = int(round(float(str(intent.get("amount", "0"))) * 10 ** USDC_DECIMALS))
except ValueError:
    fail(f"intent amount {intent.get('amount')!r} is not numeric")

for i, c in enumerate(calls):
    to, data = str(c.get("to", "")), str(c.get("data", ""))
    val = c.get("value", 0)
    if not ADDR.fullmatch(to):
        fail(f"call[{i}].to is not an address: {to!r}"); continue
    if not re.fullmatch(r"0x[0-9a-fA-F]{8,}", data):
        fail(f"call[{i}].data is not real calldata: {data[:24]!r}"); continue
    if val not in (0, "0", None):
        fail(f"call[{i}] carries ETH value {val!r}; the supported profile moves no native value")

    if norm(to) == norm(morpho_addr):
        sel = data[:10].lower()
        if sel != SUPPLY_SELECTOR:
            fail(f"call[{i}] targets Morpho with selector {sel}, not supply {SUPPLY_SELECTOR}")
            continue
        body = data[10:]
        try:
            mp, assets, shares, on_behalf, extra = abi_decode(SUPPLY_TYPES, bytes.fromhex(body))
        except Exception as e:
            fail(f"call[{i}] Morpho calldata does not decode as supply: {type(e).__name__}: {e}")
            continue
        supply_count += 1
        # trailing bytes: re-encoding must reproduce the body exactly
        if abi_encode(SUPPLY_TYPES, [mp, assets, shares, on_behalf, extra]).hex() != body.lower():
            fail(f"call[{i}] has trailing or non-canonical calldata after the supply arguments")
        if extra:
            fail(f"call[{i}] supply carries callback data ({len(extra)} bytes); the profile forbids callbacks")
        derived = "0x" + keccak(abi_encode([SUPPLY_TYPES[0]], [mp])).hex()
        if norm(derived) != norm(market_id):
            fail(f"call[{i}] encodes market {derived}, intent market is {market_id}")
        if want is not None and int(assets) != want:
            fail(f"call[{i}] supplies {int(assets)} raw units, intent is "
                 f"{intent.get('amount')} USDC = {want} raw units")
        if int(shares) != 0:
            fail(f"call[{i}] sets shares={int(shares)}; the profile supplies assets, not shares")
        if safe and norm(on_behalf) != norm(safe):
            fail(f"call[{i}] onBehalf {on_behalf} is not the declared Safe {safe}")

    elif norm(to) == norm(USDC) and data[:10].lower() == APPROVE_SEL:
        try:
            spender, amount = abi_decode(["address", "uint256"], bytes.fromhex(data[10:]))
        except Exception as e:
            fail(f"call[{i}] approve does not decode: {type(e).__name__}: {e}"); continue
        if norm(spender) != norm(morpho_addr):
            fail(f"call[{i}] approves {spender}, not the Morpho singleton")
        if int(amount) >= 2 ** 256 - 1:
            fail(f"call[{i}] is an UNLIMITED approval; the profile forbids it")
        if want is not None and int(amount) < want:
            fail(f"call[{i}] approves {int(amount)} < the {want} raw units being supplied")
        if want is not None and int(amount) > want:
            APPROVAL_NOTES.append(f"call[{i}] approves {int(amount)} for a {want}-unit supply "
                                  f"(+{int(amount) - want} headroom)")
    else:
        fail(f"call[{i}] is an UNEXPECTED transaction in the bundle: to={to} "
             f"selector={data[:10]}; the declared profile allows only a bounded USDC approve "
             f"and one Morpho supply")

if supply_count > 1:
    fail(f"bundle contains {supply_count} Morpho supply calls; the profile allows exactly one")

if supply_count == 0:
    fail(f"no call decodes as a Morpho supply to {morpho_addr}")

if failures:
    for f in failures: print("FAIL:", f)
    print(f"check-probe: FAIL ({len(failures)} problems)"); sys.exit(1)
for n in APPROVAL_NOTES:
    print("NOTE:", n)
print(f"check-probe: PASS ({len(calls)} calls, all accounted for; bytes decoded and matched to the intent)")
