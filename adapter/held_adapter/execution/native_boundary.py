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

# The EXACT status contract from almanak/framework/intents/compiler_models.py at the
# pin. Prefix matching was wrong and provably so: "SUCCESS_BUT_FAILED", "OKAY" and
# "COMPILED_UNSAFE" all passed `startswith(("OK","SUCCESS","COMPILED"))`. Only these
# three strings exist, and only one of them authorizes anything.
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
STATUS_PARTIAL = "PARTIAL"
KNOWN_STATUSES = frozenset({STATUS_SUCCESS, STATUS_FAILED, STATUS_PARTIAL})

_MISSING = object()


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

    There is deliberately NO status field here: the producer's own `.status` is the only
    verdict, read once in `unwrap_compilation_result`.
    """

    chain_id: int
    safe: str
    source_decision_id: str
    action_index: int = 0
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
    """Convert a native ActionBundle into Held's record, or fail closed.

    The producer verdict is NOT re-checked here. `unwrap_compilation_result` is the one
    place it is read; having a caller-supplied status second-guess the producer left two
    competing sources of truth, with the documentation claiming one was ignored while
    the code still enforced it.
    """
    intent_type = _field(native_bundle, "intent_type")
    if intent_type is None:
        raise NativeBoundaryError(
            "object has no 'intent_type': this is not a native ActionBundle. Held's own "
            "{safe, calls} record is a different schema and must not be passed here."
        )
    intent = str(intent_type).upper()
    transactions = _field(native_bundle, "transactions")

    if intent in HOLD_INTENT_TYPES:
        # Inspect the transactions BEFORE accepting the label. A HOLD carrying
        # executable transactions is contradictory input, not a successful no-action
        # decision -- classifying it as HOLD would discard real calls silently.
        if transactions:
            raise NativeBoundaryError(
                f"contradictory input: {intent} carries {len(transactions)} transaction(s). "
                "A HOLD has no executable economic call."
            )
        raise HoldDecision(f"native decision is {intent}: no economic call, no operation")

    if intent not in SUPPORTED_INTENT_TYPES:
        raise NativeBoundaryError(f"intent_type {intent!r} is outside the supported profile")

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


def unwrap_compilation_result(result: Any, *, require_verdict: bool = True) -> Any:
    """Take the producer's own verdict, then hand back its ActionBundle.

    `require_verdict=True` is the authorizing contract: an object with no status is
    refused rather than assumed successful. A bag of well-formed transactions is not
    evidence that compilation and native risk validation succeeded, and the earlier
    version returned exactly such an object untouched -- before it had even looked at
    `error` or `is_safety_refusal`.

    Ordering matters and was previously inverted. The SDK documents `is_safety_refusal`
    as "whether a **FAILED** status is a pre-execution SAFETY-GUARD refusal", so the
    refusal must be classified while handling FAILED. The old code only reached it after
    the success gate, which meant the ordinary native refusal shape (FAILED + refusal)
    was reported as a generic error and the category was lost.
    """
    status = _field(result, "status", _MISSING)
    if status is _MISSING or status is None:
        if require_verdict:
            raise NativeBoundaryError(
                "no producer verdict: this object carries no compilation status, so there "
                "is no evidence that compilation and native risk checks succeeded. "
                "Use normalize_bare_bundle() explicitly if you are parsing without one."
            )
        return result

    status_text = str(getattr(status, "value", status))
    if status_text not in KNOWN_STATUSES:
        raise NativeBoundaryError(
            f"unrecognised compilation status {status_text!r}; the pinned contract is "
            f"{sorted(KNOWN_STATUSES)}"
        )

    if status_text == STATUS_FAILED:
        if _field(result, "is_safety_refusal"):
            # The native guard did its job: zero transactions were built and the
            # position is untouched. V4 §3 preserves native risk validation, so Held
            # reports this as a refusal rather than routing around it.
            raise NativeRefusal(
                f"the native compiler refused on safety grounds: {_field(result, 'error')!r}"
            )
        raise NativeBoundaryError(f"native compilation FAILED: {_field(result, 'error')!r}")

    if status_text == STATUS_PARTIAL:
        raise NativeBoundaryError(
            "native compilation is PARTIAL: some transactions built and some failed. "
            "A partial bundle is never a supported single economic action."
        )

    # SUCCESS. Contradicting fields still fail closed.
    if _field(result, "is_safety_refusal"):
        raise NativeBoundaryError("contradictory result: SUCCESS carrying is_safety_refusal")
    error = _field(result, "error")
    if error:
        raise NativeBoundaryError(f"contradictory result: SUCCESS carrying error {error!r}")

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
    # The declared intent label and the family decoded from calldata must agree. The
    # label was previously read and then discarded, so a SUPPLY-labelled bundle whose
    # calls were a withdraw would have been admitted as a withdraw without comment.
    if admitted.action.family.name != record.intent_type:
        raise NativeBoundaryError(
            f"declared intent_type {record.intent_type} disagrees with the family decoded "
            f"from calldata ({admitted.action.family.name})"
        )
    return record, admitted


def normalize_bare_bundle(bundle: Any, context: ExecutionContext) -> HeldNativeRecord:
    """Parse an ActionBundle WITHOUT a producer verdict. NOT an authorizing path.

    Exists for parser-level tests and for callers who have separately established that
    compilation succeeded. It is named so that using it is a visible decision rather
    than an accident: nothing here shows that native compilation or risk validation
    succeeded, so its output must not be signed or submitted on its own.
    """
    return normalize_native_bundle(bundle, context)
