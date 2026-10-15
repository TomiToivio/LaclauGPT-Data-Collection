"""Non-destructive AI26 Collection 1.1 -> Analysis 1.2 boundary adapter.

This is an export view only: persisted records and their original schema version
remain untouched. Unknown schema versions fail closed.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

COLLECTION_VERSION = "1.1.0"
ANALYSIS_VERSION = "1.2.0"
SUPPORTED_VERSIONS = frozenset({COLLECTION_VERSION, ANALYSIS_VERSION})

# The inspected 1.1/1.2 JSON schemas have the same field definitions,
# required properties and top-level additionalProperties=false restriction.
# Only schema_version differs. Re-audit these schemas before extending this.
ANALYSIS_TOP_LEVEL = frozenset({
    "schema_version", "source_url", "source_native_ids", "raw_capture",
    "source", "content", "intermediate", "evidence", "analysis",
    "human_readable", "provenance", "review", "legacy",
})
REQUIRED = frozenset({
    "schema_version", "source_url", "raw_capture", "source", "content",
    "intermediate", "analysis", "human_readable", "provenance",
    "review", "legacy",
})


def analysis_1_2_view(record: dict[str, Any]) -> dict[str, Any]:
    """Prepare a *copy* for strict Analysis 1.2 schema validation.

    Extra Collection-only fields are retained under legacy compatibility
    metadata, not silently discarded. Handoff routing metadata is also kept
    there if the input is a combined storage document. Neither source records
    nor production databases are mutated.
    """
    if not isinstance(record, dict):
        raise TypeError("research record must be an object")
    version = record.get("schema_version")
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"unsupported research-record schema_version: {version!r}")
    missing = REQUIRED - record.keys()
    if missing:
        raise ValueError(f"missing research-record fields: {sorted(missing)}")
    if not isinstance(record.get("source_url"), str) or not record["source_url"]:
        raise ValueError("source_url is required")
    if not isinstance(record.get("legacy"), dict):
        raise ValueError("legacy must be an object")
    output = deepcopy(record)
    extensions = {key: output.pop(key) for key in list(output) if key not in ANALYSIS_TOP_LEVEL}
    if extensions:
        legacy = output["legacy"]
        if "_collection_compat_extensions" in legacy:
            raise ValueError("reserved legacy extension key already occupied")
        legacy["_collection_compat_extensions"] = extensions
    output["schema_version"] = ANALYSIS_VERSION
    return output
