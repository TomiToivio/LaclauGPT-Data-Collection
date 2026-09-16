# Collection → Analysis handoff

Data Collection exposes a stable, storage-neutral handoff envelope so Data Analysis can poll local files/SQLite or shared MongoDB without rebuilding Collection semantics.

## Handoff identity

Each source has:

- `collection_id` and optional `arena`
- canonical `source_url`
- deterministic `revision` derived from analysis-relevant source/content inputs
- deterministic `handoff_key = hash(collection_id + source_url + revision)`
- `status`: `ready`, `waiting_media`, or `excluded`
- `reason`
- source publication timestamp and scheduling priority

Repeated polling returns the same handoff key until source-derived inputs change. Analysis should use `handoff_key` as its idempotency/claim key. A changed source revision produces a new key and is eligible for re-analysis.

## Local / same-machine cron

The local exporter reads canonical JSONL and downloader state from `state.sqlite3`:

```bash
laclaugpt-handoff \
  --data-root ./data/browser \
  --project-id ai26 \
  --collection-id ai26 \
  --limit 100
```

It emits one JSON object per ready record to stdout. Diagnostic mode includes waiting/excluded records:

```bash
laclaugpt-handoff --data-root ./data/browser --project-id ai26 --include-not-ready
```

A simple polling deployment can run Collection/media jobs and then let Data Analysis consume this command periodically. Re-running it is safe because the handoff key is stable.

## Distributed mode

When Collection writes through the distributed sink, MongoDB records contain queryable routing fields plus the same `handoff` envelope. Ready records also emit a lightweight Redis event on:

```text
laclaugpt:<project_id>:stream:analysis-ready
```

The Redis event contains identity/revision references only, not the source payload. MongoDB remains durable state and S3/CSC Allas remains the raw/large-object store.

An Analysis worker can poll MongoDB directly, which remains valid even when Redis is disabled or an event was missed:

```javascript
{
  project_id: "ai26",
  collection_id: "ai26",
  "handoff.status": "ready"
}
```

The MongoDB index orders efficient readiness queries by handoff status, source priority, newest publication time, and canonical source URL. For AI26, the Collection handoff applies the public scheduling contract: source publication date must be on/after 2026-09-01, richer sources outrank X, and newest content is processed first within a tier.

## Media readiness

A record with media references stays `waiting_media` until the downloader has durable completed state (or the canonical reference already contains a local/object reference or checksum). The local handoff exporter reads the existing media index, so no second queue database is required.

In distributed mode, run the bounded media worker after collection/sync:

```bash
laclaugpt-distributed-media \
  --study-config "$LACLAUGPT_PRIVATE_CONFIG_DIR/ai26.yaml" \
  --data-root ./data/browser-ai26 \
  --workers 4 \
  --limit 25
```

The worker:

1. uses the existing source-agnostic media queue and retry state;
2. writes completed files to the configured S3/CSC Allas project namespace;
3. adds `object_ref`, checksum and download metadata to the canonical media reference;
4. re-upserts the affected record to MongoDB;
5. recalculates its handoff state; and
6. emits `analysis-ready` only when the record has become ready.

All operations are bounded and use deterministic media/object identities, so the smoke test does not require a full-corpus media run.

## First distributed smoke path

A small AI26 sample can now exercise both text-only and multimodal records:

```text
Firefox localhost capture
  → distributed-sync
  → MongoDB + raw Allas + Redis collected reference
  → distributed-media (only when media is pending)
  → MongoDB handoff.status=ready
  → Redis analysis-ready reference
  → Data Analysis worker / cron
```

This contract corresponds to the Analysis-side distributed worker work in `TomiToivio/LaclauGPT-Data-Analysis#15`. Private source lists, credentials and unpublished corpus material remain runtime-only.
