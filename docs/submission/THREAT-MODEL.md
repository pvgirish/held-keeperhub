# Authority and threat model

What can move the customer's money, who has to agree, and what happens when a step fails
halfway. Written for a reader deciding whether to trust this with funds, not for a reader
being sold something.

Every behavioural claim below is exercised on a real Base-mainnet fork by
`make final-rehearsal` or by a named test. Where something is argued rather than
demonstrated, it says so.

---

## 1. The authority chain

```
Almanak strategy  ──decision──▶  Held admission  ──envelope──▶  runner B (EIP-712)
                                                                     │
                                                              KeeperHub REST
                                                                     │
                                                     HeldController.executeSupply
                                                                     │
                                             Zodiac Roles v2 (5 non-refilling budgets)
                                                                     │
                                                         Safe 1.4.1, 2-of-3
                                                                     │
                                                              Morpho Blue
```

Five parties, and **none of them can move funds alone**:

| Party | Holds | Can it move money by itself? |
|---|---|---|
| Almanak strategy | nothing | No. It produces a decision; Held decides whether it is admissible. |
| Held (the adapter) | nothing | No. It holds no key. It builds calldata and journals. |
| Runner B | one signing key | No. A signature authorizes; it does not execute. It cannot send a transaction and needs no ETH. |
| KeeperHub | the executing wallet | No. It can only call `executeSupply`, and only with a valid runner signature the controller checks. |
| Safe owners | 2 of 3 | **Yes** — they own the Safe. Held's job is to bound what happens *without* them, not to constrain them. |

The customer's protection is not that any single party is trusted. It is that the
controller enforces the owner's stated limits on-chain, and the owner can revoke at any
time without Held's cooperation.

---

## 2. What the owner actually approves

Activation sets a policy the controller enforces on every call:

| | Value approved for M1 | What it bounds |
|---|---|---|
| `Ls` / `Ln` / `Lr` | 50,000 / 50,000 / 10,000 USDC | cumulative ceilings per lane |
| `Ms` / `Mn` / `Mr` | 10 / 100 / 1 USDC | the largest single action |
| `ms` / `mn` | 10 / 1 USDC | the smallest — no dust-griefing |
| `F` | 1.000000 USDC | a floor the Safe may never go below |
| `Nn` / `Nr` | 10 / 5 | how many successful actions, ever |
| `dn` / `dr` | 0 / 0 | cooldown between actions |

All five native Roles budgets are **non-refilling** (`refill = 0`, `period = 0`), verified
by readback in the rehearsal. A spent budget stays spent until an owner re-sets it. There
is no time-based replenishment to wait out.

**The floor is not decorative.** In the rehearsal, funding the Safe with 11 USDC and
supplying 10 leaves exactly 1 — the floor — and the *second* attempt is refused with
`FloorViolated()`. Funding 10 instead of 11 would have reverted at execution, after gas.

---

## 3. Threats, and what stops each one

### 3.1 A compromised runner key

**Stopped.** A runner signature is bounded three ways before it reaches money: the
controller checks the epoch, the policy version and the operation scope; Roles checks the
condition tree and the five budgets; the Safe holds the funds. A stolen key can, at worst,
cause actions the owner already approved, up to the ceilings the owner already set, into
the market the owner already chose. It cannot withdraw to an attacker.

Recovery is one owner ceremony: `fence()` retires the epoch, and every signature made under
it becomes permanently unusable. Rehearsed: a stale runner's attempt reverts
`WrongEpoch(uint64,uint64)` (`0x2b9264ec`), in `evidence/P04/hero-demo-trace.json` step 11.

### 3.2 A compromised or misbehaving KeeperHub

**Bounded, not eliminated.** KeeperHub holds the executing wallet, so it decides *whether*
and *when* a signed action is submitted. It cannot decide *what*: the controller recomputes
the action hash from the arguments it receives and checks the runner's signature over it.

What KeeperHub could still do is censor (refuse to submit) or delay. Held's answer is
detection, not prevention: the journal records a durable claim before any byte leaves, and
an unresolved attempt is visible and blocks a handover until it is reconciled against
`consumed[operationId]` on chain.

**A known gap, stated plainly.** Held sends `functionName`/`functionArgs` and KeeperHub's
server encodes. `ContractCallRequest.verify_encoding()` proves locally that those arguments
produce the calldata the runner signed over, but nothing yet proves KeeperHub's encoder
agrees. That is claim **P19**, and it is **NOT YET ESTABLISHED** — it needs one
authenticated dry run against a deployed controller.

### 3.3 A compromised Held process

**Bounded.** Held holds no key. The worst it can do is build a request — which still needs
a runner signature it cannot produce, and still faces every on-chain check.

### 3.4 Duplicate execution after a crash or timeout

**Stopped, and this is the part that took the most work.** The failure mode is: Held sends,
the connection drops, and nobody knows whether the transaction landed.

- The journal claims the operation as DISPATCHED and persists the exact replayable request
  in **one transaction, before any I/O**. Verified under a real `SIGKILL`.
- An ambiguous outcome is `UNKNOWN`, never "not sent". A later definitive rejection is
  recorded as definitive about the *retry* only.
- `resume()` resends the identical body under the identical `Idempotency-Key`.
- Past the 24-hour idempotency window a resend would be a genuinely new submission, so it
  is **refused** unless chain evidence establishes non-execution — and the only evidence
  that settles it is retirement of the authorization, not a zero reading at one block.
- The controller is the last line: a replayed authorization reverts
  `OperationConsumed(bytes32)` with every counter unmoved. Rehearsed.

### 3.5 A stale or wrong-scope authorization

**Stopped.** Operation identity is derived from chain, controller, Safe and lineage. An
operation admitted under one profile and signed for another is refused before sending —
a defect that actually existed and is now a regression test.

### 3.6 Activation against state that moved underneath it

**Stopped.** `activate` requires the owner's `expected` consumption to equal actual, refuses
a ceiling below what is already spent, and requires the native Roles remaining allowance to
equal `L − used` on **every** dimension. A stale preparation is refused with
`AllowanceDesynchronised`, which fired for real during P06 and is evidence rather than a
bug.

### 3.7 Held broadcasting on a credential that cannot broadcast

**Stopped, as of this pass.** `CredentialCheck.assert_can_broadcast()` existed and had no
production caller: `Submitter.submit` created a journal row, minted an idempotency key and
sent, and only then would a read-only key have earned a 403 — after the operation was
DISPATCHED. The capability is now required **before the first journal mutation**, and every
way of not getting a yes (unset variable, wrong scope, dead network, non-hosted transport)
is the same refusal. 24 tests, including that a refusal leaves the journal byte-identical
and the identical call succeeds later with no repair.

### 3.8 Fork evidence presented as mainnet evidence

**Stopped.** This is a threat to the *reader*, not to the funds, and it is the one this
project has come closest to committing. `make mainnet-evidence-gate` re-reads every record
claiming public Base from a public RPC. A fork transaction is not in Base's history, so it
cannot be confirmed — whatever the file says. 15 tests attack it the way a deadline would.

---

## 4. Recovery and handover

The hero case: runner A dispatched an operation, the outcome is unknown, and the customer
wants a different runner. Naively you would rotate the key and move on — which is how an
in-flight operation gets executed twice.

Held's sequence, durable and restartable at every step
(`packages/handover/held_handover/machine.py`):

```
PROPOSED → FENCE_PREPARED → FENCED → RECONCILED
         → CANDIDATE_PREPARED → CLEARED → ACTIVATION_PREPARED → ACTIVE
```

1. **Refuse while unresolved.** The handover blocks on `UNRESOLVED:<operation id>`, derived
   from the journal rather than asserted.
2. **Fence.** One owner ceremony retires the epoch. Runner A's signatures are now
   permanently unusable — *then* it is safe to reason about what happened.
3. **Reconcile** against `consumed[operationId]` on chain. Not a guess and not a timeout.
4. **Bounded authority inventory** at one stated block, with provenance and missing
   evidence per section. It must be COMPLETE, and a report collected before the fence is
   refused as stale.
5. **Clear** against a typed `AuthorityInventory` whose scope must match this installation.
6. **Activate** the new runner at a higher epoch. **Consumption is preserved across the
   handover** — a new runner does not get a fresh budget.

Rehearsed end to end in `evidence/P04/hero-demo-trace.json`: 12 USDC spent by runner A,
carried across as `[12000000, 0, 0, 1, 0]`, `usedSupply` unchanged at `12000000`, remaining
capacity `49988000000`.

**The replacement export carries no key material.** Credentials are *referenced*
(`env:NAME`), never copied, and the export refuses to be produced at all if checkpoints are
missing, history is unsettled, the digest is a placeholder or the controller is in the
wrong state.

---

## 5. What is deliberately not defended

Stating these is the point; a threat model that lists only solved problems is marketing.

- **Owner collusion.** Two of three owners can do anything. That is the Safe's design and
  Held does not try to constrain it.
- **Morpho or Safe or Zodiac failing.** Held depends on all three. It pins them and tests
  against the real deployed contracts, but it cannot survive a break in them.
- **Oracle manipulation in the chosen market.** Out of scope. The owner chooses the market.
- **KeeperHub censorship.** Detectable, not preventable. See 3.2.
- **KeeperHub's server-side encoder.** P19, unproven. See 3.2.
- **A malicious Almanak strategy.** Bounded by the policy, not prevented. A strategy can
  propose anything; it gets ceilings, floors, counts and one market.
- **Anything outside one Morpho market on Base with native USDC.** One supply path and two
  withdraw lanes. There is deliberately no generic "call the controller with these bytes".

---

## 6. Where each claim is checked

| Section | Evidence |
|---|---|
| 3.1 stale runner | `evidence/P04/hero-demo-trace.json` step 11 |
| 3.2 wire contract | `tests/integration/test_p03_keeperhub.py` — 46 pass |
| 3.4 crash/restart | `test_p03_submit.py` 18, `test_p03_recovery.py` 20 |
| 3.4 replay on chain | `make final-rehearsal` — `OperationConsumed(bytes32)` |
| 3.5 scope binding | `test_p03_submit.py`, scope-mismatch refusal |
| 3.6 activation guards | `make check-phase-02`, `evidence/P06/comparison.json` |
| 3.7 broadcast scope | `tests/integration/test_p03_broadcast_capability.py` — 24 pass |
| 3.8 evidence grading | `tests/integration/test_mainnet_evidence_gate.py` — 15 pass |
| §2 budgets, §4 floor | `make final-rehearsal` — 14/14 claims matched |
| §4 handover | `make hero-demo`, `tests/handover/test_handover_machine.py` — 39 pass |

All of it is `REAL LOCAL FORK` or below. **Nothing here has been proven on public Base**,
and §3.8 exists to keep that sentence true.
