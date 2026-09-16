# Held V4 — resume here

Handoff 2026-09-16 (post competent-native correction pass). Claude is sole implementation writer. **Independent review is
pending for everything in this tree — nothing here is accepted.**

Read in this order: `evidence/continuous-run.md` (state + resume command) →
`docs/decisions/advantage-review.md` (the V4 §9 decision that gates P01) →
`evidence/P00/report.md` (full history) → `docs/decisions/route-evidence.json` (route layers).

## State

**P00 complete** — `HELD_PRICE_MODE=testing-only make check-phase-00` → **PASS**
(gate-tests 21/21, manifests, probe, **native-workflow**, baseline). Six gates green,
including required work 6: real in-process SDK reconfiguration + recovery.

**P01 implemented** — `make check-phase-01` → **31/31**. See `evidence/P01/report.md`.

The nine declared cases ran on the pinned Base-mainnet fork, plus the **competent-native
controls** for I2 and I6 required by V4 §9 / A1. Each case separates `experiment_result` from
`workflow_outcome`: **9 experiments PASS**, but workflow outcomes are 6 ACHIEVED, 1
ACHIEVED-AFTER-RECOVERY, **2 NOT ACHIEVED** (I2, I6 naive — both closed by the competent
controls) and 1 PARTIAL (I9, L10).

**Next: P02** — typed controller, real Roles enforcement, atomic approval/action/cleanup on
the pinned fork. Read `docs/decisions/advantage-review.md` rev 2 first: the I6 advantage claim
is **withdrawn**, and no ceremony or signature saving is claimed anywhere. The surviving
hypothesis is the activation-time consistency guard, specified in
`docs/contracts/controller-interface.md` and still **unproven**.

Representative native comparator: **13 ceremonies / 26 signatures / 17 transactions**
(competent I2 and I6 substituted). The as-run totals 15/30/20 include the naive diagnostic
controls and must not be quoted as the native path's cost.

## Dependencies that live OUTSIDE this tree

This archive is the `held/` worktree only. These were **absent at session start** and were
rebuilt from `docs/decisions/environment-setup.md`. Expect to rebuild them again.

| What | Where it lived | Pin | Rebuild |
|---|---|---|---|
| Almanak SDK | `~/src/sdk` | rev `6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938` — **verified equal** | `git clone https://github.com/almanak-co/sdk.git && git checkout <rev>` |
| Python 3.12 venv | `~/venv312` | CPython 3.12 via `uv`; this run got **3.12.12**, manifest observed 3.12.13 | `uv python install 3.12 && uv venv --python 3.12 ~/venv312 && uv pip install --python ~/venv312/bin/python -e ~/src/sdk` |
| Foundry | `~/.foundry/bin` | **not pinned** — observed 1.8.1 / `982849d3` here; see Environment notes | From the GitHub release — `foundryup` is unusable, `foundry.paradigm.xyz` is blocked. Asset names use `arm64`, **not** `aarch64`. |

Zodiac Roles (`~/src/roles`, for reading enum values) is also absent and was not needed —
the condition operators were read from the live contract's behaviour instead.

The Makefile takes `PY` and `SDK` as overrides, so nothing is hardcoded to those paths. The
gates run under system Python 3.9 too, **except** `gate-tests` and `check-probe`, which need the
venv's `eth_abi` and the SDK.

## Environment notes

- **Foundry — resolved, and an earlier claim withdrawn.** Foundry is **not** a required pin. It
  appears only under `toolchain_observed` (a block whose `_note` says these are observations);
  `pinned_sources` has no foundry entry and `check_manifests.py` never reads one. The 1.8.3 /
  `cae51ad4` record is a truthful observation of a *different* machine and its sha256 is a
  Linux artifact. This run used 1.8.1 / `982849d3` on Darwin arm64. No re-pin is outstanding.
- **Base RPC.** The manifest's "ALL Base RPC hosts 403 at gateway" does not hold here.
  `https://mainnet.base.org` answers and the pinned fork loads in under five seconds. Treat the
  old blanket blocker as history.

## Resume command

```bash
cd <ha>/held
./fixtures/with_fork.sh bash -c '
  for s in 01_deploy_safe_and_roles 02_enable_module_and_fund 03_scope_role 03b_bind_allowance_and_build_history; do
    bash ./fixtures/scripts/$s.sh
  done
  bash ./fixtures/scripts/03c_quota_isolation.sh
  bash ./fixtures/scripts/04_scenarios.sh
  bash ./fixtures/scripts/05_native_competent_controls.sh
  python3 probes/assemble_baseline.py'
```

Steps 01–03b are idempotent and rebuild the whole fixture on a fresh fork in about 90 seconds.
**They must run in one invocation**: each shell call gets its own network namespace with
`--die-with-parent`, so a background anvil cannot survive between calls. `with_fork.sh` refuses
to hand over a fork whose chain id, block or Morpho code does not match `fixtures/fork.env`.

Every case takes an `evm_snapshot` and reverts, so controls cannot leak into measurements and
the canonical 30,000-used / 20,000-remaining start is re-asserted before each case.

## Gate state

```
make gate-tests                                21/21 hold
make check-manifests                           PASS
make check-probe                               PASS with HELD_PRICE_MODE=testing-only; FAIL without (correct)
make check-native-workflow                     PASS  - real in-process SDK recovery, 0 mismatches
make check-baseline                            PASS  - 9 cases + 2 competent-native controls
HELD_PRICE_MODE=testing-only make check-phase-00   PASS
make check-phase-01                            PASS  - 31/31 contract tests
```

## Open blocker

**L10** — authenticated KeeperHub caller/payer preflight. Needs an org API key. Blocks the P03
composed-execution step and the hosted half of I9. Does **not** block P01, P02 or any other
local work.

## What is in here and what it is worth

Every identity in the fixtures is an **anvil deterministic test account** — public, well-known,
local-fork only, never real custody. There are no credentials, no real private keys, no private
RPC URLs and no dependency caches in this tree. The only RPC referenced is the public
`https://mainnet.base.org`.

Synthetic probe stubs under `probes/checks/` are **checker fixtures**. They are never SDK, fork
or chain evidence.

Morpho supply **shares are not constant** across rebuilds — they depend on market state at
execution time. Never pin a share count to force a pass.
