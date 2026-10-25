"""A capture must carry the arena the study config declares (issue #336).

40% of the analysis-grade AI26 corpus had a blank `arena`, and it arrived through
one path: the browser capture envelope. `groups:` in the study config maps every X
handle to an arena -- elites, grassroots, parliamentary -- and every manifest row
declared one, but only the composed ``name:handle`` string was carried into the
record. The actor→arena relation was discarded at the moment of capture.

A record with a blank arena cannot enter the paper's arena stratification at all,
so this is a corpus defect, not a labelling nicety. The external-link children of an
X post inherit the parent's arena, which is why one fix repairs both populations.
"""
from __future__ import annotations

import types

from laclaugpt_data_collection.capture_server import Handler, capture_meta_for_account
from laclaugpt_data_collection.normalize import normalise


def test_the_configured_mapping_is_carried_not_inferred():
    row = {"name": "Laboratory X", "handle": "LabX", "arena": "elites", "platform": "x"}
    assert capture_meta_for_account(row) == {
        "arena": "elites",
        "source_name": "Laboratory X",
    }


def test_a_row_that_declares_nothing_contributes_nothing():
    """No arena is invented for a handle the study has not classified."""
    assert capture_meta_for_account({"name": "Someone", "handle": "h", "arena": ""}) == {
        "source_name": "Someone"
    }
    assert capture_meta_for_account(None) == {}
    assert capture_meta_for_account({}) == {}


def test_a_browser_captured_record_gains_arena_and_source_name():
    """The envelope's declared fields reach `source.raw_metadata`."""
    record = normalise(
        "x",
        {
            "id": "123",
            "author": "Somebody",
            "timestamp": "2026-10-20T10:00:00Z",
            "body": "a post",
            "link": "https://example.invalid/123",
        },
        metadata={
            "captured_at": "2026-10-20T10:01:00Z",
            "project_id": "ai26",
            "collection_id": "ai26",
            "arena": "elites",
            "source_name": "Laboratory X",
        },
    )

    assert record.source.raw_metadata["arena"] == "elites"
    assert record.source.raw_metadata["source_name"] == "Laboratory X"


def test_an_undeclared_arena_stays_absent_rather_than_blank():
    """Absent and empty are different facts; do not manufacture a key."""
    record = normalise(
        "x",
        {"id": "124", "author": "a", "body": "b", "link": "https://example.invalid/124"},
        metadata={"project_id": "ai26", "collection_id": "ai26"},
    )

    assert "arena" not in record.source.raw_metadata
    assert "source_name" not in record.source.raw_metadata


def test_the_account_row_is_resolved_with_its_arena():
    """The row, not just its name, is what the capture needs."""
    server = types.SimpleNamespace(
        cfg=types.SimpleNamespace(
            accounts=lambda: [
                {"name": "Laboratory X", "handle": "LabX", "arena": "elites", "platform": "x"},
                {"name": "Union", "handle": "union", "arena": "grassroots", "platform": "x"},
            ]
        )
    )
    handler = Handler.__new__(Handler)
    handler.server = server

    row = Handler._account_row(handler, "x", "https://x.com/LabX")

    assert row is not None
    assert row["arena"] == "elites"
    assert Handler._account_for(handler, "x", "https://x.com/LabX") == "Laboratory X:LabX"
    assert Handler._account_row(handler, "x", "https://x.com/unknown") is None
    assert Handler._account_for(handler, "x", "https://x.com/unknown") == "unattributed"


def test_an_external_link_child_inherits_the_parents_arena(monkeypatch):
    """The second population: 200 of 216 ready web records were X children.

    `capture_server` builds a child's arena from the parent's record, so a parent
    without an arena produced children without an arena. With the parent carrying
    the declared mapping, the child inherits it.
    """
    import laclaugpt_data_collection.capture_server as capture_server

    seen: list[str] = []

    def fake_fetch(url, parent, *, collection_id, arena):
        seen.append(arena)
        return types.SimpleNamespace(record=None, error="synthetic")

    monkeypatch.setattr(capture_server, "fetch_web_child", fake_fetch)

    parent = normalise(
        "x",
        {
            "id": "999",
            "author": "Somebody",
            "timestamp": "2026-10-20T10:00:00Z",
            "body": "post with a link",
            "link": "https://example.invalid/999",
            "urls": ["https://news.example.invalid/article"],
        },
        metadata={"project_id": "ai26", "collection_id": "ai26", "arena": "grassroots"},
    ).model_dump(mode="json")

    server = types.SimpleNamespace(
        cfg=types.SimpleNamespace(
            study="ai26", link_fetch_failure_blocks_parent=False
        ),
        lock=__import__("threading").RLock(),
        stats={"web_fetch_errors": 0, "web_children": 0},
        store=types.SimpleNamespace(upsert_post=lambda *a, **k: False),
    )
    handler = Handler.__new__(Handler)
    handler.server = server

    Handler._fetch_web_children(handler, [parent])

    assert seen == ["grassroots"]
    assert server.stats["web_fetch_errors"] == 1
