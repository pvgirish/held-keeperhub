# Development checkpoint — Held V4

**Git history begins here.** All earlier development happened locally in this worktree
before the repository was pushed. Nothing is backdated, no past phase commits are
fabricated, and no contributor is invented. Earlier states are documented by dated
archives kept outside this tree; they were never git commits and are not presented as
such.

**Nothing below is independently accepted.** Claude authored and ran this work; the
reviewer has not yet inspected the source or reproduced the tests. Self-testing is not
acceptance.

## Status at this checkpoint

| Phase | Status |
|---|---|
| **P00** — route evidence + measured native baseline | Local gates reported passing. **Independent acceptance pending.** |
| **P01** — types, identity, journal, result/ack | Local gates reported passing (31 tests). **Independent acceptance pending.** |
| **P02** — typed controller + native Roles enforcement | Local gates reported passing (50 tests in three stages), including property/fuzz coverage and the exact Morpho rounding/share-effect contract. **Independent acceptance pending.** |
| **P03** — native interception → signing → KeeperHub → reconciliation | **Local half complete** (89 tests). The composed PUBLIC execution is blocked on **L10** and is neither stubbed nor simulated. **Independent acceptance pending.** |

This is a checkpoint, not a claim of phase completion. P03's local half is finished, but
the composed public-execution evidence that Criterion 2 needs does not exist: no contract
is deployed, no funds are spent, and the authenticated KeeperHub route has never been
called.

## What is implemented

- `contracts/src/HeldController.sol` — paused-by-default typed controller. Two typed entry
  shapes only (no generic executor), current-epoch EIP-712 runner authorization plus a
  configured executor route, monotonic consumption counters, normal/restoration lanes with
  separate Zodiac roles and separate non-refilling allowance keys, activation-consistency
  guards, ordinary `CALL` sequence through Roles with every nested status and token return
  checked, and exact effect readback.
- `packages/core/held_core/` — unsigned base units, canonical cross-language encoding,
  the three V4 §4 identities, durable SQLite journal/outbox, and a result/ack boundary that
  commits the consumer state update and the acknowledgement in one transaction.
- `fixtures/scripts/` — reproducible Base-mainnet fork fixture: real 2-of-3 Safe, real
  Zodiac Roles module, genuine consumption history, quota isolation, the nine frozen native
  baseline scenarios and the competent-native controls.
- `probes/` — native SDK seam, configuration and recovery probes against the pinned Almanak
  revision `6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938`.

## Tests actually run, and where the evidence is

| Command | Result | Evidence |
|---|---|---|
| `HELD_PRICE_MODE=testing-only make check-phase-00` | PASS (6 gates) | `evidence/P00/`, `docs/baseline/native-measurements.json` |
| `make check-phase-01` | PASS, 31 tests | `evidence/P01/report.md`, `tests/core/run_tests.py` |
| `make check-phase-02` | PASS, 50 tests in three stages | `evidence/P02/report.md` |
| `make check-phase-03-local` | PASS, 89 tests in five files | `evidence/P03/acceptance.json` |

`check-phase-02` stage 0 is 14 **property/fuzz** tests against an independent reference
predicate (256 runs each, pinned seed). Stage 1 is 4 **labelled adversarial mock** tests
(reentrancy, ERC20 returning false, cleanup failing after the economic action). Stage 2 is
32 tests against the **real pinned** Base-mainnet Safe, Zodiac Roles, Morpho Blue and
native USDC on a fork. The evidence classes are kept separate on purpose and must not be
conflated.

`check-phase-03-local` is 17 interception + 9 native-bundle (against the REAL pinned
compiler) + 18 signing + 28 KeeperHub client + 17 submission. Every KeeperHub test runs
against `OfflineTransport`, which stamps `hosted=false`; **none of them establish L10**,
and three exist specifically to prove a local result cannot be filed as if they did.

Two cross-language checks run in opposite directions. The action hash goes Python →
Solidity via `fixtures/crosslang-vectors.json`, which carries its own provenance and is
only written when the imported SDK tree matches the pin. The envelope digest cannot go
that way — it commits to the domain separator and therefore to the controller's address —
so the fork publishes what it built to `fixtures/generated/signing-vector.json` and the
Python signer reproduces the signature **byte for byte**.

## Still pending

1. **P04** — authority inventory, owner fencing, change and handover. Independent of L10,
   so it is the next task.
2. P05 operator console, P06 composed adversarial faults, P07 install/release evidence,
   P08 assembly.
3. **L10** — authenticated KeeperHub organisation caller/payer. Blocks P03's public
   execution. Nothing about it is stubbed or simulated, and executing
   `evidence/P03/execution-manifest.json` would additionally require authorization to
   deploy a contract and spend funds, which has not been given.
4. Independent review of every phase.

## Open unknowns recorded rather than guessed

- KeeperHub's catalog exposes an internal string chain id alongside the numeric `chainId`.
  Which one `POST /api/execute/contract-call` expects cannot be established without an org
  credential. Held sends `chainId`; the alternative is recorded in the client.
- The authenticated response schema has not been observed, so the execution id and
  transaction hash fields are read defensively.

## Exact next task

P04: inventory every authority over the Safe, the Roles module and the controller; show
owner fencing; and demonstrate a policy change and a runner replacement that preserve
consumption history.

## Reproducing

External dependencies are not vendored. See `docs/decisions/environment-setup.md` and
`RESUME.md`. Solidity dependencies are pinned git submodules:

```bash
git submodule update --init --recursive
forge build
```

Toolchain: solc 0.8.28 with `via_ir`, optimizer 200 runs; OpenZeppelin v5.1.0; forge-std
v1.16.2; foundry 1.8.1 (1.8.3 observed locally). The Python side needs CPython 3.12 and the pinned Almanak SDK.

See `SECURITY-NOTES.md` regarding the Anvil development keys present in the fixtures.
