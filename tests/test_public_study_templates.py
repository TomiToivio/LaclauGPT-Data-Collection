from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ai26_public_template_is_public_safe_and_loadable() -> None:
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
    # AI26 is the realistic public reference study, so its checked-in template
    # carries real public source handles rather than synthetic `example_`
    # fixtures. The public-safe invariant is that no secret material is
    # present, not that the study is synthetic.
    assert "password" not in text.casefold()
    assert "token:" not in text.casefold()
    assert "@" not in text or "mastodon" in text.casefold()


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
