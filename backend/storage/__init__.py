"""
KPI Intelligence — Storage Backend Package.
"""

from backend.storage.config import StorageConfig, StorageBackendType, AppEnvironment
from backend.storage.factory import get_repository
from backend.storage.sqlite.repository import SQLiteRepository

try:
    from backend.storage.cosmos.repository import CosmosRepository
except ImportError:
    CosmosRepository = None

__all__ = [
    "StorageConfig",
    "StorageBackendType",
    "AppEnvironment",
    "get_repository",
    "SQLiteRepository",
    "CosmosRepository",
]
