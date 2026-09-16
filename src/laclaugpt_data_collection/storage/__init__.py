"""Storage adapters for local and distributed deployments."""

from .base import ObjectStore, RecordStore
from .csv import CSVRecordStore
from .local import FilesystemObjectStore, SQLiteRecordStore

__all__ = [
    "CSVRecordStore",
    "FilesystemObjectStore",
    "ObjectStore",
    "RecordStore",
    "SQLiteRecordStore",
]
