"""One operation, from an admitted native bundle to a reconciled on-chain outcome.

This is where the pieces meet: the interceptor's `AdmittedOperation`, the runner
signature, the durable journal and the KeeperHub client. The ordering between them is
the safety argument, so it lives here rather than in a caller's head.

## Four defects this module was rebuilt to fix

**C2 — a pending attempt did not make the operation non-sendable.** The old code
committed a PENDING attempt but left the operation AUTHORIZED, and moved it to DISPATCHED
only after the network call returned. A crash in between left an AUTHORIZED operation
with a PENDING attempt; the next `submit()` accepted that state, minted a fresh attempt
id and a fresh idempotency key, and sent a second unprotected request for work that may
already have executed. Dispatch is now an atomic CLAIM (`Journal.claim_for_dispatch`)
that moves the operation and persists the exact request in one transaction, and a
restart RESUMES the original attempt under its original key instead of starting a new
one.

**C3 — the signature was not bound to the request.** `submit()` used to take `admitted`,
`envelope` and an arbitrary `calldata` string, sign the envelope, and then send whatever
calldata it was handed. Nothing checked they corresponded. The request is no longer
supplied: it is CONSTRUCTED from the verified admitted action and exactly the signature
just produced, and the arguments are re-encoded and compared byte for byte before
anything leaves.

**C4 — reconciliation trusted a caller-supplied hash.** It loaded the journal operation
and then compared the chain marker against its `payload_hash` ARGUMENT, so a caller
passing Q for an operation durably bound to P could drive CONFIRMED off a marker of Q.
The durable binding is now authoritative and a caller disagreeing with it is an error.

**C1** lives in `keeperhub.py`: the documented wire contract.

## The order, and why each step is where it is

1. **Create or reopen** the operation. Reopening is what makes a restart continue an
   operation instead of minting a new one.
2. **Resume first.** If an unresolved attempt exists, that attempt is the only thing
   that may proceed. Never start a second one.
3. **Sign**, then build the one permitted controller call from that signature.
4. **Claim atomically** — operation state and the exact replayable request commit
   together, before any network I/O.
5. **Send**, then record what came back.
6. **Reconcile against the chain**, not against KeeperHub's word.

## Step 6 is the one that is easy to get wrong

An execution id is not an outcome and a transaction hash is not a success: a transaction
can be mined having reverted. The only evidence that this operation executed is the
controller's `consumed[operationId]`, which is written in the same transaction as the
economic effect, compared for equality with the payload hash the journal durably bound.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Protocol, Sequence

from held_core import identity
from held_core.canonical import hex32
from held_core.journal import Journal, OperationState, StateTransitionError

from .controller_abi import build_execute_call, function_abi
from .keeperhub import (
    IDEMPOTENCY_WINDOW_SECONDS,
    ContractCallRequest,
    KeeperHubClient,
    SendOutcome,
    SendResult,
    execution_key,
)


class SubmissionError(Exception):
    """The submission could not proceed safely."""


class NotReconcilable(SubmissionError):
    """There is no chain evidence available, so no verdict may be reported."""


class ResumeRequired(SubmissionError):
    """An unresolved attempt exists. Resume or reconcile it; do not start another."""

    def __init__(self, attempt: dict[str, Any], message: str) -> None:
        super().__init__(message)
        self.attempt = attempt


@dataclass(frozen=True)
class ChainEvidence:
    """A consumption reading, with the scope that makes it meaningful.

    A bare marker string is not evidence. The same 32 bytes read from the wrong chain or
    the wrong controller says nothing about this operation, and a reading from an
    unfinalized block can be reorganised away. The reader must state all of it.
    """

    marker: str
    chain_id: int
    controller: str
    block_number: int
    block_hash: str
    finalized: bool
    # The controller's CURRENT epoch. A zero marker says an operation was not consumed at
    # one observation point; it does not say the original transaction can never land. The
    # only thing that settles that is retirement of the authorization it was signed under,
    # and the controller's epoch is what shows it.
    controller_epoch: int | None = None

    @property
    def empty(self) -> bool:
        return int(self.marker, 16) == 0

    def retires(self, envelope_epoch: int) -> bool:
        """True when this reading proves an envelope of that epoch can never execute."""
        return self.controller_epoch is not None and self.controller_epoch > envelope_epoch


class ChainReader(Protocol):
    """The minimum chain access reconciliation needs."""

    def consumed(self, controller: str, operation_id: str) -> ChainEvidence: ...


# States from which a NEW send is permissible. CONFIRMED is absent because it is
# terminal. DISPATCHED and UNKNOWN are absent because an outstanding or unknown attempt
# must be resumed or reconciled, never duplicated.
_SENDABLE = frozenset({OperationState.CREATED, OperationState.AUTHORIZED, OperationState.FAILED})

_OUTCOME_TO_STATE = {
    SendOutcome.ACCEPTED: OperationState.DISPATCHED,
    SendOutcome.IN_PROGRESS: OperationState.DISPATCHED,
    SendOutcome.REJECTED: OperationState.FAILED,
    SendOutcome.UNKNOWN: OperationState.UNKNOWN,
    # A key reused with a different body means our own request is not deterministic.
    # The outcome of the ORIGINAL body is unknown, so the operation stays blocked.
    SendOutcome.IDEMPOTENCY_CONFLICT: OperationState.UNKNOWN,
}


@dataclass(frozen=True)
class Submission:
    """What happened to one attempt. Carries provenance, not conclusions."""

    operation_id: str
    attempt_id: str
    execution_key: str
    send: SendResult
    journal_state: OperationState
    resumed: bool = False

    @property
    def needs_reconciliation(self) -> bool:
        return self.journal_state in (OperationState.DISPATCHED, OperationState.UNKNOWN)

    def to_record(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "attempt_id": self.attempt_id,
            "idempotency_key": self.execution_key,
            "outcome": self.send.outcome.value,
            "journal_state": self.journal_state.value,
            "resumed": self.resumed,
            "hosted": self.send.hosted,
            "execution_id": self.send.execution_id,
            "tx_hash": self.send.tx_hash,
            "status_code": self.send.status_code,
            "error_code": self.send.error_code,
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
        market_params: Sequence[Any],
        *,
        new_attempt_id: Callable[[], str] = lambda: uuid.uuid4().hex,
        now: Callable[[], float] = None,
    ) -> None:
        import time

        self.journal = journal
        self.client = client
        self.signer = signer
        self.controller = controller
        self.chain_id = chain_id
        self.market_params = tuple(market_params)
        self._new_attempt_id = new_attempt_id
        self._now = now or time.time

    # ------------------------------------------------------------------ sending --
    def _require_consistent_scope(self, admitted, envelope) -> None:
        """The admitted operation and the envelope must belong to the SAME scope.

        `operation_id()` binds chain, controller, Safe and lineage. Admitting under one
        profile and then signing an envelope for another produces a well-formed signature
        over an id that was never minted for that deployment: the controller accepts it,
        while Held's own business identity is wrong.

        That is not hypothetical -- the composed test did exactly this, admitting against
        a profile whose controller and lineage differed from the deployed controller it
        then signed for. Comparing copied ids, payload hashes and families did not catch
        it, because all three were copied from the same place.
        """
        expected = identity.operation_id(
            envelope.scope, admitted.source_decision_id, admitted.action_index)
        if bytes(expected) != bytes(admitted.operation_id):
            raise SubmissionError(
                "scope mismatch: the admitted operation id does not derive from the "
                "envelope's scope.\n"
                f"  envelope scope : chain {envelope.scope.chain_id}, controller "
                f"{envelope.scope.controller}, safe {envelope.scope.safe}, lineage "
                f"{envelope.scope.lineage}\n"
                f"  admitted id    : {hex32(admitted.operation_id)}\n"
                f"  derives to     : {hex32(expected)}\n"
                "Admit and sign under ONE profile built from the verified deployment "
                "context.")
        if envelope.scope.chain_id != self.chain_id:
            raise SubmissionError(
                f"the envelope is scoped to chain {envelope.scope.chain_id} but this "
                f"submitter targets chain {self.chain_id}")
        if envelope.scope.controller.lower() != self.controller.lower():
            raise SubmissionError(
                f"the envelope is scoped to controller {envelope.scope.controller} but "
                f"this submitter targets {self.controller}")

    def submit(self, admitted, envelope, *, attempt_id: str | None = None) -> Submission:
        """Journal, sign, build the call, claim atomically, send, record.

        There is no `calldata` parameter. The request is derived from the admitted action
        and the signature produced here, so the submitted call and the signed
        authorization cannot be two unrelated objects.
        """
        self._require_consistent_scope(admitted, envelope)
        operation_id = hex32(admitted.operation_id)
        payload_hash = hex32(admitted.payload_hash)

        op = self.journal.create_or_reopen(
            operation_id, payload_hash, admitted.source_decision_id,
            admitted.action_index, envelope.epoch)

        if op.state is OperationState.CONFIRMED:
            raise SubmissionError(
                f"operation {operation_id} is CONFIRMED. It executed on chain; recover "
                "its result, never re-execute it.")

        # An unresolved attempt is the ONLY thing that may proceed for this operation.
        outstanding = self.journal.unresolved_attempt(operation_id)
        if outstanding is not None:
            raise ResumeRequired(
                outstanding,
                f"operation {operation_id} has an unresolved attempt "
                f"{outstanding['attempt_id']} whose outcome is not known. Call resume() "
                "to resend the identical request under its original idempotency key, or "
                "reconcile against the chain. Starting a second submission here is how "
                "one operation gets executed twice.")

        if op.state not in _SENDABLE:
            raise SubmissionError(
                f"operation {operation_id} is {op.state.value}; a send is not permitted "
                "from that state. An UNKNOWN outcome is resolved with chain evidence, "
                "not by sending again.")

        auth = self.signer.sign(envelope)
        if op.state is not OperationState.AUTHORIZED:
            self.journal.transition(operation_id, OperationState.AUTHORIZED, epoch=envelope.epoch)

        function_name, args, calldata = build_execute_call(
            admitted, envelope, auth.signature, self.market_params)

        attempt = attempt_id or self._new_attempt_id()
        key = execution_key(admitted.operation_id, attempt)
        request = ContractCallRequest(
            chain_id=self.chain_id,
            contract_address=self.controller,
            function_name=function_name,
            function_args=args,
            abi=function_abi(function_name),
            expected_calldata=calldata,
            simulate=False)
        request.verify_encoding()
        body = json.dumps(request.to_payload(), sort_keys=True)

        # Atomic: the operation becomes DISPATCHED and the exact replayable request is
        # persisted in ONE transaction, before any byte leaves the process.
        self.journal.claim_for_dispatch(
            attempt_id=attempt,
            operation_id=operation_id,
            envelope_hash=hex32(auth.signing_hash),
            epoch=envelope.epoch,
            runner=auth.runner,
            signer_ref=auth.signer_ref,
            idempotency_key=key,
            request_body=body,
            calldata=calldata,
            kind="BROADCAST")

        result = self.client.broadcast(request, key)
        return self._record(operation_id, attempt, key, result, envelope.epoch, resumed=False)

    def dry_run(self, admitted, envelope) -> Submission:
        """Simulate. Never claims the operation and never becomes an economic attempt."""
        self._require_consistent_scope(admitted, envelope)
        operation_id = hex32(admitted.operation_id)
        auth = self.signer.sign(envelope)
        function_name, args, calldata = build_execute_call(
            admitted, envelope, auth.signature, self.market_params)
        request = ContractCallRequest(
            chain_id=self.chain_id, contract_address=self.controller,
            function_name=function_name, function_args=args, abi=function_abi(function_name),
            expected_calldata=calldata, simulate=True)
        result = self.client.dry_run(request)
        op = self.journal.get(operation_id)
        return Submission(operation_id, "(simulation)", "", result,
                          op.state if op else OperationState.CREATED)

    def resume(self, operation_id: str, chain: ChainReader | None = None) -> Submission:
        """Resume the unresolved attempt under its ORIGINAL idempotency key.

        This is the restart path. It resends the IDENTICAL persisted body under the
        IDENTICAL key, which is what makes the retry idempotent at the provider rather
        than a second submission wearing a new name.

        Past the documented 24-hour idempotency window the server no longer dedupes, so a
        resend would be a genuinely new submission. Beyond the window this refuses unless
        chain evidence has established non-execution.
        """
        op = self.journal.get(operation_id)
        if op is None:
            raise SubmissionError(f"unknown operation {operation_id}")

        # TERMINAL FIRST, before anything reaches the network. An operation can be
        # CONFIRMED while an older attempt is still live -- reconciliation used to settle
        # the operation without settling its attempt -- and resuming then sent work
        # already known to be complete. The prohibited state transition was caught, but
        # only AFTER the outbound call decision, which is far too late.
        if op.state is OperationState.CONFIRMED:
            settled = self.journal.settle_live_attempts(operation_id, "CONFIRMED")
            raise SubmissionError(
                f"operation {operation_id} is CONFIRMED: it executed on chain. Nothing to "
                f"resume. {len(settled)} stale attempt(s) settled. Recover its result; "
                "never re-execute it.")
        if op.state is OperationState.FAILED:
            raise SubmissionError(
                f"operation {operation_id} is FAILED: definitively not executed. Do not "
                "resume the old request; reauthorize the SAME id and payload under a new "
                "epoch.")

        attempt = self.journal.unresolved_attempt(operation_id)
        if attempt is None:
            raise SubmissionError(f"operation {operation_id} has no unresolved attempt to resume")

        # An ACCEPTED or IN_PROGRESS attempt is already with the executor. Resending it
        # is not recovery, it is a second submission; poll and reconcile instead.
        if attempt["state"] in ("ACCEPTED", "IN_PROGRESS"):
            raise SubmissionError(
                f"attempt {attempt['attempt_id']} is {attempt['state']}: the executor has "
                "it. Poll its execution and reconcile against the chain; do not resend.")

        age = self._now() - float(attempt["created_at"])
        # >= not >: at exactly the documented window the provider may already have
        # dropped the key, and being one second early costs nothing while being one
        # second late costs an unprotected duplicate submission.
        if age >= IDEMPOTENCY_WINDOW_SECONDS:
            # Past the documented window the provider no longer dedupes, so a resend is a
            # genuinely NEW submission and the idempotency key protects nothing.
            if chain is None:
                raise NotReconcilable(
                    f"attempt {attempt['attempt_id']} is {int(age)}s old, beyond the "
                    f"{IDEMPOTENCY_WINDOW_SECONDS}s idempotency window, so KeeperHub will "
                    "no longer dedupe it. Read consumed[operationId] before any resend.")
            evidence = chain.consumed(self.controller, operation_id)
            self._check_scope(evidence)

            if not evidence.empty:
                # It executed. Resolve it rather than resending.
                self.reconcile(operation_id, op.payload_hash, chain)
                raise SubmissionError(
                    f"operation {operation_id} already executed on chain; resolved "
                    "instead of resending.")

            # Zero marker. This is where the previous version fell through and resent,
            # which was wrong: "not consumed at block N" is not "cannot be consumed at
            # block N+1". The original transaction may still be pending, and outside the
            # dedupe window a resend would be a genuinely separate submission of the same
            # economic action.
            #
            # The only evidence that settles it is RETIREMENT of the authorization: once
            # the controller's epoch has advanced past the envelope's, that signature can
            # never execute, so non-execution is definite.
            if evidence.retires(int(attempt["epoch"])):
                self.journal.settle_attempt(attempt["attempt_id"], "RETIRED")
                self.journal.transition(operation_id, OperationState.FAILED,
                                        epoch=int(attempt["epoch"]))
                raise SubmissionError(
                    f"operation {operation_id} definitely did not execute: it was "
                    f"authorized under epoch {attempt['epoch']} and the controller is now "
                    f"at epoch {evidence.controller_epoch}, so that signature can never "
                    "execute. The attempt is retired and the operation is FAILED. "
                    "Reauthorize the SAME id and payload under the current epoch; do not "
                    "resend the old request, which would revert on the epoch check.")

            raise NotReconcilable(
                f"operation {operation_id} is not consumed at finalized block "
                f"{evidence.block_number}, but its authorization (epoch "
                f"{attempt['epoch']}) has NOT been retired"
                + (f" -- the controller is still at epoch {evidence.controller_epoch}"
                   if evidence.controller_epoch is not None
                   else " and the reader did not report the controller epoch")
                + ". A zero marker at one observation point is not proof the original "
                "transaction cannot still land, and past the idempotency window a resend "
                "would be a SECOND submission rather than a deduplicated retry. Fence and "
                "advance the epoch to retire the authorization, then reauthorize the same "
                "id and payload. Remaining blocked.")

        body = json.loads(attempt["request_body"])
        request = _request_from_payload(body, attempt["calldata"])
        request.verify_encoding()
        result = self.client.broadcast(request, attempt["idempotency_key"])
        return self._record(operation_id, attempt["attempt_id"], attempt["idempotency_key"],
                            result, op.epoch, resumed=True)

    def _record(self, operation_id: str, attempt: str, key: str, result: SendResult,
                epoch: int, *, resumed: bool) -> Submission:
        self.journal.record_send_result(
            attempt,
            keeperhub_execution_id=result.execution_id,
            tx_hash=result.tx_hash,
            state=result.outcome.value)
        target = _OUTCOME_TO_STATE[result.outcome]
        current = self.journal.get(operation_id).state

        # A request-level rejection is definitive about THIS request only. If the
        # operation was already UNKNOWN, some EARLIER submission may have reached the
        # chain, and a 401 on a later retry -- a revoked credential, say -- says nothing
        # about it. Collapsing that to FAILED would licence reauthorizing an operation
        # that might already have executed.
        if (result.outcome is SendOutcome.REJECTED
                and current is OperationState.UNKNOWN):
            target = OperationState.UNKNOWN
        if target is not current:
            try:
                self.journal.transition(operation_id, target, epoch=epoch)
                current = target
            except StateTransitionError:
                # The journal forbids it, and it is right to. The case that reaches here
                # is a resumed send succeeding while the operation is UNKNOWN: an unknown
                # outcome has no automatic exit, because "the resend was accepted" is not
                # evidence about what the ORIGINAL send did. The attempt row records what
                # happened; the operation stays put until reconcile() reads the chain.
                pass
        return Submission(operation_id, attempt, key, result, current, resumed=resumed)

    # ------------------------------------------------------------ reconciliation --
    def _check_scope(self, evidence: ChainEvidence) -> None:
        if evidence.chain_id != self.chain_id:
            raise NotReconcilable(
                f"chain evidence is from chain {evidence.chain_id}, not {self.chain_id}. "
                "The same 32 bytes on another chain says nothing about this operation.")
        if evidence.controller.lower() != self.controller.lower():
            raise NotReconcilable(
                f"chain evidence is from controller {evidence.controller}, not "
                f"{self.controller}.")
        if not evidence.finalized:
            raise NotReconcilable(
                f"evidence at block {evidence.block_number} ({evidence.block_hash}) is not "
                "finalized and can still be reorganised. An unfinalized reading is not a "
                "verdict.")

    def reconcile(self, operation_id: str, payload_hash: str,
                  chain: ChainReader | None) -> OperationState:
        """Settle an operation against the CHAIN, using the journal's durable binding.

        `payload_hash` is the caller's EXPECTATION and is checked against the journal
        rather than used in its place. The previous version compared the chain marker to
        this argument directly, so a caller supplying the wrong value could make a
        matching marker drive CONFIRMED.
        """
        op = self.journal.get(operation_id)
        if op is None:
            raise SubmissionError(f"unknown operation {operation_id}")
        if payload_hash is not None and payload_hash.lower() != op.payload_hash.lower():
            raise SubmissionError(
                f"caller expected payload {payload_hash} but operation {operation_id} is "
                f"durably bound to {op.payload_hash}. Refusing to reconcile against an "
                "expectation that disagrees with the journal.")
        if op.state is OperationState.CONFIRMED:
            return op.state

        if chain is None:
            raise NotReconcilable(
                f"no chain reader for {operation_id}: without reading "
                "consumed[operationId] there is no evidence this operation executed, and "
                "the executor's own status is not a substitute.")

        evidence = chain.consumed(self.controller, operation_id)
        self._check_scope(evidence)

        if evidence.empty:
            # Only a definitively-refused send makes an empty marker mean "did not
            # execute". Otherwise the transaction may still be in flight.
            if op.state is OperationState.FAILED:
                return op.state
            raise NotReconcilable(
                f"operation {operation_id} is not consumed at finalized block "
                f"{evidence.block_number}, but its send was not definitively refused "
                f"(state {op.state.value}). It may still be in flight; resolve it by "
                "re-reading, not by declaring it failed.")

        if evidence.marker.lower() != op.payload_hash.lower():
            raise SubmissionError(
                f"operation {operation_id} was consumed on chain carrying payload "
                f"{evidence.marker}, not {op.payload_hash}. This id executed a DIFFERENT "
                "action.")

        state = self.journal.transition(operation_id, OperationState.CONFIRMED).state
        # Settle the attempts in the same breath. A live attempt under a CONFIRMED
        # operation is exactly what resume() would pick up and resend.
        self.journal.settle_live_attempts(operation_id, "CONFIRMED")
        return state

    def resolve_in_progress(self, submission: Submission, chain: ChainReader | None):
        """Poll an in-flight execution, then reconcile against the chain regardless.

        Polling is for liveness, not for truth: whatever KeeperHub reports, the verdict
        comes from `consumed[operationId]`.
        """
        if submission.send.execution_id:
            self.client.poll(submission.send.execution_id)
        op = self.journal.get(submission.operation_id)
        if op is None:
            raise SubmissionError(f"unknown operation {submission.operation_id}")
        return self.reconcile(submission.operation_id, op.payload_hash, chain)


def _request_from_payload(body: dict[str, Any], calldata: str) -> ContractCallRequest:
    """Rebuild the exact persisted request. Nothing is recomputed or refreshed."""
    return ContractCallRequest(
        chain_id=int(body["chainId"]),
        contract_address=body["contractAddress"],
        function_name=body["functionName"],
        function_args=json.loads(body["functionArgs"]),
        abi=json.loads(body["abi"]),
        expected_calldata=calldata,
        value_ether=body.get("value", "0"),
        simulate=bool(body.get("simulate", False)),
    )
