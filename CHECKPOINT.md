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
| **P02** — typed controller + native Roles enforcement | Controller implemented; **25 example-based tests passing**. **Required property/invariant coverage still pending.** |
| **P03** — composed native → KeeperHub → controller route | **Not started.** Authenticated KeeperHub execution (**L10**) remains outstanding. |

This is a checkpoint, not a claim of phase completion. P02 in particular is **incomplete**:
the suite is example-based, and property/invariant coverage over the policy arithmetic has
not been written. The next commits should show exactly that work and any defects it uncovers.

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
| `make check-phase-02` | PASS, 25 tests in two stages | `evidence/P02/report.md` |

`check-phase-02` stage 1 is 4 **labelled adversarial mock** tests (reentrancy, ERC20
returning false, cleanup failing after the economic action). Stage 2 is 21 tests against
the **real pinned** Base-mainnet Safe, Zodiac Roles, Morpho Blue and native USDC on a fork.
The two evidence classes are kept separate on purpose and must not be conflated.

## Still pending

1. **P02 property/invariant coverage** over the policy arithmetic — the immediate next task.
2. Fixes for anything that coverage uncovers.
3. P03 local composition (adapter boundary, envelope dispatch, result return).
4. **L10** — authenticated KeeperHub organisation caller/payer. Blocks P03's public
   execution. Nothing about it is stubbed or simulated.
5. Independent review of every phase.

## Exact next task

Write property/invariant tests for the controller's policy arithmetic — ceiling, floor,
per-action bounds, count and cooldown monotonicity, and lane derivation — then fix whatever
they reveal.

## Reproducing

External dependencies are not vendored. See `docs/decisions/environment-setup.md` and
`RESUME.md`. Solidity dependencies are pinned git submodules:

```bash
git submodule update --init --recursive
forge build
```

Toolchain: solc 0.8.28 with `via_ir`, optimizer 200 runs; OpenZeppelin v5.1.0; forge-std
v1.16.2; foundry 1.8.1. The Python side needs CPython 3.12 and the pinned Almanak SDK.

See `SECURITY-NOTES.md` regarding the Anvil development keys present in the fixtures.
