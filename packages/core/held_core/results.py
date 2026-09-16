"""Native result delivery and acknowledgement.

V4 §4 states the contract and its limit in the same breath:

    "An at-least-once result delivery channel with idempotent consumer
    acknowledgement is the engineering contract. ... A local 'delivered' bit by
    itself does not solve the crash between callback and acknowledgement."

So this module does NOT offer exactly-once delivery, and says so. What it offers is:

  * **at-least-once** delivery, retried until acknowledged;
  * an acknowledgement that is written in the SAME transaction as the consumer's own
    state update, so the pair cannot be torn apart by a crash;
  * **idempotence at the consumer**, so a duplicate delivery is a no-op rather than a
    second state change.

The crash window that a naive design leaves open is: callback received -> consumer
state updated -> CRASH -> ack never written -> redelivery -> consumer state updated
AGAIN. That window is closed here by construction, because there is no point at which
the consumer's state has moved but the ack has not: they are one commit.

If a real native consumer cannot enrol in this transaction -- because its state lives
somewhere this process cannot commit atomically with -- then exactly-once is NOT
available at that boundary, and `ExactlyOnceUnavailable` is raised rather than
quietly downgrading the guarantee.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from .canonical import normalize_hash
from .journal import Journal, JournalError


class DeliveryOutcome(str, Enum):
    APPLIED = "APPLIED"        # consumer state moved, ack written, same commit
    DUPLICATE = "DUPLICATE"    # already acknowledged with this exact result; no-op
    CONFLICT = "CONFLICT"      # already acknowledged with a DIFFERENT result


class ResultConflict(JournalError):
    """A second, different result arrived for an already-acknowledged operation."""


class ExactlyOnceUnavailable(JournalError):
    """The consumer cannot commit atomically with the ack, so the guarantee is absent."""


class TransactionalConsumer(Protocol):
    """A native result consumer that can enrol in the journal's transaction.

    `apply` receives the live connection and must perform its state update using it.
    It must NOT open its own transaction, and must NOT perform network I/O: anything
    that cannot be rolled back does not belong inside the commit.
    """

    def apply(self, conn: object, operation_id: str, result_hash: str, payload: str) -> str:
        ...


@dataclass
class ModeledNativeConsumer:
    """A stand-in for the native Almanak result consumer.

    Labelled a MODEL, not the real thing. It exists so the callback/ack boundary can
    be tested at all before P03 wires the actual consumer. It records how many times
    its state was mutated, which is what makes double-application observable in a
    test rather than merely argued about.
    """

    table_ready: bool = False
    applications: int = 0

    def _ensure(self, conn) -> None:  # type: ignore[no-untyped-def]
        if not self.table_ready:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS modeled_consumer_state ("
                "operation_id TEXT PRIMARY KEY, result_hash TEXT NOT NULL, applied_at INTEGER)"
            )
            self.table_ready = True

    def apply(self, conn, operation_id: str, result_hash: str, payload: str) -> str:  # type: ignore[no-untyped-def]
        self._ensure(conn)
        conn.execute(
            "INSERT OR REPLACE INTO modeled_consumer_state(operation_id,result_hash,applied_at)"
            " VALUES(?,?,?)",
            (operation_id, result_hash, int(time.time())),
        )
        self.applications += 1
        return f"applied:{payload}"


def deliver(
    journal: Journal,
    operation_id: str,
    result_hash: str,
    payload: str,
    consumer: TransactionalConsumer,
) -> DeliveryOutcome:
    """Deliver one native result exactly once *at the consumer*.

    Safe to call repeatedly with the same `(operation_id, result_hash)`: that is the
    normal case for an at-least-once channel, and it returns DUPLICATE without
    touching consumer state.
    """
    rhash = normalize_hash(result_hash, "result_hash")
    if not hasattr(consumer, "apply"):
        raise ExactlyOnceUnavailable(
            "consumer cannot enrol in the journal transaction; exactly-once is NOT "
            "available at this boundary and must not be claimed"
        )

    with journal.transaction() as conn:
        row = conn.execute(
            "SELECT result_hash, acked_at FROM results WHERE operation_id=?", (operation_id,)
        ).fetchone()

        if row is not None and row["acked_at"] is not None:
            if row["result_hash"] == rhash:
                return DeliveryOutcome.DUPLICATE
            raise ResultConflict(
                f"operation {operation_id} already acknowledged result {row['result_hash']}; "
                f"refusing to apply a different result {rhash}"
            )

        now = int(time.time())
        if row is None:
            conn.execute(
                "INSERT INTO results(operation_id,result_hash,delivered_at) VALUES(?,?,?)",
                (operation_id, rhash, now),
            )
        elif row["result_hash"] != rhash:
            # Delivered but never acknowledged, and now a different result has
            # arrived. The first delivery provably never reached the consumer
            # (no ack), so replacing it is safe and is recorded.
            conn.execute(
                "UPDATE results SET result_hash=?, delivered_at=? WHERE operation_id=?",
                (rhash, now, operation_id),
            )

        # Consumer state update and acknowledgement, one commit. This is the line
        # that closes the crash window; splitting it reopens it.
        consumer_state = consumer.apply(conn, operation_id, rhash, payload)
        conn.execute(
            "UPDATE results SET acked_at=?, consumer_state=? WHERE operation_id=?",
            (now, consumer_state, operation_id),
        )
        return DeliveryOutcome.APPLIED


def delivery_status(journal: Journal, operation_id: str) -> dict[str, object] | None:
    row = journal._db.execute(  # noqa: SLF001 - read-only accessor for reporting
        "SELECT * FROM results WHERE operation_id=?", (operation_id,)
    ).fetchone()
    return dict(row) if row else None


def unacknowledged(journal: Journal) -> list[str]:
    """Deliveries that must be retried. An at-least-once channel's work queue."""
    return [
        r["operation_id"]
        for r in journal._db.execute(  # noqa: SLF001
            "SELECT operation_id FROM results WHERE acked_at IS NULL"
        ).fetchall()
    ]
