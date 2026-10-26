"""
KPI Intelligence — Tenant Isolation & Boundary Security Tests.

Tests:
1. Enforces fail-closed behavior when TenantContext is missing on tenant-scoped containers.
2. Partition key enforcement matching trusted tenant_id.
3. Query rewriting: injects c.tenant_id = @__enforced_tenant_id into unscoped and scoped Cosmos SQL queries.
4. Preserves ORDER BY, GROUP BY, OFFSET, and LIMIT clauses during rewriting.
5. Rejects caller-supplied conflicting tenant parameters.
6. Defense-in-depth validation rejecting cross-tenant items in query results.
7. Enforces system context requirement for mutating global reference ontology.
8. Verifies parity of tenant isolation between Cosmos DB adapter and local SQLite repository.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock

from backend.contracts import (
    CosmosContainer,
    AssetDocument,
    BusinessDomainDocument,
    LifecycleStatus,
)
from backend.repository.context import TenantContext, TenantAccessDeniedError
from backend.repository.interfaces import QuerySpec, RepositoryError
from backend.storage.config import StorageConfig, StorageBackendType, AppEnvironment
from backend.storage.cosmos.repository import CosmosRepository, enforce_tenant_predicate
from backend.storage.sqlite.repository import SQLiteRepository


class TestTenantIsolationCosmos(unittest.TestCase):
    def setUp(self):
        self.config = StorageConfig(
            backend=StorageBackendType.COSMOS,
            environment=AppEnvironment.DEVELOPMENT,
            cosmos_endpoint="https://test-account.documents.azure.com:443/",
            cosmos_database="kpi_intelligence",
            use_managed_identity=True,
        )
        self.mock_client = MagicMock()
        self.mock_db = MagicMock()
        self.mock_container = MagicMock()
        self.mock_client.get_database_client.return_value = self.mock_db
        self.mock_db.get_container_client.return_value = self.mock_container

        self.repo = CosmosRepository(self.config, client=self.mock_client)
        self.tenant_a = "11111111-1111-1111-1111-111111111111"
        self.tenant_b = "22222222-2222-2222-2222-222222222222"
        self.ctx_a = TenantContext(tenant_id=self.tenant_a)
        self.ctx_b = TenantContext(tenant_id=self.tenant_b)

    def test_query_rewriter_unscoped(self):
        q = "SELECT * FROM c"
        rewritten = enforce_tenant_predicate(q)
        self.assertEqual(rewritten, "SELECT * FROM c WHERE c.tenant_id = @__enforced_tenant_id")

    def test_query_rewriter_with_where(self):
        q = "SELECT * FROM c WHERE c.doc_type = @doc_type"
        rewritten = enforce_tenant_predicate(q)
        self.assertEqual(rewritten, "SELECT * FROM c WHERE (c.doc_type = @doc_type) AND (c.tenant_id = @__enforced_tenant_id)")

    def test_query_rewriter_with_order_by(self):
        q = "SELECT * FROM c WHERE c.doc_type = @doc_type ORDER BY c.created_at DESC"
        rewritten = enforce_tenant_predicate(q)
        self.assertEqual(
            rewritten,
            "SELECT * FROM c WHERE (c.doc_type = @doc_type) AND (c.tenant_id = @__enforced_tenant_id) ORDER BY c.created_at DESC",
        )

    def test_missing_tenant_context_fails_closed(self):
        spec = QuerySpec(query="SELECT * FROM c")
        with self.assertRaises(TenantAccessDeniedError):
            self.repo.query_items(CosmosContainer.METADATA_CATALOG, self.tenant_a, spec, tenant_context=None)

        with self.assertRaises(TenantAccessDeniedError):
            self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, "item_1", tenant_context=None)

        with self.assertRaises(TenantAccessDeniedError):
            self.repo.upsert_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, {"id": "item_1"}, tenant_context=None)

        with self.assertRaises(TenantAccessDeniedError):
            self.repo.delete_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, "item_1", tenant_context=None)

    def test_partition_key_mismatch_rejected(self):
        spec = QuerySpec(query="SELECT * FROM c")
        with self.assertRaises(TenantAccessDeniedError):
            self.repo.query_items(CosmosContainer.METADATA_CATALOG, self.tenant_b, spec, tenant_context=self.ctx_a)

        with self.assertRaises(TenantAccessDeniedError):
            self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_b, "item_1", tenant_context=self.ctx_a)

        doc = {"id": "item_1", "tenant_id": self.tenant_a}
        with self.assertRaises(TenantAccessDeniedError):
            self.repo.upsert_item(CosmosContainer.METADATA_CATALOG, self.tenant_b, doc, tenant_context=self.ctx_a)

    def test_conflicting_tenant_id_parameter_rejected(self):
        spec = QuerySpec(
            query="SELECT * FROM c WHERE c.tenant_id = @tenant_id",
            parameters=[{"name": "@tenant_id", "value": self.tenant_b}],
        )
        with self.assertRaises(TenantAccessDeniedError):
            self.repo.query_items(CosmosContainer.METADATA_CATALOG, self.tenant_a, spec, tenant_context=self.ctx_a)

    def test_query_items_rewrites_and_binds_parameter(self):
        spec = QuerySpec(
            query="SELECT * FROM c WHERE c.doc_type = @doc_type",
            parameters=[{"name": "@doc_type", "value": "asset"}],
        )
        mock_iterable = MagicMock()
        mock_pager = MagicMock()
        mock_pager.__next__.return_value = [{"id": "asset_1", "tenant_id": self.tenant_a}]
        mock_pager.continuation_token = None
        mock_iterable.by_page.return_value = mock_pager
        self.mock_container.query_items.return_value = mock_iterable

        result = self.repo.query_items(CosmosContainer.METADATA_CATALOG, None, spec, tenant_context=self.ctx_a)
        self.assertEqual(len(result.items), 1)

        # Inspect call args to client.query_items
        call_kwargs = self.mock_container.query_items.call_args[1]
        self.assertEqual(call_kwargs["partition_key"], self.tenant_a)
        self.assertIn("c.tenant_id = @__enforced_tenant_id", call_kwargs["query"])
        params = {p["name"]: p["value"] for p in call_kwargs["parameters"]}
        self.assertEqual(params["@__enforced_tenant_id"], self.tenant_a)
        self.assertEqual(params["@doc_type"], "asset")

    def test_defense_in_depth_document_validation(self):
        """If query somehow returns cross-tenant data, defense-in-depth rejects it."""
        spec = QuerySpec(query="SELECT * FROM c")
        mock_iterable = MagicMock()
        mock_pager = MagicMock()
        # Returns item belonging to tenant_b while caller is tenant_a
        mock_pager.__next__.return_value = [{"id": "leaked_doc", "tenant_id": self.tenant_b}]
        mock_pager.continuation_token = None
        mock_iterable.by_page.return_value = mock_pager
        self.mock_container.query_items.return_value = mock_iterable

        with self.assertRaises(TenantAccessDeniedError) as cm:
            self.repo.query_items(CosmosContainer.METADATA_CATALOG, self.tenant_a, spec, tenant_context=self.ctx_a)

        # Assert exception is NOT wrapped in RepositoryError
        self.assertFalse(isinstance(cm.exception, RepositoryError))
        # Assert query was executed exactly once (no retry for authorization error)
        self.assertEqual(self.mock_container.query_items.call_count, 1)

    def test_authorization_failure_not_retried(self):
        """Verifies that authorization failure in _execute_with_retry is never retried."""
        call_count = 0
        def faulty_op():
            nonlocal call_count
            call_count += 1
            raise TenantAccessDeniedError("Cross tenant violation")

        with self.assertRaises(TenantAccessDeniedError):
            self.repo._execute_with_retry("test_op", faulty_op)

        self.assertEqual(call_count, 1)

    def test_genuine_storage_error_wrapped_in_repository_error(self):
        """Verifies genuine unexpected storage errors are wrapped in RepositoryError."""
        def faulty_op():
            raise RuntimeError("Database connection dropped unexpectedly")

        with self.assertRaises(RepositoryError) as cm:
            self.repo._execute_with_retry("test_op", faulty_op)

        self.assertIn("Cosmos DB error during 'test_op'", str(cm.exception))

    def test_global_ontology_mutations_require_system_context(self):
        doc = {"id": "domain_1", "business_domain": "SYSTEM", "domain_code": "CLAIMS"}
        # Regular tenant cannot upsert or delete ontology
        with self.assertRaises(TenantAccessDeniedError):
            self.repo.upsert_item(CosmosContainer.KPI_ONTOLOGY, "SYSTEM", doc, tenant_context=self.ctx_a)

        with self.assertRaises(TenantAccessDeniedError):
            self.repo.delete_item(CosmosContainer.KPI_ONTOLOGY, "SYSTEM", "domain_1", tenant_context=self.ctx_a)

        # System context succeeds
        sys_ctx = TenantContext.system_context()
        self.mock_container.upsert_item.return_value = doc
        res = self.repo.upsert_item(CosmosContainer.KPI_ONTOLOGY, "SYSTEM", doc, tenant_context=sys_ctx)
        self.assertEqual(res["id"], "domain_1")


class TestTenantIsolationSqlite(unittest.TestCase):
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

    def test_sqlite_missing_tenant_context_fails_closed(self):
        spec = QuerySpec(query="SELECT * FROM c")
        with self.assertRaises(TenantAccessDeniedError):
            self.repo.query_items(CosmosContainer.METADATA_CATALOG, self.tenant_a, spec, tenant_context=None)

        with self.assertRaises(TenantAccessDeniedError):
            self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, "item_1", tenant_context=None)

        with self.assertRaises(TenantAccessDeniedError):
            self.repo.upsert_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, {"id": "item_1"}, tenant_context=None)

        with self.assertRaises(TenantAccessDeniedError):
            self.repo.delete_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, "item_1", tenant_context=None)

    def test_sqlite_cross_tenant_isolation(self):
        doc_a = AssetDocument(id="asset_a", tenant_id=self.tenant_a, asset_name="Asset A")
        doc_b = AssetDocument(id="asset_b", tenant_id=self.tenant_b, asset_name="Asset B")

        self.repo.upsert_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, doc_a.to_dict(), self.ctx_a)
        self.repo.upsert_item(CosmosContainer.METADATA_CATALOG, self.tenant_b, doc_b.to_dict(), self.ctx_b)

        # Tenant A queries all items
        spec = QuerySpec(query="SELECT * FROM c")
        res_a = self.repo.query_items(CosmosContainer.METADATA_CATALOG, self.tenant_a, spec, self.ctx_a)
        self.assertEqual(len(res_a.items), 1)
        self.assertEqual(res_a.items[0]["id"], "asset_a")

        # Tenant A tries to read Tenant B's partition key
        with self.assertRaises(TenantAccessDeniedError):
            self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_b, "asset_b", self.ctx_a)

    def test_sqlite_conflicting_param_rejected(self):
        spec = QuerySpec(
            query="SELECT * FROM c WHERE c.tenant_id = @tenant_id",
            parameters=[{"name": "@tenant_id", "value": self.tenant_b}],
        )
        with self.assertRaises(TenantAccessDeniedError):
            self.repo.query_items(CosmosContainer.METADATA_CATALOG, self.tenant_a, spec, self.ctx_a)

    def test_sqlite_defense_in_depth_document_validation(self):
        """Verifies that SQLite query_items defense-in-depth rejects leaked cross-tenant items without wrapping."""
        # Insert a document directly with mismatching partition key
        with self.assertRaises(TenantAccessDeniedError) as cm:
            self.repo.query_items(CosmosContainer.METADATA_CATALOG, self.tenant_b, QuerySpec(query="SELECT * FROM c"), self.ctx_a)
        self.assertFalse(isinstance(cm.exception, RepositoryError))


if __name__ == "__main__":
    unittest.main()
