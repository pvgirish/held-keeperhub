"""P01 acceptance suite. Real checks; a red test is a red test.

Covers exactly what the P01 prompt requires of `make check-phase-01`: journal
crash/reopen, concurrent same-ID requests, body conflicts, epoch-independent consumed
identity, domain separation, cross-language serialization, and the two result
boundaries (callback-before-ack, ack-before-restart).

Run: PY=~/venv312/bin/python make check-phase-01
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "packages", "core"))

from held_core import canonical, identity, journal as J, results as R, units  # noqa: E402
from held_core.identity import ActionFamily, AuthorizationEnvelope, OperationScope, SupportedAction  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def test(name):
    def deco(fn):
        try:
            fn()
            PASSED.append(name)
            print(f"ok    {name}")
        except Exception:
            FAILED.append((name, traceback.format_exc()))
            print(f"FAIL  {name}")
        return fn
    return deco


def expect_raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc:
        return
    except Exception as e:
        raise AssertionError(f"expected {exc.__name__}, got {type(e).__name__}: {e}") from None
    raise AssertionError(f"expected {exc.__name__}, nothing raised")


SAFE = "0x08deEDA0Ba1eb4B6B4b5cc4DD0c4BC689EA37180"
CONTROLLER = "0x3875311cc0d4017a033893a9653a0725378aca1c"
RUNNER_A = "0x90F79bf6EB2c4f870365E785982E1f101E93b906"
RUNNER_B = "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
MARKET = "0x13c42741a359ac4a8aa8287d2be109dcf28344484f91185f9a79bd5a805a55ae"
LINEAGE = "0x" + "11" * 32
SCOPE = OperationScope(chain_id=8453, controller=CONTROLLER, safe=SAFE, lineage=LINEAGE)


def sample_action(amount=10_000_000_000):
    return SupportedAction(ActionFamily.SUPPLY, MARKET, USDC, amount, SAFE)


def envelope(epoch=1, runner=RUNNER_A, oid=None, phash=None, scope=SCOPE):
    act = sample_action()
    return AuthorizationEnvelope(
        scope=scope,
        operation_id=oid or identity.operation_id(scope, "decision-1", 0),
        source_identity_hash=canonical.canonical_hash({"src": "decision-1"}),
        payload_hash=phash or act.payload_hash(),
        action_family=ActionFamily.SUPPLY,
        epoch=epoch,
        policy_version=1,
        runner=runner,
    )


# ----------------------------------------------------------------- units ------
@test("units: bool is not an unsigned integer")
def _():
    expect_raises(units.UnitError, units.uint, True, "x")


@test("units: float is never permitted")
def _():
    expect_raises(units.UnitError, units.uint, 1.0, "x")
    expect_raises(units.UnitError, units.uint, 1e18, "x")


@test("units: negative and overflow rejected; zero accepted")
def _():
    expect_raises(units.UnitError, units.uint, -1, "x")
    expect_raises(units.UnitError, units.uint128, units.UINT128_MAX + 1, "x")
    assert units.uint(0, "x") == 0, "zero disables a lane; it is valid, not 'unset'"


@test("units: decimal-string wire form rejects non-canonical spellings")
def _():
    assert units.parse_decimal_string("10000000000", "a") == 10_000_000_000
    for bad in ("007", "+1", "-1", " 1", "0x10", "1_0", "", "1.0"):
        expect_raises(units.UnitError, units.parse_decimal_string, bad, "a")
    expect_raises(units.UnitError, units.parse_decimal_string, 10, "a")


# ------------------------------------------------------------- canonical -----
@test("canonical: raw ints rejected so a uint256 cannot become a double")
def _():
    expect_raises(units.UnitError, canonical.canonical_bytes, {"amount": 10_000_000_000})
    expect_raises(units.UnitError, canonical.canonical_bytes, {"amount": 1.5})


@test("canonical: key order and whitespace are fixed")
def _():
    a = canonical.canonical_bytes({"b": "2", "a": "1"})
    b = canonical.canonical_bytes({"a": "1", "b": "2"})
    assert a == b == b'{"a":"1","b":"2"}', a


@test("canonical: address identity does not depend on capitalisation")
def _():
    assert canonical.normalize_address(SAFE, "s") == canonical.normalize_address(SAFE.lower(), "s")
    expect_raises(units.UnitError, canonical.normalize_address, "0x1234", "s")


@test("canonical: encoding is byte-stable across runs (cross-language vector)")
def _():
    got = canonical.canonical_bytes(sample_action().to_canonical())
    want = (
        b'{"amount":"10000000000","asset":"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",'
        b'"family":"SUPPLY","market_id":"0x13c42741a359ac4a8aa8287d2be109dcf28344484f'
        b'91185f9a79bd5a805a55ae","on_behalf":"0x08deeda0ba1eb4b6b4b5cc4dd0c4bc689ea37180",'
        b'"schema":"held.action.v1"}'
    )
    assert got == want, f"\n got={got!r}\nwant={want!r}"


# -------------------------------------------------------------- identity -----
@test("identity: operation ID is INDEPENDENT of epoch and runner")
def _():
    base = identity.operation_id(SCOPE, "decision-1", 0)
    e1 = envelope(epoch=1, runner=RUNNER_A)
    e2 = envelope(epoch=99, runner=RUNNER_B)
    assert e1.operation_id == e2.operation_id == base, "consumed identity must survive handover"
    assert e1.signing_hash() != e2.signing_hash(), "authorization must still bind epoch+runner"


@test("identity: operation ID changes with every scope component")
def _():
    base = identity.operation_id(SCOPE, "decision-1", 0)
    variants = [
        identity.operation_id(OperationScope(1, CONTROLLER, SAFE, LINEAGE), "decision-1", 0),
        identity.operation_id(OperationScope(8453, SAFE, SAFE, LINEAGE), "decision-1", 0),
        identity.operation_id(OperationScope(8453, CONTROLLER, CONTROLLER, LINEAGE), "decision-1", 0),
        identity.operation_id(OperationScope(8453, CONTROLLER, SAFE, "0x" + "22" * 32), "decision-1", 0),
        identity.operation_id(SCOPE, "decision-2", 0),
        identity.operation_id(SCOPE, "decision-1", 1),
    ]
    assert len(set(variants)) == len(variants), "scope components collide"
    assert base not in variants, "a scope change must change the ID"


@test("identity: HOLD carries no amount and is never authorized")
def _():
    expect_raises(units.UnitError, SupportedAction, ActionFamily.HOLD, MARKET, USDC, 1, SAFE)
    SupportedAction(ActionFamily.HOLD, MARKET, USDC, 0, SAFE)  # valid
    expect_raises(units.UnitError, SupportedAction, ActionFamily.SUPPLY, MARKET, USDC, 0, SAFE)
    e = envelope()
    expect_raises(
        units.UnitError,
        AuthorizationEnvelope,
        e.scope, e.operation_id, e.source_identity_hash, e.payload_hash,
        ActionFamily.HOLD, 1, 1, RUNNER_A,
    )


@test("identity: payload hash tracks the economic amount")
def _():
    assert sample_action(1).payload_hash() != sample_action(2).payload_hash()


@test("identity: EIP-712 hash matches an INDEPENDENT implementation (eth_account)")
def _():
    from eth_account.messages import encode_typed_data

    e = envelope()
    td = e.to_typed_data()
    signable = encode_typed_data(full_message=td)
    # eth_account exposes the domain separator and struct hash it computed itself.
    assert signable.header == e.domain_separator(), "domain separator disagrees"
    assert signable.body == e.hash_struct(), "hashStruct disagrees"


@test("identity: domain separation across chain and controller")
def _():
    base = envelope().signing_hash()
    other_chain = envelope(scope=OperationScope(1, CONTROLLER, SAFE, LINEAGE)).signing_hash()
    other_ctrl = envelope(scope=OperationScope(8453, RUNNER_B, SAFE, LINEAGE)).signing_hash()
    assert len({base, other_chain, other_ctrl}) == 3, "a replayed domain would be accepted"


# --------------------------------------------------------------- journal -----
def tmpdb(name="j.sqlite"):
    d = tempfile.mkdtemp(prefix="held-p01-")
    return os.path.join(d, name)


@test("journal: same ID + same payload reopens idempotently")
def _():
    p = tmpdb()
    oid, ph = identity.operation_id(SCOPE, "d1", 0), sample_action().payload_hash()
    with J.Journal(p) as j:
        a = j.create_or_reopen(oid, ph, "d1", 0, 1)
        b = j.create_or_reopen(oid, ph, "d1", 0, 1)
        assert a.operation_id == b.operation_id and a.created_at == b.created_at


@test("journal: same ID + DIFFERENT payload is an identity conflict")
def _():
    p = tmpdb()
    oid = identity.operation_id(SCOPE, "d1", 0)
    with J.Journal(p) as j:
        j.create_or_reopen(oid, sample_action(1).payload_hash(), "d1", 0, 1)
        expect_raises(
            identity.IdentityConflict, j.create_or_reopen,
            oid, sample_action(2).payload_hash(), "d1", 0, 1,
        )


@test("journal: concurrent same-ID requests produce exactly one operation")
def _():
    p = tmpdb()
    oid, ph = identity.operation_id(SCOPE, "d1", 0), sample_action().payload_hash()
    J.Journal(p).close()  # create schema first
    errors: list[str] = []
    barrier = threading.Barrier(8)

    def worker():
        try:
            barrier.wait(timeout=10)
            with J.Journal(p) as j:
                j.create_or_reopen(oid, ph, "d1", 0, 1)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}")

    ts = [threading.Thread(target=worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=30)
    assert not errors, errors
    with J.Journal(p) as j:
        n = j._db.execute("SELECT COUNT(*) c FROM operations").fetchone()["c"]
    assert n == 1, f"expected exactly 1 operation row, got {n}"


@test("journal: state survives a crash (no clean shutdown) and reopens")
def _():
    p = tmpdb()
    oid, ph = identity.operation_id(SCOPE, "d1", 0), sample_action().payload_hash()
    j = J.Journal(p)
    j.create_or_reopen(oid, ph, "d1", 0, 1)
    j.transition(oid, J.OperationState.AUTHORIZED)
    # claim_for_dispatch moves the operation to DISPATCHED in the SAME transaction as
    # the attempt row. The old two-step (attempt now, state later) left a crash window
    # in which a restart saw AUTHORIZED + PENDING and started a second submission.
    j.claim_for_dispatch("att-1", oid, canonical.canonical_hash({"e": "1"}), 1,
                         RUNNER_A, "env:HELD_RUNNER_KEY",
                         idempotency_key="0x" + "ee" * 32, request_body="{}",
                         calldata="0xabcd")
    del j  # drop the handle without close(): the commits must already be durable
    with J.Journal(p) as j2:
        op = j2.get(oid)
        assert op is not None and op.state is J.OperationState.DISPATCHED, op
        assert len(j2.attempts_for(oid)) == 1
        assert [o.operation_id for o in j2.unresolved()] == [op.operation_id]


@test("journal: CONFIRMED is terminal - a consumed operation is never re-executed")
def _():
    p = tmpdb()
    oid, ph = identity.operation_id(SCOPE, "d1", 0), sample_action().payload_hash()
    with J.Journal(p) as j:
        j.create_or_reopen(oid, ph, "d1", 0, 1)
        j.transition(oid, J.OperationState.AUTHORIZED)
        j.transition(oid, J.OperationState.DISPATCHED)
        j.transition(oid, J.OperationState.CONFIRMED)
        expect_raises(J.StateTransitionError, j.transition, oid, J.OperationState.AUTHORIZED)
        expect_raises(
            J.StateTransitionError, j.claim_for_dispatch,
            "att-2", oid, canonical.canonical_hash({"e": "2"}), 2, RUNNER_B, "env:K",
            idempotency_key="0x" + "ee" * 32, request_body="{}", calldata="0xabcd",
        )


@test("journal: UNKNOWN stays blocked and cannot be re-authorized")
def _():
    p = tmpdb()
    oid, ph = identity.operation_id(SCOPE, "d1", 0), sample_action().payload_hash()
    with J.Journal(p) as j:
        j.create_or_reopen(oid, ph, "d1", 0, 1)
        j.transition(oid, J.OperationState.AUTHORIZED)
        j.transition(oid, J.OperationState.DISPATCHED)
        j.transition(oid, J.OperationState.UNKNOWN)
        expect_raises(J.StateTransitionError, j.transition, oid, J.OperationState.AUTHORIZED)
        expect_raises(J.RecoveryBlocked, j.assert_recoverable, oid)


@test("journal: reauthorizing a FAILED operation needs a strictly newer epoch")
def _():
    p = tmpdb()
    oid, ph = identity.operation_id(SCOPE, "d1", 0), sample_action().payload_hash()
    with J.Journal(p) as j:
        j.create_or_reopen(oid, ph, "d1", 0, 5)
        j.transition(oid, J.OperationState.AUTHORIZED)
        j.transition(oid, J.OperationState.FAILED)
        expect_raises(J.StateTransitionError, j.transition, oid, J.OperationState.AUTHORIZED, epoch=5)
        op = j.transition(oid, J.OperationState.AUTHORIZED, epoch=6)
        assert op.state is J.OperationState.AUTHORIZED and op.epoch == 6


@test("journal: DISPATCHED with no execution id or tx hash fails closed")
def _():
    p = tmpdb()
    oid, ph = identity.operation_id(SCOPE, "d1", 0), sample_action().payload_hash()
    with J.Journal(p) as j:
        j.create_or_reopen(oid, ph, "d1", 0, 1)
        j.transition(oid, J.OperationState.AUTHORIZED)
        j.claim_for_dispatch("att-1", oid, canonical.canonical_hash({"e": "1"}), 1,
                             RUNNER_A, "env:K", idempotency_key="0x" + "ee" * 32,
                             request_body="{}", calldata="0xabcd")
        j.transition(oid, J.OperationState.DISPATCHED)
        expect_raises(J.RecoveryBlocked, j.assert_recoverable, oid)
        j.record_send_result("att-1", keeperhub_execution_id="kh-123")
        j.assert_recoverable(oid)  # now resolvable


@test("journal: replacement lineage is preserved, not flattened")
def _():
    p = tmpdb()
    oid, ph = identity.operation_id(SCOPE, "d1", 0), sample_action().payload_hash()
    with J.Journal(p) as j:
        j.create_or_reopen(oid, ph, "d1", 0, 1)
        j.transition(oid, J.OperationState.AUTHORIZED)
        h = canonical.canonical_hash({"e": "1"})
        j.claim_for_dispatch("att-1", oid, h, 1, RUNNER_A, "env:K",
                             idempotency_key="0x" + "ee" * 32,
                             request_body="{}", calldata="0xabcd")
        j.record_send_result("att-1", tx_hash="0x" + "ab" * 32, sender_nonce=7)
        j.claim_for_dispatch("att-2", oid, h, 1, RUNNER_A, "env:K",
                             idempotency_key="0x" + "ff" * 32, request_body="{}",
                             calldata="0xabcd",
                                     replaces_attempt_id="att-1")
        rows = j.attempts_for(oid)
        assert len(rows) == 2 and rows[1]["replaces_attempt_id"] == "att-1"
        assert rows[0]["sender_nonce"] == 7, "attempt evidence must survive replacement"


@test("journal: refuses to persist anything shaped like key material")
def _():
    p = tmpdb()
    oid, ph = identity.operation_id(SCOPE, "d1", 0), sample_action().payload_hash()
    with J.Journal(p) as j:
        j.create_or_reopen(oid, ph, "d1", 0, 1)
        j.transition(oid, J.OperationState.AUTHORIZED)
        leaked = "0x" + "ac" * 32  # exactly the shape of a private key
        expect_raises(
            J.JournalError, j.claim_for_dispatch,
            "att-x", oid, canonical.canonical_hash({"e": "1"}), 1, RUNNER_A, leaked,
            idempotency_key="0x" + "ee" * 32, request_body="{}", calldata="0xabcd",
        )


@test("journal: tombstone outlives a purged operation")
def _():
    p = tmpdb()
    oid, ph = identity.operation_id(SCOPE, "d1", 0), sample_action().payload_hash()
    with J.Journal(p) as j:
        j.create_or_reopen(oid, ph, "d1", 0, 1)
        j.transition(oid, J.OperationState.AUTHORIZED)
        j.transition(oid, J.OperationState.DISPATCHED)
        j.transition(oid, J.OperationState.CONFIRMED)
        j.purge_operation_keep_tombstone(oid)
        assert j.get(oid) is None
        t = j.tombstone(oid)
        assert t and t["final_state"] == "CONFIRMED" and t["payload_hash"] == J.hex32(ph)
        # The consumed-ID guarantee still holds after the body is gone.
        expect_raises(
            identity.IdentityConflict, j.create_or_reopen,
            oid, sample_action(999).payload_hash(), "d1", 0, 1,
        )


@test("journal: an unidentified database is refused rather than used")
def _():
    p = tmpdb()
    with J.Journal(p) as j:
        j._db.execute("DELETE FROM meta")
    expect_raises(J.RecoveryBlocked, J.Journal, p)


# --------------------------------------------------------------- results -----
def _prepared(p):
    oid = J.hex32(identity.operation_id(SCOPE, "d1", 0))
    with J.Journal(p) as j:
        j.create_or_reopen(oid, sample_action().payload_hash(), "d1", 0, 1)
        j.transition(oid, J.OperationState.AUTHORIZED)
        j.transition(oid, J.OperationState.DISPATCHED)
        j.transition(oid, J.OperationState.CONFIRMED)
    return oid


@test("results: at-least-once delivery applies the consumer state exactly once")
def _():
    p = tmpdb()
    oid = _prepared(p)
    rh = "0x" + "cd" * 32
    c = R.ModeledNativeConsumer()
    with J.Journal(p) as j:
        assert R.deliver(j, oid, rh, "payload", c) is R.DeliveryOutcome.APPLIED
        for _ in range(4):
            assert R.deliver(j, oid, rh, "payload", c) is R.DeliveryOutcome.DUPLICATE
        n = j._db.execute("SELECT COUNT(*) c FROM modeled_consumer_state").fetchone()["c"]
    assert n == 1 and c.applications == 1, f"rows={n} applications={c.applications}"


@test("results: ack-before-restart - redelivery after reopen is a no-op")
def _():
    p = tmpdb()
    oid = _prepared(p)
    rh = "0x" + "cd" * 32
    c1 = R.ModeledNativeConsumer()
    with J.Journal(p) as j:
        assert R.deliver(j, oid, rh, "payload", c1) is R.DeliveryOutcome.APPLIED
    # process restart: brand-new journal handle and a brand-new consumer object with
    # no in-memory memory of having applied anything.
    c2 = R.ModeledNativeConsumer()
    with J.Journal(p) as j2:
        assert R.deliver(j2, oid, rh, "payload", c2) is R.DeliveryOutcome.DUPLICATE
        n = j2._db.execute("SELECT COUNT(*) c FROM modeled_consumer_state").fetchone()["c"]
    assert n == 1 and c2.applications == 0, f"rows={n} applications={c2.applications}"


@test("results: callback-before-ack - a crash mid-apply leaves NO partial state")
def _():
    p = tmpdb()
    oid = _prepared(p)
    rh = "0x" + "cd" * 32

    class CrashingConsumer(R.ModeledNativeConsumer):
        def apply(self, conn, operation_id, result_hash, payload):
            super().apply(conn, operation_id, result_hash, payload)
            raise RuntimeError("crash after consumer state update, before ack")

    with J.Journal(p) as j:
        expect_raises(RuntimeError, R.deliver, j, oid, rh, "payload", CrashingConsumer())
        # The consumer's write and the ack were one transaction, so BOTH rolled back.
        assert R.delivery_status(j, oid) is None, "a torn delivery left a results row"
        tables = [r[0] for r in j._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "modeled_consumer_state" in tables:
            n = j._db.execute("SELECT COUNT(*) c FROM modeled_consumer_state").fetchone()["c"]
            assert n == 0, f"consumer state survived a rolled-back delivery: {n} rows"
        # Retry on the at-least-once channel now applies exactly once.
        good = R.ModeledNativeConsumer()
        assert R.deliver(j, oid, rh, "payload", good) is R.DeliveryOutcome.APPLIED
        n = j._db.execute("SELECT COUNT(*) c FROM modeled_consumer_state").fetchone()["c"]
        assert n == 1, n


@test("results: a different result after acknowledgement is a conflict, not an overwrite")
def _():
    p = tmpdb()
    oid = _prepared(p)
    c = R.ModeledNativeConsumer()
    with J.Journal(p) as j:
        R.deliver(j, oid, "0x" + "cd" * 32, "payload", c)
        expect_raises(R.ResultConflict, R.deliver, j, oid, "0x" + "ef" * 32, "other", c)
        assert c.applications == 1


@test("results: unacknowledged deliveries are retryable work, not silent losses")
def _():
    p = tmpdb()
    oid = _prepared(p)
    with J.Journal(p) as j:
        assert R.unacknowledged(j) == []
        j._db.execute(
            "INSERT INTO results(operation_id,result_hash,delivered_at) VALUES(?,?,?)",
            (oid, "0x" + "cd" * 32, 1),
        )
        assert R.unacknowledged(j) == [oid]


def main() -> int:
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"check-phase-01: FAIL ({len(FAILED)} of {len(PASSED) + len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} P01 contract tests held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
