"""
KPI Intelligence — Storage Configuration and Environment Validation.

Manages configuration for:
- Azure Cosmos DB for NoSQL (production backend)
- Local SQLite (development and testing backend)
- Strict backend selection and production safety guards
"""

import os
from enum import Enum
from typing import Optional
from dataclasses import dataclass


class StorageBackendType(str, Enum):
    COSMOS = "cosmos"
    SQLITE = "sqlite"


class AppEnvironment(str, Enum):
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"
    TEST = "test"


@dataclass
class StorageConfig:
    backend: StorageBackendType
    environment: AppEnvironment

    # Cosmos DB Settings
    cosmos_endpoint: Optional[str] = None
    cosmos_database: Optional[str] = None
    cosmos_key: Optional[str] = None  # Dev/test secret path; managed identity preferred
    use_managed_identity: bool = True
    cosmos_max_retries: int = 5
    cosmos_retry_delay_seconds: float = 0.5
    cosmos_connection_timeout: int = 10

    # SQLite Settings
    sqlite_path: str = "local_data/kpi_intelligence.sqlite3"
    sqlite_journal_mode: str = "WAL"

    @classmethod
    def from_env(cls) -> "StorageConfig":
        env_str = os.getenv("KPI_ENVIRONMENT", "development").strip().lower()
        backend_str = os.getenv("KPI_STORAGE_BACKEND", "").strip().lower()

        # Parse environment
        try:
            app_env = AppEnvironment(env_str)
        except ValueError:
            app_env = AppEnvironment.DEVELOPMENT

        # Default backend if not explicitly provided:
        # In production or staging, default is ALWAYS Cosmos.
        # In development/test, default is SQLite if not explicitly set to cosmos.
        if not backend_str:
            if app_env in (AppEnvironment.PRODUCTION, AppEnvironment.STAGING):
                backend_str = StorageBackendType.COSMOS.value
            else:
                backend_str = StorageBackendType.SQLITE.value

        try:
            backend_type = StorageBackendType(backend_str)
        except ValueError:
            raise ValueError(
                f"Invalid KPI_STORAGE_BACKEND '{backend_str}'. Allowed values: 'cosmos', 'sqlite'."
            )

        # CRITICAL PRODUCTION SAFETY GUARD:
        # Production and Staging MUST NEVER select or fall back to SQLite.
        if app_env in (AppEnvironment.PRODUCTION, AppEnvironment.STAGING) and backend_type == StorageBackendType.SQLITE:
            raise RuntimeError(
                f"FATAL CONFIGURATION ERROR: KPI_STORAGE_BACKEND is set to 'sqlite' in {app_env.value} environment. "
                "SQLite is strictly prohibited in production and staging environments. "
                "Set KPI_STORAGE_BACKEND=cosmos and provide required Cosmos DB configuration."
            )

        endpoint = os.getenv("COSMOS_ENDPOINT")
        database = os.getenv("COSMOS_DATABASE")
        key = os.getenv("COSMOS_KEY")
        use_mi = os.getenv("COSMOS_USE_MANAGED_IDENTITY", "true").strip().lower() in ("true", "1", "yes")

        # In production Cosmos mode, validate required configuration
        if backend_type == StorageBackendType.COSMOS:
            if not endpoint:
                raise ValueError("COSMOS_ENDPOINT environment variable is required when using Cosmos DB backend.")
            if not database:
                raise ValueError("COSMOS_DATABASE environment variable is required when using Cosmos DB backend.")
            if not use_mi and not key:
                raise ValueError(
                    "Either COSMOS_USE_MANAGED_IDENTITY=true (default) or COSMOS_KEY must be provided for Cosmos DB."
                )

        raw_sqlite_path = os.getenv("KPI_SQLITE_PATH", "local_data/kpi_intelligence.sqlite3").strip()
        abs_sqlite_path = raw_sqlite_path if raw_sqlite_path == ":memory:" else os.path.abspath(raw_sqlite_path)
        journal_mode = os.getenv("KPI_SQLITE_JOURNAL_MODE", "WAL").strip().upper()
        if journal_mode not in ("WAL", "DELETE", "TRUNCATE", "MEMORY", "OFF"):
            journal_mode = "WAL"

        return cls(
            backend=backend_type,
            environment=app_env,
            cosmos_endpoint=endpoint,
            cosmos_database=database,
            cosmos_key=key,
            use_managed_identity=use_mi,
            sqlite_path=abs_sqlite_path,
            sqlite_journal_mode=journal_mode,
        )

    def to_safe_dict(self) -> dict:
        """Returns non-sensitive metadata for diagnostics and logging."""
        return {
            "backend": self.backend.value,
            "environment": self.environment.value,
            "sqlite_path": self.sqlite_path,
            "sqlite_journal_mode": self.sqlite_journal_mode,
            "has_cosmos_endpoint": bool(self.cosmos_endpoint),
            "cosmos_database": self.cosmos_database,
            "use_managed_identity": self.use_managed_identity,
        }
