"""Browser-extension checks: manifest validity, JS syntax, privacy contract.

Node is optional: when absent, these tests skip (CI installs Node 22).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

EXTENSION_DIR = Path(__file__).parents[1] / "browser" / "firefox"
REPO_ROOT = Path(__file__).parents[1]


def js_text(path: Path) -> str:
    return path.read_text(encoding="utf-8" )


def test_manifest_is_valid_and_minimal() -> None:
    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 2
    permissions = manifest["permissions"]
    assert "<all_urls>" not in permissions, "host permissions must be explicit"
    assert "downloads" not in permissions, "media downloads are not an extension feature"
    assert "history" not in permissions
    assert "cookies" not in permissions
    hosts = [p for p in permissions if "*://" in p]
    assert hosts == [
        "*://*.tiktok.com/*", "*://*.instagram.com/*",
        "*://*.x.com/*", "*://*.twitter.com/*",
    ]
    gecko = manifest["browser_specific_settings"]["gecko"]
    assert gecko["id"].endswith("@laclaugpt.org")


def test_extension_files_exist() -> None:
    for name in ("capture.js", "content.js", "navigation.js", "manifest.json"):
        assert (EXTENSION_DIR / name).is_file()


def test_no_credentials_embedded() -> None:
    for js in sorted(EXTENSION_DIR.glob("*.js")):
        text = js.read_text(encoding="utf-8")
        lowered = text.lower()
        assert "authorization" not in lowered, js
        assert "api_key" not in lowered, js
        assert "password" not in lowered, js
    # backend default is loopback only
    capture = (EXTENSION_DIR / "capture.js").read_text(encoding="utf-8")
    assert "127.0.0.1:8765" in capture


def test_capture_posts_to_local_backend() -> None:
    text = (EXTENSION_DIR / "capture.js").read_text(encoding="utf-8")
    assert "credentials: \"omit\"" in text
    assert "/capture" in text
    assert "filterResponseData" in text
    assert 'filter.write(event.data)' in text  # byte-exact site passthrough


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_files_pass_node_syntax_check() -> None:
    for js in sorted(EXTENSION_DIR.glob("*.js")):
        result = subprocess.run(
            ["node", "--input-type=module", "--check", "--", str(js)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            # classic-script fallback for MV2 background/content scripts
            result = subprocess.run(
                ["node", "--check", str(js)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"{js.name}: {result.stderr}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_no_es_module_imports_in_classic_scripts() -> None:
    # MV2 background/content scripts are classic scripts: no ES imports.
    for js in sorted(EXTENSION_DIR.glob("*.js")):
        text = js_text(js)
        for line in text.splitlines():
            stripped = line.strip()
            assert not stripped.startswith("import "), f"{js.name}: {line}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_matchers_cover_legacy_salvage_endpoints() -> None:
    """Legacy-salvaged TikTok endpoints must be routable from capture.js."""
    text = (EXTENSION_DIR / "capture.js").read_text(encoding="utf-8")
    for fragment in ("comment\\/list", "user\\/detail", "challenge\\/detail"):
        assert fragment in text, fragment

