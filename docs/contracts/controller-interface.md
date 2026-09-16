# Controller interface — planned design (P01)

**This is a design interface, not a deployed contract and not an existing protocol API.**
Nothing here has been compiled, deployed or executed. P02 implements it; P01 only fixes
its shape so the off-chain contracts can be written against something precise.

## Scope

The controller exposes **only** typed SUPPLY and WITHDRAW entry shapes (V4 §3). It never
executes an arbitrary caller-supplied call list. It makes sequential ordinary `CALL`
operations through Roles inside one outer transaction, with explicit return/revert
checking. **No runtime-selected MultiSend or delegatecall shortcut is permitted** — note
that the *native baseline* uses MultiSendCallOnly for owner batching, which is a
different actor (the Safe owners) doing a different job.

## Entry points

```solidity
function executeSupply(
    Envelope calldata envelope,   // operationId, payloadHash, epoch, policyVersion, runner
    SupplyAction calldata action, // marketParams, assets, onBehalf
    bytes calldata runnerSignature
) external;

function executeWithdraw(
    Envelope calldata envelope,
    WithdrawAction calldata action, // marketParams, assets, onBehalf, receiver == safe
    bytes calldata runnerSignature
) external;
```

`onBehalf` is Morpho's account field. V4 §2 is explicit that the compiler's Morpho
helper living in a file named `aave_helpers.py` does not make this an Aave integration.

Owner-authority entry points (`pause`, `activateEpoch`, `setPolicy`) are separate and
are **not** callable by a runner. Controller calls can never change Safe owners or
modules, grant Morpho delegation, select a new market, or modify their own policy.

## Atomic sequence (V4 §5)

1. Verify domain, active epoch, configured executor, runner signature, identity,
   canonical shape, policy version and state predicates. Prevent reentrancy.
2. **Require the managed Safe→Morpho token allowance is zero at entry.**
3. Execute only: the declared approval if needed, the unchanged native economic call,
   and the approval cleanup — all through Roles/Safe within the outer transaction.
4. Check every nested return status and token behaviour, then read exact effects.
5. Supply must show the permitted Safe debit, retained cash floor and a compatible
   positive share increase. Withdraw must show permitted Safe receipt and a compatible
   share decrease. **Do not infer success from the outer receipt alone.**
6. Borrow shares remain zero; collateral unchanged; managed allowance ends at zero.
7. Persist successful consumption and typed counters atomically; emit enough indexed
   evidence to reconstruct them.

Failure reverts the whole protected call. Gas and transaction nonces do **not** roll
back, and an entry approval left by a previous actor cannot be erased by a reverted
call — cleanup must happen before activation, not inside a transaction destined to
revert.

## State

| state | meaning |
|---|---|
| `epoch` | current authorization generation; pausing retires it |
| `policyVersion` | which typed terms are in force |
| `consumed[operationId]` | operation ID → payload hash, set only on success |
| `usedSupply` / `usedNormalWithdraw` / `usedRestoration` | cumulative, monotonic |
| counts / timestamps | normal lane shared by SUPPLY and NORMAL WITHDRAW; restoration separate |

**Consumption is monotonic.** This is the one mechanism the P00 baseline actually
motivates: native `setAllowance` writes an *absolute* remaining value, so a policy
update can silently regrant already-consumed capacity (baseline case I2). The controller
instead records consumption as counters a policy update cannot decrease.

## Activation-time consistency guard

V4 §5 already requires it, and the baseline shows the failure it catches is real:

> At activation, each Roles remaining allowance must **equal** its configured cumulative
> ceiling minus corresponding successful consumption. Any mismatch blocks activation.

Worked example from the frozen fixture, using the numbers the baseline actually
produced: 35,000 consumed, new ceiling 80,000 → the only consistent remaining value is
**45,000**. An activation proposing 50,000 asserts 30,000 consumed, contradicts recorded
consumption, and **reverts**.

Two honest caveats, both open until P06:

- An off-chain preparation check can compute the same number. It is **not** assumed to
  give the same guarantee — it sits outside the trust boundary and can be bypassed — but
  neither is that distinction assumed sufficient to justify a new contract's trust and
  maintenance cost. P06 must establish which.
- The competent native workflow reaches the correct figure too, at two ceremonies. The
  controller must therefore **not** claim a ceremony or signature saving; V4 §6
  prescribes the same two-stage fence-then-activate order for Held.

## Identity rules at the contract boundary

- A **consumed** ID rejects another execution.
- A **mismatched payload** under an already-bound ID is an identity conflict, not a retry.
- A **reverted** transaction consumes no ID, no counters and no token allowance: EVM
  rollback erases the provisional binding, so the controller cannot retain it.
- A **fresh** ID may represent genuinely new permitted work. No semantic-deduplication
  guarantee is offered against a runner inventing new identities.

## Signer

An ordinary EOA with reviewed signature recovery, using an **established library** —
never hand-written `ecrecover` handling (V4 §3). Contract-account signers require a
versioned extension. Runner identity is never inferred from a KeeperHub API key: two
keys can share an execution address, which is why the EIP-712 envelope exists.

## Not established by this document

No address, deployment, gas cost, audit status or on-chain behaviour. The EIP-712 domain
and type hash in `vectors/canonical-vectors.json` are fixed so off-chain and on-chain
implementations can be written against the same preimage — that is all.
