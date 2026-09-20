"""Local document/PDF ingestion helpers.

This keeps extraction separate from persistence and analysis. No vector database,
MongoDB or project policy is imported here.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from ..models import CollectionProvenance, NormalizedRecord


def chunk_text(text: str, *, chunk_size: int = 4000, overlap: int = 500) -> list[str]:
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Require chunk_size > 0 and 0 <= overlap < chunk_size")
    if len(text) <= chunk_size:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        if end < len(text):
            boundary = max(text.rfind(". ", start, end), text.rfind("\n", start, end))
            if boundary > start + chunk_size // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def _extract_pdf(path: Path) -> tuple[str, dict[str, Any]]:
    errors: list[str] = []
    try:
        import fitz
        doc = fitz.open(path)
        text = "\n".join(page.get_text() for page in doc)
        metadata = dict(doc.metadata or {})
        metadata["pages"] = len(doc)
        doc.close()
        return text, metadata
    except Exception as exc:
        errors.append(f"pymupdf:{exc.__class__.__name__}")
    try:
        import pypdf
        with path.open("rb") as handle:
            reader = pypdf.PdfReader(handle)
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
            metadata = {str(k): str(v) for k, v in dict(reader.metadata or {}).items()}
            metadata["pages"] = len(reader.pages)
            return text, metadata
    except Exception as exc:
        errors.append(f"pypdf:{exc.__class__.__name__}")
    raise RuntimeError("No working PDF extractor: " + ", ".join(errors))


def extract_document(path: str | Path) -> NormalizedRecord:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    checksum = hashlib.sha256(file_path.read_bytes()).hexdigest()
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        text, metadata = _extract_pdf(file_path)
        transformations = ["pdf-extract"]
    else:
        text = file_path.read_text(encoding="utf-8")
        metadata = {}
        transformations = ["utf8-text-read"]
    title = str(metadata.get("title") or metadata.get("/Title") or file_path.name)
    author = str(metadata.get("author") or metadata.get("/Author") or "")
    media_type = "application/pdf" if suffix == ".pdf" else "text/plain"
    record = NormalizedRecord(
        document_id=checksum,
        platform="document",
        author=author,
        source_url=f"file+sha256:{checksum}",
        text=text,
        raw_ref=f"file+sha256:{checksum}",
        raw_checksum=checksum,
        raw_content_type=media_type,
        collection_provenance=CollectionProvenance(
            module="local-document",
            transformations=transformations,
            metadata={
                "filename": file_path.name,
                "title": title,
                "sha256": checksum,
                "raw_reference_policy": "content-addressed-local-reference; absolute paths are not persisted",
                **metadata,
            },
        ),
    )
    record.content.title = title or None
    record.content.file_references = [
        {
            "kind": "local-document",
            "ref": f"file+sha256:{checksum}",
            "filename": file_path.name,
            "checksum": checksum,
            "content_type": media_type,
        }
    ]
    return record


def infer_abstract(text: str) -> str:
    match = re.search(r"(?is)\babstract\b\s*[:\-]?\s*(.+?)(?:\n\s*\n|\n\s*(?:keywords?|introduction)\b)", text)
    return " ".join(match.group(1).split())[:2000] if match else ""
