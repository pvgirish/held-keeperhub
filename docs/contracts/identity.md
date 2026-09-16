# Identity, journal and result contract (P01)

Status: implemented, `make check-phase-01` → 31/31. **Not independently reviewed.**

Conformance vectors: `vectors/canonical-vectors.json`. An independent implementation
reproduces those bytes and hashes or it is not interoperable.

## The three identities, and why they are separate

V4 §4 names three. Collapsing any two is the failure this document exists to prevent.

| | what it identifies | includes epoch/runner? |
|---|---|---|
| **Business operation ID** | one action of one native decision | **No** |
| **Authorization envelope** | permission to attempt it *now* | **Yes** |
| **Transaction / API attempt** | evidence about one try | n/a — never a business identity |

### Why the operation ID excludes the runner

This is the load-bearing decision. If the runner were in the preimage, replacing
operator A with B would mint a *fresh* ID for the same business operation — and the
consumed-ID check would stop protecting anything across exactly the handover it exists
to survive. V4 §4 puts it directly: *"Its consumed identity does not reset when an epoch
or runner changes."*

```
operation_id = keccak256(canonical{
    schema, scope{chain_id, controller, safe, lineage}, source_decision_id, action_index
})
```

The envelope then binds epoch, policy version and runner, so an envelope signed under
epoch N is worthless under N+1 even though the operation ID is unchanged. Vector
`epoch_runner_independence` asserts both halves: identical ID, different signing hash.

`operation_id()` is a **pure function**, so a restart that reloads the same source
decision recomputes the same ID rather than manufacturing a new one.

## Canonical encoding

Every hash is taken over these bytes, so two implementations that disagree here
disagree about identity.

1. UTF-8, no BOM. 2. Keys sorted by code point. 3. Separators exactly `,` and `:`.
4. **Integers are decimal strings, never JSON numbers.** 5. No floats — rejected by the
encoder, not by convention. 6. Addresses lower-cased. 7. Schema version inside every
hashed object.

Rule 4 is not pedantry: a uint256 does not survive an IEEE-754 double, so a JavaScript
consumer using default numbers would silently compute a different operation ID. The
encoder raises on a raw `int` to make that impossible rather than merely discouraged.

Rule 6 matters because EIP-55 checksums encode meaning in the *case* of hex digits.
Identity must not depend on how a caller capitalised an address.

## Units

Unsigned base units only. `bool` is rejected explicitly — in Python
`isinstance(True, int)` is true, so a policy field accepting `True` as `1` is a live
hazard. There is no "unlimited" sentinel. Zero is legitimate and means a lane is
disabled (V4 §5), so zero is never read as "unset".

`HOLD` carries amount 0 and is **never** authorized for execution: V4 §5 says a HOLD is
"no executable economic call, consumed operation or transaction claim", so there is
nothing for a runner to sign. A non-HOLD action with amount 0 is rejected as a
mislabelled HOLD.

## Journal state machine

```
CREATED ──▶ AUTHORIZED ──▶ DISPATCHED ──▶ CONFIRMED   (terminal — never re-execute)
   │            │               ├───────▶ FAILED      (definite non-execution)
   │            └───────────────┤               │
   └────────────────────────────┴──▶ UNKNOWN    │      (blocked — no automatic exit)
                                        │       │
                                        └──▶ CONFIRMED / FAILED  (on evidence)
                                                ▼
                            FAILED ──▶ AUTHORIZED, only under a STRICTLY NEWER epoch
```

- **Same ID, same payload** → idempotent reopen.
- **Same ID, different payload** → `IdentityConflict`. Refused from first durable
  creation, and still refused after the body is purged, because the tombstone survives.
- **UNKNOWN never returns to AUTHORIZED.** Resolution requires evidence, not optimism.
- **DISPATCHED with no execution id and no tx hash fails closed**: the send may or may
  not have happened, so the only safe reading is "unknown".
- Outbox rows are written **before** network I/O. Replacement lineage
  (`replaces_attempt_id`) is preserved, so a replacement never looks like fresh work.
- `signer_ref` stores a *reference*. Anything shaped like key material is refused on the
  way in.

### The journal adopts the NATIVE recovery verdict

Held does not invent its own notion of "unknown". `probes/p00_native_workflow_probe.py`
drives the real `almanak.framework.execution.reconciliation` predicates and maps them:

| native verdict | journal state |
|---|---|
| `success` | CONFIRMED |
| `failed_submission_requires_reconciliation` | **UNKNOWN** |
| `failed_submission_proves_revert` | FAILED |
| neither, nothing submitted | FAILED |

Order matters: reconciliation is checked **before** proven-revert, so an incident is
never downgraded to a clean failure. Six cases, zero mismatches.

## Result delivery and acknowledgement

**At-least-once delivery with idempotent acknowledgement at the consumer.** Exactly-once
is claimed only *at the consumer's state update*, and never from a local delivered flag —
V4 §4 is explicit that such a flag does not solve the crash between callback and ack.

The crash window a naive design leaves open:

```
callback → consumer state updated → CRASH → ack never written → redelivery → applied AGAIN
```

It is closed by construction: the consumer's state update and the acknowledgement are
**one commit**. There is no instant at which the consumer has moved but the ack has not.
`test_results` proves it by crashing inside `apply()` and asserting that *no* partial
state survives, then that a retry applies exactly once.

If a real consumer cannot enrol in that transaction, `ExactlyOnceUnavailable` is raised
rather than quietly downgrading the guarantee.

## Fresh-ID relabelling is explicitly OUT of scope

A runner that invents a new operation ID for economically equivalent work is **not**
prevented by anything here, and V4 §4 says so: *"no semantic-deduplication guarantee is
made against a runner deliberately inventing new work."* The consumed-ID check rejects
*reuse of an identified operation*. It cannot recognise the same economics under a
freshly minted identity. Any claim otherwise would be false.

## Known limits

- A reverted attempt leaves **no on-chain durable reservation**. Reauthorizing the same
  ID and payload under a new epoch is permitted only from FAILED, which means *definite*
  non-execution established by reconciliation.
- Journal loss: if neither an operation row nor a tombstone exists, `assert_recoverable`
  raises `RecoveryBlocked`. It fails closed rather than assuming nothing happened.
- The hosted delivery half is unmeasured under **L10**.
