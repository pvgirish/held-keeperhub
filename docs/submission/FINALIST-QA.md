# Finalist Q&A

Short, evidence-backed answers. Where the honest answer is a limitation, it is the
limitation. Claim IDs refer to [`CLAIM-LEDGER.md`](CLAIM-LEDGER.md).

**1. Why not just use Almanak's own recovery?**
Almanak's state machine recovers the *strategy's* view. It does not know what the customer
approved, what the controller recorded as spent, or whether an in-flight submission moved
funds. Held's journal and the controller's `consumed[]` answer those. We use the real pinned
Almanak consumer for acknowledgement (P17) rather than replacing it.

**2. Why not just use Safe + Zodiac Roles?**
We do — they are the enforcement layer, and Held is the sole member of both roles. Roles
bounds *what* may be called and *how much*. It does not record which operation an action
belonged to, whether a retried submission already executed, or carry consumption across a
runner change. That coordination is what Held adds.

**3. What does KeeperHub add?**
Execution as a service: the outer caller/payer, retry semantics and an idempotency contract,
so Held does not run its own broadcast infrastructure. Held keeps the runner's authorization
separate from KeeperHub's execution identity — they are different authorities.

**4. What does Held add?**
Customer-approved limits enforced on chain, an operation identity that survives retries and
restarts, and a handover that refuses to proceed while an outcome is unknown. Concretely:
demo steps 5, 10 and 11.

**5. What if KeeperHub returns UNKNOWN?**
It stays UNKNOWN. Every ambiguous result — timeouts, dropped connections, all 5xx,
unrecognised statuses — maps to UNKNOWN, never to REJECTED (P8). Resolution comes from
reading `consumed[operationId]`, not from the transport. An unknown is not a verified
negative.

**6. What stops duplicate execution?**
The operation is marked DISPATCHED and its exact replayable request is made durable in one
transaction *before* any network I/O, verified by opening a separate connection mid-send and
by SIGKILLing a real child process (P7). A restart resumes the original attempt under its
original idempotency key and makes zero duplicate network calls (P9).

**7. Can the old runner still withdraw directly from Morpho?**
Not through Held: the controller is the sole member of both Zodiac roles, and runner B is
never given a role seat. Whether some *other* authority exists is exactly what the bounded
inventory reports — and if an external Morpho delegate is found, the handover blocks and the
owner decides. Held does not revoke it automatically; it may be legitimate use by another
agent.

**8. How do you know authority discovery is complete?**
We do not claim it is. The inventory is **bounded**: a declared supported profile over a
declared block range. Anything outside is reported as out of scope, which is not the same as
absent. Required configuration that cannot be read is INCOMPLETE and blocks (P15).

**9. What happens when history is incomplete?**
It blocks. A malformed log entry is MALFORMED, not empty; an unreadable allowance is
unreadable, not zero; a truncated module page is truncated, not exhaustive. All three are
regressions added after review found them failing open.

**10. Why does Runner B inherit the remaining budget?**
Because the customer approved a ceiling, not a ceiling per runner. If B started fresh the
cap would silently double. The activation carries the exact consumption the owner saw, and
the controller reverts `StaleActivation` if anything moved in between (P10).

**11. What happens to pre-Held historical usage?**
It is deliberately not imported. A new lineage gets a clearly labelled new budget; the P00
fixture's historical 30,000 is never copied into Held's counters.

**12. Is this audited?** No. Finite adversarial testing is not an audit.

**13. Is this production ready?** No. Fork only, one market, one Safe, no public execution.

**14. What is actually public-chain verified?** **Nothing.** No public deployment, funding or
broadcast has occurred (M1, M2).

**15. What is only fork-tested?** All controller, Roles, Morpho and handover behaviour —
graded REAL LOCAL FORK throughout. An anvil fork has no finality.

**16. Why is Held original?**
The combination: an operation identity that binds the native decision, the on-chain
consumption record and the execution attempt together, so a handover can be *refused* on
evidence rather than performed on hope. We have not found that in Safe/Roles tooling or in
agent frameworks.

**17. What is the strongest native alternative?**
A competent operator using Safe batching, Zodiac Roles with tight conditions, Morpho's own
authorization history and Almanak's recovery. We measured it: fence first, let it settle,
read the consumed allowance, derive the new remaining, activate. It reaches the correct
result on the first attempt.

**18. What did your measured comparison actually show?**
That native is cheaper. From the same 30,000-consumed starting state: clean change native
1 ceremony / 2 signatures / 1 transaction against Held's 2 / 4 / 2. Interrupted change: an
exact tie at 2 / 4 / 2. **We withdrew the claim that Held reduces coordination work** — it
does not. Held cannot batch the fence with the activation, because the controller refuses
to activate while active and Held requires the fence confirmed and the epoch reconciled
first.

What survived measurement: one store answers whether a *specific* operation executed; the
system refuses while that is unknown; and an activation-time consistency guard fired for
real during the run, refusing a ceiling the Zodiac allowance would not have honoured. Held
buys enforcement and per-operation evidence, and charges setup for them.

**19. Why is KeeperHub necessary in the final integration?**
It is the execution layer: the outer caller and payer, retry semantics, and an idempotency
contract, so Held does not run broadcast infrastructure. Held keeps the runner's
authorization separate from KeeperHub's execution identity — they are different authorities
and conflating them would be a security error.

**20. What would make Held unnecessary?**
If KeeperHub exposed a durable, queryable per-operation execution record, and Almanak
carried customer-approved ceilings with on-chain consumption, most of Held's coordination
value would move upstream — which would be a good outcome.
