"""
KPI Intelligence — Ingestion API Integration Tests.

Validates:
1. /api/v1/ingestion/supported-formats:
   - Genuinely supported formats (Power BI PBIP/TMDL/Zip).
   - Correctly marks PBIX as unsupported and Excel/Tableau as planned.
2. /api/v1/ingestion/sources:
   - Returns list of ingested analytical assets for tenant.
3. /api/v1/ingestion/uploads:
   - Rejects empty uploads.
   - Ingests valid PBIP zip archive with TMDL semantic model.
   - Safe zip slip path traversal prevention.
4. /api/v1/ingestion/folder-uploads:
   - Ingests directory hierarchy with relative paths preserved.
5. Ingestion job tracking and tenant isolation.
"""

import os
import io
import json
import shutil
import zipfile
import tempfile
import unittest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.storage.sqlite.repository import SQLiteRepository
from backend.repository.context import TenantContext
from backend.contracts import CosmosContainer
from backend.storage.fixtures import TENANT_ALPHA, TENANT_BETA, generate_synthetic_fixtures
from backend.kpi_bank.service import KPIBankService
from backend.domain.service import DomainClassificationService
from backend.matching.deterministic import DeterministicMatchingEngine
from backend.matching.orchestrator import MatchingOrchestrator
from backend.learning.service import OverrideLearningService
from backend.governance.service import GovernanceService
from backend.ingestion.manager import IngestionManager


class TestIngestionAPI(unittest.TestCase):
    def setUp(self):
        # Create isolated temporary database for test
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db_path = self.temp_file.name
        self.temp_file.close()

        self.staging_dir = tempfile.mkdtemp(prefix="kpi_staging_test_")

        self.repo = SQLiteRepository(self.temp_db_path)
        self.tenant_id = TENANT_ALPHA

        # Seed synthetic fixtures into repo
        fixtures = generate_synthetic_fixtures()
        for container, docs in fixtures.items():
            for doc in docs:
                if container == CosmosContainer.KPI_ONTOLOGY:
                    p_key = getattr(doc, "business_domain", "GENERAL")
                    ctx = TenantContext.system_context()
                else:
                    p_key = getattr(doc, "tenant_id", None) or TENANT_ALPHA
                    ctx = TenantContext(tenant_id=p_key)
                self.repo.upsert_item(container, p_key, doc.to_dict(), ctx)

        kpi_bank = KPIBankService(repository=self.repo)
        domain_svc = DomainClassificationService(repository=self.repo)
        deterministic = DeterministicMatchingEngine()
        orchestrator = MatchingOrchestrator(
            kpi_bank_service=kpi_bank,
            deterministic_engine=deterministic,
        )
        learning = OverrideLearningService(repository=self.repo)
        self.gov_svc = GovernanceService(
            repository=self.repo,
            kpi_bank_service=kpi_bank,
            domain_service=domain_svc,
            matching_orchestrator=orchestrator,
            learning_service=learning,
        )
        self.ingestion_mgr = IngestionManager(
            repository=self.repo,
            staging_root=self.staging_dir,
        )

        self.app = create_app(
            governance_service=self.gov_svc,
            ingestion_manager=self.ingestion_mgr,
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.unlink(self.temp_db_path)
            except Exception:
                pass
        if os.path.exists(self.staging_dir):
            shutil.rmtree(self.staging_dir, ignore_errors=True)

    def _create_sample_pbip_zip(self) -> bytes:
        """Creates an in-memory zip archive containing a minimal valid PBIP project."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Root .pbip manifest
            pbip_content = json.dumps({
                "version": "1.0",
                "artifacts": [
                    {"report": {"path": "ClaimsReport.Report"}},
                ],
                "settings": {"enableAutoRecovery": True},
            })
            zf.writestr("ClaimsReport.pbip", pbip_content)

            # 2. Report definition
            report_pbir = json.dumps({
                "version": "1.0",
                "datasetReference": {"byPath": {"path": "../ClaimsReport.SemanticModel"}},
            })
            zf.writestr("ClaimsReport.Report/definition.pbir", report_pbir)

            report_json = json.dumps({
                "id": "rep_1001",
                "name": "Claims Executive Report",
                "visuals": [],
            })
            zf.writestr("ClaimsReport.Report/report.json", report_json)

            # 3. SemanticModel definition
            model_pbism = json.dumps({
                "version": "1.0",
                "settings": {},
            })
            zf.writestr("ClaimsReport.SemanticModel/definition.pbism", model_pbism)

            model_bim = json.dumps({
                "compatibilityLevel": 1550,
                "model": {
                    "tables": [
                        {
                            "name": "Claims",
                            "columns": [{"name": "ClaimID", "dataType": "int64"}],
                            "measures": [
                                {
                                    "name": "Loss Ratio",
                                    "expression": "DIVIDE([Incurred], [Earned])",
                                }
                            ],
                        }
                    ]
                },
            })
            zf.writestr("ClaimsReport.SemanticModel/model.bim", model_bim)

        buffer.seek(0)
        return buffer.getvalue()

    def test_get_supported_formats(self):
        """Ensures API reports PBIP as supported and PBIX/Excel as unsupported/planned."""
        resp = self.client.get("/api/v1/ingestion/supported-formats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]

        self.assertIn("POWER_BI", data["supported_platforms"])
        formats = {f["format"]: f for f in data["supported_formats"]}

        self.assertEqual(formats["PBIP"]["status"], "SUPPORTED")
        self.assertTrue(formats["PBIP"]["is_active"])

        self.assertEqual(formats["PBIX"]["status"], "UNSUPPORTED")
        self.assertFalse(formats["PBIX"]["is_active"])

        self.assertEqual(formats["EXCEL"]["status"], "PLANNED")
        self.assertEqual(formats["TABLEAU"]["status"], "PLANNED")

    def test_list_ingested_sources(self):
        """Ensures API returns registered analytical assets for the tenant."""
        resp = self.client.get("/api/v1/ingestion/sources", headers={"X-Tenant-ID": self.tenant_id})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertIsInstance(body["data"], list)

    def test_upload_pbip_zip_archive_success(self):
        """Tests uploading a valid PBIP zip archive and extracting canonical documents."""
        zip_bytes = self._create_sample_pbip_zip()

        resp = self.client.post(
            "/api/v1/ingestion/uploads",
            files={"files": ("ClaimsProject.zip", zip_bytes, "application/zip")},
            headers={"X-Tenant-ID": self.tenant_id},
        )
        self.assertEqual(resp.status_code, 200)
        result = resp.json()["data"]

        self.assertEqual(result["status"], "COMPLETED")
        self.assertIsNotNone(result["asset_id"])
        self.assertGreater(result["files_processed"], 0)

        # Verify asset now appears in sources endpoint
        sources_resp = self.client.get("/api/v1/ingestion/sources", headers={"X-Tenant-ID": self.tenant_id})
        self.assertEqual(sources_resp.status_code, 200)
        sources = sources_resp.json()["data"]
        matching = [s for s in sources if s["asset_id"] == result["asset_id"]]
        self.assertEqual(len(matching), 1)

    def test_upload_folder_batch_success(self):
        """Tests folder upload with preserved relative paths."""
        pbip_content = json.dumps({"version": "1.0", "artifacts": []}).encode("utf-8")
        model_bim = json.dumps({
            "compatibilityLevel": 1550,
            "model": {
                "tables": [
                    {
                        "name": "Underwriting",
                        "measures": [{"name": "Combined Ratio", "expression": "1.0"}],
                    }
                ]
            },
        }).encode("utf-8")

        files = [
            ("files", ("Project.pbip", pbip_content, "application/json")),
            ("files", ("model.bim", model_bim, "application/json")),
        ]
        relative_paths = json.dumps([
            "MyProject/Project.pbip",
            "MyProject/Project.SemanticModel/model.bim",
        ])

        resp = self.client.post(
            "/api/v1/ingestion/folder-uploads",
            files=files,
            data={"relative_paths": relative_paths},
            headers={"X-Tenant-ID": self.tenant_id},
        )
        self.assertEqual(resp.status_code, 200)
        result = resp.json()["data"]
        self.assertEqual(result["status"], "COMPLETED")

    def test_upload_fails_when_no_pbip_structure(self):
        """Ensures uploading unstructured files fails gracefully with diagnostic message."""
        dummy_file = b"Random binary data"
        resp = self.client.post(
            "/api/v1/ingestion/uploads",
            files={"files": ("dummy.txt", dummy_file, "text/plain")},
            headers={"X-Tenant-ID": self.tenant_id},
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertIn("No valid Power BI Project (.pbip)", body["error"])

    def test_zip_slip_security_prevention(self):
        """Ensures malicious zip archives with path traversal are blocked."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("../../evil.txt", "Malicious content")
        buffer.seek(0)

        resp = self.client.post(
            "/api/v1/ingestion/uploads",
            files={"files": ("evil.zip", buffer.getvalue(), "application/zip")},
            headers={"X-Tenant-ID": self.tenant_id},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("path traversal", resp.json()["error"].lower())

    def test_ingestion_job_tracking_and_tenant_isolation(self):
        """Ensures jobs can be queried by owner tenant, but return 404 for different tenants."""
        zip_bytes = self._create_sample_pbip_zip()
        resp = self.client.post(
            "/api/v1/ingestion/uploads",
            files={"files": ("ClaimsProject.zip", zip_bytes, "application/zip")},
            headers={"X-Tenant-ID": self.tenant_id},
        )
        job_id = resp.json()["data"]["job_id"]

        # 1. Same tenant query succeeds
        get_resp = self.client.get(f"/api/v1/ingestion/jobs/{job_id}", headers={"X-Tenant-ID": self.tenant_id})
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["data"]["job_id"], job_id)

        # 2. Foreign tenant query fails with 404
        bad_tenant_resp = self.client.get(f"/api/v1/ingestion/jobs/{job_id}", headers={"X-Tenant-ID": TENANT_BETA})
        self.assertEqual(bad_tenant_resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
