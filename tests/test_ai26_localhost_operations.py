from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_ai26_collection_codebook_is_valid_yaml() -> None:
    path = ROOT / "configs/studies/ai26.collection-codebook.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["study"] == "ai26"
    assert data["version"]
    assert "existential-risk discourse" in data["formation_sampling_cues"]


def test_ai26_localhost_cron_wrappers_resolve_repo_virtualenv() -> None:
    """Cron's PATH excludes both .venv/bin and ~/.local/bin."""
    runtime = (ROOT / "scripts/ai26_runtime.sh").read_text(encoding="utf-8")
    assert ".venv/bin" in runtime
    assert ".local/bin" in runtime

    for name in (
        "run_ai26_localhost_sync.sh",
        "run_ai26_localhost_collect.sh",
        "run_ai26_localhost_media.sh",
    ):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "ai26_runtime.sh" in text, f"{name} does not source the runtime helper"
        assert "ai26_prepend_runtime_path" in text, f"{name} does not fix PATH"
        assert "command -v laclaugpt-" not in text, (
            f"{name} still guards on a bare `command -v laclaugpt-*`, which "
            "fails under cron"
        )


def test_ai26_localhost_collect_uses_one_wrapper_for_rss_and_phase1_plugins() -> None:
    text = (ROOT / "scripts/run_ai26_localhost_collect.sh").read_text(encoding="utf-8")
    assert "laclaugpt-server-rss" in text
    assert "laclaugpt_data_collection.ai26_localhost_collect" in text
    assert text.count("--collection-id ai26") == 2
    assert "--project-id ai26" in text
    assert "run_firefox_study.sh" not in text, "Firefox must remain interactive/manual"


def test_ai26_localhost_phase1_runner_preserves_sampling_as_provenance() -> None:
    text = (
        ROOT / "src/laclaugpt_data_collection/ai26_localhost_collect.py"
    ).read_text(encoding="utf-8")
    assert '"sampling-provenance-only"' in text
    assert '"ideology_ground_truth": False' in text
    assert '"collection_machine"' in text
    assert '"publication_time_unresolved"' in text
    assert '"bluesky"' in text
    assert '"arxiv"' in text


def test_ai26_localhost_docs_have_no_placeholder_cron_workdir() -> None:
    text = (ROOT / "docs/AI26_LOCALHOST_COLLECTION.md").read_text(encoding="utf-8")
    cron_section = text.split("## 7. Cron", 1)[1].split("## 8.", 1)[0]
    assert "cd /path/to/LaclauGPT-Data-Collection" not in cron_section
    assert "cd /mnt/c/Users/totoivio/LaclauGPT-Data-Collection" in cron_section
