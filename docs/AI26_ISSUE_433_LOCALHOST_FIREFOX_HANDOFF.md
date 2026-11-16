# AI26 localhost / Firefox acceptance handoff (issue #433)

This checklist complements [AI26 Firefox browser collection](AI26_FIREFOX_BROWSER_COLLECTION.md) and [AI26 localhost collection](AI26_LOCALHOST_COLLECTION.md). It does **not** attest to a live browser test. The operator owns Firefox and private credentials; the collector owns the loopback server and AI26 distributed mirror.

## 1. Agent: prepare without collecting

Use the existing checkout and the **private** AI26 runtime configuration. Never copy secrets, targets, cookies, data, or profile directories into Git.

```bash
cd /path/to/LaclauGPT-Data-Collection
bash scripts/start_ai26_x_capture.sh --dry-run
python -m laclaugpt_data_collection.ai26_browser check --study-config /path/to/private/ai26.yaml
```

Confirm the active AI26 project/collection identity and remote MongoDB, Redis and Allas/S3 diagnostics. A passing command on one host does **not** prove availability on another host. Do not start a new database or change the default storage backend to local-only.

The Firefox endpoint is **not** a fixed port: `start_ai26_x_capture.sh` honors `LACLAUGPT_BROWSER_PORT` from the private runtime environment, defaulting to **8766**. Some older localhost deployment notes use **8765**. Use the port printed by **this host's** dry-run/status, not one copied from another host.

## 2. Agent: start/inspect the backend

```bash
bash scripts/start_ai26_x_capture.sh
bash scripts/start_ai26_x_capture.sh status
```

The launcher checks AI26 configuration, starts the loopback backend and probes `/status` and `/tour`. If the service is already managed by systemd, inspect its existing status instead of starting a second backend.

To inspect the selected port, use the endpoint from the launcher (replace PORT with its actual reported value):

```bash
curl --fail --silent --show-error http://127.0.0.1:PORT/status
curl --fail --silent --show-error http://127.0.0.1:PORT/tour
```

Require `study: ai26` (or equivalent confirmed project identity). On `/status`, inspect `distributed.enabled`, `distributed.last_error`, and synchronization/rejection counters. **Local capture success alone is not evidence that MongoDB or Allas received a record.** Do not confuse `/status` with an undocumented `/health` endpoint, and do not use an unimplemented `capture_server --verify-session` flag as a test.

## 3. Tomi: Firefox manual handoff

1. Open the **dedicated AI26 Firefox profile** using `about:profiles`, separate from other studies.
2. Open `about:debugging#/runtime/this-firefox` and load temporary add-on `browser/firefox/manifest.json`.
3. Configure the extension's `backend_url` to the exact loopback URL reported above. The extension defaults to port 8765, which may **not** match the AI26 backend's port.
4. Confirm the extension is active and the browser is ready. Browser login and navigation remain manual; the agent does not modify Tomi's profile or automate the browsing session.

**Stop/go gate:** no browser-dependent success claim until Tomi confirms this handoff.

## 4. Agent + Tomi: one-item bounded capture

Use **one approved public source** within the AI26 study sampling scope, and avoid unrestricted scrolling or bulk capture. Note the sanitized source family and a run timestamp (do not publish private targets or raw payloads).

1. Record pre-capture `/status` counters, local normalized row counts, and AI26 MongoDB canonical identity count.
2. Tomi visits the approved source with Firefox; confirm the capture counter increases.
3. Verify at least one canonical record has a stable `source_url`, source-native IDs where available, source/platform and capture time/provenance, and `project_id=ai26` / AI26 collection identity.
4. Inspect `/status` for mirror errors/rejections. If mirror is not complete, investigate the remote failures and, where appropriate for this deployment, use the existing `bash scripts/run_ai26_localhost_sync.sh` to retry. **Do not advance or delete offset/checkpoint files by hand.**
5. Read back the same canonical source identity from the **configured centralized MongoDB**, and verify any required raw/object reference is present in the AI26 Allas/S3 prefix. Redis is coordination, not the record store.
6. Re-run only the existing safe sync/retry path, read the same canonical identity again, and confirm no duplicate canonical identity. For an interrupted run, record whether the retry/resume completed or was blocked.
7. If the operator started the backend via the launcher, stop it with `bash scripts/start_ai26_x_capture.sh stop`. Do not stop an existing managed service without coordinating its owner.

If capture, remote write or read-back was not observed, mark that subtest **NOT RUN** or **BLOCKED**, never **PASS**.

## 5. Evidence template for issue #433

Post only sanitized values:

| Check | Result (PASS / FAIL / BLOCKED / NOT RUN) | Evidence |
| --- | --- | --- |
| AI26 identity + distributed preflight | | Command exit code; redacted diagnostics |
| Loopback /status and /tour | | Port, study identity, mirror enabled/error state |
| Tomi's Firefox profile/extension ready | | Handoff confirmed yes/no |
| One approved item captured | | Before/after counters, source family |
| AI26 canonical row written | | Canonical identity fields, no private content |
| Central MongoDB read-back | | Counts/dedup result, redacted reference |
| Allas/S3 reference and Redis control plane | | Sanitized status |
| Restart/resume and duplicate prevention | | Before/after canonical identity counts |

Do not mark the GitHub issue complete until the Firefox handoff and remote persistence acceptance checks have actual evidence.
