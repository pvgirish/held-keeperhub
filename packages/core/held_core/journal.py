"""Durable journal and outbox.

V4 §4: "Persist the outbox before network I/O." Everything here exists to make that
enforceable rather than aspirational, and to make the three hard cases explicit:

  * **Same ID, same payload** -> idempotent reopen. A restart must reopen the
    decision, not mint a new one.
  * **Same ID, different payload** -> `IdentityConflict`. The journal "refuses payload
    rebinding from the first durable operation creation."
  * **Outcome unknown** -> the operation stays blocked. UNKNOWN is a real state with
    no automatic exit, not a synonym for FAILED.

Secrets are references only (V4 §4). The journal stores a `signer_ref` string naming
where a key lives; it never stores key material, and `assert_no_secrets` enforces that
on the way in rather than trusting callers.
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from dataclasses import dataclass
from enum import Enum
from contextlib import contextmanager
from typing import Any, Iterator

from .canonical import hex32, normalize_address, normalize_hash
from .identity import IdentityConflict
from .units import UnitError, uint, uint64

SCHEMA_VERSION = 2


class OperationState(str, Enum):
    CREATED = "CREATED"        # durable, nothing sent
    AUTHORIZED = "AUTHORIZED"  # envelope signed, nothing sent
    DISPATCHED = "DISPATCHED"  # handed to the executor; outcome not yet known
    CONFIRMED = "CONFIRMED"    # terminal: executed on chain
    FAILED = "FAILED"          # terminal-for-now: definitively NOT executed
    UNKNOWN = "UNKNOWN"        # outcome genuinely unknown -> blocked


# V4 §4 across handover:
#   already executed      -> recover the result, never re-execute  (CONFIRMED is final)
#   definitely not executed and still desired -> reauthorize the SAME id and payload
#   outcome unknown       -> remain blocked                        (UNKNOWN has no auto exit)
_ALLOWED: dict[OperationState, frozenset[OperationState]] = {
    OperationState.CREATED: frozenset({OperationState.AUTHORIZED, OperationState.FAILED}),
    OperationState.AUTHORIZED: frozenset(
        {OperationState.DISPATCHED, OperationState.FAILED, OperationState.AUTHORIZED}
    ),
    OperationState.DISPATCHED: frozenset(
        {OperationState.CONFIRMED, OperationState.FAILED,
         OperationState.UNKNOWN, OperationState.DISPATCHED}
    ),
    # Resolution of an unknown is allowed; guessing is not. Callers must supply
    # evidence, and re-entering AUTHORIZED from UNKNOWN is forbidden outright.
    OperationState.UNKNOWN: frozenset({OperationState.CONFIRMED, OperationState.FAILED}),
    # A reverted attempt consumes nothing, so the same ID and payload may be
    # reauthorized under a new epoch -- but only from FAILED, which means
    # *definite* non-execution.
    OperationState.FAILED: frozenset({OperationState.AUTHORIZED}),
    OperationState.CONFIRMED: frozenset(),  # terminal. Never re-execute.
}

_SECRET_PATTERNS = (
    re.compile(r"\b0x[0-9a-fA-F]{64}\b"),                # raw 32-byte key material
    re.compile(r"\b[A-Za-z0-9_-]{32,}\.[A-Za-z0-9_-]{16,}\b"),  # token-ish
)


class JournalError(Exception):
    pass


class StateTransitionError(JournalError):
    pass


class RecoveryBlocked(JournalError):
    """Source identity or a prior result could not be recovered. Fail closed."""


def assert_no_secrets(value: str, field: str) -> str:
    """Reject anything that looks like key material before it reaches durable storage.

    A 32-byte hex string is exactly the shape of a private key. Hashes are that shape
    too, which is why this is applied only to free-text reference fields
    (`signer_ref`, `note`) and never to hash columns.
    """
    if not isinstance(value, str):
        raise UnitError(f"{field}: expected string, got {type(value).__name__}")
    for pat in _SECRET_PATTERNS:
        if pat.search(value):
            raise JournalError(
                f"{field}: refusing to persist a value that looks like a secret. "
                "Store a reference (path, env var name, KMS id), never the material."
            )
    return value


@dataclass(frozen=True)
class Operation:
    operation_id: str
    payload_hash: str
    source_decision_id: str
    action_index: int
    state: OperationState
    epoch: int
    created_at: int
    updated_at: int


_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA synchronous=FULL;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operations (
    operation_id       TEXT PRIMARY KEY,
    payload_hash       TEXT NOT NULL,
    source_decision_id TEXT NOT NULL,
    action_index       INTEGER NOT NULL,
    state              TEXT NOT NULL,
    epoch              INTEGER NOT NULL,
    created_at         INTEGER NOT NULL,
    updated_at         INTEGER NOT NULL
);

-- Outbox rows are written BEFORE any network I/O and keep their own lineage so a
-- replacement transaction never looks like a fresh business operation.
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id             TEXT PRIMARY KEY,
    operation_id           TEXT NOT NULL REFERENCES operations(operation_id),
    envelope_hash          TEXT NOT NULL,
    epoch                  INTEGER NOT NULL,
    runner                 TEXT NOT NULL,
    signer_ref             TEXT NOT NULL,
    keeperhub_execution_id TEXT,
    tx_hash                TEXT,
    sender_nonce           INTEGER,
    replaces_attempt_id    TEXT REFERENCES attempts(attempt_id),
    state                  TEXT NOT NULL,
    created_at             INTEGER NOT NULL,
    -- The EXACT request this attempt sent. An envelope hash identifies what was
    -- authorized; it does not let a restart resend the identical bytes under the
    -- identical key, which is what idempotent recovery actually requires.
    idempotency_key        TEXT,
    request_body           TEXT,
    calldata               TEXT,
    -- SIMULATION never becomes an economic claim. Keeping the kind on the row stops a
    -- dry run from ever being mistaken for an ambiguous send during recovery.
    kind                   TEXT NOT NULL DEFAULT 'BROADCAST'
);
CREATE INDEX IF NOT EXISTS attempts_by_op ON attempts(operation_id);
-- One live claim per operation. A PENDING broadcast attempt is the claim; the partial
-- index makes a second concurrent claim a database error rather than a race.
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_broadcast_per_op
    ON attempts(operation_id) WHERE state = 'PENDING' AND kind = 'BROADCAST';

-- At-least-once delivery with an idempotent consumer acknowledgement. `acked_at` is
-- only ever set in the SAME transaction as the consumer's own state update.
CREATE TABLE IF NOT EXISTS results (
    operation_id TEXT PRIMARY KEY REFERENCES operations(operation_id),
    result_hash  TEXT NOT NULL,
    delivered_at INTEGER NOT NULL,
    acked_at     INTEGER,
    consumer_state TEXT
);

-- Tombstones outlive their operations. Retention may purge an operation row, but the
-- replay/history guarantee is advertised for as long as the tombstone exists, so the
-- tombstone is what a consumed-ID check consults after a purge.
CREATE TABLE IF NOT EXISTS tombstones (
    operation_id TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    final_state  TEXT NOT NULL,
    created_at   INTEGER NOT NULL
);
"""


class Journal:
    """A transactionally-updated journal. One SQLite file, WAL, synchronous=FULL."""

    def __init__(self, path: str) -> None:
        self.path = path
        fresh = not os.path.exists(path) or os.path.getsize(path) == 0
        self._db = sqlite3.connect(path, isolation_level=None, timeout=30.0)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_DDL)
        if fresh:
            self._db.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                (str(SCHEMA_VERSION),),
            )
        self._check_schema()

    def _check_schema(self) -> None:
        row = self._db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is None:
            raise RecoveryBlocked(
                "journal has no schema_version: refusing to use an unidentified database"
            )
        if int(row["value"]) != SCHEMA_VERSION:
            raise RecoveryBlocked(
                f"journal schema {row['value']} != expected {SCHEMA_VERSION}; migrate explicitly"
            )

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "Journal":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- transactions ----------------------------------------------------------
    def _begin(self) -> None:
        # IMMEDIATE takes the write lock up front, so two processes racing on the
        # same operation id serialise here instead of discovering the conflict
        # halfway through and rolling back a partially applied change.
        self._db.execute("BEGIN IMMEDIATE")

    def _commit(self) -> None:
        self._db.execute("COMMIT")

    @contextmanager
    def transaction(self) -> "Iterator[sqlite3.Connection]":
        """One atomic unit spanning journal rows AND a consumer's own state.

        This is the only thing that closes the crash-between-callback-and-ack gap:
        the acknowledgement and the consumer's state update must commit together or
        not at all. Exposed so results.py can enrol a consumer in the same
        transaction rather than acking in a separate one and hoping.
        """
        self._begin()
        try:
            yield self._db
            self._commit()
        except Exception:
            self._rollback()
            raise

    def _rollback(self) -> None:
        try:
            self._db.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass

    # -- operations ------------------------------------------------------------
    def create_or_reopen(
        self,
        operation_id: bytes | str,
        payload_hash: bytes | str,
        source_decision_id: str,
        action_index: int,
        epoch: int,
    ) -> Operation:
        """Durably create an operation, or reopen the identical one.

        Idempotent for an identical payload. Raises `IdentityConflict` when the same
        ID arrives carrying a different payload -- that is a rebinding attempt, and
        V4 §4 refuses it from the first durable creation onwards.
        """
        oid = _as_hash(operation_id, "operation_id")
        phash = _as_hash(payload_hash, "payload_hash")
        if not isinstance(source_decision_id, str) or not source_decision_id:
            raise UnitError("source_decision_id: must be a non-empty string")
        uint(action_index, "action_index")
        uint64(epoch, "epoch")
        now = _now()

        self._begin()
        try:
            tomb = self._db.execute(
                "SELECT payload_hash, final_state FROM tombstones WHERE operation_id=?", (oid,)
            ).fetchone()
            if tomb is not None and tomb["payload_hash"] != phash:
                raise IdentityConflict(
                    f"operation {oid} is tombstoned under a different payload "
                    f"({tomb['payload_hash']} != {phash})"
                )

            row = self._db.execute(
                "SELECT * FROM operations WHERE operation_id=?", (oid,)
            ).fetchone()
            if row is None:
                self._db.execute(
                    "INSERT INTO operations(operation_id,payload_hash,source_decision_id,"
                    "action_index,state,epoch,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (oid, phash, source_decision_id, action_index,
                     OperationState.CREATED.value, epoch, now, now),
                )
                op = Operation(oid, phash, source_decision_id, action_index,
                               OperationState.CREATED, epoch, now, now)
            else:
                if row["payload_hash"] != phash:
                    raise IdentityConflict(
                        f"operation {oid} is already bound to payload {row['payload_hash']}; "
                        f"refusing to rebind to {phash}"
                    )
                op = _row_to_op(row)
            self._commit()
            return op
        except Exception:
            self._rollback()
            raise

    def get(self, operation_id: bytes | str) -> Operation | None:
        oid = _as_hash(operation_id, "operation_id")
        row = self._db.execute(
            "SELECT * FROM operations WHERE operation_id=?", (oid,)
        ).fetchone()
        return _row_to_op(row) if row else None

    def _require_transition(self, cur: OperationState, new: OperationState, oid: str) -> None:
        """The state-machine guard, callable from inside an open transaction."""
        if new not in _ALLOWED[cur]:
            raise StateTransitionError(f"{cur.value} -> {new.value} is not permitted")

    def transition(
        self, operation_id: bytes | str, new_state: OperationState, *, epoch: int | None = None
    ) -> Operation:
        oid = _as_hash(operation_id, "operation_id")
        if not isinstance(new_state, OperationState):
            raise UnitError("new_state: expected OperationState")
        self._begin()
        try:
            row = self._db.execute(
                "SELECT * FROM operations WHERE operation_id=?", (oid,)
            ).fetchone()
            if row is None:
                raise JournalError(f"unknown operation {oid}")
            cur = OperationState(row["state"])
            if new_state not in _ALLOWED[cur]:
                raise StateTransitionError(f"{cur.value} -> {new_state.value} is not permitted")
            if cur is OperationState.FAILED and new_state is OperationState.AUTHORIZED:
                # V4 §4: reauthorization needs the SAME id and payload under a NEW
                # epoch, after reconciliation established definite non-execution.
                if epoch is None or epoch <= int(row["epoch"]):
                    raise StateTransitionError(
                        "reauthorizing a failed operation requires a strictly newer epoch "
                        f"(current {row['epoch']}, got {epoch})"
                    )
            new_epoch = int(row["epoch"]) if epoch is None else uint64(epoch, "epoch")
            now = _now()
            self._db.execute(
                "UPDATE operations SET state=?, epoch=?, updated_at=? WHERE operation_id=?",
                (new_state.value, new_epoch, now, oid),
            )
            if new_state in (OperationState.CONFIRMED, OperationState.FAILED):
                self._db.execute(
                    "INSERT OR REPLACE INTO tombstones(operation_id,payload_hash,final_state,"
                    "created_at) VALUES(?,?,?,?)",
                    (oid, row["payload_hash"], new_state.value, now),
                )
            self._commit()
            return _row_to_op(
                self._db.execute(
                    "SELECT * FROM operations WHERE operation_id=?", (oid,)
                ).fetchone()
            )
        except Exception:
            self._rollback()
            raise

    # -- outbox ----------------------------------------------------------------
    def claim_for_dispatch(
        self,
        attempt_id: str,
        operation_id: bytes | str,
        envelope_hash: bytes | str,
        epoch: int,
        runner: str,
        signer_ref: str,
        *,
        idempotency_key: str,
        request_body: str,
        calldata: str,
        kind: str = "BROADCAST",
        replaces_attempt_id: str | None = None,
    ) -> None:
        """Claim the operation for dispatch and persist the exact request, atomically.

        This replaces `record_attempt_before_send`, which committed a PENDING attempt but
        left the operation AUTHORIZED. That was a real recovery hole: after a crash
        between the send and the response, a restart saw an AUTHORIZED operation, treated
        it as sendable, minted a NEW attempt id and a NEW idempotency key, and submitted
        a second unprotected request for work that may already have executed.

        Three things therefore happen in ONE transaction:

          1. The operation moves to DISPATCHED. It is no longer sendable, so a restart
             cannot casually re-enter the send path.
          2. The attempt row is written with its idempotency key, request body and
             calldata -- everything needed to resend the IDENTICAL request under the
             IDENTICAL key, which is what makes a retry idempotent rather than a
             duplicate.
          3. The unique partial index rejects a second concurrent PENDING broadcast, so
             two submitters racing cannot both claim the same operation.

        A SIMULATION does not claim the operation: a dry run is not an economic attempt
        and must not move the state or block a later real send.
        """
        oid = _as_hash(operation_id, "operation_id")
        if kind not in ("BROADCAST", "SIMULATION"):
            raise UnitError("kind: expected BROADCAST or SIMULATION")
        if kind == "BROADCAST" and not idempotency_key:
            raise JournalError(
                "a broadcast attempt requires an idempotency key; without one a retry is "
                "an unprotected duplicate submission"
            )
        assert_no_secrets(signer_ref, "signer_ref")

        self._begin()
        try:
            op = self._db.execute(
                "SELECT state FROM operations WHERE operation_id=?", (oid,)
            ).fetchone()
            if op is None:
                raise JournalError(f"unknown operation {oid}")
            state = OperationState(op["state"])
            if state is OperationState.CONFIRMED:
                raise StateTransitionError(
                    f"operation {oid} is CONFIRMED; never re-execute a consumed operation"
                )

            if kind == "BROADCAST":
                existing = self._db.execute(
                    "SELECT attempt_id FROM attempts WHERE operation_id=? AND state='PENDING' "
                    "AND kind='BROADCAST'",
                    (oid,),
                ).fetchone()
                if existing is not None:
                    raise StateTransitionError(
                        f"operation {oid} already has an unresolved attempt "
                        f"{existing['attempt_id']}. Resolve or resume it; do not start a "
                        "second submission while its outcome is unknown."
                    )

            self._db.execute(
                "INSERT INTO attempts(attempt_id,operation_id,envelope_hash,epoch,runner,"
                "signer_ref,replaces_attempt_id,state,created_at,idempotency_key,"
                "request_body,calldata,kind) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    attempt_id, oid, _as_hash(envelope_hash, "envelope_hash"),
                    uint64(epoch, "epoch"), normalize_address(runner, "runner"),
                    signer_ref, replaces_attempt_id, "PENDING", _now(),
                    idempotency_key, request_body, calldata, kind,
                ),
            )

            if kind == "BROADCAST":
                # The claim itself. After this commit the operation is DISPATCHED even
                # though no byte has left the process -- which is the only safe reading,
                # because a crash one instruction later is indistinguishable from a
                # crash after the server received it.
                self._require_transition(state, OperationState.DISPATCHED, oid)
                self._db.execute(
                    "UPDATE operations SET state=?, epoch=?, updated_at=? WHERE operation_id=?",
                    (OperationState.DISPATCHED.value, uint64(epoch, "epoch"), _now(), oid),
                )
            self._commit()
        except Exception:
            self._rollback()
            raise

    def unresolved_attempt(self, operation_id: bytes | str) -> dict[str, Any] | None:
        """The PENDING broadcast attempt blocking this operation, if any.

        Recovery reads this to resume the ORIGINAL request under its ORIGINAL key rather
        than minting a new one.
        """
        oid = _as_hash(operation_id, "operation_id")
        row = self._db.execute(
            "SELECT * FROM attempts WHERE operation_id=? AND state='PENDING' AND kind='BROADCAST' "
            "ORDER BY created_at LIMIT 1",
            (oid,),
        ).fetchone()
        return dict(row) if row else None

    def record_send_result(
        self,
        attempt_id: str,
        *,
        keeperhub_execution_id: str | None = None,
        tx_hash: str | None = None,
        sender_nonce: int | None = None,
        state: str = "SENT",
    ) -> None:
        self._begin()
        try:
            self._db.execute(
                "UPDATE attempts SET keeperhub_execution_id=COALESCE(?,keeperhub_execution_id),"
                "tx_hash=COALESCE(?,tx_hash), sender_nonce=COALESCE(?,sender_nonce), state=? "
                "WHERE attempt_id=?",
                (
                    keeperhub_execution_id,
                    normalize_hash(tx_hash, "tx_hash") if tx_hash else None,
                    None if sender_nonce is None else uint64(sender_nonce, "sender_nonce"),
                    state, attempt_id,
                ),
            )
            self._commit()
        except Exception:
            self._rollback()
            raise

    def attempts_for(self, operation_id: bytes | str) -> list[dict[str, Any]]:
        oid = _as_hash(operation_id, "operation_id")
        return [
            dict(r)
            for r in self._db.execute(
                "SELECT * FROM attempts WHERE operation_id=? ORDER BY created_at, attempt_id",
                (oid,),
            ).fetchall()
        ]

    # -- recovery --------------------------------------------------------------
    def unresolved(self) -> list[Operation]:
        """Operations a restart must resolve before doing anything else."""
        rows = self._db.execute(
            "SELECT * FROM operations WHERE state IN (?,?,?) ORDER BY created_at",
            (OperationState.AUTHORIZED.value, OperationState.DISPATCHED.value,
             OperationState.UNKNOWN.value),
        ).fetchall()
        return [_row_to_op(r) for r in rows]

    def assert_recoverable(self, operation_id: bytes | str) -> None:
        """Fail closed when identity or a prior result cannot be recovered.

        V4 §4: an operation whose outcome is unknown "remains blocked". This raises
        rather than returning a boolean so a caller cannot accidentally proceed by
        ignoring a falsy return.
        """
        oid = _as_hash(operation_id, "operation_id")
        op = self.get(oid)
        if op is None:
            tomb = self._db.execute(
                "SELECT final_state FROM tombstones WHERE operation_id=?", (oid,)
            ).fetchone()
            if tomb is None:
                raise RecoveryBlocked(
                    f"operation {oid} has neither a journal row nor a tombstone: "
                    "source identity is unrecoverable, refusing to proceed"
                )
            return
        if op.state is OperationState.DISPATCHED:
            rows = self.attempts_for(oid)
            if not any(r["keeperhub_execution_id"] or r["tx_hash"] for r in rows):
                raise RecoveryBlocked(
                    f"operation {oid} is DISPATCHED with no execution id or tx hash: "
                    "the send may or may not have happened; outcome unknown, stay blocked"
                )
        if op.state is OperationState.UNKNOWN:
            raise RecoveryBlocked(f"operation {oid} outcome is UNKNOWN; stay blocked")

    def tombstone(self, operation_id: bytes | str) -> dict[str, Any] | None:
        oid = _as_hash(operation_id, "operation_id")
        row = self._db.execute(
            "SELECT * FROM tombstones WHERE operation_id=?", (oid,)
        ).fetchone()
        return dict(row) if row else None

    def purge_operation_keep_tombstone(self, operation_id: bytes | str) -> None:
        """Retention: drop the operation body, keep the replay guarantee."""
        oid = _as_hash(operation_id, "operation_id")
        self._begin()
        try:
            t = self._db.execute(
                "SELECT 1 FROM tombstones WHERE operation_id=?", (oid,)
            ).fetchone()
            if t is None:
                raise JournalError(
                    f"refusing to purge {oid}: no tombstone, so the consumed-ID guarantee "
                    "would be lost"
                )
            self._db.execute("DELETE FROM attempts WHERE operation_id=?", (oid,))
            self._db.execute("DELETE FROM results WHERE operation_id=?", (oid,))
            self._db.execute("DELETE FROM operations WHERE operation_id=?", (oid,))
            self._commit()
        except Exception:
            self._rollback()
            raise


def _now() -> int:
    return int(time.time())


def _as_hash(value: bytes | str, field: str) -> str:
    if isinstance(value, bytes):
        return hex32(value)
    return normalize_hash(value, field)


def _row_to_op(row: sqlite3.Row) -> Operation:
    return Operation(
        operation_id=row["operation_id"],
        payload_hash=row["payload_hash"],
        source_decision_id=row["source_decision_id"],
        action_index=int(row["action_index"]),
        state=OperationState(row["state"]),
        epoch=int(row["epoch"]),
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
    )
