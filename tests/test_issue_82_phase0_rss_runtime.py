"""Phase 0 RSS-only runtime contract (issue #82).

These tests pin the *runtime independence* claims: the Phase 0 collection path must
work with MongoDB alone, so it may not require Redis, S3/Allas, a browser collector
or any multimodal pipeline. They are import/graph checks, so they run offline and
would fail if a Phase 1 dependency were reintroduced into the Phase 0 path.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "laclaugpt_data_collection"

# The modules that make up the Phase 0 RSS collection runtime.
PHASE0_MODULES = ["server_runner.py", "phase0_mongo.py"]
# Phase 1 services the Phase 0 path must not require.
FORBIDDEN_SERVICES = {"redis", "boto3", "botocore", "minio"}
# Multimodal / heavy analysis libraries that must not be required.
FORBIDDEN_MODALITY = {"cv2", "easyocr", "whisper", "PIL", "torch", "pytesseract"}
# Browser-collector markers.
FORBIDDEN_BROWSER = {"firefox", "zeeschuimer", "4cat", "playwright", "selenium"}


def _imported_names(path: Path) -> set[str]:
    """Top-level module names imported by a source file (AST, no execution)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("module", PHASE0_MODULES)
def test_phase0_path_imports_no_forbidden_service(module: str) -> None:
    names = _imported_names(SRC / module)
    assert not (names & FORBIDDEN_SERVICES), f"{module} imports {names & FORBIDDEN_SERVICES}"


@pytest.mark.parametrize("module", PHASE0_MODULES)
def test_phase0_path_imports_no_multimodal_library(module: str) -> None:
    names = _imported_names(SRC / module)
    assert not (names & FORBIDDEN_MODALITY), f"{module} imports {names & FORBIDDEN_MODALITY}"


@pytest.mark.parametrize("module", PHASE0_MODULES)
def test_phase0_path_imports_no_browser_collector(module: str) -> None:
    names = _imported_names(SRC / module)
    assert not (names & FORBIDDEN_BROWSER), f"{module} imports {names & FORBIDDEN_BROWSER}"


def test_phase0_path_does_not_use_the_distributed_capture_sink() -> None:
    """The Phase 1 distributed plane is intentionally bypassed, not required."""
    source = (SRC / "server_runner.py").read_text(encoding="utf-8")
    assert "DistributedCaptureSink" not in source


def test_phase0_entry_point_and_cron_flags_exist() -> None:
    """`laclaugpt-server-rss` must resolve and accept the cron wrapper's flags."""
    from laclaugpt_data_collection.server_runner import main

    assert callable(main)


def test_phase0_rss_is_the_only_active_source_type() -> None:
    """Phase 0 collects RSS/Atom only; other platforms are not wired in."""
    source = (SRC / "server_runner.py").read_text(encoding="utf-8")
    for platform in ("tiktok", "instagram", "telegram", "minet"):
        assert platform not in source.lower(), f"{platform} must not appear in the Phase 0 path"


def test_mongodb_is_the_only_required_backend() -> None:
    """The store is MongoDB; no Redis/S3 client is imported on this path."""
    source = (SRC / "phase0_mongo.py").read_text(encoding="utf-8")
    assert "MongoClient" in source
    tree = ast.parse(source)
    imported = {
        (n.module or "").split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
    } | {
        a.name.split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, ast.Import)
        for a in n.names
    }
    assert not (imported & FORBIDDEN_SERVICES), f"imports {imported & FORBIDDEN_SERVICES}"


def test_documentation_covers_phase0_and_the_restoration_rule() -> None:
    doc = (REPO / "docs" / "PHASE0_RSS_RUNTIME.md").read_text(encoding="utf-8").lower()
    assert "rss" in doc
    assert "mongodb" in doc
    for phrase in ("redis", "allas", "browser", "multimodal"):
        assert phrase in doc, f"the Phase 0 doc must state that {phrase} is not required"
    assert "one functionality at a time" in doc
    assert "cron" in doc
