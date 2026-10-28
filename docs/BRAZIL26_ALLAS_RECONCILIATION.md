# Brazil26 deduplicated archive: offline handoff for issue #373

This narrowly scoped utility is **not a collector** and does not access localhost, CSC Allas, MongoDB, credentials, or private machines. The Brazil26-specific request in #373 is an explicit exception to the repository's AI26-default instruction; no live Brazil26 collection behavior is changed.

## Per-machine preparation

On each source host, export available Brazil26 metadata to UTF-8 CSV. Required columns: `platform`, `post_id` (or `video_id`). Optional columns: `media_path`, `source_url`, `creator`, `post_timestamp`, `collection_timestamp`, `download_timestamp`, `caption`, `metadata_id`. Put media files under the CSV's directory and use *relative* media paths. Absolute paths and paths escaping this directory are intentionally rejected. Keep private source locations and raw data outside public GitHub.

Copy or securely stage the CSV and referenced files from each source on one protected analysis machine. This tool does not discover hostnames or stage files automatically.

```bash
python scripts/brazil26_reconcile_offline.py \
  --source laptop=/private/brazil26/laptop/metadata.csv \
  --source wsl=/private/brazil26/wsl/metadata.csv \
  --source laskin=/private/brazil26/laskin/metadata.csv \
  --output /private/brazil26/reconciliation
pytest -q tests/test_issue_373_brazil26_reconciliation.py
```

Output is deterministic for identical inputs. Re-running overwrites **derived reports only**, not original videos or input CSVs. `canonical_metadata.csv` has one row per `(platform, post_id)`; `media_manifest.csv` retains different hashes under the same ID. Identical SHA-256 bytes map to one proposed content-addressed object key, even across IDs/hosts, and `source_provenance.csv` keeps every input record in JSON for lossless auditing. `conflicts.json` preserves conflicting values and `exceptions.json` lists incomplete identities or missing/outside media. Only metadata fields represented in the input CSV can be recovered; platform-specific extras are preserved in the raw JSON provenance column.

**Do not treat these manifests as successful uploads.** The object keys are *proposals*. Status is `pending_upload`, and report flags `allas_checked=false`, `upload_verified=false`. This is a local dry-run/reconciliation facility, **not an Allas sync client**, and no `--resume` upload capability is claimed.

## Allas phase: blocked until access

1. Enumerate all source hosts, video directories, local databases and existing Allas keys (including any previously uploaded files) and record inaccessible machines.
2. Audit conflicts and aliases (platform post IDs, actual reposts, unknown/missing IDs); inspect variants before any upload. Count canonical records, file hashes and bytes per host. Existing Allas keys must be reconciled first.
3. Implement/use a project-approved CSC S3 adapter with credentials supplied through environment configuration; for each proposed content-addressed key, HEAD and verify size + stored SHA256 metadata. If the key exists with a different checksum, **refuse overwrite**. Never equate S3 ETag with SHA256. Upload only absent keys with verifiable content metadata and verify by streaming a read-back or audited sample. Record successful uploads in a durable resume ledger and re-list keys.
4. Upload the canonical CSV, media manifest, provenance, conflict and report files only after media integrity checks, with restricted project access. Update media statuses and file references only after verification.
5. Reconcile Allas inventory and every host manifest (including source counts and bytes); publish a final audit with explicit unverified gaps. Keep originals intact until manually authorized otherwise.

**Privacy:** the outputs may contain sensitive account identifiers, research text and private filesystem paths. Do not commit generated manifests to public repositories.
