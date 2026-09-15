"""Construct configured local or distributed storage backends."""
from __future__ import annotations

from .config import Settings
from .storage.base import ObjectStore, RecordStore
from .storage.local import FilesystemObjectStore, SQLiteRecordStore


def build_record_store(settings: Settings) -> RecordStore:
    if settings.record_backend == "sqlite":
        return SQLiteRecordStore(settings.sqlite_path)
    if settings.record_backend == "mongodb":
        from .storage.remote import MongoRecordStore

        collection = settings.distributed_namespace.mongo_collection("records")
        return MongoRecordStore(
            settings.mongodb_uri,
            settings.mongodb_database,
            collection=collection,
            project_id=settings.project_id,
        )
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
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            prefix=prefix,
        )
    raise ValueError(f"Unsupported object backend: {settings.object_backend}")
