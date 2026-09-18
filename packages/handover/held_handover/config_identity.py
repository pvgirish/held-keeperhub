"""The native configuration identity runner B must be continuing under.

An earlier version derived a digest from the SDK revision, the chain, the Safe and the price
mode, and called it "the native configuration digest". It bound less than that name claimed:
two different Morpho markets on the same Safe produced the SAME digest, so a replacement
could have continued under a different market and the digest would have agreed.

## What the identity must cover

Everything that changes what the producer COMPILES or what the controller will ACCEPT. If a
field can differ between two installations that a replacement must not be swapped between,
it belongs here:

  producer   the pinned Almanak SDK revision, and the strategy configuration digest
  chain      chain id
  custody    Safe, controller, lineage
  market     Morpho, loan token, collateral, oracle, IRM, LLTV
  profile    the supported execution profile (which action families are admissible)
  pricing    price mode, ONLY because it materially changes what the compiler emits

Price mode is included deliberately: `testing-only` substitutes a fixed USDC price into the
compiler, so a bundle produced under it is not the bundle production would have produced.

## Canonical serialization

Sorted `key=value` pairs joined by `|`, UTF-8, keccak256. Sorted so field order cannot
change the digest; explicit `key=` so two fields cannot merge into one ambiguous string.

The METADATA is stored beside the digest, not only the digest, so another reviewer can
recompute it rather than take it on trust.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Any

SCHEMA = "held.native-config-identity.v1"


class ConfigIdentityError(Exception):
    """A configuration identity could not be formed truthfully."""


REQUIRED = (
    "sdkRevision", "strategyConfigDigest", "chainId", "safe", "controller", "lineage",
    "morpho", "loanToken", "collateralToken", "oracle", "irm", "lltv",
    "executionProfile", "priceMode",
)


@dataclass
class NativeConfigIdentity:
    """The fields, the canonical string, and the digest over it."""

    fields: dict[str, Any] = field(default_factory=dict)

    def canonical(self) -> str:
        missing = [k for k in REQUIRED if k not in self.fields or self.fields[k] in (None, "")]
        if missing:
            raise ConfigIdentityError(
                f"the configuration identity is missing {missing}. A digest over a partial "
                "identity binds less than its name claims, which is the defect this "
                "replaces.")
        parts = []
        for k in sorted(self.fields):
            v = self.fields[k]
            v = v.lower() if isinstance(v, str) and v.startswith("0x") else v
            parts.append(f"{k}={v}")
        return "|".join(parts)

    def digest(self) -> str:
        from eth_utils import keccak
        return "0x" + keccak(self.canonical().encode()).hex()

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "digest": self.digest(),
                "fields": dict(sorted(self.fields.items())),
                "canonical": self.canonical(),
                "_reproduce": "sorted key=value pairs joined by '|', UTF-8, keccak256. The "
                              "fields are stored so a reviewer can recompute the digest "
                              "rather than trust it."}


def sdk_revision(path: str = "~/src/sdk") -> str:
    import os
    out = subprocess.run(["git", "-C", os.path.expanduser(path), "rev-parse", "HEAD"],
                         capture_output=True, text=True)
    return out.stdout.strip() or "UNPINNED"


def build(
    *,
    chain_id: int,
    safe: str,
    controller: str,
    lineage: str,
    morpho: str,
    market: tuple[str, str, str, str, int],
    execution_profile: str,
    price_mode: str,
    strategy_config_digest: str,
    sdk_rev: str | None = None,
) -> NativeConfigIdentity:
    loan, collateral, oracle, irm, lltv = market
    return NativeConfigIdentity(fields={
        "sdkRevision": sdk_rev or sdk_revision(),
        "strategyConfigDigest": strategy_config_digest,
        "chainId": chain_id,
        "safe": safe,
        "controller": controller,
        "lineage": lineage,
        "morpho": morpho,
        "loanToken": loan,
        "collateralToken": collateral,
        "oracle": oracle,
        "irm": irm,
        "lltv": lltv,
        "executionProfile": execution_profile,
        "priceMode": price_mode,
    })
