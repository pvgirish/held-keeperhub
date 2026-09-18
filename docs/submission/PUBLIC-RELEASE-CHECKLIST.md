# Public release checklist

The repository is **private**. Changing that requires Girish's authorization and has not
been requested. This is what must be true first, prepared in advance so the decision is a
decision rather than a project.

| # | Item | Status | How it is checked |
|---|---|---|---|
| 1 | No committed secrets | **PASS** | `make clean-install` scans tracked source; only anvil deterministic keys appear, and they are documented as fixture identities |
| 2 | No private RPC endpoints | **PASS** | the only RPC referenced is the public `https://mainnet.base.org` |
| 3 | No API keys | **PASS** | **Re-derived 2026-09-18.** This used to pass on absence — "no KeeperHub credential exists in this environment to leak" — which stopped being true when one was supplied. It now passes on the protections instead: the client resolves by reference (`env:NAME`) and never persists, logs or reprs a value; `CredentialReference` refuses a reference that carries the secret; and `evidence/P03/l10-route-proof.json` is built by `CredentialCheck.to_evidence()`, which records the prefix match as a boolean and copies no key, no `keyPrefix`, no operator name and no email. A regression test asserts all four are absent |
| 4 | No real private keys | **PASS** | every key in the fixtures is a well-known anvil account, labelled as such in `SECURITY-NOTES.md` |
| 5 | Fixture credentials clearly labelled | **PASS** | `SECURITY-NOTES.md` and inline comments at every use site |
| 6 | No personal filesystem paths | **PASS** | checked against tracked `*.py`, `*.sh`, `*.sol` and the Makefile |
| 7 | README works signed-out | **PASS** | all links are repository-relative; no private URL is referenced |
| 8 | Evidence included | **PASS** | `evidence/P00`–`P06`, plus the review packets under `docs/plan/` |
| 9 | License present | **CHECK** | `contracts/src/*.sol` carry `SPDX-License-Identifier: MIT`; a repository-level LICENSE file is **not present** and should be added before publication |
| 10 | Release source matches candidate SHA | **PASS** | the pre-release manifest records the SHA and a clean tree |

## The one gap

**Item 9.** Solidity sources carry SPDX MIT headers, but there is no repository-level
`LICENSE`. Adding one is a small, reversible change — it is listed here rather than done
silently because choosing a license is the owner's call, not the executor's.

## What publication does not fix

Making the repository public satisfies **M3**. It does not satisfy **M1** or **M2**, which
need a real KeeperHub execution. Publishing early would expose an entry whose headline
evidence is absent.
