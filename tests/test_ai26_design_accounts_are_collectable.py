# -*- coding: utf-8 -*-
"""Issue #266 contract: the design's accounts are actually in the manifest.

The defect this pins: ``ai26.example.yaml`` declares the accounts the study
intends to sample per arena group, and the source manifest is what the collector
can poll. Nothing made them agree, so two accounts declared by the design
(``wgawest.bsky.social`` and ``creativecommons.bsky.social``) were in **no** row of
the manifest, and one group's bluesky strand -- ``grassroots_creator_rights_licensing``
-- therefore had zero records. Nothing failed: the study config was valid, the
manifest was valid, and the two were simply describing different studies.

The contract: every account the design declares must exist as an **active** row in
the manifest, unless it is listed below as deliberately uncollected. A divergence is
a failure, not a silent coverage limit.

An account that is deliberately not collected is recorded in
``DOCUMENTED_UNCOLLECTED`` with the reason, so the decision is reviewable and the
limit is visible. The comparison is order- and case-insensitive: X and Bluesky
handles are case-insensitive for lookup, and the local part of a mastodon acct is
too -- a *host* divergence is still a different account and still fails.

Pure config/data contract: it asserts nothing about prose or documentation.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "configs" / "studies" / "ai26.sources.example.toml"
DESIGN = REPO / "configs" / "studies" / "ai26.example.yaml"

# The kinds of account the design may declare, mapped to the manifest row family
# that must carry them, and the manifest field that identifies the account.
KIND_TO_TABLE = {
    "x": ("x_account", "handle"),
    "bluesky": ("bluesky_account", "handle"),
    "mastodon": ("mastodon_account", "acct"),
}

# Accounts the design declares that the study does not collect, with the reason.
# Empty: every declared account is collected. An entry here is a deliberate,
# reviewed coverage limit, not an oversight.
DOCUMENTED_UNCOLLECTED: dict[str, str] = {}


def _key(value: object) -> str:
    """Normalise an account identifier for comparison."""
    return str(value or "").strip().lstrip("@").casefold()


def _is_active(row: dict) -> bool:
    """Mirror the collector: a row runs unless it is explicitly not enabled."""
    return row.get("enabled", row.get("active", True)) is not False


def manifest_accounts() -> dict[str, set[str]]:
    data = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for kind, (table, field) in KIND_TO_TABLE.items():
        out[kind] = {
            _key(row.get(field))
            for row in (data.get(table) or [])
            if _is_active(row)
        }
    return out


def declared_accounts() -> list[tuple[str, str, str]]:
    """Every (group, kind, account) the design declares."""
    design = yaml.safe_load(DESIGN.read_text(encoding="utf-8"))
    declared: list[tuple[str, str, str]] = []
    for group in design.get("groups") or []:
        gid = str(group.get("id") or "<unnamed group>")
        for kind, accounts in (group.get("accounts") or {}).items():
            assert kind in KIND_TO_TABLE, (
                f"group {gid} declares account kind {kind!r}, which this guard does "
                "not know how to check against the manifest. Teach it, rather than "
                "letting the kind go unchecked."
            )
            for account in accounts or []:
                declared.append((gid, str(kind), str(account)))
    return declared


def test_the_design_declares_at_least_one_account_per_kind() -> None:
    """A guard over an empty design would pass while proving nothing."""
    declared = declared_accounts()
    assert declared, "the design declares no accounts; this guard would be vacuous"
    kinds = {kind for _, kind, _ in declared}
    assert kinds == set(KIND_TO_TABLE), (
        f"expected the design to exercise every account kind {sorted(KIND_TO_TABLE)}, "
        f"found {sorted(kinds)}"
    )


def test_every_declared_account_is_an_active_manifest_row() -> None:
    available = manifest_accounts()
    missing: list[str] = []
    for group, kind, account in declared_accounts():
        if account in DOCUMENTED_UNCOLLECTED:
            continue
        if _key(account) not in available[kind]:
            missing.append(f"{group}: {kind} {account!r}")
    assert not missing, (
        "the design declares account(s) that no active manifest row can collect, so "
        "the group's evidence silently stays empty (#266). Either add the row to the "
        "manifest or record the account in DOCUMENTED_UNCOLLECTED with a reason:\n  "
        + "\n  ".join(sorted(set(missing)))
    )


def test_a_documented_uncollected_account_records_a_reason() -> None:
    undocumented = sorted(
        account for account, reason in DOCUMENTED_UNCOLLECTED.items()
        if not str(reason or "").strip()
    )
    assert not undocumented, (
        f"account(s) marked uncollected with no reason: {undocumented}"
    )


def test_documented_uncollected_accounts_are_still_declared_by_the_design() -> None:
    """A stale exemption hides a future defect of the kind it was written for."""
    declared = {account for _, _, account in declared_accounts()}
    stale = sorted(set(DOCUMENTED_UNCOLLECTED) - declared)
    assert not stale, (
        f"DOCUMENTED_UNCOLLECTED lists account(s) the design no longer declares: {stale}"
    )
