"""A bridge-captured X record can prove its own identity from the URL it came from (#470).

The 609 records behind #470 carry no ``source.platform``, no ``source.author`` and no source name;
the only surviving field is the ``x.com`` ``source_url``. Reading that URL is not guessing — the
host and path decide — but anything ambiguous must stay unattributed so the audit can count it.
"""
from __future__ import annotations

import pytest

from laclaugpt_data_collection.arena_backfill import identity, plan_update
from scripts.backfill_ai26_x_arenas import resolve_record

DECLARED = [
    {"name": "Demis Hassabis", "platform": "x", "handle": "demishassabis",
     "group_id": "frontier_labs_x", "arena": "elites"},
]


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://x.com/demishassabis/status/123", ("x", "demishassabis")),
        ("https://twitter.com/Tegmark/status/9", ("x", "Tegmark")),
        ("https://x.com/demishassabis", ("x", "demishassabis")),
        ("https://other.example/demishassabis", ("", "")),
        ("https://x.com/home", ("", "")),
        ("https://x.com/i/web/status/1", ("", "")),
        ("", ("", "")),
    ],
)
def test_identity_is_proven_from_the_url_or_not_at_all(url, expected) -> None:
    assert identity({"platform": "", "author": "", "source_url": url}) == expected


def test_a_declared_handle_fills_arena_even_when_platform_was_blank() -> None:
    document = {
        "arena": "",
        "source": {
            "platform": "",
            "author": "",
            "source_url": "https://x.com/demishassabis/status/123",
            "raw_metadata": {},
        },
    }
    update = plan_update(document, DECLARED)
    assert update is not None
    assert update["arena"] == "elites"
    assert update["source.platform"] == "x"
    assert update["source.author"] == "demishassabis"


def test_an_undeclared_handle_stays_unattributed_even_with_a_proven_url() -> None:
    document = {
        "arena": "",
        "source": {"platform": "", "author": "", "source_url": "https://x.com/stranger/status/1",
                   "raw_metadata": {}},
    }
    assert plan_update(document, DECLARED) is None


def test_a_declared_non_x_platform_is_not_repaired_from_an_x_url() -> None:
    document = {
        "arena": "",
        "source": {"platform": "web", "author": "", "source_url": "https://x.com/demishassabis/status/1",
                   "raw_metadata": {}},
    }
    assert plan_update(document, DECLARED) is None


def test_the_guarded_script_uses_the_same_proof_and_still_refuses_conflicts() -> None:
    mapping = {"demishassabis": ("elites", "frontier")}
    row = {"source": {"platform": "", "author": "",
                      "source_url": "https://x.com/demishassabis/status/1", "raw_metadata": {}}}
    assert resolve_record(row, mapping) == ("elites", "frontier")
    # A URL proving one handle and an author proving another is a conflict, not a repair.
    conflict = {"source": {"platform": "x", "author": "tegmark",
                           "source_url": "https://x.com/demishassabis/status/1", "raw_metadata": {}}}
    assert resolve_record(conflict, {**mapping, "tegmark": ("elites", "frontier")}) is None
