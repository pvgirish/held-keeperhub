# DoraHacks submission draft

**NOT SUBMITTED.** Copy-ready answers, held here until submission is authorized. Every
factual sentence maps to [`CLAIM-LEDGER.md`](CLAIM-LEDGER.md) at the status recorded there.

## Project

**Held** — customer-approved operating limits and recoverable runner handover for Almanak
strategies.

## Which live project does this integrate with?

**Almanak.** Held intercepts the real pinned Almanak `IntentCompiler` / `IntentStateMachine`
output, admits exactly one supported action from it, and returns the execution result to the
real native consumer for acknowledgement.

## What does the integration do?

An Almanak strategy decides what to do; KeeperHub executes it. Held handles what happens
around a **change** — capping what a strategy may spend, or replacing the runner operating
it — when an execution may be in flight.

It derives a durable operation identity from the deployment's own scope, records the
dispatch before any network I/O, resolves outcomes from the controller's own
`consumed[operationId]` rather than from the transport, and refuses to hand over to a
replacement runner while any outcome is unknown. Verified consumption carries across the
handover, so a new runner inherits the spent budget rather than a fresh one.

## Which KeeperHub surfaces?

`POST /api/execute/contract-call` (direct contract call) with the `Idempotency-Key` header,
`GET /api/execute/{id}/status`, and the public `GET /api/chains` catalog. Built and
wire-tested against the documented schema.

**The execution route has not been called with a credential.** As of 2026-09-18 an
organisation credential exists and the authenticated `GET /api/keys` route accepts it, but
it is scoped `mcp:read` and no contract call has been submitted on it — see "what remains
unfinished".

## Network

Base. All current evidence is from a **Base-mainnet fork** pinned at block 51353212. No
public-chain transaction exists.

## What economic action?

A Morpho Blue supply of native USDC from a 2-of-3 Safe, executed through Zodiac Roles by a
paused-by-default typed controller. The demo moves 12 USDC for real on the fork.

## What transaction proves it?

**NOT YET ESTABLISHED.** No public transaction exists. An organisation credential arrived on
2026-09-18 and the authenticated route accepts it, which is real but is a fact about a
credential, not a transaction: the key is scoped `mcp:read`, which the API documents as
read-and-simulate only, and there is no deployed controller to aim a call at. So no
authenticated execution has been made. It is neither stubbed nor simulated, and a local
result is structurally prevented from being filed as a hosted one.

## Working proof available today

| | |
|---|---|
| Source | private repository; public access not yet authorized |
| Demo | `make hero-demo` — 12 steps on a pinned fork |
| KeeperHub execution | **NOT YET ESTABLISHED** |
| Transaction | **NOT YET ESTABLISHED** |

## What still breaks, and what remains unfinished

Stated candidly, because a submission that hides these is worse than one that lacks them.

- **No public-chain execution and no authenticated KeeperHub call.** This is the mandatory
  requirement and it is absent.
- **Not audited.** Finite adversarial testing is not an audit.
- **Not production ready.** One Safe, one Morpho market, supply and withdraw, fork only.
- **Authority discovery is bounded**, not universal: a declared profile over a declared
  block range. Anything outside is out of scope, which is not the same as absent.
- **Native tooling beat us on operator work.** We measured it from the same starting state.
  A competent native operator does the clean change in one owner ceremony against our two,
  and ties us exactly on the interrupted one. We withdrew the claim that Held reduces
  coordination work.
- **One adversarial case is unestablished for an external reason**: a broadcast whose
  transaction hash is known but whose receipt never arrives on a public chain.
- **A genuine chain reorganisation is not simulated.** A fork has no finality.
- **The operator console's HTML rendering is still prototype**, though live mode reads real
  sources and refuses to fall back to demonstration data.

## What we would say if asked why to look anyway

Three independent review passes found nineteen real defects in this code, including a log
decoder that could not read live output at all and a reconciliation boundary that believed
whatever its caller said. All are closed with regressions that assert the refusal. The
repository states what it has not established more prominently than what it has.
