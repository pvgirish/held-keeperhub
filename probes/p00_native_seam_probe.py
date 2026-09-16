"""P00 native seam probe — offline, no RPC.

Exercises the REAL pinned SDK: the real address registry, the real SupplyIntent
model and its validators, and the real Morpho compiler dispatch. Reports the
exact step at which an RPC becomes necessary. Nothing here is mocked, and no
result is invented.
"""
import json, os, subprocess, sys
from decimal import Decimal

out = {"steps": [], "pinned_rev": None}

def step(name, status, detail):
    out["steps"].append({"step": name, "status": status, "detail": detail})

# 1 — real address registry for the supported profile
from almanak.connectors.morpho_blue.addresses import (
    MORPHO_BLUE, MORPHO_BLUE_TOKENS, MORPHO_MARKETS, MORPHO_BLUE_ADDRESS,
)
base_core = MORPHO_BLUE.get("base")
base_tokens = MORPHO_BLUE_TOKENS.get("base", {})
base_markets = MORPHO_MARKETS.get("base", {})
step("registry.base.singleton", "OK" if base_core else "FAIL", base_core)
step("registry.base.usdc", "OK" if "USDC" in base_tokens else "FAIL", base_tokens.get("USDC"))
step("registry.base.market_count", "OK", len(base_markets))
step("registry.base.market_names", "OK", sorted(base_markets.keys())[:12])
step("registry.vanity_address", "INFO",
     {"vanity": MORPHO_BLUE_ADDRESS,
      "note": "registry warns this has ZERO code on several chains; per-chain singletons used instead"})
step("registry.network_awareness", "REJECTED-Sepolia",
     "MORPHO_BLUE / MORPHO_BLUE_TOKENS / MORPHO_MARKETS are keyed by chain NAME only; "
     "no Network dimension, so chain=base+network=sepolia would return MAINNET params.")

# 2 — connector declared chain support
from almanak.connectors.morpho_blue.sdk import SUPPORTED_CHAINS
from almanak.connectors.morpho_blue.flash_loan_provider import MORPHO_SUPPORTED_CHAINS
step("connector.supported_chains", "OK", sorted(SUPPORTED_CHAINS))
step("connector.flashloan_subset", "OK", sorted(MORPHO_SUPPORTED_CHAINS))

# 3 — real intent model + validators (this is the native decision object)
from almanak.framework.intents import SupplyIntent
market_id = sorted(base_markets.keys())[0] if base_markets else None
try:
    intent = SupplyIntent(protocol="morpho_blue", chain="base", token="USDC",
                          amount=Decimal("100"), market_id=market_id)
    step("intent.supply.construct", "OK",
         {"protocol": intent.protocol, "chain": intent.chain, "token": intent.token,
          "amount": str(intent.amount), "market_id": market_id})
except Exception as e:
    step("intent.supply.construct", "FAIL", f"{type(e).__name__}: {e}")

# 4 — validator proof: market_id is mandatory for morpho
try:
    SupplyIntent(protocol="morpho_blue", chain="base", token="USDC", amount=Decimal("100"))
    step("intent.validator.market_id_required", "UNEXPECTED-OK", "no market_id accepted")
except Exception as e:
    step("intent.validator.market_id_required", "OK (correctly rejected)", type(e).__name__)

# 5 — compiler class surface, no RPC yet
from almanak.connectors.morpho_blue.compiler import MorphoBlueCompiler
step("compiler.protocols", "OK", sorted(MorphoBlueCompiler.protocols))
step("compiler.chains", "OK", sorted(MorphoBlueCompiler.chains))

# 6 — REAL native compilation via the SDK's PUBLIC entry point.
# History of this step, kept so nobody repeats it:
#   v1 emitted BLOCKED unconditionally without ever calling the compiler.
#   v2 hand-built a BaseCompilerContext and hit "Protocols cannot be instantiated"
#      during CONSTRUCTION - which was then mis-reported as a compiler failure.
# The SDK already ships the concrete services adapter (_ConnectorCompilerServices,
# bound to IntentCompiler). Held must NOT reimplement it. Use IntentCompiler.compile().
#
# Failure STAGES are recorded separately. Construction != entered != returned.
SAFE = os.environ.get("HELD_FIXTURE_SAFE", "0x1234567890123456789012345678901234567890")
RPC = os.environ.get("HELD_BASE_RPC")
PRICE_MODE = os.environ.get("HELD_PRICE_MODE", "none")  # "none" | "testing-only"

stage = {"constructed": False, "compile_entered": False, "returned": False}
compiler = None
try:
    from almanak.framework.intents.compiler import IntentCompiler
    kwargs = dict(chain="base", wallet_address=SAFE, default_protocol="morpho_blue",
                  rpc_url=RPC, rpc_timeout=30.0)
    if PRICE_MODE == "testing-only":
        # TESTING-ONLY configuration. Never runtime evidence. Only set deliberately.
        kwargs["price_oracle"] = {"USDC": Decimal("1")}
    compiler = IntentCompiler(**kwargs)
    stage["constructed"] = True
    step("compile.stage.construct", "OK",
         {"entry": "IntentCompiler(...)", "rpc_url_present": bool(RPC),
          "price_mode": PRICE_MODE,
          "note": "uses the SDK's own _ConnectorCompilerServices; Held implements no services layer"})
except Exception as e:
    step("compile.stage.construct", "FAILED",
         {"exception": f"{type(e).__name__}: {str(e)[:300]}",
          "note": "CONSTRUCTION failure - the compiler was never entered"})

if compiler is not None:
    try:
        collateral_intent = SupplyIntent(
            protocol="morpho_blue", chain="base", token="USDC",
            amount=Decimal("100"), market_id=market_id, use_as_collateral=False)
        stage["compile_entered"] = True
        result = compiler.compile(collateral_intent)
        stage["returned"] = True
        calls = []
        for tx in (getattr(result, "transactions", None) or getattr(result, "calls", None) or []):
            g = (lambda k: getattr(tx, k, None) if not isinstance(tx, dict) else tx.get(k))
            calls.append({"to": g("to"), "data": g("data"), "value": g("value")})
        st = str(getattr(getattr(result, "status", ""), "name", getattr(result, "status", "")))
        ok = bool(calls) and st.upper().startswith(("OK", "SUCCESS", "COMPILED"))
        step("compile.supply.calldata", "OK" if ok else "BLOCKED",
             {"safe": SAFE, "calls": calls, "compiler_status": st,
              "use_as_collateral": False, "stage": stage, "rpc_url_present": bool(RPC),
              "errors": [str(x)[:200] for x in (getattr(result, "errors", None) or [])][:4]})
    except Exception as e:
        step("compile.supply.calldata", "BLOCKED",
             {"stage": stage, "rpc_url_present": bool(RPC),
              "failure_stage": "compilation" if stage["compile_entered"] else "intent_build",
              "exception": f"{type(e).__name__}: {str(e)[:300]}"})
else:
    step("compile.supply.calldata", "BLOCKED",
         {"stage": stage, "failure_stage": "construction",
          "note": "compiler never constructed; nothing was compiled"})

_sdk = os.path.expanduser(os.environ.get("SDK", "~/src/sdk"))
out["pinned_rev"] = subprocess.run(
    ["git", "-C", _sdk, "rev-parse", "HEAD"], capture_output=True, text=True
).stdout.strip() or None
out["sdk_path"] = _sdk

print(json.dumps(out, indent=2, default=str))
