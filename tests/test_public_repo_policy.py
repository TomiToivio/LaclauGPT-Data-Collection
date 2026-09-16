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
    key_name = "api" + "_key"
    secret_value = "synthetic-" + "secret-value"
    text = f'{key_name} = "{secret_value}"\n'
    assert POLICY.content_policy_violations(Path("settings.py"), text)


def test_credential_bearing_urls_are_rejected() -> None:
    scheme = "mongo" + "db://"
    credentials = "synthetic-user" + ":" + "synthetic-password"
    text = f'uri = "{scheme}{credentials}@example.invalid:27017/db"\n'
    assert POLICY.content_policy_violations(Path("settings.py"), text)


def test_placeholders_and_environment_plumbing_are_allowed() -> None:
    safe = '''
api_key = "replace-locally"
aws_secret_access_key=secret_access_key
mongodb_uri = os.environ["LACLAUGPT_MONGODB_URI"]
'''
    assert POLICY.content_policy_violations(Path("example.py"), safe) == []


def test_cloud_credential_bundles_are_rejected_by_name() -> None:
    """`allas_conf` (CSC Allas helper) was once committed; it must never pass again."""
    for name in (
        "allas_conf",
        "allas-conf",
        "nested/allas_conf",
        "gcloud_conf",
        "az_conf",
    ):
        assert POLICY.path_policy_violations(Path(name)), name


def test_openstack_credential_values_are_rejected() -> None:
    """A populated OS_* credential slot is secret material, not plumbing."""
    token_var = "OS_AUTH" + "_TOKEN"
    leaked = f"export {token_var}=gAAAAABabc123def456ghi789jkl012mno345\n"
    assert POLICY.content_policy_violations(Path("allas_conf"), leaked)

    password_var = "OS_" + "PASSWORD"
    leaked_pw = f'{password_var}="hunter2hunter2"\n'
    assert POLICY.content_policy_violations(Path("clouds.sh"), leaked_pw)


def test_openstack_plumbing_is_not_a_false_positive() -> None:
    """Empty slots and variable references are how a script reads its environment."""
    token_var = "OS_AUTH" + "_TOKEN"
    password_var = "OS_" + "PASSWORD"
    safe = (
        f"export {token_var}=\n"
        f'{token_var}="${token_var}"\n'
        f"{token_var}=${{{token_var}:-}}\n"
        f"{password_var}=replace-locally\n"
    )
    assert POLICY.content_policy_violations(Path("allas_conf.example.sh"), safe) == []
