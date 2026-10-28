# Brazil26 consolidation

One dataset out of many collection hosts. The tool is `scripts/brazil26/consolidate.py`;
it is a **consolidator, not a collector** — it reads what a host already has, and never
deletes, moves or rewrites media.

## Why identity needs two keys

| question | key |
| --- | --- |
| *which media item is this?* | `(platform, document_id, media_index)` |
| *is this the same file?* | SHA-256 of the bytes |

A consolidation that uses only the first key duplicates storage when the same image is
used in several posts. One that uses only the second loses the post it belongs to.
Both are needed: identical bytes collapse to one object, and a logical item that has two
genuinely different files keeps both, flagged for review rather than silently resolved.

## Usage

```bash
python scripts/brazil26/consolidate.py run \
    --root "$BRAZIL26_ROOT" \
    --out-dir "$BRAZIL26_CONSOLIDATION_OUT" \
    --workers 12
```

This writes, to the output directory (never into this repository):

- `inventory.json` — what the host holds, index vs disk
- `manifest.json` — one row per physical file, with a recomputed SHA-256
- `dedupe.json` — duplicate groups, logical variants, index disagreements
- `brazil26_canonical.csv` — one row per logical item, joined to post metadata
- `brazil26_files.csv` — one row per physical file, linked by content hash
- `AUDIT.md` — the human-readable reconciliation report

Then, with CSC credentials in the environment:

```bash
# stage one symlink per distinct hash, so each byte-identical file uploads once
python scripts/brazil26/consolidate.py upload \
    --manifest "$OUT/manifest.json" --staging "$BRAZIL26_ROOT/_staging" \
    --dest allas:brazil26/media --dry-run     # remove --dry-run to upload

python scripts/brazil26/consolidate.py verify \
    --manifest "$OUT/manifest.json" --dest allas:brazil26/media
```

Objects are content-addressed: `media/<sha256[:2]>/<sha256><ext>`. Identical bytes
therefore occupy one object no matter how many hosts or posts reference them, and the
upload is idempotent — `rclone --checksum --immutable` skips what is already there, so
re-running after an interruption neither duplicates nor overwrites.

## Matching the index to the files

The index does not always record a resolvable path: some rows store a bare filename
while the file lives in a per-collector subdirectory. The tool falls back to matching on
basename, **but only when the match is unambiguous**, and records how each row was
matched in `path_match` (`exact`, `basename`, `none`). An ambiguous filename is never
guessed between — that would attach the wrong post metadata to a file, which is worse
than leaving it unmatched.

## What must not go into this repository

Media, manifests, canonical CSVs and any post-level research data stay in private
storage. This document and the script are code and procedure only.
