# Brazil26 consolidation and Allas archive (#373)

Every Brazil26 video collected on any host, merged into one deduplicated dataset in CSC Allas, with a
canonical CSV that names each object. The corpus is **not** re-scraped here: this is consolidation of what
already exists.

## What the corpus is on this host (Laskin, 2026-10-28)

| source | path | contents |
|---|---|---|
| **live capture root** | `/home/tomi/laclaugpt-brasil-data` | 31 GB — `media/` (6,966 files), `media/tiktok_pyktok/`, `normalized/*.jsonl`, `manifests/`, `state.sqlite3` |
| collection metadata (×3, identical) | `…/KEEP_PRIVATE/collection-data/brazil26` | 477 MB each — `raw/` (9,065 NDJSON), `normalized/`, `manifests/`, `state.sqlite3` |
| config only | `…/LaclauGPT-Private/collection/brazil26` | 24 KB — no data |

The three `KEEP_PRIVATE` copies are byte-for-byte the same metadata tree; only one needs archiving, and the
duplication is recorded here rather than silently resolved by deleting a copy.

`state.sqlite3` is the inventory backbone — `media_index` already carries `sha256`, `byte_size`,
`mime_type`, `local_path` and `downloaded_at` for **7,023** media rows, and `normalized/*.jsonl` carries
the post metadata (`author`, `timestamp`, `source_url`, `text`, `hashtags`, `engagement`).

## Identity and deduplication

Two keys, doing two different jobs:

- **Logical video** — `(platform, document_id)`, written as `instagram:DdCjLTFMSxm`. One canonical row per
  logical video; several media files (carousel images, video + thumbnail) hang off it.
- **Byte identity** — **SHA-256**. The Allas object key *is* the hash:
  `brazil26/videos/<sha256>.<ext>`.

Because the key is the hash, the two requirements that usually conflict cannot:

- identical bytes collected on two machines occupy **one** object — there is nothing else they could map to;
- two different files can never collide, even if they share a filename or a size;
- distinct versions stay traceable, because each keeps its own key and its own manifest row.

**Measured on this host:** 7,023 media files → **5,846 distinct objects**, 28.75 GB of unique bytes out of
31.56 GB total. 1,177 files are byte-identical duplicates within the corpus.

## Layout in Allas

```
brazil26/videos/<sha256>.<ext>          one object per distinct byte sequence
brazil26/metadata/brazil26_canonical.csv  one row per logical video
brazil26/manifests/brazil26_files.csv     one row per media file, linked by canonical_id
brazil26/manifests/inventory.json         counts, bytes, anomalies
```

Bucket: `LaclauGPT-AI26` (from `LACLAUGPT_S3_BUCKET`), endpoint `https://a3s.fi`.

`brazil26_canonical.csv` columns: `canonical_id, dataset, platform, document_id, url, author,
post_timestamp, collected_at, text, hashtags, media_count, media_status, media_sha256, media_bytes,
object_key, source_local_path`. One row per video is what downstream analysis reads; anything CSV cannot
carry losslessly stays in `normalized/*.jsonl` and is referenced by `document_id`.

## Running it

```bash
# 1. inventory — reads the state DB, writes the CSV pair and inventory.json
python scripts/brazil26_consolidate.py inventory \
    --state-db /home/tomi/laclaugpt-brasil-data/state.sqlite3 \
    --data-root /home/tomi/laclaugpt-brasil-data \
    --out out/brazil26            # add --verify to recompute every SHA-256

# 2. upload — idempotent, resumable, safe to interrupt
python scripts/brazil26_consolidate.py upload \
    --manifest out/brazil26/brazil26_files.csv --bucket "$LACLAUGPT_S3_BUCKET" \
    --workers 12 --dry-run        # drop --dry-run to write

# 3. validate — re-list the bucket and reconcile against the manifest
python scripts/brazil26_consolidate.py validate \
    --manifest out/brazil26/brazil26_files.csv --bucket "$LACLAUGPT_S3_BUCKET" \
    --out out/brazil26/validation.json
```

Credentials come from the normal boto3 chain (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` exported from
the project `.env`, or `~/.aws/credentials` written by `allas-conf`). Nothing is hard-coded, and no
credential or dataset is committed to the repository.

### Idempotency rules — why a rerun is safe

- An object is skipped only when it exists with **the same size *and* the same `sha256` metadata**.
  Size alone is not sufficient: two different files can share a size, and treating that as "already
  uploaded" would silently lose one of them.
- If an object exists with a *different* size, the upload **refuses** and reports it, unless `--overwrite`
  is given. Nothing is overwritten by default.
- Interrupting the run loses nothing: every object is independent, and the next run recomputes the todo
  set from the bucket's own state.

### On the other collection hosts

The same three commands run anywhere the collector wrote data; only `--state-db` and `--data-root` change.
Because object keys are content hashes, two hosts archiving the same file converge on one object without
coordination — the second upload is a skip, not a duplicate.

## Safety

- **Original local files are never deleted or moved.** The tool only reads them.
- No overwrite without `--overwrite`.
- The manifest records `status` per file (`ok`, `missing_local`, `hash_mismatch`, `size_mismatch`), so an
  incomplete source is visible rather than averaged into a percentage.

## What this does not do

- It does not verify that a downloaded file is the *content* the platform served — that is a collection
  question, not a consolidation one.
- It does not re-hash every file by default (`--verify` does, and takes as long as reading 31 GB).
- It does not archive the 477 MB metadata tree to Allas; only media and the two CSVs. The `raw/` NDJSON is
  the collection log and can be added as `brazil26/metadata/raw/` if wanted.
- It does not resolve the three duplicate `KEEP_PRIVATE` copies — recorded, not deleted, because deciding
  which copy is authoritative is the author's call.
