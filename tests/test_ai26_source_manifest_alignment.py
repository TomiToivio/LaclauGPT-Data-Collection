"""AI26 design-to-manifest account and feed declaration contracts (#265, #266)."""
from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "configs/studies/ai26.sources.example.toml"
DESIGN = ROOT / "configs/studies/ai26.example.yaml"


def _load():
    return (tomllib.loads(MANIFEST.read_text(encoding="utf-8")),
            yaml.safe_load(DESIGN.read_text(encoding="utf-8")))


def test_all_feed_rows_have_a_declared_arena():
    manifest, design = _load()
    arenas = set(design["arenas"])
    assert all(row.get("arena") in arenas for row in manifest["feed"])


def test_inactive_feeds_explain_why_they_are_not_polled():
    manifest, _ = _load()
    for name in ("marc_andreessen", "yudkowsky_net", "kaifulee_medium",
                 "public_ai_network", "ada_lovelace",
                 "data_society"):
        row = next(row for row in manifest["feed"] if row["name"] == name)
        assert row.get("enabled") is False, name
        assert row.get("inactive_reason"), name


def test_declared_bluesky_handles_are_collectable_in_their_arena():
    manifest, design = _load()
    rows = {row["handle"].casefold(): row for row in manifest["bluesky_account"]
            if row.get("active", row.get("enabled", True)) is not False}
    for group in design["groups"]:
        for handle in group.get("accounts", {}).get("bluesky", []):
            row = rows.get(handle.casefold())
            assert row is not None, (group["id"], handle)
            assert row["arena"] == group["arena"], (group["id"], handle)


def test_miri_row_names_the_handle_miri_publishes_not_a_lookalike():
    """#475: @MIRI_AI is an unrelated Japanese personal account; intelligence.org names @MIRIBerkeley.

    The row is not cosmetic. It decides whose posts are counted in the existential-risk stratum, and a
    lookalike handle silently substitutes a stranger's timeline for an institution's voice -- 218 records,
    with 194 of them in Japanese and 2 mentioning AI at all. This pins the handle, and pins that the
    design and the manifest agree about it, so a revert cannot be quiet.
    """
    manifest, design = _load()
    row = next(row for row in manifest["x_account"] if row["name"] == "Machine Intelligence Research Institute")
    assert row["handle"] == "MIRIBerkeley", "MIRI's own site links to x.com/MIRIBerkeley"

    declared = {
        handle
        for group in design["groups"]
        for handle in group.get("accounts", {}).get("x", [])
    }
    assert "MIRIBerkeley" in declared
    assert "MIRI_AI" not in declared, "the lookalike handle must not remain in any group"


def test_declared_mastodon_handles_match_active_manifest():
    manifest, design = _load()
    rows = {row["acct"].casefold() for row in manifest["mastodon_account"]
            if row.get("active", row.get("enabled", True)) is not False}
    for group in design["groups"]:
        for acct in group.get("accounts", {}).get("mastodon", []):
            assert acct.casefold() in rows, (group["id"], acct)



def test_correct_miri_identity_and_parliamentary_sources():
    manifest, design = _load()
    x_handles = {row["handle"].casefold() for row in manifest["x_account"]}
    assert "miri_ai" not in x_handles
    assert "miriberkeley" in x_handles
    group = next(g for g in design["groups"] if g["id"] == "xrisk_safety_x")
    assert "MIRIBerkeley" in group["accounts"]["x"]
    assert "MIRI_AI" not in group["accounts"]["x"]
    assert "intelligence.org" in group["accounts"]["bluesky"]
    feeds = {row["name"]: row for row in manifest["feed"]}
    for name in ("us_congressional_bills", "uk_ai_security_institute"):
        assert feeds[name]["arena"] == "parliamentary"
        assert feeds[name].get("enabled", True)
        assert feeds[name]["priority"] == "P2"
