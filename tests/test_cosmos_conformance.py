"""
KPI Intelligence — Cosmos DB & Domain Model Conformance Test Suite.

Verifies:
1. Strict document schema validation (required fields, partition keys, enums).
2. Lifecycle classification rules, precedence, and calendar interval arithmetic.
3. Fail-closed tenant context enforcement across domain repositories.
4. Embedded document aggregate consistency for reports and semantic models.
5. In-memory and SQLite repository behavior conformance with Cosmos contracts.
"""

import os
import tempfile
import unittest
from datetime import datetime, timezone, date

from backend.contracts import (
    CosmosContainer,
    DocumentType,
    AssetDocument,
    AssetVersionDocument,
    ReportDocument,
    SemanticModelDocument,
    LineageEdgeDocument,
    KpiCandidateDocument,
    KpiMappingDocument,
    MappingApprovalDocument,
    MappingOverrideDocument,
    KpiRationalisationDocument,
    OntologyVersionDocument,
    OntologyEntryDocument,
    BusinessDomainDocument,
    ParserRunDocument,
    ExtractionErrorDocument,
    LifecycleStatus,
    subtract_calendar_months,
    classify_report_lifecycle,
)
from backend.repository.context import TenantContext, TenantAccessDeniedError
from backend.repository.services import (
    CatalogServiceRepository,
    GovernanceServiceRepository,
    OntologyServiceRepository,
    AuditServiceRepository,
)
from backend.storage.sqlite.repository import SQLiteRepository


class TestDocumentSchemaValidation(unittest.TestCase):
    """Verifies that all Cosmos document models enforce strict validation rules."""

    def test_asset_document_validation(self):
        # Valid asset
        asset = AssetDocument(id="a1", tenant_id="t1", asset_name="Sales Asset")
        asset.validate()

        # Missing tenant_id
        with self.assertRaises(ValueError):
            AssetDocument(id="a2", tenant_id="", asset_name="Sales Asset").validate()

        # Missing asset_name
        with self.assertRaises(ValueError):
            AssetDocument(id="a3", tenant_id="t1", asset_name="").validate()

    def test_report_document_validation(self):
        # Valid report
        rep = ReportDocument(id="r1", tenant_id="t1", report_name="Exec Report", lifecycle_status="ACTIVE")
        rep.validate()

        # Missing report_name
        with self.assertRaises(ValueError):
            ReportDocument(id="r2", tenant_id="t1", report_name="").validate()

        # Invalid lifecycle_status
        with self.assertRaises(ValueError):
            ReportDocument(id="r3", tenant_id="t1", report_name="R3", lifecycle_status="INVALID_STATUS").validate()

    def test_ontology_entry_validation(self):
        # Valid entry
        entry = OntologyEntryDocument(
            id="k1", business_domain="CLAIMS_RISK", kpi_code="CLM_001", kpi_name="Loss Ratio"
        )
        entry.validate()

        # Missing business_domain partition key
        with self.assertRaises(ValueError):
            OntologyEntryDocument(id="k2", business_domain="", kpi_code="CLM_002", kpi_name="Name").validate()

        # Missing kpi_code
        with self.assertRaises(ValueError):
            OntologyEntryDocument(id="k3", business_domain="CLAIMS_RISK", kpi_code="", kpi_name="Name").validate()

    def test_mapping_override_validation(self):
        # Valid override with justification
        ovr = MappingOverrideDocument(
            id="o1",
            tenant_id="t1",
            kpi_mapping_id="m1",
            replacement_ontology_entry_id="k1",
            override_justification="Authorized formula divergence for commercial lines.",
        )
        ovr.validate()

        # Empty justification must fail
        with self.assertRaises(ValueError):
            MappingOverrideDocument(
                id="o2",
                tenant_id="t1",
                kpi_mapping_id="m1",
                replacement_ontology_entry_id="k1",
                override_justification="   ",
            ).validate()


class TestLifecycleClassificationRules(unittest.TestCase):
    """
    Verifies strict calendar arithmetic and 4-state lifecycle classification.
    """

    def test_calendar_month_subtraction(self):
        # Standard: August 31 - 6 months -> February 28 (non-leap year)
        dt_2023 = datetime(2023, 8, 31, 12, 0, tzinfo=timezone.utc)
        sub_2023 = subtract_calendar_months(dt_2023, 6)
        self.assertEqual(sub_2023.year, 2023)
        self.assertEqual(sub_2023.month, 2)
        self.assertEqual(sub_2023.day, 28)

        # Leap year: August 31, 2024 - 6 months -> February 29, 2024
        dt_2024 = datetime(2024, 8, 31, 12, 0, tzinfo=timezone.utc)
        sub_2024 = subtract_calendar_months(dt_2024, 6)
        self.assertEqual(sub_2024.year, 2024)
        self.assertEqual(sub_2024.month, 2)
        self.assertEqual(sub_2024.day, 29)

        # Clamping: March 31 - 1 month -> February 28 (or 29)
        dt_mar31 = datetime(2023, 3, 31, 0, 0, tzinfo=timezone.utc)
        sub_mar = subtract_calendar_months(dt_mar31, 1)
        self.assertEqual(sub_mar.month, 2)
        self.assertEqual(sub_mar.day, 28)

    def test_lifecycle_precedence(self):
        now = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)

        # 1. No owner -> ORPHANED regardless of access date
        status_orphaned = classify_report_lifecycle(
            owner_id=None,
            last_accessed_at="2026-10-25T00:00:00Z",
            as_of=now,
        )
        self.assertEqual(status_orphaned, LifecycleStatus.ORPHANED)

        # 2. Owner present, but last_accessed_at is NULL -> UNCLASSIFIED
        # (Standard Power BI PBIP desktop file without server activity)
        status_unclassified = classify_report_lifecycle(
            owner_id="user_alice",
            last_accessed_at=None,
            as_of=now,
        )
        self.assertEqual(status_unclassified, LifecycleStatus.UNCLASSIFIED)

        # 3. Owner present, access date > 6 calendar months ago -> DORMANT
        status_dormant = classify_report_lifecycle(
            owner_id="user_alice",
            last_accessed_at="2026-01-15T00:00:00Z",
            as_of=now,
        )
        self.assertEqual(status_dormant, LifecycleStatus.DORMANT)

        # 4. Owner present, access date within 6 calendar months -> ACTIVE
        status_active = classify_report_lifecycle(
            owner_id="user_alice",
            last_accessed_at="2026-09-01T00:00:00Z",
            as_of=now,
        )
        self.assertEqual(status_active, LifecycleStatus.ACTIVE)


class TestDomainServiceRepositories(unittest.TestCase):
    """
    Verifies that domain service repositories preserve strict tenant isolation
    and Cosmos DB partitioning contracts.
    """

    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.db_path = self.temp_file.name
        self.temp_file.close()

        self.repo = SQLiteRepository(self.db_path)
        self.catalog_repo = CatalogServiceRepository(self.repo)
        self.governance_repo = GovernanceServiceRepository(self.repo)
        self.ontology_repo = OntologyServiceRepository(self.repo)
        self.audit_repo = AuditServiceRepository(self.repo)

        self.tenant_a = "11111111-1111-1111-1111-111111111111"
        self.tenant_b = "22222222-2222-2222-2222-222222222222"
        self.ctx_a = TenantContext(tenant_id=self.tenant_a)
        self.ctx_b = TenantContext(tenant_id=self.tenant_b)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_catalog_service_operations(self):
        # Save Report Document with embedded pages
        report = ReportDocument(
            id="rep_exec_01",
            tenant_id=self.tenant_a,
            report_name="Executive Briefing",
            owner_id="user_123",
            owner_name="Alice Smith",
            lifecycle_status=LifecycleStatus.ACTIVE.value,
            pages=[
                {"page_id": "p1", "page_name": "KPIs", "visuals": [{"visual_id": "v1", "visual_type": "card"}]}
            ],
        )

        saved = self.catalog_repo.save_report(report, self.ctx_a)
        self.assertEqual(saved.id, "rep_exec_01")
        self.assertEqual(len(saved.pages), 1)

        # Retrieve Report within Tenant A context
        retrieved = self.catalog_repo.get_report("rep_exec_01", self.ctx_a)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.report_name, "Executive Briefing")

        # Partition isolation: Tenant B reading its own partition does not find Tenant A report
        self.assertIsNone(self.catalog_repo.get_report("rep_exec_01", self.ctx_b))

        # Cross-tenant direct access failure: Tenant B querying Tenant A's partition raises TenantAccessDeniedError
        with self.assertRaises(TenantAccessDeniedError):
            self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_a, "rep_exec_01", self.ctx_b)

    def test_governance_service_operations(self):
        # Candidate and Mapping
        cand = KpiCandidateDocument(
            id="cand_loss_01",
            tenant_id=self.tenant_a,
            candidate_name="Loss Ratio Raw",
        )
        self.governance_repo.save_candidate(cand, self.ctx_a)

        mapping = KpiMappingDocument(
            id="map_loss_01",
            tenant_id=self.tenant_a,
            kpi_candidate_id="cand_loss_01",
            selected_ontology_entry_id="kpi_std_01",
            mapping_status="PROPOSED",
        )
        self.governance_repo.save_mapping(mapping, self.ctx_a)

        # Approve mapping
        approval = MappingApprovalDocument(
            id="app_loss_01",
            tenant_id=self.tenant_a,
            kpi_mapping_id="map_loss_01",
            approved_ontology_entry_id="kpi_std_01",
            approved_by_user_id="user_admin",
        )
        approved = self.governance_repo.approve_mapping(approval, self.ctx_a)
        self.assertEqual(approved.approved_ontology_entry_id, "kpi_std_01")

        # Verify mapping updated to APPROVED
        updated_map = self.governance_repo.get_mapping("map_loss_01", self.ctx_a)
        self.assertEqual(updated_map.mapping_status, "APPROVED")
        self.assertIsNotNone(updated_map.active_approval)

    def test_ontology_service_global_partitioning(self):
        # Reference data is stored under partition key /business_domain
        entry = OntologyEntryDocument(
            id="kpi_curated_01",
            business_domain="CLAIMS_RISK",
            kpi_code="CLM_LOSS_RATIO",
            kpi_name="Incurred Loss Ratio",
            definition="Ratio of incurred losses to earned premium",
        )
        saved = self.ontology_repo.save_entry(entry)
        self.assertEqual(saved.kpi_code, "CLM_LOSS_RATIO")

        # Query entries by domain
        paged = self.ontology_repo.list_entries_by_domain("CLAIMS_RISK")
        self.assertEqual(len(paged.items), 1)
        self.assertEqual(paged.items[0]["kpi_name"], "Incurred Loss Ratio")


if __name__ == "__main__":
    unittest.main()
