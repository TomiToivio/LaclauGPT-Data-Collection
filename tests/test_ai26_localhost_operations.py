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
    """Cron's PATH excludes both .venv/bin and ~/.local/bin.

    The wrappers resolve their interpreter through the shared
    ``scripts/ai26_runtime.sh`` helper rather than exporting a literal PATH
    string, because a literal export silently produces a broken entry when
    HOME is unset (``${HOME:-}`` expands to nothing under ``env -i``).
    """
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


def test_ai26_localhost_docs_have_no_placeholder_cron_workdir() -> None:
    text = (ROOT / "docs/AI26_LOCALHOST_COLLECTION.md").read_text(encoding="utf-8")
    cron_section = text.split("## 7. Cron", 1)[1].split("## 8.", 1)[0]
    assert "cd /path/to/LaclauGPT-Data-Collection" not in cron_section
    assert "cd /mnt/c/Users/totoivio/LaclauGPT-Data-Collection" in cron_section
