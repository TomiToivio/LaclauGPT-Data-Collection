"""Brazil26 source-family allowlist (issue #233).

Brazil26 collects from **X, Instagram and TikTok only**. The deployment profile
must disable RSS, YouTube, Telegram, Reddit, Bluesky, Mastodon, arXiv and every
other source family, and it must do so *mechanically* — not by hoping nobody
configures them.

This module is the single place that decision lives. A study manifest declares

.. code-block:: toml

    enabled_platforms = ["x", "instagram", "tiktok"]

and every collector consults :func:`enabled_plugin_ids` / :func:`platform_allowed`
before running. There is deliberately no implicit default: a manifest that does
not declare ``enabled_platforms`` enables **nothing**, so an old manifest cannot
silently re-enable RSS.

The mapping is one-way and explicit: each platform name maps to the collection
plugin id(s) that implement it. Browser platforms (``x``/``instagram``/``tiktok``)
are not first-party plugins; they are captured by the Firefox extension, so they
map to the empty tuple and are only consulted by the media worker and preflight.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any, Iterable, Mapping

#: The source families the Brazil26 deployment is allowed to collect from.
BRAZIL26_PLATFORMS: tuple[str, ...] = ("x", "instagram", "tiktok")

#: Every source family the repo knows how to collect, mapped to the plugin id(s)
#: that implement it. A platform absent from this map cannot be enabled by a
#: manifest — a typo is an error, never a silent pass.
PLATFORM_PLUGINS: Mapping[str, tuple[str, ...]] = {
    "x": (),            # Firefox capture; no first-party plugin
    "instagram": (),    # Firefox capture
    "tiktok": (),       # Firefox capture
    "rss": ("rss",),
    "youtube": ("youtube",),
    "telegram": ("telegram",),
    "reddit": ("reddit",),
    "bluesky": ("bluesky",),
    "mastodon": ("mastodon",),
    "arxiv": ("arxiv",),
}

#: Platforms that are collected by the browser extension rather than a plugin.
BROWSER_PLATFORMS: frozenset[str] = frozenset({"x", "instagram", "tiktok"})

_MANIFEST_KEYS = ("enabled_platforms", "enabled_sources")


class SourceAllowlistError(ValueError):
    """Raised when a manifest's source policy is missing or incoherent."""


def enabled_platforms(manifest: Mapping[str, Any]) -> frozenset[str]:
    """Return the platforms a manifest enables, or the empty set if it declares none.

    ``enabled_platforms`` is the canonical key; ``enabled_sources`` is accepted
    as an alias so older manifests keep working. Unknown platform names raise, so
    a typo surfaces instead of quietly collecting the wrong sources.
    """
    declared: Any = None
    for key in _MANIFEST_KEYS:
        if key in manifest:
            declared = manifest[key]
            break
    if declared is None:
        return frozenset()
    if not isinstance(declared, list) or not all(isinstance(item, str) for item in declared):
        raise SourceAllowlistError("enabled_platforms must be a list of strings")
    unknown = sorted({item.strip().lower() for item in declared} - set(PLATFORM_PLUGINS))
    if unknown:
        raise SourceAllowlistError(
            "unknown source platform(s): " + ", ".join(unknown)
            + "; known: " + ", ".join(sorted(PLATFORM_PLUGINS))
        )
    return frozenset(item.strip().lower() for item in declared)


def enabled_plugin_ids(manifest: Mapping[str, Any]) -> frozenset[str]:
    """Return the collection plugin ids the manifest's platforms resolve to.

    A manifest that enables only browser platforms (the Brazil26 default)
    returns the empty set — correctly, because no *plugin* may run. RSS and
    YouTube return their plugin ids and are therefore refused by the Brazil26
    wrappers.
    """
    plugin_ids: set[str] = set()
    for platform in enabled_platforms(manifest):
        plugin_ids.update(PLATFORM_PLUGINS[platform])
    return frozenset(plugin_ids)


def platform_allowed(manifest: Mapping[str, Any], platform: str) -> bool:
    """True when ``platform`` is explicitly enabled by the manifest."""
    return platform.strip().lower() in enabled_platforms(manifest)


def filter_allowed_platforms(
    allowlist: Iterable[str], platforms: Iterable[str]
) -> list[str]:
    """Keep only ``platforms`` that are in ``allowlist``, preserving order.

    Used by the media worker to skip a queued job whose platform a stricter
    profile has since disabled, rather than downloading it and filtering later.
    """
    allowed = {item.strip().lower() for item in allowlist}
    return [p for p in platforms if str(p).strip().lower() in allowed]


def load_manifest(manifest_path: str | Path) -> dict[str, Any]:
    """Read a TOML source manifest. Missing files raise ``FileNotFoundError``."""
    path = Path(manifest_path)
    if not path.is_file():
        raise FileNotFoundError(f"source manifest not found: {path}")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def assert_brazil26_only(manifest: Mapping[str, Any]) -> frozenset[str]:
    """Fail loudly if a manifest enables anything outside X/Instagram/TikTok.

    This is the guard the #233 acceptance criteria rest on: the Brazil26
    deployment must *prove* it collects exactly three source families. It is
    called by preflight and by ``brazil26_localhost_collect``.
    """
    platforms = enabled_platforms(manifest)
    extra = sorted(platforms - set(BRAZIL26_PLATFORMS))
    if extra:
        raise SourceAllowlistError(
            "Brazil26 collects X/Instagram/TikTok only; manifest also enables: "
            + ", ".join(extra)
        )
    return platforms


def main(argv: list[str] | None = None) -> int:
    """CLI used by the shell wrappers to gate a source family.

    ``--manifest M --require-plugin rss`` exits 0 only when the manifest enables
    the ``rss`` plugin; otherwise it prints the reason to stderr and exits 3. The
    wrappers use this to skip a whole pass (e.g. the RSS scheduler) for a
    manifest that does not permit it, instead of running it and filtering after.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="laclaugpt-source-allowlist")
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--require-plugin",
        default="",
        help="exit 0 only if the manifest enables this collection plugin id",
    )
    parser.add_argument(
        "--require-brazil26-only",
        action="store_true",
        help="fail if the manifest enables anything outside X/Instagram/TikTok",
    )
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
    except (FileNotFoundError, tomllib.TOMLDecodeError) as exc:
        print(f"source manifest unreadable: {exc}", file=sys.stderr)
        return 2

    try:
        if args.require_brazil26_only:
            assert_brazil26_only(manifest)
        plugins = enabled_plugin_ids(manifest)
    except SourceAllowlistError as exc:
        print(str(exc), file=sys.stderr)
        return 3

    if args.require_plugin and args.require_plugin.strip() not in plugins:
        print(
            f"source family {args.require_plugin!r} is not enabled by {args.manifest}",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover

    raise SystemExit(main())
