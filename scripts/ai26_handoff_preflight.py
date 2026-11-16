#!/usr/bin/env python3
"""Read-only readiness check for the AI26 localhost collection handoff (#433).

The issue splits responsibility: Tomi configures and launches Firefox, the agent prepares and
verifies everything else and the browser-dependent collection starts only after an explicit
handoff. This script is the handoff's factual half — it answers, without writing to any store,
changing any profile or printing a secret:

* is the private runtime env present and parseable (values are never echoed);
* do the study config and source manifest exist and parse;
* which record backend the env actually selects, and if it is MongoDB, can this host reach the
  configured database with the credentials it has;
* is a Firefox capture backend already listening, and what does its own ``/status`` say;
* does the named Firefox profile exist, and is the extension manifest in this checkout.

It never writes records, never starts a server, never edits a profile and never treats "no
credentials configured" as success. Exit codes:

    0  every prerequisite is satisfied — the bounded browser smoke test may start
    2  something is misconfigured (bad path, unparseable file, backend error)
    3  blocked on the operator (credentials not present here, Firefox not handed over)

    python scripts/ai26_handoff_preflight.py
    python scripts/ai26_handoff_preflight.py --json
    python scripts/ai26_handoff_preflight.py --env-file data/config/ai26-localhost.env
"""
from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

OK = "ok"
WARNING = "warning"
BLOCKED = "blocked"
MISCONFIGURED = "misconfigured"

EXIT_READY = 0
EXIT_MISCONFIGURED = 2
EXIT_BLOCKED = 3

#: Keys whose values are read to decide what to check, never to be printed.
SECRET_KEYS = re.compile(
    r"(URI|URL|PASSWORD|SECRET|TOKEN|KEY|CREDENTIAL)", re.IGNORECASE
)
#: Keys a MongoDB-backed localhost profile cannot work without.
REQUIRED_REMOTE_KEYS = ("LACLAUGPT_MONGODB_URI", "LACLAUGPT_MONGODB_DATABASE")


@dataclass
class Check:
    name: str
    status: str
    detail: str
    #: Non-secret facts a human needs to act on the result.
    facts: dict[str, Any] = field(default_factory=dict)


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a shell-style env file without executing it.

    Values stay in memory only; :func:`describe_env` is what gets printed.
    """
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def describe_env(env: dict[str, str]) -> dict[str, Any]:
    """What may be printed about an env file: key names, presence, and safe values."""
    safe: dict[str, Any] = {}
    for key, value in env.items():
        if SECRET_KEYS.search(key):
            safe[key] = "set" if value else "EMPTY"
        else:
            safe[key] = value
    return safe


def check_env_file(path: Path) -> Check:
    if not path.is_file():
        return Check(
            "runtime_env",
            BLOCKED,
            f"no private runtime env at {path} — copy .env.example there and fill it in; "
            "credentials must never be committed",
            {"path": str(path)},
        )
    try:
        env = read_env_file(path)
    except OSError as exc:
        return Check("runtime_env", MISCONFIGURED, f"cannot read {path}: {exc}", {"path": str(path)})
    if not env:
        return Check("runtime_env", MISCONFIGURED, f"{path} parses to no keys", {"path": str(path)})
    return Check(
        "runtime_env",
        OK,
        f"{len(env)} keys parsed from {path} (values not printed)",
        {"path": str(path), "keys": sorted(env)},
    )


def resolve(path_text: str, *, base: Path) -> Path:
    """Resolve a configured path the way the wrappers do: relative to the checkout."""
    candidate = Path(os.path.expanduser(path_text))
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def check_parseable(name: str, path: Path, *, env_var: str) -> Check:
    if not path.exists():
        return Check(
            name,
            BLOCKED,
            f"{env_var} points at {path}, which does not exist; the wrapper refuses rather than "
            "inventing one (see docs/AI26_LOCALHOST_COLLECTION.md §10)",
            {"path": str(path)},
        )
    try:
        if path.suffix == ".toml":
            import tomllib

            tomllib.loads(path.read_text(encoding="utf-8"))
        elif path.suffix in {".yaml", ".yml"}:
            import yaml

            yaml.safe_load(path.read_text(encoding="utf-8"))
        else:
            path.read_text(encoding="utf-8")
    except Exception as exc:  # a parse failure is a configuration failure, not a crash
        return Check(name, MISCONFIGURED, f"{path} does not parse: {exc}", {"path": str(path)})
    return Check(name, OK, f"{path} parses", {"path": str(path)})


def check_record_backend(env: dict[str, str]) -> Check:
    """Which store the env selects — the issue forbids a second local database as canonical."""
    backend = env.get("LACLAUGPT_RECORD_BACKEND", "auto").strip().lower()
    uri = env.get("LACLAUGPT_MONGODB_URI", "").strip()
    database = env.get("LACLAUGPT_MONGODB_DATABASE", "laclaugpt").strip() or "laclaugpt"
    facts = {"record_backend": backend, "mongodb_uri": "set" if uri else "EMPTY",
             "mongodb_database": database}
    if backend == "mongodb" and not uri:
        return Check(
            "record_backend",
            BLOCKED,
            "LACLAUGPT_RECORD_BACKEND=mongodb but LACLAUGPT_MONGODB_URI is empty: the store "
            "refuses to build rather than quietly writing locally (factory.build_record_store)",
            facts,
        )
    if backend in {"csv", "sqlite"}:
        return Check(
            "record_backend",
            WARNING,
            f"local-only profile ({backend}): canonical records stay on this machine, so the "
            "centralized-database acceptance criterion of #433 cannot be met with this env",
            facts,
        )
    if backend == "auto" and not uri:
        return Check(
            "record_backend",
            WARNING,
            "auto with no MongoDB URI degrades to a CSV store: this is the documented local-only "
            "workstation profile, not the centralized database",
            facts,
        )
    return Check("record_backend", OK, f"{backend} store selected with a configured URI", facts)


def connect_mongodb(uri: str, database: str, *, timeout_s: float = 5.0,
                    client_factory: Callable[[str, float], Any] | None = None) -> Any:
    if client_factory is None:
        from pymongo import MongoClient  # imported lazily: the local-only profile has no pymongo

        return MongoClient(uri, serverSelectionTimeoutMS=int(timeout_s * 1000),
                           connectTimeoutMS=int(timeout_s * 1000))
    return client_factory(uri, timeout_s)


def check_mongodb(uri: str, database: str, project_id: str, *,
                  client_factory: Callable[[str, float], Any] | None = None) -> Check:
    """Read-only reachability: ping, list collections, count this project's records.

    Nothing is written and no document is fetched, so the check cannot disturb the study store
    and cannot leak record content into a log.
    """
    facts: dict[str, Any] = {"database": database, "project_id": project_id}
    try:
        client = connect_mongodb(uri, database, client_factory=client_factory)
        client.admin.command("ping")
        db = client[database]
        names = sorted(db.list_collection_names())
        facts["collections"] = len(names)
        records = db["records"]
        facts["records_for_project"] = records.count_documents({"project_id": project_id})
        facts["records_total_sampled"] = records.estimated_document_count()
        client.close()
    except Exception as exc:  # unreachable host, bad credentials, missing driver
        return Check(
            "centralized_database",
            BLOCKED,
            f"cannot reach {database}: {type(exc).__name__}: {str(exc)[:200]}",
            facts,
        )
    return Check(
        "centralized_database",
        OK,
        f"ping ok; {facts['collections']} collections; "
        f"{facts['records_for_project']} records for project {project_id}",
        facts,
    )


def check_capture_backend(host: str, port: int, *, timeout_s: float = 3.0,
                          opener: Callable[[str, float], dict[str, Any]] | None = None) -> Check:
    """Ask a running Firefox capture backend about itself via its documented /status."""
    if opener is None:
        def default_opener(url: str, timeout: float) -> dict[str, Any]:
            with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")

        fetch = default_opener
    else:
        fetch = opener

    url = f"http://{host}:{port}/status"
    facts: dict[str, Any] = {"url": url}
    try:
        payload = fetch(url, timeout_s)
    except (URLError, OSError) as exc:
        return Check(
            "capture_backend",
            BLOCKED,
            f"nothing answering on {host}:{port} ({getattr(exc, 'reason', exc)}); start it with "
            "scripts/run_firefox_study.sh or the ai26-capture user service",
            facts,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        return Check("capture_backend", MISCONFIGURED, f"{url} did not return JSON: {exc}", facts)
    facts.update(
        study=str(payload.get("study", "")),
        collector=str(payload.get("collector", "")),
        active=bool(payload.get("active")),
        distributed=(payload.get("distributed") or {}).get("enabled"),
        captures=(payload.get("stats") or {}).get("captures"),
    )
    detail = (
        f"study={facts['study']} active={facts['active']} captures={facts['captures']} "
        f"distributed={facts['distributed']}"
    )
    if facts["study"] != "ai26":
        return Check("capture_backend", MISCONFIGURED,
                     f"backend answers but its study is {facts['study']!r}, not 'ai26'", facts)
    return Check("capture_backend", OK, detail, facts)


def candidate_profiles_ini() -> list[Path]:
    """Where Firefox actually keeps ``profiles.ini`` on this OS, in preference order.

    Ubuntu's Firefox is a snap, so the profile lives under ``~/snap`` rather than ``~/.mozilla``;
    a flatpak install puts it under ``~/.var``. Checking only ``~/.mozilla`` reports a Firefox
    that plainly exists as "not set up" — which is exactly what the first run of this script did.
    """
    home = Path.home()
    return [
        home / "snap" / "firefox" / "common" / ".mozilla" / "firefox" / "profiles.ini",
        home / ".var" / "app" / "org.mozilla.firefox" / ".mozilla" / "firefox" / "profiles.ini",
        home / ".mozilla" / "firefox" / "profiles.ini",
    ]


def find_firefox_profile(name: str, *, profiles_ini: Path | None = None) -> Check:
    """Locate a Firefox profile by name, read-only.

    The issue forbids altering Tomi's profile, so this only reads ``profiles.ini``.
    """
    candidates = [profiles_ini] if profiles_ini else candidate_profiles_ini()
    ini = next((c for c in candidates if c and c.is_file()), None)
    facts: dict[str, Any] = {"profile_name": name,
                            "profiles_ini": str(ini) if ini else [str(c) for c in candidates]}
    if ini is None:
        return Check("firefox_profile", BLOCKED,
                     f"no profiles.ini in {', '.join(str(c) for c in candidates)}; "
                     "Firefox is not set up on this host", facts)
    parser = configparser.ConfigParser()
    parser.read(ini, encoding="utf-8")
    declared = [parser.get(s, "Name", fallback="") for s in parser.sections() if s.startswith("Profile")]
    facts["declared_profiles"] = declared
    for section in parser.sections():
        if not section.startswith("Profile"):
            continue
        if parser.get(section, "Name", fallback="") != name:
            continue
        relative = parser.get(section, "IsRelative", fallback="1") == "1"
        raw = parser.get(section, "Path", fallback="")
        path = (ini.parent / raw) if relative else Path(raw)
        facts["path"] = str(path)
        facts["exists"] = path.is_dir()
        if not path.is_dir():
            return Check("firefox_profile", BLOCKED,
                         f"profile {name!r} is registered but {path} is missing", facts)
        return Check("firefox_profile", OK,
                     f"profile {name!r} at {path} (read-only check; this script never modifies it)",
                     facts)
    # The configured name being absent is an operator decision, not a code error: the env may
    # have been copied from another host. Report what does exist so the fix is obvious.
    return Check("firefox_profile", BLOCKED,
                 f"no Firefox profile named {name!r}; this host declares {declared}", facts)


def check_extension(checkout: Path) -> Check:
    manifest = checkout / "browser" / "firefox" / "manifest.json"
    if not manifest.is_file():
        return Check("capture_extension", MISCONFIGURED, f"{manifest} is missing", {"path": str(manifest)})
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Check("capture_extension", MISCONFIGURED, f"{manifest} is not JSON: {exc}",
                     {"path": str(manifest)})
    return Check(
        "capture_extension",
        OK,
        f"extension {data.get('name', '?')} {data.get('version', '?')} present; whether it is loaded "
        "in the browser is an operator check (about:debugging)",
        {"path": str(manifest), "version": data.get("version")},
    )


def run_preflight(env_file: Path, *, checkout: Path, capture_opener=None,
                  mongo_factory=None) -> list[Check]:
    checks: list[Check] = [check_env_file(env_file)]
    env = read_env_file(env_file) if env_file.is_file() else {}

    base = checkout
    study_config = env.get("LACLAUGPT_STUDY_CONFIG", "")
    source_manifest = env.get("LACLAUGPT_SOURCE_MANIFEST", "")
    if study_config:
        checks.append(check_parseable("study_config", resolve(study_config, base=base),
                                      env_var="LACLAUGPT_STUDY_CONFIG"))
    else:
        checks.append(Check("study_config", BLOCKED, "LACLAUGPT_STUDY_CONFIG is not set"))
    if source_manifest:
        checks.append(check_parseable("source_manifest", resolve(source_manifest, base=base),
                                      env_var="LACLAUGPT_SOURCE_MANIFEST"))
    else:
        checks.append(Check("source_manifest", BLOCKED, "LACLAUGPT_SOURCE_MANIFEST is not set"))

    backend = check_record_backend(env)
    checks.append(backend)
    uri = env.get("LACLAUGPT_MONGODB_URI", "").strip()
    if uri:
        checks.append(check_mongodb(uri, env.get("LACLAUGPT_MONGODB_DATABASE", "laclaugpt"),
                                    env.get("LACLAUGPT_PROJECT_ID", "ai26"),
                                    client_factory=mongo_factory))
    else:
        checks.append(Check(
            "centralized_database", BLOCKED,
            "no LACLAUGPT_MONGODB_URI in this env file, so read/write connectivity to the "
            "centralized database cannot be verified from this host",
        ))

    host = env.get("LACLAUGPT_BROWSER_HOST", "127.0.0.1")
    port = int(env.get("LACLAUGPT_BROWSER_PORT", "8765") or 8765)
    checks.append(check_capture_backend(host, port, opener=capture_opener))

    profile = env.get("LACLAUGPT_FIREFOX_PROFILE", "")
    if profile:
        checks.append(find_firefox_profile(profile))
    else:
        checks.append(Check("firefox_profile", BLOCKED, "LACLAUGPT_FIREFOX_PROFILE is not set"))
    checks.append(check_extension(checkout))
    return checks


def exit_code(checks: list[Check]) -> int:
    statuses = {c.status for c in checks}
    if MISCONFIGURED in statuses:
        return EXIT_MISCONFIGURED
    if BLOCKED in statuses:
        return EXIT_BLOCKED
    return EXIT_READY


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai26-handoff-preflight")
    parser.add_argument("--checkout", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--env-file")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    checkout = Path(args.checkout).resolve()
    env_file = Path(args.env_file) if args.env_file else Path(
        os.environ.get("LACLAUGPT_ENV_FILE") or checkout / "data" / "config" / "ai26-localhost.env"
    ).expanduser()

    checks = run_preflight(env_file, checkout=checkout)
    code = exit_code(checks)
    if args.json:
        print(json.dumps({"env_file": str(env_file), "checks": [asdict(c) for c in checks],
                          "exit_code": code}, indent=2, sort_keys=True, default=str))
        return code
    print(f"AI26 localhost handoff preflight — {env_file}")
    for check in checks:
        print(f"  [{check.status:12s}] {check.name:20s} {check.detail}")
    blocked = [c.name for c in checks if c.status == BLOCKED]
    print()
    if code == EXIT_READY:
        print("READY: every prerequisite is satisfied; the bounded browser smoke test may start.")
    elif code == EXIT_BLOCKED:
        print(f"BLOCKED on operator input: {', '.join(blocked)}. Nothing was written.")
    else:
        print(f"MISCONFIGURED: {', '.join(c.name for c in checks if c.status == MISCONFIGURED)}.")
    return code


if __name__ == "__main__":
    sys.exit(main())
