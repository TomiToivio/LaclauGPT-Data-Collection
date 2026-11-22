"""#457: the runtime gate must distinguish compatible drift from schema drift.

The gate has three verdicts, and the difference between two of them is whether a collection cycle may
write records:

- ``in_sync``          nothing differs;
- ``stale_compatible`` behind upstream, but no file that changes what a stored record means;
- ``blocked``          schema-affecting upstream change (or an unverifiable checkout) — refuse to write.

The decision is tested here against **synthetic Git repositories**: a bare origin plus a clone pushed one
commit behind. Nothing touches the live Laskin checkout, which is what the issue's verification gate
requires — simulating drift by editing the deployed tree would be the failure mode, not the test.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.check_ai26_runtime import SCHEMA_AFFECTING_PREFIXES, Finding, code_drift_blockers

pytestmark = pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git is required to build a synthetic repository",
)


def _run(*args: str, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _repo(tmp_path: Path, changed_file: str) -> tuple[Path, str]:
    """A clone one commit behind its origin, where upstream touched ``changed_file``."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _run("init", "--bare", "--initial-branch=main", str(origin), cwd=tmp_path)

    seed = tmp_path / "seed"
    seed.mkdir()
    _run("init", "--initial-branch=main", cwd=seed)
    _run("remote", "add", "origin", str(origin), cwd=seed)
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    _run("add", ".", cwd=seed)
    _run("-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-m", "base", cwd=seed)
    _run("push", "-u", "origin", "main", cwd=seed)

    checkout = tmp_path / "checkout"
    _run("clone", str(origin), str(checkout), cwd=tmp_path)

    target = seed / changed_file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("upstream change\n", encoding="utf-8")
    _run("add", ".", cwd=seed)
    _run("-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-m", "upstream", cwd=seed)
    _run("push", cwd=seed)
    _run("fetch", "origin", cwd=checkout)

    head = _run("rev-parse", "--short", "HEAD", cwd=checkout)
    return checkout, head


def _findings(checkout: Path, head: str) -> list[Finding]:
    return [
        Finding(
            name=f"code ({checkout.name})",
            ok=False,
            detail=f"2 commit(s) behind origin/main (HEAD {head}, origin/main abc1234)",
        )
    ]


@pytest.mark.parametrize(
    "changed_file",
    [
        "docs/notes.md",
        "src/laclaugpt_data_collection/collectors/rss.py",
        "scripts/run_ai26_laskin_collect.sh",
    ],
)
def test_non_schema_drift_is_not_blocking(tmp_path, changed_file):
    checkout, head = _repo(tmp_path, changed_file)
    schema_paths, reasons = code_drift_blockers(_findings(checkout, head), [checkout])
    assert schema_paths == []
    assert reasons == [], reasons


@pytest.mark.parametrize(
    "changed_file",
    [
        "src/laclaugpt_data_collection/models.py",
        "src/laclaugpt_data_collection/canonical.py",
        "schemas/laclaugpt-rdf.shacl.ttl",
    ],
)
def test_schema_drift_blocks_the_write(tmp_path, changed_file):
    checkout, head = _repo(tmp_path, changed_file)
    schema_paths, reasons = code_drift_blockers(_findings(checkout, head), [checkout])
    assert reasons, "schema-affecting drift must block"
    assert any(reason.endswith("schema-affecting changes upstream") for reason in reasons)
    assert schema_paths and schema_paths[0].endswith(changed_file)


def test_every_guarded_prefix_is_actually_guarded(tmp_path):
    """A prefix that matches nothing would silently weaken the gate."""
    for index, prefix in enumerate(SCHEMA_AFFECTING_PREFIXES):
        base = tmp_path / f"case{index}"
        base.mkdir(parents=True, exist_ok=True)
        checkout, head = _repo(base, f"{prefix}probe.py")
        schema_paths, _ = code_drift_blockers(_findings(checkout, head), [checkout])
        assert schema_paths, f"{prefix} is declared but guarded nothing"
