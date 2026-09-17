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


def test_brazil26_public_template_is_synthetic_and_loadable() -> None:
    from laclaugpt_data_collection.study import load_config

    path = ROOT / "configs" / "studies" / "brazil26.example.yaml"
    text = path.read_text(encoding="utf-8")
    cfg = load_config(path)
    assert cfg.study == "brazil26"
    assert len(cfg.candidates) == 2
    assert "Example Candidate" in text


def test_firefox_runtime_wrapper_keeps_capture_loopback_only() -> None:
    text = (ROOT / "scripts" / "run_firefox_study.sh").read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in text
    assert "0.0.0.0" not in text


def test_every_public_study_yaml_parses() -> None:
    """Every checked-in study YAML must be loadable by a YAML parser.

    The runbook tells researchers to copy these files into ``data/config/``, so
    an unparseable template is handed straight to them. This guards that class
    of defect: the AI26 collection codebook once carried an unclosed quote in a
    ``note:`` value, which made the whole document unreadable without any test
    noticing.
    """
    import yaml

    files = sorted((ROOT / "configs" / "studies").glob("*.yaml"))
    assert files, "expected checked-in public study YAML files"

    for path in files:
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:  # pragma: no cover - failure path
            raise AssertionError(f"{path.name} is not valid YAML: {exc}") from exc


def test_ai26_collection_codebook_parses_and_keeps_its_contract() -> None:
    """The AI26 codebook must parse and keep its declared structure."""
    import yaml

    path = ROOT / "configs" / "studies" / "ai26.collection-codebook.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert data["study"] == "ai26"
    # The formation cues are the research-design surface other projects consume;
    # losing one silently would change what the collection appears to cover.
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

