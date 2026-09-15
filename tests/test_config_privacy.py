from pathlib import Path

from laclaugpt_data_collection.config import Settings


def test_default_configuration_is_local_first() -> None:
    settings = Settings(_env_file=None)
    assert settings.record_backend == "sqlite"
    assert settings.object_backend == "filesystem"
    assert settings.cache_backend == "memory"
    assert settings.data_root == Path("data")
    assert settings.sqlite_path == Path("data/database/collection.sqlite3")


def test_standard_runtime_tree_is_created_under_data(tmp_path: Path) -> None:
    root = tmp_path / "data"
    settings = Settings(
        _env_file=None,
        data_root=root,
        sqlite_path=root / "database" / "collection.sqlite3",
    )
    settings.ensure_local_directories()
    for relative in (
        "logs",
        "database",
        "config",
        "files",
        "csv",
        "codebooks",
        "sources",
        "downloads",
        "models/ollama",
        "models/whisper",
        "exports",
    ):
        assert (root / relative).is_dir()


def test_safe_summary_never_exposes_secret_values() -> None:
    mongo_uri = "mongo" + "db://" + "user" + ":" + "password" + "@example.invalid:27017/laclaugpt"
    redis_url = "redis://" + ":" + "password" + "@example.invalid:6379/0"
    secret_values = {
        "mongodb_uri": mongo_uri,
        "redis_url": redis_url,
        "s3_access_key_id": "synthetic-access-value",
        "s3_secret_access_key": "synthetic-secret-value",
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
