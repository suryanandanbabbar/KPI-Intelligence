"""
KPI Intelligence — Canonical Repository Interfaces.

Defines the contract for physical storage adapters (Cosmos DB NoSQL and SQLite).
Enforces:
- Tenant-scoped reads and writes
- Pagination via continuation tokens
- Concurrency control via ETags
- Partition key awareness
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Sequence
from backend.contracts.base import CosmosContainer
from backend.repository.context import TenantContext


class RepositoryError(Exception):
    """Base error for repository operations."""
    pass


class DocumentNotFoundError(RepositoryError):
    """Raised when an item is not found."""
    pass


class ConcurrencyConflictError(RepositoryError):
    """Raised on ETag mismatch (HTTP 412 in Cosmos)."""
    pass


class ThrottlingError(RepositoryError):
    """Raised when rate limits are exceeded (HTTP 429 in Cosmos)."""
    def __init__(self, message: str, retry_after_ms: Optional[int] = None):
        super().__init__(message)
        self.retry_after_ms = retry_after_ms


@dataclass
class QuerySpec:
    """Parameterized query specification for NoSQL and SQLite querying."""
    query: str
    parameters: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class PagedResult:
    """Result set returned with pagination metadata."""
    items: List[Dict[str, Any]]
    continuation_token: Optional[str] = None
    request_charge: float = 0.0
    total_count: Optional[int] = None


class IRepository(ABC):
    """Abstract data-access repository interface implemented by Cosmos DB and SQLite."""

    @abstractmethod
    def get_item(
        self,
        container: CosmosContainer,
        partition_key: str,
        item_id: str,
        tenant_context: Optional[TenantContext] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Point-reads a document by ID and partition key with tenant authorization.
        Returns None if not found.
        """
        pass

    @abstractmethod
    def upsert_item(
        self,
        container: CosmosContainer,
        partition_key: str,
        item: Dict[str, Any],
        tenant_context: Optional[TenantContext] = None,
        etag: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Idempotently inserts or updates a document.
        If etag is supplied, enforces optimistic concurrency (fails if etag changed).
        """
        pass

    @abstractmethod
    def delete_item(
        self,
        container: CosmosContainer,
        partition_key: str,
        item_id: str,
        tenant_context: Optional[TenantContext] = None,
    ) -> bool:
        """
        Deletes a document by ID and partition key with tenant authorization.
        Returns True if deleted, False if item was not found.
        """
        pass

    @abstractmethod
    def query_items(
        self,
        container: CosmosContainer,
        partition_key: Optional[str],
        query_spec: QuerySpec,
        tenant_context: Optional[TenantContext] = None,
        page_size: int = 100,
        continuation_token: Optional[str] = None,
    ) -> PagedResult:
        """
        Queries items in a container, scoped by tenant authorization and optional partition key.
        Supports continuation-token pagination.
        """
        pass

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Performs a diagnostic connectivity and readiness check."""
        pass
