"""Issue #192: localhost collect wrappers must pass --study-config to the RSS worker.

``server_runner.main()`` requires ``--study-config`` and ``run_phase1_rss`` calls
``sink.assert_private_config(study_config)``.  The localhost wrappers predate that
change, so the documented non-browser collection path failed with an argparse error.
The pre-existing wrapper tests only asserted the presence of the command *name*,
which is why the regression stayed invisible to CI.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

WRAPPERS = (
    "scripts/run_brazil26_localhost_collect.sh",
    "scripts/run_ai26_localhost_collect.sh",
)


def _rss_invocation(text: str) -> str:
    """Return the shell command block that invokes laclaugpt-server-rss."""
    lines = text.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if re.match(r"\s*laclaugpt-server-rss\b", line)),
        None,
    )
    assert start is not None, "wrapper no longer invokes laclaugpt-server-rss"
    block: list[str] = []
    for line in lines[start:]:
        block.append(line)
        # The command ends at the first line that is not a backslash continuation.
        if not line.rstrip().endswith("\\"):
            break
    return "\n".join(block)


@pytest.mark.parametrize("relative", WRAPPERS)
def test_localhost_wrapper_passes_study_config_to_rss_worker(relative: str) -> None:
    invocation = _rss_invocation((ROOT / relative).read_text(encoding="utf-8"))
    assert "--study-config" in invocation, (
        f"{relative} invokes laclaugpt-server-rss without --study-config; "
        "server_runner.main() makes it a required argument"
    )


@pytest.mark.parametrize("relative", WRAPPERS)
def test_localhost_wrapper_fails_fast_on_missing_study_config(relative: str) -> None:
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert re.search(r'\[\[\s*-f\s+"\$STUDY_CONFIG"\s*\]\]', text), (
        f"{relative} must validate that the resolved study config exists before running"
    )


def test_brazil26_wrapper_resolves_private_study_config() -> None:
    """BRAZIL26_CONFIG from the ignored env file must win over the public template."""
    text = (ROOT / "scripts/run_brazil26_localhost_collect.sh").read_text(encoding="utf-8")
    assert "BRAZIL26_CONFIG" in text
    assert "LACLAUGPT_STUDY_CONFIG" in text
