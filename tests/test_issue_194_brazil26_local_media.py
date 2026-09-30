"""Issue #194: the localhost media wrapper must stay local-first.

``run_brazil26_localhost_media.sh`` is documented as part of the
zero-infrastructure localhost profile (``docs/brazil26-localhost.md``: the default
profile "does not instantiate the distributed mirror").  The worker does have a
local filesystem path, selected when ``settings.distributed_requested`` is false.

The wrapper, however, never pinned the storage backends.  ``Settings`` reads a
repo-root ``.env``, so any non-empty ``LACLAUGPT_MONGODB_URI`` combined with
``record_backend="auto"`` makes ``distributed_requested`` true and the tick dies
before doing any work::

    ValueError: invalid distributed configuration:
    distributed collection requires LACLAUGPT_RUN_ID

This is the same defect class #193 fixed for the collect wrapper.  The
pre-existing wrapper tests only asserted that the wrapper invokes the worker, so
nothing caught the leak.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

MEDIA_WRAPPER = ROOT / "scripts/run_brazil26_localhost_media.sh"

# A repo-root .env that would otherwise flip the pass into the distributed plane.
DISTRIBUTED_SELECTORS = (
    "LACLAUGPT_RECORD_BACKEND",
    "LACLAUGPT_OBJECT_BACKEND",
    "LACLAUGPT_CACHE_BACKEND",
    "LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND",
    "LACLAUGPT_MESSAGING_BACKEND",
    "LACLAUGPT_TASK_QUEUE_BACKEND",
    "LACLAUGPT_MONGODB_URI",
    "LACLAUGPT_REDIS_URL",
    "LACLAUGPT_S3_BUCKET",
)


@pytest.fixture(scope="module")
def media_text() -> str:
    return MEDIA_WRAPPER.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", DISTRIBUTED_SELECTORS)
def test_media_wrapper_pins_every_distributed_selector(media_text: str, name: str) -> None:
    """Each distributed selector must be explicitly assigned by the wrapper.

    Leaving one unset lets a repo-root .env reach ``Settings`` and turn this local
    pass into a distributed one.
    """
    assert re.search(rf"^\s*export\s+{name}=", media_text, re.MULTILINE), (
        f"{MEDIA_WRAPPER.name} does not pin {name}; a repo-root .env can then "
        "switch the localhost media pass into the distributed plane"
    )


def test_media_wrapper_clears_remote_endpoints(media_text: str) -> None:
    """MongoDB/Redis/S3 endpoints must be cleared, not merely overridden."""
    for name in ("LACLAUGPT_MONGODB_URI", "LACLAUGPT_REDIS_URL", "LACLAUGPT_S3_BUCKET"):
        assert re.search(rf"^\s*export\s+{name}=$", media_text, re.MULTILINE), (
            f"{MEDIA_WRAPPER.name} must clear {name} (export {name}=) so a "
            "repo-root .env cannot point the localhost media pass at a remote host"
        )


def test_media_wrapper_selects_local_storage(media_text: str) -> None:
    """The local-first backend set that ``distributed_requested`` inspects."""
    expected = {
        "LACLAUGPT_RECORD_BACKEND": "csv",
        "LACLAUGPT_OBJECT_BACKEND": "filesystem",
        "LACLAUGPT_CACHE_BACKEND": "memory",
        "LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND": "local",
        "LACLAUGPT_MESSAGING_BACKEND": "none",
        "LACLAUGPT_TASK_QUEUE_BACKEND": "direct",
    }
    for name, value in expected.items():
        assert re.search(rf"^\s*export\s+{name}={value}\s*$", media_text, re.MULTILINE), (
            f"{MEDIA_WRAPPER.name} must export {name}={value} for the local profile"
        )


def test_media_wrapper_leaves_remote_mirroring_to_the_sync_step(media_text: str) -> None:
    """Local pinning is a deliberate design choice, not an accident."""
    lowered = media_text.lower()
    assert "zero-infrastructure" in lowered or "local-first" in lowered
    assert "run_brazil26_localhost_sync.sh" in media_text
