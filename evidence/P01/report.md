# P01 — identity, journal and result contract

2026-09-16. Claude, sole implementation writer. **Independent review pending; nothing
here is accepted.** `make check-phase-01` → **31/31**.

## What was built

`packages/core/held_core/` — five modules, no network, no keys, no chain.

| module | job |
|---|---|
| `units.py` | unsigned base units; rejects `bool`, `float`, negatives, overflow |
| `canonical.py` | one byte string per value, in any language |
| `identity.py` | the three identities of V4 §4 and the EIP-712 envelope |
| `journal.py` | durable SQLite journal/outbox and the state machine |
| `results.py` | at-least-once delivery with an idempotent consumer ack |

Contracts: `docs/contracts/identity.md`, `docs/contracts/controller-interface.md`,
`docs/contracts/vectors/canonical-vectors.json`. Tests: `tests/core/run_tests.py`.

## The decisions worth defending

**The operation ID excludes the runner and the epoch.** If either were in the preimage,
replacing operator A with B would mint a fresh ID for the same business operation, and
the consumed-ID check would stop protecting anything across exactly the handover it
exists to survive. The envelope binds epoch, policy version and runner instead. The
vectors assert both halves: identical ID, different signing hash.

**Amounts are decimal strings on the wire.** A uint256 does not survive an IEEE-754
double. A JavaScript consumer using default numbers would silently compute a different
operation ID. The encoder raises on a raw `int`, so this is enforced rather than
documented.

**`bool` is not an integer.** `isinstance(True, int)` is true in Python, so a policy
field accepting `True` as `1` is a live hazard. Rejected explicitly.

**Addresses are lower-cased, not EIP-55.** Checksum form encodes meaning in the *case* of
hex digits; identity must not depend on how a caller capitalised an address.

**The consumer state update and the ack are one commit.** That is the only thing that
closes `callback → state updated → CRASH → ack lost → redelivery → applied AGAIN`. The
test crashes inside `apply()` and asserts no partial state survives, then that a retry
applies exactly once. Exactly-once is claimed **at the consumer**, never from a local
delivered flag — V4 §4 says a delivered bit does not solve this, and it does not.

**The journal adopts the NATIVE recovery verdict.** Held does not invent its own notion
of "unknown". `probes/p00_native_workflow_probe.py` drives the real
`almanak.framework.execution.reconciliation` predicates; six cases map onto journal
states with **zero mismatches**, and the journal then enforces the consequence.
Reconciliation is checked *before* proven-revert so an incident is never downgraded to a
clean failure.

## Verification

The EIP-712 domain separator and `hashStruct` are **cross-checked against `eth_account`**
rather than trusted. A hand-rolled `abi_encode` + `keccak` that agrees only with itself
proves nothing.

Covered, as the P01 prompt requires: journal crash/reopen (handle dropped without
`close()`), concurrent same-ID (8 threads through a barrier → exactly one row), body
conflicts, epoch-independent consumed identity, domain separation across chain and
controller, cross-language byte vectors, and both result boundaries.

## Bugs found in my own work

- Three test helpers passed raw `int`s into `canonical_hash`. The encoder **correctly
  rejected them** — the guard caught its author.
- A tombstone assertion compared `bytes` against the stored hex string. Fixed.

## Honest limits

- No contract is deployed. `controller-interface.md` is a design interface; P02 builds it.
- **No semantic deduplication.** A runner that mints a fresh ID for economically
  equivalent work is not prevented, and V4 §4 says so explicitly.
- A reverted attempt leaves no on-chain durable reservation. Reauthorization is permitted
  only from FAILED — *definite* non-execution — under a strictly newer epoch.
- The hosted result-delivery half is unmeasured under **L10**.
- Self-testing is not independent acceptance. `accepted` stays `false`.

## Next

**P02** — typed controller, real Roles enforcement and atomic approval/action/cleanup
against the pinned Base fork. Its prerequisite (this phase's identity and journal
contracts) is met.
