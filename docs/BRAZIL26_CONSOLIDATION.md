# Brazil26 consolidation and Allas archive (#373)

Every Brazil26 media item collected on any host, merged into one deduplicated dataset in CSC
Allas, with a canonical CSV that names each object. The corpus is **not** re-scraped here: this
is consolidation of what already exists, and no source file is ever deleted, moved or rewritten.

## Three scripts, three jobs

There is more than one entry point because the stages have different inputs and different
failure modes. They are **not** interchangeable:

| script | input | does | network |
| --- | --- | --- | --- |
| `scripts/brazil26_reconcile_offline.py` (#375) | CSV descriptions of several hosts | reconciles hosts offline; preserves `conflict_fields`, `source_hosts`, variant counts | none |
| `scripts/brazil26_consolidate.py` | live collection root: `state.sqlite3` + `media/` | canonical CSV + file manifest, then uploads distinct files to Allas with SHA-256 object metadata and validates the bucket | S3 |
| `scripts/brazil26/consolidate.py` | live collection root | inventory, manifest, dedupe, canonical CSV; content-addressed staging; `rclone` transfer and verify | rclone/Swift |

The middle and the last overlap on inventory and dedupe. They differ in how they talk to Allas
(S3 metadata versus `rclone --checksum --immutable`) and in how they handle a rerun; unifying
them is a design decision, and the field sets are not yet aligned (`allas_object_key` versus a
computed object key, `conflict_fields` versus `variants`).

## Identity and deduplication

Two keys, doing two different jobs:

- **Logical item** — `(platform, document_id)`, e.g. `instagram:DdCjLTFMSxm`. One canonical row
  per logical item; several media files (carousel images, video plus thumbnail) hang off it.
- **Byte identity** — **SHA-256**. The Allas object key *is* the hash:
  `brazil26/videos/<sha256>.<ext>`.

Because the key is the hash, two requirements that usually fight cannot:

- identical bytes collected on two machines occupy **one** object — there is nothing else they
  could map to;
- two different files cannot collide, even if they share a filename or a size;
- distinct versions stay traceable, because each keeps its own key and its own manifest row.

## Measured on the first host

| | |
| --- | --- |
| index rows | 7,023 |
| files on disk | 7,021 |
| total bytes | 31.56 GB |
| distinct SHA-256 | 5,847 |
| byte-identical duplicates | 1,174 |
| unique bytes | 28.75 GB |

Two index rows duplicate each other and one file on disk has no index row, which is why the
row count and the file count differ. Counted over files, the corpus resolves to **5,847**
distinct objects; counted over index rows it reads 5,846. The file count is authoritative.

## The path trap

The index cannot locate **860 of its own files**: those rows store a bare filename
(`@account_video_….mp4`) while the file lives in a per-collector subdirectory such as
`media/tiktok_pyktok/`. Matching only on the recorded path produces hundreds of phantom
"missing" files and silently strips platform, author and text from the canonical CSV — it cost
**861 rows** of post metadata on the first run.

Both host-side scripts fall back to basename matching **only when the match is unambiguous**,
and record how each row was matched (`exact` / `basename` / `none`). An ambiguous filename is
never guessed between: attaching the wrong post to a file is worse than leaving it unmatched.

## Layout in Allas

```
brazil26/videos/<sha256>.<ext>             one object per distinct byte sequence
brazil26/metadata/brazil26_canonical.csv   one row per logical item
brazil26/manifests/brazil26_files.csv      one row per media file, linked by canonical id
brazil26/manifests/inventory.json          counts, bytes, anomalies
```

Bucket and endpoint come from the environment (`LACLAUGPT_S3_BUCKET`, `LACLAUGPT_S3_ENDPOINT`);
credentials are the researcher's and are never committed.

Canonical CSV columns: `canonical_id, dataset, platform, document_id, url, author,
post_timestamp, collected_at, text, hashtags, media_count, media_status, media_sha256,
media_bytes, object_key, source_local_path`. One row per logical item is what downstream
analysis reads; anything CSV cannot carry losslessly stays in `normalized/*.jsonl` and is
referenced by `document_id`.

## Running

```bash
# host inventory + manifest + canonical CSV
python scripts/brazil26_consolidate.py inventory \
    --state-db "$BRAZIL26_ROOT/state.sqlite3" --data-root "$BRAZIL26_ROOT" \
    --out "$OUT" --verify

# upload distinct objects, then reconcile the bucket against the manifest
python scripts/brazil26_consolidate.py upload --manifest "$OUT/files.csv" --dry-run
python scripts/brazil26_consolidate.py validate --manifest "$OUT/files.csv"

# the rclone route: stage one symlink per distinct hash, then copy and verify
python scripts/brazil26/consolidate.py upload \
    --manifest "$OUT/manifest.json" --staging "$BRAZIL26_ROOT/_staging" \
    --dest allas:brazil26/media --dry-run
```

## Safety

- **Original local files are never deleted or moved.** The tool only reads them.
- No overwrite without `--overwrite`.
- A rerun skips an object only when **both** size and SHA-256 agree; a differing object is refused
  rather than overwritten.
- `--dry-run` performs no network I/O.
- The manifest records `status` per file (`ok`, `missing_local`, `hash_mismatch`, `size_mismatch`), so an
  incomplete source is visible rather than averaged into a percentage.
- Media, manifests and canonical CSVs are research data: they stay in private storage and Allas,
  never in this repository.

## What this does not do

- It does not verify that a downloaded file is the *content* the platform served — that is a collection
  question, not a consolidation one.
- It does not re-hash every file by default (`--verify` does, and takes as long as reading the whole corpus).
- It does not archive the raw metadata tree to Allas; only media and the two CSVs. The `raw/` NDJSON is the
  collection log and can be added under `brazil26/metadata/raw/` if wanted.
- It does not resolve duplicate metadata copies between hosts — recorded, not deleted, because deciding
  which copy is authoritative is the author's call.
