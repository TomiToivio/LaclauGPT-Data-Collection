# Cross-machine ingestion identity for AI26 X records (#478)

Three localhost collectors are meant to feed one `ai26__records` from the same Laskin-side analysis and
dashboard. Before that is true in production, the store's uniqueness has to be the *post*, not the string a
browser happened to hold. This document records what that means, what was measured in the shared store, and
what still needs a host.

## The identity rule

`models.source_identity()` derives the key the store writes and queries on:

- the X/Twitter host family (`x.com`, `www/mobile/m.x.com`, `twitter.com`, `www/mobile/m.twitter.com`) folds to
  `x.com`;
- a post's identity is its numeric status id: `x.com/<user>/status/<id>`, `twitter.com/<USER>/status/<id>/photo/1`
  and `x.com/i/web/status/<id>` all become `https://x.com/i/status/<id>`;
- X share parameters (`s=`, `t=`, `ref_src=`, `ref_url=`, `src=`) carry no identity and are dropped;
- every other host is left to `canonicalize_source_url()` — tracking parameters and a trailing slash only.
  Rewriting a news site's host would change what the source *is*, not how it is spelled, and `t=` on a YouTube
  link is a timestamp.

`canonicalize_source_url()` keeps its previous, conservative meaning: it is the URL a *record shows* and the
URL a researcher can open. Identity is a separate, derived field (`source_identity`), stored next to it.

## What the store now does

| Concern | Behaviour |
| --- | --- |
| Uniqueness | Partial unique index on `(project_id, collection_id, source_identity)`; partial so documents written before the field existed keep loading. |
| Single write | Looks up by identity; if absent, falls back to the raw URL and then to the post id, so a document written under an older spelling is **adopted**, not duplicated. |
| Bulk write | Adopts legacy documents for the batch first, then upserts by identity. |
| Reads | `contains()` and `graph_lookup()` also resolve by identity; the graph join still uses `source_url`, because relationships reference the URL a record shows. |
| Evidence | The captured `source_url` is never rewritten. Only the derived routing key is added. |

## Measured in the shared store (read-only, 2026-11-26)

Against `ai26__records` (12,582 documents) with the identity rule above:

```
$ python -m laclaugpt_data_collection.x_ingest_identity --mongodb-uri "$LACLAUGPT_MONGODB_URI" \
    --database "$LACLAUGPT_MONGODB_DATABASE"
documents 12582 · distinct identities 12578
duplicate identities 4 (4 extra document(s)) · without identity 12582
variants: {'has_query': 577, 'scheme_is_http': 3}
```

Four duplicate identities, four extra documents, all on `x.com` URLs:

- **three** are an X post stored twice: one `platform=x` record under `x.com/<user>/status/<id>`, plus one
  `platform=web` record of the *same post* whose URL carried a share parameter (`?s=20`, `?ref_src=…`);
- **one** is a `web`/`web` pair of the same URL with differing query strings.

The URL-keyed unique index could not see either shape as one document, so the corpus already holds four
duplicated posts — in a store with a single writer. That is the failure mode #478 predicts for three
localhost writers, already present. Counts move as the live feed advances; re-run the audit rather than
quoting this figure.

All 12,582 documents predate the identity field, so `source_identity` is absent everywhere; the first write
of an existing URL adopts its document, and the backfill stamps the rest:

```bash
python -m laclaugpt_data_collection.x_ingest_identity \
  --mongodb-uri "$LACLAUGPT_MONGODB_URI" --database "$LACLAUGPT_MONGODB_DATABASE" --json
python -m laclaugpt_data_collection.x_ingest_identity \
  --mongodb-uri "$LACLAUGPT_MONGODB_URI" --database "$LACLAUGPT_MONGODB_DATABASE" --backfill
```

The audit prints counts only — hosts, variant flags and duplicate counts. It never prints a URL or record
content, so its output is safe to paste into an issue. `--backfill` is a dry run unless you pass it; run the
audit first, then backfill once, then re-run the audit to confirm zero.

## What is verified, and what is not

Verified here (no hosts involved): the canonicalisation cases, the identity key on writes and reads, adoption
of a legacy document instead of a duplicate, the partial unique index, and the audit/backfill behaviour —
16 tests in `tests/test_issue_478_ingest_identity.py` over a fake collection that behaves like Mongo for the
operations the store uses.

**Not verified:** that any localhost collector reaches the shared database. That needs the browser, the
loopback capture service and the per-host environment on Tomi's machines; see
`AI26_ISSUE_433_LOCAL_HANDOFF.md` for the split of operator versus agent work. Until a real post from each
host appears in `ai26__records` with correct provenance, the end-to-end acceptance of #478 stays open.

## Local-only fallback must stay visible

A collector with no MongoDB URI degrades to CSV and reports it (`distributed: {enabled: false}`). That is not
central ingestion, and the daily status must keep saying so: a local CSV that no one ships is a collection
gap, not a corpus.
