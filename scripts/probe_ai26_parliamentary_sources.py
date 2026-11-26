"""Read-only public-feed preflight for issue #474; no MongoDB or stored text."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.server_runner import collect_rss_records, load_feed_manifest

TARGETS = ("us_congressional_bills", "uk_ai_security_institute")


def probe(feeds: list[dict[str, Any]]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for name in TARGETS:
        rows = [row for row in feeds if row["name"] == name]
        counts: Counter[str] = Counter()
        warnings: list[str] = []
        if len(rows) != 1:
            warnings.append("expected exactly one enabled manifest row")
        else:
            try:
                records, warnings = collect_rss_records(
                    rows, collection_id="ai26", worker_id="public-feed-preflight",
                )
                for record in records:
                    payload = record.model_dump(mode="json")
                    counts["records"] += 1
                    if not payload.get("source_url"):
                        counts["missing_url"] += 1
                        continue
                    handoff = build_handoff(payload, project_id="ai26")
                    if (
                        handoff["arena"] == "parliamentary"
                        and handoff["published_at"]
                        and handoff["status"] == "ready"
                        and str((payload.get("content") or {}).get("text") or "").strip()
                    ):
                        counts["usable_dated_text"] += 1
                    else:
                        counts["not_usable"] += 1
            except Exception as exc:
                warnings.append(f"preflight failure ({type(exc).__name__})")
        report[name] = {
            "records": counts["records"],
            "usable_dated_text": counts["usable_dated_text"],
            "not_usable": counts["not_usable"],
            "missing_url": counts["missing_url"],
            "warnings": warnings,
            "passed": counts["usable_dated_text"] > 0,
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("configs/studies/ai26.sources.example.toml"))
    args = parser.parse_args()
    report = probe(load_feed_manifest(args.manifest))
    print(json.dumps(report, sort_keys=True))
    return 0 if all(row["passed"] for row in report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
