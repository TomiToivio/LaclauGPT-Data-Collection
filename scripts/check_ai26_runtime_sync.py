#!/usr/bin/env python3
"""Read-only AI26 runtime release drift gate (#277).

Compare runtime config byte hashes to the checked-out tracked files, and HEAD to
the locally known origin/main. No fetch, pull, deploy, secrets or sampling changes.
Use git fetch origin main *separately* when an up-to-date remote comparison is
needed; this program never updates refs.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path


def sha(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args], text=True, capture_output=True,
            check=False, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def evaluate(root: Path, remote: str = "origin/main") -> tuple[bool, str]:
    labels = (
        ("sources", "configs/studies/ai26.sources.example.toml",
         "data/config/ai26.sources.toml"),
        ("study", "configs/studies/ai26.example.yaml", "data/config/ai26.yaml"),
    )
    findings: list[str] = []
    for label, tracked, deployed in labels:
        a, b = sha(root / tracked), sha(root / deployed)
        if a is None or b is None:
            findings.append(f"{label}=missing(tracked={bool(a)},runtime={bool(b)})")
        elif a != b:
            findings.append(f"{label}=stale(tracked={a[:12]},runtime={b[:12]})")
        else:
            findings.append(f"{label}=sync")
    head = git(root, "rev-parse", "HEAD")
    upstream = git(root, "rev-parse", "--verify", remote)
    if not head or not upstream:
        findings.append("code=unknown(missing-git-ref)")
    elif head == upstream:
        findings.append(f"code=sync({head[:12]})")
    else:
        behind = git(root, "rev-list", "--count", f"HEAD..{remote}")
        ahead = git(root, "rev-list", "--count", f"{remote}..HEAD")
        findings.append(f"code=stale(head={head[:12]},upstream={upstream[:12]},behind={behind or '?'},ahead={ahead or '?'})")
    clean = git(root, "status", "--porcelain", "--untracked-files=no")
    findings.append("tree=unknown" if clean is None else ("tree=dirty" if clean else "tree=clean"))
    ok = all(f"{name}=sync" in item for name, item in zip(("sources", "study", "code"), findings)) and clean == ""
    return ok, ("AI26_RUNTIME_SYNC=" + ("in_sync" if ok else "stale") + " " + " ".join(findings))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--remote", default="origin/main")
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        parser.error("checkout root does not exist")
    ok, line = evaluate(args.root.resolve(), remote=args.remote)
    print(line)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
