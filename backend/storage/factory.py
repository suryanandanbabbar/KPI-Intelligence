"""
KPI Intelligence — Storage Backend Factory.

Provides centralized repository instantiation:
- Enforces strict backend selection based on environment configuration
- Guarantees production environments cannot accidentally or silently select SQLite
- Returns unified IRepository interface
"""

import logging
from typing import Optional
from backend.repository.interfaces import IRepository
from backend.storage.config import StorageConfig, StorageBackendType, AppEnvironment
from backend.storage.sqlite.repository import SQLiteRepository

logger = logging.getLogger("kpi_intel.storage.factory")


def get_repository(config: Optional[StorageConfig] = None) -> IRepository:
    """
    Instantiates and returns the configured IRepository implementation.
    Validates environment safety constraints.
    """
    if config is None:
        config = StorageConfig.from_env()

    # Re-validate environment guard
    if config.environment in (AppEnvironment.PRODUCTION, AppEnvironment.STAGING) and config.backend == StorageBackendType.SQLITE:
        raise RuntimeError(
            f"SECURITY VIOLATION: Refusing to create SQLite repository in '{config.environment.value}' environment. "
            "Azure Cosmos DB for NoSQL is the only permitted production persistence backend."
        )

    if config.backend == StorageBackendType.COSMOS:
        logger.info("Initializing Azure Cosmos DB production repository.")
        from backend.storage.cosmos.repository import CosmosRepository
        return CosmosRepository(config)

    elif config.backend == StorageBackendType.SQLITE:
        logger.info("Initializing local SQLite test repository at: %s", config.sqlite_path)
        return SQLiteRepository(config.sqlite_path)

    else:
        raise ValueError(f"Unsupported storage backend: '{config.backend}'")
