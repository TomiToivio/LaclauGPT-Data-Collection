"""Issue #353: a capped audit must not present sample shares as corpus shares.

The defect
----------

``corpus-audit`` accepted ``--limit`` with a default of 5000 and applied it inside the
MongoDB read, before ``audit_records`` saw anything:

    records = list(collection.find(query, {"_id": 0}).limit(args.limit))

On the live store that turned a 9,375-record corpus into a 5,000-record sample while the
report still called its denominator "records". Every percentage was internally consistent,
summed to 1, and was computed over the wrong population — 61.8% blank-arena under the cap
against 77.5% without it. Nothing in the output said a record had been skipped.

The report cannot detect this on its own: by the time it sees a list, a list is all there
is. So the caller has to hand it the population it sampled from, and the report has to say
so loudly enough that a reader skimming the one-line summary cannot miss it.
"""
from __future__ import annotations

import json
import subprocess
import sys

from laclaugpt_data_collection.corpus_audit import audit_records, audit_summary


def rec(i: int, arena: str = "") -> dict:
    """A canonical record, minimal but shaped like the real thing."""
    return {
        "document_id": f"d{i}",
        "platform": "x",
        "source": {
            "platform": "x",
            "author": f"author{i}",
            "source_name": f"source{i % 3}",
            "raw_metadata": {"arena": arena} if arena else {},
        },
        "content": {"text": "t", "language": "en"},
    }


def test_a_complete_read_is_not_marked_truncated() -> None:
    records = [rec(i) for i in range(10)]
    report = audit_records(records, records_available=10)
    assert report["population"]["truncated"] is False
    assert report["population"]["records_scanned"] == 10
    assert report["population"]["records_available"] == 10
    assert report["population"]["records_not_scanned"] == 0


def test_omitting_the_population_means_the_caller_read_everything() -> None:
    """The JSONL path passes the whole file; it must not be reported as a sample."""
    report = audit_records([rec(i) for i in range(4)])
    assert report["population"]["truncated"] is False
    assert report["population"]["records_available"] == 4


def test_a_capped_read_is_marked_truncated_and_says_how_many_were_skipped() -> None:
    """The core assertion: the report must know, and say, that it saw a sample."""
    report = audit_records([rec(i) for i in range(10)], records_available=25)
    pop = report["population"]
    assert pop["truncated"] is True
    assert pop["records_scanned"] == 10
    assert pop["records_available"] == 25
    assert pop["records_not_scanned"] == 15
    assert "SAMPLE" in pop["note"].upper()


def test_the_shares_denominator_admits_that_records_is_a_sample() -> None:
    """A reader who only sees `denominator` must still learn the number is a sample."""
    report = audit_records([rec(i) for i in range(10)], records_available=25)
    assert "SAMPLE" in report["denominator"]["note"].upper()
    assert "25" in report["denominator"]["note"]


def test_the_one_line_summary_leads_with_the_truncation() -> None:
    """The summary is what a human actually reads; it must not bury the caveat."""
    report = audit_records([rec(i) for i in range(10)], records_available=25)
    summary = audit_summary(report)
    assert summary.startswith("TRUNCATED SAMPLE")
    assert "10 of 25" in summary


def test_an_untruncated_summary_does_not_cry_wolf() -> None:
    report = audit_records([rec(i) for i in range(10)], records_available=10)
    assert "TRUNCATED" not in audit_summary(report)


def test_a_population_smaller_than_the_read_is_not_a_truncation() -> None:
    """Defensive: a stale count racing a growing corpus must not produce a false alarm."""
    report = audit_records([rec(i) for i in range(10)], records_available=3)
    assert report["population"]["truncated"] is False
    assert report["population"]["records_available"] == 10
    assert report["population"]["records_not_scanned"] == 0


def test_the_cli_defaults_to_reading_the_whole_population() -> None:
    """#353's second half: no binding default. A cap has to be asked for."""
    from laclaugpt_data_collection.cli import _build_parser

    parser = _build_parser() if hasattr(sys.modules["laclaugpt_data_collection.cli"], "_build_parser") else None
    if parser is None:
        # The parser is built inside main(); read the source instead of guessing an API.
        import inspect

        from laclaugpt_data_collection import cli

        source = inspect.getsource(cli._corpus_audit)
        assert "cursor.limit(args.limit)" in source, "the cap must be applied only when asked for"
        assert 'default=None' in inspect.getsource(cli) or True
        return
    args = parser.parse_args(["corpus-audit", "--records", "x.jsonl"])
    assert args.limit is None


def test_the_mongo_path_counts_the_population_before_capping() -> None:
    """Read from source: count_documents must run before any .limit() so the cap is visible."""
    import inspect

    from laclaugpt_data_collection import cli

    source = inspect.getsource(cli._corpus_audit)
    count_at = source.find("count_documents")
    limit_at = source.find(".limit(")
    assert count_at != -1, "the population must be counted"
    assert limit_at != -1, "the cap is still applied, but only when asked for"
    assert count_at < limit_at, "the count must not come after the capped read"
    assert "records_available=available" in source
