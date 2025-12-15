"""Adapters for external systems.

This module contains implementations of the repository protocols
for various storage backends.
"""

from src.adapters.repository_compat import WINDOW, RepositoryAdapter
from src.adapters.sqlite_repository import SQLiteRepository

__all__ = ["RepositoryAdapter", "SQLiteRepository", "WINDOW"]
