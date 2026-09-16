# Advantage review — the V4 §9 decision before P01

Date: 2026-09-16. Author: Claude, sole implementation writer. **Not independently reviewed.**

**Revision 2.** Revision 1 deferred testing the simple native remedies to P06. That was wrong
and is withdrawn. V4 §9 requires the comparator to be a *competent* native workflow — *"Do not
deliberately forget a native revocation and call the result representative"* — and A1 puts this
review **before P01**. The competent-native controls have now been run. Revision 1's conclusion
does not survive them intact. The original nine-case traces are preserved unchanged.

## What the corrected comparison establishes

The nine cases in `native-measurements.json` ran **one** native procedure: a single batched
owner change. Two of its outcomes failed the customer objective. The controls in
`I2-competent-control.json` and `I6-competent-control.json` then ran the **competent** native
workflow for those two, on the same fork, from the same canonical state.

| | naive procedure (04) | competent workflow (05) |
|---|---|---|
| **I2** ambiguous in-flight submission | workflow **NOT ACHIEVED** — 5,000 of consumption silently regranted; repaired only by a second corrective ceremony. 2 ceremonies / 4 sigs / 3 txs. | workflow **ACHIEVED first time**. Fence as its own ceremony, let it settle, read the allowance actually consumed, derive the new ceiling from that, activate B. 2 ceremonies / 4 sigs / 2 txs. |
| **I6** known legacy Morpho grant | workflow **NOT ACHIEVED** — grant survived the handover as live independent authority. | workflow **ACHIEVED at zero extra cost**. Inventory detects the grant; `setAuthorization(legacy,false)` goes into the *same* MultiSend as the ceiling change and the role swap. 1 ceremony / 2 sigs / 1 tx. |

Both controls are behavioural, not asserted. In I6 the legacy agent provably moved the Safe's
Morpho position before revocation (shares fell) and provably cannot afterwards
(`execution reverted: unauthorized`). In I2 the in-flight supply genuinely landed before the
fence, and the reconciled arithmetic followed what actually executed: used 35,000 → new
remaining 45,000, not a forced 50,000.

## What this does to the Revision 1 thesis

Revision 1 rested on two claims. The controls dispose of one and reshape the other.

**I6 does not survive at all.** Morpho's `setAuthorization` is an ordinary Safe-originated
call, so revoking it costs a competent operator nothing — no extra ceremony, signature or
transaction. The declared scenario is a *known* grant. An operator who knows about it closes it
for free. The 04 trace is retained as an **omission control**: it shows the cost of forgetting,
not a native incapability. Any claim that Held is needed to surface a legacy grant is withdrawn.

**I2 survives only in a much weaker form.** The competent native workflow gets the arithmetic
right. What it costs is atomicity: the change *cannot* be one ceremony, because the correct
ceiling is unknowable until the fence has settled. Native therefore pays two ceremonies — and
so does Held, because V4 §6 prescribes the same fence → reconcile → prepare → activate order.
**There is no ceremony or signature saving available here, and none is claimed.**

What remains is narrower and honest: native `setAllowance` accepts *any* absolute value. Nothing
in the native stack refuses a write that implies un-consuming already-consumed capacity. The
competent workflow avoids that by operator discipline — reading the reconciled figure first.
Correctness depends entirely on the runbook being followed; a naive or hurried operator commits
a silently wrong ceiling and never learns, which is exactly what the 04 I2 trace records.

## The decision

**Provisional continuation to P01, on a materially narrowed hypothesis, with the weakened
basis stated plainly.**

The surviving hypothesis is the activation-time consistency guard that V4 §5 *already*
specifies: *"At activation, each Roles remaining allowance must equal its configured cumulative
ceiling minus corresponding successful consumption... Any mismatch blocks activation."* The
baseline shows the failure mode that guard exists to catch is real and silent. Nothing new is
being invented, and V4 is not being narrowed to it — the journal, result contract, scoped
authority workflow and console remain in scope unchanged.

This is deliberately not stated as "native cannot do this." Native can, and did. The claim is
the weaker one that a guard which *refuses* an inconsistent activation is worth more than a
runbook line that *asks* an operator to check — and that claim is **unproven**, which is the
honest status at P00.

### What this decision does NOT license

- No ceremony, signature or transaction saving. The competent native clean change is
  1 / 2 / 1, and the interrupted change is 2 / 4 / 2. Held must match or beat those or record
  that it did not.
- No claim that Held uniquely finds or fixes legacy grants. Withdrawn outright.
- No reframing of the benchmark. The protocol is frozen and its digest is bound into
  `native-measurements.json`.
- No waiver of the added cost V4 §9 measure 6 requires disclosing: a new contract to trust,
  audit, deploy and maintain.

### What would reject it in P06

- Held needs more owner ceremonies or signatures than the competent native workflow.
- Held's own counters can be desynchronised by the same in-flight interleaving as I2, making
  the guard nominal.
- The guard turns out to be expressible as a native pre-activation check — for instance a
  script that refuses to sign a `setAllowance` whose implied consumption is below the observed
  figure. If a check outside the trust boundary buys what a controller inside it buys, the
  controller is not worth its cost, and §9 requires recording that.

That third falsifier is the sharpest one and it is now specific enough to test directly.

## Honest limits of this review

The controls exercise **contract-level** behaviour: Safe, Zodiac Roles, MultiSendCallOnly,
Morpho Blue and USDC on a pinned fork, driven by anvil/cast. They do **not** exercise Almanak
reconfiguration, the native recovery machinery, or native result consumption. The operator-work
counts are counts of contract-level operator actions, not a human-factors study. I9's hosted
callback half remains unmeasured under L10. A fuller native-workflow comparison across those
boundaries would change the coordination numbers in either direction, and is not claimed here.
