"""Raw captures must not keep credentials (#378).

The Firefox extension posts every X GraphQL response. Some of them carry live bearer
tokens (``grok_account_jwt`` was observed on this workstation), and the capture server
stored them verbatim under ``data/<study>/raw/``. Redaction happens in
``CollectionStore.append_raw`` so every platform and every caller gets it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from laclaugpt_data_collection.store import (  # noqa: E402
    REDACTED,
    CollectionStore,
    redact_secrets,
)

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop"


def test_a_token_field_is_redacted_but_its_siblings_survive() -> None:
    payload = {"data": {"grok_account_jwt": {"grok_user_id": "1", "status": "OK", "token": JWT}}}
    cleaned = redact_secrets(payload)
    node = cleaned["data"]["grok_account_jwt"]
    assert node["token"] == REDACTED
    assert node["grok_user_id"] == "1"
    assert node["status"] == "OK"


def test_a_jwt_hidden_inside_ordinary_text_is_redacted() -> None:
    cleaned = redact_secrets({"text": f"prefix {JWT} suffix"})
    assert JWT not in cleaned["text"]
    assert REDACTED in cleaned["text"]


def test_timeline_payloads_are_untouched() -> None:
    payload = {
        "data": {"user": {"result": {"timeline": {"instructions": [
            {"type": "TimelineAddEntries", "entries": [{"content": {"itemContent": {
                "tweet_results": {"result": {"legacy": {"full_text": "hello"}}}}}}]}
        ]}}}}
    }
    assert redact_secrets(payload) == payload


def test_lists_and_common_credential_keys_are_covered() -> None:
    cleaned = redact_secrets({"items": [{"api_key": "abc"}, {"cookie": "c"}, {"n": 2}]})
    assert cleaned["items"][0]["api_key"] == REDACTED
    assert cleaned["items"][1]["cookie"] == REDACTED
    assert cleaned["items"][2]["n"] == 2


def test_append_raw_writes_the_redacted_payload(tmp_path: Path) -> None:
    store = CollectionStore(tmp_path)
    ref = store.append_raw("x", {"data": {"grok_account_jwt": {"token": JWT}}, "ts": "t"})
    written = (tmp_path / ref).read_text(encoding="utf-8")
    assert JWT not in written
    assert json.loads(written)["data"]["grok_account_jwt"]["token"] == REDACTED
    store.close()
