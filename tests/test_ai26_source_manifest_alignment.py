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
                 "public_ai_network", "petterijarvinen", "ada_lovelace",
                 "data_society"):
        row = next(row for row in manifest["feed"] if row["name"] == name)
        assert row.get("active") is False, name
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


def test_declared_mastodon_handles_match_active_manifest():
    manifest, design = _load()
    rows = {row["acct"].casefold() for row in manifest["mastodon_account"]
            if row.get("active", row.get("enabled", True)) is not False}
    for group in design["groups"]:
        for acct in group.get("accounts", {}).get("mastodon", []):
            assert acct.casefold() in rows, (group["id"], acct)
