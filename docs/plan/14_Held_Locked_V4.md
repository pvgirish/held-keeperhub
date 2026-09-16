# Held — Locked V4
## Owner-approved strategy changes and recoverable handover

**Status: implementation plan locked; capabilities and competitive advantage are not yet demonstrated.**
**Date: 15 September 2026.** Scope and sequencing do not depend on the hackathon deadline.

**Sequencing amendment A1, 15 September 2026:** P00 now records route evidence by layer and runs the native baseline before P01. P06 retains comparability checks and justified, versioned baseline reruns. Product guarantees and the P05 console scope remain unchanged. See the [amendment review](16_P00_Amendments_and_Explainer_Review.md); the original files are preserved under work/held-v4-amendment/before/.

This is the authoritative plan for the next implementation. It replaces V3 for that implementation only; historical specifications remain untouched. “Locked” fixes the product promise, safety boundaries and acceptance conditions. It does not certify a deployment, earn a 25/30 score or predict a prize.

Companions: [phase prompts](15_Held_V4_Phases_and_Prompts.md), [competition brief](../work/competition-brief-2026-09-15-supplied-page.md), [configuration evidence](09_Held_Configuration_Gate_and_Feedback_Review.md).

## 1. The product decision

**Held lets an operator run a supported native Almanak strategy under customer-approved limits, then change those limits or replace the runner without losing consumption history or guessing what an interrupted operation did.**

The owner sees one review surface for terms, changes, unresolved work and authority evidence. Held coordinates several systems; it does not collapse their state into one store.

First customer: an operator using the public Almanak SDK and gateway with a customer-controlled Safe. Hosted Almanak support is not advertised. The operator and owner can belong to the same organization. No artificial paid-agent hiring relationship is required.

The recurring machine job is exact admission of supported compiled actions. The human job is reviewing changes and resolving interruption or replacement. A legitimate HOLD is a successful no-action decision.

### What the latest comparison establishes

| Feedback claim | Locked correction |
|---|---|
| Six state stores become one | They remain distributed, with additional Held state. One coordinated review/reconciliation surface is the proposed benefit. |
| Native is half-finished while Held is atomic | Give native tools the same Safe batching and transaction boundaries. Both have off-chain configuration and recovery work. |
| The original Roles allowance exists only off-chain | Prior settings can be recovered from available chain transaction/event history. Convenience and discoverability must be measured. |
| Nothing native handles uncertain execution | Almanak and KeeperHub have recovery machinery. Reuse it and compare the complete workflow. |
| One signature versus one signature | Count owner approval ceremonies, on-chain transactions and individual signatures separately. A 2-of-3 Safe is not a one-signature account. Held makes no saving claim. |
| Runner A/B are the Held Role members | The controller remains the sole member of the operating roles. Runner authorization changes in the controller. |
| A live protected installation may retain A's Morpho grant | It may not. A legacy grant is a labeled migration or authority-drift fixture, separate from the valid protected baseline. |
| The adapter refusing B gives the same handover guarantee | Only if B has no independently usable on-chain authority. V4 keeps the controller paused until an owner-authorized activation. |
| A nonce recognizes any duplicate intended payment | It rejects reuse of an identified operation. It cannot identify equivalent economics under a freshly invented operation identity. |
| Three of four measures already prove superiority | Withdraw the result. The written comparison is a test specification. Measure the result in P06. |

Documentation and a reproducible comparison can establish a technical workflow improvement without mandatory interviews. They do not establish how often actual operators suffer the problem or whether users prefer the product. Neither missing customer interviews nor existing primitives automatically disqualifies this hackathon integration.

## 2. First supported profile

- One mandate lineage, one customer-owned Safe, one reviewed Morpho Blue deployment and loan-asset supply market.
- Production reference: Base and native USDC. P00 must pin and read back the actual deployment, token, market, decimals and implementations. No address or live market is assumed validated.
- Supported native actions: fixed-asset SUPPLY, fixed-asset WITHDRAW to the same Safe, and HOLD.
- Zero borrow shares before and after each admitted operation. Existing collateral is permitted but must remain unchanged within that operation.
- No borrowing, collateral supply/withdrawal, arbitrary recipients, callbacks, arbitrary targets, general delegatecall, MAX/all amounts, bridge, or unrelated strategy management.
- The Safe's entire selected market supply position is the withdrawal source. External supply credits are fungible; historical attribution does not segregate their spendability.
- Owner custody and recovery remain independent of Held and KeeperHub. The execution coalition cannot satisfy the Safe owner quorum.
- Reject an incompatible shared Safe rather than revoke permissions used by unrelated agents without informed owner approval.
- Native economic calldata must match the compiled supported action. Morpho's account ABI field is **onBehalf**. The compiler's Morpho helper living in a file named aave_helpers.py does not make it an Aave integration.

Public testnet evidence is preferred when a genuine supported Morpho deployment, native compiler configuration and KeeperHub route are available. Otherwise prepare an explicitly authorized small-value Base execution. A mock protocol or local fork is not public transaction evidence for an existing deployed protocol. Resolve this in P00; do not silently substitute a token transfer.

Current discovery evidence: Morpho's official registry lists a Base Sepolia deployment, and KeeperHub's public chain catalog returned that network as enabled on 15 September 2026. This establishes a candidate, not its usable market, native SDK support or authenticated caller/payer route. The Morpho plugin's mainnet list does not constrain the distinct generic direct-execution route. P00 must keep those evidence layers separate; absence from one page is not proof that no deployment exists. Base mainnet is a conditional V4 fallback, not an event-imposed network requirement.

## 3. Architecture and authority

~~~mermaid
flowchart LR
    A[Native Almanak strategy and compiler] --> B[Held adapter and durable journal]
    B --> C[Runner signs exact operation envelope]
    C --> D[KeeperHub simulation and submission]
    D --> E[Held controller]
    E --> F[Scoped Zodiac Roles]
    F --> G[Customer Safe]
    G --> H[Morpho supported action]
    H --> I[Receipt, events and state reconciliation]
    I --> B
    B --> J[Native Almanak result]
    O[Customer Safe owners] --> E
~~~

### Component contract

| Component | Responsibility | Does not establish |
|---|---|---|
| Almanak | Native decision, compilation, risk checks and result consumption | That Held's custom execution route works merely because an API exists |
| Adapter/journal | Canonical action admission, durable source identity, dispatch, reconciliation, bounded inventory and usable coordination | Independent on-chain authority or truth of missing historical data |
| Runner key | Authorizes the exact operation envelope for its current epoch | Owner configuration authority |
| KeeperHub | Actual approved outer execution, simulation, execution record, submission/status machinery | Lifetime replay protection or customer ownership independence by default |
| Controller | Current-epoch authorization, per-operation consumption, finite terms, atomic checks and pause/activation | A universal scanner or recognition of semantic duplicates with different IDs |
| Roles | Fixed targets/arguments and native non-refilling allowance defense | All state-dependent Held predicates or complete external authority |
| Safe owners | Custody, installation, fence, cleanup, policy change, activation and recovery | A cryptographic proof that an inventory covered unavailable history |

### Exact route

Intercept the native ActionBundle before Zodiac/Safe wrapping and signing. Preserve native risk validation and receipt/result semantics. Submit the reviewed outer controller call through an actually supported KeeperHub route. Observe payer, outer sender, controller caller, Roles member, Safe caller and protocol receiver separately.

The controller exposes only typed SUPPLY and WITHDRAW execution entry shapes. Decode and compare native core calls against those shapes; never execute an arbitrary caller-supplied call list. It makes sequential ordinary CALL operations through Roles in one outer transaction, with explicit return/revert checking. No runtime-selected MultiSend or delegatecall shortcut is allowed.

The controller is the sole member of its narrowly scoped operating roles. Neither runner is given a direct Role path around it. Roles may use separate normal/restoration roles and shared count allowances where the policy requires them; each remains controller-only.

Runner identity must not be inferred from a KeeperHub API key. Two API keys can share an execution address. V4 uses a current-epoch runner authorization key to sign an EIP-712 envelope before KeeperHub submits it. The controller verifies that signature and its configured executor route. Old Runner A credentials cannot become Runner B just by copying the new epoch number. The supported first signer is an ordinary EOA with reviewed signature recovery; use an established library, not custom ecrecover handling. Broader contract-account signers require a versioned extension.

Owner recovery can bypass operating limits because it is owner authority, not delegated automation. Controller calls cannot change Safe owners/modules, grant Morpho delegation, select a new market or modify their own policy.

## 4. Identity, journal and replay contract

### Three distinct identities

1. **Business operation ID:** a stable native decision/action identity, persisted before any submission. It is scoped to chain, controller, Safe and mandate lineage. Its consumed identity does not reset when an epoch or runner changes.
2. **Authorization envelope:** operation ID, native source identity, exact action/payload hash, current epoch, policy version and domain. Runner signature binds all of these.
3. **Transaction/API attempt:** KeeperHub execution key, execution ID, transaction hashes, sender nonces and replacement lineage. These are evidence about attempts, not interchangeable business identities.

P01 must establish a stable native decision identifier or persist a generated ID once at the native decision boundary. Restarts must reopen that decision rather than manufacture a new ID. One decision may contain declared indexed actions; indices and canonicalization are versioned.

The journal refuses payload rebinding from the first durable operation creation. The controller records successful operation consumption and its payload hash under the mandate lineage; it cannot retain a failed transaction’s provisional binding after EVM rollback. A consumed ID rejects another execution; a mismatched payload under an already bound ID is an identity conflict. A reverted transaction consumes no successful ID, counters or token allowance. A fresh ID may represent a new permitted operation; no semantic-deduplication guarantee is made against a runner deliberately inventing new work.

Across handover:
- Already executed: recover the existing result; never re-execute.
- Definitely not executed and still desired: explicitly reauthorize the **same ID and payload** under the new epoch after reconciliation.
- Outcome unknown: remain blocked.
- Changed economic payload: cancel the old proposal only after proving it cannot execute, then create a separately reviewed new decision. Do not disguise a retry as new work.

Persist the outbox before network I/O. Store intent/config/compiler version, envelope hash, operation ID, policy/epoch, signer reference, KeeperHub IDs, hashes, finality and result-delivery state. Secrets are references only.

An at-least-once result delivery channel with idempotent consumer acknowledgement is the engineering contract. Claim one logical Almanak result only after the native callback/state-machine boundary is shown to tolerate duplicate delivery and crash recovery. A local “delivered” bit by itself does not solve the crash between callback and acknowledgement.

KeeperHub's documented 24-hour replay window is an additional control. Past the window, query chain consumption and original attempts; never blindly resend. If an operation has not executed, preserve the same ID on any authorized resubmission. Account transaction nonces may change across legitimate attempts; the invariant is no fresh business ID for an uncertain retry.

## 5. Exact operating terms and atomic execution

All values use unsigned integer token base units, counts or chain seconds. No float arithmetic, guessed defaults or unlimited sentinel. The owner approves coherent finite values.

Terms: cumulative supply limit Ls; normal/restoration withdrawal limits Ln/Lr; successful normal/restoration count limits Nn/Nr; per-action maxima Ms/Mn/Mr; normal minima ms/mn; normal/restoration cooldowns dn/dr; liquid cash floor F; supply-trigger surplus H. Zero capacity explicitly disables an action lane. F and H may be zero.

Let B be the Safe's token balance immediately before the protected call:

- SUPPLY: B >= F + H; ms <= amount <= Ms; amount <= B - F; supply Used + amount <= Ls; normal count and cooldown available.
- NORMAL WITHDRAW: B >= F; mn <= amount <= Mn; normal withdrawal Used + amount <= Ln; normal count and cooldown available.
- RESTORATION WITHDRAW: B < F; 0 < amount <= Mr; amount <= F - B; restoration Used + amount <= Lr; restoration count/cooldown available. No normal minimum or normal-capacity requirement. The controller derives this lane from B; the runner cannot choose it to evade limits.
- HOLD: no executable economic call, consumed operation or transaction claim.

Counts/cooldowns are distinct: SUPPLY and NORMAL WITHDRAW share the normal count and initialized timestamp; restoration uses its own. Counters update only after successful atomic execution. Changing runner, epoch or terms preserves consumption and timestamps. Withdrawals, donations, interest and retries never refill cumulative supply capacity. Reducing a ceiling below consumed use is rejected; stopping remains available.

Native Roles quotas are defense in depth. The controller's Used/count/timestamp state supports typed lifetime terms and state-dependent classification. These are multiple states that must agree:
- Native allowance keys remain stable across replacements.
- At activation, each Roles remaining allowance must equal its configured cumulative ceiling minus corresponding successful consumption.
- Supply/withdraw amount quotas consume on the economic protocol call, not again on its token approval/cleanup.
- Shared native count allowance is used only on relevant normal economic calls; restoration is separate.
- Any mismatch blocks activation or the relevant operation. Owner policy updates and Roles changes are atomic with expected-consumption checks.

Atomic operation sequence:
1. Verify domain, active epoch, configured executor and runner signature, identity, canonical shape, policy version and state predicates. Prevent reentrancy.
2. Require managed Safe-to-Morpho token allowance zero at entry.
3. Execute only the declared approval if needed, unchanged native economic call, and approval cleanup through Roles/Safe within the outer transaction.
4. Check every nested return status and token behavior, then read exact effects.
5. Supply must show the permitted Safe debit, retained cash floor and compatible positive share increase. Withdrawal must show permitted Safe receipt and compatible share decrease. Pin Morpho rounding semantics and admitted token behavior in P01/P02; do not infer successful effects from the outer receipt alone.
6. Borrow remains zero; collateral unchanged; managed allowance ends at zero. Failure reverts the whole protected call.
7. Persist successful operation consumption and typed counters atomically; emit enough indexed evidence to reconstruct them.

Gas and transaction nonces do not roll back. An entry approval from a previous actor cannot be erased by a reverted call; cleanup must happen before activation, not inside a transaction destined to revert. USDC-unit limits are not guaranteed dollar values or insurance against protocol loss/depeg/illiquidity.

## 6. Installation, inventory and owner-controlled handover

### Inventory boundary

At one stated finalized block/hash, report separately:
- Safe ownership/threshold and supported implementation; enabled modules, guard, fallback and recognized delegated paths.
- Roles implementation, role members, target/argument conditions and allowance state.
- Morpho grants recovered from canonical authorization history plus known identities, confirmed through mapping readback.
- Relevant token approvals and supported Permit2/delegated spend paths.
- Runner/executor identities and privately attested credential/admin control, explicitly distinguished from public-chain facts.

First protected profile: no active external Morpho delegates within the complete inspected deployment inventory. Morpho grants are global across markets within that deployment. A Safe calling for itself does not need an external delegate. Unknown/unrecognized relevant paths, missing required history, or an incompatible legitimate sibling workflow prevent protected activation.

A report is COMPLETE only within its declared discovery, implementation and reachability assumptions. Public chain data cannot prove private-key ownership or unavailable credentials. Never claim every future way funds can move is known. Later owner grants or module changes can invalidate protection; detection occurs on the observation/finality schedule and is not instantaneous revocation.

### Initial activation

Deploy/configure the controller in a paused, never-active state. Establish owner control, dedicated operation keys, exact Roles configuration, zero relevant unmanaged approvals/grants, pinned native integration configuration and a complete supported inventory. There are no inherited in-flight operations for a new lineage. Existing protocol shares can be acknowledged by the owner but historical spending is not silently treated as Held spending.

Prepare an owner Safe batch that establishes the reviewed Roles allowances and activates epoch 1 with exact expected controller usage/configuration and the reviewed inventory commitment. A commitment identifies the report; it does not make historical completeness an on-chain proof. The activation function checks every supported on-chain predicate it can verify. Unsupported required evidence prevents preparing a READY proposal.

For the early P03 integration proof, use a dedicated owner-controlled fixture Safe with available history. P00 defines the complete bounded bootstrap checklist; P03 records its actual finalized-block evidence and independently checks it before activation. Manual collection is permitted at this stage; missing evidence is not. P04 automates and generalizes that same inventory workflow. A P03 receipt does not claim the P04 automated product already exists.

### Migration from a native installation

A newly deployed paused controller does not fence Runner A’s pre-existing native Role or Morpho access. First use owner authority to remove or otherwise conclusively fence the old native operating paths, then reconcile their pending transactions and inventory. Do not advertise “old runner stopped” merely because the new Held controller is paused.

V4 does not automatically import historic native spend into verified Held counters. A new lineage starts a clearly labeled new mandate budget; prior activity is reported separately. If the customer requires one cap spanning pre-Held and Held operation, migration remains unsupported until a separately reviewed, evidence-backed import contract is specified. The ordinary comparison fixture gives each branch the same starting successful use; Held use comes from its own verified pre-change history, not an invented counter.

### Replacement / changed terms

1. **Fence:** owner pauses the current epoch on-chain. This invalidates its operating authorization; an adapter flag alone does not. Wait for the configured finality evidence.
2. **Reconcile:** process all old in-flight operation IDs and final counters against the fence. A call included before the fence is counted; one ordered after it must fail. Reorg/unknown evidence keeps the handover pending.
3. **Prepare:** pin candidate terms, Runner B key, native configuration digest, counter snapshot, Roles remaining values and required owner cleanup. Preserve old records. Neither runner can act while paused.
4. **Cleanup and inventory:** perform only owner-approved relevant revocations while paused; wait/read back as needed. Never revoke an unrelated agent's permission merely to get green. Missing inputs, conflicting use or history produce specific INCOMPLETE sections. The report commits its candidate set, source block, code assumptions and discovery range; the activation checks the supplied candidates and current supported configuration, without pretending this verifies discovery completeness on-chain.
5. **Activate:** after reconciliation and complete supported inventory, owner authorizes the candidate. A Safe batch updates remaining native allowances and activates a fresh epoch with expected-used/state/config guards. Stale preparation or guard failure reverts the batch; the controller stays paused.
6. **Read back:** verify inclusion, policy, epoch, runner, Roles state and supported authority. Display ACTIVE only on valid evidence. If a later observation becomes incomplete, stop new adapter dispatch and explain whether the contract is still active; owner fencing is a separate confirmed action. Never display “on-chain paused” merely because the UI stopped.
7. **Continue:** Runner B obtains the exported native inputs/checkpoints, resolves old results idempotently, and produces the next supported action or HOLD. Runner A cannot reuse old signed envelopes.

Owner operations may require multiple transactions and approval ceremonies, including cleanup and final activation. This is deliberate two-stage control around unresolved work, not a signature-saving claim. Compare the same safety outcome with a competent native baseline.

The controller's pause/epoch prevents delegated activation without the owner transition. It does not itself revoke an external Morpho grant. A malicious owner can deliberately bypass the preparation tool; owner misconduct and future owner-granted bypasses are outside delegated-runner guarantees.

## 7. What changes from V3

| V3 feature/promise | V4 decision and reason |
|---|---|
| Owner custody, exact native actions, typed finite terms and same-transaction effects | Retain. They protect the supported ordinary execution job. |
| Controller-only Roles access, durable operation consumption, epoch retirement | Retain. They make authorization and handover enforceable across services. |
| Verifier-issued renewable leases / service-observation attestations | Remove from this product. V4's job is owner-controlled operation/change/recovery, not automatic service-health renewal. |
| Automatic stop merely because owner/operator becomes quiet | Not promised. Without an owner fence, authorization remains subject to current terms and finite capacity; there is no observation-based expiry. |
| Paid operator retainer, wage Safe and Superfluid closeout | Remove. V4 is owner-operated software with no compensation service. Do not claim full V3 paid-mode coverage. |
| x402 paid reports, marketplace and broad MCP analysis API | Remove from core. No surface added merely for sponsor count. |
| Universal migration to another controller or arbitrary account/strategy | Unsupported. A new controller is a reviewed new installation; consumption does not magically migrate. |
| One-signature/one-state/unique-vulnerability claims | Remove. None is part of the product promise. |

There is no ban on Solidity or preference for complexity. Existing components are used where they meet the promise. Restoring removed guarantees requires a versioned change and updated tests.

## 8. Usability, privacy and operations

Four user views:
1. **Terms:** market, supported actions, current ceilings, Used/Remaining, floor and precise changes.
2. **Activity:** action/HOLD/refusal/unknown, original operation, KeeperHub attempt, transaction and effect evidence.
3. **Change & handover:** fence status, unresolved work, owner cleanup, candidate terms, activation and missing inputs.
4. **Authority & export:** scope/block/finality, complete/incomplete sections, credential references, offline recovery package.

Put ABI details and debug traces behind diagnostics. A truthful INCOMPLETE section is not a badge to manufacture. Relevant missing evidence blocks the affected flow; unrelated limitations are labeled without pretending every operation must stop.

Lock the first product as a single-organization, self-hosted operator console with a private local database. Do not advertise multi-tenant SaaS. Owner approvals occur through the customer's Safe tooling, not private keys in Held.
- Bind every authenticated request and exported artifact to the configured organization, Safe and lineage. No anonymous private-state endpoint.
- Keep KeeperHub and runner credentials in existing secret storage or environment references; never logs, browser bundles, git, fixtures or recovery exports.
- Private reports by default. Publish only explicit demo data/redacted evidence.
- Define retention and deletion of local private records; preserve the necessary operation tombstone/recovery index for as long as its replay/history guarantee is advertised. Public chain records are not deletable.
- Support has no default access. Diagnostic export is explicit, redacted and inspectable.
- Test cross-Safe/lineage access, secret leakage, owner-action authorization, path traversal and exported credential references.

Operational spend is separate from capital limits. Configure finite attempts, backoff, timeouts and operator-visible unresolved states. Inventory the actual payer and provider billing. Do not claim a hard gas/API-spend ceiling unless the chosen funding/provider boundary enforces it. Missing keys/funding does not justify changing provider, custody, or billing routes.

## 9. Fair advantage test

**Illustrative fixture, not a real customer's balances:** cumulative supply ceiling 50,000 USDC; 30,000 successfully used; owner raises ceiling to 80,000 and replaces A with B. New remaining supply capacity is 50,000 USDC. Baseline historical use must be reconstructible and given the same starting evidence.

Compare:
- Native Almanak + KeeperHub recovery + correctly configured Roles + Safe batching + competent inventory/runbook/scripts.
- Held on the same starting state, supported authority boundary, chain conditions and requested outcome.

Measure separately:
1. Approval ceremonies, individual owner signatures and submitted transactions.
2. Human tools/screens/commands and manually correlated fields. Count the underlying stores separately; never call them one.
3. Correct outcomes and recovery effort at identical meaningful interruption points.
4. Supported authority left over and the specificity of any unresolved evidence.
5. Replay behavior for a stable operation ID within and beyond API cache expiry.
6. Installation/maintenance burden added by each path.

Predeclare scenarios before recording Held's outcome: ordinary change, ambiguous old submission, stale Used snapshot, changed policy, missing archive data, known legacy grant migration, failed cleanup, new-key activation and delayed callback acknowledgement. Give both paths the same actor knowledge. Do not deliberately forget a native revocation and call the result representative.

Freeze the protocol and measures before either measured run. Execute the native half in P00 on a realistic labeled local fork with native tools, before Held implementation. Record raw steps, results and environment; the existing design is already known, so this is not a blinded study. Review any weak or absent remaining advantage before P01. P06 verifies comparability and measures Held. Preserve the original native record, but permit necessary native reproduction or corrections with a versioned reason and equivalent conditions for both paths. Never compare obsolete or mistaken baseline numbers merely because they were frozen first.

Native on-chain updates batched into one reverting Safe transaction get their atomicity credit. Native recovery may be just as correct; record that result. Separate safety behavior, operator work and new contract trust. A demonstration supports the exact tested comparison, not universal superiority or real customer demand.

Accept a material improvement claim only when the observed workflow removes meaningful operator coordination or improves truthful recovery at the same claimed safety boundary, with added setup/trust cost disclosed. A tie, mixed result or failed thesis is an admissible result, not a reason to invent another metric. No required interview count, time-saving percentage or 25+ score is manufactured.

## 10. Proof, testing and competition deliverables

Each claim must have a test/reproduction, exact source revision, environment label, expected and observed outcome, and an independent readback/check where appropriate.

Required coverage:
- Valid native supply, same-Safe withdrawal and HOLD.
- Wrong target/account/recipient/market/action/callback/amount; trailing bytes; approval variants; unsupported wrapper.
- All quota/count/cooldown/floor boundaries, exhaustion and owner increases; normal/restoration separation.
- Failed nested calls/token behavior/postconditions roll back successful consumption and cleanup effects.
- Identical ID retry, same ID/different payload, domain replay, old epoch, same-KeeperHub-sender/different-runner keys, concurrent attempts.
- Crashes before durable write, before send, after server acceptance, after broadcast, after chain success, and around result delivery/acknowledgement.
- Beyond-cache retries, replacement transactions, receipt-not-yet-visible, reorg/finality disagreement and lost local state.
- Fence ordering, stale activation snapshot, unavailable history, unresolved external grant, failed revocation and missing replacement inputs.
- Correct client/chain status disagreement reporting; no UI-only pause represented as on-chain fence.
- Privacy, access control, redaction and unassisted developer setup.

A finite suite is not an audit or guarantee of zero defects. Run meaningful unit/property/fork tests and the actual composed integration; passing mocks alone does not establish hosted behavior. Test permissions and replay at the layer that enforces them.

### Judged surfaces

| Official criterion | Submission evidence |
|---|---|
| Integration depth | Native intent/compiler trace, actual adapter boundary and native outcome return |
| Execution through KeeperHub | Supported economic action, execution record, public transaction link and verified inner effects |
| Reliability/observability | Honest interruption/recovery, mutation refusal, fence/activation and scoped INCOMPLETE behavior |
| Usefulness/originality | Fair before/after operator task with observed coordination benefit and disclosed tradeoffs |
| Developer experience/code quality | Independent setup, clear configuration, reusable adapter, relevant tests and readable implementation |

Prepare source repository, short working demo video, transaction link, exact surfaces used, network, candid unfinished parts and reachable contact. Up to ten finalists present working builds and answer questions. No fixed demo duration or official numeric weights were supplied. Bounty requirements remain separate and partly unanswered; core V4 does not depend on a bounty entry.

### Live story

Begin with the customer's ordinary task and an admitted native action. Show current Used/Remaining. Introduce a genuine pending/ambiguous operation, fence and reconcile it, review the owner change, complete supported revocation checks, activate B and continue with preserved use. Show one meaningful mutation refusal. A missing-history case remains INCOMPLETE and blocks activation; restore evidence before continuing. Show a legacy Morpho grant only as a labeled migration/drift fixture. End with independently inspectable proof. Never claim the client stopped an EVM transaction halfway through.

## 11. Implementation phases and decisions

| Phase | Outcome | Depends on |
|---|---|---|
| P00 | Pinned route evidence, preregistered comparison and measured native baseline | This plan |
| P01 | Versioned types, stable identity, journal and native result contract | P00 |
| P02 | Controller + Roles execution and activation invariants on realistic fork | P01 |
| P03 | Actual native Almanak → KeeperHub → controller/Role/Safe/Morpho → native result | P02 |
| P04 | Supported authority inventory, owner fencing, change and handover | P03 |
| P05 | Usable private operator console, configuration and recovery export | P04 |
| P06 | Adversarial composed verification and fair native comparison | P05 |
| P07 | Independent developer installation, release and evidence audit | P06 |
| P08 | Submission pack and rehearsed live demonstration | P07 |

Phases are acceptance-based, not days. Do not skip unresolved dependencies by creating a generic demo. Specific addresses, chain deployment, signer route and compiler seam are discovery outputs of P00, not silent placeholders or permission to choose a weaker route.

### How to handle a blocked phase

P00 establishes configuration feasibility and native baseline evidence; only P03 can establish the implemented public execution route. A documentation or catalog check is not an end-to-end route pass. Classify each required layer as supported, verified, disproved or blocked-unknown, with the exact missing evidence and next action.

P03 supplies mandatory integrated transaction evidence. P02 and P04 remain necessary for Held's enforcement and handover promises. P06 demonstrates reliability through composed faults, while P07 demonstrates developer reuse; those qualities are built throughout earlier phases. P08 must assemble and verify the required source, working video and transaction links before the entry is ready to submit; a P03 receipt alone is insufficient. These are dependencies and proof responsibilities, not exclusive criterion ownership or numeric weights.

P05 remains a usable private console in this plan. If a concrete platform blocker motivates a CLI interface, raise a versioned product decision preserving the four operator jobs, understandable owner approval, authentication/privacy, recovery export and independently tested usability. A command-line interface is not automatically equally usable and does not waive P05 outcomes. No deadline or build-speed cut is authorized. Complete independent work and surface a bounded decision when a dependency is blocked; do not silently skip it or start unrelated features.

Execute a phase only when asked. This document authorizes planning; it does not authorize transactions, public deployments, spending, outreach or publication. Prepare a concrete action manifest and use existing specific authorization, or obtain it as the final step after all preparatory work. Local reversible implementation and tests are the default scope of a subsequently invoked phase.

## 12. Source register and limits

- [Supplied official corpus and authority labels](../work/competition-brief-2026-09-15-supplied-page.md).
- [V3](04_Held_Locked_V3.md) and [technical/narrative corrections](06_Held_V3_New_Feedback_Review.md): historical context, not competing authority for removed V4 features.
- [Almanak execution API](https://sdk.docs.almanak.co/api/execution.html); [pinned runner reconciliation](https://github.com/almanak-co/sdk/blob/6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938/almanak/framework/runner/strategy_runner.py#L9228).
- [Roles allowances](https://docs.roles.gnosisguild.org/general/allowances), [conditions](https://docs.roles.gnosisguild.org/general/conditions).
- [KeeperHub direct execution](https://docs.keeperhub.com/api/direct-execution), [Safe ownership and routing](https://docs.keeperhub.com/wallet-management/safe).
- [KeeperHub chain catalog contract](https://docs.keeperhub.com/api/chains), [Morpho plugin scope](https://docs.keeperhub.com/plugins/morpho), [official Morpho deployment registry](https://docs.morpho.org/developers/contracts/addresses/); dated retrieval evidence in work/held-v4-amendment/sources/.
- [Pinned Morpho implementation](https://github.com/morpho-org/morpho-blue/blob/8e26ca6a8dbc5089edcd67fb576248810fd2870a/src/Morpho.sol).

Public technical documentation was reread on 15 September 2026; exact deployment behavior is still to be established. The user supplied official page/tab text after browser refresh failures. No full current competitor field, judge weights, live Held execution, benchmark result, customer preference or winning probability is established by this plan.
