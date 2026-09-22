from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ai26_public_reference_template_is_safe_and_loadable() -> None:
    from laclaugpt_data_collection.study import load_config

    path = ROOT / "configs" / "studies" / "ai26.example.yaml"
    text = path.read_text(encoding="utf-8")
    cfg = load_config(path)
    assert cfg.study == "ai26"
    assert cfg.start == date(2026, 9, 1)
    assert cfg.accounts()
    assert {"x", "bluesky", "mastodon", "youtube", "rss", "web", "scholarly"} <= set(
        cfg.platforms
    )
    assert "reference_case: true" in text
    assert "source_manifest: ai26.sources.example.toml" in text
    assert "Credentials, cookies, browser profiles, private endpoints" in text
    assert "password" not in text.casefold()
    assert "token:" not in text.casefold()


def test_brazil26_public_template_is_phase1_safe_and_loadable() -> None:
    from laclaugpt_data_collection.study import load_config

    path = ROOT / "configs" / "studies" / "brazil26.example.yaml"
    text = path.read_text(encoding="utf-8")
    cfg = load_config(path)
    assert cfg.study == "brazil26"
    assert cfg.start == date(2026, 9, 7)
    assert len(cfg.candidates) == 2
    assert {"x", "instagram", "tiktok", "rss", "web", "youtube"} <= set(cfg.platforms)
    assert "reference_case: true" in text
    assert "collection_codebook: brazil26.collection-codebook.yaml" in text
    assert "source_manifest: brazil26.sources.example.toml" in text
    assert "Example Candidate" in text
    assert "<private-config-root>/brazil26/study.yaml" in text
    assert "password" not in text.casefold()
    assert "token:" not in text.casefold()


def test_brazil26_public_codebook_and_manifest_are_loadable() -> None:
    import tomllib

    import yaml

    from laclaugpt_data_collection.server_runner import load_feed_manifest

    codebook = ROOT / "configs" / "studies" / "brazil26.collection-codebook.yaml"
    manifest = ROOT / "configs" / "studies" / "brazil26.sources.example.toml"

    data = yaml.safe_load(codebook.read_text(encoding="utf-8"))
    assert data["study"] == "brazil26"
    assert data["handoff"]["collection_id"] == "brazil26"
    assert "never auto-discover or auto-fill missing political actors" in data["browser_sampling"]["rules"]

    parsed = tomllib.loads(manifest.read_text(encoding="utf-8"))
    assert parsed["feed"]
    feeds = load_feed_manifest(manifest)
    assert feeds
    assert all(feed.get("arena") == "institutional" for feed in feeds)


def test_brazil26_handoff_identity_is_isolated_from_ai26() -> None:
    from laclaugpt_data_collection.handoff import build_handoff

    def record(collection_id: str) -> dict:
        return {
            "source_url": "https://example.invalid/shared-source",
            "source": {
                "platform": "synthetic",
                "source_type": "web",
                "created_at": "2026-09-20T12:00:00Z",
                "raw_metadata": {"collection_id": collection_id, "arena": "institutional"},
            },
            "content": {"text": "same source, separate study routing"},
            "provenance": [{"metadata": {"collection_id": collection_id}}],
        }

    brazil = build_handoff(record("brazil26"), project_id="brazil26")
    ai = build_handoff(record("ai26"), project_id="ai26")

    assert brazil["collection_id"] == "brazil26"
    assert brazil["status"] == "ready"
    assert brazil["handoff_key"] != ai["handoff_key"]


def test_brazil26_browser_and_non_browser_can_coexist() -> None:
    profile = (ROOT / "configs" / "brazil26.localhost-remote.example.toml").read_text(encoding="utf-8")
    collect = (ROOT / "scripts" / "run_brazil26_localhost_collect.sh").read_text(encoding="utf-8")
    install = (ROOT / "scripts" / "install_brazil26.sh").read_text(encoding="utf-8")

    assert 'host = "127.0.0.1"' in profile
    assert 'interactive = true' in profile
    assert 'non_browser_enabled = true' in profile
    assert "--collection-id brazil26" in collect
    assert "refuses LACLAUGPT_PROJECT_ID" in collect
    assert "brazil26.sources.example.toml" in install


def test_firefox_runtime_wrapper_keeps_capture_loopback_only() -> None:
    text = (ROOT / "scripts" / "run_firefox_study.sh").read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in text
    assert "0.0.0.0" not in text


def test_every_public_study_yaml_parses() -> None:
    import yaml

    files = sorted((ROOT / "configs" / "studies").glob("*.yaml"))
    assert files, "expected checked-in public study YAML files"

    for path in files:
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise AssertionError(f"{path.name} is not valid YAML: {exc}") from exc


def test_ai26_collection_codebook_parses_and_keeps_its_contract() -> None:
    import yaml

    path = ROOT / "configs" / "studies" / "ai26.collection-codebook.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert data["study"] == "ai26"
    cues = data["formation_sampling_cues"]
    for name in (
        "accelerationism",
        "existential-risk discourse",
        "left-wing techno-optimism",
        "ai safety",
        "ai critical",
    ):
        assert name in cues, f"missing formation sampling cue: {name}"
        assert cues[name]["discovery_terms"], f"{name} has no discovery terms"
