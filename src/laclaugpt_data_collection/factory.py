"""Construct configured local or distributed storage backends."""
from __future__ import annotations

import logging

from .config import Settings
from .storage.base import ObjectStore, RecordStore
from .storage.csv import CSVRecordStore
from .storage.local import FilesystemObjectStore, SQLiteRecordStore

logger = logging.getLogger(__name__)


def _build_mongodb_store(settings: Settings) -> RecordStore:
    if not settings.mongodb_uri:
        raise RuntimeError(
            "MongoDB storage requires LACLAUGPT_MONGODB_URI (or mongodb_uri in private config)"
        )
    from .storage.remote import MongoRecordStore

    store = MongoRecordStore(
        settings.mongodb_uri,
        settings.mongodb_database,
        collection=settings.effective_mongodb_collection,
        project_id=settings.project_id,
        connect_timeout_ms=settings.mongodb_connect_timeout_ms,
        graph_max_depth=settings.mongodb_graph_max_depth,
    )
    store.ping()
    return store


def build_record_store(settings: Settings) -> RecordStore:
    """Build the selected store without ever inventing a remote destination.

    ``auto`` only attempts MongoDB when a URI is explicitly configured. If the
    configured MongoDB cannot be reached, auto degrades to CSV. Explicit
    ``mongodb`` is strict and surfaces the connection/import error.
    """
    if settings.record_backend == "csv":
        return CSVRecordStore(settings.csv_path)
    if settings.record_backend == "sqlite":
        return SQLiteRecordStore(settings.sqlite_path)
    if settings.record_backend == "mongodb":
        return _build_mongodb_store(settings)
    if settings.record_backend == "auto":
        if settings.mongodb_uri:
            try:
                return _build_mongodb_store(settings)
            except Exception as exc:  # optional enhancement must degrade safely
                logger.warning("MongoDB unavailable in auto mode; falling back to CSV: %s", exc)
        return CSVRecordStore(settings.csv_path)
    raise ValueError(f"Unsupported record backend: {settings.record_backend}")


def build_object_store(settings: Settings) -> ObjectStore:
    if settings.object_backend == "filesystem":
        return FilesystemObjectStore(settings.data_root / "objects")
    if settings.object_backend == "s3":
        from .storage.remote import S3ObjectStore

        if not settings.s3_bucket:
            raise ValueError("S3 backend requires LACLAUGPT_S3_BUCKET")
        prefix = f"{settings.s3_prefix_root}/{settings.project_id}"
        return S3ObjectStore(
            bucket=settings.s3_bucket,
            endpoint_url=settings.effective_s3_endpoint,
            region_name=settings.s3_region,
            access_key_id=settings.effective_s3_access_key,
            secret_access_key=settings.effective_s3_secret_key,
            prefix=prefix,
        )
    raise ValueError(f"Unsupported object backend: {settings.object_backend}")
