#!/usr/bin/env python3
"""Read-only: does the AI26 runtime on this host match the repository? (#277)

Three independent facts are checked, and each is reported separately so that
"not checked" can never be read as "fine":

1. **the deployed source manifest vs the tracked plan** -- using
   :func:`laclaugpt_data_collection.manifest_drift.compare_manifests`, the same
   identity-aware comparison the hourly collector uses, so a retired row that is
   retained with ``enabled = false`` does not count as drift;
2. **the deployed study config vs the tracked one** -- a byte comparison, because
   the deploy tool for it is a straight copy;
3. **the code checkout this host runs from vs ``origin/main``** -- plus whether
   the working tree is dirty, since a locally modified checkout is its own kind
   of "not what the repository says".

**It never applies anything.** Deploying content changes what the production
pipeline samples, which is a maintainer decision; this check exists to make that
decision a one-liner instead of a discovery. Nothing here writes to the runtime,
to git, or to any store: it reads files and runs read-only git queries.

Exit codes: ``0`` everything fresh, ``1`` something is stale, ``2`` the check
could not be completed (a missing file, an unusable interpreter) -- deliberately
distinct from ``1``, so an unrun check is never mistaken for a passing one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

FRESH = 0
STALE = 1
CANNOT_CHECK = 2

_SCRIPT = Path(__file__).resolve()
_DEFAULT_ROOT = _SCRIPT.parents[1]
_DEFAULT_TRACKED_SOURCES = "configs/studies/ai26.sources.example.toml"
_DEFAULT_TRACKED_STUDY = "configs/studies/ai26.example.yaml"
_DEFAULT_DEPLOYED_SOURCES = "data/config/ai26.sources.toml"
_DEFAULT_DEPLOYED_STUDY = "data/config/ai26.yaml"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )


def check_code_checkout(root: Path) -> dict:
    """Compare the running checkout with ``origin/main``. Read-only: no fetch."""
    if _git(root, "rev-parse", "--git-dir").returncode != 0:
        return {"check": "code", "status": "cannot_check", "detail": "not a git checkout"}

    head = _git(root, "rev-parse", "--verify", "HEAD").stdout.strip()
    # ``git rev-parse <unresolvable>`` echoes its argument, so the exit status --
    # not a non-empty stdout -- decides whether the reference exists. Getting this
    # wrong reported a missing ref as "diverged", which is a different fact.
    resolved = _git(root, "rev-parse", "--verify", "origin/main")
    reference = resolved.stdout.strip() if resolved.returncode == 0 else ""
    dirty = bool(_git(root, "status", "--porcelain").stdout.strip())

    if not reference:
        return {
            "check": "code",
            "status": "cannot_check",
            "detail": "no origin/main ref (never fetched here); run git fetch to enable this check",
        }
    if head == reference:
        status = "fresh"
        detail = f"HEAD == origin/main ({head[:12]})"
    else:
        behind = _git(root, "rev-list", "--count", "HEAD..origin/main").stdout.strip() or "?"
        ahead = _git(root, "rev-list", "--count", "origin/main..HEAD").stdout.strip() or "?"
        if behind not in {"0", "?"} and ahead == "0":
            status, detail = "stale", f"{behind} commit(s) behind origin/main (HEAD {head[:12]})"
        elif ahead != "0" and behind == "0":
            status, detail = "ahead", f"{ahead} local commit(s) origin/main does not have"
        else:
            status, detail = "stale", f"diverged from origin/main ({behind} behind, {ahead} ahead)"
    return {
        "check": "code",
        "status": status,
        "detail": detail,
        "dirty": dirty,
        "head": head,
        "origin_main": reference,
    }


def check_source_manifest(deployed: Path, tracked: Path) -> dict:
    """Identity-aware manifest comparison, falling back loudly to a hash check."""
    if not tracked.exists():
        return {"check": "source_manifest", "status": "cannot_check",
                "detail": f"tracked plan not found: {tracked}"}
    if not deployed.exists():
        return {"check": "source_manifest", "status": "cannot_check",
                "detail": f"deployed manifest not found: {deployed}"}
    try:
        from laclaugpt_data_collection.manifest_drift import compare_manifests, drift_summary
    except Exception as exc:  # noqa: BLE001 - the check must still say something
        # A weaker check, labelled as weaker: never let this look like the real one.
        same = digest(deployed) == digest(tracked)
        return {
            "check": "source_manifest",
            "status": "fresh" if same else "stale",
            "detail": "BYTE COMPARISON ONLY (package not importable: "
                      f"{type(exc).__name__}) - not the identity-aware check",
            "weak": True,
        }
    report = compare_manifests(deployed, tracked)
    return {
        "check": "source_manifest",
        "status": "fresh" if report["in_sync"] else "stale",
        "detail": drift_summary(report),
        "added": report["added"],
        "removed": report["removed"],
        "deployed_total": report["deployed_total"],
        "tracked_total": report["tracked_total"],
    }


def check_study_config(deployed: Path, tracked: Path) -> dict:
    if not tracked.exists() or not deployed.exists():
        missing = tracked if not tracked.exists() else deployed
        return {"check": "study_config", "status": "cannot_check",
                "detail": f"file not found: {missing}"}
    a, b = digest(deployed), digest(tracked)
    return {
        "check": "study_config",
        "status": "fresh" if a == b else "stale",
        "detail": "byte-identical to the tracked config" if a == b else
                  "differs from the tracked config; review and deploy deliberately",
        "deployed_sha256": a,
        "tracked_sha256": b,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=_DEFAULT_ROOT,
                        help="repository root the runtime runs from (default: this checkout)")
    parser.add_argument("--tracked-sources", default=_DEFAULT_TRACKED_SOURCES)
    parser.add_argument("--tracked-study-config", default=_DEFAULT_TRACKED_STUDY)
    parser.add_argument("--deployed-sources", default=_DEFAULT_DEPLOYED_SOURCES)
    parser.add_argument("--deployed-study-config", default=_DEFAULT_DEPLOYED_STUDY)
    parser.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    parser.add_argument("--quiet", action="store_true", help="summary line only")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    results = [
        check_source_manifest(root / args.deployed_sources, root / args.tracked_sources),
        check_study_config(root / args.deployed_study_config, root / args.tracked_study_config),
        check_code_checkout(root),
    ]

    stale = [r for r in results if r["status"] in {"stale", "ahead"}]
    unknown = [r for r in results if r["status"] == "cannot_check"]

    if args.json:
        print(json.dumps({"root": str(root), "checks": results,
                          "fresh": not stale and not unknown,
                          "stale_count": len(stale), "cannot_check_count": len(unknown)}, indent=2))
    else:
        if not args.quiet:
            for r in results:
                mark = {"fresh": "ok   ", "stale": "STALE", "ahead": "AHEAD",
                        "cannot_check": "???? "}.get(r["status"], r["status"])
                print(f"[{mark}] {r['check']:15s} {r['detail']}")
                if r.get("dirty"):
                    print(f"[warn ] {'':15s} the working tree has uncommitted changes")
                if r.get("weak"):
                    print(f"[warn ] {'':15s} this check was WEAKER than intended; see above")

        if stale:
            print(f"RUNTIME STALE: {len(stale)} of {len(results)} check(s) disagree with the repository. "
                  "Nothing has been changed. Refresh deliberately: see docs/AI26_RUNTIME_REFRESH.md")
        elif unknown:
            print(f"RUNTIME UNKNOWN: {len(unknown)} of {len(results)} check(s) could not be completed. "
                  "This is NOT an all-clear - fix the check before trusting freshness.")
        else:
            print("RUNTIME FRESH: the deployed configs and the code checkout match the repository.")

    if unknown:
        return CANNOT_CHECK
    return STALE if stale else FRESH


if __name__ == "__main__":
    sys.exit(main())
