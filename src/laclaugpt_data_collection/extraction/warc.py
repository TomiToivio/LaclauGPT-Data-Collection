"""Optional WARC helpers kept outside normal collection execution."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator


def iter_warc_payloads(path: str | Path) -> Iterator[tuple[str, bytes]]:
    try:
        from warcio.archiveiterator import ArchiveIterator
    except ImportError as exc:
        raise RuntimeError("warcio is optional; install .[phase1-extraction]") from exc

    with Path(path).open("rb") as stream:
        for record in ArchiveIterator(stream):
            if record.rec_type != "response":
                continue
            target = record.rec_headers.get_header("WARC-Target-URI") or ""
            yield target, record.content_stream().read()
