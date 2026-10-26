"""
KPI Intelligence — Repository Abstraction Package.
"""

from backend.repository.context import TenantContext, TenantAccessDeniedError
from backend.repository.interfaces import (
    IRepository,
    QuerySpec,
    PagedResult,
    RepositoryError,
    DocumentNotFoundError,
    ConcurrencyConflictError,
    ThrottlingError,
)
from backend.repository.services import (
    CatalogServiceRepository,
    GovernanceServiceRepository,
    OntologyServiceRepository,
    AuditServiceRepository,
)

__all__ = [
    "TenantContext",
    "TenantAccessDeniedError",
    "IRepository",
    "QuerySpec",
    "PagedResult",
    "RepositoryError",
    "DocumentNotFoundError",
    "ConcurrencyConflictError",
    "ThrottlingError",
    "CatalogServiceRepository",
    "GovernanceServiceRepository",
    "OntologyServiceRepository",
    "AuditServiceRepository",
]
