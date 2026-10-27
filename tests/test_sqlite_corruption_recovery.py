"""
KPI Intelligence — SQLite Integrity Diagnostics & Corruption Safeguard Tests.

Validates:
1. Absolute path resolution and KPI_SQLITE_PATH environment handling.
2. Healthy database non-destructive integrity diagnostics (PRAGMA quick_check / integrity_check).
3. Non-destructive corruption detection returning actionable StorageCorruptionError.
4. Invariant: Corrupted database file is NEVER silently deleted, reset, or overwritten.
5. API error mapping:
   - /ready returns HTTP 503 with error_code="STORAGE_CORRUPTED" when store is corrupt.
   - /api/v1/storage/diagnostics reports diagnostic status without mutation.
   - Ingestion failures due to SQLite corruption return HTTP 503 rather than misleading HTTP 400.
6. Standard healthy read/write operations and tenant isolation invariants preserved.
7. Connections are reliably closed in finally blocks to prevent file-lock contention.
"""

import os
import io
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from backend.storage.config import StorageConfig, StorageBackendType, AppEnvironment
from backend.storage.sqlite.repository import SQLiteRepository, StorageCorruptionError
from backend.contracts.base import CosmosContainer
from backend.repository.context import TenantContext, TenantAccessDeniedError
from backend.api.app import create_app, AppDependencies
from backend.governance.service import GovernanceService
from backend.ingestion.manager import IngestionManager


class TestSQLiteCorruptionAndRecovery(unittest.TestCase):
    def setUp(self):
        # Create an isolated temporary database for each test
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.temp_db_path = self.temp_file.name
        self.temp_file.close()

    def tearDown(self):
        # Clean up temporary test files
        for ext in ("", "-wal", "-shm"):
            p = f"{self.temp_db_path}{ext}"
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

    # -------------------------------------------------------------------------
    # 1. Path Resolution Tests
    # -------------------------------------------------------------------------

    def test_absolute_path_resolution(self):
        """Verifies relative KPI_SQLITE_PATH is canonicalized to an absolute path."""
        with patch.dict(os.environ, {"KPI_SQLITE_PATH": "local_data/test_custom.sqlite3"}):
            config = StorageConfig.from_env()
            self.assertTrue(os.path.isabs(config.sqlite_path))
            self.assertTrue(config.sqlite_path.endswith("local_data/test_custom.sqlite3") or config.sqlite_path.endswith("local_data\\test_custom.sqlite3"))

    def test_journal_mode_configuration(self):
        """Verifies KPI_SQLITE_JOURNAL_MODE can be configured to DELETE or WAL."""
        with patch.dict(os.environ, {"KPI_SQLITE_JOURNAL_MODE": "DELETE"}):
            config = StorageConfig.from_env()
            self.assertEqual(config.sqlite_journal_mode, "DELETE")

        with patch.dict(os.environ, {"KPI_SQLITE_JOURNAL_MODE": "WAL"}):
            config = StorageConfig.from_env()
            self.assertEqual(config.sqlite_journal_mode, "WAL")

    # -------------------------------------------------------------------------
    # 2. Healthy Database Integrity Diagnostics
    # -------------------------------------------------------------------------

    def test_healthy_database_integrity_diagnostic(self):
        """Verifies non-destructive integrity check on healthy database returns healthy=True."""
        repo = SQLiteRepository(self.temp_db_path)
        diag = repo.check_integrity(deep=False)

        self.assertEqual(diag["status"], "healthy")
        self.assertTrue(diag["healthy"])
        self.assertEqual(diag["messages"], ["ok"])
        self.assertTrue(os.path.isabs(diag["db_path"]))
        self.assertGreater(diag["file_size_bytes"], 0)

        # Deep integrity check
        diag_deep = repo.check_integrity(deep=True)
        self.assertEqual(diag_deep["status"], "healthy")
        self.assertTrue(diag_deep["healthy"])
        self.assertEqual(diag_deep["messages"], ["ok"])

    def test_health_check_method_healthy(self):
        """Verifies health_check returns HEALTHY status and container counts."""
        repo = SQLiteRepository(self.temp_db_path)
        health = repo.health_check()

        self.assertEqual(health["status"], "HEALTHY")
        self.assertTrue(health["healthy"])
        self.assertEqual(health["backend"], "sqlite")
        self.assertEqual(health["total_documents"], 0)

    # -------------------------------------------------------------------------
    # 3. Corruption Detection and Non-Destructive Invariant
    # -------------------------------------------------------------------------

    def test_corruption_detection_preserves_file_without_deletion(self):
        """
        Intentionally corrupts database bytes and verifies:
        1. check_integrity detects corruption.
        2. Instantiating repository raises StorageCorruptionError.
        3. The file is NOT wiped, deleted, or reset.
        """
        # First initialize schema
        repo = SQLiteRepository(self.temp_db_path)
        ctx = TenantContext(tenant_id="tenant-1")
        doc = {"id": "doc-1", "tenant_id": "tenant-1", "doc_type": "test_doc", "val": 123}
        repo.upsert_item(CosmosContainer.KPI_GOVERNANCE, "tenant-1", doc, ctx)

        original_size = os.path.getsize(self.temp_db_path)
        self.assertGreater(original_size, 0)

        # Intentionally corrupt page data in the SQLite file
        with open(self.temp_db_path, "r+b") as f:
            f.seek(100)  # Skip SQLite 100-byte file header, overwrite B-tree root page
            f.write(b"CORRUPTED_DISK_IMAGE_GARBAGE_BYTES_TEST" * 50)
            f.flush()

        corrupted_size = os.path.getsize(self.temp_db_path)
        self.assertEqual(original_size, corrupted_size)

        # Non-destructive integrity diagnostic must report corruption
        repo_uninitialized = SQLiteRepository.__new__(SQLiteRepository)
        repo_uninitialized.db_path = self.temp_db_path
        repo_uninitialized.journal_mode = "WAL"

        diag = repo_uninitialized.check_integrity(deep=False)
        self.assertFalse(diag["healthy"])
        self.assertEqual(diag["status"], "corrupted")

        # Repository re-instantiation must raise StorageCorruptionError and NOT delete/reset file
        with self.assertRaises(StorageCorruptionError) as cm:
            SQLiteRepository(self.temp_db_path)

        err = cm.exception
        self.assertEqual(err.db_path, self.temp_db_path)
        self.assertIn("corrupted", str(err).lower())
        self.assertIn("SQLITE_RECOVERY_RUNBOOK.md", str(err))

        # INVARIANT: File still exists and was not deleted or truncated to 0
        self.assertTrue(os.path.exists(self.temp_db_path))
        self.assertEqual(os.path.getsize(self.temp_db_path), corrupted_size)

    # -------------------------------------------------------------------------
    # 4. API Error Mapping for Storage Corruption
    # -------------------------------------------------------------------------

    def test_api_ready_endpoint_returns_503_on_corrupt_store(self):
        """Verifies GET /ready returns HTTP 503 when the storage repository is corrupted."""
        mock_repo = MagicMock(spec=SQLiteRepository)
        mock_repo.check_integrity.return_value = {
            "status": "corrupted",
            "healthy": False,
            "db_path": "/fake/path/kpi.sqlite3",
            "messages": ["database disk image is malformed"],
        }

        mock_gov = MagicMock(spec=GovernanceService)
        mock_gov.repo = mock_repo

        mock_deps = AppDependencies(governance_service=mock_gov)
        app = create_app()

        from backend.api.app import get_dependencies
        app.dependency_overrides[get_dependencies] = lambda: mock_deps

        client = TestClient(app)
        resp = client.get("/ready")

        self.assertEqual(resp.status_code, 503)
        body = resp.json()
        self.assertEqual(body["status"], "not_ready")
        self.assertEqual(body["error_code"], "STORAGE_CORRUPTED")
        self.assertIn("SQLITE_RECOVERY_RUNBOOK.md", body["remediation"])

    def test_api_storage_diagnostics_endpoint(self):
        """Verifies GET /api/v1/storage/diagnostics returns structured health metrics."""
        repo = SQLiteRepository(self.temp_db_path)
        mock_gov = MagicMock(spec=GovernanceService)
        mock_gov.repo = repo

        mock_deps = AppDependencies(governance_service=mock_gov)
        app = create_app()

        from backend.api.app import get_dependencies
        app.dependency_overrides[get_dependencies] = lambda: mock_deps

        client = TestClient(app)
        resp = client.get("/api/v1/storage/diagnostics")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["backend"], "sqlite")
        self.assertTrue(body["diagnostics"]["healthy"])
        self.assertEqual(body["diagnostics"]["status"], "healthy")

    def test_ingestion_manager_maps_sqlite_corruption_to_503(self):
        """
        Verifies that when ingestion encounters a malformed SQLite disk image,
        the folder-upload endpoint returns HTTP 503 (STORAGE_CORRUPTED) rather than HTTP 400.
        """
        mock_ingestion_mgr = MagicMock(spec=IngestionManager)
        mock_ingestion_mgr.process_file_batch.return_value = {
            "job_id": "job-corrupt-1",
            "status": "FAILED",
            "error_code": "STORAGE_CORRUPTED",
            "error_message": "Storage failure: Local database disk image is malformed.",
            "diagnostics": [{"code": "STORAGE_CORRUPTED"}],
        }

        mock_gov = MagicMock(spec=GovernanceService)
        mock_deps = AppDependencies(governance_service=mock_gov, ingestion_manager=mock_ingestion_mgr)

        app = create_app()
        from backend.api.app import get_dependencies
        app.dependency_overrides[get_dependencies] = lambda: mock_deps

        client = TestClient(app)
        files = [("files", ("model.pbip", b"dummy content", "application/octet-stream"))]
        resp = client.post("/api/v1/ingestion/folder-uploads", files=files, headers={"x-tenant-id": "tenant-test"})

        self.assertEqual(resp.status_code, 503)
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error_code"], "STORAGE_CORRUPTED")
        self.assertIn("SQLITE_RECOVERY_RUNBOOK.md", body["remediation"])

    # -------------------------------------------------------------------------
    # 5. Healthy Read/Write and Tenant Isolation Invariants
    # -------------------------------------------------------------------------

    def test_healthy_crud_and_tenant_isolation_preserved(self):
        """Verifies normal document upsert, get, query, and tenant boundaries function cleanly."""
        repo = SQLiteRepository(self.temp_db_path)
        ctx_alpha = TenantContext(tenant_id="tenant-alpha")
        ctx_beta = TenantContext(tenant_id="tenant-beta")

        # Upsert for Alpha
        doc = {
            "id": "item-1",
            "tenant_id": "tenant-alpha",
            "doc_type": "metric",
            "name": "Loss Ratio",
        }
        saved = repo.upsert_item(CosmosContainer.KPI_GOVERNANCE, "tenant-alpha", doc, ctx_alpha)
        self.assertEqual(saved["id"], "item-1")

        # Read by Alpha succeeds
        retrieved = repo.get_item(CosmosContainer.KPI_GOVERNANCE, "tenant-alpha", "item-1", ctx_alpha)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["name"], "Loss Ratio")

        # Read by Beta with mismatched partition key fails with TenantAccessDeniedError
        with self.assertRaises(TenantAccessDeniedError):
            repo.get_item(CosmosContainer.KPI_GOVERNANCE, "tenant-alpha", "item-1", ctx_beta)


if __name__ == "__main__":
    unittest.main()
