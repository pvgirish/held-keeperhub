# Submission pack

Final copy for every field the form is likely to ask for. Written to be pasted.

**One rule applied throughout:** no sentence here would be false without a public
transaction, unless it is explicitly marked as not yet established. Nothing needs to be
walked back later.

**Evidence labels used below, and they never blur:**

| Label | Means |
|---|---|
| **FORK VERIFIED** | Real pinned contracts on an anvil fork of Base. Proves behaviour; proves nothing about mainnet. |
| **PREPARED** | Calldata, parameters, estimates. Nothing executed. |
| **PUBLIC MAINNET VERIFIED** | A transaction in Base's history, re-read from a public RPC by `make mainnet-evidence-gate`. **Held has none.** |

---

## Project name

**Held**

## One-line tagline

> Customer-approved operating limits and recoverable runner handover for autonomous
> strategies — enforced on-chain, executed through KeeperHub.

## Short description (≈50 words)

> Held sits between an Almanak strategy and its funds. The customer approves operating
> limits; a Zodiac Roles module and a Safe enforce them on-chain. When an execution's
> outcome is unknown, Held refuses to hand over to a new runner until the operation is
> reconciled against the chain — so one operation is never executed twice.

## Full description

> An autonomous strategy that can move real money raises three questions before anyone
> sensible funds it: **what is the worst it can do today, what happens when it goes quiet
> mid-execution, and who can move my money right now?**
>
> Held answers all three.
>
> **The limits are the customer's, and the chain enforces them.** The owner approves
> cumulative ceilings, a per-action maximum, a per-action minimum, a cash floor the Safe
> may never go below, a count limit and one market. Those live in a Zodiac Roles v2 module
> and a Safe 1.4.1 — not in a config file Held reads — so the guarantee does not depend on
> Held behaving. All five native budgets are **non-refilling**: a spent budget stays spent
> until an owner re-sets it.
>
> **Held holds no key and no funds.** It intercepts the Almanak `ActionBundle`, admits
> exactly one supported action or refuses, derives an operation identity bound to chain,
> controller, Safe and lineage, and has a runner sign an EIP-712 envelope. The runner signs
> and never transacts — it needs no ETH. KeeperHub broadcasts. The controller recomputes
> the action hash from the arguments it actually receives and checks the signature against
> the *current* epoch.
>
> **The hard part is the unknown outcome.** Held sends, the connection drops, and nobody
> knows whether the transaction landed. Rotating the runner now is how one operation gets
> executed twice — and it is a well-meaning operator who does it, not an attacker. Held
> writes a durable claim plus the exact replayable request in one transaction *before any
> I/O*, treats an ambiguous result as `UNKNOWN` rather than "not sent", and refuses the
> handover on the unresolved operation id derived from its own journal. The owner fences
> the epoch — every signature the old runner made becomes permanently unusable — and only
> then is it safe to reconcile against the controller's own `consumed[]` record.
> Consumption carries across the handover, so the new runner inherits the spent budget
> rather than a fresh one.
>
> **Status, stated plainly:** everything above is exercised against real pinned contracts
> on a Base-mainnet fork. Nothing has been deployed, funded or broadcast on public Base.
> The KeeperHub organisation route accepts our credential (200, `hosted=true`, scope
> `mcp:read`); we have not executed through it. The repository contains a gate whose only
> job is to stop our own fork evidence from being read as mainnet evidence.

## The problem

Agent frameworks got good at deciding. The operational layer under them did not keep up.

Three failures, in the order they bite:

1. **No enforced ceiling.** "The strategy is configured to spend at most X" is a sentence,
   not a constraint. If the process is wrong, compromised, or simply restarted with a stale
   config, nothing stops it.
2. **The unknown outcome.** A submission that never returns might have executed. Treating
   it as "failed" and retrying executes it twice. Treating it as "succeeded" loses the
   operation. Most tooling gives you a nonce and a hope.
3. **The handover that races.** The customer wants a different runner. Rotating the key
   while an operation is in flight is the single most likely way to lose money here — and
   afterwards the new runner typically gets a *fresh* budget, silently doubling the cap the
   customer approved.

None of these is exotic. All three happen on an ordinary Tuesday.

## The solution

| Problem | What Held does | Verified |
|---|---|---|
| No enforced ceiling | Limits live in Zodiac Roles + Safe, non-refilling, enforced on every call | **FORK VERIFIED** — second attempt reverts `FloorViolated()` |
| Unknown outcome | Durable claim before any I/O; `UNKNOWN` is never read as "not sent"; resend under the identical idempotency key | **FORK VERIFIED** — incl. real `SIGKILL` |
| Racing handover | Refuses on the unresolved operation id; fence, then reconcile against chain | **FORK VERIFIED** — `UNRESOLVED:0x…` |
| Budget resets on swap | Consumption carried across the handover | **FORK VERIFIED** — `usedSupply` unchanged |
| Replay | Controller refuses a consumed authorization | **FORK VERIFIED** — `OperationConsumed(bytes32)` |
| Stale runner after fence | Old signatures permanently unusable | **FORK VERIFIED** — `WrongEpoch(uint64,uint64)` |

## How it works

```
Owner ─approves limits─▶ Held ─▶ KeeperHub ─▶ HeldController ─▶ Zodiac Roles ─▶ Safe ─▶ Morpho
  ▲                        │                  epoch + EIP-712    5 budgets      2-of-3
  └─── can fence, revoke ──┘                                            funds never leave the owner
```

1. The Almanak strategy produces a decision. Held intercepts the `ActionBundle`.
2. Held admits **exactly one** supported action or refuses. There is deliberately no
   generic "call the controller with these bytes".
3. Operation identity is derived from chain, controller, Safe and lineage — so an operation
   admitted under one profile cannot be signed for another.
4. Runner B signs an EIP-712 envelope. It signs; it never transacts.
5. Held writes the durable claim **and** the replayable request in one transaction, then
   sends to KeeperHub with an `Idempotency-Key` bound to the attempt.
6. The controller checks epoch, policy version, scope, family and payload hash, then calls
   through Roles, which checks the condition tree and the five budgets, into the Safe.
7. Held reconciles the journal against `consumed[operationId]` on chain.

## Technical implementation

| Layer | What | Where |
|---|---|---|
| Decision | Almanak SDK pinned `6e83e00e` — real `IntentCompiler`, real `ActionBundle`, executed in-process | `adapter/held_adapter/execution/interceptor.py` |
| Identity | `operation_id` over chain, controller, Safe, lineage | `packages/core/held_core/identity.py` |
| Authorization | EIP-712; the signer recovers from its own output and refuses a key that is not the configured runner | `adapter/held_adapter/signing/runner_signer.py` |
| Durability | SQLite journal; claim + request in ONE transaction before any I/O | `packages/core/held_core/journal.py` |
| Execution | KeeperHub REST `POST /api/execute/contract-call` | `adapter/held_adapter/execution/keeperhub.py` |
| Enforcement | `HeldController` → Zodiac Roles v2 → Safe 1.4.1 → Morpho Blue | `contracts/src/HeldController.sol` |
| Installation | One canonical installer, 15 owner actions | `contracts/src/install/HeldInstall.sol` |
| Handover | Durable restartable machine, 8 states + BLOCKED | `packages/handover/held_handover/machine.py` |
| Operator view | Localhost console; holds no keys | `console/run.py` |

**Testing.** 257 tests in `make check-phase-03-local` alone; 39 handover, 31 core, 44
console, plus Solidity suites against the real pinned contracts. Three independent review
rounds found ~30 real defects, all closed with regressions that assert the **refusal**
rather than the success.

**Measured on the pinned fork with the final identities** (`make final-rehearsal`,
**FORK VERIFIED**):

| Step | Gas |
|---|---|
| Safe deploy | 283,452 |
| Roles deploy | 190,822 |
| `enableModule(ROLES)`, 2-of-3 | 101,048 |
| 15-action ceremony, 2-of-3 throughout | 3,994,368 incl. approvals |
| `activate`, 2-of-3 | 308,029 |
| `executeSupply` | 485,779 |

Cost ceiling priced against live Base fees and the on-chain Chainlink ETH/USD feed:
**≈$2.60 at 3× headroom**, excluding Base's L1 data fee — a gap recorded, not omitted.

## KeeperHub usage

Held uses KeeperHub's **direct contract-call execution**, not the workflow builder.

- `POST /api/execute/contract-call`, `Authorization: Bearer <organisation key>`
- `Idempotency-Key` = `keccak(domain ‖ operationId ‖ attemptId)` — bound to the **attempt**,
  so a timeout retry collapses and a deliberate replacement does not
- `GET /api/execute/{id}/status` to resolve an ambiguous send
- 202 as the documented write success; the two documented 409 codes kept as opposite
  outcomes rather than one branch
- Scopes: `mcp:read` reads and simulates; `mcp:write` / `mcp:admin` broadcast

**Established (P30, AUTHENTICATED HOSTED):** the live organisation route accepts Held's
credential over HTTPS — 200, the configured secret matches a listed organisation key by its
documented `keyPrefix`, scope `mcp:read`. A fact about a **credential**, not an execution.

**Not established:** M1 (a real transaction through KeeperHub), P18 (Held has executed
through KeeperHub), L10 (the caller/payer accepts Held's outer controller call), P19
(KeeperHub's server-side encoder reproduces Held's intended calldata). All need a deployed
controller; none exists.

46 wire-contract tests run against `OfflineTransport`, which stamps `hosted=false`; four
tests exist solely to prove a local result cannot be filed as a hosted one.

## Real-world impact

**"What is the worst this can do today?"** A number the customer set and the chain
enforces: at most `Ms` per action, at most `Ls` ever, never below the floor `F`, at most
`Nn` times, in one market. Not a policy document — a revert.

**"The runner went quiet. Now what?"** This is where real money is lost, and not to
attackers. Held makes the dangerous sequence *refuse*.

**"Who can move my money right now?"** A bounded inventory at one stated block, with
provenance per section, that reports INCOMPLETE rather than guessing — and blocks
activation when it does.

**Who it is for:** anyone running an Almanak strategy against a Safe they do not want to
watch continuously. The limits stay the customer's, the keys stay the customer's, Held
holds nothing.

**Honest sizing:** one market, one chain, one supply path, two withdraw lanes. A deep
vertical slice, not a platform.

## Product advantage

The honest comparison is published and **it does not favour Held on cost**
(`evidence/P06/comparison.json`, **FORK VERIFIED**):

| | Native Safe + Roles | Held |
|---|---|---|
| Clean policy change | cheaper | **more expensive** |
| Interrupted handover | tie | tie |
| Owner ceremonies for a handover | 1 | **2** |

Held needs two ceremonies because the controller refuses `activate` while active and
requires the fence CONFIRMED and the retiring epoch reconciled first. A real constraint,
reported as a cost. Claims C1 and W1–W8 once said otherwise; they are **withdrawn and kept
visible** in the ledger.

The advantage is what native does not have:

1. **An unknown outcome is a first-class state**, not a nonce and a hope.
2. **Handover cannot race an in-flight operation.** The refusal is behavioural.
3. **Consumption survives the handover.** Rotating keys natively resets nothing and tells
   you nothing.
4. **The authority question is answerable**, by something that can fail closed.
5. **The refusals are named.** `FloorViolated()` is much stronger evidence than "it
   reverted".

In one line: **native is cheaper at doing the right thing; Held is better at not doing the
wrong thing twice.**

## Security and authority model

Five parties, and **none can move funds alone**:

| Party | Holds | Can it move money alone? |
|---|---|---|
| Almanak strategy | nothing | No — it proposes; Held decides admissibility |
| Held | nothing | No — it holds no key |
| Runner B | one signing key | No — a signature authorizes; it cannot send |
| KeeperHub | the executing wallet | No — only `executeSupply`, only with a valid signature the controller checks |
| Safe owners | 2 of 3 | **Yes** — they own the Safe |

A stolen runner key can only cause actions the owner already approved, up to ceilings the
owner already set, into the market the owner already chose. Recovery is one owner ceremony.

**Deliberately not defended against:** owner collusion; a break in Safe, Zodiac or Morpho;
oracle manipulation in the chosen market; KeeperHub censorship (detectable, not
preventable); KeeperHub's server-side encoder (P19, unproven).

Full analysis: [`THREAT-MODEL.md`](THREAT-MODEL.md).

## Challenges

**The unknown outcome was harder than the happy path, by a wide margin.** Most of the
difficulty was resisting the convenient answer. A zero reading of `consumed[operationId]`
at one block feels like proof of non-execution; it is not — the original transaction can
still land. The only evidence that settles it is *retirement of the authorization*. An
earlier version fell through and resent. That is now a refusal with a test.

**Three review rounds found ~30 real defects.** Some were ours, and instructive:

- A `SetAuthorization` decoder indexed 32-byte words positionally. Real `cast logs` output
  puts `blockHash` and `data` before `topics`, so every real entry was malformed and the
  discovery path was inert. It passed because the fixture emitted a simplified shape.
- `collect()` read whatever report was on disk, so a stale inventory collected *before* the
  fence rendered as a live one. It now requires an mtime change.
- `assert_can_broadcast()` was written, documented, and called by nothing outside its own
  tests. The production path claimed a journal row and sent, and a read-only key would have
  earned a 403 *after* the operation was DISPATCHED.
- The scope parser split on whitespace only. The organisation's write key reads
  `mcp:read,mcp:write,mcp:admin` — comma-joined, that parsed as one unknown token, so Held
  would have refused its own valid write key at the worst possible moment.

**Measuring honestly cost us our headline.** The native-vs-Held comparison was run twice;
the corrected result does not favour Held. Publishing it and withdrawing eight claims was
the right call and it made the submission weaker-sounding and more trustworthy.

## What was built during the hackathon

Everything in this repository: the adapter and interceptor, the identity and journal layer,
`HeldController` and its canonical installer, the bounded authority inventory, the durable
handover machine, the operator console, the KeeperHub client, and the whole evidence
apparatus — claim ledger, evidence index, submission gate, pre-broadcast gate, mainnet
evidence gate, contradiction audit.

Not built here and not claimed: Almanak, KeeperHub, Safe, Zodiac Roles, Morpho.

## Future work

- **Close M1/M2.** Deploy, fund, execute. Everything is rehearsed; only money and
  authorization are missing.
- **Settle P19** with one authenticated dry run against the deployed controller.
- **Remove the server-side encoding dependency** by sending raw calldata if KeeperHub
  supports it.
- **More markets and lanes.** The scope is one market by choice, not by limitation.
- **Finish the console's HTML rendering.** Live mode reads real sources and refuses to fall
  back to demonstration data; the four views are still prototype.
- **An audit.** Finite testing is not an audit and this says so everywhere.

## Links and placeholders

Every link below is a placeholder. Filling one in without a matching public transaction is
refused by `make mainnet-evidence-gate`, which re-reads the record from a public Base RPC.
Fill-on-execution templates: [`evidence/M1/templates/`](../../evidence/M1/templates/).

| Field | Value | Label |
|---|---|---|
| GitHub URL | `https://github.com/pvgirish/held-keeperhub` — **private today** | PREPARED |
| Video URL | *not recorded* — see [VIDEO-SCRIPT.md](VIDEO-SCRIPT.md) | PREPARED |
| Network | Base mainnet, chain id 8453 | — |
| Safe | `https://basescan.org/address/…` — *not deployed* | PREPARED |
| Zodiac Roles module | `https://basescan.org/address/…` — *not deployed* | PREPARED |
| HeldController | `https://basescan.org/address/…` — *not deployed* | PREPARED |
| Owner ceremony (15 tx) | *not executed* | PREPARED |
| Activation tx | `https://basescan.org/tx/…` — *not executed* | PREPARED |
| **The supply tx (M1)** | `https://basescan.org/tx/…` — *not executed* | PREPARED |
| KeeperHub execution id | *not executed* | PREPARED |
| Morpho position | `https://basescan.org/address/…` — *not created* | PREPARED |
| Licence | [MIT](../../LICENSE) | — |

**Already-deployed contracts Held uses** (not ours, listed so a judge can verify the
integration is real):

| | Address |
|---|---|
| Safe singleton 1.4.1 | `0x41675C099F32341bf84BFc5382aF534df5C7461a` |
| SafeProxyFactory | `0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67` |
| Zodiac ModuleProxyFactory | `0x000000000000aDdB49795b0f9bA5BC298cDda236` |
| Zodiac Roles v2 mastercopy | `0x9646fDAD06d3e24444381f44362a3B0eB343D337` |
| Morpho Blue | `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` |
| USDC (native) | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` |
| Market id | `0x13c42741a359ac4a8aa8287d2be109dcf28344484f91185f9a79bd5a805a55ae` |

## Judging-criteria mapping

| Criterion | Where | Strength |
|---|---|---|
| Working integration with a live project | Almanak SDK pinned and executed in-process; 26 tests against the real compiler | **Strong** |
| KeeperHub usage | Direct contract-call execution; 46 wire-contract tests; credential validated live (P30) | **Partial** — route accepts us; no execution |
| A real transaction (M1) | — | **Not met** |
| Technical depth | 3 review rounds, ~30 defects closed, refusal-asserting regressions, `SIGKILL` coverage, full ceremony rehearsed 2-of-3 | **Strong** |
| Originality | The recoverable-handover problem appears unaddressed in this space | **Strong** |
| Evidence quality | Five never-promoted grades, a gate that re-reads mainnet claims from a public RPC, withdrawn claims kept visible | **Strong** |
| Completeness / polish | README, runbook, threat model, claim ledger, evidence index, video script, MIT licence | **Good** |
| Public accessibility (M3) | Repository private; licence now present | **Partial** |
| Demo video (M4) | Script and shot list written; not recorded | **Not met** |

`make submission-gate` returns **BLOCKED** and will keep returning BLOCKED until a public
transaction exists. A mandatory requirement is not waived by strong engineering, and the
gate is written so nobody can decide otherwise on the night.

## If asked why to look anyway

Because the failure this is built around is the one that actually happens, and because the
repository is unusually honest about what it has not shown. The comparison measurement does
not favour us and we published it. Eight claims are withdrawn and kept visible. There is a
gate whose entire job is to stop our own fork evidence being read as mainnet evidence, and
fifteen tests that attack it.

If M1 lands, everything above it is built and rehearsed end to end with the final
addresses. If it does not, this is still a correct answer to a problem the field has not
finished noticing.
