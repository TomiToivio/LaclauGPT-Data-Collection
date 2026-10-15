#!/usr/bin/env python3
"""Read-only AI26 runtime staleness check: repository versus what actually runs.

Issue #277: a merged fix stays inert until someone deploys it by hand. Three runtime
copies exist -- the two private config files and the code checkout the cron entrypoints
import -- and until now only the source manifest had a drift field, which was reported
every cycle and false for days without anyone acting on it. This reports *all* of them,
in one line each, and exits non-zero when any is stale, so a human or a scheduler can
gate on it.

Read-only by construction: it hashes files, reads local Git refs and, with ``--import-path``,
asks an interpreter where a package resolves from. It never copies, writes, applies,
fetches by default or touches the database. Nothing here authorizes a deployment; the
reviewed procedure stays in ``docs/AI26_LASKIN_RUNTIME_RELEASE_GATE.md``.

    python scripts/check_ai26_runtime.py                     # this checkout
    python scripts/check_ai26_runtime.py --fetch             # refresh refs first
    python scripts/check_ai26_runtime.py --checkout ../LaclauGPT-Data-Analysis
    python scripts/check_ai26_runtime.py --json

Exit codes: 0 everything in sync, 1 something is stale, 2 the check could not be made.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: Tracked-versus-deployed pairs, mirroring the defaults of the deploy tools that own
#: them: ``deploy_ai26_sources.py`` and ``deploy_ai26_study_config.py``. Those two stay
#: the source of truth for the paths; keep this table in step with them.
RUNTIME_CONFIG_PAIRS: tuple[tuple[str, Path, Path], ...] = (
    (
        "ai26.sources.toml",
        Path("configs/studies/ai26.sources.example.toml"),
        Path("data/config/ai26.sources.toml"),
    ),
    (
        "ai26.yaml",
        Path("configs/studies/ai26.example.yaml"),
        Path("data/config/ai26.yaml"),
    ),
)

#: A package whose import location proves which checkout the interpreter actually runs.
IMPORT_PROBE = "laclaugpt_data_collection"


@dataclass(frozen=True)
class Finding:
    """One runtime copy, and whether it matches the repository."""

    name: str
    ok: bool
    detail: str

    def line(self) -> str:
        return f"runtime {self.name:<24} {'ok' if self.ok else 'STALE':<6} {self.detail}"


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def compare_config(name: str, tracked: Path, deployed: Path) -> Finding:
    """Compare one tracked config file with the private runtime copy of it."""
    if not tracked.is_file():
        return Finding(name, False, f"tracked file is missing: {tracked}")
    tracked_digest = digest(tracked.read_bytes())
    if not deployed.is_file():
        return Finding(name, False, f"not deployed: {deployed} (tracked {tracked_digest[:12]})")
    deployed_digest = digest(deployed.read_bytes())
    if tracked_digest == deployed_digest:
        return Finding(name, True, f"sha256 {tracked_digest[:12]}")
    return Finding(
        name,
        False,
        f"drift: tracked {tracked_digest[:12]} != deployed {deployed_digest[:12]} ({deployed})",
    )


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def compare_checkout(name: str, checkout: Path, *, fetch: bool) -> Finding:
    """Compare a working checkout with its own ``origin/main``.

    Uses the local remote-tracking ref, so the check needs no network. ``fetch`` is the
    caller's explicit opt-in for a truthful comparison against the real remote.
    """
    if not (checkout / ".git").exists():
        return Finding(name, False, f"not a Git checkout: {checkout}")
    if fetch:
        git("fetch", "--quiet", "origin", "main", cwd=checkout)
    head = git("rev-parse", "--short", "HEAD", cwd=checkout)
    upstream = git("rev-parse", "--short", "refs/remotes/origin/main", cwd=checkout)
    if not head or not upstream:
        return Finding(name, False, f"cannot resolve HEAD and origin/main in {checkout}")
    counts = git("rev-list", "--left-right", "--count", "HEAD...refs/remotes/origin/main", cwd=checkout)
    ahead, _, behind = counts.partition("\t")
    dirty = len(git("status", "--porcelain", cwd=checkout).splitlines())
    suffix = f", {dirty} uncommitted path(s)" if dirty else ""
    if ahead.strip() not in ("", "0"):
        return Finding(
            name,
            False,
            f"{ahead.strip()} commit(s) ahead of origin/main (HEAD {head}, origin/main {upstream})"
            f" - not the reviewed revision{suffix}",
        )
    if behind.strip() in ("", "0"):
        return Finding(name, True, f"{head} == origin/main {upstream}{suffix}")
    return Finding(
        name,
        False,
        f"{behind.strip()} commit(s) behind origin/main (HEAD {head}, origin/main {upstream}){suffix}",
    )


def compare_import_path(name: str, checkout: Path) -> Finding:
    """Ask the checkout's interpreter which copy of the package it imports."""
    if not (checkout / "src" / IMPORT_PROBE).is_dir():
        # A sibling repository has no such package: probing it would report drift that
        # cannot exist. The probe is only meaningful for the checkout that owns it.
        return Finding(name, True, f"{IMPORT_PROBE} is not part of this checkout; skipped")
    python = checkout / ".venv" / "bin" / "python"
    if not python.is_file():
        return Finding(name, True, f"no {python}; skipped")
    probe = (
        "import importlib.util, json;"
        f"spec = importlib.util.find_spec({IMPORT_PROBE!r});"
        "print(json.dumps(spec.origin if spec else None))"
    )
    result = subprocess.run([str(python), "-c", probe], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return Finding(name, False, f"probe failed under {python}: {result.stderr.strip()[:120]}")
    origin = json.loads(result.stdout.strip() or "null")
    if not origin:
        return Finding(name, False, f"{IMPORT_PROBE} not importable under {python}")
    inside = Path(origin).resolve().is_relative_to(checkout.resolve())
    return Finding(
        name,
        inside,
        f"{origin}" if inside else f"outside this checkout: {origin}",
    )


def collect(root: Path, checkouts: list[Path], *, fetch: bool) -> list[Finding]:
    findings = [
        compare_config(name, root / tracked, root / deployed)
        for name, tracked, deployed in RUNTIME_CONFIG_PAIRS
    ]
    for checkout in checkouts:
        label = f"code ({checkout.name})"
        findings.append(compare_checkout(label, checkout, fetch=fetch))
        findings.append(compare_import_path(f"import ({checkout.name})", checkout))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent,
                        help="Repository root owning the tracked and deployed configs")
    parser.add_argument("--checkout", type=Path, action="append", default=None,
                        help="Checkout to compare with origin/main; repeatable (default: --root)")
    parser.add_argument("--fetch", action="store_true",
                        help="Run `git fetch origin main` first; needs network and a clean tree")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    checkouts = [path.resolve() for path in (args.checkout or [root])]
    findings = collect(root, checkouts, fetch=args.fetch)
    stale = [finding for finding in findings if not finding.ok]

    if args.json:
        print(json.dumps({"stale": bool(stale), "findings":
                          [dict(name=f.name, ok=f.ok, detail=f.detail) for f in findings]}, indent=2))
    else:
        for finding in findings:
            print(finding.line())
        print(f"runtime result: {'STALE' if stale else 'in sync'} ({len(stale)} of {len(findings)} checks)")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
