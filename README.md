# Held

**Customer-approved operating limits and recoverable runner handover for Almanak
strategies.** KeeperHub is the intended execution layer and the client is built and
wire-tested against it — but **Held has not yet executed through KeeperHub**, because the
organisation credential that route requires does not exist here. That is stated up front
rather than implied away.

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
| 3 | A **real** operation is dispatched over a socket to a server that receives it and drops the connection — durable attempt, `UNKNOWN` |
| 4 | The owner **fences** the controller on chain |
| 5 | The handover is **REFUSED** — on a set the machine derives from the journal, not from a list it was handed |
| 6 | Reconciliation asks the controller's own `consumed[]` record, not the transport |
| 7 | A **bounded authority inventory**, collected live at the fence and scoped to this installation |
| 8 | Runner B is **pinned** against the consumption actually on chain |
| 9 | Held **prepares** the activation and describes it; it does not sign it |
| 10 | Runner B is active — **`usedSupply` is still 12000000**, remaining 49988000000 |
| 11 | Runner A **attempts** its old authorization and is refused: `WrongEpoch` |
| 12 | Runner B receives what it needs — **no key material** |

Steps 5, 10 and 11 are the product. Step 5 is the refusal that stops a handover from
guessing — and the operation it names is a real dispatched one whose transport genuinely
never answered, not a constructed id. Step 10 is the budget surviving the swap. Step 11 is
behavioural: runner A really signs a fresh operation under its retired epoch, really sends
it, and the controller really reverts with `WrongEpoch(uint64,uint64)` — selector
`0x2b9264ec`.

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

## What the KeeperHub integration actually is

Held's execution path is a KeeperHub direct contract call. The client is built against the
documented `POST /api/execute/contract-call` route and is wire-tested in 28 tests:
documented request body, the `Idempotency-Key` **header**, `GET /api/execute/{id}/status`
with the poll hint, 202 as the documented write success, and the two documented 409 codes
kept as opposite outcomes rather than one branch.

**It has not been called with a credential.** Every one of those tests runs against
`OfflineTransport`, which stamps `hosted=false`, and `SendResult.assert_hosted_evidence()`
refuses a non-hosted result — so no local fixture can be filed as a hosted one. Three tests
exist solely to prove that. Whether KeeperHub's server-side encoder reproduces Held's
intended calldata is recorded as **unknown**, because settling it needs one authenticated
dry run that has not happened.

## Reliability and recovery

The parts that matter when something goes wrong, each with a test behind it:

- A dispatched operation is **durable before any network I/O** — verified by opening a
  separate connection mid-send, and by `SIGKILL`ing a real child process.
- Every ambiguous result — timeouts, dropped connections, all 5xx, unrecognised statuses —
  becomes `UNKNOWN`, never `REJECTED`. **An unknown is not a verified negative.**
- A restart resumes the original attempt under its original idempotency key and makes
  **zero duplicate network calls**.
- Resolution comes from `consumed[operationId]` read at a stated block with chain id,
  controller and finality — never from a caller's expectation and never from the
  transport's silence.

Two defects found by adversarial review, and what they cost:

1. The `SetAuthorization` decoder **could not read real `cast logs` output at all** — it
   indexed 32-byte words positionally and the block hash comes first. The entire
   grant-discovery path was inert against live data, hidden by a test fixture that emitted a
   simplified shape.
2. `reconcile()` believed a caller-supplied empty list. The machine now **re-derives** the
   retiring-epoch operation set from the durable journal, so omitting an operation is
   refused rather than believed.

## Native vs Held — measured, not argued

`make p06-comparison` runs the Held half on the fork against the
[frozen native baseline](docs/baseline/native-measurements.json), same operation, same
counters. The result does not favour Held on operator work:

Both sides start from the **same** economic state — 30,000 USDC already consumed against a
50,000 ceiling — and every ceremony below is a real Safe `execTransaction` signed by two of
three owners. The change is a real MultiSendCallOnly delegatecall on both sides.

| | ceremonies | signatures | transactions | final remaining |
|---|---|---|---|---|
| Native, clean | **1** | **2** | **1** | 50,000 |
| Held, clean | 2 | 4 | 2 | 50,000 |
| Native, interrupted (competent) | 2 | 4 | 2 | 45,000 |
| Held, interrupted | 2 | 4 | 2 | 50,000 |

> The two interrupted rows did **not** suffer the same interruption — native's in-flight
> supply landed (5,000 more consumed), Held's never reached the chain. Both reach the
> correct remaining capacity for the event they actually faced; neither preserved more than
> the other.

A competent native operator — fence first, let it settle, read the consumed allowance,
derive the new remaining, then activate — **reaches the correct remaining capacity on the
first attempt.** Held ties on the interrupted change and costs an extra ceremony on the
clean one, because it cannot batch the fence with the activation: the controller refuses to
activate while active, and Held requires the fence confirmed and the epoch reconciled first.
That is a product constraint, and the claim that Held reduces coordination work is
[withdrawn](docs/submission/CLAIM-LEDGER.md).

What the measurements *do* support:

- **One store answers whether a specific operation executed.** Native derives the budget
  correctly in aggregate but does not identify which operation ran.
- **The system refuses while an outcome is unknown.** Native has no per-operation record to
  refuse with; a competent operator supplies the discipline instead.
- **An activation-time consistency guard.** Observed firing during the measurement:
  `AllowanceDesynchronised(rolesRemaining, expected)` refused an activation whose raised
  ceiling the Zodiac allowance would not have honoured.
- **Against Held: it costs more.** A controller, two role memberships, five budgets and a
  durable journal, before any of the above is available — plus one more owner ceremony on a
  clean change.

Held buys enforcement and per-operation evidence at the price of setup and one extra
transaction. That is the honest trade.

## Supported scope

One Safe, one Morpho market, supply and withdraw, on Base. Two typed controller entry
points — no generic executor. Authority discovery is **bounded**: a declared profile over a
declared block range, and anything outside it is reported as out of scope, which is not the
same as absent.

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

Needs Python 3.12, Foundry, and the pinned Almanak SDK. Every environment variable is
documented in [`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md); setup is in
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
- **P05 console**: `--state-source live` reads real sources and refuses to fall back to
  demonstration data, but the HTML rendering of the four views is still prototype.
- **One adversarial case is unestablished for an external reason**: a broadcast whose
  transaction hash is known but whose receipt never arrives on a *public* chain. That needs
  L10.
- **A genuine chain reorganisation is not simulated.** A fork has no finality to disagree
  about; what is tested is that unfinalized readings are not verdicts.
- **Not audited, not production ready.** Finite testing is not an audit.
- **Every key in the fixtures is a well-known anvil account.** That is not custody and
  proves nothing about a production installation.

## What Held does not claim

Held does not replace Almanak, KeeperHub, Safe or Morpho, and it does not claim those tools
cannot do what they actually do. **We measured that, and native won on operator work.** A
competent operator with Safe batching, Zodiac Roles, Morpho's own history and Almanak's
recovery reaches the correct end state in fewer ceremonies and fewer transactions than Held
does.

Held's surviving claim is narrower and is the one the measurements support: it makes an
interrupted operation **resolvable from one place**, refuses to proceed while the answer is
unknown, and refuses to install a policy the native Roles layer would not honour. It buys
enforcement and per-operation evidence, and charges setup for them.

## Status

| Phase | Implementation | Evidence | Independent review |
|---|---|---|---|
| P00 route + native baseline | complete | REAL LOCAL FORK + REAL OFFLINE SDK | pending |
| P01 identity + journal | complete | locally verified | pending |
| P02 controller + Roles | complete | REAL LOCAL FORK | pending |
| P03 native → KeeperHub | **PARTIAL** | local complete; **hosted missing (L10)** | two reviews, all findings closed |
| P04 authority + handover | runtime service + hero demo | REAL LOCAL FORK | Review 1, all findings closed |
| P05 operator console | live mode implemented; HTML rendering still prototype | SYNTHETIC + REAL LOCAL FORK | pending |
| P06 adversarial + comparison | 23/24 cases; comparison **measured** | REAL LOCAL FORK | pending |
| P07 clean install | `make clean-install` passes from an isolated clone | — | pending |
| P08 submission package | assembled; gate **BLOCKED** on mandatory items | — | pending |

Nothing in this repository is independently accepted. Self-testing is not acceptance.
