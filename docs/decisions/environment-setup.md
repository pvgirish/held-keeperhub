# Reproducible environment setup

**Sections 1-3 and 5 were actually run** on the device VM on 2026-09-15 and are reproducible from a clean state.
**Section 4 is PENDING** - those commands have never been executed, because no RPC endpoint is reachable. Do not read them as historical results. Paths are the executor's scratch (`$HOME`), deliberately **outside** the connected folder — a clone and a venv are not deliverables.

## 1. Python 3.12 (the SDK requires >= 3.12)

The device VM ships Python 3.10.12, which the pinned SDK refuses:

    ERROR: Package 'almanak' requires a different Python: 3.10.12 not in '>=3.12'

Fixed with `uv`, which fetches a standalone CPython from GitHub (reachable; `python.org` was not needed):

    python3 -m pip install --user uv
    export PATH="$HOME/.local/bin:$PATH"
    uv python install 3.12          # -> CPython 3.12.13

## 2. The pinned SDK

    mkdir -p ~/src && cd ~/src
    git clone --filter=blob:none --no-checkout https://github.com/almanak-co/sdk.git sdk
    cd sdk && git checkout 6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938
    uv venv --python 3.12 ~/venv312
    uv pip install --python ~/venv312/bin/python -e .

Verify:

    cd ~/src/sdk && git rev-parse HEAD        # 6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938
    wc -l almanak/framework/runner/strategy_runner.py   # 13533

## 3. Foundry

`foundry.paradigm.xyz` is refused by the egress gateway, so `foundryup` cannot be used. The GitHub release is reachable, so install from it directly, with a checksum check:

    TAG=v1.8.3; A=arm64        # asset names use arm64, NOT aarch64
    BASE="https://github.com/foundry-rs/foundry/releases/download/${TAG}"
    curl -sL -o foundry.tar.gz "${BASE}/foundry_${TAG}_linux_${A}.tar.gz"
    curl -sL -o foundry.sha256 "${BASE}/foundry_${TAG}_linux_${A}.sha256"
    [ "$(awk '{print $1}' foundry.sha256)" = "$(sha256sum foundry.tar.gz | awk '{print $1}')" ] || exit 1
    mkdir -p ~/.foundry/bin && tar -xzf foundry.tar.gz -C ~/.foundry/bin
    export PATH="$HOME/.foundry/bin:$PATH"

Installed and verified: forge / anvil / cast **1.8.3**, commit `cae51ad458f6abb64852b7709eb784352429825d`, sha256 `93fc23be26c8a902ca58fe54aa6ca28c880b58af95d052674933161df7928e6d`.

Anvil works standalone without any fork URL — smoke tested, chain id `31337`, block `0`.

## 4. PENDING - not yet run, no endpoint reachable

A **Base mainnet RPC endpoint**. Every host tested is refused 403 at the egress CONNECT gateway. Anvil is installed and working, but `anvil --fork-url <base>` cannot run without one.

None of the commands in this section has been run. When an endpoint becomes available, do not assume it is sufficient - verify before forking:

    cast chain-id     --rpc-url "$BASE_RPC"        # must be 8453
    cast block-number --rpc-url "$BASE_RPC"
    # pin a block, then confirm the endpoint serves HISTORICAL state at it:
    cast code   <morpho-singleton> --rpc-url "$BASE_RPC" --block <N>
    cast storage <morpho-singleton> 0 --rpc-url "$BASE_RPC" --block <N>

A rate-limited public endpoint may answer `chain-id` and still fail archive reads at a pinned block. Record the chosen block **number and hash** in `native-measurements.json`.

## 5. Running the gates

    cd <ha>/held
    make check-phase-00
