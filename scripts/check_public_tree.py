"""Fail CI when tracked files violate public-repository hygiene rules."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

FORBIDDEN_SUFFIXES = {
    ".sqlite",
    ".sqlite3",
    ".db",
    ".duckdb",
    ".jsonl",
    ".ndjson",
    ".parquet",
    ".feather",
    ".arrow",
    ".csv",
    ".tsv",
    ".xlsx",
    ".xls",
    ".sav",
    ".dta",
    ".rds",
    ".rdata",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".mp3",
    ".wav",
    ".flac",
    ".har",
    ".pcap",
    ".pcapng",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
}
FORBIDDEN_NAMES = {
    ".env",
    ".envrc",
    ".netrc",
    ".s3cfg",
    "clouds.yaml",
    "clouds.yml",
    "terraform.tfvars",
}
FORBIDDEN_PARTS = {
    "cookies",
    "browser-profile",
    "storage_state",
    "study.private",
    "credentials",
    "secrets",
    "private",
    "playwright/.auth",
}
FORBIDDEN_PREFIXES = (
    "openrc",
    "kubeconfig",
    "id_rsa",
    "id_ed25519",
    # Cloud/OpenStack credential bundles. `allas_conf` is the CSC Allas helper, but any
    # `*-conf` cloud credential file belongs outside the public repository.
    "allas_conf",
    "allas-conf",
)
FORBIDDEN_EXACT_NAMES = {
    "allas_conf",
    "allas-conf",
    "gcloud_conf",
    "az_conf",
}
ALLOWED_EXACT = {
    ".env.example",
    "configs/laptop.example.toml",
    "configs/server.example.toml",
}
PRIVATE_PATH_PATTERNS = [
    re.compile(r"(?i)(?:^|[\s'\"=])/(?:home|Users)/[A-Za-z0-9._-]+/"),
    re.compile(r"(?i)(?:^|[\s'\"=])/mnt/[a-z]/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"(?i)\b[A-Za-z]:\\\\Users\\\\[A-Za-z0-9._-]+\\\\"),
]

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    # Flag literal secret-looking assignments, not variable-to-variable plumbing such as
    # aws_secret_access_key=secret_access_key.
    re.compile(
        r"(?i)(?:password|secret_access_key|secret[_-]?key|api[_-]?key|access[_-]?token)"
        r"\s*[:=]\s*([\"'])(?!replace-locally|example|\$\{|os\.environ)"
        r"[^\"'\r\n]{8,}\1"
    ),
    # Catch credential-bearing URLs such as scheme://user:password@host.
    re.compile(r"(?i)\b(?:mongodb(?:\+srv)?|redis|https?|s3)://[^\s/:@]+:[^\s/@]+@[^\s/]+"),
    # OpenStack/CSC-style credential bundles such as `export OS_AUTH_TOKEN=<value>`.
    # A bare variable reference (OS_AUTH_TOKEN="$OS_AUTH_TOKEN") or a placeholder is
    # plumbing, not a secret, and must stay allowed. Only horizontal whitespace is
    # consumed after the separator, so a match can never run on to the next line and
    # treat a following variable *name* as a value.
    re.compile(
        r"(?i)\b(?:export[ \t]+)?OS_(?:AUTH_TOKEN|PASSWORD|AUTH_DATA|SECRET_KEY|ACCESS_KEY)"
        r"[ \t]*[:=][ \t]*[\"']?(?!\$|<|replace|example|changeme)[^\s\"'\r\n]{12,}"
    ),
]


def tracked_files() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files", "-z"])
    return [Path(item.decode()) for item in output.split(b"\0") if item]


def path_policy_violations(path: Path) -> list[str]:
    """Return publication-policy violations that can be detected from a path alone."""
    posix = path.as_posix()
    lowered = posix.casefold()
    if posix in ALLOWED_EXACT:
        return []

    violations: list[str] = []
    if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
        violations.append(f"forbidden data/secret suffix: {path}")
    if path.name.casefold() in FORBIDDEN_NAMES:
        violations.append(f"forbidden private/config filename: {path}")
    if path.name.casefold() in FORBIDDEN_EXACT_NAMES:
        violations.append(f"forbidden cloud credential bundle: {path}")
    if path.name.casefold().startswith(FORBIDDEN_PREFIXES):
        violations.append(f"forbidden operational credential/config filename: {path}")
    if any(part in lowered for part in FORBIDDEN_PARTS):
        violations.append(f"forbidden private/config filename pattern: {path}")
    if ".local." in lowered or ".private." in lowered or ".secrets." in lowered:
        violations.append(f"forbidden local/private config filename pattern: {path}")
    if path.suffix.casefold() == ".tfstate" or ".tfstate." in lowered:
        violations.append(f"forbidden infrastructure state: {path}")
    return violations


def content_policy_violations(path: Path, text: str) -> list[str]:
    """Return publication-policy violations detected from UTF-8 text content."""
    violations: list[str] = []
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            violations.append(f"possible secret material: {path}")
            break

    # Tests may contain synthetic forbidden examples to exercise the policy. Public-facing
    # docs, configs, scripts and source code must not expose real workstation identities.
    if "tests/" not in path.as_posix():
        for pattern in PRIVATE_PATH_PATTERNS:
            if pattern.search(text):
                violations.append(f"possible machine-specific personal path: {path}")
                break
    return violations


def main() -> int:
    failures: list[str] = []
    for path in tracked_files():
        failures.extend(path_policy_violations(path))
        if not path.is_file() or path.stat().st_size > 1_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        failures.extend(content_policy_violations(path, text))

    if failures:
        print("Public-tree policy violations:")
        for failure in sorted(set(failures)):
            print(f"- {failure}")
        return 1
    print("Public-tree policy check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
