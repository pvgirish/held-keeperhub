# Video script — 2-minute and 5-minute cuts

Two narrations, one shot list, and the explorer links that have to exist before either can
be recorded honestly.

**Nothing here has been recorded.** M4 is NOT YET ESTABLISHED.

**The hard rule, inherited from the demo runbook:** every number spoken on camera must be
readable on screen at the moment it is spoken. If a figure cannot be shown being produced,
it is cut — not softened.

---

## Before recording: what must be true

| | Required for the 2-min cut | Required for the 5-min cut |
|---|---|---|
| Fork rehearsal passes | yes | yes |
| `make hero-demo` passes | yes | yes |
| Console runs in live mode | no | yes |
| **A public Base transaction exists (M1)** | **yes** | **yes** |
| Repository public with a licence (M3) | for the link card | for the link card |

**The video stays last on purpose.** A demo recorded before M1 would either show a fork and
call it mainnet — which is the exact failure `make mainnet-evidence-gate` exists to prevent
— or would have a hole where its central claim belongs. Record after the receipt exists.

---

## The 2-minute cut

Aimed at a judge with forty submissions to get through. One problem, one proof, one honest
limit.

### 0:00–0:20 — The problem

> "An Almanak strategy just sent an execution. The connection dropped. You don't know
> whether it landed.
>
> Now the customer wants a different runner. If you rotate the key, you might execute that
> operation twice. If you wait, you're stuck."

**On screen:** the journal row, state `UNKNOWN`, with the operation id visible.

### 0:20–0:50 — What Held does about it

> "Held refuses the handover. Not with a warning — it blocks on the unresolved operation
> id, read out of its own journal.
>
> First it fences the epoch. That's one owner transaction, and after it every signature the
> old runner made is permanently unusable. Only *then* is it safe to ask what happened.
>
> It reconciles against `consumed[operationId]` on chain. Not a timeout. Not a guess."

**On screen:** `HandoverBlocked: UNRESOLVED:0x…` → the fence tx → the consumption readback.

### 0:50–1:20 — The limits are on-chain

> "The customer approved limits. At most 10 USDC per action, 50,000 ever, never below a
> one-USDC floor, ten actions total, one market.
>
> Those aren't in a config file Held reads. They're in a Zodiac Roles module and a Safe.
> Watch the second supply."

**On screen:** the first supply succeeds — 10 USDC moves, Morpho position appears. The
second reverts: **`FloorViolated()`**. Then the replay: **`OperationConsumed(bytes32)`**,
counters unmoved.

### 1:20–1:45 — Through KeeperHub, on Base

> "That execution went out through KeeperHub's contract-call API, with an idempotency key
> bound to the attempt, and landed on Base."

**On screen:** the KeeperHub execution id, then BaseScan, then the Morpho position.

### 1:45–2:00 — The honest close

> "One market, one chain, one supply path. The gas comparison against a plain Safe doesn't
> favour Held, and we published the measurement that says so.
>
> What Held has is the thing that isn't in the gas number: an unknown outcome that can be
> resolved without executing twice."

**On screen:** the comparison table, native cheaper on the clean change.

---

## The 5-minute cut

The 2-minute beats, plus the three things a technical judge will want to check.

### 0:00–0:45 — Problem and architecture

As above, then the chain on screen:

> "Almanak decides. Held admits only what the customer approved. A runner signs an EIP-712
> envelope — it signs, it never transacts, it holds no ETH. KeeperHub broadcasts. The
> controller, the Roles module and the Safe enforce.
>
> Held holds no key. If Held is compromised, the worst it can do is build a request that
> still needs a signature it can't produce."

### 0:45–1:40 — Terms, and the bounded inventory

> "Before activation, Held answers a question most tooling can't: who can move this money
> right now?
>
> One bounded readback at one stated block. Safe ownership and threshold. Enabled modules.
> Role membership and condition trees. All five native budgets. Morpho grants, confirmed by
> mapping readback.
>
> Nine sections, and it can fail. If a section is unreadable it reports INCOMPLETE and
> blocks activation — it does not guess."

**On screen:** the inventory output, then delete a readable source and re-run so INCOMPLETE
appears on camera.

### 1:40–2:40 — Real execution, and the two refusals

As the 2-minute cut, slower, with the controller state before and after and both refusals
named on screen.

### 2:40–3:50 — The hero: recovery and handover

> "Runner A dispatched an operation and the server dropped the connection after receiving
> it. The journal says UNKNOWN — not 'failed', because we genuinely do not know.
>
> Handover refuses. Fence. Reconcile against the chain. Bounded inventory — and note it has
> to be collected *after* the fence; a report from before is refused as stale, which is a
> bug we shipped once and now fail closed on.
>
> Prepare the candidate. Activate runner B at a higher epoch.
>
> The number that matters: runner A had spent 12 USDC. Runner B inherits `usedSupply` of
> 12 USDC. It does not get a fresh budget."

**On screen:** `[12000000, 0, 0, 1, 0]` carried across; `usedSupply` unchanged; remaining
`49988000000`; runner A's stale attempt reverting `WrongEpoch(uint64,uint64)` `0x2b9264ec`.

### 3:50–4:25 — Evidence discipline

> "Five evidence grades, never promoted. Most of this repository is REAL LOCAL FORK, and it
> says so.
>
> This gate re-reads anything claiming public Base from a public RPC. Watch what happens if
> I relabel the fork rehearsal as a mainnet result."

**On screen:** relabel the record, run `make mainnet-evidence-gate`, show **REFUSED — does
not exist on public Base**.

> "Eight claims in this ledger are withdrawn. They're still visible."

### 4:25–5:00 — Limits and close

> "What isn't proven: KeeperHub's server-side encoder reproducing our calldata byte for
> byte. That needs one authenticated dry run and it's on the list, unticked.
>
> One market, one chain. The gas comparison doesn't favour us.
>
> Held is for the case where a strategy can move real money and somebody has to be able to
> answer what it can do, and what happens when it goes quiet."

---

## Shot list

Screenshots double as submission stills. `FORK` / `PREPARED` / `PUBLIC MAINNET VERIFIED`
must be legible in any shot where it applies.

| # | Shot | Source | Label | Cut |
|---|---|---|---|---|
| 1 | Journal row, state `UNKNOWN` | `make hero-demo` step 3 | FORK | both |
| 2 | `HandoverBlocked: UNRESOLVED:0x…` | hero-demo step 5 | FORK | both |
| 3 | Fence transaction + confirmation | hero-demo step 7 | FORK | both |
| 4 | `consumed[operationId]` readback | hero-demo step 6 | FORK | both |
| 5 | Bounded inventory, 9 sections COMPLETE | `make final-rehearsal` | FORK | 5-min |
| 6 | The same inventory reporting INCOMPLETE | source removed | FORK | 5-min |
| 7 | Activation readback: epoch 1, runner B, executor | `make final-rehearsal` | FORK | 5-min |
| 8 | First supply — 10 USDC moves | `make final-rehearsal` | FORK | both |
| 9 | Second attempt — `FloorViolated()` | `make final-rehearsal` | FORK | both |
| 10 | Replay — `OperationConsumed(bytes32)` | `make final-rehearsal` | FORK | both |
| 11 | Consumption carried: `[12000000,0,0,1,0]` | hero-demo step 8 | FORK | 5-min |
| 12 | Stale runner — `WrongEpoch` `0x2b9264ec` | hero-demo step 11 | FORK | 5-min |
| 13 | Four console views, live mode | `make console-live` | FORK | 5-min |
| 14 | Comparison table, native cheaper | `evidence/P06/comparison.json` | FORK | both |
| 15 | Relabelled record REFUSED | `make mainnet-evidence-gate` | — | 5-min |
| 16 | **KeeperHub execution id** | the real submission | **PUBLIC MAINNET VERIFIED** | both |
| 17 | **BaseScan: the supply transaction** | `FILL:` | **PUBLIC MAINNET VERIFIED** | both |
| 18 | **Morpho position on BaseScan** | `FILL:` | **PUBLIC MAINNET VERIFIED** | both |
| 19 | **Safe balance = 1.000000 USDC** | `FILL:` | **PUBLIC MAINNET VERIFIED** | both |
| 20 | Claim ledger, withdrawn claims visible | `CLAIM-LEDGER.md` | — | 5-min |

**Shots 16–19 cannot be filmed today.** They are the whole of M1.

---

## Explorer links

Every one is a `FILL:` sentinel. Filling one in without a matching public transaction is
refused by `make mainnet-evidence-gate` — the record is re-read from a public Base RPC.

| What | Link |
|---|---|
| Safe | `FILL:https://basescan.org/address/…` |
| Roles module | `FILL:https://basescan.org/address/…` |
| HeldController | `FILL:https://basescan.org/address/…` |
| Ceremony (15 tx) | `FILL:` — 15 links |
| Activation | `FILL:https://basescan.org/tx/…` |
| **The supply (M1)** | `FILL:https://basescan.org/tx/…` |
| Morpho position | `FILL:https://basescan.org/address/…` |
| Repository | `FILL:` — private today (M3) |
| Video | `FILL:` — not recorded (M4) |

---

## Recording rules

1. **Never show a fork result without the FORK label on screen.**
2. **Never say "on Base" about a fork.** Say "on a Base-mainnet fork", every time.
3. **No number is spoken that is not visible** at the moment it is spoken.
4. **Do not soften the comparison.** Native is cheaper on the clean change. Say it.
5. **Name the refusals.** `FloorViolated()` beats "it reverted".
6. **Do not re-record around a failure.** If something fails on camera, that is the take —
   fix the thing, then record again from a clean state.
