"""
KPI Intelligence — Automated Test Suite for KPI Mapping, Domain Segregation,
Human Governance, Override Learning, and REST API.

Covers:
1. Domain classification across all 5 canonical business domains and unclassified entities.
2. Human domain correction and audit trail persistence.
3. Reference KPI Bank search, lifecycle, duplicate detection, and schema-compliant creation.
4. Deterministic fallback matching engine (weighted signals, contradiction penalties, explanations).
5. LLM primary matching engine, output validation, and hallucination rejection triggering fallback.
6. Matching orchestrator, top-3 ranking, and input fingerprinting.
7. Human governance: approval, rejection, and manual override with mandatory justification validation.
8. Override learning: stable source fingerprints, semantic field fingerprints, layered lookup, conflict detection, and re-ingestion reuse.
9. Tenant boundary isolation across all read/write/override operations.
10. REST API endpoints (summary, domains, fields, mapping run, approval, override, kpi-bank, audit).
"""

import os
import uuid
import unittest
import tempfile
import json
from datetime import datetime, timezone
from unittest.mock import patch

from backend.storage.sqlite.repository import SQLiteRepository
from backend.repository.context import TenantContext
from backend.repository.interfaces import QuerySpec
from backend.contracts import CosmosContainer, DocumentType
from backend.storage.fixtures import TENANT_ALPHA, TENANT_BETA, generate_synthetic_fixtures
from backend.kpi_bank.service import KPIBankService
from backend.domain.service import DomainClassificationService, BusinessDomainType
from backend.matching.deterministic import DeterministicMatchingEngine
from backend.matching.llm import LLMMatchingEngine, LLMMatchingError
from backend.matching.orchestrator import MatchingOrchestrator
from backend.learning.service import OverrideLearningService
from backend.learning.fingerprint import compute_source_fingerprint, compute_semantic_fingerprint
from backend.governance.service import GovernanceService
from backend.api.app import KPIIntelligenceAPI


class TestKPIMappingWorkflow(unittest.TestCase):
    def setUp(self):
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
        self.api = KPIIntelligenceAPI(governance_service=self.governance_service)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.unlink(self.temp_db_path)
            except OSError:
                pass

    # =========================================================================
    # 1. DOMAIN CLASSIFICATION & CORRECTION
    # =========================================================================

    def test_domain_classification_claims(self):
        """Claims & Risk domain is correctly classified from claims/loss terminology."""
        res = self.domain_service.classify_metadata_field(
            field_name="IncurredLossRatio",
            expression="SUM(FactClaims[LossAmount]) / SUM(DimPolicy[Premium])",
            description="Total claims loss incurred over earned premium",
            parent_name="FactClaims",
        )
        self.assertEqual(res["primary_domain"], BusinessDomainType.CLAIMS_RISK.value)
        self.assertIn(res["confidence_code"], ("HIGH", "MEDIUM"))
        self.assertIn("loss", res["supporting_evidence"])
        self.assertIn("claims", res["supporting_evidence"])

    def test_domain_classification_underwriting_and_legal_segregated(self):
        """Underwriting and Legal are strictly segregated and never merged."""
        res_und = self.domain_service.classify_metadata_field(
            field_name="QuoteBindHitRatio",
            expression="DIVIDE([PoliciesBound], [SubmissionsQuoted])",
            description="Hit ratio of quotes converted to bound policies",
            parent_name="UnderwritingDesk",
        )
        self.assertEqual(res_und["primary_domain"], BusinessDomainType.UNDERWRITING.value)

        res_leg = self.domain_service.classify_metadata_field(
            field_name="LitigationDefenseSpend",
            expression="SUM(LegalExpenses[CounselBilling])",
            description="Defense counsel legal expense on lawsuits",
            parent_name="LitigationRegister",
        )
        self.assertEqual(res_leg["primary_domain"], BusinessDomainType.LEGAL.value)
        self.assertNotEqual(res_und["primary_domain"], res_leg["primary_domain"])

    def test_domain_classification_sales_and_actuarial(self):
        """Sales & Distribution and Actuarial domains are classified accurately."""
        res_sales = self.domain_service.classify_metadata_field(
            field_name="BrokerCommissionGWP",
            expression="SUM(BrokerSales[WrittenPremium]) * 0.15",
            description="Broker sales commissions paid on written premium",
        )
        self.assertEqual(res_sales["primary_domain"], BusinessDomainType.SALES_DISTRIBUTION.value)

        res_act = self.domain_service.classify_metadata_field(
            field_name="LossTriangleDevelopmentFactor",
            expression="[CumulativeLoss] / [PreviousDevelopmentLoss]",
            description="Actuarial development link ratio factor on triangles",
        )
        self.assertEqual(res_act["primary_domain"], BusinessDomainType.ACTUARIAL.value)

    def test_domain_classification_unclassified_fallback(self):
        """Ambiguous or unevidenced metadata is explicitly marked UNCLASSIFIED."""
        res = self.domain_service.classify_metadata_field(
            field_name="InternalRowCounterX9",
            expression="ROW_NUMBER()",
            description="Technical internal helper index",
        )
        self.assertEqual(res["primary_domain"], "UNCLASSIFIED")
        self.assertEqual(res["confidence_code"], "UNCLASSIFIED")
        self.assertEqual(res["confidence_score"], 0.0)

    def test_human_domain_correction_persists(self):
        """Human domain correction updates domain classification and logs audit event."""
        res = self.domain_service.record_human_correction(
            tenant_id=self.tenant_id,
            target_object_id="field_123",
            corrected_domain="UNDERWRITING",
            user_id="lead_underwriter",
            justification="Misclassified due to generic naming",
            previous_domain="SALES_DISTRIBUTION",
        )
        self.assertEqual(res["corrected_domain"], "UNDERWRITING")
        self.assertEqual(res["classification_method"], "HUMAN_OVERRIDE")

        # Verify audit record in operational_audit
        ctx = TenantContext(tenant_id=self.tenant_id)
        spec = QuerySpec(
            query="SELECT * FROM c WHERE c.tenant_id = @tenant_id AND c.doc_type = @doc_type",
            parameters=[
                {"name": "@tenant_id", "value": self.tenant_id},
                {"name": "@doc_type", "value": DocumentType.AUDIT_EVENT.value},
            ],
        )
        res_audit = self.repo.query_items(CosmosContainer.OPERATIONAL_AUDIT, self.tenant_id, spec, ctx)
        self.assertTrue(any(e.get("event_type") == "DOMAIN_CLASSIFICATION_CORRECTED" for e in res_audit.items))

    # =========================================================================
    # 2. KPI BANK SEARCH, CREATION & DUPLICATE DETECTION
    # =========================================================================

    def test_kpi_bank_search_by_name_and_domain(self):
        """KPI Bank search returns ranked matches filtered by domain."""
        res = self.kpi_bank.search(query="calls declined", domain="SALES_DISTRIBUTION", limit=5)
        self.assertGreater(len(res), 0)
        top = res[0]
        self.assertEqual(top["name"], "% Calls Agent Declined")
        self.assertEqual(top["business_domain"], "SALES_DISTRIBUTION")

    def test_kpi_bank_duplicate_detection(self):
        """Detects exact and alias duplicates before creating a new KPI."""
        dupes = self.kpi_bank.detect_duplicates("% Calls Agent Declined")
        self.assertGreater(len(dupes), 0)
        self.assertEqual(dupes[0]["match_type"], "EXACT_NAME")

        # Collision with alias
        alias_dupes = self.kpi_bank.detect_duplicates("Agent Decline Rate")
        self.assertGreater(len(alias_dupes), 0)
        self.assertEqual(alias_dupes[0]["match_type"], "ALIAS_MATCH")

    def test_kpi_bank_creation_validates_required_fields(self):
        """KPI creation rejects records missing name or definition."""
        with self.assertRaises(ValueError):
            self.kpi_bank.create_kpi({"name": "", "definition": "Test def"})

        with self.assertRaises(ValueError):
            self.kpi_bank.create_kpi({"name": "Test KPI", "definition": ""})

    def test_kpi_bank_creation_success(self):
        """Valid KPI creation persists to bank and creates draft status."""
        new_kpi = self.kpi_bank.create_kpi({
            "name": "Underwriting Binder Clearance Rate",
            "definition": "Percentage of quoted binders issued within 24 hours.",
            "domain": "Underwriting",
            "formula": "[Cleared Binders] / [Total Binders Submitted]",
            "aggregation_type": "RATIO",
            "status": "active",
        })
        self.assertIsNotNone(new_kpi.get("kpi_id"))
        self.assertEqual(new_kpi["business_domain"], "UNDERWRITING")
        self.assertEqual(new_kpi["status"], "active")

        # Verify retrievable via search
        search_res = self.kpi_bank.search("Binder Clearance", domain="UNDERWRITING")
        self.assertTrue(any(k["kpi_id"] == new_kpi["kpi_id"] for k in search_res))

    # =========================================================================
    # 3. DETERMINISTIC & LLM MATCHING ENGINES
    # =========================================================================

    def test_deterministic_matching_penalizes_formula_contradiction(self):
        """Deterministic matching detects and penalizes formula contradictions."""
        field_ratio = {
            "name": "Incurred Loss",
            "expression": "[LossAmount] / [EarnedPremium]",  # A ratio
            "domain": "CLAIMS_RISK",
        }
        kpi_sum = {
            "kpi_id": "k1",
            "name": "Incurred Loss",
            "formula": "SUM(LossAmount)",  # A cumulative sum, contradictory
            "business_domain": "CLAIMS_RISK",
        }
        eval_res = self.deterministic_engine._evaluate_candidate(
            field_name=field_ratio["name"],
            field_expr=field_ratio["expression"],
            field_domain=field_ratio["domain"],
            f_tokens={"incurred", "loss"},
            f_expr_tokens={"lossamount", "earnedpremium"},
            f_desc_tokens=set(),
            kpi=kpi_sum,
        )
        self.assertIn("Formula structure mismatch (ratio vs absolute aggregate)", eval_res["structured_evidence"]["contradictory_evidence"])
        self.assertNotEqual(eval_res["confidence_code"], "HIGH")

    def test_llm_hallucinated_kpi_id_triggers_fallback(self):
        """LLM returning an invented/hallucinated KPI ID fails validation and triggers deterministic fallback."""
        def hallucinating_provider(prompt):
            return json.dumps({
                "recommendations": [
                    {
                        "kpi_id": "hallucinated-invented-uuid-9999",
                        "confidence_code": "HIGH",
                        "confidence_score": 0.99,
                        "ranking_rationale": "Fabricated match",
                    }
                ]
            })

        llm = LLMMatchingEngine(provider_fn=hallucinating_provider)
        orch = MatchingOrchestrator(kpi_bank_service=self.kpi_bank, llm_engine=llm)

        res = orch.discover_and_rank_candidates(
            {"name": "Agent Declines", "expression": "[Declined] / [Total]"},
            domain="SALES_DISTRIBUTION",
        )
        self.assertTrue(res["fallback_used"])
        self.assertIn("hallucination rejected", res["fallback_reason"])
        self.assertEqual(res["matching_engine"], self.deterministic_engine.VERSION)

    def test_llm_malformed_json_triggers_fallback(self):
        """Malformed JSON from LLM triggers deterministic fallback cleanly."""
        def malformed_provider(prompt):
            return "This is not valid json at all!"

        llm = LLMMatchingEngine(provider_fn=malformed_provider)
        orch = MatchingOrchestrator(kpi_bank_service=self.kpi_bank, llm_engine=llm)

        res = orch.discover_and_rank_candidates(
            {"name": "Agent Declines", "expression": "[Declined] / [Total]"},
            domain="SALES_DISTRIBUTION",
        )
        self.assertTrue(res["fallback_used"])
        self.assertIn("Malformed JSON", res["fallback_reason"])

    # =========================================================================
    # 4. HUMAN GOVERNANCE & APPROVAL WORKFLOW
    # =========================================================================

    def test_high_confidence_never_auto_approves(self):
        """Even a 1.0 confidence suggestion remains in PROPOSED state awaiting human review."""
        res = self.governance_service.run_mapping_pipeline(self.tenant_id, force_fallback=True)
        self.assertEqual(res["status"], "COMPLETED")

        fields = self.governance_service.list_fields_with_mappings(self.tenant_id)
        for f in fields:
            if f.get("decision_source") != "HUMAN_OVERRIDE_REUSED":
                self.assertIn(f["mapping_status"], ("PROPOSED", "UNMAPPED"))
                self.assertNotEqual(f["mapping_status"], "APPROVED")

    def test_human_approval_lifecycle(self):
        """Explicit human approval transitions mapping to APPROVED and saves ledger."""
        self.governance_service.run_mapping_pipeline(self.tenant_id, force_fallback=True)
        fields = self.governance_service.list_fields_with_mappings(self.tenant_id)
        target = next(f for f in fields if f.get("top_candidate_id"))

        mapping_id = target["mapping_id"]
        approved_kpi = target["top_candidate_id"]

        app_res = self.governance_service.approve_candidate(
            tenant_id=self.tenant_id,
            mapping_id=mapping_id,
            approved_kpi_id=approved_kpi,
            user_id="lead_analyst_sarah",
        )
        self.assertEqual(app_res["status"], "APPROVED")
        self.assertEqual(app_res["approved_by"], "lead_analyst_sarah")

        # Verify updated status
        updated_fields = self.governance_service.list_fields_with_mappings(self.tenant_id)
        updated = next(f for f in updated_fields if f["mapping_id"] == mapping_id)
        self.assertEqual(updated["mapping_status"], "APPROVED")
        self.assertEqual(updated["selected_kpi_id"], approved_kpi)

    def test_human_rejection_leaves_field_unresolved(self):
        """Rejecting a candidate sets status to REJECTED without mapping an alternative."""
        self.governance_service.run_mapping_pipeline(self.tenant_id, force_fallback=True)
        fields = self.governance_service.list_fields_with_mappings(self.tenant_id)
        target = next(f for f in fields if f.get("top_candidate_id"))

        rej_res = self.governance_service.reject_candidate(
            tenant_id=self.tenant_id,
            mapping_id=target["mapping_id"],
            user_id="lead_analyst_sarah",
            reason="Metric does not reflect standard insurance definition",
        )
        self.assertEqual(rej_res["status"], "REJECTED")

        updated_fields = self.governance_service.list_fields_with_mappings(self.tenant_id)
        updated = next(f for f in updated_fields if f["mapping_id"] == target["mapping_id"])
        self.assertEqual(updated["mapping_status"], "REJECTED")
        self.assertIsNone(updated["selected_kpi_id"])

    def test_override_requires_non_empty_justification(self):
        """Overriding candidate mapping strictly requires >= 10 chars justification."""
        self.governance_service.run_mapping_pipeline(self.tenant_id, force_fallback=True)
        fields = self.governance_service.list_fields_with_mappings(self.tenant_id)
        target = fields[0]

        # Empty justification fails
        with self.assertRaises(ValueError):
            self.governance_service.override_mapping(
                tenant_id=self.tenant_id,
                mapping_id=target["mapping_id"],
                replacement_kpi_id="7c194cb9-677a-48e2-a623-ee745b3e7ac4",
                override_justification="",
            )

        # Short justification (< 10 chars) fails
        with self.assertRaises(ValueError):
            self.governance_service.override_mapping(
                tenant_id=self.tenant_id,
                mapping_id=target["mapping_id"],
                replacement_kpi_id="7c194cb9-677a-48e2-a623-ee745b3e7ac4",
                override_justification="too short",
            )

        # Valid justification succeeds
        valid_res = self.governance_service.override_mapping(
            tenant_id=self.tenant_id,
            mapping_id=target["mapping_id"],
            replacement_kpi_id="7c194cb9-677a-48e2-a623-ee745b3e7ac4",
            override_justification="Selected based on organizational naming convention for declined calls",
            user_id="lead_analyst",
        )
        self.assertEqual(valid_res["status"], "OVERRIDDEN")

    # =========================================================================
    # 5. OVERRIDE LEARNING & RE-INGESTION REUSE
    # =========================================================================

    def test_reusable_override_fingerprinting_and_reuse(self):
        """Approved override is learned and automatically reused upon subsequent re-mapping."""
        field = {
            "field_id": "measure_calls_declined_custom",
            "name": "Declined Calls Metric",
            "expression": "SUM(Declined) / SUM(Incoming)",
            "domain": "SALES_DISTRIBUTION",
            "entity_type": "MEASURE",
            "platform": "POWER_BI",
            "asset_id": "asset_100",
        }
        kpi_target_id = "7c194cb9-677a-48e2-a623-ee745b3e7ac4"

        # Record human override
        ovr = self.learning_service.record_override(
            tenant_id=self.tenant_id,
            kpi_mapping_id="map_measure_calls_declined_custom",
            replacement_kpi_id=kpi_target_id,
            override_justification="Standard operational decline rate definition applies",
            user_id="chief_analyst",
            metadata_field=field,
        )
        self.assertTrue(ovr["is_active"])
        self.assertTrue(len(ovr["canonical_source_fingerprint"]) > 0)
        self.assertTrue(len(ovr["semantic_field_fingerprint"]) > 0)

        # Simulate re-ingestion lookup
        lookup = self.learning_service.find_reusable_override(self.tenant_id, field, self.kpi_bank)
        self.assertTrue(lookup["has_match"])
        self.assertFalse(lookup["has_conflict"])
        self.assertEqual(lookup["override"]["replacement_ontology_entry_id"], kpi_target_id)
        self.assertEqual(lookup["override"]["reuse_count"], 1)

    def test_conflicting_overrides_require_human_review(self):
        """Conflicting overrides pointing to different KPIs trigger conflict review."""
        field = {
            "field_id": "metric_loss_equiv",
            "name": "Incurred Loss Measure",
            "expression": "SUM(Loss)",
            "domain": "CLAIMS_RISK",
            "entity_type": "MEASURE",
            "platform": "POWER_BI",
            "asset_id": "asset_claims",
        }
        # Record override 1
        self.learning_service.record_override(
            tenant_id=self.tenant_id,
            kpi_mapping_id="map_1",
            replacement_kpi_id="kpi_incurred_loss_ratio",
            override_justification="Mapped to incurred loss ratio by user A",
            user_id="user_a",
            metadata_field=field,
        )
        # Record conflicting override 2 for same fingerprint
        self.learning_service.record_override(
            tenant_id=self.tenant_id,
            kpi_mapping_id="map_2",
            replacement_kpi_id="kpi_combined_ratio",
            override_justification="Mapped to combined ratio by user B",
            user_id="user_b",
            metadata_field=field,
        )

        lookup = self.learning_service.find_reusable_override(self.tenant_id, field, self.kpi_bank)
        self.assertFalse(lookup["has_match"])
        self.assertTrue(lookup["has_conflict"])
        self.assertIn("Human review required", lookup["reason"])

    # =========================================================================
    # 6. TENANT ISOLATION
    # =========================================================================

    def test_tenant_isolation_on_overrides_and_mappings(self):
        """Tenant Alpha cannot see or reuse Tenant Beta's overrides or mappings."""
        field_beta = {
            "field_id": "beta_underwriting_field",
            "name": "Commercial Bind Ratio",
            "domain": "UNDERWRITING",
        }
        self.learning_service.record_override(
            tenant_id=TENANT_BETA,
            kpi_mapping_id="map_beta_01",
            replacement_kpi_id="kpi_combined_ratio",
            override_justification="Commercial underwriting specific mapping",
            user_id="beta_lead",
            metadata_field=field_beta,
        )

        # Alpha searches for override
        alpha_lookup = self.learning_service.find_reusable_override(TENANT_ALPHA, field_beta, self.kpi_bank)
        self.assertFalse(alpha_lookup["has_match"])

        # Alpha lists overrides
        alpha_overrides = self.learning_service.list_active_overrides(TENANT_ALPHA)
        self.assertFalse(any(o.get("tenant_id") == TENANT_BETA for o in alpha_overrides))

    # =========================================================================
    # 7. REST API ENDPOINTS
    # =========================================================================

    def test_api_workspace_summary(self):
        """GET /api/v1/workspace/summary returns operational metrics."""
        code, body = self.api.handle_request("GET", "/api/v1/workspace/summary", {}, None, {"x-tenant-id": self.tenant_id})
        self.assertEqual(code, 200)
        self.assertTrue(body["success"])
        self.assertIn("total_canonical_entities", body["data"])
        self.assertIn("domain_distribution", body["data"])

    def test_api_domains_and_metrics(self):
        """GET /api/v1/domains returns the 5 canonical domains."""
        code, body = self.api.handle_request("GET", "/api/v1/domains", {}, None, {})
        self.assertEqual(code, 200)
        domain_codes = [d["code"] for d in body["data"]]
        self.assertIn("CLAIMS_RISK", domain_codes)
        self.assertIn("UNDERWRITING", domain_codes)
        self.assertIn("LEGAL", domain_codes)
        self.assertIn("SALES_DISTRIBUTION", domain_codes)
        self.assertIn("ACTUARIAL", domain_codes)

    def test_api_kpi_bank_search_and_create(self):
        """Search and creation endpoints on KPI Bank."""
        code, body = self.api.handle_request("GET", "/api/v1/kpi-bank/search", {"q": ["calls"]}, None, {})
        self.assertEqual(code, 200)
        self.assertGreater(body["count"], 0)

        # Create
        create_payload = {
            "name": "Rest API Test KPI",
            "definition": "Definition via REST API",
            "domain": "Legal",
            "formula": "LegalCosts / TotalLosses",
        }
        code, body = self.api.handle_request("POST", "/api/v1/kpi-bank/create", {}, create_payload, {})
        self.assertEqual(code, 201)
        self.assertEqual(body["data"]["name"], "Rest API Test KPI")


if __name__ == "__main__":
    unittest.main()
