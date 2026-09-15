from pathlib import Path

from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.deployment import (
    DeploymentProfile,
    apply_profile,
    render_cron,
    render_systemd_units,
    validate_profile,
)
from laclaugpt_data_collection.integrations.hermes import (
    browser_capture_readiness,
    inspect_effective_config,
    plan_collection_run,
    stamp_agent_provenance,
)
from laclaugpt_data_collection.models import CanonicalRecord


def test_laptop_firefox_profile_is_local_and_loopback() -> None:
    settings = apply_profile(Settings(_env_file=None), DeploymentProfile.laptop_firefox_local())
    assert settings.machine == "laptop"
    assert settings.execution == "cli"
    assert settings.browser == "firefox-local"
    assert settings.record_backend == "sqlite"
    assert settings.object_backend == "filesystem"
    assert settings.cache_backend == "memory"
    assert settings.browser_host == "127.0.0.1"
    assert validate_profile(settings) == []


def test_firefox_local_rejects_non_loopback_bind() -> None:
    settings = Settings(_env_file=None, browser="firefox-local", browser_host="0.0.0.0")
    assert "localhost" in validate_profile(settings)[0]
    assert browser_capture_readiness(settings)["safe_local_bind"] is False


def test_linux_server_profiles_keep_execution_and_storage_composable() -> None:
    base = Settings(_env_file=None)
    local = apply_profile(base, DeploymentProfile.linux_server_local())
    distributed = apply_profile(base, DeploymentProfile.linux_server_distributed())
    assert local.machine == distributed.machine == "linux-server"
    assert local.execution == distributed.execution == "cron"
    assert (local.record_backend, local.object_backend, local.cache_backend) == (
        "sqlite",
        "filesystem",
        "memory",
    )
    assert (distributed.record_backend, distributed.object_backend, distributed.cache_backend) == (
        "mongodb",
        "s3",
        "redis",
    )


def test_schedule_generation_is_offline_and_uses_private_runtime_paths() -> None:
    cron = render_cron("laclaugpt-collect doctor")
    assert "data/runs/collection.lock" in cron
    assert "data/logs/collection.log" in cron
    units = render_systemd_units(
        "laclaugpt-collect doctor",
        working_directory=Path("/opt/laclaugpt-collection"),
    )
    assert "ExecStart=laclaugpt-collect doctor" in units["service"]
    assert "Persistent=true" in units["timer"]


def test_hermes_inspection_is_redacted_and_dry_run_is_offline() -> None:
    marker = "synthetic" + "-credential-value"
    mongo_uri = "mongo" + "db://" + "user" + ":" + marker + "@example.invalid:27017/db"
    redis_url = "redis://" + ":" + marker + "@example.invalid:6379/0"
    settings = Settings(
        _env_file=None,
        mongodb_uri=mongo_uri,
        redis_url=redis_url,
        s3_secret_access_key=marker,
    )
    summary = inspect_effective_config(settings)
    rendered = repr(summary)
    assert marker not in rendered
    assert "mongodb_uri" not in summary
    assert "redis_url" not in summary
    plan = plan_collection_run(settings)
    assert plan.dry_run is True
    assert plan.caller == "hermes-agent"
    assert plan.profile["execution"] == "agent"


def test_agent_provenance_does_not_change_canonical_identity() -> None:
    record = CanonicalRecord(source_url="https://example.invalid/post/1?utm_source=test")
    source_url = record.source_url
    result = stamp_agent_provenance(record, run_id="synthetic-run")
    assert result.source_url == source_url
    assert result.provenance[-1].metadata["caller"] == "hermes-agent"
    assert result.provenance[-1].metadata["execution"] == "agent"
    assert result.provenance[-1].run_id == "synthetic-run"


def test_all_default_runtime_paths_stay_under_data() -> None:
    settings = Settings(_env_file=None)
    assert settings.data_root == Path("data")
    assert settings.sqlite_path.is_relative_to(settings.data_root)
