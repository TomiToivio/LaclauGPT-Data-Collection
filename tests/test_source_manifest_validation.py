from pathlib import Path

import pytest

from laclaugpt_data_collection.server_runner import load_feed_manifest


def test_disabled_feed_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "sources.toml"
    path.write_text(
        '[[feed]]\nname="disabled"\nfeed_url="https://example.org/feed"\nenabled=false\n'
        '[[feed]]\nname="enabled"\nfeed_url="https://example.org/other"\npriority="P2"\n',
        encoding="utf-8",
    )
    feeds = load_feed_manifest(path)
    assert [feed["name"] for feed in feeds] == ["enabled"]


@pytest.mark.parametrize(
    "content, message",
    [
        ('[[feed]]\nfeed_url="https://example.org/feed"\n', "requires a name"),
        ('[[feed]]\nname="bad"\nfeed_url="file:///tmp/feed"\n', "http(s) feed_url"),
        (
            '[[feed]]\nname="bad"\nfeed_url="https://example.org/feed"\npriority="urgent"\n',
            "priority must be P1, P2 or P3",
        ),
        (
            '[[feed]]\nname="bad"\nfeed_url="https://example.org/feed"\nenabled="yes"\n',
            "enabled must be boolean",
        ),
    ],
)
def test_malformed_feed_manifest_fails_visibly(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    path = tmp_path / "sources.toml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_feed_manifest(path)
