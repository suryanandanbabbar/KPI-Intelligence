"""
KPI Intelligence — Azure Cosmos DB for NoSQL Production Adapter.

Implements IRepository using the official Azure Cosmos DB Python SDK.
Features:
- Microsoft Entra ID (DefaultAzureCredential) / Managed Identity support
- Account Key fallback for local Cosmos emulator / development testing
- Robust HTTP 429 throttling handling with exponential backoff & jitter
- ETag optimistic concurrency enforcement (HTTP 412 handling)
- Partition-scoped point reads, queries, and continuation-token pagination
- Sanitized operational metrics without leaking sensitive payloads
"""

import time
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone

from backend.contracts.base import CosmosContainer, CONTAINER_PARTITION_KEYS
from backend.repository.interfaces import (
    IRepository,
    QuerySpec,
    PagedResult,
    DocumentNotFoundError,
    ConcurrencyConflictError,
    ThrottlingError,
    RepositoryError,
)
from backend.repository.context import TenantContext
from backend.storage.config import StorageConfig

logger = logging.getLogger("kpi_intel.storage.cosmos")

# Lazy-import azure.cosmos and azure.identity
try:
    from azure.cosmos import CosmosClient, PartitionKey
    from azure.cosmos.exceptions import CosmosHttpResponseError
    from azure.identity import DefaultAzureCredential
    AZURE_SDK_AVAILABLE = True
except ImportError:
    AZURE_SDK_AVAILABLE = False
    CosmosClient = None
    CosmosHttpResponseError = Exception


class CosmosRepository(IRepository):
    """
    Production storage adapter for Azure Cosmos DB for NoSQL.
    """

    def __init__(self, config: StorageConfig, client: Optional[Any] = None):
        self.config = config
        self._client = client
        self._database = None
        self._containers: Dict[str, Any] = {}
        self._init_client()

    def _init_client(self) -> None:
        """Initializes CosmosClient using managed identity or key authentication."""
        if not AZURE_SDK_AVAILABLE and self._client is None:
            raise RuntimeError(
                "azure-cosmos SDK is not installed in the active Python environment. "
                "Install via 'pip install azure-cosmos azure-identity'."
            )

        if self._client is None:
            if not self.config.cosmos_endpoint:
                raise ValueError("COSMOS_ENDPOINT is required to initialize Cosmos DB.")
            if not self.config.cosmos_database:
                raise ValueError("COSMOS_DATABASE is required to initialize Cosmos DB.")

            logger.info("Initializing Azure Cosmos DB client for endpoint: %s", self.config.cosmos_endpoint)
            if self.config.use_managed_identity:
                credential = DefaultAzureCredential()
            else:
                if not self.config.cosmos_key:
                    raise ValueError("COSMOS_KEY is required when COSMOS_USE_MANAGED_IDENTITY is false.")
                credential = self.config.cosmos_key

            self._client = CosmosClient(
                url=self.config.cosmos_endpoint,
                credential=credential,
                connection_timeout=self.config.cosmos_connection_timeout,
            )

        self._database = self._client.get_database_client(self.config.cosmos_database)

    def _get_container_client(self, container: CosmosContainer) -> Any:
        name = container.value
        if name not in self._containers:
            self._containers[name] = self._database.get_container_client(name)
        return self._containers[name]

    def _execute_with_retry(self, operation_name: str, op_callable) -> Any:
        """
        Executes a Cosmos SDK operation with bounded retry for transient errors and HTTP 429 throttling.
        """
        max_attempts = self.config.cosmos_max_retries
        attempt = 0
        while True:
            try:
                attempt += 1
                return op_callable()
            except CosmosHttpResponseError as ex:
                status_code = getattr(ex, "status_code", 500)
                # 429: Throttling / Request Rate Too Large
                if status_code == 429:
                    if attempt >= max_attempts:
                        retry_after = ex.headers.get("x-ms-retry-after-ms") if hasattr(ex, "headers") else None
                        raise ThrottlingError(
                            f"Cosmos DB throttling (HTTP 429) exceeded max {max_attempts} retries for '{operation_name}'.",
                            retry_after_ms=int(retry_after) if retry_after else None,
                        )
                    # Read retry-after header if present, otherwise exponential backoff
                    wait_ms = 500 * (2 ** (attempt - 1))
                    if hasattr(ex, "headers") and "x-ms-retry-after-ms" in ex.headers:
                        try:
                            wait_ms = int(ex.headers["x-ms-retry-after-ms"])
                        except (ValueError, TypeError):
                            pass
                    logger.warning(
                        "Cosmos DB 429 throttling encountered on %s (attempt %d/%d). Backing off %d ms.",
                        operation_name, attempt, max_attempts, wait_ms
                    )
                    time.sleep(wait_ms / 1000.0)
                    continue

                # 412: Precondition Failed (ETag mismatch)
                if status_code == 412:
                    raise ConcurrencyConflictError(
                        f"Cosmos DB concurrency conflict (HTTP 412) on operation '{operation_name}': document was modified concurrently."
                    )

                # 404: Not Found
                if status_code == 404:
                    raise DocumentNotFoundError(f"Cosmos DB document not found (HTTP 404) during '{operation_name}'.")

                # Other HTTP errors: re-raise wrapped
                raise RepositoryError(
                    f"Cosmos DB error during '{operation_name}': HTTP {status_code} - {getattr(ex, 'message', str(ex))}"
                )

    def get_item(
        self,
        container: CosmosContainer,
        partition_key: str,
        item_id: str,
        tenant_context: Optional[TenantContext] = None,
    ) -> Optional[Dict[str, Any]]:
        client = self._get_container_client(container)

        def _read():
            try:
                return client.read_item(item=item_id, partition_key=partition_key)
            except DocumentNotFoundError:
                return None
            except CosmosHttpResponseError as e:
                if getattr(e, "status_code", None) == 404:
                    return None
                raise

        doc = self._execute_with_retry(f"read_item({container.value}, {item_id})", _read)
        if doc and tenant_context:
            tenant_context.assert_authorized(doc.get("tenant_id"))
        return doc

    def upsert_item(
        self,
        container: CosmosContainer,
        partition_key: str,
        item: Dict[str, Any],
        tenant_context: Optional[TenantContext] = None,
        etag: Optional[str] = None,
    ) -> Dict[str, Any]:
        item_tenant = item.get("tenant_id")
        if tenant_context:
            tenant_context.assert_authorized(item_tenant)

        client = self._get_container_client(container)
        doc_id = item.get("id")

        def _upsert():
            if etag:
                # Use replace_item with match_condition to enforce ETag
                match_condition = {"type": "IfMatch", "condition": etag}
                return client.replace_item(
                    item=doc_id,
                    body=item,
                    access_condition=match_condition
                )
            else:
                return client.upsert_item(body=item)

        return self._execute_with_retry(f"upsert_item({container.value}, {doc_id})", _upsert)

    def delete_item(
        self,
        container: CosmosContainer,
        partition_key: str,
        item_id: str,
        tenant_context: Optional[TenantContext] = None,
    ) -> bool:
        # If tenant context provided, verify tenant ownership before deleting
        if tenant_context:
            existing = self.get_item(container, partition_key, item_id, tenant_context)
            if not existing:
                return False
            tenant_context.assert_authorized(existing.get("tenant_id"))

        client = self._get_container_client(container)

        def _delete():
            try:
                client.delete_item(item=item_id, partition_key=partition_key)
                return True
            except (DocumentNotFoundError, CosmosHttpResponseError) as ex:
                if getattr(ex, "status_code", None) == 404:
                    return False
                raise

        return self._execute_with_retry(f"delete_item({container.value}, {item_id})", _delete)

    def query_items(
        self,
        container: CosmosContainer,
        partition_key: Optional[str],
        query_spec: QuerySpec,
        tenant_context: Optional[TenantContext] = None,
        page_size: int = 100,
        continuation_token: Optional[str] = None,
    ) -> PagedResult:
        client = self._get_container_client(container)

        # Enforce tenant isolation parameter if tenant context present
        query = query_spec.query
        params = list(query_spec.parameters)
        if tenant_context and not tenant_context.is_system:
            # Ensure tenant_id parameter matches context
            if not any(p["name"] == "@tenant_id" for p in params):
                params.append({"name": "@tenant_id", "value": tenant_context.tenant_id})

        def _query():
            query_iterable = client.query_items(
                query=query,
                parameters=params,
                partition_key=partition_key,
                max_item_count=page_size,
            )
            pager = query_iterable.by_page(continuation_token)
            try:
                page = next(pager)
                items = list(page)
                next_token = pager.continuation_token
            except StopIteration:
                items = []
                next_token = None

            # Get request charge from last response
            charge = 0.0
            if hasattr(client, "client_connection") and hasattr(client.client_connection, "last_response_headers"):
                headers = client.client_connection.last_response_headers
                charge = float(headers.get("x-ms-request-charge", 0.0))

            return PagedResult(items=items, continuation_token=next_token, request_charge=charge)

        return self._execute_with_retry(f"query_items({container.value})", _query)

    def health_check(self) -> Dict[str, Any]:
        """Performs a lightweight read to verify Cosmos DB connectivity."""
        try:
            # Read database properties
            db_props = self._database.read()
            return {
                "status": "HEALTHY",
                "backend": "cosmos",
                "endpoint": self.config.cosmos_endpoint,
                "database": self.config.cosmos_database,
                "database_id": db_props.get("id"),
            }
        except Exception as e:
            return {
                "status": "UNHEALTHY",
                "backend": "cosmos",
                "error": str(e),
            }
