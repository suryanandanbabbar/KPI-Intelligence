"""
KPI Intelligence — Unit & Integration Tests for Local SQLite Repository.

Verifies:
1. Full CRUD operations across Cosmos containers.
2. Parameterized SQL queries using json_extract.
3. Continuation token pagination.
4. Optimistic concurrency control (ETag matching and 412 conflicts).
5. Fail-closed cross-tenant isolation enforcement.
6. Reset, init, and reseed functionality.
7. Critical production safety guard preventing SQLite execution in production/staging.
"""

import os
import tempfile
import unittest
import uuid
from typing import Dict, Any

from backend.contracts import (
    CosmosContainer,
    AssetDocument,
    ReportDocument,
    LifecycleStatus,
)
from backend.repository.context import TenantContext, TenantAccessDeniedError
from backend.repository.interfaces import QuerySpec, ConcurrencyConflictError
from backend.storage.config import StorageConfig, StorageBackendType, AppEnvironment
from backend.storage.sqlite.repository import SQLiteRepository
from backend.storage.fixtures import seed_synthetic_data


class TestSqliteDocumentRepository(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.db_path = self.temp_file.name
        self.temp_file.close()

        self.repo = SQLiteRepository(self.db_path)
        self.tenant_a = "11111111-1111-1111-1111-111111111111"
        self.tenant_b = "22222222-2222-2222-2222-222222222222"
        self.ctx_a = TenantContext(tenant_id=self.tenant_a)
        self.ctx_b = TenantContext(tenant_id=self.tenant_b)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_crud_operations(self):
        doc = AssetDocument(
            id="asset_test_001",
            tenant_id=self.tenant_a,
            asset_name="Financial Dashboard Asset",
            platform="POWER_BI",
        )

        # 1. Create (upsert)
        created = self.repo.upsert_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, doc.to_dict(), self.ctx_a)
        self.assertEqual(created["id"], "asset_test_001")
        self.assertIn("_etag", created)
        etag_v1 = created["_etag"]

        # 2. Read
        read_doc = self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, "asset_test_001", self.ctx_a)
        self.assertIsNotNone(read_doc)
        self.assertEqual(read_doc["asset_name"], "Financial Dashboard Asset")
        self.assertEqual(read_doc["_etag"], etag_v1)

        # 3. Update
        created["asset_name"] = "Updated Financial Dashboard Asset"
        updated = self.repo.upsert_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, created, self.ctx_a)
        self.assertEqual(updated["asset_name"], "Updated Financial Dashboard Asset")
        self.assertNotEqual(updated["_etag"], etag_v1)

        # 4. Delete
        deleted = self.repo.delete_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, "asset_test_001", self.ctx_a)
        self.assertTrue(deleted)

        # Verify not found after delete
        not_found = self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, "asset_test_001", self.ctx_a)
        self.assertIsNone(not_found)

    def test_parameterized_queries(self):
        # Insert test reports
        for i in range(5):
            rep = ReportDocument(
                id=f"rep_{i}",
                tenant_id=self.tenant_a,
                report_name=f"Report #{i}",
                lifecycle_status=LifecycleStatus.ACTIVE.value if i % 2 == 0 else LifecycleStatus.DORMANT.value,
            )
            self.repo.upsert_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, rep.to_dict(), self.ctx_a)

        # Query active reports
        spec = QuerySpec(
            query="SELECT * FROM c WHERE c.doc_type = @type AND c.lifecycle_status = @status",
            parameters=[
                {"name": "@type", "value": "report"},
                {"name": "@status", "value": "ACTIVE"},
            ],
        )

        paged = self.repo.query_items(CosmosContainer.METADATA_CATALOG, self.tenant_a, spec, self.ctx_a)
        self.assertEqual(len(paged.items), 3)
        for item in paged.items:
            self.assertEqual(item["lifecycle_status"], "ACTIVE")

    def test_continuation_token_pagination(self):
        # Insert 7 reports
        for i in range(7):
            rep = ReportDocument(
                id=f"rep_page_{i}",
                tenant_id=self.tenant_a,
                report_name=f"Paged Report {i}",
            )
            self.repo.upsert_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, rep.to_dict(), self.ctx_a)

        spec = QuerySpec(
            query="SELECT * FROM c WHERE c.doc_type = @type",
            parameters=[{"name": "@type", "value": "report"}],
        )

        # Page 1 (limit 3)
        page1 = self.repo.query_items(
            CosmosContainer.METADATA_CATALOG, self.tenant_a, spec, self.ctx_a, page_size=3
        )
        self.assertEqual(len(page1.items), 3)
        self.assertIsNotNone(page1.continuation_token)

        # Page 2 (limit 3)
        page2 = self.repo.query_items(
            CosmosContainer.METADATA_CATALOG,
            self.tenant_a,
            spec,
            self.ctx_a,
            page_size=3,
            continuation_token=page1.continuation_token,
        )
        self.assertEqual(len(page2.items), 3)
        self.assertIsNotNone(page2.continuation_token)

        # Page 3 (remaining 1 item)
        page3 = self.repo.query_items(
            CosmosContainer.METADATA_CATALOG,
            self.tenant_a,
            spec,
            self.ctx_a,
            page_size=3,
            continuation_token=page2.continuation_token,
        )
        self.assertEqual(len(page3.items), 1)
        self.assertIsNone(page3.continuation_token)

        # Verify all items collected without duplicate IDs
        all_ids = [item["id"] for item in page1.items + page2.items + page3.items]
        self.assertEqual(len(set(all_ids)), 7)

    def test_etag_optimistic_concurrency_control(self):
        doc = AssetDocument(
            id="asset_etag_test",
            tenant_id=self.tenant_a,
            asset_name="Concurrent Asset",
        )
        created = self.repo.upsert_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, doc.to_dict(), self.ctx_a)
        original_etag = created["_etag"]

        # Successful update with matching ETag
        created["asset_name"] = "Concurrent Asset V2"
        updated = self.repo.upsert_item(
            CosmosContainer.METADATA_CATALOG, self.tenant_a, created, self.ctx_a, etag=original_etag
        )
        self.assertNotEqual(updated["_etag"], original_etag)

        # Conflict update with stale ETag
        created["asset_name"] = "Stale Conflict Update"
        with self.assertRaises(ConcurrencyConflictError) as cm:
            self.repo.upsert_item(
                CosmosContainer.METADATA_CATALOG, self.tenant_a, created, self.ctx_a, etag=original_etag
            )
        self.assertIn("ETag mismatch", str(cm.exception))

    def test_cross_tenant_isolation_enforcement(self):
        doc = AssetDocument(
            id="asset_tenant_a",
            tenant_id=self.tenant_a,
            asset_name="Tenant A Confidential Asset",
        )
        self.repo.upsert_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, doc.to_dict(), self.ctx_a)

        # Tenant B cannot read Tenant A doc (raises TenantAccessDeniedError fail-closed)
        with self.assertRaises(TenantAccessDeniedError):
            self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, "asset_tenant_a", self.ctx_b)

        # Tenant B attempting to upsert with Tenant A partition key raises TenantAccessDeniedError
        with self.assertRaises(TenantAccessDeniedError):
            self.repo.upsert_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, doc.to_dict(), self.ctx_b)

        # Tenant B attempting to delete Tenant A doc raises TenantAccessDeniedError
        with self.assertRaises(TenantAccessDeniedError):
            self.repo.delete_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, "asset_tenant_a", self.ctx_b)


    def test_reset_and_synthetic_seed(self):
        seed_count = seed_synthetic_data(self.repo)
        self.assertGreater(seed_count, 15)

        # Inspect counts
        counts = self.repo.inspect_counts()
        self.assertEqual(counts["total_documents"], seed_count)
        self.assertGreater(counts["by_container"][CosmosContainer.METADATA_CATALOG.value], 0)
        self.assertGreater(counts["by_container"][CosmosContainer.KPI_ONTOLOGY.value], 0)

        # Reset database
        self.repo.reset_database()
        empty_counts = self.repo.inspect_counts()
        self.assertEqual(empty_counts["total_documents"], 0)

    def test_production_safety_guard(self):
        # Setting production environment with sqlite backend MUST raise fatal error
        os.environ["KPI_ENVIRONMENT"] = "production"
        os.environ["KPI_STORAGE_BACKEND"] = "sqlite"

        try:
            with self.assertRaises(RuntimeError) as cm:
                StorageConfig.from_env()
            self.assertIn("SQLite is strictly prohibited in production and staging", str(cm.exception))
        finally:
            os.environ["KPI_ENVIRONMENT"] = "development"
            os.environ["KPI_STORAGE_BACKEND"] = "sqlite"


if __name__ == "__main__":
    unittest.main()
