# Held V4 — phases and copy-ready prompts

Read [the locked plan](14_Held_Locked_V4.md) first. This pack covers the entire implementation, verification, developer release and submission preparation. None of the product phases has been executed by creating this pack.

Includes sequencing amendment A1: P00 verifies layered route evidence and runs the native baseline before P01; P06 checks comparability and permits justified versioned reruns. See [review and source findings](16_P00_Amendments_and_Explainer_Review.md). P05 remains the console; an alternative interface requires an explicit product amendment preserving its outcomes.

## How to use

1. Open a phase file and paste its coordinator prompt into the Astra thread.
2. Astra reads the common contract and the locked plan, then dispatches a bounded GLM executor packet.
3. Finish and independently accept that phase before invoking its dependent phase. No calendar target changes scope.
4. Do not paste a bare ROLE=EXECUTOR packet into the coordinator thread as a role change.
5. The phase contract prepares external actions for final authorization; it does not grant permission to spend, deploy or publish merely because a phase file exists.

Common contract: [00_COMMON.md](held-v4-prompts/00_COMMON.md).
Product workspace when implementation begins: /Users/girish/Documents/Codex/2026-09-15/ha/held.

## Phase map

| Phase | Outcome | GLM effort | Dependency |
|---|---|---|---|
| [P00](held-v4-prompts/P00_baseline-and-configuration.md) | Verify the route and measure the native baseline | High | Plan |
| [P01](held-v4-prompts/P01_identity-and-journal.md) | Freeze types, operation identity and durable recovery records | Max | P00 |
| [P02](held-v4-prompts/P02_controller-and-roles.md) | Implement the typed controller and native Roles enforcement | Max | P01 |
| [P03](held-v4-prompts/P03_native-keeperhub-execution.md) | Connect native Almanak execution through KeeperHub | Max | P02 |
| [P04](held-v4-prompts/P04_authority-and-handover.md) | Implement bounded authority inventory and owner-controlled handover | Max | P03 |
| [P05](held-v4-prompts/P05_operator-product-and-privacy.md) | Deliver the usable private operator product | High | P04 |
| [P06](held-v4-prompts/P06_adversarial-and-advantage-tests.md) | Run adversarial integration tests and the fair advantage comparison | Max | P05 |
| [P07](held-v4-prompts/P07_independent-install-and-release.md) | Verify independent developer use and release evidence | High | P06 |
| [P08](held-v4-prompts/P08_submission-and-live-demo.md) | Prepare the submission and working-build presentation | High | P07 |

## What completion means

P00 establishes configuration feasibility and measures the native baseline. P01–P05 produce the product in coherent layers. P06 establishes composed correctness, checks baseline comparability and measures the claimed advantage. P07 establishes developer reuse and release evidence. P08 prepares the actual submission and live demonstration; publication is a distinct authorized action.

A complete plan is not a complete build. A passed technical comparison is not customer demand. A high-quality build is not a guaranteed prize. The official criteria and the user's private product-quality threshold remain separate.

## Handoff boundaries

- Missing supported configuration blocks dependent architecture rather than triggering a generic transfer workaround.
- Missing public-action authorization blocks that action while local work can continue.
- A materially failed advantage comparison requires a product decision; it does not justify fake metrics or stronger prose.
- A failed safety/recovery invariant blocks release.
- One failed provider request does not authorize a model/billing fallback.
- No phase requires a forced number of interviews, fake test count or presumed score.

All prompts intentionally reference the same locked V4. Any material change to identity, custody, supported actions, terms, handover, replay, privacy or removed lease/pay promises requires a versioned amendment and updated affected prompts.
