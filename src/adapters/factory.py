"""Repository factory for creating different repository implementations.

This module provides a factory function for creating repository instances
based on the specified backend type.

Supported backends:
- "sqlite": Production SQLite-backed repository
- "memory": In-memory repository for testing

Example:
    # Create a SQLite repository
    repo = create_repository("sqlite", db_path="data/app.db")

    # Create an in-memory repository for testing
    repo = create_repository("memory")
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Union

from src.adapters.sqlite_repository import SQLiteRepository

if TYPE_CHECKING:
    from src.adapters.memory_repository import MemoryRepository

# Type alias for repository return type
RepositoryType = Union["SQLiteRepository", "MemoryRepository"]


def create_repository(backend: str, **kwargs: str | Path) -> RepositoryType:
    """Create a repository instance based on the specified backend.

    Args:
        backend: The backend type to use. Supported values:
            - "sqlite": SQLite-backed repository (requires db_path kwarg)
            - "memory": In-memory repository for testing
        **kwargs: Backend-specific configuration options:
            - db_path: Required for "sqlite" backend. Path to the database file.

    Returns:
        A repository instance of the appropriate type.

    Raises:
        ValueError: If the backend is not supported or required kwargs are missing.

    Example:
        # SQLite repository
        repo = create_repository("sqlite", db_path="/path/to/db.sqlite")

        # Memory repository
        repo = create_repository("memory")
    """
    if backend == "sqlite":
        db_path = kwargs.get("db_path")
        if db_path is None:
            raise ValueError("'db_path' is required for sqlite backend")
        return SQLiteRepository(db_path)

    if backend == "memory":
        # Import here to avoid circular imports and allow memory_repository
        # to be optional (only needed for testing)
        from src.adapters.memory_repository import MemoryRepository

        return MemoryRepository()

    raise ValueError(
        f"Unsupported backend: {backend!r}. Supported backends: 'sqlite', 'memory'"
    )
