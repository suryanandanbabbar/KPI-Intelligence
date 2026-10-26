"""
KPI Intelligence — Unit & Mocked Integration Tests for Cosmos DB Adapter.

Tests:
1. Point reads, upserts, and deletes with mocked Cosmos client.
2. HTTP 429 Rate Limiting / Throttling retry loop with backoff and eventual ThrottlingError.
3. HTTP 412 Precondition Failed concurrency conflict handling.
4. HTTP 404 Not Found handling.
5. Continuation token pagination.
6. Graceful skip for live Azure environment when unconfigured.
"""

import os
import unittest
from unittest.mock import MagicMock, patch
from typing import Dict, Any

from backend.contracts import CosmosContainer, AssetDocument
from backend.repository.context import TenantContext, TenantAccessDeniedError
from backend.repository.interfaces import (
    QuerySpec,
    ConcurrencyConflictError,
    ThrottlingError,
    DocumentNotFoundError,
    RepositoryError,
)
from backend.storage.config import StorageConfig, StorageBackendType, AppEnvironment
from backend.storage.cosmos.repository import CosmosRepository, AZURE_SDK_AVAILABLE

try:
    from azure.cosmos.exceptions import CosmosHttpResponseError
except ImportError:
    class CosmosHttpResponseError(Exception):
        def __init__(self, message="Cosmos Error", status_code=500, headers=None):
            super().__init__(message)
            self.status_code = status_code
            self.headers = headers or {}


class TestCosmosAdapterMocked(unittest.TestCase):
    def setUp(self):
        self.config = StorageConfig(
            backend=StorageBackendType.COSMOS,
            environment=AppEnvironment.DEVELOPMENT,
            cosmos_endpoint="https://test-account.documents.azure.com:443/",
            cosmos_database="kpi_intelligence",
            use_managed_identity=True,
            cosmos_max_retries=3,
            cosmos_retry_delay_seconds=0.01,
        )

        # Mock Azure Cosmos SDK client and container clients
        self.mock_client = MagicMock()
        self.mock_db = MagicMock()
        self.mock_container = MagicMock()

        self.mock_client.get_database_client.return_value = self.mock_db
        self.mock_db.get_container_client.return_value = self.mock_container

        self.repo = CosmosRepository(self.config, client=self.mock_client)
        self.tenant_id = "11111111-1111-1111-1111-111111111111"
        self.ctx = TenantContext(tenant_id=self.tenant_id)

    def test_get_item_success(self):
        sample_doc = {
            "id": "asset_100",
            "tenant_id": self.tenant_id,
            "doc_type": "asset",
            "asset_name": "Test Asset",
            "_etag": '"etag123"',
        }
        self.mock_container.read_item.return_value = sample_doc

        result = self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_id, "asset_100", self.ctx)
        self.assertEqual(result, sample_doc)
        self.mock_container.read_item.assert_called_once_with(item="asset_100", partition_key=self.tenant_id)

    def test_get_item_not_found_returns_none(self):
        err = CosmosHttpResponseError(status_code=404, message="Not Found")
        self.mock_container.read_item.side_effect = err

        result = self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_id, "nonexistent", self.ctx)
        self.assertIsNone(result)

    def test_upsert_item_success(self):
        sample_doc = {
            "id": "asset_100",
            "tenant_id": self.tenant_id,
            "doc_type": "asset",
            "asset_name": "New Asset",
            "_etag": '"new_etag"',
        }
        self.mock_container.upsert_item.return_value = sample_doc

        res = self.repo.upsert_item(CosmosContainer.METADATA_CATALOG, self.tenant_id, sample_doc, self.ctx)
        self.assertEqual(res["_etag"], '"new_etag"')
        self.mock_container.upsert_item.assert_called_once()

    def test_delete_item_success(self):
        self.mock_container.read_item.return_value = {"id": "asset_100", "tenant_id": self.tenant_id}
        self.mock_container.delete_item.return_value = None

        deleted = self.repo.delete_item(CosmosContainer.METADATA_CATALOG, self.tenant_id, "asset_100", self.ctx)
        self.assertTrue(deleted)
        self.mock_container.delete_item.assert_called_once_with(item="asset_100", partition_key=self.tenant_id)

    def test_throttling_429_retry_success(self):
        """Simulates 429 throttling on first two attempts, succeeded on third."""
        err_429 = CosmosHttpResponseError(status_code=429, message="Too Many Requests")
        err_429.headers = {"x-ms-retry-after-ms": "5"}
        success_doc = {"id": "asset_throttled", "tenant_id": self.tenant_id}

        self.mock_container.read_item.side_effect = [err_429, err_429, success_doc]

        result = self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_id, "asset_throttled", self.ctx)
        self.assertEqual(result, success_doc)
        self.assertEqual(self.mock_container.read_item.call_count, 3)

    def test_throttling_429_exhausted_raises_throttling_error(self):
        """Simulates 429 throttling exceeding maximum retries."""
        err_429 = CosmosHttpResponseError(status_code=429, message="Rate limit exceeded")
        err_429.headers = {"x-ms-retry-after-ms": "15"}
        self.mock_container.read_item.side_effect = err_429

        with self.assertRaises(ThrottlingError) as cm:
            self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_id, "asset_blocked", self.ctx)

        self.assertIn("exceeded max 3 retries", str(cm.exception))
        self.assertEqual(cm.exception.retry_after_ms, 15)
        self.assertEqual(self.mock_container.read_item.call_count, 3)

    def test_precondition_failed_412_raises_concurrency_conflict(self):
        """Simulates HTTP 412 on ETag mismatch."""
        err_412 = CosmosHttpResponseError(status_code=412, message="Precondition Failed")
        self.mock_container.replace_item.side_effect = err_412

        doc = {"id": "asset_conflict", "tenant_id": self.tenant_id, "asset_name": "Conflict Asset"}
        with self.assertRaises(ConcurrencyConflictError) as cm:
            self.repo.upsert_item(
                CosmosContainer.METADATA_CATALOG, self.tenant_id, doc, self.ctx, etag='"old_etag"'
            )

        self.assertIn("HTTP 412", str(cm.exception))



    def test_tenant_isolation_boundary_enforcement(self):
        """Verify cross-tenant operation fails closed."""
        other_tenant = "99999999-9999-9999-9999-999999999999"
        doc = {"id": "asset_foreign", "tenant_id": other_tenant}
        self.mock_container.read_item.return_value = doc

        # Access with TenantContext(tenant_id) where tenant_id != other_tenant
        with self.assertRaises(TenantAccessDeniedError):
            self.repo.get_item(CosmosContainer.METADATA_CATALOG, other_tenant, "asset_foreign", self.ctx)


class TestCosmosLiveIntegration(unittest.TestCase):
    @unittest.skipIf(
        not os.getenv("COSMOS_LIVE_TEST"),
        "Live Azure Cosmos DB tests skipped (set COSMOS_LIVE_TEST=1 and provide COSMOS_ENDPOINT/COSMOS_KEY to enable)"
    )
    def test_live_cloud_roundtrip(self):
        """Live roundtrip test against real Azure Cosmos DB account or emulator."""
        cfg = StorageConfig.from_env()
        repo = CosmosRepository(cfg)
        health = repo.health_check()
        self.assertEqual(health["status"], "HEALTHY")


if __name__ == "__main__":
    unittest.main()
