"""The ONE named boundary between the native SDK's ActionBundle and Held's own record.

The real seam at the pin, discovered by running the actual compiler rather than
assuming:

    IntentCompiler.compile(intent) -> CompilationResult
        .status            CompilationStatus.SUCCESS | ...
        .error, .is_safety_refusal, .is_transient, .warnings
        .action_bundle     ActionBundle(intent_type, transactions, metadata,
                                        sensitive_data)
        .transactions      a FLATTENED TransactionData list

The P00 probe read the flattened `.transactions` and never touched `.action_bundle`,
which is how the schema mismatch stayed hidden. Compilation status is read from the
RESULT here, not accepted from the caller: a caller-supplied "status" is an assertion,
whereas `result.status` is the producer's own verdict.

Held's internal admission record is `{safe, calls}`. Those are **not the same schema**,
and the earlier interceptor read only `calls` — so a real ActionBundle handed to it took
the "bundle has no calls" path. The P00 probe had been doing this conversion inline and
calling its output "the bundle", which is what hid the mismatch.

This module makes the conversion explicit, versioned and non-mutating:

  * It reads `transactions`, the SDK's actual field.
  * It copies economic calldata **byte for byte**. Nothing is re-encoded or normalised
    into the payload; only the container changes.
  * `sensitive_data` is never read, copied, logged or recorded. The SDK excludes it from
    `to_dict()` and states it must never reach logs or persistent storage.
  * Execution context (chain, Safe/wallet, controller) is resolved from its actual
    source and checked against the installed profile. Nothing is fabricated to make a
    bundle fit, and a contradiction fails closed.

`HELD_RECORD_VERSION` is the version of **Held's** representation, not the SDK's.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Mapping

sys.path.insert(0, __file__.rsplit("/adapter/", 1)[0] + "/packages/core")

from held_core.canonical import normalize_address  # noqa: E402

HELD_RECORD_VERSION = "held.native-record.v1"

# V4 §2 supported native actions. A HOLD is a successful no-action decision and must
# never become a transaction; anything else is outside the supported profile.
SUPPORTED_INTENT_TYPES = {"SUPPLY", "WITHDRAW"}
HOLD_INTENT_TYPES = {"HOLD", "NO_ACTION", "NOOP"}


class NativeBoundaryError(Exception):
    """The native object could not be admitted into Held's representation."""


class HoldDecision(Exception):
    """The native decision was a HOLD.

    Raised rather than returned so a caller cannot accidentally treat it as an
    executable operation. V4 §5: a HOLD has no executable economic call, no consumed
    operation and no transaction claim.
    """


class NativeRefusal(Exception):
    """The native compiler itself refused. Held does not second-guess that."""


@dataclass(frozen=True)
class ExecutionContext:
    """Where the operation is actually going, resolved at its real source.

    These are checked against the installed profile rather than trusted. A bundle that
    disagrees with the profile is a contradiction, not something to normalise away.

    `compiler_status` is a FALLBACK for callers holding a bare ActionBundle. When a
    CompilationResult is available its own `.status` is authoritative and this field is
    ignored.
    """

    chain_id: int
    safe: str
    source_decision_id: str
    action_index: int = 0
    compiler_status: str = "SUCCESS"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HeldNativeRecord:
    """Held's representation. NOT the SDK's schema, and labelled so nobody confuses them."""

    version: str
    intent_type: str
    safe: str
    calls: tuple
    source_metadata_keys: tuple  # key NAMES only; values are not copied wholesale

    def as_bundle(self) -> dict[str, Any]:
        """The shape `admit_bundle` consumes."""
        return {"safe": self.safe, "calls": list(self.calls)}


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _copy_transaction(tx: Any, index: int) -> dict[str, Any]:
    """Copy one native transaction verbatim. No re-encoding, no normalisation."""
    to = _field(tx, "to")
    data = _field(tx, "data")
    value = _field(tx, "value", 0)
    if to is None or data is None:
        raise NativeBoundaryError(
            f"transaction[{index}] is missing 'to' or 'data'; refusing to guess"
        )
    # `data` is passed through untouched -- admit_bundle decodes the real bytes and
    # a strict re-encode there is what rejects anything non-canonical.
    return {"to": to, "data": data, "value": value}


def normalize_native_bundle(native_bundle: Any, context: ExecutionContext) -> HeldNativeRecord:
    """Convert a native ActionBundle into Held's record, or fail closed."""
    status = str(context.compiler_status or "").upper()
    if not status.startswith(("OK", "SUCCESS", "COMPILED")):
        raise NativeBoundaryError(f"native compilation did not succeed: {context.compiler_status!r}")

    intent_type = _field(native_bundle, "intent_type")
    if intent_type is None:
        raise NativeBoundaryError(
            "object has no 'intent_type': this is not a native ActionBundle. Held's own "
            "{safe, calls} record is a different schema and must not be passed here."
        )
    intent = str(intent_type).upper()
    if intent in HOLD_INTENT_TYPES:
        raise HoldDecision(f"native decision is {intent}: no economic call, no operation")
    if intent not in SUPPORTED_INTENT_TYPES:
        raise NativeBoundaryError(f"intent_type {intent!r} is outside the supported profile")

    transactions = _field(native_bundle, "transactions")
    if transactions is None:
        raise NativeBoundaryError("native ActionBundle exposes 'transactions'; none found")
    if not isinstance(transactions, (list, tuple)) or not transactions:
        # A supported economic intent with no transactions is a contradiction, not a HOLD.
        raise NativeBoundaryError(f"{intent} carries no transactions; refusing to infer a HOLD")

    calls = tuple(_copy_transaction(tx, i) for i, tx in enumerate(transactions))

    # sensitive_data is deliberately NOT read. Only metadata KEY NAMES are retained, so
    # no native value is copied into Held's record by accident.
    metadata = _field(native_bundle, "metadata") or {}
    metadata_keys = tuple(sorted(str(k) for k in metadata)) if isinstance(metadata, Mapping) else ()

    return HeldNativeRecord(
        version=HELD_RECORD_VERSION,
        intent_type=intent,
        safe=normalize_address(context.safe, "context.safe"),
        calls=calls,
        source_metadata_keys=metadata_keys,
    )


def unwrap_compilation_result(result: Any) -> Any:
    """Take the producer's own verdict, then hand back its ActionBundle.

    Fails closed on a non-SUCCESS status, a recorded error, or a native safety refusal.
    A safety refusal is the native risk check doing its job; V4 §3 says native risk
    validation is preserved, so Held must not route around it.
    """
    status = _field(result, "status")
    if status is None:
        return result  # already an ActionBundle, or a caller-built object
    status_text = str(getattr(status, "value", status)).upper()
    if not status_text.startswith(("OK", "SUCCESS", "COMPILED")):
        raise NativeBoundaryError(f"native compilation did not succeed: status={status_text}")
    if _field(result, "is_safety_refusal"):
        raise NativeRefusal("the native compiler refused this action on safety grounds")
    error = _field(result, "error")
    if error:
        raise NativeBoundaryError(f"native compilation reported an error: {error!r}")

    bundle = _field(result, "action_bundle")
    if bundle is None:
        raise NativeBoundaryError(
            "CompilationResult carries no action_bundle; the flattened .transactions "
            "list is NOT the bundle and must not be substituted for it"
        )
    return bundle


def admit_native_bundle(native_bundle: Any, context: ExecutionContext, profile: Any):
    """Normalise a REAL native ActionBundle, then run the existing admission checks.

    The admission logic is unchanged: this only feeds it the right object. A HOLD
    propagates as `HoldDecision` and never reaches admission.
    """
    from .interceptor import admit_bundle  # local import keeps the modules independent

    if context.chain_id != profile.chain_id:
        raise NativeBoundaryError(
            f"execution context chain {context.chain_id} contradicts profile chain {profile.chain_id}"
        )
    bundle = unwrap_compilation_result(native_bundle)
    record = normalize_native_bundle(bundle, context)
    if record.safe != profile.safe:
        raise NativeBoundaryError(
            f"execution context Safe {record.safe} contradicts profile Safe {profile.safe}"
        )
    admitted = admit_bundle(
        record.as_bundle(), profile, context.source_decision_id, context.action_index
    )
    return record, admitted
