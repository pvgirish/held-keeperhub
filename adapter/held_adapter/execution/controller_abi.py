"""Building the ONE permitted controller invocation, and proving it encodes correctly.

This module exists because of a specific defect. `Submitter.submit()` used to take an
admitted operation, an envelope and an arbitrary `calldata` string as three independent
arguments; it signed the envelope and then sent whatever calldata it was handed. Nothing
checked that the calldata contained that operation, that envelope or that signature. The
signed authorization and the submitted request were simply two unrelated objects that
happened to travel together.

So the request is no longer supplied. It is CONSTRUCTED here from the verified admitted
action plus exactly the authorization that was just produced, and there is no code path
that accepts a caller-provided call.

## Why the encoding is checked locally

KeeperHub's documented contract takes `functionName` and `functionArgs`, not raw
calldata. That hands ABI encoding to the server. The runner's signature commits to an
action hash, and the controller recomputes the payload from the arguments it actually
receives -- so if the server's encoder produced different bytes, the controller would
reject the call after an execution had been spent.

`build_execute_call()` therefore returns both the arguments and the exact calldata those
arguments must encode to, and `ContractCallRequest.verify_encoding()` re-encodes the
arguments independently and requires byte equality before anything leaves the process.

What this establishes: the arguments Held sends are the arguments that produce the
intended calldata. What it does NOT establish: that KeeperHub's server-side encoder
agrees. That needs one authenticated dry run and is blocked on L10. It is recorded as
such rather than assumed.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from eth_abi import encode as abi_encode
from eth_utils import keccak

from held_core.canonical import normalize_address

# Struct component types, in declaration order, exactly as HeldController declares them.
ENVELOPE_COMPONENTS = (
    ("operationId", "bytes32"),
    ("sourceIdentityHash", "bytes32"),
    ("payloadHash", "bytes32"),
    ("actionFamily", "uint8"),
    ("safe", "address"),
    ("lineage", "bytes32"),
    ("epoch", "uint64"),
    ("policyVersion", "uint32"),
    ("runner", "address"),
)
MARKET_PARAMS_COMPONENTS = (
    ("loanToken", "address"),
    ("collateralToken", "address"),
    ("oracle", "address"),
    ("irm", "address"),
    ("lltv", "uint256"),
)

ENVELOPE_TYPE = "(" + ",".join(t for _, t in ENVELOPE_COMPONENTS) + ")"
MARKET_PARAMS_TYPE = "(" + ",".join(t for _, t in MARKET_PARAMS_COMPONENTS) + ")"

# The only two entry points the controller exposes. There is deliberately no generic
# "call the controller with these bytes" path: V4 §3 forbids a runtime-selected call.
EXECUTE_SUPPLY = "executeSupply"
EXECUTE_WITHDRAW = "executeWithdraw"
_FAMILY_TO_FUNCTION = {1: EXECUTE_SUPPLY, 2: EXECUTE_WITHDRAW}

_ARG_TYPES = (ENVELOPE_TYPE, MARKET_PARAMS_TYPE, "uint256", "bytes")


class ControllerAbiError(Exception):
    """The controller call could not be built or does not encode as required."""


def _tuple_component(name: str, components: Sequence[tuple[str, str]]) -> dict[str, Any]:
    return {
        "name": name,
        "type": "tuple",
        "components": [{"name": n, "type": t} for n, t in components],
    }


def function_abi(function_name: str) -> list[dict[str, Any]]:
    """The minimal ABI fragment for one entry point, as the API's `abi` field."""
    if function_name not in (EXECUTE_SUPPLY, EXECUTE_WITHDRAW):
        raise ControllerAbiError(f"unsupported controller function {function_name!r}")
    return [{
        "name": function_name,
        "type": "function",
        "stateMutability": "nonpayable",
        "outputs": [],
        "inputs": [
            _tuple_component("env", ENVELOPE_COMPONENTS),
            _tuple_component("mp", MARKET_PARAMS_COMPONENTS),
            {"name": "amount", "type": "uint256"},
            {"name": "signature", "type": "bytes"},
        ],
    }]


def selector(function_name: str) -> bytes:
    sig = f"{function_name}({','.join(_ARG_TYPES)})"
    return keccak(sig.encode())[:4]


def _as_bytes(value: Any, size: int | None = None) -> bytes:
    """Accept bytes or 0x-hex. The persisted request round-trips through JSON."""
    if isinstance(value, bytes):
        out = value
    elif isinstance(value, str):
        out = bytes.fromhex(value[2:] if value.startswith("0x") else value)
    else:
        raise ControllerAbiError(f"expected bytes or hex string, got {type(value).__name__}")
    if size is not None and len(out) != size:
        raise ControllerAbiError(f"expected {size} bytes, got {len(out)}")
    return out


def _as_int(value: Any) -> int:
    """Accept int or a decimal/hex string. Large uint256 values travel as strings."""
    if isinstance(value, bool):
        raise ControllerAbiError("a boolean is not an integer argument")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 16) if value.startswith("0x") else int(value)
    raise ControllerAbiError(f"expected an integer, got {type(value).__name__}")


def _coerce_args(args: Sequence[Any]) -> list[Any]:
    """Normalise the JSON-transport forms back to what the ABI encoder needs.

    A persisted request is stored as its JSON body, so `bytes` came back as `"0x…"` and
    integers as decimal strings. Re-encoding that round-tripped form and still getting
    the original calldata is precisely the replay guarantee `resume()` depends on.
    """
    env, mp, amount, signature = args
    env = tuple(env)
    mp = tuple(mp)
    if len(env) != len(ENVELOPE_COMPONENTS):
        raise ControllerAbiError(
            f"envelope has {len(env)} fields, expected {len(ENVELOPE_COMPONENTS)}")
    if len(mp) != len(MARKET_PARAMS_COMPONENTS):
        raise ControllerAbiError(
            f"market params has {len(mp)} fields, expected {len(MARKET_PARAMS_COMPONENTS)}")

    env_out = []
    for (name, typ), raw in zip(ENVELOPE_COMPONENTS, env):
        if typ == "bytes32":
            env_out.append(_as_bytes(raw, 32))
        elif typ == "address":
            env_out.append(normalize_address(raw, name))
        else:
            env_out.append(_as_int(raw))
    mp_out = []
    for (name, typ), raw in zip(MARKET_PARAMS_COMPONENTS, mp):
        mp_out.append(normalize_address(raw, name) if typ == "address" else _as_int(raw))
    return [tuple(env_out), tuple(mp_out), _as_int(amount), _as_bytes(signature, 65)]


def encode_call(function_name: str, args: Sequence[Any]) -> str:
    """ABI-encode a controller call to 0x-prefixed calldata."""
    if len(args) != 4:
        raise ControllerAbiError(f"expected 4 arguments, got {len(args)}")
    coerced = _coerce_args(args)
    try:
        body = abi_encode(list(_ARG_TYPES), coerced)
    except Exception as exc:
        raise ControllerAbiError(f"arguments do not encode against the controller ABI: {exc}") from exc
    return "0x" + (selector(function_name) + body).hex()


def build_execute_call(admitted, envelope, signature: bytes, market_params: Sequence[Any]):
    """Construct the only permitted invocation for this admitted action.

    Every field comes from the admitted action or the signed envelope. Nothing is
    supplied by a caller, so there is no opportunity for the submitted request and the
    signed authorization to disagree.

    Returns `(function_name, args, calldata)`.
    """
    family = int(admitted.action.family)
    function_name = _FAMILY_TO_FUNCTION.get(family)
    if function_name is None:
        # HOLD (0) reaches here only as a bug: V4 §5 says a HOLD has no executable call,
        # and the envelope type refuses to carry one.
        raise ControllerAbiError(
            f"action family {family} has no controller entry point; only SUPPLY and "
            "WITHDRAW are executable"
        )

    if envelope.action_family != admitted.action.family:
        raise ControllerAbiError(
            f"envelope family {envelope.action_family.name} disagrees with the admitted "
            f"action family {admitted.action.family.name}"
        )
    if bytes(envelope.operation_id) != bytes(admitted.operation_id):
        raise ControllerAbiError("envelope operation id disagrees with the admitted operation")
    if bytes(envelope.payload_hash) != bytes(admitted.payload_hash):
        raise ControllerAbiError(
            "envelope payload hash disagrees with the admitted action hash; the runner "
            "would be authorizing a different action than the one admitted"
        )
    if len(signature) != 65:
        raise ControllerAbiError(f"expected a 65-byte signature, got {len(signature)}")

    env_arg = (
        bytes(envelope.operation_id),
        bytes(envelope.source_identity_hash),
        bytes(envelope.payload_hash),
        int(envelope.action_family),
        normalize_address(envelope.scope.safe, "safe"),
        bytes.fromhex(envelope.scope.lineage[2:]),
        int(envelope.epoch),
        int(envelope.policy_version),
        normalize_address(envelope.runner, "runner"),
    )
    mp_arg = tuple(market_params)
    args = [env_arg, mp_arg, int(admitted.action.amount), bytes(signature)]
    return function_name, args, encode_call(function_name, args)


def decode_and_match(calldata: str, function_name: str, args: Sequence[Any]) -> None:
    """Require that `calldata` is exactly what `args` encode to under `function_name`."""
    rebuilt = encode_call(function_name, args)
    if rebuilt.lower() != calldata.lower():
        raise ControllerAbiError(
            "the request arguments do not encode to the expected controller calldata.\n"
            f"  expected: {calldata}\n  from args: {rebuilt}"
        )
