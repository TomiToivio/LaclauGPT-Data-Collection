"""Fail CI when tracked files violate public-repository hygiene rules."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

FORBIDDEN_SUFFIXES = {
    ".sqlite",
    ".sqlite3",
    ".db",
    ".jsonl",
    ".ndjson",
    ".parquet",
    ".xlsx",
    ".xls",
    ".sav",
    ".dta",
    ".rds",
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".mp3",
    ".wav",
}
FORBIDDEN_PARTS = {
    ".env",
    "cookies",
    "browser-profile",
    "storage_state",
    "study.private",
    "credentials",
    "secrets",
}
ALLOWED_EXACT = {".env.example"}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    # Flag literal secret-looking assignments, not variable-to-variable plumbing such as
    # aws_secret_access_key=secret_access_key.
    re.compile(
        r"(?i)(?:password|secret_access_key|api[_-]?key|access[_-]?token)"
        r"\s*[:=]\s*([\"'])(?!replace-locally|example|\$\{|os\.environ)"
        r"[^\"'\r\n]{8,}\1"
    ),
]


def tracked_files() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files", "-z"])
    return [Path(item.decode()) for item in output.split(b"\0") if item]


def main() -> int:
    failures: list[str] = []
    for path in tracked_files():
        lowered = path.as_posix().lower()
        if path.as_posix() not in ALLOWED_EXACT:
            if path.suffix.lower() in FORBIDDEN_SUFFIXES:
                failures.append(f"forbidden data suffix: {path}")
            if any(part in lowered for part in FORBIDDEN_PARTS):
                failures.append(f"forbidden private/config filename pattern: {path}")
        if not path.is_file() or path.stat().st_size > 1_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                failures.append(f"possible secret material: {path}")
                break

    if failures:
        print("Public-tree policy violations:")
        for failure in sorted(set(failures)):
            print(f"- {failure}")
        return 1
    print("Public-tree policy check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
