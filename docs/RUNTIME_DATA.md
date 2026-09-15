# Runtime data layout

All runtime and study-specific material belongs under the repository-local `data/` directory. The whole `data/` tree is ignored by Git and must stay untracked.

Standard layout:

```text
data/
  logs/
  database/
  config/
  files/
  csv/
  jsonl/
  codebooks/
  sources/
  downloads/
  media/
  models/
    ollama/
    whisper/
  cache/
  tmp/
  exports/
  artifacts/
  runs/
  browser/
  transcripts/
  frames/
```

Do not create new top-level runtime directories such as `logs/`, `database/`, `csv/`, `downloads/`, `outputs/`, or model caches. Runtime paths must be derived from `Settings.data_root`. `Settings.ensure_local_directories()` creates the standard tree.

When Collection and Analysis run on the same machine, Analysis may read Collection output directly from this repository's `data/` tree through an explicitly configured filesystem path. No dataset needs to be copied into Git for module interoperability.

For distributed operation, use the configured MongoDB record store, Redis coordination/cache, and S3-compatible object storage such as CSC Allas. CSV/JSONL file transfer remains the manual interoperability fallback.
