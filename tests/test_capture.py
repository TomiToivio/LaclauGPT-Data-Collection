from laclaugpt_data_collection.capture import BrowserCapture, deduplicate_captures
from laclaugpt_data_collection.capture_server import capture_to_record


def test_capture_has_stable_id() -> None:
    first = BrowserCapture(source_url="https://example.invalid/post/1", platform="web", post_id="1")
    second = BrowserCapture(source_url="https://example.invalid/post/1", platform="web", post_id="1")
    assert first.capture_id == second.capture_id


def test_capture_deduplication() -> None:
    capture = BrowserCapture(source_url="https://example.invalid/post/1", platform="web", post_id="1")
    assert deduplicate_captures([capture, capture]) == [capture]


def test_browser_capture_becomes_canonical_record() -> None:
    capture = BrowserCapture(
        source_url="https://example.invalid/post/42",
        platform="web",
        post_id="42",
        author="synthetic-author",
        text="Synthetic research fixture.",
        media_urls=["https://example.invalid/media/42.jpg"],
    )
    record = capture_to_record(capture)
    assert record.document_id == "42"
    assert record.source_url == capture.source_url
    assert record.collection_provenance.capture_id == capture.capture_id
    assert record.media_references[0].url.endswith("42.jpg")


def test_invalid_source_url_rejected() -> None:
    try:
        BrowserCapture(source_url="not-a-url", platform="web")
    except ValueError:
        return
    raise AssertionError("invalid URL should have been rejected")
