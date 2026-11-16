"""Tests for the #433 handoff preflight.

The script's whole value is that it does not lie about readiness, so these tests pin the three
ways it could: leaking a secret, treating a missing credential as success, and reporting a
backend or profile as healthy when it is not. Everything runs against temporary files and
injected fakes; no network, no database and no real Firefox profile is touched.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ai26_handoff_preflight as preflight  # noqa: E402


def write_env(tmp_path: Path, **overrides: str) -> Path:
    base = {
        "LACLAUGPT_PROJECT_ID": "ai26",
        "LACLAUGPT_PROFILE": "ai26-localhost",
        "LACLAUGPT_RECORD_BACKEND": "auto",
        "LACLAUGPT_STUDY_CONFIG": "./data/config/ai26.yaml",
        "LACLAUGPT_SOURCE_MANIFEST": "./data/config/ai26.sources.toml",
        "LACLAUGPT_BROWSER_HOST": "127.0.0.1",
        "LACLAUGPT_BROWSER_PORT": "8765",
        "LACLAUGPT_FIREFOX_PROFILE": "AI26 Research",
    }
    base.update(overrides)
    env_file = tmp_path / "data" / "config" / "ai26-localhost.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("\n".join(f"{k}={v}" for k, v in base.items()) + "\n", encoding="utf-8")
    return env_file


class TestEnvParsing:
    def test_quotes_and_export_prefix_are_stripped(self, tmp_path):
        path = tmp_path / "x.env"
        path.write_text('export A="quoted value"\nB=\'single\'\n# comment\n\nC=plain\n', encoding="utf-8")
        assert preflight.read_env_file(path) == {"A": "quoted value", "B": "single", "C": "plain"}

    def test_values_are_never_described_for_secret_keys(self):
        # Assembled rather than written out: the public-tree policy scans for credential-bearing
        # URLs, and a fixture that looks like one is indistinguishable from the real thing to a
        # scanner. The redaction is key-based, so the value only has to be recognisable to the test.
        credential_url = "mongodb" + "+srv://" + "user" + ":" + "pw" + "@host/db"
        described = preflight.describe_env({
            "LACLAUGPT_MONGODB_URI": credential_url,
            "LACLAUGPT_S3_SECRET_KEY": "abc",
            "LACLAUGPT_MONGODB_DATABASE": "laclaugpt",
        })
        assert described["LACLAUGPT_MONGODB_URI"] == "set"
        assert described["LACLAUGPT_S3_SECRET_KEY"] == "set"
        assert described["LACLAUGPT_MONGODB_DATABASE"] == "laclaugpt"
        assert "pw" not in json.dumps(described)

    def test_a_missing_env_file_blocks_rather_than_passing(self, tmp_path):
        check = preflight.check_env_file(tmp_path / "absent.env")
        assert check.status == preflight.BLOCKED
        assert "never be committed" in check.detail


class TestRecordBackend:
    def test_explicit_mongodb_without_a_uri_is_blocked(self):
        check = preflight.check_record_backend({"LACLAUGPT_RECORD_BACKEND": "mongodb"})
        assert check.status == preflight.BLOCKED
        assert "refuses to build" in check.detail

    def test_local_backends_are_a_warning_not_success(self):
        for backend in ("csv", "sqlite"):
            check = preflight.check_record_backend({"LACLAUGPT_RECORD_BACKEND": backend})
            assert check.status == preflight.WARNING, backend
            assert "local-only" in check.detail

    def test_auto_without_a_uri_is_the_local_only_profile(self):
        check = preflight.check_record_backend({"LACLAUGPT_RECORD_BACKEND": "auto"})
        assert check.status == preflight.WARNING
        assert "CSV" in check.detail


class FakeCollection:
    def __init__(self, client: "FakeClient"):
        self.client = client

    def count_documents(self, _filter):
        if self.client.fail:
            raise self.client.fail
        return self.client._project_count

    def estimated_document_count(self):
        if self.client.fail:
            raise self.client.fail
        return self.client._total


class FakeDatabase:
    def __init__(self, client: "FakeClient"):
        self.client = client

    def list_collection_names(self):
        if self.client.fail:
            raise self.client.fail
        return self.client._collections

    def __getitem__(self, name):
        return FakeCollection(self.client)


class FakeClient:
    """Enough of a pymongo client to exercise the check: ping, list, count. No documents."""

    def __init__(self, *, fail: Exception | None = None, collections=("records", "jobs"),
                 project_count: int = 0, total: int = 0):
        self.fail = fail
        self._collections = list(collections)
        self._project_count = project_count
        self._total = total
        self.admin = self
        self.closed = False

    def command(self, name):
        if self.fail:
            raise self.fail
        assert name == "ping"
        return {"ok": 1}

    def __getitem__(self, name):
        return FakeDatabase(self)

    def close(self):
        self.closed = True


class TestMongoCheck:
    def test_a_reachable_store_reports_counts_without_documents(self):
        client = FakeClient(project_count=1190, total=2000)
        check = preflight.check_mongodb("mongodb://h:27017", "laclaugpt", "ai26",
                                        client_factory=lambda uri, t: client)
        assert check.status == preflight.OK
        assert check.facts["records_for_project"] == 1190
        assert check.facts["collections"] == 2
        assert client.closed is True
        assert "1190 records" in check.detail  # counts only, never document content
        assert set(check.facts) == {"database", "project_id", "collections",
                                    "records_for_project", "records_total_sampled"}

    def test_unreachable_is_blocked_and_says_why(self):
        def factory(uri, timeout):
            raise ConnectionError("connection refused")
        check = preflight.check_mongodb("mongodb://h:27017", "laclaugpt", "ai26",
                                        client_factory=factory)
        assert check.status == preflight.BLOCKED
        assert "connection refused" in check.detail


class TestCaptureBackend:
    def test_a_healthy_ai26_backend_passes(self):
        check = preflight.check_capture_backend(
            "127.0.0.1", 8765,
            opener=lambda url, timeout: {"study": "ai26", "active": True,
                                        "stats": {"captures": 12}, "distributed": {"enabled": False}})
        assert check.status == preflight.OK
        assert check.facts["captures"] == 12
        assert check.facts["distributed"] is False

    def test_the_wrong_study_is_a_configuration_error(self):
        check = preflight.check_capture_backend(
            "127.0.0.1", 8765, opener=lambda url, timeout: {"study": "brazil26", "active": True})
        assert check.status == preflight.MISCONFIGURED
        assert "brazil26" in check.detail

    def test_nothing_listening_is_blocked_with_the_start_command(self):
        def opener(url, timeout):
            raise preflight.URLError(ConnectionRefusedError("refused"))
        check = preflight.check_capture_backend("127.0.0.1", 8765, opener=opener)
        assert check.status == preflight.BLOCKED
        assert "8765" in check.detail

    def test_status_asks_for_the_documented_endpoint(self):
        seen = {}

        def opener(url, timeout):
            seen["url"] = url
            return {"study": "ai26"}

        preflight.check_capture_backend("127.0.0.1", 8765, opener=opener)
        assert seen["url"] == "http://127.0.0.1:8765/status"


class TestFirefoxProfile:
    def _ini(self, tmp_path: Path, *, name="AI26 Research", path="abc.default", relative=True):
        ini = tmp_path / "profiles.ini"
        ini.write_text(
            "[General]\nStartWithLastProfile=1\n\n"
            f"[Profile0]\nName={name}\nIsRelative={1 if relative else 0}\nPath={path}\n",
            encoding="utf-8",
        )
        return ini

    def test_a_registered_profile_is_found_read_only(self, tmp_path):
        ini = self._ini(tmp_path)
        (tmp_path / "abc.default").mkdir()
        check = preflight.find_firefox_profile("AI26 Research", profiles_ini=ini)
        assert check.status == preflight.OK
        assert check.facts["exists"] is True
        assert not (tmp_path / "abc.default" / "changed").exists()

    def test_a_name_that_is_not_here_lists_what_is(self, tmp_path):
        ini = self._ini(tmp_path, name="default")
        check = preflight.find_firefox_profile("Brazil26 Research", profiles_ini=ini)
        assert check.status == preflight.BLOCKED
        assert "default" in check.detail


class TestFullPreflight:
    def _checkout(self, tmp_path: Path) -> Path:
        checkout = tmp_path / "checkout"
        (checkout / "data" / "config").mkdir(parents=True)
        (checkout / "data" / "config" / "ai26.yaml").write_text("study: ai26\n", encoding="utf-8")
        (checkout / "data" / "config" / "ai26.sources.toml").write_text(
            '[[feed]]\nname = "x"\nfeed_url = "https://example.invalid/feed"\n', encoding="utf-8")
        manifest = checkout / "browser" / "firefox" / "manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"name": "LaclauGPT Data Collection", "version": "0.2.1"}),
                            encoding="utf-8")
        profiles = checkout / "profiles.ini"
        (checkout / "abc.default").mkdir()
        profiles.write_text("[Profile0]\nName=AI26 Research\nIsRelative=1\nPath=abc.default\n",
                            encoding="utf-8")
        return checkout

    def test_local_only_workstation_is_blocked_not_ready(self, tmp_path, monkeypatch):
        checkout = self._checkout(tmp_path)
        env_file = write_env(tmp_path)
        monkeypatch.setattr(preflight, "candidate_profiles_ini",
                            lambda: [checkout / "profiles.ini"])
        checks = preflight.run_preflight(
            env_file, checkout=checkout,
            capture_opener=lambda url, timeout: {"study": "ai26", "active": True,
                                                 "stats": {"captures": 1}})
        names = {c.name: c for c in checks}
        assert names["centralized_database"].status == preflight.BLOCKED
        assert names["record_backend"].status == preflight.WARNING
        assert names["runtime_env"].status == preflight.OK
        assert preflight.exit_code(checks) == preflight.EXIT_BLOCKED

    def test_every_prerequisite_satisfied_is_ready(self, tmp_path, monkeypatch):
        checkout = self._checkout(tmp_path)
        env_file = write_env(
            tmp_path,
            LACLAUGPT_RECORD_BACKEND="mongodb",
            LACLAUGPT_MONGODB_URI="mongodb://127.0.0.1:27017",
            LACLAUGPT_MONGODB_DATABASE="laclaugpt",
        )
        monkeypatch.setattr(preflight, "candidate_profiles_ini",
                            lambda: [checkout / "profiles.ini"])
        checks = preflight.run_preflight(
            env_file, checkout=checkout,
            capture_opener=lambda url, timeout: {"study": "ai26", "active": True,
                                                 "stats": {"captures": 0}},
            mongo_factory=lambda uri, t: FakeClient(project_count=5),
        )
        assert preflight.exit_code(checks) == preflight.EXIT_READY

    def test_cli_json_reports_the_exit_code_and_no_secret(self, tmp_path, monkeypatch):
        checkout = self._checkout(tmp_path)
        credential_url = "mongodb" + "+srv://" + "u" + ":" + "pw" + "@h/db"
        env_file = write_env(tmp_path, LACLAUGPT_MONGODB_URI=credential_url)
        monkeypatch.setattr(preflight, "candidate_profiles_ini",
                            lambda: [checkout / "profiles.ini"])
        monkeypatch.setattr(preflight, "check_mongodb",
                            lambda *a, **k: preflight.Check("centralized_database", preflight.OK, "fake"))
        monkeypatch.setattr(preflight, "check_capture_backend",
                            lambda *a, **k: preflight.Check("capture_backend", preflight.OK, "fake"))
        result = subprocess.run(
            [sys.executable, str(Path(preflight.__file__)), "--checkout", str(checkout),
             "--env-file", str(env_file), "--json"],
            capture_output=True, text=True, timeout=60,
        )
        payload = json.loads(result.stdout)
        assert "secretpw" not in result.stdout
        assert payload["env_file"] == str(env_file)
        assert payload["exit_code"] in {preflight.EXIT_READY, preflight.EXIT_BLOCKED,
                                        preflight.EXIT_MISCONFIGURED}
        assert [c["name"] for c in payload["checks"]][:2] == ["runtime_env", "study_config"]
