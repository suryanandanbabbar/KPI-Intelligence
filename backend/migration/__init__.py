"""
KPI Intelligence — Canonical PostgreSQL to Cosmos DB Migration Package.
"""

from backend.migration.dispositions import (
    MigrationDispositionType,
    TableMigrationDisposition,
    CANONICAL_MIGRATION_REGISTRY,
    get_disposition_for_table,
)

__all__ = [
    "MigrationDispositionType",
    "TableMigrationDisposition",
    "CANONICAL_MIGRATION_REGISTRY",
    "get_disposition_for_table",
]
