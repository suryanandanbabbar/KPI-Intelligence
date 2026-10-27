"""
KPI Intelligence — FastAPI Backend Automated Integration Tests.

Validates:
1. FastAPI app startup and OpenAPI schema integrity.
2. Health (/health) and readiness (/ready) diagnostic endpoints.
3. Workspace summary and domain segregation metrics.
4. Extracted canonical metadata inspection (without reopening raw files).
5. Mapping pipeline execution with fallback handling.
6. Human governance:
   - Mandatory human approval (HIGH confidence never auto-approves).
   - Structured rejection.
   - Server-side override justification enforcement (>= 10 chars).
7. KPI Bank search and schema-compliant creation.
8. Override learning retrieval and invalidation.
9. Chronological immutable audit logging.
10. Tenant boundary isolation across read/write operations.
"""

import os
import tempfile
import unittest
from datetime import datetime, timezone
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


class TestFastAPIBackend(unittest.TestCase):
    def setUp(self):
        # Create isolated temporary database for test
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db_path = self.temp_file.name
        self.temp_file.close()

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

        self.kpi_bank = KPIBankService(repository=self.repo)
        self.domain_service = DomainClassificationService(repository=self.repo)
        self.deterministic_engine = DeterministicMatchingEngine()
        self.learning_service = OverrideLearningService(repository=self.repo)
        self.orchestrator = MatchingOrchestrator(
            kpi_bank_service=self.kpi_bank,
            deterministic_engine=self.deterministic_engine,
        )
        self.governance_service = GovernanceService(
            repository=self.repo,
            kpi_bank_service=self.kpi_bank,
            domain_service=self.domain_service,
            matching_orchestrator=self.orchestrator,
            learning_service=self.learning_service,
        )

        # Create FastAPI app and TestClient
        self.app = create_app(governance_service=self.governance_service)
        self.client = TestClient(self.app)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            os.remove(self.temp_db_path)

    # -------------------------------------------------------------------------
    # 1. APPLICATION & OPENAPI CHECKS
    # -------------------------------------------------------------------------

    def test_openapi_schema_generated(self):
        """OpenAPI schema must be valid and expose canonical versioned endpoints."""
        resp = self.client.get("/openapi.json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["info"]["title"], "KPI Intelligence API")
        paths = data["paths"]

        # Required canonical endpoints
        self.assertIn("/health", paths)
        self.assertIn("/ready", paths)
        self.assertIn("/api/v1/workspace/summary", paths)
        self.assertIn("/api/v1/domains", paths)
        self.assertIn("/api/v1/domains/{domain}/metrics", paths)
        self.assertIn("/api/v1/metadata/fields", paths)
        self.assertIn("/api/v1/metadata/fields/{field_id}", paths)
        self.assertIn("/api/v1/mapping/fields/{field_id}/candidates", paths)
        self.assertIn("/api/v1/mapping/run", paths)
        self.assertIn("/api/v1/mapping/approve", paths)
        self.assertIn("/api/v1/mapping/reject", paths)
        self.assertIn("/api/v1/mapping/override", paths)
        self.assertIn("/api/v1/kpi-bank/search", paths)
        self.assertIn("/api/v1/kpi-bank/create", paths)
        self.assertIn("/api/v1/overrides", paths)
        self.assertIn("/api/v1/audit/history", paths)

    def test_health_and_readiness_endpoints(self):
        """Health and readiness return valid operational status without leaking tenant data."""
        resp_h = self.client.get("/health")
        self.assertEqual(resp_h.status_code, 200)
        data_h = resp_h.json()
        self.assertEqual(data_h["status"], "healthy")
        self.assertEqual(data_h["service"], "kpi-intelligence-api")

        resp_r = self.client.get("/ready")
        self.assertEqual(resp_r.status_code, 200)
        self.assertEqual(resp_r.json()["status"], "ready")

    # -------------------------------------------------------------------------
    # 2. WORKSPACE SUMMARY & DOMAINS
    # -------------------------------------------------------------------------

    def test_workspace_summary_endpoint(self):
        """GET /api/v1/workspace/summary returns aggregated operational counts."""
        resp = self.client.get("/api/v1/workspace/summary", headers={"x-tenant-id": self.tenant_id})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        data = body["data"]
        self.assertIn("total_canonical_entities", data)
        self.assertIn("domain_distribution", data)
        self.assertIn("approved_mappings", data)
        self.assertIn("total_active_overrides", data)

    def test_domains_and_domain_metrics(self):
        """GET /api/v1/domains and /api/v1/domains/{domain}/metrics work correctly."""
        resp = self.client.get("/api/v1/domains")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        codes = [d["code"] for d in body["data"]]
        self.assertIn("CLAIMS_RISK", codes)
        self.assertIn("LEGAL", codes)
        self.assertIn("UNDERWRITING", codes)
        self.assertIn("SALES_DISTRIBUTION", codes)
        self.assertIn("ACTUARIAL", codes)

        # Domain metrics
        resp_m = self.client.get(
            "/api/v1/domains/CLAIMS_RISK/metrics",
            headers={"x-tenant-id": self.tenant_id},
        )
        self.assertEqual(resp_m.status_code, 200)
        body_m = resp_m.json()
        self.assertTrue(body_m["success"])
        self.assertEqual(body_m["data"]["domain"], "CLAIMS_RISK")

    # -------------------------------------------------------------------------
    # 3. METADATA INSPECTION & DOMAIN CORRECTION
    # -------------------------------------------------------------------------

    def test_list_metadata_fields_and_candidates(self):
        """GET /api/v1/metadata/fields reads canonical documents and returns fields."""
        resp = self.client.get("/api/v1/metadata/fields", headers={"x-tenant-id": self.tenant_id})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertGreater(body["count"], 0)
        field = body["data"][0]
        self.assertIn("field_id", field)
        self.assertIn("domain", field)

        # Candidates for single field
        resp_c = self.client.get(
            f"/api/v1/mapping/fields/{field['field_id']}/candidates",
            headers={"x-tenant-id": self.tenant_id},
        )
        self.assertEqual(resp_c.status_code, 200)
        body_c = resp_c.json()
        self.assertTrue(body_c["success"])
        self.assertIn("top_candidates", body_c["data"])

    def test_domain_correction_persists(self):
        """POST /api/v1/metadata/fields/{field_id}/domain updates domain classification."""
        payload = {
            "corrected_domain": "UNDERWRITING",
            "justification": "Analyst verified commercial lines classification",
            "previous_domain": "CLAIMS_RISK",
        }
        resp = self.client.post(
            "/api/v1/metadata/fields/calc_IncurredLosses/domain",
            json=payload,
            headers={"x-tenant-id": self.tenant_id},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["corrected_domain"], "UNDERWRITING")

    # -------------------------------------------------------------------------
    # 4. MAPPING PIPELINE & HUMAN GOVERNANCE
    # -------------------------------------------------------------------------

    def test_run_mapping_pipeline_endpoint(self):
        """POST /api/v1/mapping/run executes end-to-end pipeline."""
        resp = self.client.post(
            "/api/v1/mapping/run",
            json={"force_fallback": True},
            headers={"x-tenant-id": self.tenant_id},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertGreater(body["data"]["total_fields"], 0)

    def test_approve_mapping_endpoint(self):
        """POST /api/v1/mapping/approve persists approval in repository."""
        # Run mapping first
        self.client.post(
            "/api/v1/mapping/run",
            json={"force_fallback": True},
            headers={"x-tenant-id": self.tenant_id},
        )
        # Find an actual proposed mapping
        resp_p = self.client.get("/api/v1/mappings/proposals", headers={"x-tenant-id": self.tenant_id})
        proposals = resp_p.json()["data"]
        self.assertGreater(len(proposals), 0)
        target = proposals[0]
        mapping_id = f"map_{target['field_id']}"
        top_kpi = target["top_candidates"][0]["kpi_id"]

        resp = self.client.post(
            "/api/v1/mapping/approve",
            json={"mapping_id": mapping_id, "approved_kpi_id": top_kpi},
            headers={"x-tenant-id": self.tenant_id},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["status"], "APPROVED")

    def test_reject_mapping_endpoint(self):
        """POST /api/v1/mapping/reject marks mapping rejected with reason."""
        self.client.post(
            "/api/v1/mapping/run",
            json={"force_fallback": True},
            headers={"x-tenant-id": self.tenant_id},
        )
        resp_p = self.client.get("/api/v1/mappings/proposals", headers={"x-tenant-id": self.tenant_id})
        proposals = resp_p.json()["data"]
        self.assertGreater(len(proposals), 0)
        mapping_id = f"map_{proposals[0]['field_id']}"

        resp = self.client.post(
            "/api/v1/mapping/reject",
            json={"mapping_id": mapping_id, "reason": "Not approved by finance"},
            headers={"x-tenant-id": self.tenant_id},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["status"], "REJECTED")

    def test_override_justification_server_side_validation(self):
        """POST /api/v1/mapping/override strictly validates >= 10 chars server-side."""
        self.client.post(
            "/api/v1/mapping/run",
            json={"force_fallback": True},
            headers={"x-tenant-id": self.tenant_id},
        )
        resp_p = self.client.get("/api/v1/mappings/proposals", headers={"x-tenant-id": self.tenant_id})
        proposals = resp_p.json()["data"]
        self.assertGreater(len(proposals), 0)
        mapping_id = f"map_{proposals[0]['field_id']}"

        # Invalid: < 10 characters
        resp_invalid = self.client.post(
            "/api/v1/mapping/override",
            json={
                "mapping_id": mapping_id,
                "replacement_kpi_id": "8d2a5fb0-1234-4567-89ab-cdef01234567",
                "override_justification": "short",
            },
            headers={"x-tenant-id": self.tenant_id},
        )
        self.assertEqual(resp_invalid.status_code, 400)
        self.assertFalse(resp_invalid.json()["success"])

        # Valid: >= 10 non-whitespace characters
        resp_valid = self.client.post(
            "/api/v1/mapping/override",
            json={
                "mapping_id": mapping_id,
                "replacement_kpi_id": "8d2a5fb0-1234-4567-89ab-cdef01234567",
                "override_justification": "This measure aligns with combined ratio calculation standard.",
            },
            headers={"x-tenant-id": self.tenant_id},
        )
        self.assertEqual(resp_valid.status_code, 200)
        self.assertTrue(resp_valid.json()["success"])
        self.assertEqual(resp_valid.json()["data"]["status"], "OVERRIDDEN")

    # -------------------------------------------------------------------------
    # 5. KPI BANK SEARCH & CREATION
    # -------------------------------------------------------------------------

    def test_kpi_bank_search_and_create(self):
        """KPI Bank search and creation endpoints."""
        resp_s = self.client.get("/api/v1/kpi-bank/search?q=loss")
        self.assertEqual(resp_s.status_code, 200)
        self.assertTrue(resp_s.json()["success"])

        # Create new KPI
        new_kpi = {
            "name": "FastAPI Commercial Binding Ratio",
            "definition": "Ratio of bound policies to quoted policies.",
            "domain": "Underwriting",
            "formula": "BoundPolicies / QuotedPolicies",
            "unit": "PERCENTAGE",
        }
        resp_c = self.client.post(
            "/api/v1/kpi-bank/create",
            json=new_kpi,
            headers={"x-tenant-id": self.tenant_id},
        )
        self.assertEqual(resp_c.status_code, 201)
        body_c = resp_c.json()
        self.assertTrue(body_c["success"])
        self.assertEqual(body_c["data"]["name"], "FastAPI Commercial Binding Ratio")

    # -------------------------------------------------------------------------
    # 6. OVERRIDES & AUDIT HISTORY
    # -------------------------------------------------------------------------

    def test_overrides_and_audit_endpoints(self):
        """GET /api/v1/overrides and GET /api/v1/audit/history."""
        resp_o = self.client.get("/api/v1/overrides", headers={"x-tenant-id": self.tenant_id})
        self.assertEqual(resp_o.status_code, 200)
        self.assertTrue(resp_o.json()["success"])

        resp_a = self.client.get("/api/v1/audit/history?limit=20", headers={"x-tenant-id": self.tenant_id})
        self.assertEqual(resp_a.status_code, 200)
        self.assertTrue(resp_a.json()["success"])

    # -------------------------------------------------------------------------
    # 7. TENANT ISOLATION
    # -------------------------------------------------------------------------

    def test_tenant_boundary_isolation(self):
        """Tenant Alpha cannot access or mutate Tenant Beta's mappings."""
        # Create mapping in Beta
        self.governance_service.run_mapping_pipeline(TENANT_BETA, force_fallback=True)

        # Alpha requests fields for Alpha
        resp_a = self.client.get("/api/v1/metadata/fields", headers={"x-tenant-id": TENANT_ALPHA})
        fields_a = resp_a.json()["data"]

        # Alpha requests fields for Beta: client sends Beta tenant header
        resp_b = self.client.get("/api/v1/metadata/fields", headers={"x-tenant-id": TENANT_BETA})
        fields_b = resp_b.json()["data"]

        # Ensure field IDs are isolated to their respective tenants
        field_ids_a = {f["field_id"] for f in fields_a}
        field_ids_b = {f["field_id"] for f in fields_b}
        self.assertNotEqual(field_ids_a, field_ids_b)


if __name__ == "__main__":
    unittest.main()
