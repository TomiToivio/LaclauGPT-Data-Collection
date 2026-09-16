"""Public-documentation privacy for the two-machine deployment pattern.

The two-role deployment doc describes real operational topology. It must stay
generic: environment-variable indirection only, never a real hostname, private
path, endpoint, bucket or project identifier.

This test encodes the rule that issue #16 states as "public docs show the
laptop/server invocation pattern using environment indirection only", so a
future edit cannot quietly commit the actual deployment details.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parents[1] / "docs" / "TWO_MACHINE_SETUP.md"

# Deployment specifics that must never appear in a public document.
FORBIDDEN_SUBSTRINGS = (
    "laskin",
    "/mnt/workspace",
    "laclaugpt-private",
    "totoivio",
    "c:\\users",
    "a3s.fi",
    "spectaclescraper",
    "guy_debord",
    "project_2009497",
)

_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# Long hex/base64 runs look like an access key or secret.
_OPAQUE_TOKEN = re.compile(r"\b[0-9a-f]{32,}\b|\b[A-Za-z0-9+/]{40,}={0,2}\b")
_CREDENTIAL_URL = re.compile(
    r"(?i)\b(?:mongodb(?:\+srv)?|redis|https?|s3)://[^\s/:@]+:[^\s/@]+@[^\s/]+"
)
_ABSOLUTE_PRIVATE_PATH = re.compile(r"/(?:home|mnt|opt|srv|var)/[A-Za-z0-9._-]+")
_WINDOWS_PATH = re.compile(r"[A-Za-z]:\\")


@pytest.fixture(scope="module")
def doc_text() -> str:
    assert DOC.is_file(), f"missing deployment doc: {DOC}"
    return DOC.read_text(encoding="utf-8")


def test_doc_contains_no_deployment_specific_strings(doc_text: str) -> None:
    lowered = doc_text.casefold()
    found = sorted(needle for needle in FORBIDDEN_SUBSTRINGS if needle in lowered)
    assert not found, f"deployment-specific details leaked into {DOC.name}: {found}"


def test_doc_contains_no_ip_addresses(doc_text: str) -> None:
    """Loopback is allowed (the browser role binds there); real hosts are not."""
    matches = sorted(set(_IPV4.findall(doc_text)))
    non_loopback = [ip for ip in matches if not ip.startswith("127.")]
    assert not non_loopback, f"non-loopback IP literal(s) in {DOC.name}: {non_loopback}"


def test_doc_contains_no_credential_bearing_urls(doc_text: str) -> None:
    matches = _CREDENTIAL_URL.findall(doc_text)
    assert not matches, f"credential-bearing URL(s) in {DOC.name}: {matches}"


def test_doc_contains_no_opaque_tokens(doc_text: str) -> None:
    matches = sorted(set(_OPAQUE_TOKEN.findall(doc_text)))
    assert not matches, f"opaque token-like value(s) in {DOC.name}: {matches}"


def test_doc_contains_no_absolute_paths(doc_text: str) -> None:
    private_hits = sorted(set(_ABSOLUTE_PRIVATE_PATH.findall(doc_text)))
    windows_hits = _WINDOWS_PATH.findall(doc_text)
    assert not private_hits, f"absolute private path(s) in {DOC.name}: {private_hits}"
    assert not windows_hits, f"Windows absolute path(s) in {DOC.name}: {windows_hits}"


def test_doc_uses_environment_indirection_and_placeholders(doc_text: str) -> None:
    """The doc must reference the run contract by variable, not by value."""
    for key in (
        "LACLAUGPT_PROJECT_ID",
        "LACLAUGPT_RUN_ID",
        "LACLAUGPT_PRIVATE_CONFIG_DIR",
        "LACLAUGPT_MONGODB_URI",
        "LACLAUGPT_REDIS_URL",
        "LACLAUGPT_S3_BUCKET",
    ):
        assert key in doc_text, f"{DOC.name} should reference {key}"

    # Deployment values appear as placeholders, never as literals.
    assert "<private>" in doc_text
    assert "<private-config-root>" in doc_text
