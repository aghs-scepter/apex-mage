"""Adapters for external systems.

This module contains implementations of the repository protocols
for various storage backends.
"""

from src.adapters.gcs_adapter import GCSAdapter, GCSUploadError
from src.adapters.repository_compat import WINDOW, RepositoryAdapter
from src.adapters.sqlite_repository import SQLiteRepository

__all__ = [
    "GCSAdapter",
    "GCSUploadError",
    "RepositoryAdapter",
    "SQLiteRepository",
    "WINDOW",
]
