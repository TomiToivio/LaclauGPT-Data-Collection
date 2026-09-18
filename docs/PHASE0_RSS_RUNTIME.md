# Phase 0 RSS-only collection runtime

Phase 0 collects **RSS/Atom feeds only** and writes plain text records directly to
MongoDB, so the complete Phase 0 path
(collection → analysis → validation → visualization) can work reliably on the
simplest possible input.

```text
RSS/Atom feeds
    ↓
plain text records
    ↓
MongoDB  (laclaugpt2_<project>_scraper_collection)
    ↓
LaclauGPT Phase 0 analysis
```

## What Phase 0 does

The active Phase 0 collector is `laclaugpt-server-rss`
(or `python -m laclaugpt_data_collection.server_runner`). For each feed item it:

1. reads configured `[[feed]]` rows from the source manifest;
2. fetches the feed item;
3. preserves the canonical article URL;
4. fetches full article text where practical (falling back to the feed summary);
5. preserves feed/source metadata (`source_name`, `arena`, `actor_name`, ...);
6. preserves item metadata (title, date, author/byline, categories/tags);
7. deduplicates by canonical URL;
8. upserts the record into the shared MongoDB corpus;
9. is safe to run repeatedly from cron.

## CLI

```bash
LACLAUGPT_PROJECT_ID=ai26 \
LACLAUGPT_MONGODB_URI='mongodb://HOST:PORT/' \
laclaugpt-server-rss \
  --source-manifest data/config/ai26.sources.toml \
  --max-feeds 8 \
  --per-feed-limit 5 \
  --limit 40
```

Flags: `--source-manifest` (required), `--collection-id`, `--worker-id`,
`--max-feeds`, `--per-feed-limit`, `--limit`, `--json`.

Exit code is non-zero when collection fails, so cron surfaces the fault.

## Cron

Each invocation is one bounded cycle — nothing here starts a perpetual scheduler:

```cron
10 * * * * /bin/bash /mnt/workspace/LaclauGPT-Data-Collection/scripts/run_ai26_laskin_collect.sh >> /mnt/workspace/LaclauGPT-Data-Collection/data/logs/ai26-laskin-collect.log 2>&1
```

`scripts/run_ai26_laskin_collect.sh` is the bounded one-cycle wrapper. It resolves
the console script inside the checkout's venv and loads its own environment, so cron
needs no inherited environment.

## MongoDB boundary

Phase 0 collection and the Phase 0 analysis core share **one** database and **one**
collection name, derived from the project id:

```text
laclaugpt2_<project>_scraper_collection      # e.g. laclaugpt2_ai26_scraper_collection
```

Documents are **flat**, not the nested canonical record. Records are upserted on a
stable identity (canonical `source_url`, fragments and tracking parameters stripped),
so re-collecting an article updates it in place instead of duplicating it. See
`docs/CANONICAL_RECORD_CONTRACT.md` for the field list.

## Phase 0 versus Phase 1

Phase 1 collection code remains in the repository but is **not part of the active
Phase 0 runtime**. Disabled from this path:

- X/Twitter, TikTok, Instagram, YouTube and Telegram collectors;
- browser-assisted capture (Firefox, Zeeschuimer/4CAT);
- multimodal media download, image/video/audio handling, OCR and Whisper support;
- Redis queues and CSC Allas media storage;
- distributed and agent-based orchestration.

The Phase 0 path requires **MongoDB only**. It opens no Redis connection and no
S3/Allas connection, and there are no hidden fallbacks into Phase 1 services.

Phase 1 code was not deleted to achieve this. It stays available as a reference
implementation and is restored **one functionality at a time**, only after Phase 0
works end to end. For each restored feature: add one adapter, verify collection
independently, verify the MongoDB records, verify compatibility with Phase 0
analysis, and only then add the next feature. Do not restore multiple platform
collectors at once.

## Related

- `docs/AI26_PHASE1_HANDOFF.md` — the Phase 1 Collection → Analysis handoff contract.
- `docs/CANONICAL_RECORD_CONTRACT.md` — the canonical record and Phase 0 boundary fields.
- `README.md` — repository overview.
