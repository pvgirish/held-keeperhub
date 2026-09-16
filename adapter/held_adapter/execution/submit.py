"""One operation, from an admitted native bundle to a reconciled on-chain outcome.

This is where the pieces meet: the interceptor's `AdmittedOperation`, the runner
signature, the durable journal and the KeeperHub client. It exists because the ordering
between them is the whole safety argument, and ordering that lives only in a caller's
head gets reordered.

## The order, and why each step is where it is

1. **Create or reopen** the operation in the journal. Reopening is what makes a restart
   continue an operation instead of minting a new one.
2. **Sign**, then record AUTHORIZED. Signing before journaling the attempt is safe: a
   signature that is never sent authorizes nothing.
3. **Record the attempt, before any network I/O.** A crash after this and before the
   send leaves a row with no execution id, which recovery must read as "outcome
   unknown". That is strictly safer than the alternative ordering, where a crash after
   sending but before journaling leaves a broadcast nobody knows about.
4. **Send.**
5. **Record what came back**, mapping the send outcome onto the journal's states:

       ACCEPTED    -> DISPATCHED   KeeperHub owns it; the chain has not spoken yet
       IN_PROGRESS -> DISPATCHED   already in flight under this key; poll, do not resend
       REJECTED    -> FAILED       definitively not executed; the id may be reauthorized
       UNKNOWN     -> UNKNOWN      blocked, by design, until evidence resolves it

6. **Reconcile against the chain**, not against KeeperHub's word.

## Step 6 is the one that is easy to get wrong

An execution id is not an outcome and a transaction hash is not a success: a transaction
can be mined having reverted. The only evidence that this operation executed is the
controller's own `consumed[operationId]`, which the controller sets in the same
transaction as the economic effect. So `reconcile()` reads that, and requires it to
equal the payload hash this operation was created with.

That last equality matters as much as the presence check. `consumed[id] != 0` would say
"this id was used"; `consumed[id] == payload_hash` says "this id was used for THIS
action". Without it, an id consumed by a different payload would reconcile as success.

A caller that cannot read the chain gets no verdict. `reconcile()` refuses rather than
falling back to KeeperHub's status, because "the executor said it worked" is exactly the
inference V4 §5 forbids.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from held_core.canonical import hex32
from held_core.journal import Journal, OperationState

from .keeperhub import (
    ContractCallRequest,
    KeeperHubClient,
    KeeperHubError,
    SendOutcome,
    SendResult,
    execution_key,
)


class SubmissionError(Exception):
    """The submission could not proceed safely."""


class NotReconcilable(SubmissionError):
    """There is no chain evidence available, so no verdict may be reported."""


class ChainReader(Protocol):
    """The minimum chain access reconciliation needs.

    Deliberately tiny and injected: reconciliation must work against a fork, a public
    RPC or a node, and must not drag a particular web3 stack into this module.
    """

    def consumed(self, controller: str, operation_id: str) -> str:
        """Return `consumed[operationId]` as 0x-prefixed 32-byte hex."""


# The states from which a fresh send is permissible. CONFIRMED is absent because it is
# terminal: re-executing a consumed operation is the failure this project exists to
# prevent. UNKNOWN is absent because an unknown outcome must be resolved with evidence,
# never by trying again and hoping.
_SENDABLE = frozenset({OperationState.CREATED, OperationState.AUTHORIZED, OperationState.FAILED})

_OUTCOME_TO_STATE = {
    SendOutcome.ACCEPTED: OperationState.DISPATCHED,
    SendOutcome.IN_PROGRESS: OperationState.DISPATCHED,
    SendOutcome.REJECTED: OperationState.FAILED,
    SendOutcome.UNKNOWN: OperationState.UNKNOWN,
}


@dataclass(frozen=True)
class Submission:
    """What happened to one attempt. Carries provenance, not conclusions."""

    operation_id: str
    attempt_id: str
    execution_key: str
    send: SendResult
    journal_state: OperationState

    @property
    def needs_reconciliation(self) -> bool:
        return self.journal_state in (OperationState.DISPATCHED, OperationState.UNKNOWN)

    def to_record(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "attempt_id": self.attempt_id,
            "execution_key": self.execution_key,
            "outcome": self.send.outcome.value,
            "journal_state": self.journal_state.value,
            "hosted": self.send.hosted,
            "execution_id": self.send.execution_id,
            "tx_hash": self.send.tx_hash,
            "status_code": self.send.status_code,
            "attempts_made": self.send.attempts_made,
            "error": self.send.error,
        }


class Submitter:
    """Drives one operation through the journal and the executor."""

    def __init__(
        self,
        journal: Journal,
        client: KeeperHubClient,
        signer,
        controller: str,
        chain_id: int,
        *,
        new_attempt_id: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self.journal = journal
        self.client = client
        self.signer = signer
        self.controller = controller
        self.chain_id = chain_id
        self._new_attempt_id = new_attempt_id

    # ------------------------------------------------------------------ sending --
    def submit(
        self,
        admitted,
        envelope,
        calldata: str,
        *,
        dry_run: bool = False,
        attempt_id: str | None = None,
    ) -> Submission:
        """Journal, sign, journal the attempt, send, then journal the answer."""
        operation_id = hex32(admitted.operation_id)
        payload_hash = hex32(admitted.payload_hash)

        op = self.journal.create_or_reopen(
            operation_id, payload_hash, admitted.source_decision_id,
            admitted.action_index, envelope.epoch,
        )
        if op.state is OperationState.CONFIRMED:
            raise SubmissionError(
                f"operation {operation_id} is CONFIRMED. It executed on chain; recover "
                "its result, never re-execute it."
            )
        if op.state not in _SENDABLE:
            raise SubmissionError(
                f"operation {operation_id} is {op.state.value}; a send is not permitted "
                "from that state. An UNKNOWN outcome is resolved with chain evidence, "
                "not by sending again."
            )

        auth = self.signer.sign(envelope)
        if op.state is not OperationState.AUTHORIZED:
            self.journal.transition(operation_id, OperationState.AUTHORIZED, epoch=envelope.epoch)

        attempt = attempt_id or self._new_attempt_id()
        key = execution_key(admitted.operation_id, attempt)

        # BEFORE any network I/O. A crash between here and the send must look like
        # "outcome unknown", not like "nothing was sent".
        self.journal.record_attempt_before_send(
            attempt_id=attempt,
            operation_id=operation_id,
            envelope_hash=hex32(auth.signing_hash),
            epoch=envelope.epoch,
            runner=auth.runner,
            signer_ref=auth.signer_ref,  # a reference; the journal refuses key material
        )

        request = ContractCallRequest(
            chain_id=self.chain_id,
            to=self.controller,
            calldata=calldata,
            execution_key=key,
            operation_id=operation_id,
            attempt_id=attempt,
        )

        result = self.client.dry_run(request) if dry_run else self.client.broadcast(request)

        if dry_run:
            # A dry run is not an attempt at execution. It must not move the operation
            # towards DISPATCHED, and it never consumes anything.
            self.journal.record_send_result(attempt, state="DRY_RUN")
            return Submission(operation_id, attempt, key, result, op.state)

        self.journal.record_send_result(
            attempt,
            keeperhub_execution_id=result.execution_id,
            tx_hash=result.tx_hash,
            state=result.outcome.value,
        )

        # A send was attempted, so the operation is DISPATCHED first -- "handed to the
        # executor, outcome not yet known" is exactly true the moment the request left.
        # The journal does not allow AUTHORIZED -> UNKNOWN directly, and it is right not
        # to: an unknown outcome is a refinement of having dispatched, not an
        # alternative to it.
        self.journal.transition(operation_id, OperationState.DISPATCHED, epoch=envelope.epoch)
        state = _OUTCOME_TO_STATE[result.outcome]
        if state is not OperationState.DISPATCHED:
            self.journal.transition(operation_id, state, epoch=envelope.epoch)
        return Submission(operation_id, attempt, key, result, state)

    # ------------------------------------------------------------ reconciliation --
    def reconcile(
        self, operation_id: str, payload_hash: str, chain: ChainReader | None
    ) -> OperationState:
        """Settle an operation against the CHAIN, never against KeeperHub's word.

        An execution id is not an outcome and a mined transaction is not a success: a
        transaction can revert and still be mined. The controller's
        `consumed[operationId]` is written in the same transaction as the economic
        effect, so it is the only thing that answers the question.
        """
        if chain is None:
            raise NotReconcilable(
                f"no chain reader for {operation_id}: without reading "
                "consumed[operationId] there is no evidence this operation executed, "
                "and the executor's own status is not a substitute."
            )

        op = self.journal.get(operation_id)
        if op is None:
            raise SubmissionError(f"unknown operation {operation_id}")
        if op.state is OperationState.CONFIRMED:
            return op.state

        marker = chain.consumed(self.controller, operation_id)
        empty = "0x" + "00" * 32

        if marker == empty:
            # Nothing consumed this id. That is only a definite non-execution if the
            # send itself was definitively refused; otherwise the transaction may still
            # be in flight, and UNKNOWN is the honest state.
            if op.state is OperationState.FAILED:
                return op.state
            raise NotReconcilable(
                f"operation {operation_id} is not consumed on chain, but its send was "
                f"not definitively refused (state {op.state.value}). It may still be in "
                "flight; resolve it by re-reading, not by declaring it failed."
            )

        if marker.lower() != payload_hash.lower():
            # The id was consumed by something else. Reporting success here would be
            # the exact confusion the payload binding exists to prevent.
            raise SubmissionError(
                f"operation {operation_id} was consumed on chain carrying payload "
                f"{marker}, not {payload_hash}. This id executed a DIFFERENT action."
            )

        return self.journal.transition(operation_id, OperationState.CONFIRMED).state

    def resolve_in_progress(self, submission: Submission, chain: ChainReader | None):
        """Poll an in-flight execution, then reconcile against the chain regardless.

        Polling is for liveness, not for truth: whatever KeeperHub reports, the verdict
        still comes from `consumed[operationId]`.
        """
        if submission.send.execution_id:
            self.client.poll(submission.send.execution_id)
        op = self.journal.get(submission.operation_id)
        if op is None:
            raise SubmissionError(f"unknown operation {submission.operation_id}")
        return self.reconcile(submission.operation_id, op.payload_hash, chain)
