"""Storage adapters for local and distributed deployments."""

from .base import ObjectStore, RecordStore
from .local import FilesystemObjectStore, SQLiteRecordStore

__all__ = [
    "FilesystemObjectStore",
    "ObjectStore",
    "RecordStore",
    "SQLiteRecordStore",
]
