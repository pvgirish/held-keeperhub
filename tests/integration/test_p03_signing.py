"""P03: runner authorization signing from a key reference.

LOCAL. These tests establish that Held produces a signature the pinned controller would
accept, and that it refuses locally in the cases where an on-chain rejection would have
cost a KeeperHub execution. They do NOT establish the hosted route, which is blocked by
L10 and is not simulated here.

The anvil deterministic account used below is a well-known public test key. It is not
custody, and it is supplied through the same env-var reference mechanism production
would use, so the reference path itself is what is under test.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "packages", "core"))
sys.path.insert(0, os.path.join(ROOT, "adapter"))

from eth_account import Account  # noqa: E402

from held_adapter.signing.runner_signer import (  # noqa: E402
    KeyReference,
    KeyReferenceError,
    RunnerSigner,
    SignerMismatch,
    SigningError,
    signer_from_env,
)
from held_core.identity import ActionFamily, AuthorizationEnvelope, OperationScope  # noqa: E402
from held_core.journal import assert_no_secrets  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

# anvil account #3 -- public, well-known, local-fork only. Never real custody.
RUNNER_KEY = "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6"
RUNNER = "0x90F79bf6EB2c4f870365E785982E1f101E93b906"
OTHER_KEY = "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a"
OTHER = "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65"

SAFE = "0x08deEDA0Ba1eb4B6B4b5cc4DD0c4BC689EA37180"
CONTROLLER = "0x3875311cc0d4017a033893a9653a0725378aca1c"
SCOPE = OperationScope(8453, CONTROLLER, SAFE, "0x" + "11" * 32)


def test(name):
    def deco(fn):
        try:
            fn()
            PASSED.append(name)
            print(f"ok    {name}")
        except Exception:
            import traceback
            FAILED.append((name, traceback.format_exc()))
            print(f"FAIL  {name}")
        return fn
    return deco


def envelope(runner: str = RUNNER, epoch: int = 1) -> AuthorizationEnvelope:
    return AuthorizationEnvelope(
        scope=SCOPE,
        operation_id=bytes.fromhex("aa" * 32),
        source_identity_hash=bytes.fromhex("bb" * 32),
        payload_hash=bytes.fromhex("cc" * 32),
        action_family=ActionFamily.SUPPLY,
        epoch=epoch,
        policy_version=1,
        runner=runner,
    )


def expect(exc_type, fn, *a, **k) -> str:
    try:
        fn(*a, **k)
    except exc_type as e:
        return str(e)
    raise AssertionError(f"expected {exc_type.__name__}, nothing raised")


def with_key(env_name: str, value: str):
    os.environ[env_name] = value


# ----------------------------------------------------------------- references --
@test("a key reference names a location and never carries the material")
def _():
    ref = KeyReference("env:HELD_RUNNER_KEY")
    assert ref.scheme == "env" and ref.locator == "HELD_RUNNER_KEY"
    # The reference is what reaches durable storage, so the journal's own secret guard
    # must accept it. That guard is the thing that would reject a leaked key.
    assert_no_secrets(ref.ref, "signer_ref")


@test("a key-shaped 'reference' is refused outright")
def _():
    msg = expect(KeyReferenceError, KeyReference, RUNNER_KEY)
    assert "key material" in msg, msg
    # also when disguised behind a valid-looking scheme
    msg2 = expect(KeyReferenceError, KeyReference, f"env:{RUNNER_KEY[2:]}")
    assert "key material" in msg2, msg2


@test("an unknown or malformed reference scheme is refused")
def _():
    assert "scheme" in expect(KeyReferenceError, KeyReference, "kms:arn/whatever")
    assert "scheme" in expect(KeyReferenceError, KeyReference, "HELD_RUNNER_KEY")


@test("a reference to an unset variable fails loudly, not silently")
def _():
    os.environ.pop("HELD_ABSENT_KEY", None)
    s = RunnerSigner("env:HELD_ABSENT_KEY", RUNNER)
    assert "unset or empty" in expect(KeyReferenceError, s.address)


@test("neither the signer nor its reference leaks material through repr")
def _():
    with_key("HELD_RUNNER_KEY", RUNNER_KEY)
    s = signer_from_env(RUNNER)
    for text in (repr(s), repr(s.key_ref), str(s)):
        assert RUNNER_KEY not in text and RUNNER_KEY[2:] not in text, text
    assert "HELD_RUNNER_KEY" in repr(s)


# --------------------------------------------------------------------- signing --
@test("signs an envelope and recovers the configured runner")
def _():
    with_key("HELD_RUNNER_KEY", RUNNER_KEY)
    s = signer_from_env(RUNNER)
    assert s.address() == RUNNER.lower()
    auth = s.sign(envelope())
    assert len(auth.signature) == 65
    assert auth.runner == RUNNER.lower()
    assert auth.signer_ref == "env:HELD_RUNNER_KEY"
    recovered = Account._recover_hash(auth.signing_hash, signature=auth.signature)
    assert recovered.lower() == RUNNER.lower()


@test("the hand-rolled EIP-712 digest agrees with eth_account's independent one")
def _():
    from eth_account.messages import encode_typed_data
    from eth_utils import keccak

    env = envelope()
    independent = encode_typed_data(full_message=env.to_typed_data())
    digest = keccak(b"\x19" + independent.version + independent.header + independent.body)
    assert digest == env.signing_hash(), (
        "held_core's encoding and eth_account's disagree; every signature Held produces "
        "would be unverifiable by the controller"
    )


@test("the produced signature is low-s, so the controller cannot reject it as malleable")
def _():
    with_key("HELD_RUNNER_KEY", RUNNER_KEY)
    s = signer_from_env(RUNNER)
    half_n = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0
    for epoch in range(1, 12):
        auth = s.sign(envelope(epoch=epoch))
        assert int.from_bytes(auth.signature[32:64], "big") <= half_n
        assert auth.signature[64] in (27, 28)


@test("a different epoch produces a different signature over a different digest")
def _():
    with_key("HELD_RUNNER_KEY", RUNNER_KEY)
    s = signer_from_env(RUNNER)
    a, b = s.sign(envelope(epoch=1)), s.sign(envelope(epoch=2))
    assert a.signing_hash != b.signing_hash, "epoch is bound into the signed digest"
    assert a.signature != b.signature


@test("signing is deterministic for the same envelope (RFC 6979)")
def _():
    with_key("HELD_RUNNER_KEY", RUNNER_KEY)
    s = signer_from_env(RUNNER)
    assert s.sign(envelope()).signature == s.sign(envelope()).signature


# ------------------------------------------------------------------- refusals --
@test("a key that is not the envelope's runner is refused LOCALLY, before any send")
def _():
    # This is the fault worth catching here: the signature would be well-formed, the
    # journal would record a sent attempt, and the controller would reject it on chain
    # after an execution had been spent.
    with_key("HELD_OTHER_KEY", OTHER_KEY)
    s = RunnerSigner("env:HELD_OTHER_KEY", RUNNER)
    msg = expect(SignerMismatch, s.sign, envelope(runner=RUNNER))
    assert "recovers to" in msg and OTHER.lower() in msg.lower(), msg


@test("an envelope naming a different runner than the signer is refused")
def _():
    with_key("HELD_RUNNER_KEY", RUNNER_KEY)
    s = signer_from_env(RUNNER)
    msg = expect(SignerMismatch, s.sign, envelope(runner=OTHER))
    assert "configured for" in msg, msg


@test("a HOLD can never be signed, because it authorizes nothing")
def _():
    from held_core.units import UnitError
    msg = expect(UnitError, AuthorizationEnvelope,
                 scope=SCOPE, operation_id=bytes(32), source_identity_hash=bytes(32),
                 payload_hash=bytes(32), action_family=ActionFamily.HOLD,
                 epoch=1, policy_version=1, runner=RUNNER)
    assert "HOLD" in msg, msg


@test("a non-hex environment value is refused rather than silently mis-signed")
def _():
    with_key("HELD_BAD_KEY", "not-a-key")
    s = RunnerSigner("env:HELD_BAD_KEY", RUNNER)
    assert "hex private key" in expect(KeyReferenceError, s.sign, envelope())


# ------------------------------------------------------------------- keystore --
@test("an encrypted keystore reference signs, and needs its passphrase from env")
def _():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "runner.json")
        with open(path, "w") as fh:
            json.dump(Account.encrypt(RUNNER_KEY, "correct horse"), fh)

        s = RunnerSigner(f"keystore:{path}", RUNNER)
        os.environ.pop("HELD_KEYSTORE_PASSPHRASE", None)
        assert "passphrase" in expect(KeyReferenceError, s.sign, envelope())

        os.environ["HELD_KEYSTORE_PASSPHRASE"] = "correct horse"
        auth = s.sign(envelope())
        assert auth.runner == RUNNER.lower()
        # The path is a reference, so it is safe to persist; the passphrase never was
        # an argument and never reaches the record.
        assert_no_secrets(auth.signer_ref, "signer_ref")
        assert "correct horse" not in json.dumps(auth.to_record())
        del os.environ["HELD_KEYSTORE_PASSPHRASE"]


@test("a missing keystore file fails loudly")
def _():
    s = RunnerSigner("keystore:/nonexistent/runner.json", RUNNER)
    assert "not found" in expect(KeyReferenceError, s.sign, envelope())


# --------------------------------------------------------------------- record --
@test("the persisted record carries the reference and no key material")
def _():
    with_key("HELD_RUNNER_KEY", RUNNER_KEY)
    auth = signer_from_env(RUNNER).sign(envelope())
    blob = json.dumps(auth.to_record())
    assert RUNNER_KEY not in blob and RUNNER_KEY[2:] not in blob
    assert "env:HELD_RUNNER_KEY" in blob
    assert_no_secrets(auth.to_record()["signer_ref"], "signer_ref")


# ------------------------------------------------- cross-language, both directions --
@test("reproduces the digest AND the signature the deployed controller published")
def _():
    """The reverse direction of the actionHash vector.

    The envelope digest commits to the domain separator, which contains the controller's
    address, so Python cannot precompute it -- the fork publishes what it built and this
    reproduces it from held_core alone. Agreement here is what makes "the adapter signs
    what the controller verifies" a cross-language claim rather than Python agreeing
    with Python.
    """
    path = os.path.join(ROOT, "fixtures", "generated", "signing-vector.json")
    assert os.path.exists(path), (
        "fixtures/generated/signing-vector.json is missing. It is written by the fork "
        "suite (make check-phase-02); this check is not allowed to silently pass without it."
    )
    with open(path) as fh:
        v = json.load(fh)

    scope = OperationScope(v["chainId"], v["controller"], v["safe"], v["lineage"])
    env = AuthorizationEnvelope(
        scope=scope,
        operation_id=bytes.fromhex(v["operationId"][2:]),
        source_identity_hash=bytes.fromhex(v["sourceIdentityHash"][2:]),
        payload_hash=bytes.fromhex(v["payloadHash"][2:]),
        action_family=ActionFamily(v["actionFamily"]),
        epoch=v["epoch"],
        policy_version=v["policyVersion"],
        runner=v["runner"],
    )

    published = bytes.fromhex(v["signingHash"][2:])
    assert env.signing_hash() == published, (
        f"held_core computed {env.signing_hash().hex()} but the deployed controller "
        f"computed {v['signingHash']}: the adapter would sign something the controller "
        "does not verify"
    )

    # Same key, independently re-signed. Both sides use deterministic ECDSA, so full
    # byte equality is the strongest available statement: identical digest AND identical
    # signature, produced by two implementations that share no code.
    with_key("HELD_VECTOR_KEY", OTHER_KEY)
    s = RunnerSigner("env:HELD_VECTOR_KEY", v["runner"])
    auth = s.sign(env)
    assert "0x" + auth.signature.hex() == v["signature"], (
        f"python produced {'0x' + auth.signature.hex()}, the fork published {v['signature']}"
    )
    # And the controller's own recovery target is what we claim to be.
    assert Account._recover_hash(published, signature=auth.signature).lower() == v["runner"].lower()


def main() -> int:
    for v in ("HELD_RUNNER_KEY", "HELD_OTHER_KEY", "HELD_BAD_KEY", "HELD_KEYSTORE_PASSPHRASE",
              "HELD_VECTOR_KEY"):
        os.environ.pop(v, None)
    print("---")
    if FAILED:
        for name, tb in FAILED:
            print(f"\n=== {name} ===\n{tb}")
        print(f"P03 signing: FAIL ({len(FAILED)}/{len(PASSED)+len(FAILED)})")
        return 1
    print(f"all {len(PASSED)} P03 signing tests held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
