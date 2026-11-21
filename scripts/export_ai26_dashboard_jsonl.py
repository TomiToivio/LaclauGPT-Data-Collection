#!/usr/bin/env python3
"""Export AI26 annotations from MongoDB as the dashboard's per-arena JSONL (#436).

This is the canonical, versioned copy of the exporter. It used to live only inside an archived private
repository, so the deployed unit pointed at code no current repository owned — which is how a five-week
failure stayed invisible.

Three rules, each earned by a failure:

* **Write atomically, never truncate first.** Each arena is written to a temporary file and replaced only
  after the whole export succeeded. The old unit truncated the live files *before* running, so a single
  annotation the interchange model rejected left the dashboard **empty** rather than stale — a failure that
  reads as "the corpus is gone".
* **One bad record must not cost the export.** Shape drift is data, not a crash: a record that does not
  validate is named on stdout and skipped, and the rest still land.
* **Name the destination, never infer it silently.** The runtime (which provides the models and the store
  handle) and the output root both come from the environment, and `--check` prints them without writing.

Environment:
    AI26_MONGO_DATABASE         database holding ``ai26_annotations`` (default: vasama_ai)
    LACLAUGPT_AI26_RUNTIME      directory that provides ``laclaugpt`` and ``laclaugpt_interchange``
    AI26_DASHBOARD_EXPORT_ROOT  output directory for ``<arena>.jsonl`` (default: <runtime>/../collection-data/dashboard)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TextIO

#: The AI26 runtime on the deployment host. Not a path inside this public repository: the runtime holds
#: study data and credentials.
DEFAULT_RUNTIME = "/mnt/workspace/LaclauGPT-Private/ai26_runtime"
ARCHIVED_RUNTIME = "/mnt/workspace/laclaugpt-private/ai26_runtime"


def resolve_runtime(explicit: str | None = None, environment: dict[str, str] | None = None,
                    defaults: tuple[str, ...] | None = None) -> Path:
    """The directory that provides the interchange models and the store handle.

    An explicit path wins, then the environment, then the current location, then the archived one as a
    last resort. A candidate must actually carry the package — a directory that merely exists is not a
    runtime, and silently importing the wrong copy is how two models of one record diverge.
    """
    env = environment if environment is not None else os.environ
    checked: list[str] = []
    fallbacks = (DEFAULT_RUNTIME, ARCHIVED_RUNTIME) if defaults is None else defaults
    for candidate in (explicit, env.get("LACLAUGPT_AI26_RUNTIME"), *fallbacks):
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        checked.append(str(path))
        if (path / "laclaugpt_interchange").exists() or (path.parent / "laclaugpt").exists():
            return path
    raise SystemExit("no AI26 runtime found; looked in: " + ", ".join(checked))


def _load_runtime(runtime: Path):
    """Import the runtime's models *after* its paths are on sys.path, so no global install wins."""
    for entry in (str(runtime.parent), str(runtime)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    from laclaugpt.researcher_reporting import researcher_row  # noqa: PLC0415
    from laclaugpt_interchange import DocumentAnnotation  # noqa: PLC0415
    from mongo_writer import get_db  # noqa: PLC0415

    return DocumentAnnotation, researcher_row, get_db


def _arena_for_annotation(db, annotation: dict) -> str:
    provenance = annotation.get("collection_provenance") or {}
    arena = provenance.get("arena_id") or provenance.get("arena")
    if arena:
        return str(arena)
    native_id = str(annotation.get("document_id") or "").split("::", 1)[-1]
    source = db.ai26_sources.find_one({"native_id": native_id}, {"metadata.arena": 1}) or {}
    return str((source.get("metadata") or {}).get("arena") or "elites")


def _normalise_shapes(annotation: dict) -> dict:
    """``formation_original`` arrives as a bare string before the list-shaped model, and as a list after.

    The model accepts only the list, so one older record used to abort the whole export.
    """
    value = annotation.get("formation_original")
    if isinstance(value, str):
        annotation["formation_original"] = [value] if value.strip() else []
    return annotation


def export(database: str, output_root: Path, runtime: Path) -> dict[str, int]:
    """Write one JSONL per arena, atomically, and return the record count per arena."""
    DocumentAnnotation, researcher_row, get_db = _load_runtime(runtime)
    db = get_db()
    if database:
        db = db.client[database]
    output_root.mkdir(parents=True, exist_ok=True)
    handles: dict[str, TextIO] = {}
    temp_paths: dict[str, Path] = {}
    counts: dict[str, int] = {}
    pid = os.getpid()
    skipped: list[str] = []
    try:
        for annotation in db.ai26_annotations.find({}, sort=[("created_at", 1)]):
            annotation.pop("_id", None)
            arena = _arena_for_annotation(db, annotation)
            if arena not in handles:
                temp = output_root / f".{arena}.jsonl.tmp-{pid}"
                handles[arena] = temp.open("w", encoding="utf-8")
                temp_paths[arena] = temp
                counts[arena] = 0
            try:
                record = researcher_row(DocumentAnnotation.model_validate(_normalise_shapes(annotation)))
            except Exception as exc:  # noqa: BLE001 - shape drift is data, not a crash
                skipped.append(f"{annotation.get('document_id', '?')} ({type(exc).__name__})")
                continue
            handles[arena].write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            counts[arena] += 1
        for handle in handles.values():
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
        for arena, temp in temp_paths.items():
            os.replace(temp, output_root / f"{arena}.jsonl")
    finally:
        for handle in handles.values():
            if not handle.closed:
                handle.close()
        for temp in temp_paths.values():
            temp.unlink(missing_ok=True)
    if skipped:
        print(f"skipped {len(skipped)} annotation(s) that did not validate:", *skipped[:10], sep="\n  ")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runtime", help="directory providing the interchange models and the store handle")
    parser.add_argument("--output-root", help="where <arena>.jsonl is written")
    parser.add_argument("--database", default=os.environ.get("AI26_MONGO_DATABASE", "vasama_ai"))
    parser.add_argument("--check", action="store_true", help="report the resolved paths, write nothing")
    args = parser.parse_args(argv)

    runtime = resolve_runtime(args.runtime)
    output_root = Path(args.output_root or os.environ.get("AI26_DASHBOARD_EXPORT_ROOT")
                       or runtime.parent / "collection-data" / "dashboard").expanduser()
    print(f"runtime: {runtime}")
    print(f"database: {args.database}")
    print(f"export root: {output_root}")
    if args.check:
        return 0
    counts = export(args.database, output_root, runtime)
    print("exported:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
