from pathlib import Path

from laclaugpt_data_collection.config import Settings


def test_default_configuration_is_local_first() -> None:
    settings = Settings(_env_file=None)
    assert settings.record_backend == "sqlite"
    assert settings.object_backend == "filesystem"
    assert settings.cache_backend == "memory"
    assert settings.data_root == Path("data")


def test_safe_summary_never_exposes_secret_values() -> None:
    secret_values = {
        "mongodb_uri": "mongodb://user:password@example.invalid:27017/laclaugpt",
        "redis_url": "redis://:password@example.invalid:6379/0",
        "s3_access_key_id": "access-key-value",
        "s3_secret_access_key": "secret-key-value",
    }
    settings = Settings(_env_file=None, **secret_values)
    summary = settings.safe_summary()
    rendered = repr(summary)

    assert "mongodb_uri" not in summary
    assert "redis_url" not in summary
    assert "s3_access_key_id" not in summary
    assert "s3_secret_access_key" not in summary
    for value in secret_values.values():
        assert value not in rendered
