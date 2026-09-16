# Negative tests for the P00 gates

Run them with `probes/checks/run_negative_tests.sh`. It builds a **temporary workspace**,
runs the fakes there, and deletes it.

**It never writes to `docs/baseline/` in the real tree.** An earlier version of this file
told the reader to copy a fake into `docs/baseline/native-measurements.json`. That was wrong:
it recreates the contamination the quarantine exists to prevent, and would overwrite a real
result. Do not do it.

## What the fakes prove

`REJECTED-fake-measurements.json` is a plausible-looking record — correct keys, correct
types, nine rows, `protocol_frozen_before_run: true`. Kept as an artefact only.

Findings from the 2026-09-15 review, all since fixed:

| Fake input | Old gate | Now |
|---|---|---|
| Nine `NOT-PREDECLARED-*` ids unrelated to the frozen protocol | PASS | rejected — the nine declared ids are required, each exactly once |
| A **directory** as every evidence path | PASS | rejected — `isfile` plus a 64-byte floor |
| Empty `environment` / `pinned_revisions` objects | PASS | rejected — chain id, block number, block hash, foundry version, SDK rev all validated |
| `recovery_effort: 0` | wrongly **rejected** | accepted — zero is a valid result |
| A compiled call targeting the **correct** Morpho address | wrongly **rejected** | accepted |

That last row was the worst of them: the gate stringified the whole registry dict and
searched for it inside a 42-character address, so it could never match. A real successful
compilation would have failed the gate.

Schema validity is necessary and never sufficient. These gates make a careless or
fabricated record fail loudly. They cannot prove a baseline was run.
