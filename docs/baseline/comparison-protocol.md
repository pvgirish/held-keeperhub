# Comparison protocol — FROZEN before either measured run

Frozen in P00, before any Held code exists and before any measurement. P06 may reproduce or correct the native half under a recorded versioned reason; it may not quietly rescore it.

## The operation

Cumulative supply ceiling 50,000 USDC, of which 30,000 is successfully used. The owner raises the ceiling to 80,000 and replaces operator A with operator B. Correct remaining supply capacity afterwards is **50,000 USDC**.

Illustrative fixture amounts. Not any real customer's balances.

## The two paths, given equal footing

**Native.** Almanak + KeeperHub recovery + correctly configured Zodiac Roles + Safe batching + a competent operator with a runbook, scripts, allowance/event history access and an authority checklist. Native batching and native reconciliation get full credit. Deliberately forgetting a native revocation invalidates the run.

**Held.** Same starting state, same authority boundary, same chain conditions, same requested outcome, same actor knowledge.

## Measures — recorded separately, never merged

1. Owner **approval ceremonies**, **individual signatures**, and **submitted transactions**. Three different numbers. A 2-of-3 Safe is not a one-signature account.
2. Human tools, screens and commands touched; fields correlated by hand. Underlying state stores counted separately — they stay six either way.
3. Correct outcomes and recovery effort at each predeclared interruption point.
4. Supported authority left over, and how specific any unresolved evidence is.
5. Replay behaviour for a stable operation ID, inside and beyond the 24-hour API cache.
6. Installation and maintenance burden each path adds, including new contract trust.

## Predeclared interruption points

Declared now so neither path can be handed a friendlier set later. Each carries a **stable id**; `native-measurements.json` must report all nine, each exactly once, under these exact ids. Meaning is fixed with the id.

| id | condition |
|---|---|
| `I1-clean` | Ordinary change, no interruption. |
| `I2-ambiguous-submission` | A prior submission broadcast but unconfirmed at fence time. |
| `I3-stale-used-snapshot` | A stale Used snapshot at preparation time. |
| `I4-policy-changed-midway` | Policy changed between preparation and activation. |
| `I5-missing-archive-data` | Archive data missing for part of the history. |
| `I6-legacy-grant-migration` | A known legacy Morpho grant — labelled migration fixture, not the protected baseline. |
| `I7-failed-cleanup` | A cleanup transaction fails. |
| `I8-new-key-activation` | New-key activation with the old key still holding credentials. |
| `I9-delayed-callback-ack` | Delayed callback acknowledgement. |

A recovery effort of **0 is a valid recorded result**, not a missing field.

## Admissible outcomes

A tie, a mixed result, or Held being worse on a measure are all admissible and get recorded as found. If the native path already meets the outcome with no material unresolved benefit left, that is a product decision to take **before P01**.

No target improvement percentage. No required interview count. No score.
