"""
KPI Intelligence — Synthetic Seed Fixtures for Local Testing and Validation.

Contains deterministic synthetic fixtures covering:
- Multiple tenant contexts (Tenant Alpha, Tenant Beta)
- Reports in all 4 lifecycle states: ACTIVE, DORMANT, ORPHANED, UNCLASSIFIED
- Semantic models with tables, measures, and relationships
- KPI candidates, proposals, approvals, and human overrides
- Reference ontology entries across business domains
- Operational audit logs and diagnostics

ALL DATA IN THIS MODULE IS SYNTHETIC AND DESIGNED FOR LOCAL VALIDATION ONLY.
"""

import uuid
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone, timedelta
from backend.contracts import (
    CosmosContainer,
    AssetDocument,
    AssetVersionDocument,
    ReportDocument,
    SemanticModelDocument,
    LineageEdgeDocument,
    KpiCandidateDocument,
    KpiMappingDocument,
    MappingApprovalDocument,
    MappingOverrideDocument,
    OntologyVersionDocument,
    OntologyEntryDocument,
    BusinessDomainDocument,
    ParserRunDocument,
    ExtractionErrorDocument,
    LifecycleStatus,
    subtract_calendar_months,
    utc_now_iso,
)

# Deterministic UUIDs for synthetic test tenants
TENANT_ALPHA = "11111111-1111-1111-1111-111111111111"  # Tenant Alpha
TENANT_BETA  = "22222222-2222-2222-2222-222222222222"  # Tenant Beta

USER_ALICE = "aaaa0000-0000-0000-0000-000000000001"
USER_BOB   = "bbbb0000-0000-0000-0000-000000000002"


def generate_synthetic_fixtures() -> Dict[CosmosContainer, List[Any]]:
    """Generates deterministic synthetic fixtures across all 4 Cosmos containers."""
    now = datetime.now(timezone.utc)
    one_month_ago = (now - timedelta(days=30)).isoformat()
    seven_months_ago = subtract_calendar_months(now, 7).isoformat()

    catalog_docs = []
    governance_docs = []
    ontology_docs = []
    audit_docs = []

    # -------------------------------------------------------------------------
    # 1. ONTOLOGY CONTAINER (Global Reference Data)
    # -------------------------------------------------------------------------
    domains = [
        ("CLAIMS_RISK", "Claims & Risk", "Insurance claims processing, reserving, and fraud."),
        ("UNDERWRITING", "Underwriting", "Policy pricing, capacity, and risk selection."),
        ("LEGAL", "Legal", "Litigation tracking, compliance, and legal expense."),
        ("SALES_DISTRIBUTION", "Sales & Distribution", "Broker/agent production and commission."),
        ("SERVICE_OPERATIONS", "Service & Operations", "Policy servicing, call center, SLAs."),
        ("ACTUARIAL", "Actuarial", "Solvency modeling, loss reserving, and mortality."),
    ]
    for d_code, d_name, d_desc in domains:
        ontology_docs.append(BusinessDomainDocument(
            id=f"domain_{d_code.lower()}",
            domain_code=d_code,
            domain_name=d_name,
            domain_description=d_desc,
        ))

    ontology_version = OntologyVersionDocument(
        id="onto_ver_1_0_0",
        version_number="1.0.0",
        content_hash="synthetic_hash_ontology_v1",
        kpi_count=2,
    )
    ontology_docs.append(ontology_version)

    onto_entry_1 = OntologyEntryDocument(
        id="kpi_incurred_loss_ratio",
        business_domain="CLAIMS_RISK",
        ontology_version_id=ontology_version.id,
        kpi_code="CLM_001",
        kpi_name="Incurred Loss Ratio",
        definition="Total incurred losses divided by earned premium.",
        formula="[Incurred Losses] / [Earned Premium]",
        unit="PERCENTAGE",
        aggregation_method="RATIO",
        synonyms=["Loss Ratio", "Losses Incurred to Earned Premium"],
    )
    onto_entry_2 = OntologyEntryDocument(
        id="kpi_combined_ratio",
        business_domain="UNDERWRITING",
        ontology_version_id=ontology_version.id,
        kpi_code="UND_001",
        kpi_name="Combined Ratio",
        definition="Sum of incurred losses and operating expenses divided by earned premium.",
        formula="([Incurred Losses] + [Expenses]) / [Earned Premium]",
        unit="PERCENTAGE",
        aggregation_method="RATIO",
        synonyms=["Combined Operating Ratio", "COR"],
    )
    ontology_docs.extend([onto_entry_1, onto_entry_2])

    # -------------------------------------------------------------------------
    # 2. METADATA CATALOG (Tenant Alpha & Beta)
    # -------------------------------------------------------------------------
    # Asset for Tenant Alpha
    asset_alpha = AssetDocument(
        id="asset_claims_exec_report",
        tenant_id=TENANT_ALPHA,
        platform="POWER_BI",
        asset_name="Claims Executive Dashboard",
        source_native_path="powerbi/finance/claims.pbip",
    )
    version_alpha = AssetVersionDocument(
        id="ver_claims_exec_v1",
        tenant_id=TENANT_ALPHA,
        asset_id=asset_alpha.id,
        version_number=1,
        content_hash="hash_alpha_v1_synthetic",
        raw_content_hash="raw_hash_alpha_v1",
        structure_hash="struct_hash_alpha_v1",
        metadata_hash="meta_hash_alpha_v1",
    )
    catalog_docs.extend([asset_alpha, version_alpha])

    # Report 1 (Tenant Alpha): ACTIVE (owned, accessed 30 days ago)
    rep_active = ReportDocument(
        id="rep_active_claims",
        tenant_id=TENANT_ALPHA,
        asset_id=asset_alpha.id,
        asset_version_id=version_alpha.id,
        report_name="Active Executive Summary",
        owner_id=USER_ALICE,
        owner_name="Alice Smith",
        last_accessed_at=one_month_ago,
        lifecycle_status=LifecycleStatus.ACTIVE.value,
        page_count=3,
        visual_count=12,
    )

    # Report 2 (Tenant Alpha): DORMANT (owned, accessed 7 months ago)
    rep_dormant = ReportDocument(
        id="rep_dormant_claims",
        tenant_id=TENANT_ALPHA,
        asset_id=asset_alpha.id,
        asset_version_id=version_alpha.id,
        report_name="Legacy Monthly Claims Review",
        owner_id=USER_BOB,
        owner_name="Bob Jones",
        last_accessed_at=seven_months_ago,
        lifecycle_status=LifecycleStatus.DORMANT.value,
        page_count=2,
        visual_count=8,
    )

    # Report 3 (Tenant Alpha): ORPHANED (unowned)
    rep_orphaned = ReportDocument(
        id="rep_orphaned_claims",
        tenant_id=TENANT_ALPHA,
        asset_id=asset_alpha.id,
        asset_version_id=version_alpha.id,
        report_name="Unassigned Ad-Hoc Claims Canvas",
        owner_id=None,
        owner_name=None,
        last_accessed_at=one_month_ago,
        lifecycle_status=LifecycleStatus.ORPHANED.value,
        page_count=1,
        visual_count=4,
    )

    # Report 4 (Tenant Alpha): UNCLASSIFIED (owned, but last access unknown)
    rep_unclass = ReportDocument(
        id="rep_unclassified_claims",
        tenant_id=TENANT_ALPHA,
        asset_id=asset_alpha.id,
        asset_version_id=version_alpha.id,
        report_name="New Prototype Claims View",
        owner_id=USER_ALICE,
        owner_name="Alice Smith",
        last_accessed_at=None,
        lifecycle_status=LifecycleStatus.UNCLASSIFIED.value,
        page_count=1,
        visual_count=2,
    )

    # Report 5 (Tenant Beta): Cross-tenant isolation verification
    asset_beta = AssetDocument(
        id="asset_underwriting_portfolio",
        tenant_id=TENANT_BETA,
        platform="POWER_BI",
        asset_name="Underwriting Portfolio",
    )
    rep_beta = ReportDocument(
        id="rep_beta_underwriting",
        tenant_id=TENANT_BETA,
        asset_id=asset_beta.id,
        asset_version_id="ver_beta_v1",
        report_name="Commercial Lines Underwriting",
        owner_id=USER_BOB,
        owner_name="Bob Jones",
        last_accessed_at=one_month_ago,
        lifecycle_status=LifecycleStatus.ACTIVE.value,
    )
    catalog_docs.extend([rep_active, rep_dormant, rep_orphaned, rep_unclass, asset_beta, rep_beta])

    # Semantic Model for Tenant Alpha
    sem_model = SemanticModelDocument(
        id="model_claims_tabular",
        tenant_id=TENANT_ALPHA,
        asset_id=asset_alpha.id,
        asset_version_id=version_alpha.id,
        model_name="ClaimsAnalyticsModel",
        tables=[
            {"table_name": "FactClaims", "columns": ["ClaimId", "LossAmount", "PaidDate"]},
            {"table_name": "DimPolicy", "columns": ["PolicyId", "Premium", "EffectiveDate"]},
        ],
        calculations=[
            {"calculation_name": "IncurredLosses", "expression": "SUM(FactClaims[LossAmount])"},
            {"calculation_name": "EarnedPremium", "expression": "SUM(DimPolicy[Premium])"},
        ],
        relationships=[
            {"from_table": "FactClaims", "to_table": "DimPolicy", "cardinality": "manyToOne"}
        ]
    )
    edge = LineageEdgeDocument(
        id="edge_claims_to_loss_ratio",
        tenant_id=TENANT_ALPHA,
        asset_version_id=version_alpha.id,
        source_object_id="FactClaims.LossAmount",
        target_object_id="IncurredLosses",
        edge_type="MEASURE_DEPENDENCY",
    )
    catalog_docs.extend([sem_model, edge])

    # -------------------------------------------------------------------------
    # 3. KPI GOVERNANCE (Tenant Alpha)
    # -------------------------------------------------------------------------
    cand = KpiCandidateDocument(
        id="cand_incurred_loss_measure",
        tenant_id=TENANT_ALPHA,
        asset_version_id=version_alpha.id,
        source_object_id="IncurredLosses",
        candidate_name="Incurred Losses",
        candidate_expression="SUM(FactClaims[LossAmount])",
        candidate_type="MEASURE",
        unit="CURRENCY",
    )
    mapping = KpiMappingDocument(
        id="map_loss_ratio_001",
        tenant_id=TENANT_ALPHA,
        kpi_candidate_id=cand.id,
        asset_version_id=version_alpha.id,
        ontology_version_id=ontology_version.id,
        selected_ontology_entry_id=onto_entry_1.id,
        mapping_status="APPROVED",
        decision_source="LLM_INFERENCE",
        top_candidates=[
            {
                "ontology_entry_id": onto_entry_1.id,
                "rank": 1,
                "confidence_score": 0.94,
                "confidence_band": "HIGH",
                "match_score": 0.95,
                "rationale": "High semantic alignment on incurred loss calculation.",
                "is_recommended": True,
            }
        ]
    )
    approval = MappingApprovalDocument(
        id="app_loss_ratio_001",
        tenant_id=TENANT_ALPHA,
        kpi_mapping_id=mapping.id,
        approved_ontology_entry_id=onto_entry_1.id,
        approved_by_user_id=USER_ALICE,
        approval_status="ACTIVE",
        approved_at=one_month_ago,
    )
    governance_docs.extend([cand, mapping, approval])

    # -------------------------------------------------------------------------
    # 4. OPERATIONAL AUDIT (Tenant Alpha)
    # -------------------------------------------------------------------------
    parser_run = ParserRunDocument(
        id="run_claims_ingest_001",
        tenant_id=TENANT_ALPHA,
        asset_version_id=version_alpha.id,
        platform="POWER_BI",
        parser_name="PowerBIPBIPParser",
        run_status="SUCCESSFUL",
        objects_extracted=24,
        started_at=one_month_ago,
        completed_at=one_month_ago,
    )
    audit_docs.append(parser_run)

    return {
        CosmosContainer.METADATA_CATALOG: catalog_docs,
        CosmosContainer.KPI_GOVERNANCE: governance_docs,
        CosmosContainer.KPI_ONTOLOGY: ontology_docs,
        CosmosContainer.OPERATIONAL_AUDIT: audit_docs,
    }


def seed_synthetic_data(repo: Any) -> int:
    """Convenience helper to seed synthetic fixtures into any IRepository."""
    fixtures = generate_synthetic_fixtures()
    total_seeded = 0
    for container, docs in fixtures.items():
        partition_key_attr = "business_domain" if container == CosmosContainer.KPI_ONTOLOGY else "tenant_id"
        for doc in docs:
            pk = getattr(doc, partition_key_attr) or getattr(doc, "id")
            repo.upsert_item(container, pk, doc.to_dict())
            total_seeded += 1
    return total_seeded

