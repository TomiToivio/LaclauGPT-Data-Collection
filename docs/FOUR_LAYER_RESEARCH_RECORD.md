# Four-layer research record in Data Collection

Collection is the preservation boundary for LaclauGPT research data.

Every new record uses schema `1.1.0` and carries `raw_capture`, `source`, `content`, `intermediate`, `analysis`, `human_readable`, provenance/review state and `legacy` compatibility data.

## Collection invariants

1. Preserve what the source returned. Browser/API collectors retain the exact parsed source item inline when practical and an immutable full-response `raw_ref` when available. RSS/API/web-scraper adapters should pass the original item to `raw_payload`; large/binary sources should retain a durable raw reference instead.
2. Normalization is additive. `source` and `content` make source material usable but never replace `raw_capture`.
3. Collection initializes the intermediate and analysis layers rather than inventing analysis results.
4. Collection generates a deterministic human-readable collection-stage summary so a researcher can inspect a record before Analysis runs.
5. CSV exports contain both nested canonical JSON sections and stable wide research columns. Analysis fields such as `whisper_transcript`, `ocr_1`, `frame_1` and `summary_analysis` are present but empty until downstream processing fills them.
6. MongoDB/JSONL persist the complete four-layer document. S3/Allas may hold large raw/media material referenced by the record. Redis remains coordination/control infrastructure rather than the sole research-data store.

Legacy 1.0 records are migrated explicitly. If the original source payload is unavailable, migration marks that limitation in `raw_capture.metadata` instead of pretending a normalized reconstruction is the original response.
