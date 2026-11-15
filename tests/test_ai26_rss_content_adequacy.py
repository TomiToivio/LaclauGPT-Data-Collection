"""Regression contracts for AI26 headline-only RSS reporting (#416)."""
from pathlib import Path

import yaml

CODEBOOK = Path(__file__).resolve().parents[1] / "configs/studies/ai26.collection-codebook.yaml"


def test_rss_content_adequacy_audit_is_explicit():
    config = yaml.safe_load(CODEBOOK.read_text(encoding="utf-8"))
    audit = config["rss_content_adequacy"]
    assert audit["classification_unit"] == "record"
    assert audit["measurement_field"] == "content.text"
    assert audit["short_text_threshold_chars"] == 300
    assert audit["short_text_records"] == 708
    assert audit["audited_ready_records"] == 2070
    assert audit["audit_date"] == "2026-11-14"


def test_observed_headline_only_sources_have_complete_counts():
    audit = yaml.safe_load(CODEBOOK.read_text(encoding="utf-8"))["rss_content_adequacy"]
    rows = audit["headline_only_sources"]
    expected = {
        "tech_policy_press": (196, 196),
        "datacenterdynamics": (142, 141),
        "openai_news": (118, 118),
        "datacenterknowledge": (62, 62),
        "gary_marcus": (45, 45),
        "works_in_progress": (19, 19),
        "deepmind_blog_rss": (15, 15),
        "interconnects": (15, 15),
    }
    for source, (ready, short) in expected.items():
        assert rows[source]["audited_ready"] == ready
        assert rows[source]["audited_short"] == short
        assert rows[source]["reason"]
        assert 0 <= short <= ready
    gap = audit["parliamentary_language_gap_at_audit"]
    assert gap["records_without_language"] == 221
    assert gap["tech_policy_press_without_language"] == 185


def test_reporting_contract_disallows_silent_article_equivalence():
    audit = yaml.safe_load(CODEBOOK.read_text(encoding="utf-8"))["rss_content_adequacy"]
    rules = " ".join(audit["reporting_rules"]).lower()
    assert "separately" in rules
    assert "missing language" in rules
    assert "denominators" in rules
    assert "not source identity alone" in rules
    assert audit["limitations"]
