"""Source-identity declarations: an aggregator is not a publisher (#296).

A manifest row whose items link at an aggregator -- not at the publisher -- may say
so once:

.. code-block:: toml

    [[feed]]
    name = "local_data_centre_moratorium_news"
    source_identity = "aggregator"
    aggregator = "google_news"

Measured on the live feed: every Google News item's ``<link>`` is
``news.google.com/rss/articles/<opaque token>`` and the publisher appears only in
the item's ``<source url="https://gizmodo.com">`` element, so the item's own URL is
its stable identity while the publisher is provenance. Recording the declaration
keeps "what identifies this record" and "who published it" separable, which is the
difference between a corpus that can attribute a claim and one that cannot.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

AGGREGATOR = "aggregator"


def _provenance_metadata(record: object) -> Mapping[str, Any]:
    """The last provenance step's metadata, from a model or a plain mapping."""
    provenance = record.get("provenance") if isinstance(record, Mapping) else getattr(
        record, "provenance", None
    )
    if not provenance:
        return {}
    last = provenance[-1]
    metadata = last.get("metadata") if isinstance(last, Mapping) else getattr(last, "metadata", None)
    return metadata if isinstance(metadata, Mapping) else {}


def apply_source_identity(record: object, row: Mapping[str, Any]) -> dict[str, Any]:
    """The provenance fields a row's declared source identity contributes.

    Empty unless the row declares ``source_identity = "aggregator"``: a publisher
    row needs no marker, and silently marking every row would make the marker mean
    nothing. The publisher fields come from the collector, where the entry's
    ``<source>`` element was read.
    """
    if str(row.get("source_identity") or "").strip().lower() != AGGREGATOR:
        return {}
    stamped: dict[str, Any] = {"source_identity": AGGREGATOR}
    aggregator: dict[str, str] = {}
    provider = str(row.get("aggregator") or "").strip()
    if provider:
        aggregator["provider"] = provider
    metadata = _provenance_metadata(record)
    for key in ("publisher_url", "publisher_name"):
        value = str(metadata.get(key) or "").strip()
        if value:
            aggregator[key] = value
    if aggregator:
        stamped["aggregator"] = aggregator
    return stamped
