"""Issue #212: the AI26 Laskin path must honour the declared collector retry policy.

The study config declares ``collector_defaults.retry`` but only ``PluginRunner``
read it, so a transient arXiv HTTP 429/503 silently cost a whole tick's scholarly
records. These tests pin the orchestration-boundary retry that closes the hole.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from laclaugpt_data_collection import ai26_laskin_runner as runner
from laclaugpt_data_collection.collectors.base import CollectionResult
from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord
from laclaugpt_data_collection.plugins import RetryPolicy


class FakeHTTPStatusError(Exception):
    """Stand-in for arxiv.HTTPError without requiring the optional 'documents' extra."""

    def __init__(self, status: int) -> None:
        super().__init__(f"Page request resulted in HTTP {status}")
        self.status = status


def _study_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "ai26.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_retry_policy_is_read_from_the_study_config(tmp_path: Path) -> None:
    config = _study_config(
        tmp_path,
        """
collector_defaults:
  retry:
    max_attempts: 4
    initial_backoff_seconds: 5
    max_backoff_seconds: 45
""",
    )

    policy = runner.load_collector_retry_policy(config)

    assert policy == RetryPolicy(max_attempts=4, base_delay_seconds=5.0, max_delay_seconds=45.0)


def test_retry_policy_falls_back_to_defaults_on_missing_or_malformed_config(tmp_path: Path) -> None:
    no_retry = _study_config(tmp_path, "collector_defaults:\n  pagination:\n    max_pages_per_poll: 3\n")
    assert runner.load_collector_retry_policy(no_retry) == RetryPolicy()

    malformed = _study_config(
        tmp_path,
        "collector_defaults:\n  retry:\n    max_attempts: 0\n    initial_backoff_seconds: -1\n",
    )
    policy = runner.load_collector_retry_policy(malformed)
    assert policy.max_attempts == RetryPolicy().max_attempts
    assert policy.base_delay_seconds == RetryPolicy().base_delay_seconds

    assert runner.load_collector_retry_policy(tmp_path / "does-not-exist.yaml") == RetryPolicy()


def test_call_with_retry_recovers_from_a_transient_status(monkeypatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: slept.append(seconds))
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise FakeHTTPStatusError(429)
        return "ok"

    result = runner._call_with_retry(
        flaky,
        policy=RetryPolicy(max_attempts=3, base_delay_seconds=2.0, max_delay_seconds=30.0),
        is_retryable=lambda exc: runner._retryable_http_status(exc) in (429, 503),
    )

    assert result == "ok"
    assert calls["n"] == 3
    assert slept == [2.0, 4.0]


def test_call_with_retry_reraises_when_the_budget_is_exhausted_or_not_retryable(monkeypatch) -> None:
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

    exhausted = {"n": 0}

    def always_503() -> None:
        exhausted["n"] += 1
        raise FakeHTTPStatusError(503)

    with pytest.raises(FakeHTTPStatusError):
        runner._call_with_retry(
            always_503,
            policy=RetryPolicy(max_attempts=2),
            is_retryable=lambda exc: runner._retryable_http_status(exc) in (429, 503),
        )
    assert exhausted["n"] == 2

    terminal = {"n": 0}

    def hard_404() -> None:
        terminal["n"] += 1
        raise FakeHTTPStatusError(404)

    with pytest.raises(FakeHTTPStatusError):
        runner._call_with_retry(
            hard_404,
            policy=RetryPolicy(max_attempts=5),
            is_retryable=lambda exc: runner._retryable_http_status(exc) in (429, 503),
        )
    assert terminal["n"] == 1  # not retryable -> fail fast, no extra attempts


def test_scholarly_job_retries_a_transient_429_then_collects(monkeypatch) -> None:
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    record = NormalizedRecord(
        document_id="2609.12345",
        platform="arxiv",
        timestamp="2026-09-22T05:00:00Z",
        source_url="https://arxiv.org/abs/2609.12345",
        text="synthetic",
        raw_payload={},
        collection_provenance=CollectionProvenance(module="issue-212-test"),
    )

    class FlakyArxivCollector:
        attempts = 0

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def collect(self) -> CollectionResult:
            FlakyArxivCollector.attempts += 1
            if FlakyArxivCollector.attempts == 1:
                raise FakeHTTPStatusError(429)
            result = CollectionResult(requests_seen=1)
            result.records.append(record)
            return result

    monkeypatch.setattr(runner, "ArxivCollector", FlakyArxivCollector)

    records, warnings = runner._records_for_job(
        {"kind": "scholarly_query", "name": "ai_governance", "services": ["arxiv"], "query": "ai"},
        collection_id="ai26",
        worker_id="laskin-test",
        per_source_limit=5,
        retry_policy=RetryPolicy(max_attempts=3),
    )

    assert FlakyArxivCollector.attempts == 2
    assert warnings == []
    assert [r.source_url for r in records] == ["https://arxiv.org/abs/2609.12345"]
    assert records[0].source.raw_metadata["source_name"] == "ai_governance"
