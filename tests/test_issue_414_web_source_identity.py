# -*- coding: utf-8 -*-
"""Issue #414 — the drift gate must see `web_source` rows, which carry `homepage`.

`manifest_drift` keyed `web_source` on `url` alone, but every audited AI26
`[[web_source]]` row (and every deployed one) writes `homepage`. Every row
therefore resolved to no identity and was dropped from both sides, so the gate
reported "in sync" with `web_source deployed=0 tracked=0` while 11-12 active rows
existed -- blindness to a whole kind, not a narrow parsing quirk.

These tests pin the repaired semantics:

* a `homepage`-only row is counted and reported;
* a row added to the tracked plan but missing from the deployed manifest is
  drift, so the gate can fail instead of clearing silently;
* the two spellings (`homepage`, `url`) are one identity, so switching spelling
  never reads as a false added/removed pair;
* the same URL may still appear as both `[[feed]]` and `[[web_source]]`.

All fixtures are synthetic; no real manifest is read.
"""
from __future__ import annotations

from pathlib import Path

from laclaugpt_data_collection.manifest_drift import compare_manifests


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _web(name: str, homepage: str) -> str:
    return f'[[web_source]]\nname = "{name}"\nhomepage = "{homepage}"\narena = "elites"\n'


def _web_url(name: str, url: str) -> str:
    return f'[[web_source]]\nname = "{name}"\nurl = "{url}"\narena = "elites"\n'


def test_homepage_rows_are_counted(tmp_path: Path) -> None:
    """The #414 symptom: 0/0 over rows that plainly exist."""
    body = _web("anthropic_news", "https://www.anthropic.com/news") + _web(
        "meta_ai", "https://ai.meta.com/blog"
    )
    manifest = _write(tmp_path, "m.toml", body)
    report = compare_manifests(manifest, manifest)
    counts = report["counts"]["web_source"]
    assert counts["deployed"] == 2, "a homepage-only row must resolve an identity"
    assert counts["tracked"] == 2
    assert report["deployed_total"] == 2
    assert report["in_sync"] is True


def test_a_homepage_row_missing_from_the_deployed_manifest_is_drift(
    tmp_path: Path,
) -> None:
    """The gate's whole purpose: an audited source that never reached runtime."""
    deployed = _write(
        tmp_path, "d.toml", _web("anthropic_news", "https://www.anthropic.com/news")
    )
    tracked = _write(
        tmp_path,
        "t.toml",
        _web("anthropic_news", "https://www.anthropic.com/news")
        + _web("meta_ai", "https://ai.meta.com/blog"),
    )
    report = compare_manifests(deployed, tracked)
    assert report["in_sync"] is False
    assert report["drift_kinds"] == ["web_source"]
    assert report["added"] == ["web_source:url=https://ai.meta.com/blog"]
    assert report["counts"]["web_source"]["added"] == 1


def test_homepage_and_url_spellings_are_one_identity(tmp_path: Path) -> None:
    """Switching spelling must not read as one removed plus one added."""
    deployed = _write(tmp_path, "d.toml", _web_url("a", "https://a.example/news"))
    tracked = _write(tmp_path, "t.toml", _web("a", "https://a.example/news"))
    report = compare_manifests(deployed, tracked)
    assert report["in_sync"] is True
    assert report["added"] == []
    assert report["removed"] == []


def test_a_trailing_slash_on_a_homepage_is_not_a_source_change(
    tmp_path: Path,
) -> None:
    deployed = _write(tmp_path, "d.toml", _web("a", "https://a.example/news"))
    tracked = _write(tmp_path, "t.toml", _web("a", "https://a.example/news/"))
    assert compare_manifests(deployed, tracked)["in_sync"] is True


def test_a_homepage_web_source_does_not_collide_with_a_feed(tmp_path: Path) -> None:
    """The same URL can route as a feed and as a web source."""
    feed = '[[feed]]\nname = "a"\nfeed_url = "https://a.example/x"\n'
    deployed = _write(tmp_path, "d.toml", feed)
    tracked = _write(
        tmp_path, "t.toml", feed + _web("web_a", "https://a.example/x")
    )
    report = compare_manifests(deployed, tracked)
    assert report["drift_kinds"] == ["web_source"]
    assert report["added"] == ["web_source:url=https://a.example/x"]
