"""
KPI Intelligence — Catalog Document Contracts (metadata_catalog container).

Container: metadata_catalog
Partition Key: /tenant_id
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from backend.contracts.base import BaseDocument, DocumentType, CURRENT_SCHEMA_VERSION
from backend.contracts.lifecycle import LifecycleStatus


@dataclass
class AssetDocument(BaseDocument):
    """Logical BI Asset record (e.g., a Power BI project or report file)."""
    doc_type: str = DocumentType.ASSET.value
    platform: str = "POWER_BI"
    asset_name: str = ""
    asset_type: str = "REPORT"
    asset_description: Optional[str] = None
    source_native_id: Optional[str] = None
    source_native_path: Optional[str] = None
    source_version: Optional[str] = None
    current_version_id: Optional[str] = None
    lifecycle_status: str = "ACTIVE"
    first_ingested_at: Optional[str] = None
    last_ingested_at: Optional[str] = None

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("AssetDocument requires a valid 'tenant_id'.")
        if not self.asset_name:
            raise ValueError("AssetDocument requires 'asset_name'.")


@dataclass
class ArtifactItem:
    relative_path: str
    artifact_type: str
    content_hash: str
    size_bytes: int
    mime_type: Optional[str] = None
    is_supported: bool = True
    extraction_status: str = "SUCCESSFUL"


@dataclass
class AssetVersionDocument(BaseDocument):
    """Release version snapshot of an asset with cryptographic digests."""
    doc_type: str = DocumentType.ASSET_VERSION.value
    asset_id: str = ""
    version_number: int = 1
    content_hash: str = ""
    raw_content_hash: str = ""
    structure_hash: str = ""
    metadata_hash: str = ""
    parser_version: str = "1.0.0"
    extraction_status: str = "SUCCESSFUL"
    source_manifest: Dict[str, Any] = field(default_factory=dict)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("AssetVersionDocument requires 'tenant_id'.")
        if not self.asset_id:
            raise ValueError("AssetVersionDocument requires 'asset_id'.")
        if not self.content_hash:
            raise ValueError("AssetVersionDocument requires 'content_hash'.")


@dataclass
class ReportPageItem:
    page_id: str
    page_name: str
    page_order: int = 0
    page_type: str = "Standard"
    visual_count: int = 0
    is_hidden: bool = False
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReportDocument(BaseDocument):
    """Dashboard/Report definition document tracking ownership and access."""
    doc_type: str = DocumentType.REPORT.value
    asset_id: str = ""
    asset_version_id: str = ""
    platform: str = "POWER_BI"
    report_name: str = ""
    report_type: str = "POWER_BI_PBIP"
    owner_id: Optional[str] = None
    owner_name: Optional[str] = None
    last_accessed_at: Optional[str] = None
    lifecycle_status: str = LifecycleStatus.ORPHANED.value
    page_count: int = 0
    visual_count: int = 0
    report_configuration: Dict[str, Any] = field(default_factory=dict)
    pages: List[Dict[str, Any]] = field(default_factory=list)
    bookmarks: List[Dict[str, Any]] = field(default_factory=list)
    visual_interactions: List[Dict[str, Any]] = field(default_factory=list)
    navigation: List[Dict[str, Any]] = field(default_factory=list)
    filters: List[Dict[str, Any]] = field(default_factory=list)
    source_metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("ReportDocument requires 'tenant_id'.")
        if not self.report_name:
            raise ValueError("ReportDocument requires 'report_name'.")
        valid_statuses = {s.value for s in LifecycleStatus}
        if self.lifecycle_status not in valid_statuses:
            raise ValueError(f"Invalid lifecycle_status '{self.lifecycle_status}'. Allowed: {valid_statuses}")


@dataclass
class SemanticModelDocument(BaseDocument):
    """Tabular / semantic data model document with embedded entities."""
    doc_type: str = DocumentType.SEMANTIC_MODEL.value
    asset_id: str = ""
    asset_version_id: str = ""
    model_name: str = ""
    model_type: str = "TABULAR_TMDL"
    compatibility_level: Optional[int] = None
    culture: Optional[str] = None
    model_definition: Dict[str, Any] = field(default_factory=dict)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    calculations: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    partitions: List[Dict[str, Any]] = field(default_factory=list)
    named_expressions: List[Dict[str, Any]] = field(default_factory=list)
    hierarchies: List[Dict[str, Any]] = field(default_factory=list)
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    filters: List[Dict[str, Any]] = field(default_factory=list)
    security_roles: List[Dict[str, Any]] = field(default_factory=list)
    data_sources: List[Dict[str, Any]] = field(default_factory=list)
    query_dependencies: List[Dict[str, Any]] = field(default_factory=list)

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("SemanticModelDocument requires 'tenant_id'.")
        if not self.model_name:
            raise ValueError("SemanticModelDocument requires 'model_name'.")


@dataclass
class SpreadsheetWorkbookDocument(BaseDocument):
    """Excel / spreadsheet workbook aggregate document (Subsystem E)."""
    doc_type: str = DocumentType.SPREADSHEET_WORKBOOK.value
    asset_id: str = ""
    asset_version_id: str = ""
    workbook_name: str = ""
    worksheet_count: int = 0
    cells: List[Dict[str, Any]] = field(default_factory=list)
    pivot_caches: List[Dict[str, Any]] = field(default_factory=list)
    pivot_tables: List[Dict[str, Any]] = field(default_factory=list)
    spreadsheet_objects: List[Dict[str, Any]] = field(default_factory=list)
    spreadsheet_rules: List[Dict[str, Any]] = field(default_factory=list)

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("SpreadsheetWorkbookDocument requires 'tenant_id'.")
        if not self.workbook_name:
            raise ValueError("SpreadsheetWorkbookDocument requires 'workbook_name'.")


@dataclass
class LineageEdgeDocument(BaseDocument):
    """Directed dependency / lineage edge connecting analytical elements."""
    doc_type: str = DocumentType.LINEAGE_EDGE.value
    asset_version_id: str = ""
    source_object_id: str = ""
    target_object_id: str = ""
    edge_type: str = "MEASURE_DEPENDENCY"
    derivation_method: str = "SOURCE_DECLARED"
    confidence_score: float = 1.0
    evidence: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("LineageEdgeDocument requires 'tenant_id'.")
        if not self.source_object_id or not self.target_object_id:
            raise ValueError("LineageEdgeDocument requires source_object_id and target_object_id.")

