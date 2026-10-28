"""Issue #378, localhost slice: one queue identity across hosts.

The queue is only a de-duplication mechanism if two hosts reading the same manifest address the same
entry. On 2026-10-28 a live run on the WSL host proved they did not: Laskin held
``bluesky_account:Timnit Gebru`` (the manifest's ``name``) while the localhost collector queued
``bluesky_account:timnitgebru.blacksky.app`` (the ``handle``) and then claimed a job it could not
match to any manifest row.
"""
from __future__ import annotations

import pytest

from laclaugpt_data_collection.ai26_localhost_collect import _manifest_jobs
from laclaugpt_data_collection.distributed_jobs import job_identity

#: The row shape both hosts read from ai26.sources.toml.
BLUESKY_ROW = {"name": "Timnit Gebru", "handle": "timnitgebru.blacksky.app", "priority": "P1"}
SCHOLARLY_ROW = {"name": "frontier_ai_safety", "services": ["arxiv", "openalex"],
                 "query": "(AGI OR frontier AI) AND safety", "priority": "P1"}


def test_identity_uses_the_manifest_name_not_the_handle() -> None:
    jobs = _manifest_jobs({"bluesky_account": [BLUESKY_ROW], "scholarly_query": [SCHOLARLY_ROW]})
    names = {job["kind"]: job["name"] for job in jobs}
    assert names == {"bluesky_account": "Timnit Gebru",
                     "scholarly_query": "frontier_ai_safety"}


def test_identity_falls_back_to_handle_or_query_without_a_name() -> None:
    jobs = _manifest_jobs({"bluesky_account": [{"handle": "someone.bsky.social"}],
                           "scholarly_query": [{"query": "alg gov", "services": ["arxiv"]}]})
    names = {job["kind"]: job["name"] for job in jobs}
    assert names == {"bluesky_account": "someone.bsky.social", "scholarly_query": "alg gov"}


def test_the_localhost_and_the_runner_address_the_same_queue_entry() -> None:
    """The property the queue depends on: one source, one job id, on every host."""
    jobs = _manifest_jobs({"bluesky_account": [BLUESKY_ROW], "scholarly_query": [SCHOLARLY_ROW]})
    localhost_ids = {job_identity(job) for job in jobs}
    # This is how ai26_laskin_runner.load_non_browser_jobs + job_identity see the same rows:
    runner_ids = {job_identity({"kind": "bluesky_account", **BLUESKY_ROW}),
                  job_identity({"kind": "scholarly_query", **SCHOLARLY_ROW})}
    assert localhost_ids == runner_ids
    assert localhost_ids == {"bluesky_account:Timnit Gebru",
                             "scholarly_query:frontier_ai_safety"}


def test_a_manifest_whose_rows_are_not_arxiv_is_left_out() -> None:
    jobs = _manifest_jobs({"scholarly_query": [{"name": "openalex_only",
                                                "services": ["openalex"], "query": "x"}]})
    assert jobs == []


@pytest.mark.parametrize("kind,row,expected", [
    ("bluesky_account", BLUESKY_ROW, "bluesky_account:Timnit Gebru"),
    ("scholarly_query", SCHOLARLY_ROW, "scholarly_query:frontier_ai_safety"),
])
def test_queue_ids_are_stable_across_reruns(kind, row, expected) -> None:
    assert job_identity({"kind": kind, **row}) == expected
