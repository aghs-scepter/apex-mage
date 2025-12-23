"""Adapters for external systems.

This module contains implementations of the repository protocols
for various storage backends.
"""

from src.adapters.factory import create_repository
from src.adapters.gcs_adapter import GCSAdapter, GCSUploadError
from src.adapters.memory_repository import MemoryRepository
from src.adapters.repository_compat import WINDOW, RepositoryAdapter
from src.adapters.sqlite_repository import SQLiteRepository

__all__ = [
    "GCSAdapter",
    "GCSUploadError",
    "MemoryRepository",
    "RepositoryAdapter",
    "SQLiteRepository",
    "WINDOW",
    "create_repository",
]
