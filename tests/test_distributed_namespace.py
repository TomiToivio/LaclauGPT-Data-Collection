from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.distributed import ProjectNamespace


def test_ai26_namespace_is_collision_safe() -> None:
    ns = ProjectNamespace("ai26")
    assert ns.redis_base == "laclaugpt:ai26"
    assert ns.settings_key("collection") == "laclaugpt:ai26:settings:collection:current"
    assert ns.codebook_key("entities", "v3") == "laclaugpt:ai26:codebook:entities:v3"
    assert ns.mongo_collection("records") == "ai26__records"
    assert ns.s3_key("media", "abc", "video.mp4") == "projects/ai26/media/abc/video.mp4"


def test_projects_do_not_share_namespaces() -> None:
    projects = [ProjectNamespace(name) for name in ("ai26", "ep24", "brazil26", "hungary26")]
    assert len({item.redis_base for item in projects}) == 4
    assert len({item.mongo_collection("records") for item in projects}) == 4
    assert len({item.s3_key("raw") for item in projects}) == 4


def test_settings_expose_project_namespace() -> None:
    settings = Settings(_env_file=None, project_id="brazil26")
    assert settings.distributed_namespace.mongo_collection("records") == "brazil26__records"
    assert settings.safe_summary()["redis_namespace"] == "laclaugpt:brazil26"


def test_invalid_project_id_is_rejected() -> None:
    try:
        ProjectNamespace("EP24")
    except ValueError as exc:
        assert "project_id" in str(exc)
    else:
        raise AssertionError("uppercase project ID should be rejected")
