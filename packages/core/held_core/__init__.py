"""Held core contracts: units, canonical encoding, identity, journal, results.

Versioned and testable before any value-moving code exists (P01). Nothing in this
package touches a chain, a network or a key.
"""
from .canonical import canonical_bytes, canonical_hash, hex32, normalize_address, normalize_hash
from .identity import (
    ActionFamily,
    AuthorizationEnvelope,
    IdentityConflict,
    OperationScope,
    SupportedAction,
    operation_id,
)
from .journal import (
    Journal,
    JournalError,
    Operation,
    OperationState,
    RecoveryBlocked,
    StateTransitionError,
)
from .results import DeliveryOutcome, ResultConflict, deliver
from .units import UnitError

__all__ = [
    "ActionFamily", "AuthorizationEnvelope", "DeliveryOutcome", "IdentityConflict",
    "Journal", "JournalError", "Operation", "OperationScope", "OperationState",
    "RecoveryBlocked", "ResultConflict", "StateTransitionError", "SupportedAction",
    "UnitError", "canonical_bytes", "canonical_hash", "deliver", "hex32",
    "normalize_address", "normalize_hash", "operation_id",
]

SCHEMA_VERSION = 1
