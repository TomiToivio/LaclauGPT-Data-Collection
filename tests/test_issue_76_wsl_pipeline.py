from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_issue_76_deliverables_exist() -> None:
    required = [
        "requirements.txt",
        "scripts/install_common.sh",
        "scripts/install_ai26.sh",
        "scripts/install_brazil26.sh",
        "scripts/install_cron_ai26.sh",
        "scripts/install_cron_brazil26.sh",
        "scripts/validate_installation.sh",
        "scripts/run_brazil26_localhost_collect.sh",
        "scripts/run_brazil26_localhost_media.sh",
        "scripts/run_brazil26_localhost_sync.sh",
        "docs/installation/WSL_UBUNTU.md",
        "docs/installation/AI26.md",
        "docs/installation/BRAZIL26.md",
    ]
    for item in required:
        assert (ROOT / item).exists(), item


def test_public_project_envs_use_allas_conf_not_embedded_keys() -> None:
    for name in ("configs/ai26.browser.env.example", "configs/brazil26.env.example"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "allas-conf" in text
        assert "LACLAUGPT_S3_ACCESS_KEY=" not in text
        assert "LACLAUGPT_S3_SECRET_KEY=" not in text


def test_browser_backends_are_loopback_only() -> None:
    for name in ("configs/ai26.browser.env.example", "configs/brazil26.env.example"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "LACLAUGPT_BROWSER_HOST=127.0.0.1" in text


def test_cron_installers_are_marker_managed() -> None:
    for name in ("scripts/install_cron_ai26.sh", "scripts/install_cron_brazil26.sh"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "# BEGIN LACLAUGPT" in text
        assert "crontab" in text
        assert "data/logs/" in text
