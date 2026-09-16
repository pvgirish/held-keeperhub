# Security notes for this repository

## Private keys in this repository are the public Anvil test keys

`fixtures/scripts/*.sh` and `test/contracts/HeldController.t.sol` contain 32-byte hex
private keys. **These are the well-known Anvil / Hardhat deterministic development
accounts.** They are published in Foundry's own documentation and ship inside
`lib/forge-std/test/StdCheats.t.sol` in this very dependency tree.

They are used only to sign local-fork fixture transactions. They hold no mainnet value,
control no real Safe, and are never used for any public network.

They are identified here rather than scrubbed, because a reader finding a hex private key
in a repository deserves an explicit answer about what it is. Secret scanning is **not**
disabled or suppressed anywhere in this repository.

| account | address | role in the fixtures |
|---|---|---|
| anvil #0 | `0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266` | Safe owner 1 |
| anvil #1 | `0x70997970C51812dc3A010C7d01b50e0d17dc79C8` | Safe owner 2 |
| anvil #2 | `0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC` | Safe owner 3 |
| anvil #3 | `0x90F79bf6EB2c4f870365E785982E1f101E93b906` | operator A |
| anvil #4 | `0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65` | operator B |
| anvil #6 | `0x976EA74026E726554dB657fA54763abd0C3a0aa9` | legacy agent / executor |

## What is deliberately NOT in this repository

- No KeeperHub organisation API key, JWT or any authenticated credential. The
  authenticated caller/payer route is the open blocker **L10**; nothing about it is
  stored, stubbed or simulated here.
- No private or rate-limited RPC endpoint. The only RPC referenced is the public
  `https://mainnet.base.org`, in `fixtures/fork.env`.
- No local databases, virtual environments, dependency caches or build output.
- No real custody material of any kind.

## fixtures/fork.env is intentionally committed

It carries the public Base RPC URL, the pinned fork block number and hash, the chain id
and public contract addresses. It is configuration required to reproduce the fork, not a
credential.

## If you are reviewing a push-protection alert

Please check it against the table above before assuming a leak. If something genuinely
sensitive ever lands here, rotate it first and rewrite history second — do not simply
delete the file in a later commit.
