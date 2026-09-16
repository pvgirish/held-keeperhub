# The authoritative plan corpus

**This directory is the source of truth for requirements. Do not derive a requirement from
the implementation when it is written here.**

That mistake has already been made once and cost real work: P05's four operator views are
specified in `14_Held_Locked_V4.md` §8 as **Terms · Activity · Change & handover ·
Authority & export**, and they were instead *derived* from the product sentence as
"J1–J4" because this corpus was not in the repository. The derivation was close enough to
look reasonable and wrong enough to build the wrong surface. Restoring these files here is
the fix.

## Contents and provenance

Restored verbatim from `Held_abc0fdd_Review_and_Authoritative_Plan.zip`, supplied
2026-09-16. Every file was verified against the packet's own `SHA256SUMS.json` after
copying; all 13 matched.

| File | What it governs |
|---|---|
| `14_Held_Locked_V4.md` | The locked product, including amendment A1. §2 supported profile, §4 identity/journal, §5 operating terms, §6 handover, §8 the four operator views, §9 the comparison. |
| `15_Held_V4_Phases_and_Prompts.md` | The phase map P00–P08. |
| `Continuous_Execution_Directive.md` | EXEC-01: continuous execution, review-timing deferral, and the stopping rule. |
| `held-v4-prompts/00_COMMON.md` | The common contract every phase applies. |
| `held-v4-prompts/P00..P08_*.md` | The original per-phase prompts, including owned paths, required work, required artifacts and acceptance conditions. |
| `SHA256SUMS.json` | The recorded digests. `make check-plan-digests` re-verifies them. |
| `REVIEW-abc0fdd.md` | The source review of commit `abc0fdd` that reopened P03 and reclassified P04/P05. |

## Two things these files are NOT

**Not an implementation snapshot.** The packet is planning and review material. It must
never be used to overwrite or roll back the live worktree, which is at `abc0fdd` or later.

**Not superseded by the phase prompts' own routing.** The original prompts name a
coordinator dispatching to GLM-5.3. That routing is historical. Claude is the sole
implementation writer; the human reviewer is the independent reviewer. Everything else in
the prompts — owned paths, required work, artifacts, acceptance — stands.

## Checkpoint pointers

- Reviewed commit: `abc0fdd3e832538900045961574ccb2887734e07` ("P05: the private operator
  console"). This is the **reviewed checkpoint, not a reset target**. Preserve all commits
  at or after it.
- Repository: `pvgirish/held-keeperhub`, private.
- Live phase state: `evidence/continuous-run.md` and each `evidence/P0*/acceptance.json`.

## Phase status after the abc0fdd review

The review rejected "P03 local complete, P04/P05 complete". The corrected reading:

| Phase | Status |
|---|---|
| P00, P01 | Locally verified. Not reopened. |
| P02 | Enforcement and accounting evidence preserved; independent acceptance pending. |
| P03 | **Partial, with local defects C1–C4.** Not blocked solely by L10. |
| P04 | Useful fork contract tests. The required runtime inventory / handover **service** does not exist. **Partial preparation.** |
| P05 | Useful private-console prototype. Not connected to real service state, and the four §8 views are not implemented as specified. **Partial preparation.** |
| P06 | Not startable: a comparison of an incomplete workflow would not measure the product. |

`accepted=false` records that independent review has not happened. It does **not** waive a
missing substantive prerequisite, and a phase with unmet prerequisites is not "complete
pending review".
