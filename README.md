# Held

**Customer-approved operating limits and recoverable runner handover for Almanak
strategies, executed through KeeperHub.**

```
Almanak  →  Held  →  KeeperHub  →  HeldController  →  Zodiac Roles  →  Safe  →  Morpho
                                                                                   │
                            reconciliation back to Almanak  ←────────────────────┘
```

| | |
|---|---|
| **Demo** | `make hero-demo` — 12 steps, ~3s, against a pinned Base-mainnet fork |
| **KeeperHub execution** | **NOT YET ESTABLISHED** — see [Limitations](#what-is-not-established) |
| **Explorer transaction** | **NOT YET ESTABLISHED** |
| **Reproduce** | [Run it locally](#run-it-locally) |
| **Evidence index** | [docs/submission/EVIDENCE-INDEX.md](docs/submission/EVIDENCE-INDEX.md) |
| **Current limitations** | [What is not established](#what-is-not-established) |

> Those two `NOT YET ESTABLISHED` rows are not placeholders waiting to be filled with
> something equivalent. Held's KeeperHub route needs an organisation API credential that
> does not exist in this environment, so the authenticated call has never been made. It is
> neither stubbed nor simulated, and a local result is structurally prevented from being
> filed as a hosted one. See [`evidence/P03/public-action-request.json`](evidence/P03/public-action-request.json).

---

## The problem, in 30 seconds

An Almanak strategy decides what to do. KeeperHub executes it. Both work.

The awkward part is everything around a **change**. A customer who wants to cap what a
strategy may spend, or replace the runner operating it, hits three questions that are
nobody's job today:

1. **What has actually been spent so far?** Not what the strategy believes — what the chain
   recorded.
2. **What happened to the operation that was in flight when we stopped?** A submission that
   never returned might have executed, or not. An unknown is not a verified negative.
3. **After the swap, does the new runner inherit the spent budget, or a fresh one?** A fresh
   one means the customer's cap silently doubled.

Get these wrong and you either lose money or lose the customer's consent. Held's job is to
make the answers verifiable.

## The hero workflow

This is what `make hero-demo` runs, end to end, against real contracts on a fork:

| | |
|---|---|
| 1 | Runner A is **active** under the customer's approved limits |
| 2 | Runner A executes a **real supply** — 12 USDC actually leaves the Safe into Morpho |
| 3 | An operation becomes **ambiguous** — the send never returned |
| 4 | The owner **fences** the controller on chain |
| 5 | The handover is **REFUSED** while the outcome is unresolved |
| 6 | Reconciliation asks the controller's own `consumed[]` record, not the transport |
| 7 | A **bounded authority inventory** over the supported profile |
| 8 | Runner B is **pinned** against the consumption actually on chain |
| 9 | Held **prepares** the activation and describes it; it does not sign it |
| 10 | Runner B is active — **`usedSupply` is still 12000000**, remaining 49988000000 |
| 11 | Runner A **attempts** its old authorization and is refused: `WrongEpoch` |
| 12 | Runner B receives what it needs — **no key material** |

Steps 5, 10 and 11 are the product. Step 5 is the refusal that stops a handover from
guessing. Step 10 is the budget surviving the swap. Step 11 is behavioural: runner A really
signs a fresh operation under its retired epoch, really sends it, and the controller really
reverts with `WrongEpoch(uint64,uint64)` — selector `0x2b9264ec`.

## Architecture

| Layer | What it is | Where |
|---|---|---|
| **Adapter** | Intercepts the Almanak `ActionBundle`, admits exactly one supported action, derives the operation identity, signs the runner envelope | [`adapter/`](adapter/) |
| **Core** | Unsigned base units, canonical cross-language encoding, durable SQLite journal, result/ack boundary | [`packages/core/`](packages/core/) |
| **Controller** | Paused-by-default typed contract. Two typed entries, no generic executor. EIP-712 runner authorization against the *current* epoch | [`contracts/src/HeldController.sol`](contracts/src/HeldController.sol) |
| **Install** | One definition of what "Held is installed" means — both Zodiac roles, condition trees, five budgets | [`contracts/src/install/HeldInstall.sol`](contracts/src/install/HeldInstall.sol) |
| **Authority** | Bounded inventory of who can move the customer's funds, within a declared profile | [`packages/authority/`](packages/authority/) |
| **Handover** | Durable, restartable handover machine + owner transaction builder | [`packages/handover/`](packages/handover/) |
| **Console** | The private operator views | [`console/`](console/) |

**Held holds no owner key and no customer funds.** It *prepares* owner transactions and
describes what they change; the owner executes them in their own Safe. A Held component that
could fence or activate on its own would be a fourth authority over the customer's funds
that the inventory does not contain and the owner never approved.

## Evidence grades

Every claim in this repository carries one, and they are never promoted:

| Grade | Meaning |
|---|---|
| `PUBLIC CHAIN` | A real transaction on a public network. **Held has none yet.** |
| `AUTHENTICATED HOSTED` | A real authenticated KeeperHub call. **Held has none yet.** |
| `REAL LOCAL FORK` | Real pinned contracts on an anvil fork. No finality, not public. |
| `REAL OFFLINE SDK` | The real pinned Almanak SDK, in-process. |
| `SYNTHETIC` | A model or scripted double. Control-flow evidence only. |

A test, a mock, a fork result or an `OfflineTransport` result is never presented as a
KeeperHub execution. Three tests exist specifically to prove a local result cannot be filed
as hosted evidence.

## Run it locally

Needs Python 3.12, Foundry, and the pinned Almanak SDK. See
[`docs/decisions/environment-setup.md`](docs/decisions/environment-setup.md).

```bash
git submodule update --init --recursive
forge build
HELD_PRICE_MODE=testing-only make hero-demo
```

The full gates:

```bash
HELD_PRICE_MODE=testing-only make check-phase-02 check-phase-03-local check-phase-04
```

`check-phase-03` deliberately exits non-zero: it runs every local check and then reports
INCOMPLETE, because the required KeeperHub execution has not been performed. A gate that
went green without it would be lying.

## What is not established

Stated plainly, because a submission that hides these is worse than one that lacks them.

- **No public-chain execution.** Nothing is deployed, funded or broadcast on any public
  network. Every controller result is from a Base-mainnet fork at block 51353212.
- **No authenticated KeeperHub call.** L10 is open: no organisation API credential exists in
  this environment. Whether KeeperHub's server-side encoder reproduces Held's intended
  calldata is recorded as unknown, not assumed.
- **P03 is PARTIAL.** Its local half is complete and regressed; the hosted half does not
  exist.
- **P05 console is a prototype** being connected to real service state.
- **P06–P08 are not complete.** Adversarial composed coverage, clean-install verification
  and the submission package are in progress.
- **Not audited, not production ready.** Finite testing is not an audit.
- **Every key in the fixtures is a well-known anvil account.** That is not custody and
  proves nothing about a production installation.

## What Held does not claim

Held does not replace Almanak, KeeperHub, Safe or Morpho, and it does not claim those tools
cannot do what they actually do. A competent operator with Safe batching, Zodiac Roles,
Morpho's own history and Almanak's recovery can already do a great deal. The measured
comparison is in [`docs/submission/CLAIM-LEDGER.md`](docs/submission/CLAIM-LEDGER.md), and
where it shows a tie or a tradeoff, it says so.

Held's claim is narrower: it makes customer-approved changes and runner handovers across
those tools **recoverable and verifiable**, so an interrupted operation does not have to be
guessed at and a replacement runner cannot silently inherit a fresh budget.

## Status

| Phase | Implementation | Evidence | Independent review |
|---|---|---|---|
| P00 route + native baseline | complete | REAL LOCAL FORK + REAL OFFLINE SDK | pending |
| P01 identity + journal | complete | locally verified | pending |
| P02 controller + Roles | complete | REAL LOCAL FORK | pending |
| P03 native → KeeperHub | **PARTIAL** | local complete; **hosted missing (L10)** | one commit reviewed |
| P04 authority + handover | runtime service + hero demo | REAL LOCAL FORK | pending |
| P05 operator console | prototype, being connected | SYNTHETIC | pending |
| P06–P08 | not started / in progress | — | — |

Nothing in this repository is independently accepted. Self-testing is not acceptance.
