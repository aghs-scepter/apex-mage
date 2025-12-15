"""Adapters for external systems.

This module contains implementations of the repository protocols
for various storage backends.
"""

from src.adapters.sqlite_repository import SQLiteRepository

__all__ = ["SQLiteRepository"]
