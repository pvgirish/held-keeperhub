# Demo runbook

Deterministic, screen by screen. Target 3:00. Every number shown must already appear in
[`CLAIM-LEDGER.md`](CLAIM-LEDGER.md) at the grade it is spoken at.

## Before recording

```bash
git submodule update --init --recursive
forge build
```

Check the environment is on-pin — the demo is worthless against a drifted SDK:

```bash
git -C ~/src/sdk rev-parse HEAD     # must be 6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938
~/venv312/bin/python -V             # 3.12.x
forge --version                     # 1.8.1
```

Do a full dry run. `make hero-demo` rebuilds the fork fixture each time and takes ~2 minutes
wall clock, of which the 12 demo steps are ~3 seconds.

## 0:00–0:15 — The problem

> "Almanak decides strategy actions and KeeperHub executes them. Held handles the part
> around a change: customer-approved operating limits, and recoverable runner handovers when
> execution becomes uncertain."

Show the README diagram. Do not read the architecture aloud.

## 0:15–0:35 — Terms

Show the console Terms view, or demo steps 1–2:

- approved supply ceiling `50000000000`
- used `12000000`
- remaining `49988000000`
- runner A, epoch 1
- evidence grade **REAL LOCAL FORK**

Say the grade out loud. It is the credibility of everything that follows.

## 0:35–1:10 — Real execution

Run the supply and show it land:

> "This is an Almanak-shaped bundle, admitted by Held, signed by runner A with EIP-712,
> executed by the controller through Zodiac Roles against real Morpho on a Base-mainnet
> fork. Twelve USDC actually leaves the Safe."

**If the public KeeperHub transaction exists by recording time, open it here and say so
explicitly.** If it does not:

> "The KeeperHub execution is not established yet — it needs an organisation credential we
> do not have. It is not stubbed and not simulated, and the repository says so."

Do not skip this sentence. A judge who discovers it later discounts everything else.

## 1:10–2:05 — The hero: recovery and handover

This is the centre of the demo. Walk demo steps 3–12:

1. An operation goes **ambiguous** — the send never returned.
2. Attempt the handover. **It is refused**, naming the unresolved operation.
3. Reconcile: the verdict comes from `consumed[operationId]` on chain, not the transport's
   silence.
4. Owner **fences** — note that Held prepared the transaction and the owner sent it.
5. Bounded authority inventory: 9 sections, complete.
6. Prepare runner B, pinned to the consumption actually on chain.
7. Owner **activates**.
8. **`usedSupply` is still 12000000.** Remaining still 49988000000. The budget survived.
9. Runner A **attempts** its old authorization → reverts `WrongEpoch(uint64,uint64)`.

Linger on 8 and 9. They are the product.

## 2:05–2:30 — Operator console

Four views, ~6 seconds each: Terms, Activity, Unresolved, Authority/Handover. Point at the
evidence-grade labels.

## 2:30–2:50 — Reliability

Show **two real defects found by adversarial review**, and the regressions that now cover
them. Do not show a test count.

1. The `SetAuthorization` decoder could not read real `cast logs` output — it indexed
   32-byte words positionally and the block hash comes first. The whole grant-discovery path
   was inert against live data, hidden by a simplified test fixture.
2. `restore()` accepted a native snapshot belonging to a *different* decision and reported
   the operation complete.

> "Both were found by reviewing the corrections, not the original code."

## 2:50–3:05 — Scope honesty

> "Supported today: one Safe, one Morpho market, supply and withdraw, on a fork. Not
> claimed: a public KeeperHub execution, an audit, or production readiness."

## 3:05–3:15 — Close

> "Held does not replace Almanak, KeeperHub, Safe or Morpho. It makes customer-approved
> changes and runner handovers across them recoverable."

## Hard rules

- Never show a number not in the claim ledger.
- Never say "executed through KeeperHub" until M1 is VERIFIED.
- If a step fails live, say what failed. Do not re-record over it silently.
- The fork is a fork. Say so at least twice.
