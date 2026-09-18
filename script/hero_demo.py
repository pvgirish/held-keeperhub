#!/usr/bin/env python3
"""The hero workflow, driven end to end against the REAL pinned fork.

    runner A active -> capacity consumed -> an operation becomes ambiguous ->
    handover REFUSED while unresolved -> reconcile against the chain ->
    owner fences -> bounded authority inventory -> prepare runner B ->
    owner activates -> Held's verified consumption is preserved ->
    runner A's old authorization is refused -> runner B continues

Nothing here is staged. The controller, Safe, Zodiac Roles, Morpho and USDC are the real
pinned contracts on a Base-mainnet fork; the owner transactions are the ones
`held_handover.owner_tx` builds, executed by the impersonated owner Safe exactly as a real
owner would execute them in their own Safe; the consumption figures are read back off the
controller.

EVIDENCE GRADE: REAL LOCAL FORK. An anvil fork has no finality and no public visibility.
This demonstrates the handover mechanism; it is NOT a public-chain execution and must never
be presented as one.

Run it with `make hero-demo`, which supplies the fork.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("packages/handover", "packages/authority", "packages/core", "adapter"):
    sys.path.insert(0, os.path.join(ROOT, p))

from held_handover import (  # noqa: E402
    Candidate,
    ExpectedState,
    HandoverBlocked,
    HandoverMachine,
    Policy,
    build_export,
    build_fence,
)
from held_handover.readback import read_controller_state  # noqa: E402
from held_handover.sources import CastControllerSource  # noqa: E402
from held_handover.owner_tx import build_activate  # noqa: E402
from held_handover import CastConsumptionReader, build_report  # noqa: E402

RPC = os.environ["HELD_BASE_RPC"]
SAFE = os.environ["HELD_SAFE"]
CONTROLLER = os.environ["HELD_CONTROLLER"]
CHAIN = 8453

# anvil deterministic accounts. LOCAL FIXTURE IDENTITIES ONLY, never custody.
RUNNER_A = "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65"
RUNNER_B = "0x976EA74026E726554dB657fA54763abd0C3a0aa9"
EXECUTOR = "0x976EA74026E726554dB657fA54763abd0C3a0aa9"
LINEAGE = "0x" + "0" * 62 + "11"

STEPS: list[dict] = []
NATIVE_CHECKPOINTS: list[dict] = []
_t0 = time.time()


def cast(*args: str, check: bool = True) -> str:
    cmd = ["cast", *args, "--rpc-url", RPC]
    out = subprocess.run(cmd, capture_output=True, text=True,
                         env={**os.environ,
                              "PATH": f"{os.path.expanduser('~')}/.foundry/bin:"
                                      f"{os.environ.get('PATH', '')}"})
    if check and out.returncode != 0:
        raise RuntimeError(f"cast {' '.join(args[:3])} failed: {out.stderr.strip()[:300]}")
    return out.stdout.strip()


def owner_send(tx) -> str:
    """Execute an owner transaction AS THE SAFE, the way a real owner would.

    Held built this calldata and did not sign it. On the fork the Safe is impersonated,
    which stands in for the 2-of-3 ceremony evidenced separately in P00.
    """
    return cast("send", tx.to, tx.data, "--from", SAFE, "--unlocked",
                "--value", str(tx.value))


def step(n: int, title: str, **detail) -> None:
    STEPS.append({"n": n, "title": title, "at": round(time.time() - _t0, 2), **detail})
    print(f"\n[{n:2d}] {title}")
    for k, v in detail.items():
        if k.startswith("_"):
            continue
        print(f"     {k}: {v}")


def read(dispatching: bool = True):
    # No finality source: this is a fork, so nothing here is finalized and the
    # evidence grades as REAL LOCAL FORK rather than PUBLIC CHAIN.
    src = CastControllerSource(RPC)
    return read_controller_state(src, controller=CONTROLLER, expected_chain_id=CHAIN,
                                 adapter_dispatching=dispatching)


def policy() -> Policy:
    """The customer's approved operating limits, in USDC base units."""
    return Policy(Ls=50_000_000_000, Ln=50_000_000_000, Lr=10_000_000_000,
                  Ms=40_000_000_000, Mn=40_000_000_000, Mr=10_000_000_000,
                  ms=1_000_000, mn=1_000_000, F=0, H=0, Nn=10, Nr=5)


def expected_from(reading) -> ExpectedState:
    u = reading.used
    return ExpectedState(u["usedSupply"], u["usedNormalWithdraw"], u["usedRestoration"],
                         u["normalCount"], u["restorationCount"])


RUNNER_A_KEY = "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a"


def config_identity():
    """The ACTUAL native configuration identity runner B must continue under.

    Built by held_handover.config_identity, which binds the producer, the chain, the
    custody addresses, the FULL market tuple, the execution profile and the price mode. An
    earlier version bound none of the market, so two different Morpho markets on the same
    Safe produced the same digest.
    """
    from held_handover import build_config_identity
    from eth_utils import keccak

    usdc = os.environ.get("HELD_USDC", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
    return build_config_identity(
        chain_id=CHAIN, safe=SAFE, controller=CONTROLLER, lineage=LINEAGE,
        morpho="0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb",
        market=(usdc, "0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452",
                "0xD7A1abA119a236Fea5BBC5cAC6836465cbe9289A",
                "0x46415998764C29aB2a25CbeA6254146D50D22687", 860000000000000000),
        execution_profile="supply+withdraw/morpho_blue/single-safe",
        price_mode=os.environ.get("HELD_PRICE_MODE", "production"),
        strategy_config_digest="0x" + keccak(
            b"SupplyIntent|morpho_blue|base|USDC|100").hex())


def native_config_digest() -> str:
    return config_identity().digest()
SUPPLY_AMOUNT = 12_000_000  # 12 USDC, well inside the approved per-action maximum


def _build_supply(live, *, decision_id: str, runner: str, key: str, epoch: int | None = None):
    """Admit a supply and sign it. Returns (admitted, envelope, calldata).

    Shared by the real consumption and by the stale-authorization attempt, so the stale
    attempt is the SAME shape of call -- the only difference is the epoch and runner it
    was signed for, which is exactly the thing under test.
    """
    from eth_abi import encode as abi_encode
    from eth_utils import keccak

    from held_core.identity import AuthorizationEnvelope
    from held_adapter.execution.controller_abi import build_execute_call
    from held_adapter.execution.interceptor import Profile, admit_bundle
    from held_adapter.signing.runner_signer import RunnerSigner

    usdc = os.environ.get("HELD_USDC", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
    market = (usdc,
              "0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452",
              "0xD7A1abA119a236Fea5BBC5cAC6836465cbe9289A",
              "0x46415998764C29aB2a25CbeA6254146D50D22687",
              860000000000000000)
    profile = Profile(chain_id=CHAIN, controller=CONTROLLER, safe=SAFE, lineage=LINEAGE,
                      morpho="0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb",
                      token=usdc, market_params=market)
    bundle = {
        "safe": SAFE,
        "calls": [
            {"to": usdc, "value": 0,
             "data": "0x095ea7b3" + abi_encode(
                 ["address", "uint256"], [profile.morpho, SUPPLY_AMOUNT]).hex()},
            {"to": profile.morpho, "value": 0,
             "data": "0xa99aad89" + abi_encode(
                 ["(address,address,address,address,uint256)", "uint256", "uint256",
                  "address", "bytes"],
                 [profile.market_params, SUPPLY_AMOUNT, 0, SAFE.lower(), b""]).hex()},
        ],
    }
    admitted = admit_bundle(bundle, profile, decision_id, 0)
    NATIVE_CHECKPOINTS.append({"intent_id": decision_id, "intent_type": "SUPPLY",
                               "state": "VALIDATING_SUPPLY",
                               "operation_id": "0x" + bytes(admitted.operation_id).hex()})
    env = AuthorizationEnvelope(
        scope=profile.scope(),
        operation_id=admitted.operation_id,
        source_identity_hash=keccak(decision_id.encode()),
        payload_hash=admitted.payload_hash,
        action_family=admitted.action.family,
        epoch=epoch if epoch is not None else live.epoch,
        policy_version=live.policy_version,
        runner=runner)
    os.environ["HELD_HERO_KEY"] = key
    signed = RunnerSigner("env:HELD_HERO_KEY", runner).sign(env)
    _fn, _args, calldata = build_execute_call(admitted, env, signed.signature,
                                              profile.market_params)
    return admitted, env, calldata


# Controller custom errors, computed with `cast sig` rather than guessed. Naming the
# refusal matters: "it reverted" is much weaker evidence than "it reverted with
# WrongEpoch(2, 1)", which says the epoch guard is what refused it.
CONTROLLER_ERRORS = {
    "0x2b9264ec": "WrongEpoch(uint64 got, uint64 want)",
    "0x5cd5d233": "BadSignature()",
    "0xc1f407ce": "WrongPolicyVersion(uint32 got, uint32 want)",
    "0xc4dbbd03": "WrongScope()",
    "0x9e87fac8": "Paused()",
}


def decode_revert(blob: str) -> tuple[str, str]:
    """Name the custom error if we recognise it. An unrecognised one stays raw."""
    import re as _re
    m = _re.search(r"0x[0-9a-fA-F]{8}", blob)
    if not m:
        return "", blob.strip().split(chr(10))[0][:160]
    sel = m.group(0).lower()
    return CONTROLLER_ERRORS.get(sel, ""), sel


class DroppingServer:
    """A REAL local HTTP server that accepts the request and then drops the connection.

    This is the difference between "we constructed an ambiguous outcome" and "an ambiguous
    outcome happened". The request genuinely leaves the client over a socket, the server
    genuinely receives and records it, and then the connection closes with no response --
    so the client cannot know whether the work was started.

    EVIDENCE GRADE: REAL OPERATION + DURABLE JOURNAL + REAL LOCAL TRANSPORT AMBIGUITY.
    The server is local and is not KeeperHub. Nothing here is hosted evidence.
    """

    def __init__(self) -> None:
        import socket
        import threading

        self.received: list[dict] = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        import socket as _s
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except OSError:
                return
            try:
                conn.settimeout(2.0)
                blob = b""
                while b"\r\n\r\n" not in blob and len(blob) < 65536:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    blob += chunk
                head = blob.split(b"\r\n\r\n", 1)[0].decode("latin-1")
                self.received.append({
                    "request_line": head.split("\r\n")[0],
                    "bytes": len(blob),
                    "has_idempotency_header": "idempotency-key" in head.lower(),
                })
                # The point: accept, then vanish. No status line, no body.
                conn.setsockopt(_s.SOL_SOCKET, _s.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
                conn.close()
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass

    def close(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass


class RealLocalTransport:
    """Performs an ACTUAL socket HTTP request to the dropping server."""

    hosted = False          # local, and not KeeperHub. Never hosted evidence.

    def __init__(self, port: int) -> None:
        self.port = port
        self.calls = 0

    def request(self, method, url, *, headers, body, timeout):
        import http.client

        self.calls += 1
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout or 5)
        path = "/api/execute/contract-call"
        conn.request(method, path, body=body, headers=dict(headers))
        # The server closes without answering. Whatever this raises, the outcome of the
        # work is genuinely unknown.
        return conn.getresponse()


def interrupt_a_real_submission(live, journal) -> dict:
    """Dispatch a REAL Held operation whose request is received and then dropped.

    The previous version of this demo assigned `ambiguous = "0x" + "7e"*32` and narrated it
    as a send that never came back. Nothing was ever built, journaled or submitted.

    This is the real thing, twice over: the actual Submitter admits an action, derives the
    operation id from this deployment's scope, signs the envelope, claims the operation
    durably BEFORE any I/O -- and the request then travels over a real socket to a real
    server that receives it and closes without responding.
    """
    from held_adapter.execution.keeperhub import KeeperHubClient
    from held_adapter.execution.submit import AssumedBroadcastCapability, Submitter
    from held_adapter.signing.runner_signer import RunnerSigner

    admitted, env, _calldata = _build_supply(
        live, decision_id="hero-demo-interrupted", runner=RUNNER_A, key=RUNNER_A_KEY)
    oid = "0x" + bytes(admitted.operation_id).hex()

    server = DroppingServer()
    transport = RealLocalTransport(server.port)
    market = (os.environ.get("HELD_USDC", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"),
              "0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452",
              "0xD7A1abA119a236Fea5BBC5cAC6836465cbe9289A",
              "0x46415998764C29aB2a25CbeA6254146D50D22687",
              860000000000000000)
    os.environ["HELD_KEEPERHUB_API_KEY"] = "kh_local_fork_demo_not_a_real_credential"
    os.environ["HELD_HERO_KEY"] = RUNNER_A_KEY
    try:
        sub = Submitter(journal,
                        KeeperHubClient(transport=transport, sleep=lambda _: None),
                        RunnerSigner("env:HELD_HERO_KEY", RUNNER_A),
                        CONTROLLER, CHAIN, market,
                        new_attempt_id=lambda: "hero-interrupted-attempt-1",
                        # The demo runs against a local socket, not KeeperHub: there
                        # is no organisation route here to ask about scopes.
                        capability=AssumedBroadcastCapability(
                            "hero demo on a local fork; the server is a local socket"))
        submission = sub.submit(admitted, env)
        outcome = submission.send.outcome.name
    finally:
        time.sleep(0.05)
        server.close()

    op = journal.get(oid)
    attempt = journal.unresolved_attempt(oid)
    return {"operation_id": oid,
            "journal_state": op.state.value if op else None,
            "attempt": (attempt or {}).get("attempt_id"),
            "outcome": outcome,
            "transport_calls": transport.calls,
            "server_received": len(server.received),
            "server_saw_idempotency_header": bool(
                server.received and server.received[0]["has_idempotency_header"]),
            "request_line": server.received[0]["request_line"] if server.received else None,
            "evidence_grade": "REAL OPERATION + DURABLE JOURNAL + REAL LOCAL TRANSPORT "
                              "AMBIGUITY (local server, NOT KeeperHub, NOT hosted)"}


def attempt_stale_authorization(live) -> dict:
    """Runner A signs a NEW operation under its OLD epoch, after the handover.

    This is the behavioural test of the headline claim. Inferring the refusal from the
    configuration would prove nothing: the controller has to actually reject it.
    """
    _admitted, env, calldata = _build_supply(
        live, decision_id="hero-demo-stale-A", runner=RUNNER_A, key=RUNNER_A_KEY,
        epoch=1)
    out = subprocess.run(
        ["cast", "send", CONTROLLER, calldata, "--from", EXECUTOR, "--unlocked",
         "--rpc-url", RPC],
        capture_output=True, text=True,
        env={**os.environ, "PATH": f"{os.path.expanduser('~')}/.foundry/bin:"
                                   f"{os.environ.get('PATH', '')}"})
    blob = (out.stdout + out.stderr)
    name, selector = decode_revert(blob) if out.returncode != 0 else ("", "")
    return {"rejected": out.returncode != 0,
            "signed_for_epoch": env.epoch,
            "error": name or selector,
            "selector": selector}


def consume_budget(live) -> int:
    """Have runner A execute one REAL supply, so there is consumption to preserve.

    This is the ordinary Held path, not a shortcut: an Almanak-shaped bundle is admitted,
    the operation id is derived from THIS deployment's scope, runner A signs the envelope
    with EIP-712, and the controller executes it through Zodiac Roles against real Morpho.
    The controller's own `usedSupply` is what moves.
    """
    _admitted, _env, calldata = _build_supply(
        live, decision_id="hero-demo-decision", runner=RUNNER_A, key=RUNNER_A_KEY)
    cast("rpc", "anvil_impersonateAccount", EXECUTOR, check=False)
    cast("rpc", "anvil_setBalance", EXECUTOR, "0xDE0B6B3A7640000", check=False)
    cast("send", CONTROLLER, calldata, "--from", EXECUTOR, "--unlocked")
    return SUPPLY_AMOUNT


def main() -> int:
    print("=" * 78)
    print("HELD — hero workflow: customer-approved limits and a recoverable handover")
    print("EVIDENCE GRADE: REAL LOCAL FORK (Base mainnet fork, no finality, not public)")
    print("=" * 78)

    # ---------------------------------------------------------------- 1. runner A --
    before = read()
    if before.status.value == "OWNER_FENCED" and before.epoch == 0:
        act = build_activate(
            controller=CONTROLLER, chain_id=CHAIN, new_epoch=1, new_policy_version=1,
            new_runner=RUNNER_A, new_executor=EXECUTOR, policy=policy(),
            expected=expected_from(before), current_epoch=0)
        owner_send(act)
    live = read()
    step(1, "Runner A is ACTIVE under customer-approved limits",
         epoch=live.epoch, runner=live.runner, status=live.status.value)

    # ------------------------------------------- 2. runner A actually spends budget --
    # This matters: a handover that preserves a consumption of ZERO demonstrates nothing.
    # Runner A executes a REAL supply through the controller, so the figure carried across
    # the handover later is one that was genuinely spent.
    spent = consume_budget(live)
    live = read()
    p = policy()
    used = live.used
    step(2, "Runner A executes a REAL supply through Held — budget is actually spent",
         amount_usdc=f"{spent / 1_000_000:.2f}",
         supply_ceiling=p.Ls, used=used["usedSupply"],
         remaining=p.Ls - used["usedSupply"],
         normal_count=f"{used['normalCount']}/{p.Nn}",
         path="Almanak-shaped bundle -> Held admission -> runner A EIP-712 -> "
              "HeldController -> Zodiac Roles -> Safe -> Morpho")

    # ------------------------------------- 3. a REAL operation becomes ambiguous --
    from held_core.journal import Journal

    journal_path = os.path.join(ROOT, "fixtures", "generated", "hero-demo-journal.sqlite")
    os.makedirs(os.path.dirname(journal_path), exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(journal_path + suffix):
            os.remove(journal_path + suffix)
    j = Journal(journal_path)

    interrupted = interrupt_a_real_submission(live, j)
    step(3, "A REAL operation is dispatched; the server receives it and drops the connection",
         operation=interrupted["operation_id"][:18] + "...",
         journal_state=interrupted["journal_state"],
         durable_attempt=interrupted["attempt"],
         send_outcome=interrupted["outcome"],
         server_received_request=interrupted["server_received"],
         saw_idempotency_header=interrupted["server_saw_idempotency_header"],
         grade=interrupted["evidence_grade"],
         why="the request really left over a socket and the server really received it, "
             "then closed without answering. Held claimed the operation durably BEFORE any "
             "I/O, so the attempt is recoverable — but whether the work started is "
             "genuinely unknown, and an unknown is not a verified negative")

    m = HandoverMachine.start(j, handover_id="hero", controller=CONTROLLER, chain_id=CHAIN,
                              retiring_runner=live.runner, retiring_epoch=live.epoch,
                              safe=SAFE, lineage=LINEAGE)
    fence_tx = m.prepare_fence(current_epoch=live.epoch)
    owner_send(fence_tx)
    m.confirm_fenced(read(dispatching=False))
    step(4, "Owner FENCES the controller on chain (Held prepared it; the owner sent it)",
         selector=fence_tx.data,
         fence_block=read(dispatching=False).block_number,
         status=read(dispatching=False).status.value,
         note="an adapter that merely stops dispatching is NOT a fence — the controller "
              "would still honour a signed envelope")

    # The machine DERIVES the retiring-epoch operation set from the journal. With the
    # chain unreachable the interrupted operation is UNRESOLVED, and that blocks.
    fence_reading = read(dispatching=False)

    class Unreachable:
        def consumed(self, controller, operation_id):
            raise RuntimeError("the chain is unreachable")

    stuck = build_report(j, record=m.record, fence_reading=fence_reading,
                         reader=Unreachable())
    try:
        m.reconcile(stuck)
        raise AssertionError("the handover proceeded with an unresolved operation")
    except HandoverBlocked as exc:
        step(5, "Handover REFUSED while the outcome is unresolved",
             operations_derived_from_journal=len(stuck.resolutions),
             blockers=exc.blockers,
             why="the machine derived this set from the durable journal, not from a list "
                 "someone handed it. Activating now would either lose consumption that "
                 "really happened or charge the customer twice for work that did not")

    # ------------------------------------------------------- 6. reconcile the truth --
    reader = CastConsumptionReader(RPC, chain_id=CHAIN)
    report = build_report(j, record=m.record, fence_reading=fence_reading, reader=reader)
    m.reconcile(report)
    after_recon = read(dispatching=False)
    resolved = report.resolutions[0] if report.resolutions else None
    step(6, "Reconciled from the controller's own consumed[] record",
         operations=len(report.resolutions),
         verdict=resolved.resolution if resolved else "none",
         marker=(resolved.marker or "")[:18] + "..." if resolved else "",
         used_supply=after_recon.used["usedSupply"],
         note="the verdict comes from consumed[operationId] at a stated block, not from "
              "the transport's silence")

    # ------------------------------------------------- 7. bounded authority inventory --
    from held_authority import collect
    # Collected LIVE against this fork, at or after the fence. There is deliberately no
    # fallback: the previous version built an empty SimpleNamespace when the report was
    # missing, which turned absent authority evidence into clean authority evidence.
    # HANDOVER mode, not initial: this controller has already run one epoch and spent
    # budget, which is exactly what makes the handover worth doing. The initial-activation
    # checklist asks a different question (is this fresh?) and would be INCOMPLETE forever.
    inv = collect(env={"HELD_SAFE": SAFE, "HELD_CONTROLLER": CONTROLLER,
                       "HELD_BASE_RPC": RPC, "HELD_INVENTORY_MODE": "handover"},
                  cwd=ROOT)
    step(7, "Bounded authority inventory, collected LIVE at the fence",
         mode="handover",
         sections=inv.section_count, complete=inv.complete,
         observed_at_block=inv.block_number,
         external_delegates=inv.external_delegates or "none",
         grade=inv.evidence_grade)

    # --------------------------------------------------------- 8. prepare runner B --
    paused = read(dispatching=False)
    cand = Candidate(runner=RUNNER_B, executor=EXECUTOR, new_epoch=paused.epoch + 1,
                     new_policy_version=2, policy=policy(),
                     expected=expected_from(paused),
                     native_config_digest=native_config_digest(), lineage=LINEAGE)
    m.prepare_candidate(cand, observed=paused)
    step(8, "Runner B pinned against the consumption actually on chain",
         runner_b=RUNNER_B, new_epoch=cand.new_epoch,
         carried=list(cand.expected.as_tuple()))

    m.clear_authority(inv, fence_block=fence_reading.block_number)

    # ------------------------------------------------------------- 9. owner activates --
    act_tx = m.prepare_activation()
    step(9, "Held PREPARES the activation and describes it; it does not sign it",
         summary=act_tx.summary,
         reverts_if=len(act_tx.reverts_if))
    owner_send(act_tx)
    final = read()
    m.confirm_active(final)
    step(10, "Runner B is ACTIVE — Held's verified consumption survived the handover",
         epoch=final.epoch, runner=final.runner,
         used_supply=final.used["usedSupply"],
         remaining=policy().Ls - final.used["usedSupply"],
         lineage_preserved=True)

    # --------------------------------------------- 11. runner A's authorization is dead --
    stale = attempt_stale_authorization(final)
    assert stale["rejected"], (
        "runner A's stale authorization was ACCEPTED after the handover -- the headline "
        "claim is false and this demo must not be shown")
    step(11, "Runner A ATTEMPTS its old authorization — the controller refuses it",
         signed_for_epoch=stale["signed_for_epoch"], current_epoch=final.epoch,
         rejected=stale["rejected"], reverted_with=stale["error"],
         selector=stale["selector"],
         why="behavioural, not inferred: runner A really signed a fresh operation under "
             "its retired epoch and really sent it. The controller authorizes against the "
             "CURRENT epoch and runner, so it reverts.")

    # ------------------------------------------------------------ 12. B can continue --
    # What B genuinely needs: the native decision checkpoints from this lineage, and the
    # settled predecessors so it does not re-derive history from scratch.
    checkpoints = [{"intentId": cp["intent_id"], "intentType": cp["intent_type"],
                    "state": cp["state"], "source": "REAL OFFLINE SDK"}
                   for cp in NATIVE_CHECKPOINTS]
    settled = [r.to_dict() for r in report.resolutions]
    exp = build_export(handover_id="hero", record=m.record, reading=final,
                       runner_key_reference="env:HELD_RUNNER_B_KEY",
                       native_checkpoints=checkpoints, settled_operations=settled)
    out = os.path.join(ROOT, "evidence", "P04", "hero-demo-replacement-export.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        fh.write(exp.to_json())
    step(12, "Runner B receives what it needs to continue — and no key material",
         usable=exp.usable,
         remaining_supply=exp.remaining_capacity["supply"],
         credential="REFERENCED (env:HELD_RUNNER_B_KEY), never carried",
         export=os.path.relpath(out, ROOT))

    trace = {
        "schema": "held.hero-demo-trace.v1",
        "evidenceGrade": "REAL LOCAL FORK",
        "_scope": "Base-mainnet FORK. No finality, no public visibility, no funds at risk. "
                  "This demonstrates the handover mechanism. It is NOT a public-chain "
                  "execution and must not be presented as one.",
        "chainId": CHAIN, "controller": CONTROLLER, "safe": SAFE,
        "retiringRunner": RUNNER_A, "replacementRunner": RUNNER_B,
        "steps": STEPS,
        "handover": m.status(),
    }
    trace_path = os.path.join(ROOT, "evidence", "P04", "hero-demo-trace.json")
    with open(trace_path, "w") as fh:
        json.dump(trace, fh, indent=2)
        fh.write("\n")

    j.close()
    print("\n" + "=" * 78)
    print(f"hero workflow complete — {len(STEPS)} steps, "
          f"{round(time.time() - _t0, 1)}s, EVIDENCE GRADE: REAL LOCAL FORK")
    print(f"trace: {os.path.relpath(trace_path, ROOT)}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
