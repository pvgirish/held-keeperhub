# Phase dependencies and blocked-phase handling

Written in P00 per the A1 amendment. This is a triage order for a blocked dependency. It is not permission to skip a phase that is merely difficult, and no item here is a deadline-driven cut.

## Proof responsibilities

| Phase | What it is responsible for proving | If blocked |
|---|---|---|
| P00 | Route feasibility by evidence layer; the measured native baseline | Blocks dependent P01 architecture. Does not block the event. |
| P01 | Operation identity, journal, native result contract | Blocks P02. |
| P02 | Controller and Roles enforcement on a realistic fork | Blocks P03. Required for every enforcement claim. |
| **P03** | **The mandatory composed transaction evidence.** Criterion 2 needs a link to a transaction executed through KeeperHub, and an incomplete submission cannot be judged. | **Escalate immediately.** Without P03 there is no submission. |
| P04 | Authority inventory, owner fencing, change and handover | Required for every handover claim. |
| P05 | The private operator console | See below. |
| P06 | Composed adversarial faults; the Held half of the comparison | Reliability evidence. |
| P07 | Independent developer install and release evidence | Developer-reuse evidence. |
| P08 | Assembles and verifies source + video + transaction links | A P03 receipt alone does NOT make the entry ready to submit. |

Reliability and developer reuse are built throughout the earlier phases. P06 and P07 demonstrate them; they do not own a criterion exclusively, and there are no numeric weights.

## P05 is not an automatic cut

P05 remains the private console. A CLI is not automatically equivalent. Replacing it requires a versioned product amendment that preserves all four operator jobs, understandable owner approval, authentication and privacy, recovery export, and independently tested usability. Build difficulty and the calendar are not reasons.

## Blocked-dependency rule

A blocked dependency triggers a bounded decision plus all independent preparation that remains possible. Never a silent stall, never an automatic skip, never a generic demo substituted for the real artifact.
