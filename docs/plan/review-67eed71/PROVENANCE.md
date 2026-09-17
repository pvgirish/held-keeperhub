# Provenance — `Held_67eed71_Review_and_Regression_Packet`

The review of `67eed7193f5fe9472d8c2f1876dfb10c7e400f9a`, stored here so a future session
finds the actual pending instructions instead of re-deriving them. The review text is
`docs/plan/REVIEW-67eed71.md`, verbatim.

## Delivery

Received 2026-09-17 as a ZIP. It was **not** authored in this tree and is not Claude's own
work: it is the external reviewer's packet.

```
Held_67eed71_Review_and_Regression_Packet.zip
sha256  960685c6dc238e772718affeb290f9aee989d38733d3fb03a2b0908fc5054416
bytes   27291
```

## Member digests, as unpacked

| File | sha256 |
|---|---|
| `Held_67eed71_Review_and_Continuation.md` | `d1c6aa6b47b5567b656a855b2e259ee4611ecae7d04089340e592db5ae172cd4` |
| `manifest.json` | `8b27dd75224ee886d720e9e2dad16524cee0b027ed7808a3ea5da329bdc5ab77` |
| `test_native_checkpoint.py` | `cc544cfc285a46d78d657dcadb14e888491268364b3bdc5567cb1c5b7781f2a0` |
| `test_bootstrap_collector.py` | `6b3343d94c4d493975b4f49206b7f03e88d38443f7e1ba022ae657c50398d5a8` |
| `native_probe_results.json` | `fad8f8e45f0bfed54efaeaa2da9f2f5db2d11391c86590747677a2dd3a809c3a` |
| `collector_probe_results.json` | `4047fedd8775032ec269007331e210d3e0bed4df0e13d1177a496e78c43a5349` |
| `source/native_result.py` | `2917f6193e9f3b7916c5212001b52d81651930ee42643fe97cc2527fa6390337` |
| `source/collect_bootstrap_evidence.py` | `3200f02132ba4d0ea07b78e7dfdec2be308d0c41370b295ac074d484e83c309d` |

The reviewer's two probe result files are kept here under a `reviewer-` prefix so they are
never confused with results produced in this tree.

## The review is against current code — verified, not assumed

The packet carries the two source files it executed, with Git blob hashes. Both match this
repository at `67eed71` **exactly**, and the packet copies are byte-identical to the working
tree:

| File | Packet `git_blob_sha1` | `git rev-parse HEAD:<path>` | Bytes |
|---|---|---|---|
| `adapter/held_adapter/execution/native_result.py` | `6b3299a0de956e076b59183c9a570105a2a34310` | same | identical |
| `script/collect_bootstrap_evidence.py` | `637f1717b9b2b55ad9f05388b6eff03eb46a9b9e` | same | identical |

So the findings below are not stale observations of an older tree.

## Reproduction in this tree, 2026-09-17

Both probes were run here against the committed sources. **Every finding reproduced, and
every confirmed-fixed control still passed.**

```sh
cd docs/plan/review-67eed71
python3 test_native_checkpoint.py
python3 test_bootstrap_collector.py
```

`test_native_checkpoint.py` — 12 cases, 9 `fixed_control`, **3 `remaining_finding`**:

| Case | Observed |
|---|---|
| public `needs_execution` consults dirty uncommitted machine | `authoritative=false`, returned a decision, `refused=false` |
| `restore` accepts snapshot B under binding A | `complete=true`, `inconsistent=[]`, `refused=false` |
| `restore` builds work with no durable operation | `machines_built=1`, `needs_execution=true`, `refused=false` |

`test_bootstrap_collector.py` — 12 cases, 8 correct rejections, **4 `FALSE PERMITTED`**:
unreviewed nonzero Safe fallback; unsupported Safe implementation version (`0.0.0-unsupported`);
garbled nonempty logs accepted as complete history; malformed native quota balance.

## What these probes are, and are not

The reviewer is explicit, and it is repeated here because the distinction is the whole point
of this project's evidence discipline:

- They execute the **exact committed files**, verified by blob hash before loading.
- They use a **synthetic journal and synthetic machine**, and replace `subprocess.run` with
  scripted `cast` responses in temporary directories.
- They do **not** run the Almanak SDK, the production Held Journal, Forge, a fork, or any RPC.
  No key, signer, provider call or transaction is involved.
- Their **exit status is not a phase gate.** They reproduce and localize known behaviour.
  They do not stand in for integration evidence, and their baseline models do not prove a
  valid installation.

Closing the findings requires the real production entry points, the real journal, the pinned
native consumer and live fork readbacks — not a green run of these scripts.
