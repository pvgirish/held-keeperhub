"""Runner authorization signing, from a key REFERENCE rather than key material.

V4 §4: the runner authorizes one operation under one epoch, and the controller recovers
that signature on chain. Two things follow, and both are enforced here rather than left
to convention.

**A reference, never the material.** Nothing in this module accepts, returns, stores or
reprs a private key. A `KeyReference` is a string like `env:HELD_RUNNER_KEY` or
`keystore:/path/to/v3.json` that *names where the key lives*; it is the only form that
reaches the journal, a log line or an evidence file. The material is resolved inside
`sign()`, used, and dropped. A reference that is itself key-shaped is refused outright,
because the whole point is defeated if someone passes `0x<64 hex>` as a "reference".

**A signature that will not verify is a defect, not a later surprise.** `sign()` recovers
the signer from its own output and requires it to equal `envelope.runner`. Signing with
the wrong key otherwise produces a well-formed attempt that the journal records as sent
and the controller rejects on chain -- consuming a KeeperHub execution and leaving an
operation whose outcome has to be reconciled, for a fault that was knowable locally.

The hand-rolled `signing_hash()` in held_core.identity is also cross-checked against
eth_account's independent EIP-712 implementation on every signature, not only in tests.
The controller recovers over the hand-rolled encoding; if the two ever diverge, every
signature Held produces is unverifiable, so the check belongs on the live path.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak  # noqa: F401  (re-exported shape parity with held_core)

from held_core.canonical import hex32, normalize_address
from held_core.identity import AuthorizationEnvelope

# A reference must NAME a location. These are the forms that do.
SCHEME_ENV = "env"
SCHEME_KEYSTORE = "keystore"
KNOWN_SCHEMES = (SCHEME_ENV, SCHEME_KEYSTORE)

# 32 bytes of hex, with or without the prefix, is exactly the shape of a private key.
_KEY_SHAPED = re.compile(r"(?:^|[^0-9a-fA-F])(?:0x)?[0-9a-fA-F]{64}(?:$|[^0-9a-fA-F])")


class SigningError(Exception):
    """The signature could not be produced, or could not be trusted once produced."""


class SignerMismatch(SigningError):
    """The key behind the reference is not the runner the envelope names."""


class KeyReferenceError(SigningError):
    """The reference is malformed, key-shaped, or points at nothing."""


def _reject_key_shaped(value: str, field: str) -> str:
    if _KEY_SHAPED.search(value):
        raise KeyReferenceError(
            f"{field}: this looks like key material, not a reference. Pass "
            f"'env:NAME' or 'keystore:/path' so that only the NAME is ever persisted."
        )
    return value


@dataclass(frozen=True)
class KeyReference:
    """Where a runner key lives. Never what it is.

    `ref` is safe to journal, log and put in evidence. It is the value
    `held_core.journal.assert_no_secrets` is designed to accept.
    """

    ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.ref, str):
            raise KeyReferenceError(
                f"key reference must be a string, got {type(self.ref).__name__}"
            )
        # Key-shape FIRST. A bare private key has no scheme either, and reporting that
        # as a formatting problem sends the reader to fix the wrong thing.
        _reject_key_shaped(self.ref, "key reference")
        if ":" not in self.ref:
            raise KeyReferenceError(
                f"key reference must be '<scheme>:<locator>' with scheme in "
                f"{list(KNOWN_SCHEMES)}; got {self.ref!r}"
            )
        scheme = self.ref.split(":", 1)[0]
        if scheme not in KNOWN_SCHEMES:
            raise KeyReferenceError(
                f"unknown key reference scheme {scheme!r}; known: {list(KNOWN_SCHEMES)}"
            )

    @property
    def scheme(self) -> str:
        return self.ref.split(":", 1)[0]

    @property
    def locator(self) -> str:
        return self.ref.split(":", 1)[1]

    def __repr__(self) -> str:  # keeps the shape explicit in tracebacks
        return f"KeyReference({self.ref!r})"

    def _resolve(self, passphrase_env: str | None = None) -> bytes:
        """Return the key material transiently. Callers must not retain it.

        Deliberately private and deliberately not cached: a resolved key held on an
        object outlives the operation it was needed for and shows up in any repr,
        pickle or crash dump of that object.
        """
        if self.scheme == SCHEME_ENV:
            raw = os.environ.get(self.locator)
            if not raw:
                raise KeyReferenceError(
                    f"environment variable {self.locator!r} is unset or empty"
                )
            raw = raw.strip()
            try:
                return bytes.fromhex(raw[2:] if raw.startswith("0x") else raw)
            except ValueError as exc:
                raise KeyReferenceError(
                    f"{self.locator!r} does not contain a hex private key"
                ) from exc

        # keystore: an encrypted V3 file. The passphrase comes from its own env var,
        # so neither the key nor the passphrase is ever an argument that could be
        # captured in a shell history, a traceback frame or a config file.
        if not os.path.exists(self.locator):
            raise KeyReferenceError(f"keystore file not found: {self.locator}")
        env_name = passphrase_env or "HELD_KEYSTORE_PASSPHRASE"
        passphrase = os.environ.get(env_name)
        if not passphrase:
            raise KeyReferenceError(
                f"keystore {self.locator} needs a passphrase in ${env_name}"
            )
        import json

        with open(self.locator) as fh:
            return Account.decrypt(json.load(fh), passphrase)


@dataclass(frozen=True)
class SignedAuthorization:
    """A signature plus exactly the provenance that is safe to persist."""

    envelope: AuthorizationEnvelope
    signature: bytes
    signer_ref: str  # the REFERENCE; never the key
    runner: str
    signing_hash: bytes

    def to_record(self) -> dict[str, object]:
        return {
            "operation_id": hex32(self.envelope.operation_id),
            "signing_hash": hex32(self.signing_hash),
            "signature": "0x" + self.signature.hex(),
            "signer_ref": self.signer_ref,
            "runner": self.runner,
            "epoch": str(self.envelope.epoch),
        }


class RunnerSigner:
    """Signs authorization envelopes for ONE runner identity.

    `expected_runner` is supplied separately from the key on purpose: it is the address
    the customer's policy authorized, and the constructor's job is to detect a key that
    does not match it before anything is spent.
    """

    def __init__(
        self,
        key_ref: KeyReference | str,
        expected_runner: str,
        *,
        passphrase_env: str | None = None,
    ) -> None:
        self.key_ref = key_ref if isinstance(key_ref, KeyReference) else KeyReference(key_ref)
        self.expected_runner = normalize_address(expected_runner, "expected_runner")
        self._passphrase_env = passphrase_env

    def __repr__(self) -> str:
        return f"RunnerSigner(ref={self.key_ref.ref!r}, runner={self.expected_runner})"

    @property
    def signer_ref(self) -> str:
        return self.key_ref.ref

    def address(self) -> str:
        """The address behind the reference, resolved transiently."""
        material = self.key_ref._resolve(self._passphrase_env)
        try:
            return normalize_address(Account.from_key(material).address, "signer")
        finally:
            del material

    def sign(self, envelope: AuthorizationEnvelope) -> SignedAuthorization:
        if normalize_address(envelope.runner, "envelope.runner") != self.expected_runner:
            raise SignerMismatch(
                f"envelope names runner {envelope.runner}, this signer is configured for "
                f"{self.expected_runner}"
            )

        digest = envelope.signing_hash()

        # Cross-check the hand-rolled encoding against an independent EIP-712
        # implementation on the live path. The controller recovers over the hand-rolled
        # form, so a divergence makes every Held signature unverifiable.
        independent = _typed_digest(encode_typed_data(full_message=envelope.to_typed_data()))
        if independent != digest:
            raise SigningError(
                "EIP-712 encodings disagree: held_core.identity.signing_hash() produced "
                f"{hex32(digest)} and eth_account produced {hex32(independent)} for the "
                "same envelope"
            )

        material = self.key_ref._resolve(self._passphrase_env)
        try:
            # "unsafe" names the fact that the digest is signed without re-deriving it
            # from a message. That is exactly what EIP-712 needs, and the digest above
            # was just cross-checked against an independent implementation.
            signed = Account.unsafe_sign_hash(digest, material)
        finally:
            del material

        signature = bytes(signed.signature)
        if len(signature) != 65:
            raise SigningError(f"expected a 65-byte signature, got {len(signature)}")

        # Recover from our own output. A signature the controller will reject is a local
        # defect; discovering it on chain costs an execution and leaves an operation to
        # reconcile.
        recovered = normalize_address(
            Account._recover_hash(digest, signature=signature), "recovered"
        )
        if recovered != self.expected_runner:
            raise SignerMismatch(
                f"signature recovers to {recovered}, not the configured runner "
                f"{self.expected_runner}; the key behind {self.key_ref.ref} is wrong"
            )

        # The controller rejects a malleable signature, so producing one is a defect too.
        s = int.from_bytes(signature[32:64], "big")
        if s > _SECP256K1_HALF_N:
            raise SigningError("signature is not low-s; the controller rejects malleable signatures")
        if signature[64] not in (27, 28):
            raise SigningError(f"unexpected v value {signature[64]}")

        return SignedAuthorization(
            envelope=envelope,
            signature=signature,
            signer_ref=self.key_ref.ref,
            runner=self.expected_runner,
            signing_hash=digest,
        )


_SECP256K1_HALF_N = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0


def _typed_digest(signable) -> bytes:
    """The EIP-712 digest eth_account would sign, rebuilt from its SignableMessage."""
    return keccak(b"\x19" + signable.version + signable.header + signable.body)


def signer_from_env(
    runner: str, env_var: str = "HELD_RUNNER_KEY", **kw: object
) -> RunnerSigner:
    """Convenience for local fork work. The env var NAME is what gets recorded."""
    return RunnerSigner(KeyReference(f"{SCHEME_ENV}:{env_var}"), runner, **kw)  # type: ignore[arg-type]
