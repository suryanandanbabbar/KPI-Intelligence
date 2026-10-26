"""
KPI Intelligence — Business-Level Domain Service Repositories.

Provides high-level, strongly typed domain operations over IRepository:
- Enforces strict tenant isolation on every tenant-owned method
- Handles serialization and contract validation
- Encapsulates queries for lifecycle, governance, and catalog search
"""

from typing import List, Optional, Dict, Any
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
    MappingAuditEventDocument,
    IngestionEventDocument,
    LifecycleStatus,
    classify_report_lifecycle,
)
from backend.repository.interfaces import IRepository, QuerySpec, PagedResult
from backend.repository.context import TenantContext


class CatalogServiceRepository:
    """Manages metadata catalog assets, reports, models, and lineage edges."""

    def __init__(self, repo: IRepository):
        self.repo = repo
        self.container = CosmosContainer.METADATA_CATALOG

    def save_asset(self, asset: AssetDocument, context: TenantContext) -> AssetDocument:
        context.assert_authorized(asset.tenant_id)
        asset.validate()
        res = self.repo.upsert_item(self.container, asset.tenant_id, asset.to_dict(), context, etag=asset._etag)
        return AssetDocument.from_dict(res)

    def get_asset(self, asset_id: str, context: TenantContext) -> Optional[AssetDocument]:
        data = self.repo.get_item(self.container, context.tenant_id, asset_id, context)
        return AssetDocument.from_dict(data) if data else None

    def save_asset_version(self, version: AssetVersionDocument, context: TenantContext) -> AssetVersionDocument:
        context.assert_authorized(version.tenant_id)
        version.validate()
        res = self.repo.upsert_item(self.container, version.tenant_id, version.to_dict(), context, etag=version._etag)
        return AssetVersionDocument.from_dict(res)

    def get_asset_version(self, version_id: str, context: TenantContext) -> Optional[AssetVersionDocument]:
        data = self.repo.get_item(self.container, context.tenant_id, version_id, context)
        return AssetVersionDocument.from_dict(data) if data else None

    def save_report(self, report: ReportDocument, context: TenantContext) -> ReportDocument:
        context.assert_authorized(report.tenant_id)
        report.validate()
        res = self.repo.upsert_item(self.container, report.tenant_id, report.to_dict(), context, etag=report._etag)
        return ReportDocument.from_dict(res)

    def get_report(self, report_id: str, context: TenantContext) -> Optional[ReportDocument]:
        data = self.repo.get_item(self.container, context.tenant_id, report_id, context)
        return ReportDocument.from_dict(data) if data else None

    def list_reports(
        self,
        context: TenantContext,
        lifecycle_status: Optional[str] = None,
        page_size: int = 100,
        continuation_token: Optional[str] = None
    ) -> PagedResult:
        query = "SELECT * FROM c WHERE c.tenant_id = @tenant_id AND c.doc_type = @doc_type"
        params = [
            {"name": "@tenant_id", "value": context.tenant_id},
            {"name": "@doc_type", "value": DocumentType.REPORT.value}
        ]
        if lifecycle_status:
            query += " AND c.lifecycle_status = @lifecycle_status"
            params.append({"name": "@lifecycle_status", "value": lifecycle_status})

        query += " ORDER BY c.created_at DESC"
        spec = QuerySpec(query=query, parameters=params)
        return self.repo.query_items(
            self.container, context.tenant_id, spec, context, page_size, continuation_token
        )

    def save_semantic_model(self, model: SemanticModelDocument, context: TenantContext) -> SemanticModelDocument:
        context.assert_authorized(model.tenant_id)
        model.validate()
        res = self.repo.upsert_item(self.container, model.tenant_id, model.to_dict(), context, etag=model._etag)
        return SemanticModelDocument.from_dict(res)

    def get_semantic_model(self, model_id: str, context: TenantContext) -> Optional[SemanticModelDocument]:
        data = self.repo.get_item(self.container, context.tenant_id, model_id, context)
        return SemanticModelDocument.from_dict(data) if data else None

    def save_lineage_edge(self, edge: LineageEdgeDocument, context: TenantContext) -> LineageEdgeDocument:
        context.assert_authorized(edge.tenant_id)
        edge.validate()
        res = self.repo.upsert_item(self.container, edge.tenant_id, edge.to_dict(), context, etag=edge._etag)
        return LineageEdgeDocument.from_dict(res)


class GovernanceServiceRepository:
    """Manages candidate KPIs, mappings, approvals, overrides, and rationalizations."""

    def __init__(self, repo: IRepository):
        self.repo = repo
        self.container = CosmosContainer.KPI_GOVERNANCE

    def save_candidate(self, candidate: KpiCandidateDocument, context: TenantContext) -> KpiCandidateDocument:
        context.assert_authorized(candidate.tenant_id)
        candidate.validate()
        res = self.repo.upsert_item(self.container, candidate.tenant_id, candidate.to_dict(), context, etag=candidate._etag)
        return KpiCandidateDocument.from_dict(res)

    def get_candidate(self, candidate_id: str, context: TenantContext) -> Optional[KpiCandidateDocument]:
        data = self.repo.get_item(self.container, context.tenant_id, candidate_id, context)
        return KpiCandidateDocument.from_dict(data) if data else None

    def save_mapping(self, mapping: KpiMappingDocument, context: TenantContext) -> KpiMappingDocument:
        context.assert_authorized(mapping.tenant_id)
        mapping.validate()
        res = self.repo.upsert_item(self.container, mapping.tenant_id, mapping.to_dict(), context, etag=mapping._etag)
        return KpiMappingDocument.from_dict(res)

    def get_mapping(self, mapping_id: str, context: TenantContext) -> Optional[KpiMappingDocument]:
        data = self.repo.get_item(self.container, context.tenant_id, mapping_id, context)
        return KpiMappingDocument.from_dict(data) if data else None

    def list_pending_mappings(
        self,
        context: TenantContext,
        page_size: int = 100,
        continuation_token: Optional[str] = None
    ) -> PagedResult:
        query = "SELECT * FROM c WHERE c.tenant_id = @tenant_id AND c.doc_type = @doc_type AND c.mapping_status = @status"
        params = [
            {"name": "@tenant_id", "value": context.tenant_id},
            {"name": "@doc_type", "value": DocumentType.KPI_MAPPING.value},
            {"name": "@status", "value": "PROPOSED"}
        ]
        spec = QuerySpec(query=query, parameters=params)
        return self.repo.query_items(self.container, context.tenant_id, spec, context, page_size, continuation_token)

    def approve_mapping(self, approval: MappingApprovalDocument, context: TenantContext) -> MappingApprovalDocument:
        context.assert_authorized(approval.tenant_id)
        approval.validate()
        # 1. Fetch current mapping to ensure it exists and belongs to tenant
        mapping = self.get_mapping(approval.kpi_mapping_id, context)
        if not mapping:
            raise ValueError(f"Target mapping '{approval.kpi_mapping_id}' not found.")

        # 2. Save immutable approval record
        res = self.repo.upsert_item(self.container, approval.tenant_id, approval.to_dict(), context)
        app_doc = MappingApprovalDocument.from_dict(res)

        # 3. Update mapping status to APPROVED
        mapping.mapping_status = "APPROVED"
        mapping.selected_ontology_entry_id = approval.approved_ontology_entry_id
        mapping.active_approval = app_doc.to_dict()
        self.save_mapping(mapping, context)
        return app_doc

    def override_mapping(self, override: MappingOverrideDocument, context: TenantContext) -> MappingOverrideDocument:
        context.assert_authorized(override.tenant_id)
        override.validate()
        mapping = self.get_mapping(override.kpi_mapping_id, context)
        if not mapping:
            raise ValueError(f"Target mapping '{override.kpi_mapping_id}' not found.")

        # Save override record
        res = self.repo.upsert_item(self.container, override.tenant_id, override.to_dict(), context)
        ovr_doc = MappingOverrideDocument.from_dict(res)

        # Update mapping status to OVERRIDDEN
        mapping.mapping_status = "OVERRIDDEN"
        mapping.selected_ontology_entry_id = override.replacement_ontology_entry_id
        self.save_mapping(mapping, context)
        return ovr_doc


class OntologyServiceRepository:
    """Manages the reference KPI bank and business domains (partitioned by /business_domain)."""

    def __init__(self, repo: IRepository):
        self.repo = repo
        self.container = CosmosContainer.KPI_ONTOLOGY

    def save_entry(self, entry: OntologyEntryDocument) -> OntologyEntryDocument:
        entry.validate()
        # Ontology is global reference data; uses system context
        ctx = TenantContext.system_context()
        res = self.repo.upsert_item(self.container, entry.business_domain, entry.to_dict(), ctx, etag=entry._etag)
        return OntologyEntryDocument.from_dict(res)

    def get_entry(self, domain: str, entry_id: str) -> Optional[OntologyEntryDocument]:
        ctx = TenantContext.system_context()
        data = self.repo.get_item(self.container, domain, entry_id, ctx)
        return OntologyEntryDocument.from_dict(data) if data else None

    def list_entries_by_domain(
        self,
        domain: str,
        page_size: int = 100,
        continuation_token: Optional[str] = None
    ) -> PagedResult:
        ctx = TenantContext.system_context()
        query = "SELECT * FROM c WHERE c.business_domain = @domain AND c.doc_type = @doc_type"
        params = [
            {"name": "@domain", "value": domain},
            {"name": "@doc_type", "value": DocumentType.ONTOLOGY_ENTRY.value}
        ]
        spec = QuerySpec(query=query, parameters=params)
        return self.repo.query_items(self.container, domain, spec, ctx, page_size, continuation_token)


class AuditServiceRepository:
    """Manages parser execution metrics, extraction errors, and governance audit trails."""

    def __init__(self, repo: IRepository):
        self.repo = repo
        self.container = CosmosContainer.OPERATIONAL_AUDIT

    def log_parser_run(self, run: ParserRunDocument, context: TenantContext) -> ParserRunDocument:
        context.assert_authorized(run.tenant_id)
        run.validate()
        res = self.repo.upsert_item(self.container, run.tenant_id, run.to_dict(), context)
        return ParserRunDocument.from_dict(res)

    def log_error(self, err: ExtractionErrorDocument, context: TenantContext) -> ExtractionErrorDocument:
        context.assert_authorized(err.tenant_id)
        err.validate()
        res = self.repo.upsert_item(self.container, err.tenant_id, err.to_dict(), context)
        return ExtractionErrorDocument.from_dict(res)

    def log_event(self, event: MappingAuditEventDocument, context: TenantContext) -> MappingAuditEventDocument:
        context.assert_authorized(event.tenant_id)
        event.validate()
        res = self.repo.upsert_item(self.container, event.tenant_id, event.to_dict(), context)
        return MappingAuditEventDocument.from_dict(res)
