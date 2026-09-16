"""Unsigned base units. No floats, no sentinels, no guessed defaults.

V4 §5: "All values use unsigned integer token base units, counts or chain seconds.
No float arithmetic, guessed defaults or unlimited sentinel."

Two rules carry most of the weight here:

  * `bool` is NOT an acceptable integer. In Python `isinstance(True, int)` is True,
    so a policy field silently accepting `True` as 1 is a real hazard, not a
    theoretical one. It is rejected explicitly.
  * There is no "unlimited". A caller who wants no cap must say so by supplying the
    explicit finite maximum for the width. Zero is a legitimate value meaning the
    action lane is disabled (V4 §5), so zero is never treated as "unset".
"""
from __future__ import annotations

UINT128_MAX = (1 << 128) - 1
UINT64_MAX = (1 << 64) - 1
UINT256_MAX = (1 << 256) - 1


class UnitError(ValueError):
    """An amount, count or timestamp that is not a valid unsigned base-unit value."""


def _reject_non_integer(value: object, field: str) -> None:
    if isinstance(value, bool):
        # Deliberate: bool is a subclass of int and would otherwise pass silently.
        raise UnitError(f"{field}: bool is not an unsigned integer (got {value!r})")
    if isinstance(value, float):
        raise UnitError(f"{field}: float is never permitted, use base units (got {value!r})")
    if not isinstance(value, int):
        raise UnitError(f"{field}: must be int, got {type(value).__name__}")


def uint(value: object, field: str, *, maximum: int = UINT256_MAX) -> int:
    """Validate an unsigned integer that fits the declared width."""
    _reject_non_integer(value, field)
    assert isinstance(value, int)
    if value < 0:
        raise UnitError(f"{field}: must be >= 0, got {value}")
    if value > maximum:
        raise UnitError(f"{field}: {value} exceeds maximum {maximum}")
    return value


def uint128(value: object, field: str) -> int:
    return uint(value, field, maximum=UINT128_MAX)


def uint64(value: object, field: str) -> int:
    return uint(value, field, maximum=UINT64_MAX)


def parse_decimal_string(text: object, field: str, *, maximum: int = UINT256_MAX) -> int:
    """Decode the canonical wire form of an amount.

    Amounts travel as decimal STRINGS, never JSON numbers: a uint256 does not
    survive a round trip through an IEEE-754 double, and any consumer in a language
    whose default number type is a double would corrupt it silently. See canonical.py.
    """
    if not isinstance(text, str):
        raise UnitError(f"{field}: amounts travel as decimal strings, got {type(text).__name__}")
    if text == "" or not text.isdigit():
        # isdigit() rejects "+1", "-1", " 1", "1_0", "0x10" and unicode oddities.
        raise UnitError(f"{field}: not a canonical decimal string: {text!r}")
    if len(text) > 1 and text[0] == "0":
        raise UnitError(f"{field}: leading zeros are not canonical: {text!r}")
    return uint(int(text), field, maximum=maximum)


def to_decimal_string(value: int, field: str, *, maximum: int = UINT256_MAX) -> str:
    return str(uint(value, field, maximum=maximum))
