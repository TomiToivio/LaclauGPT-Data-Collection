#!/usr/bin/env python3
"""Read-only readiness report for AI26 localhost collection with Tomi's Firefox (issue #433).

The collector has two halves and they fail differently. The **data plane** (MongoDB, Redis, the S3
bucket) can be verified by an agent. The **browser half** cannot: it needs a Firefox profile with the
extension loaded and logged into the platforms, which is Tomi's to set up. This script keeps that
distinction explicit — a browser-dependent step is reported BLOCKED, never PASS, until the operator
says the browser is ready.

    python scripts/ai26_localhost_readiness.py
    python scripts/ai26_localhost_readiness.py --firefox-ready --json

It writes nothing, starts nothing, and never reads a credential value: it checks that variables are
*set*, probes the capture backend's own `/status` endpoint, and inspects file existence.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
INFO = "INFO"

#: Where the capture backend's own status endpoint lives by default on Laskin.
CAPTURE_URL = "http://127.0.0.1:8766/status"

#: Snap and packaged Firefox keep profiles in different places; both are normal.
PROFILE_PATTERNS = (
    "~/snap/firefox/common/.mozilla/firefox/profiles.ini",
    "~/.mozilla/firefox/profiles.ini",
)


def check(name: str, status: str, detail: str) -> dict[str, Any]:
    return {"check": name, "status": status, "detail": detail}


def _read_json(url: str, timeout: float = 5.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - explicit URL
            return json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def capture_endpoint_findings(payload: Mapping[str, Any] | None, url: str) -> list[dict[str, Any]]:
    """Interpret the capture backend's own status document."""
    if payload is None:
        return [check("capture backend", FAIL, f"no JSON from {url}")]
    study = str(payload.get("study") or "")
    active = bool(payload.get("active"))
    seen = payload.get("seen_total")
    stats = payload.get("stats") if isinstance(payload.get("stats"), Mapping) else {}
    results = [
        check("capture backend", PASS, f"answering at {url}"),
        check("capture backend is active", PASS if active else FAIL, f"active={active} study={study or '?'}"),
    ]
    if study and study != "ai26":
        results.append(check("capture backend serves AI26", FAIL, f"study={study}, expected ai26"))
    if isinstance(seen, int):
        results.append(check("capture backend has seen traffic", PASS if seen else INFO,
                             f"seen_total={seen}"))
    if stats:
        results.append(check("capture backend counters", INFO,
                             ", ".join(f"{key}={value}" for key, value in sorted(stats.items()))))
    return results


def firefox_findings(extension_manifest: Path, firefox_ready: bool) -> list[dict[str, Any]]:
    """What can be known about the browser without touching Tomi's profile."""
    binary = shutil.which("firefox") or shutil.which("firefox-esr")
    profiles = next((Path(pattern).expanduser() for pattern in PROFILE_PATTERNS
                     if Path(pattern).expanduser().is_file()), None)
    results = [
        check("firefox installed", PASS if binary else FAIL, binary or "no firefox on PATH"),
        check("firefox profile present", PASS if profiles else FAIL,
              str(profiles) if profiles else "no profiles.ini in the snap or classic location"),
        check("capture extension manifest", PASS if extension_manifest.is_file() else FAIL,
              str(extension_manifest)),
    ]
    if firefox_ready:
        results.append(check("browser capture handoff", PASS,
                             "operator declared Firefox ready; browser-dependent collection may run"))
    else:
        results.append(check(
            "browser capture handoff", BLOCKED,
            "Tomi must load browser/firefox/manifest.json into the AI26 profile, log into the "
            "platforms and confirm; until then the browser smoke test is BLOCKED, not passed"))
    return results


def service_state(unit: str) -> tuple[str, str]:
    """(state, scope) for one unit, trying the user manager first and then the system one.

    Both AI26 units on Laskin happen to be user units, and asking the system manager about a user
    unit returns "inactive" without an error -- which reads as a failure of the service rather than
    of the question.
    """
    for scope, extra in (("user", ["--user"]), ("system", [])):
        try:
            result = subprocess.run(["systemctl", *extra, "is-active", unit],
                                    capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        state = (result.stdout or "").strip()
        if state and state != "inactive":
            return state, scope
        if scope == "system":
            return state or "unknown", scope
    return "unknown", "unavailable"


def service_findings(unit: str) -> list[dict[str, Any]]:
    state, scope = service_state(unit)
    return [check(unit, PASS if state == "active" else FAIL, f"{state} ({scope} manager)")]


def environment_findings(required: Sequence[str]) -> list[dict[str, Any]]:
    """Variables that must be set for the data plane; values are never printed."""
    missing = [name for name in required if not os.environ.get(name)]
    return [check("data-plane environment", PASS if not missing else FAIL,
                  "all required variables set" if not missing else "missing: " + ", ".join(missing))]


def candidate_urls(explicit: str | None) -> list[str]:
    """Where the capture backend might answer: explicit, loopback, then the bind host.

    The Laskin backend binds the Tailscale address rather than loopback, so a loopback-only probe
    reports "no backend" about a service that is running.
    """
    urls: list[str] = []
    if explicit:
        urls.append(explicit)
    urls.append(CAPTURE_URL)
    host = os.environ.get("AI26_BIND_HOST")
    if host:
        urls.append(f"http://{host}:8766/status")
    seen: list[str] = []
    for url in urls:
        if url not in seen:
            seen.append(url)
    return seen


def probe_capture(explicit: str | None) -> tuple[dict[str, Any] | None, str]:
    for url in candidate_urls(explicit):
        payload = _read_json(url)
        if payload is not None:
            return payload, url
    return None, candidate_urls(explicit)[0]


def evaluate(*, capture_url: str | None, extension_manifest: Path, firefox_ready: bool,
             required_env: Sequence[str], export_unit: str = "ai26-export.service",
             capture_unit: str = "ai26-capture.service") -> list[dict[str, Any]]:
    """Every finding in one list. Probes are injectable so the logic is testable offline."""
    results: list[dict[str, Any]] = []
    results += environment_findings(required_env)
    payload, answered = probe_capture(capture_url)
    results += capture_endpoint_findings(payload, answered)
    results += service_findings(capture_unit)
    results += service_findings(export_unit)
    results += firefox_findings(extension_manifest, firefox_ready)
    return results


def summarise(results: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Counts keyed in lower case, so the JSON reads the same as the printed summary."""
    counts = {"pass": 0, "fail": 0, "blocked": 0, "info": 0}
    for item in results:
        key = str(item.get("status", "")).lower()
        counts[key] = counts.get(key, 0) + 1
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    here = Path(__file__).resolve().parents[1]
    parser.add_argument("--capture-url", default=os.environ.get("AI26_CAPTURE_URL"),
                        help="status URL; defaults to probing loopback and AI26_BIND_HOST")
    parser.add_argument("--extension-manifest", type=Path,
                        default=here / "browser" / "firefox" / "manifest.json")
    parser.add_argument("--firefox-ready", action="store_true",
                        help="the operator has confirmed Tomi's Firefox and extension are ready")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    required = ("LACLAUGPT_MONGODB_URI", "LACLAUGPT_REDIS_URL", "LACLAUGPT_PROJECT_ID")
    results = evaluate(capture_url=args.capture_url, extension_manifest=args.extension_manifest,
                       firefox_ready=args.firefox_ready, required_env=required)
    counts = summarise(results)

    if args.json:
        print(json.dumps({"checks": results, "summary": counts}, indent=2, sort_keys=True))
    else:
        width = max(len(item["check"]) for item in results)
        for item in results:
            print(f"{item['status']:8} {item['check']:<{width}}  {item['detail']}")
        print(f"\n{counts['pass']} pass, {counts['fail']} fail, {counts['blocked']} blocked")

    # Blocked is not a failure of this script: it is the handoff waiting on a human. A FAIL is.
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
