"""Issue LaclauGPT#71 — the NooPunk browser-collection node.

NooPunk's duty is the always-on browser capture that Laskin cannot do, so the risks
this guards are narrow and concrete:

1. **The runbook naming a mechanism that does not exist.** It deliberately adds no
   script, so every command and file it points at must be real — otherwise the
   operator is sent looking for something that was never written.
2. **Two corpora instead of one.** NooPunk must write into the shared AI26
   namespace, never a node-local database, bucket or project id.
3. **A schedule that collides with Laskin.** Both nodes upsert into the same
   collections; a tick on Laskin's own minutes would contend for the same backends.
4. **Secrets in a public repository.**
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NOOPUNK_DOC = ROOT / "docs" / "AI26_NOOPUNK_COLLECTION.md"
LOCALHOST_DOC = ROOT / "docs" / "AI26_LOCALHOST_COLLECTION.md"
TWO_MACHINE_DOC = ROOT / "docs" / "AI26_TWO_MACHINE_COLLECTION.md"

#: Everything the NooPunk runbook tells an operator to use must exist.
REFERENCED_PATHS = (
    "scripts/run_ai26_localhost_collect.sh",
    "scripts/run_ai26_localhost_media.sh",
    "scripts/run_ai26_localhost_sync.sh",
    "scripts/ai26_runtime.sh",
    "configs/studies/ai26.example.yaml",
    "configs/studies/ai26.sources.example.toml",
    "configs/studies/ai26.collection-codebook.yaml",
    ".env.example",
    "docs/AI26_LOCALHOST_COLLECTION.md",
    "docs/AI26_TWO_MACHINE_COLLECTION.md",
    "docs/AI26_LASKIN_COLLECTION.md",
    "docs/BROWSER_CAPTURE.md",
    "docs/CANONICAL_RECORD_CONTRACT.md",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_noopunk_runbook_exists_and_is_public_safe() -> None:
    assert NOOPUNK_DOC.exists(), "the NooPunk collection runbook is missing"
    text = _text(NOOPUNK_DOC)
    assert "always-on" in text.lower()
    assert "browser" in text.lower()


def test_every_referenced_mechanism_actually_exists() -> None:
    """The runbook adds no script, so every path it names must be real."""
    for relative in REFERENCED_PATHS:
        assert (ROOT / relative).exists(), (
            f"the NooPunk runbook references {relative}, which does not exist"
        )


def test_noopunk_runbook_reuses_the_existing_localhost_wrappers() -> None:
    """No duplicated collection machinery: the same wrappers, a different role."""
    text = _text(NOOPUNK_DOC)
    for script in (
        "run_ai26_localhost_collect.sh",
        "run_ai26_localhost_media.sh",
        "run_ai26_localhost_sync.sh",
    ):
        assert script in text, f"the runbook does not use {script}"
    assert "adds no script" in text or "reuses" in text.lower()


def test_noopunk_does_not_define_a_local_namespace() -> None:
    """Machine identity is provenance; it must never become study identity."""
    text = _text(NOOPUNK_DOC)
    for invented in (
        "noopunk__records",
        "LACLAUGPT_PROJECT_ID=noopunk",
        "LACLAUGPT_MONGODB_DATABASE=noopunk",
        "noopunk-bucket",
    ):
        assert invented not in text, f"the runbook invents {invented!r}"
    assert "never study identity" in text, (
        "the runbook must state that machine identity is never study identity"
    )


def test_noopunk_uses_the_workstation_machine_class() -> None:
    text = _text(NOOPUNK_DOC)
    assert "LACLAUGPT_MACHINE=laptop" in text


def test_schedule_advice_avoids_laskins_minutes() -> None:
    """Both nodes share one sink, so a colliding tick contends for the same backends.

    Laskin's own cadence is :10 collection and :30 media (see the two-machine
    document). The existing localhost installer uses :10 for sync, which collides;
    the NooPunk guidance must not repeat that.
    """
    two_machine = _text(TWO_MACHINE_DOC)
    assert "hourly :10" in two_machine.replace("  ", " ") or ":10" in two_machine
    assert "hourly :30" in two_machine.replace("  ", " ") or ":30" in two_machine

    text = _text(NOOPUNK_DOC)
    assert "collides with Laskin" in text, (
        "the runbook must warn that the existing :10 sync tick collides with Laskin"
    )
    # the recommended schedule must not reuse :10 or :30
    recommended = re.findall(r"^:(\d\d)\s+(sync|capture|media)", text, re.MULTILINE)
    assert recommended, "the runbook does not give a concrete schedule"
    chosen = {minute for minute, _ in recommended}
    assert "10" not in chosen, "the recommended schedule collides with Laskin at :10"
    assert "30" not in chosen, "the recommended schedule collides with Laskin at :30"


def test_runbook_states_collection_survives_analysis_and_visualization_stopping() -> None:
    text = " ".join(_text(NOOPUNK_DOC).split()).lower()
    assert "even when analysis and visualization are stopped" in text


def test_runbook_states_capture_does_not_depend_on_laskin() -> None:
    text = " ".join(_text(NOOPUNK_DOC).split()).lower()
    assert "must not depend on laskin being up" in text or "independent" in text


def test_noopunk_doc_contains_no_credential_or_private_path() -> None:
    text = _text(NOOPUNK_DOC)
    for pattern in (
        r"mongodb(\+srv)?://[^\s\"']*" + ":" + r"[^\s\"']*@",
        r"redis://[^\s\"']*" + ":" + r"[^\s\"']*@",
        r"AKIA[0-9A-Z]{16}",
        r"(?i)password\s*=\s*[^\s\"']+",
    ):
        assert re.search(pattern, text) is None, "the runbook may contain a credential"
    for prefix in ("/home/", "/Users/", "/mnt/"):
        assert prefix not in text, f"the runbook hard-codes {prefix}"


def test_two_machine_doc_still_assigns_the_browser_role_to_a_workstation() -> None:
    """Guard the premise: if Laskin ever claims browser capture, revisit this file."""
    text = " ".join(_text(TWO_MACHINE_DOC).split()).lower()
    assert "researcher laptop" in text or "browser-assisted capture" in text
    assert "never enable a browser" in text, (
        "the two-machine doc no longer forbids browser collection on the collector host"
    )


def test_noopunk_runbook_keeps_firefox_tooling_compatibility() -> None:
    text = " ".join(_text(NOOPUNK_DOC).split()).lower()
    assert "firefox" in text
    assert "compatibility" in text
