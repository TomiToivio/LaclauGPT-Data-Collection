# -*- coding: utf-8 -*-
"""Detect drift between the deployed source manifest and the tracked plan (issue #206).

The running collection reads a **deployed** manifest under `data/` (gitignored
runtime config). The audited source plan lives in `configs/studies/`. When the
tracked plan gains a source, the running pipeline keeps collecting the old set
until a human redeploys -- and nothing in the cycle reports it.

Measured 2026-10-02: deployed 19 feeds vs tracked 23 (28 jobs), so sources that
were audited, verified and committed produced no records at all. By 2026-10-09
the gap had widened (deployed 19 vs tracked 37 feeds).

This module compares the two files and reports the difference in the same
structural terms the manifest loader uses, so the answer is exact rather than a
diff a human has to read. It is observational: it never writes either file.

The comparison is deliberately **identity-based**, not line-based. A source is
"added" when the tracked plan has an identity the deployed manifest lacks;
"removed" when the deployed manifest has one the tracked plan no longer audits.
Identity is a kind-scoped natural key, because the same URL can legitimately
appear as both a `[[feed]]` and a `[[web_source]]` (they route differently).
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

#: Source kinds that can appear in a manifest, in a stable reporting order.
SOURCE_TABLES: tuple[str, ...] = (
    "feed",
    "web_source",
    "bluesky_account",
    "mastodon_account",
    "youtube_source",
    "scholarly_query",
    "x_account",
    "browser_source",
)

#: The identity field for each kind, tried in order. The first present wins.
#: `feed`/`web_source` are keyed on their URL; accounts on their handle/acct;
#: queries on their name, because a query has no URL.
_IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "feed": ("feed_url",),
    "web_source": ("url",),
    "bluesky_account": ("handle", "acct", "actor"),
    "mastodon_account": ("acct", "actor", "handle"),
    "youtube_source": ("channel_url", "channel_id", "url", "name"),
    "scholarly_query": ("name",),
    "x_account": ("handle", "name"),
    "browser_source": ("url", "name"),
}


def _identity(kind: str, row: dict[str, Any]) -> str:
    """Return a stable identity string for one source row, or '' when unknown.

    A trailing slash is ignored so the #205 redirect class does not read as a
    source change.
    """
    for field in _IDENTITY_FIELDS.get(kind, ("name", "url")):
        value = row.get(field)
        if isinstance(value, str) and value.strip():
            return row_identity(kind, field, value.strip().rstrip("/"))
    return ""


def row_identity(kind: str, field: str, value: str) -> str:
    """Compose the reported identity, so the CLI and the tests agree on format."""
    return f"{kind}:{field}={value}"


def _enabled(row: dict[str, Any]) -> bool:
    """A row is active unless explicitly disabled (mirrors the loader)."""
    return row.get("enabled", row.get("active", True)) is not False


def load_manifest_rows(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Load a manifest into ``{kind: [row, ...]}``, keeping only active rows.

    Uses the same tomllib read and enabled semantics as the runner's loaders so
    drift cannot be reported for a row the pipeline would skip anyway.
    """
    manifest = Path(path)
    if not manifest.is_file():
        raise FileNotFoundError(f"source manifest does not exist: {manifest}")
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    out: dict[str, list[dict[str, Any]]] = {}
    for kind in SOURCE_TABLES:
        rows = data.get(kind) or []
        if not isinstance(rows, list):
            raise ValueError(f"source manifest {kind!r} must be an array of tables")
        out[kind] = [row for row in rows if isinstance(row, dict) and _enabled(row)]
    return out


def compare_manifests(
    deployed: str | Path, tracked: str | Path
) -> dict[str, Any]:
    """Compare a deployed manifest against the tracked plan.

    Returns a JSON-serialisable report:

    - ``counts`` -- per kind, the deployed/tracked/added/removed/drift counts.
    - ``added`` -- identities the tracked plan has and the running set lacks
      (the record-level loss #206 describes).
    - ``removed`` -- identities the running set still polls but the tracked plan
      no longer audits (hand-edited or withdrawn).
    - ``in_sync`` -- True when no kind differs in either direction.
    - ``drift_kinds`` -- the kinds that differ, for a one-line summary.
    """
    deployed_rows = load_manifest_rows(deployed)
    tracked_rows = load_manifest_rows(tracked)

    counts: dict[str, dict[str, int]] = {}
    added: list[str] = []
    removed: list[str] = []
    drift_kinds: list[str] = []

    for kind in SOURCE_TABLES:
        def identities(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
            out: dict[str, dict[str, Any]] = {}
            for row in rows:
                key = _identity(kind, row)
                if key:
                    out.setdefault(key, row)
            return out

        have = identities(deployed_rows.get(kind, []))
        want = identities(tracked_rows.get(kind, []))
        kind_added = sorted(set(want) - set(have))
        kind_removed = sorted(set(have) - set(want))
        n_drift = len(kind_added) + len(kind_removed)
        counts[kind] = {
            "deployed": len(have),
            "tracked": len(want),
            "added": len(kind_added),
            "removed": len(kind_removed),
            "drift": n_drift,
        }
        if n_drift:
            drift_kinds.append(kind)
        added.extend(kind_added)
        removed.extend(kind_removed)

    return {
        "deployed_manifest": str(Path(deployed)),
        "tracked_plan": str(Path(tracked)),
        "counts": counts,
        "added": added,
        "removed": removed,
        "in_sync": not drift_kinds,
        "drift_kinds": drift_kinds,
        "deployed_total": sum(c["deployed"] for c in counts.values()),
        "tracked_total": sum(c["tracked"] for c in counts.values()),
    }


def drift_summary(report: dict[str, Any]) -> str:
    """One-line human summary, suitable for a log line or a cron notification."""
    if report["in_sync"]:
        return "source manifest in sync with the tracked plan"
    parts = [
        f"{kind}: {report['counts'][kind]['deployed']}->{report['counts'][kind]['tracked']}"
        for kind in report["drift_kinds"]
    ]
    return (
        f"source manifest DRIFT: deployed {report['deployed_total']} vs tracked "
        f"{report['tracked_total']} ({', '.join(parts)}); "
        f"{len(report['added'])} audited source(s) not deployed, "
        f"{len(report['removed'])} deployed source(s) no longer audited"
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="laclaugpt-collect manifest-drift",
        description="Report how the deployed source manifest differs from the tracked plan.",
    )
    parser.add_argument("--deployed", required=True, help="the manifest the pipeline reads")
    parser.add_argument("--tracked", required=True, help="the audited plan in configs/studies/")
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="exit 1 when the manifests differ (for a CI/cron gate)",
    )
    args = parser.parse_args(argv)

    report = compare_manifests(args.deployed, args.tracked)
    print(json.dumps(report, indent=2, sort_keys=True))
    print(drift_summary(report), file=__import__("sys").stderr)
    if args.fail_on_drift and not report["in_sync"]:
        return 1
    return 0
