"""Collect configured Mastodon actors without substituting public timelines."""
import pytest

from laclaugpt_data_collection import ai26_laskin_runner as runner
from laclaugpt_data_collection.collectors.mastodon import MastodonCollectionError, MastodonCollector


class Client:
    def __init__(self, resolved="researcher"):
        self.resolved = resolved
        self.calls = []

    def account_lookup(self, acct):
        self.calls.append(("lookup", acct))
        return {"id": "42", "acct": self.resolved}

    def account_statuses(self, account_id, **kwargs):
        self.calls.append(("statuses", account_id, kwargs))
        return [{
            "id": "100", "url": "https://example.invalid/@researcher/100",
            "account": {"acct": "researcher", "id": "42"},
            "content": "<p>Synthetic AI governance text</p>",
            "created_at": "2026-10-01T00:00:00Z", "language": "fi",
        }]

    def timeline_public(self, **kwargs):
        pytest.fail("Named actors must never become public timeline samples")


def test_actor_lookup_statuses_limit_cursor_and_provenance():
    client = Client()
    result = MastodonCollector(
        "https://example.invalid", acct="@researcher@example.invalid", limit=3,
        cursor="101", client=client,
    ).collect()
    assert client.calls == [
        ("lookup", "researcher@example.invalid"),
        ("statuses", "42", {"limit": 3, "max_id": "101"}),
    ]
    assert result.requests_seen == 2
    assert result.next_cursor == "100"
    record = result.records[0]
    assert record.source.language == "fi"
    assert record.source.raw_metadata["configured_acct"] == "researcher@example.invalid"


def test_wrong_actor_fails_without_timeline_fallback():
    client = Client("someone_else")
    with pytest.raises(MastodonCollectionError, match="did not match"):
        MastodonCollector("https://example.invalid", acct="researcher", client=client).collect()
    assert len(client.calls) == 1


def test_runner_uses_home_instance_and_stamps_sampling_provenance(monkeypatch):
    client = Client()
    monkeypatch.setattr(MastodonCollector, "_client", lambda self: client)
    records, warnings = runner._records_for_job(
        {"kind": "mastodon_account", "name": "Synthetic researcher",
         "acct": "@researcher@example.invalid", "arena": "elites", "priority": "P1"},
        collection_id="ai26", worker_id="test", per_source_limit=5,
    )
    assert warnings == []
    assert records[0].source.raw_metadata["arena"] == "elites"
    assert records[0].source.raw_metadata["source_name"] == "Synthetic researcher"
    assert records[0].provenance[-1].api_url == "https://example.invalid"
    assert client.calls[-1][2]["limit"] == 5


@pytest.mark.parametrize("acct", ["", "researcher", "@user@host/path", "@user@host?token=x"])
def test_invalid_acct_is_a_configuration_failure(acct):
    with pytest.raises(runner.SourceJobError, match="invalid_mastodon_acct"):
        runner._records_for_job(
            {"kind": "mastodon_account", "acct": acct},
            collection_id="ai26", worker_id="test", per_source_limit=5,
        )
