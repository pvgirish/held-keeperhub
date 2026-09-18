# Environment reference

Every `HELD_*` variable the code requires, what it is for, and whether it is a secret.

**No secret is ever committed, logged or written into an evidence artifact.** Key material
is referenced (`env:NAME`, `keystore:/path`) and resolved transiently; the reference is what
travels, never the value.

## Always needed

| Variable | What | Secret |
|---|---|---|
| `HELD_BASE_RPC` | The Base RPC endpoint. For local work this is the anvil fork that `fixtures/with_fork.sh` starts and exports; for a public read it is a Base endpoint. | no |
| `HELD_PRICE_MODE` | `testing-only` supplies a fixed USDC price to the pinned compiler. **Never valid as runtime evidence** — the probe gate fails without it and must. | no |

## Fixture-supplied (written by `fixtures/scripts/*` into `/tmp/held_fixture.env`)

| Variable | What |
|---|---|
| `HELD_SAFE` | The customer Safe being operated |
| `HELD_ROLES` | The Zodiac Roles module |
| `HELD_ROLE_KEY`, `HELD_ALLOW_KEY` | The fixture's normal role key and supply allowance key |
| `HELD_CONTROLLER` | The deployed Held controller |
| `HELD_INSTALL_MANIFEST` | Path to the declared installation the checklist compares against |
| `HELD_RUNNER`, `HELD_EXECUTOR` | The selected operating identities |
| `HELD_FORK_BLOCK` | Lower bound for bounded authorization-history discovery |
| `HELD_INVENTORY_MODE` | `initial` (fresh installation, V4 §6) or `handover` (mid-life authority) |

## Key references — SECRET, never committed

| Variable | What | Secret |
|---|---|---|
| `HELD_RUNNER_KEY` | The runner signing key, resolved through `RunnerSigner("env:HELD_RUNNER_KEY", ...)`. The signer recovers from its own output and refuses a key that is not the configured runner. | **yes** |
| `HELD_COMPOSED_RUNNER_KEY` | The composed local run's runner key. On a fork this is an anvil deterministic account — public, well known, never custody. | fixture |
| `HELD_HERO_KEY` | Set by `script/hero_demo.py` for its own signing. Anvil account, fork only. | fixture |
| `HELD_KEYSTORE_PASSPHRASE` | Passphrase for a `keystore:/path` reference, when that form is used instead of `env:`. | **yes** |
| `HELD_KEEPERHUB_API_KEY` | The KeeperHub organisation credential, and **the only variable any KeeperHub code path reads.** Currently resolves to the organisation's `mcp:read` key, validated live (`make check-l10-route-proof` → `evidence/P03/l10-route-proof.json`). Broadcasting needs `mcp:write` or `mcp:admin`; there is **no separate write-key variable**, so a broadcast means the owner temporarily swaps the write key into this same name (`M1-IRREVERSIBLE-PREFLIGHT.md` step 11) and swaps it back. | **yes** |

## Console

| Variable | What | Secret |
|---|---|---|
| `HELD_CONSOLE_SECRET` | Shared secret for the private operator console. Localhost only; the console holds no keys and can move no funds. | **yes** |

## Prerequisites this repository does not install

| What | Pin |
|---|---|
| CPython | 3.12 |
| Almanak SDK | `6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938` |
| Foundry | observed 1.8.1; **not** a required pin — see `RESUME.md` |

`make` takes `PY` and `SDK` as overrides, so nothing is hardcoded to a particular machine.
See [`docs/decisions/environment-setup.md`](decisions/environment-setup.md) for how these
were rebuilt.
