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

When Collection writes through the distributed sink, MongoDB records contain queryable routing fields plus the same `handoff` envelope. Text-only/otherwise-ready records also emit a lightweight Redis event on:

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

Distributed records with media remain `waiting_media` until a distributed media worker persists the object/reference and refreshes the canonical MongoDB record. Text-only records can already flow end-to-end in the first distributed smoke test.

## First distributed smoke path

For the first test, use a small text-only AI26 sample:

```text
Firefox localhost capture
  → distributed-sync
  → MongoDB canonical record + handoff.status=ready
  → Redis analysis-ready reference
  → Data Analysis worker / cron
```

This contract corresponds to the Analysis-side distributed worker work in `TomiToivio/LaclauGPT-Data-Analysis#15`. Private source lists, credentials and unpublished corpus material remain runtime-only.
