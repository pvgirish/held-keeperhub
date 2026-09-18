# Held

### Customer-approved operating limits and recoverable runner handover for Almanak strategies.

An autonomous strategy that can move real money needs answers to three questions before
anyone sensible funds it. **What is the worst it can do today? What happens when it goes
quiet mid-execution? Who can move my money right now?**

Held answers all three, and enforces the first one on-chain — so the guarantee does not
depend on Held behaving.

```
Owner  ─approves limits─▶  Held  ─▶  KeeperHub  ─▶  HeldController  ─▶  Zodiac Roles  ─▶  Safe  ─▶  Morpho
  ▲                          │                      (epoch, signature)   (5 budgets)     (2-of-3)
  └──── can fence and revoke ┘                                                   funds never leave the owner
```

**The customer sets ceilings, per-action maximums, a cash floor and a count limit. A Zodiac
Roles module and a Safe enforce them. Held holds no key and no funds.**

Watch what that buys, from the rehearsal:

| | |
|---|---|
| First approved action | **10.000000 USDC** moves into Morpho. Signed by the runner, broadcast by the executor, allowed by the chain. |
| Second attempt | **Refused — `FloorViolated()`.** The Safe is at its 1 USDC floor. Not a warning; a revert. |
| Replayed authorization | **Refused — `OperationConsumed(bytes32)`.** Every counter unmoved. |
| Limits | **Non-refilling.** A spent budget stays spent until an owner re-sets it. No waiting it out. |
| Runner goes quiet | Handover **blocks** on the unresolved operation until it is reconciled against the chain. |

### Status, honestly

| | |
|---|---|
| **Demo** | `make hero-demo` — 12 steps, ~3s, pinned Base-mainnet fork |
| **Full ceremony rehearsal** | `make final-rehearsal` — **14/14 claims matched**, final identities, real 2-of-3 |
| **Public Base transaction** | **NOT YET ESTABLISHED** — nothing deployed, funded or broadcast |
| **KeeperHub execution** | **NOT YET ESTABLISHED** — the route accepts our credential; we have not executed |
| **Demo video** | **NOT RECORDED** — script ready, see [VIDEO-SCRIPT.md](docs/submission/VIDEO-SCRIPT.md) |
| **Licence** | [MIT](LICENSE) |

> Those `NOT YET ESTABLISHED` rows are not placeholders waiting for something equivalent.
> Nothing in this repository is graded above `REAL LOCAL FORK`, and
> [`make mainnet-evidence-gate`](script/mainnet_evidence_gate.py) exists specifically to
> stop our own fork evidence from being read as mainnet evidence — it re-reads any such
> claim from a public Base RPC. 15 tests attack it.

| Read next | |
|---|---|
| What it does and why it matters | [Submission pack](docs/submission/SUBMISSION-PACK.md) |
| Who can move the money | [Threat model](docs/submission/THREAT-MODEL.md) |
| Every claim, its command, its grade | [Evidence index](docs/submission/EVIDENCE-INDEX.md) |
| What is claimed and what is withdrawn | [Claim ledger](docs/submission/CLAIM-LEDGER.md) |
| Run it yourself | [Run it locally](#run-it-locally) |

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

Held's execution path is a KeeperHub **direct contract call** — not the workflow builder.
The client is built against the documented `POST /api/execute/contract-call` route and is
wire-tested in 46 tests: documented request body, the `Idempotency-Key` **header** derived
from `keccak(domain ‖ operationId ‖ attemptId)`, `GET /api/execute/{id}/status` with the
poll hint, 202 as the documented write success, and the two documented 409 codes kept as
opposite outcomes rather than one branch.

**The credential is real; the execution is not.** `make check-l10-route-proof` performs a
live authenticated `GET /api/keys`: 200, `hosted=true`, the configured secret matches a
listed organisation key by its documented `keyPrefix`, scope `mcp:read`. That is claim
**P30**, and it is a fact about a *credential*, not an execution.

Broadcasting needs `mcp:write` or `mcp:admin`. The organisation holds such a key and it is
**deliberately not configured** — swapping it in is a distinct, reversible owner action.
Until then Held's production path refuses to broadcast *before writing anything to the
journal*: 24 tests hold that refusal, including that the journal is left byte-identical and
the identical call succeeds later with no repair.

Every other KeeperHub result runs against `OfflineTransport`, which stamps `hosted=false`,
and `assert_hosted_evidence()` refuses a non-hosted result — so no local fixture can be
filed as a hosted one. Four tests exist solely to prove that. Whether KeeperHub's
server-side encoder reproduces Held's intended calldata (**P19**) is recorded as
**unknown**: settling it needs one authenticated dry run against a deployed controller.

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
| `AUTHENTICATED HOSTED` | A real authenticated KeeperHub call. **One row: P30, a credential check — not an execution.** |
| `REAL LOCAL FORK` | Real pinned contracts on an anvil fork. No finality, not public. |
| `REAL OFFLINE SDK` | The real pinned Almanak SDK, in-process. |
| `SYNTHETIC` | A model or scripted double. Control-flow evidence only. |

A test, a mock, a fork result or an `OfflineTransport` result is never presented as a
KeeperHub execution. Four tests exist specifically to prove a local result cannot be filed
as hosted evidence, and `make mainnet-evidence-gate` goes further: any record claiming
`PUBLIC MAINNET VERIFIED` is re-read from a **public** Base RPC and refused unless the
transaction is really in Base's history. A fork transaction is not, whatever the file says.
15 tests attack that gate the way a deadline would.

### FORK VERIFIED vs PUBLIC MAINNET VERIFIED

Every record in `evidence/` carries exactly one of three labels. The distinction is the
most important thing in this repository.

| Label | Means | Held today |
|---|---|---|
| **FORK VERIFIED** | Real pinned contracts, real protocol, on an anvil fork of Base. Proves behaviour. Proves nothing about mainnet. | **Almost everything** |
| **PREPARED** | Calldata, parameters, gas estimates. Nothing executed. | The M1 templates and parameter sheets |
| **PUBLIC MAINNET VERIFIED** | A transaction that exists in Base's history and was re-read from a public RPC by the gate. | **Nothing yet** |

A FORK record can never satisfy a mainnet claim. That is enforced, not promised: relabel
one and `make mainnet-evidence-gate` asks a public Base RPC for the transaction, which is
not there. Run it — it refuses, and says why.

### What is FORK VERIFIED

The whole M1 ceremony, rehearsed with the final identities (`make final-rehearsal`):
2-of-3 Safe deploy → Roles deploy → `enableModule` → controller deploy (paused) →
**15-action owner ceremony, every action through a real `execTransaction`** → exact 11
USDC funding → bounded authority inventory COMPLETE → activation → runner-B envelope →
executor path → **10 USDC supplied** → second attempt `FloorViolated()` → replay
`OperationConsumed(bytes32)`. 14 of 14 claims matched, 0 problems.

No owner private key was used, requested or held: owners approve by `approveHash` and the
Safe accepts its pre-validated signature form.

## Security model

The short version: **five parties, and none of them can move funds alone.** Held holds no
key — if Held is compromised, the worst it can do is build a request that still needs a
runner signature it cannot produce and still faces every on-chain check. A stolen runner
key can only cause actions the owner already approved, up to ceilings the owner already
set, into the market the owner already chose; recovery is one owner ceremony.

Full analysis, including the four things deliberately **not** defended against:
**[docs/submission/THREAT-MODEL.md](docs/submission/THREAT-MODEL.md)**.

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

The whole M1 ceremony, rehearsed on a fresh fork with the **final** identities — the three
real owners at threshold 2, runner B, KeeperHub's managed signer — every owner act through
a real 2-of-3 `execTransaction`:

```bash
make final-rehearsal
```

It deploys nothing publicly, funds nothing and broadcasts nothing. No owner private key is
used, requested or held: the owners approve by `approveHash` and the Safe accepts its
pre-validated signature form.

`check-phase-03` deliberately exits non-zero: it runs every local check and then reports
INCOMPLETE, because the required KeeperHub execution has not been performed. A gate that
went green without it would be lying.

## What is not established

Stated plainly, because a submission that hides these is worse than one that lacks them.

- **No public-chain execution.** Nothing is deployed, funded or broadcast on any public
  network. Every controller result is from a Base-mainnet fork at block 51353212.
- **No authenticated KeeperHub *execution*.** Corrected 2026-09-18: an organisation
  credential now exists and the authenticated route accepts it — `make check-l10-route-proof`
  gets 200 on a live `GET /api/keys` and reads its scope. That is a fact about a credential,
  not about an execution, and **L10 is still open**: nothing has been submitted to the
  caller/payer, because no controller is deployed to aim a call at. The credential is scoped
  `mcp:read`, which the API documents as read-and-simulate only, so no transaction can be
  broadcast on it at all. Whether KeeperHub's server-side encoder reproduces Held's intended
  calldata is still recorded as unknown, not assumed.
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
| M1 rehearsal, final identities | full ceremony, 14/14 claims matched | REAL LOCAL FORK | pending |

Nothing in this repository is independently accepted. Self-testing is not acceptance.

## Demo video and on-chain links

Every link below is a placeholder. Filling one in without a matching public transaction is
refused by `make mainnet-evidence-gate`, which re-reads the record from a public Base RPC.

| | Status |
|---|---|
| **Demo video** | *not recorded* — narration and 20-shot list in [VIDEO-SCRIPT.md](docs/submission/VIDEO-SCRIPT.md) |
| Safe | *not deployed* — `https://basescan.org/address/…` |
| Zodiac Roles module | *not deployed* — `https://basescan.org/address/…` |
| HeldController | *not deployed* — `https://basescan.org/address/…` |
| Owner ceremony (15 tx) | *not executed* |
| Activation | *not executed* — `https://basescan.org/tx/…` |
| **The supply transaction (M1)** | *not executed* — `https://basescan.org/tx/…` |
| KeeperHub execution id | *not executed* |
| Morpho position | *not created* — `https://basescan.org/address/…` |

Fill-on-execution templates for all of the above: [`evidence/M1/templates/`](evidence/M1/templates/).

## Licence

[MIT](LICENSE). Dependencies are pinned git submodules and external packages — referenced,
never vendored — and keep their own licences: OpenZeppelin (MIT), forge-std
(MIT OR Apache-2.0), the Almanak SDK (external, pinned, not redistributed). Every Solidity
file authored here carries `SPDX-License-Identifier: MIT`.

## Reading further

| | |
|---|---|
| What is claimed, and what is withdrawn | [`docs/submission/CLAIM-LEDGER.md`](docs/submission/CLAIM-LEDGER.md) |
| Every claim's command and grade | [`docs/submission/EVIDENCE-INDEX.md`](docs/submission/EVIDENCE-INDEX.md) |
| Who can move the money, and what breaks | [`docs/submission/THREAT-MODEL.md`](docs/submission/THREAT-MODEL.md) |
| The submission text itself | [`docs/submission/SUBMISSION-PACK.md`](docs/submission/SUBMISSION-PACK.md) |
| The demo narration and shot list | [`docs/submission/VIDEO-SCRIPT.md`](docs/submission/VIDEO-SCRIPT.md) |
| Running the demo, step by step | [`docs/submission/DEMO-RUNBOOK.md`](docs/submission/DEMO-RUNBOOK.md) |
| Likely judge questions, answered | [`docs/submission/FINALIST-QA.md`](docs/submission/FINALIST-QA.md) |
| The public execution, step by step | [`docs/submission/M1-OWNER-RUN-SEQUENCE.md`](docs/submission/M1-OWNER-RUN-SEQUENCE.md) |
| The one irreversible action | [`docs/submission/M1-IRREVERSIBLE-PREFLIGHT.md`](docs/submission/M1-IRREVERSIBLE-PREFLIGHT.md) |
