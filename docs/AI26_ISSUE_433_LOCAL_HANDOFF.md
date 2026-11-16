# AI26 localhost collection — handoff checkpoint (#433)

This is the operator handoff for #433: what is already verified on this workstation, what the agent may
start without Tomi, and what stays blocked until Tomi supplies credentials or a browser session. The
setup narrative lives in [`AI26_LOCALHOST_COLLECTION.md`](AI26_LOCALHOST_COLLECTION.md) and
[`AI26_FIREFOX_BROWSER_COLLECTION.md`](AI26_FIREFOX_BROWSER_COLLECTION.md); this page does not repeat it.

Read the preflight before every browser-dependent run. It is read-only: it writes no record, starts no
server, edits no Firefox profile and prints no secret value.

```bash
python scripts/ai26_handoff_preflight.py          # human-readable, exit 0/2/3
python scripts/ai26_handoff_preflight.py --json   # same checks, machine-readable
```

Exit codes: `0` every prerequisite satisfied — the bounded browser smoke test may start; `2` something
is misconfigured and will not work until changed; `3` blocked on the operator.

## The split

**Tomi:** launch Firefox with the capture extension loaded and say it is ready. Nothing here ever
launches or reconfigures Firefox, and nothing here writes into a profile.

**Agent:** run the preflight, run the bounded non-browser collection, and only after Tomi's explicit
"ready" do the browser-dependent smoke test — then read the records back and report counts, ids,
timestamps and deduplication. A blocked check is reported as *blocked*, never as *passed*.

## State on this workstation (verified 2026-11-08)

Preflight output, values sanitised:

```
[ok          ] runtime_env          23 keys parsed from data/config/ai26-localhost.env (values not printed)
[ok          ] study_config         .../LaclauGPT-Private/collection/ai26/ai26.private.yaml parses
[blocked     ] source_manifest      LACLAUGPT_SOURCE_MANIFEST points at data/config/ai26.sources.toml, which does not exist
[warning     ] record_backend       auto with no MongoDB URI degrades to a CSV store: local-only profile, not the centralized database
[blocked     ] centralized_database no LACLAUGPT_MONGODB_URI in this env file
[ok          ] capture_backend      study=ai26 active=True captures=12823 distributed=False
[blocked     ] firefox_profile      no Firefox profile named 'Brazil26 Research'; this host declares ['default']
[ok          ] capture_extension    extension LaclauGPT Data Collection 0.2.1 present
```

What that means in plain terms:

| Criterion from #433 | State |
|---|---|
| Collector starts on localhost without a second database | ✅ the documented architecture already is this; `ai26-capture.service` is running on loopback |
| Read/write connectivity to the centralized database | ⛔ **not verified** — this env has no MongoDB URI, so the store is local-only |
| Firefox-dependent collection with Tomi's browser | ⛔ **not verified now** — the backend is up and has 12,823 captures, but no session is feeding it and the configured profile name does not exist on this host |
| Bounded smoke test persisted and read back, no duplicates on resume | ✅ for the collection mechanism (see below); ⛔ for the centralized store, which cannot be reached |
| Reproducible runbook and sanitised evidence | this page plus `scripts/ai26_handoff_preflight.py` |
| Blocked tests clearly reported | below |

### The backend is genuinely running

```
$ systemctl --user status ai26-capture.service
ai26-capture.service  loaded active running  AI26 Firefox capture backend (loopback 8765, study ai26; local-only profile)

$ curl -s http://127.0.0.1:8765/status
{"collector": "laclaugpt-data-collection-0.1.0", "study": "ai26", "active": true,
 "stats": {"captures": 12823, "posts": 8949, "errors": 0, "x_unattributed": 2171},
 "seen_total": 10241, "capture_media_inline": true,
 "distributed": {"enabled": false, "reason": "local-only profile: no distributed mirror"}}
```

Two corrections to earlier notes on this issue, both verified against the code:

* the capture backend listens on **8765**, not 8766 (`CaptureServer.__init__`, `--port` default);
* there is **no `/health` endpoint and no `--verify-session` flag**. `GET /status` is the read-only
  probe; `/ping` exists but answers **POST** only (`GET /ping` → 404).

### Bounded collection smoke test (isolated, real)

Run twice against a throwaway data root and a local sqlite store, with a two-row manifest so the run is
bounded by construction:

```
$ python -m laclaugpt_data_collection.ai26_localhost_collect \
      --source-manifest $SMOKE/mini.toml --study-config configs/studies/ai26.example.yaml
run 1: ai_governance_smoke | seen 10 | written 10 | duplicates 0 | ok
run 2: ai_governance_smoke | seen 10 | written  0 | duplicates 10 | ok
records in store: 10
```

Read back from the store, one record: `schema_version 1.1.0`, `source_url https://arxiv.org/abs/…`,
`source_native_ids.document_id`, `provenance[0].captured_at`, `module arxiv-client`,
`raw_metadata.project_id ai26`, `raw_metadata.collection_id ai26`, `raw_metadata.arena elites`.
Re-running the same command writes nothing and skips all ten as duplicates, which is the restart/resume
behaviour #433 asks to see — demonstrated without touching the study store or the shared database.

Observation, not a defect: `source.collected_at` is `null` on these records while
`provenance[0].captured_at` is set. Provenance is the canonical place for capture time; anything that
reads `source.collected_at` for freshness will see nothing.

## What Tomi needs to supply

1. **Centralized database access.** Put `LACLAUGPT_MONGODB_URI` and `LACLAUGPT_MONGODB_DATABASE` in
   `data/config/ai26-localhost.env` and set `LACLAUGPT_RECORD_BACKEND=mongodb` (explicit, so a typo
   fails loudly instead of degrading to CSV — `factory.build_record_store` refuses to build a mongodb
   store without a URI). Read/write permission is needed on the `records` collection for the run to
   persist, and `ai26__records` / queue collections for `--dispatch-mongo`. Then:

   ```bash
   python scripts/ai26_handoff_preflight.py   # expects centralized_database: ok
   ```

2. **The source manifest.** `data/config/ai26.sources.toml` does not exist here, so the collect wrapper
   stops by design. Either point `LACLAUGPT_SOURCE_MANIFEST` at the private manifest used on the other
   hosts, or authorise copying the public template:

   ```bash
   cp configs/studies/ai26.sources.example.toml data/config/ai26.sources.toml
   ```

   The template is public and bounded; the private manifest may add rows the study needs.

3. **A browser profile decision.** `LACLAUGPT_FIREFOX_PROFILE` names `Brazil26 Research`, which this
   host does not have — its snap Firefox declares only `default`. Either open Firefox with the
   AI26-research profile (and correct the name), or confirm that `default` is the intended profile.
   The agent will not edit that file or that profile.

## After the handoff

```bash
# 1. Tomi: Firefox open, extension loaded (about:debugging → This Firefox → Load Temporary Add-on →
#    browser/firefox/manifest.json), then says it is ready.
python scripts/ai26_handoff_preflight.py            # all ok or only warnings
curl -s http://127.0.0.1:8765/status                # captures before
# 2. Tomi: one bounded capture of a public-safe page.
curl -s http://127.0.0.1:8765/status                # captures after: exactly +1 expected
# 3. Agent: read the new record back from the configured store, check id, timestamps, provenance,
#    and that a second sync creates no duplicate.
```

A sync (`scripts/run_ai26_localhost_sync.sh`) is only meaningful once the env points at the
centralized store; with the current local-only profile it has nothing to mirror, which is why
`/status` reports `distributed: disabled`.
