# Phase 1 arXiv and document collection

Issue #110 reactivates scholarly/document acquisition as an isolated Phase 1 source family. Collection remains descriptive: it captures source text, bibliographic/source metadata, provenance and durable references, then hands the canonical record to Data Analysis without analytical interpretation.

## arXiv

- Identity is the canonical `https://arxiv.org/abs/<id>` URL; the arXiv ID is retained as `source_native_ids.document_id`.
- The normalized text is title plus abstract/summary. The title is also mapped to `content.title`.
- A deterministic JSON-safe bibliographic snapshot is preserved in `raw_capture.payload`.
- The PDF URL is a `MediaReference`; Collection does not download or interpret the PDF automatically.
- `download_required=true` marks that downstream media/document acquisition may materialize the PDF when the study enables it.
- Batch pagination uses a non-negative integer offset carried through `CollectionContext.cursor`. A full page returns the next offset.
- Duplicate arXiv records in one batch are suppressed by canonical `source_url`; durable cross-run idempotency remains enforced by `CollectionRunner`/the configured `RecordStore`.
- Missing optional dependencies fail with an explicit install message; invalid cursors fail before collection.

## Local documents

- Local text/PDF imports use SHA-256 content identity: `file+sha256:<digest>`.
- The same content-addressed reference is stored as the raw/local reference and the checksum is retained.
- Absolute machine paths are deliberately not persisted in canonical records.
- Source filename, title, MIME-like content type and extraction metadata remain descriptive source metadata.
- PDFs use PyMuPDF first with pypdf fallback; a failure of both extractors raises an explicit error.
- Text files are read as UTF-8.
- Document chunking remains a helper only. Collection does not run embeddings, discourse coding, OCR/vision interpretation, topic modelling or other analytical processing here.

## Analysis handoff

Both source types emit the normal `CanonicalRecord`. The existing handoff contract therefore applies unchanged: Analysis receives stable source identity, normalized text, source metadata, raw/reference provenance and media/file references. An arXiv record with an unmaterialized PDF may report `waiting_media` when the handoff policy requires referenced media to be durable; text-only local documents are immediately source-ready.

Synthetic coverage lives in:

- `tests/fixtures/phase1_arxiv_document.json`
- `tests/test_issue_110_arxiv_documents.py`
