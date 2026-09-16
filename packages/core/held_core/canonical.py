"""Canonical serialization: one byte string per logical value, in any language.

Every hash in Held is taken over these bytes, so two implementations that disagree
here disagree about operation identity. The rules are deliberately boring and chosen
so a JavaScript, Go or Rust consumer can reproduce them without a library:

  1. UTF-8, no BOM.
  2. Object keys sorted by Unicode code point.
  3. No insignificant whitespace: separators are exactly ',' and ':'.
  4. **Integers are decimal strings, never JSON numbers.** A uint256 does not survive
     an IEEE-754 double. Any language whose default number type is a double would
     round-trip `"12345678901234567890123"` into something else and produce a
     different operation ID, silently.
  5. No floats anywhere. Not rejected by convention — rejected by the encoder.
  6. Schema version is part of every hashed object, so a type change cannot collide
     with the old type's identity.

`\\uXXXX` escaping is disabled (`ensure_ascii=False`) so the bytes are the natural
UTF-8 encoding rather than Python's ASCII-safe variant, which other languages do not
produce by default.
"""
from __future__ import annotations

import json
from typing import Any

from eth_utils import keccak

from .units import UnitError


def _check(value: Any, path: str) -> None:
    if isinstance(value, float):
        raise UnitError(f"{path}: float is not canonically encodable; use base units as strings")
    if isinstance(value, bool):
        return  # bools are fine as JSON booleans; they are just never integers
    if isinstance(value, int):
        raise UnitError(
            f"{path}: raw int {value} is not canonically encodable. "
            "Encode amounts, counts and timestamps as decimal strings."
        )
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise UnitError(f"{path}: object keys must be strings, got {type(k).__name__}")
            _check(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _check(v, f"{path}[{i}]")
    elif value is None or isinstance(value, str):
        return
    else:
        raise UnitError(f"{path}: {type(value).__name__} is not canonically encodable")


def canonical_bytes(obj: Any) -> bytes:
    """The one true encoding of `obj`. Rejects anything ambiguous across languages."""
    _check(obj, "$")
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(obj: Any) -> bytes:
    """keccak256 over the canonical encoding. 32 bytes."""
    return keccak(canonical_bytes(obj))


def hex32(b: bytes) -> str:
    if len(b) != 32:
        raise ValueError(f"expected 32 bytes, got {len(b)}")
    return "0x" + b.hex()


def normalize_address(addr: str, field: str) -> str:
    """Lower-case 0x-prefixed 20-byte address.

    Lower case, not EIP-55 checksum: the checksum form embeds the *case* of the hex
    digits, so two spellings of the same address hash differently. Identity must not
    depend on how a caller happened to capitalise an address.
    """
    if not isinstance(addr, str):
        raise UnitError(f"{field}: address must be a string, got {type(addr).__name__}")
    if not addr.startswith("0x") or len(addr) != 42:
        raise UnitError(f"{field}: not a 0x-prefixed 20-byte address: {addr!r}")
    body = addr[2:]
    try:
        int(body, 16)
    except ValueError:
        raise UnitError(f"{field}: address is not hex: {addr!r}") from None
    return "0x" + body.lower()


def normalize_hash(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise UnitError(f"{field}: hash must be a string, got {type(value).__name__}")
    if not value.startswith("0x") or len(value) != 66:
        raise UnitError(f"{field}: not a 0x-prefixed 32-byte hash: {value!r}")
    try:
        int(value[2:], 16)
    except ValueError:
        raise UnitError(f"{field}: hash is not hex: {value!r}") from None
    return "0x" + value[2:].lower()
