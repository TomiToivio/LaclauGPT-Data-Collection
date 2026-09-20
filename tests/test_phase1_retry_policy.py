from collections.abc import Iterable
from typing import Any

import pytest

from laclaugpt_data_collection.collectors.base import CollectionResult
from laclaugpt_data_collection.models import CanonicalRecord, NormalizedRecord
from laclaugpt_data_collection.plugins import (
    CollectionContext,
    CollectionRunError,
    CollectionRunner,
    PluginRegistry,
    PluginSpec,
    RetryPolicy,
    adapt_collector,
)


class MemoryStore:
    def __init__(self) -> None:
        self.records: dict[str, CanonicalRecord] = {}

    def contains(self, source_url: str) -> bool:
        return source_url in self.records

    def upsert(self, record: CanonicalRecord) -> None:
        self.records[record.source_url] = record

    def upsert_many(self, records: Iterable[CanonicalRecord]) -> None:
        for record in records:
            self.upsert(record)


class RetryableFailure(RuntimeError):
    retryable = True

    def __init__(self, message: str, *, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _record(source_url: str = "urn:synthetic:retry") -> NormalizedRecord:
    return NormalizedRecord(
        document_id="retry-1",
        platform="synthetic",
        source_url=source_url,
        text="retry fixture",
        raw_payload={"synthetic": True},
        raw_content_type="application/json",
    )


def _registry(factory: Any) -> PluginRegistry:
    registry = PluginRegistry()
    registry.register(
        adapt_collector(
            PluginSpec(
                plugin_id="synthetic-retry",
                version="1.0.0",
                source_type="api",
                modes=("polling",),
            ),
            factory,
        )
    )
    return registry


def test_transient_failure_recovers_with_bounded_backoff_and_reports_attempts() -> None:
    attempts = 0
    sleeps: list[float] = []

    class Collector:
        def collect(self) -> CollectionResult:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RetryableFailure("temporary")
            return CollectionResult(records=[_record()], warnings=["partial source warning"])

    runner = CollectionRunner(
        _registry(lambda _context: Collector()),
        MemoryStore(),
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.5, max_delay_seconds=5),
        sleep=sleeps.append,
    )
    result = runner.run("synthetic-retry", CollectionContext(collection_id="AI26"))

    assert attempts == 3
    assert sleeps == [0.5, 1.0]
    assert result.attempts == 3
    assert result.records_written == 1
    assert result.warnings == ["partial source warning"]


def test_retry_after_is_preserved_and_used_for_rate_limit_backoff() -> None:
    attempts = 0
    sleeps: list[float] = []

    class Collector:
        def collect(self) -> CollectionResult:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RetryableFailure("rate limited", retry_after="17")
            return CollectionResult(records=[_record()])

    runner = CollectionRunner(
        _registry(lambda _context: Collector()),
        MemoryStore(),
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=1, max_delay_seconds=30),
        sleep=sleeps.append,
    )
    result = runner.run("synthetic-retry", CollectionContext())

    assert result.attempts == 2
    assert sleeps == [17.0]


def test_deterministic_validation_failure_is_not_retried() -> None:
    attempts = 0
    sleeps: list[float] = []

    class Collector:
        def collect(self) -> CollectionResult:
            nonlocal attempts
            attempts += 1
            raise ValueError("bad configuration")

    runner = CollectionRunner(
        _registry(lambda _context: Collector()),
        MemoryStore(),
        retry_policy=RetryPolicy(max_attempts=5),
        sleep=sleeps.append,
    )

    with pytest.raises(CollectionRunError) as captured:
        runner.run("synthetic-retry", CollectionContext())

    assert attempts == 1
    assert sleeps == []
    assert captured.value.attempts == 1
    assert captured.value.retryable is False
    assert isinstance(captured.value.cause, ValueError)


def test_retryable_failure_stops_exactly_at_max_attempts_and_preserves_state() -> None:
    attempts = 0
    sleeps: list[float] = []

    class Collector:
        def collect(self) -> CollectionResult:
            nonlocal attempts
            attempts += 1
            raise RetryableFailure("still rate limited", retry_after="9")

    runner = CollectionRunner(
        _registry(lambda _context: Collector()),
        MemoryStore(),
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=1, max_delay_seconds=20),
        sleep=sleeps.append,
    )

    with pytest.raises(CollectionRunError) as captured:
        runner.run("synthetic-retry", CollectionContext())

    assert attempts == 3
    assert sleeps == [9.0, 9.0]
    assert captured.value.attempts == 3
    assert captured.value.retryable is True
    assert captured.value.retry_after == "9"


def test_retry_success_then_rerun_remains_idempotent() -> None:
    calls = 0
    store = MemoryStore()

    class Collector:
        def collect(self) -> CollectionResult:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RetryableFailure("one transient")
            return CollectionResult(records=[_record()])

    runner = CollectionRunner(
        _registry(lambda _context: Collector()),
        store,
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0),
        sleep=lambda _seconds: None,
    )

    first = runner.run("synthetic-retry", CollectionContext())
    second = runner.run("synthetic-retry", CollectionContext())

    assert first.records_written == 1
    assert second.records_written == 0
    assert second.duplicates_skipped == 1
    assert list(store.records) == ["urn:synthetic:retry"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_attempts": 0}, "max_attempts"),
        ({"base_delay_seconds": -1}, "base_delay_seconds"),
        ({"max_delay_seconds": -1}, "max_delay_seconds"),
    ],
)
def test_retry_policy_rejects_unbounded_or_invalid_values(
    kwargs: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        RetryPolicy(**kwargs)
