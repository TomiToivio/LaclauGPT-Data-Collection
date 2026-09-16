# Distributed project storage

This module implements the shared LaclauGPT multi-project namespace defined by `schemas/distributed-project.schema.json` and the parent repository's `docs/DISTRIBUTED_PROJECT_STORAGE.md`.

Set `LACLAUGPT_PROJECT_ID` to a stable lower-case project identifier such as `ai26`, `ep24`, `brazil26` or `hungary26`. `Settings.distributed_namespace` then derives the same names used by Analysis and Visualization.

## Redis control plane

Redis distributes small versioned control documents and workflow coordination, not large research objects. Collection workers may read:

- `laclaugpt:<project>:manifest:current`;
- `laclaugpt:<project>:settings:collection:current`;
- `laclaugpt:<project>:codebook:<name>:current` when collection-time vocabularies are explicitly required;
- project-specific collection streams, worker state and locks.

Immutable revisions use the same key with the revision replacing `current`. Every control document uses the common envelope with project ID, schema version, revision, SHA-256 and payload. Secrets, cookies, tokens and browser profiles never belong in these payloads.

Collection publishes references and stable identity to downstream streams. Queue messages should include `project_id`, `source_url`, `run_id`, schema version and a MongoDB/S3 reference where applicable, rather than embedding large media or raw captures.

## MongoDB record plane

The default shared database is `laclaugpt`, with project-prefixed collections such as:

```text
ai26__records
ai26__runs
ai26__artifacts
brazil26__records
```

Collection writes source-side canonical records to `<project>__records`. `source_url` remains the canonical unique identity. Persisted records should carry `project_id` as an additional routing guard.

## S3 / CSC Allas object plane

A single bucket can serve every project. Collection object keys begin with:

```text
projects/<project>/raw/
projects/<project>/canonical/
projects/<project>/media/
projects/<project>/manifests/
projects/<project>/runs/
```

The same layout works with CSC Allas or another S3-compatible provider. Bucket credentials and endpoint configuration remain private environment/deployment settings.

### CSC Allas client configuration

Allas is not fully S3-compatible in two ways that break uploads with the boto3
defaults, while leaving reads working:

| Symptom | Cause | Correct setting |
|---|---|---|
| `MissingContentLength` (HTTP 411) on PUT | Allas rejects signature version 4 uploads | `LACLAUGPT_S3_SIGNATURE_VERSION=s3` |
| `QuotaExceeded` (HTTP 403) on PUT, even with an empty bucket | Allas rejects path-style addressing uploads | `LACLAUGPT_S3_ADDRESSING_STYLE=auto` |

Both are the defaults, so an Allas deployment needs no extra configuration.
`list`/`head`/`get` succeed with signature v4 and either addressing style, so a
misconfigured client still appears healthy until the first object is written.
Set `s3v4`/`path` only for real AWS S3 or another provider that has retired
SigV2. `laclaugpt-collect doctor` prints the effective values.

## Isolation rule

A worker configured for one `project_id` must reject messages or records labelled with another project. Never derive project routing from source platform, filename or a human-readable study title.
