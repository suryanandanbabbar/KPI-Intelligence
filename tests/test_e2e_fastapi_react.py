"""
KPI Intelligence — End-to-End Smoke Test for FastAPI Backend + React Frontend.

Verifies:
1. Static asset serving for the built React bundle (HTML, JS, CSS).
2. React frontend API integration:
   - Diagnostic health checks.
   - Read workflow: workspace summary, segregated domains, extracted canonical metadata fields.
   - Write governance workflow: pipeline execution, candidate approval, KPI creation, manual override with justification.
   - Audit trail reflection.
3. Isolated test repository and database: `local_data/kpi_intelligence.sqlite3` remains pristine and untouched.
"""

import os
import re
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


class TestE2EFastAPIReact(unittest.TestCase):
    def setUp(self):
        # Create an isolated temporary SQLite database
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

        self.app = create_app(governance_service=self.governance_service)
        self.client = TestClient(self.app)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            os.remove(self.temp_db_path)

    def test_e2e_react_serving_and_workflows(self):
        """End-to-end smoke test exercising React asset delivery, read workflow, and write governance."""
        # 1. Verify React Production HTML and Assets Delivery
        resp_root = self.client.get("/")
        self.assertEqual(resp_root.status_code, 200)
        self.assertIn("text/html", resp_root.headers.get("content-type", ""))
        self.assertIn('<div id="root"></div>', resp_root.text)

        # Extract JS asset path from index.html and verify asset serving
        js_matches = re.findall(r'src="(/assets/[^"]+\.js)"', resp_root.text)
        self.assertGreater(len(js_matches), 0, "Built React JS bundle path must exist in HTML")
        js_asset_path = js_matches[0]
        resp_js = self.client.get(js_asset_path)
        self.assertEqual(resp_js.status_code, 200)
        self.assertGreater(len(resp_js.content), 1000)

        # 2. Diagnostics
        resp_health = self.client.get("/health")
        self.assertEqual(resp_health.status_code, 200)
        self.assertEqual(resp_health.json()["status"], "healthy")

        # 3. Read Workflow (Initial State)
        resp_summary = self.client.get("/api/v1/workspace/summary", headers={"x-tenant-id": self.tenant_id})
        self.assertEqual(resp_summary.status_code, 200)
        summary_data = resp_summary.json()["data"]
        self.assertGreater(summary_data["total_canonical_entities"], 0)

        resp_domains = self.client.get("/api/v1/domains")
        self.assertEqual(resp_domains.status_code, 200)
        self.assertGreater(len(resp_domains.json()["data"]), 0)

        resp_fields = self.client.get("/api/v1/metadata/fields", headers={"x-tenant-id": self.tenant_id})
        self.assertEqual(resp_fields.status_code, 200)
        fields = resp_fields.json()["data"]
        self.assertGreater(len(fields), 0)

        # 4. Write Governance Workflow
        # (a) Run mapping pipeline
        resp_run = self.client.post(
            "/api/v1/mapping/run",
            json={"force_fallback": True},
            headers={"x-tenant-id": self.tenant_id},
        )
        self.assertEqual(resp_run.status_code, 200)
        self.assertTrue(resp_run.json()["success"])

        # (b) Retrieve proposals awaiting review
        resp_proposals = self.client.get("/api/v1/mappings/proposals", headers={"x-tenant-id": self.tenant_id})
        self.assertEqual(resp_proposals.status_code, 200)
        proposals = resp_proposals.json()["data"]
        self.assertGreater(len(proposals), 0)

        target_field = proposals[0]
        mapping_id = f"map_{target_field['field_id']}"
        top_kpi_id = target_field["top_candidates"][0]["kpi_id"]

        # (c) Human approval of proposal
        resp_approve = self.client.post(
            "/api/v1/mapping/approve",
            json={"mapping_id": mapping_id, "approved_kpi_id": top_kpi_id},
            headers={"x-tenant-id": self.tenant_id},
        )
        self.assertEqual(resp_approve.status_code, 200)
        self.assertEqual(resp_approve.json()["data"]["status"], "APPROVED")

        # (d) Create a new governed KPI in the KPI Bank
        new_kpi_payload = {
            "name": "E2E Governed Commercial Ratio",
            "definition": "Ratio of commercial underwriting gross losses to earned premiums.",
            "domain": "Underwriting",
            "formula": "CommercialLosses / CommercialEarnedPremium",
            "unit": "PERCENTAGE",
        }
        resp_kpi = self.client.post(
            "/api/v1/kpi-bank/create",
            json=new_kpi_payload,
            headers={"x-tenant-id": self.tenant_id},
        )
        self.assertEqual(resp_kpi.status_code, 201)
        created_kpi = resp_kpi.json()["data"]
        created_kpi_id = created_kpi["id"]

        # (e) Override another proposal with created KPI (with valid >=10 char justification)
        if len(proposals) > 1:
            second_target = proposals[1]
            second_mapping_id = f"map_{second_target['field_id']}"
            resp_override = self.client.post(
                "/api/v1/mapping/override",
                json={
                    "mapping_id": second_mapping_id,
                    "replacement_kpi_id": created_kpi_id,
                    "override_justification": "E2E Governance Test: Remapping to newly created commercial standard KPI.",
                },
                headers={"x-tenant-id": self.tenant_id},
            )
            self.assertEqual(resp_override.status_code, 200)
            self.assertEqual(resp_override.json()["data"]["status"], "OVERRIDDEN")

        # 5. Verify Audit History reflects the human governance decisions
        resp_audit = self.client.get("/api/v1/audit/history?limit=10", headers={"x-tenant-id": self.tenant_id})
        self.assertEqual(resp_audit.status_code, 200)
        audit_events = resp_audit.json()["data"]
        event_types = [e["event_type"] for e in audit_events]
        self.assertIn("MAPPING_APPROVED", event_types)

    def test_domain_segregation_ui_controls_not_duplicated_and_cards_refined(self):
        """
        Verifies that:
        1. The Domain Segregation view does not duplicate page header controls (no page-intro-header).
        2. Top-bar in application shell remains the single global owner of actions and title.
        3. Domain cards use display name as primary heading and canonical code as secondary metadata.
        4. Key signals density control (+N more button) is implemented.
        """
        app_jsx_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "src", "App.jsx"))
        with open(app_jsx_path, "r", encoding="utf-8") as f:
            app_code = f.read()

        # 1. No duplicated header controls
        self.assertNotIn("page-intro-header", app_code, "page-intro-header must be removed to avoid duplicating top-bar")
        self.assertIn("top-bar", app_code)
        self.assertIn("Run Mapping Pipeline", app_code)

        # 2. Refined Domain Card Structure
        self.assertIn("domain-dashboard-card", app_code)
        self.assertIn("domain-card-name", app_code)
        self.assertIn("domain-card-code-secondary", app_code)
        self.assertIn("domain-metric-row", app_code)
        self.assertIn("domain-signals-section", app_code)
        self.assertIn("signal-chip-more-btn", app_code)
        self.assertIn("toggleDomainSignals", app_code)
        self.assertIn("Strict Domain Boundary", app_code)
        self.assertIn("View Fields →", app_code)

        # 3. CSS checks for card consistency and tokens
        css_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "styles.css"))
        with open(css_path, "r", encoding="utf-8") as f:
            css_code = f.read()

        self.assertIn(".domain-card-code-secondary", css_code)
        self.assertIn(".signal-chip-more-btn", css_code)
        self.assertIn(".domain-dashboard-card", css_code)
        self.assertIn(".domain-cards-grid", css_code)


if __name__ == "__main__":
    unittest.main()
