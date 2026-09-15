from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "check_public_tree.py"
SPEC = importlib.util.spec_from_file_location("check_public_tree", SCRIPT)
assert SPEC and SPEC.loader
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


def test_public_examples_are_allowed() -> None:
    assert POLICY.path_policy_violations(Path(".env.example")) == []
    assert POLICY.path_policy_violations(Path("configs/laptop.example.toml")) == []
    assert POLICY.path_policy_violations(Path("configs/server.example.toml")) == []


def test_private_config_and_data_paths_are_rejected() -> None:
    samples = [
        Path(".env"),
        Path("configs/server.local.toml"),
        Path("configs/study.private.yaml"),
        Path("data/posts.csv"),
        Path("raw/capture.jsonl"),
        Path("browser/session.har"),
        Path("clouds.yaml"),
        Path("terraform.tfstate"),
    ]
    for sample in samples:
        assert POLICY.path_policy_violations(sample), sample


def test_literal_secret_assignments_are_rejected() -> None:
    text = 'api_key = "this-is-a-real-looking-secret"\n'
    assert POLICY.content_policy_violations(Path("settings.py"), text)


def test_credential_bearing_urls_are_rejected() -> None:
    text = 'uri = "mongodb://researcher:supersecret@example.invalid:27017/db"\n'
    assert POLICY.content_policy_violations(Path("settings.py"), text)


def test_placeholders_and_environment_plumbing_are_allowed() -> None:
    safe = '''
api_key = "replace-locally"
aws_secret_access_key=secret_access_key
mongodb_uri = os.environ["LACLAUGPT_MONGODB_URI"]
'''
    assert POLICY.content_policy_violations(Path("example.py"), safe) == []
