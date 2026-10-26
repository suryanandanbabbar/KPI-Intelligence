"""
KPI Intelligence — Canonical Document Contracts Package.
"""

from backend.contracts.base import (
    BaseDocument,
    DocumentType,
    CosmosContainer,
    CONTAINER_PARTITION_KEYS,
    CURRENT_SCHEMA_VERSION,
    utc_now_iso,
)
from backend.contracts.lifecycle import (
    LifecycleStatus,
    classify_report_lifecycle,
    subtract_calendar_months,
    normalize_datetime,
)
from backend.contracts.catalog import (
    AssetDocument,
    AssetVersionDocument,
    ReportDocument,
    ReportPageItem,
    SemanticModelDocument,
    AnalyticalObjectDocument,
    SecurityPrincipalDocument,
    LineageEdgeDocument,
    SpreadsheetWorkbookDocument,
    ArtifactItem,
)
from backend.contracts.governance import (
    KpiCandidateDocument,
    KpiMappingDocument,
    KpiMappingRunDocument,
    MappingApprovalDocument,
    MappingOverrideDocument,
    KpiRationalisationDocument,
    DomainClassificationDocument,
    MetadataFieldReviewDocument,
    ProposalCandidateItem,
)
from backend.contracts.ontology import (
    OntologyVersionDocument,
    OntologyEntryDocument,
    BusinessDomainDocument,
    PlatformCapabilityDocument,
)
from backend.contracts.audit import (
    ParserRunDocument,
    ExtractionErrorDocument,
    MappingAuditEventDocument,
    IngestionEventDocument,
    OntologyChangeEventDocument,
)

__all__ = [
    "BaseDocument",
    "DocumentType",
    "CosmosContainer",
    "CONTAINER_PARTITION_KEYS",
    "CURRENT_SCHEMA_VERSION",
    "utc_now_iso",
    "LifecycleStatus",
    "classify_report_lifecycle",
    "subtract_calendar_months",
    "normalize_datetime",
    "AssetDocument",
    "AssetVersionDocument",
    "ReportDocument",
    "ReportPageItem",
    "SemanticModelDocument",
    "AnalyticalObjectDocument",
    "SecurityPrincipalDocument",
    "SpreadsheetWorkbookDocument",
    "LineageEdgeDocument",
    "ArtifactItem",
    "KpiCandidateDocument",
    "KpiMappingDocument",
    "KpiMappingRunDocument",
    "MappingApprovalDocument",
    "MappingOverrideDocument",
    "KpiRationalisationDocument",
    "DomainClassificationDocument",
    "MetadataFieldReviewDocument",
    "ProposalCandidateItem",
    "OntologyVersionDocument",
    "OntologyEntryDocument",
    "BusinessDomainDocument",
    "PlatformCapabilityDocument",
    "ParserRunDocument",
    "ExtractionErrorDocument",
    "MappingAuditEventDocument",
    "IngestionEventDocument",
    "OntologyChangeEventDocument",
]
