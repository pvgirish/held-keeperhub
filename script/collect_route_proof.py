#!/usr/bin/env python3
"""M1 route proof: what the REAL authenticated KeeperHub route says, and nothing more.

Every KeeperHub result in this repository until now came from `OfflineTransport`, which
stamps `hosted=False` precisely so a local fixture could never be filed as hosted
evidence. This script is the first thing that runs against the live organisation route
with a real credential, over `HttpsTransport`, which is the only transport that can
produce `hosted=True`.

## What it does

One authenticated `GET /api/keys` (route-evidence L10, request A in
`evidence/P03/public-action-request.json`). It reads the organisation's key listing,
matches the configured credential against it by the documented `keyPrefix`, and records
the scopes actually attached.

It broadcasts nothing, deploys nothing, and spends nothing. There is no path in this
file that can submit a contract call.

## What the result establishes, exactly

  * that the organisation route accepts the configured credential -- a fact no local
    test could produce, because `/api/chains` answers 200 with no credential at all;
  * that the credential we hold is one of the keys the organisation lists;
  * the scopes on it, which is what decides whether a broadcast is possible at all.

## What it does NOT establish

  * **M1.** M1 is "a real transaction executed through KeeperHub". A credential listing
    is not a transaction. If the observed scope is `mcp:read`, M1 is not merely
    unperformed but currently impossible on this credential, and the evidence file says
    so in those words.
  * **L10 as a whole.** Whether the authenticated caller/payer accepts Held's outer
    controller call is a separate question, and it needs a deployed controller to aim a
    dry run at. This run does not answer it and does not close the gate.
  * **P19.** Nothing here shows KeeperHub's server-side encoder reproduces Held's
    intended calldata.

The evidence file carries no secret, no key prefix, no operator name and no email: the
prefix match happens in memory and only the boolean survives. See
`CredentialCheck.to_evidence()`.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("adapter", "packages/core"):
    sys.path.insert(0, os.path.join(ROOT, p))

from held_adapter.execution.keeperhub import (  # noqa: E402
    DEFAULT_BASE_URL,
    KEYS_PATH,
    SCOPE_READ,
    BROADCAST_SCOPES,
    CredentialReference,
    HttpsTransport,
    KeeperHubClient,
    L10Blocked,
)

CREDENTIAL_REF = "env:HELD_KEEPERHUB_API_KEY"
OUT = os.path.join(ROOT, "evidence", "P03", "l10-route-proof.json")


def main() -> int:
    base_url = os.environ.get("HELD_KEEPERHUB_BASE_URL", DEFAULT_BASE_URL)
    ref = CredentialReference(CREDENTIAL_REF)

    # HttpsTransport refuses a non-https origin, so this cannot be pointed at a local
    # stand-in and still be recorded as hosted.
    client = KeeperHubClient(ref, transport=HttpsTransport(base_url), base_url=base_url)

    try:
        check = client.organisation_keys()
    except L10Blocked as exc:
        print(f"L10 route proof: BLOCKED — {exc}")
        return 1

    # A non-hosted result must never reach the evidence file. The transport above is
    # https, so this is a belt-and-braces assertion, not an expected branch.
    check.assert_hosted_evidence()

    record = {
        "schema": "held.l10-route-proof.v1",
        "gate": "L10-authenticated-caller-payer",
        "step": "request A — authenticated organisation credential check",
        "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "call": {
            "method": "GET",
            "url": f"{base_url}{KEYS_PATH}",
            "authenticated": True,
            "credential_ref": CREDENTIAL_REF,
            "broadcasts": False,
            "spends": "nothing — no gas, no funds, no contract call",
        },
        "transport": {
            "class": type(client.transport).__name__,
            "hosted": client.transport.hosted,
            "why_it_matters": (
                "OfflineTransport stamps hosted=false and every other KeeperHub result in "
                "this repository carries that stamp. This is the first hosted=true result."
            ),
        },
        "result": check.to_evidence(),
        "establishes": [
            "The live organisation route accepts the configured credential.",
            "The credential held here is one of the keys the organisation lists, matched "
            "by the documented keyPrefix against the resolved secret.",
            "The scopes actually attached to that credential.",
        ],
        "does_not_establish": {
            "M1": (
                "M1 is a real transaction executed through KeeperHub. A credential listing "
                "is not a transaction. M1 remains NOT YET ESTABLISHED."
            ),
            "L10": (
                "Whether the authenticated caller/payer accepts Held's outer controller "
                "call is unanswered. It needs a simulate-mode contract call against a "
                "DEPLOYED HeldController, and no controller exists on any public chain."
            ),
            "P18": "Held has not executed anything through KeeperHub.",
            "P19": (
                "Nothing here shows KeeperHub's server-side encoder reproduces Held's "
                "intended calldata."
            ),
        },
        "remaining_for_M1": _remaining(check),
        "boundaries": [
            "This is evidence about a CREDENTIAL, not about an EXECUTION.",
            "GET /api/chains is public and answers 200 with no credential; it was never "
            "usable as an authentication check and is not what was called here.",
            "No secret, key prefix, operator name or email is recorded in this file.",
        ],
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(record, fh, indent=1)
        fh.write("\n")

    print(f"status        : {check.status_code}")
    print(f"hosted        : {check.hosted}")
    print(f"credential    : {'matches a listed organisation key' if check.matched else 'NOT MATCHED'}")
    print(f"scopes        : {list(check.scopes) or '(none read)'}")
    print(f"can broadcast : {check.can_broadcast}")
    if check.error:
        print(f"error         : {check.error}")
    print(f"written       : {os.path.relpath(OUT, ROOT)}")
    print("---")

    if not check.valid:
        print("L10 route proof: FAIL — the credential is not established as valid.")
        return 1

    print("L10 route proof: request A ESTABLISHED (hosted). L10 itself remains OPEN, and")
    print("                 M1 remains NOT YET ESTABLISHED — see does_not_establish.")
    if not check.can_broadcast:
        print(f"                 Scope is {SCOPE_READ}-only: M1 is not merely unperformed,")
        print(f"                 it is impossible on this credential. One of "
              f"{list(BROADCAST_SCOPES)} is required.")
    return 0


def _remaining(check) -> list[str]:
    todo = []
    if not check.can_broadcast:
        todo.append(
            f"A credential carrying one of {list(BROADCAST_SCOPES)}. The observed scope "
            f"is {list(check.scopes)}, which the documentation says can read and simulate "
            "but cannot broadcast."
        )
    todo += [
        "A HeldController deployed to Base mainnet, with its Safe and Zodiac Roles module, "
        "scoped and activated by the owners. None exists.",
        "A funded Safe, at an amount agreed in advance.",
        "A simulate-mode contract call against that controller, passing, before any "
        "broadcast (evidence/P03/public-action-request.json step 8).",
        "Explicit authorization to deploy a contract and spend funds, which has not been "
        "given.",
    ]
    return todo


if __name__ == "__main__":
    raise SystemExit(main())
