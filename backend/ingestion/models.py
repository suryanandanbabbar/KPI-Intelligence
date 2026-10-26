"""
KPI Intelligence — Canonical Ingestion Models.

Dataclasses representing canonical records conforming exactly to the 61-table
PostgreSQL schema in the kpi_intel schema.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
import uuid


@dataclass
class CanonicalAsset:
    asset_id: uuid.UUID
    tenant_id: uuid.UUID
    platform: str
    asset_type: str
    asset_name: str
    asset_description: Optional[str] = None
    source_native_id: Optional[str] = None
    source_native_path: Optional[str] = None
    source_version: Optional[str] = None
    lifecycle_status: str = "ACTIVE"
    current_version_id: Optional[uuid.UUID] = None


@dataclass
class CanonicalAssetVersion:
    asset_version_id: uuid.UUID
    asset_id: uuid.UUID
    tenant_id: uuid.UUID
    version_number: int
    content_hash: str
    raw_content_hash: str
    structure_hash: str
    metadata_hash: str
    parser_version: str
    schema_version: str = "1.0.0"
    source_manifest: Dict[str, Any] = field(default_factory=dict)
    extraction_status: str = "SUCCESSFUL"


@dataclass
class CanonicalSourceArtifact:
    source_artifact_id: uuid.UUID
    asset_version_id: uuid.UUID
    relative_path: str
    artifact_type: str
    content_hash: str
    size_bytes: int
    source_native_id: Optional[str] = None
    mime_type: Optional[str] = None
    is_supported: bool = True
    extraction_status: str = "SUCCESSFUL"
    extraction_notes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalAnalyticalObject:
    object_id: uuid.UUID
    asset_version_id: uuid.UUID
    tenant_id: uuid.UUID
    platform: str
    object_type: str
    canonical_name: str
    parent_object_id: Optional[uuid.UUID] = None
    source_artifact_id: Optional[uuid.UUID] = None
    source_native_id: Optional[str] = None
    source_native_name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    source_path: Optional[str] = None
    source_locator: Dict[str, Any] = field(default_factory=dict)
    is_hidden: bool = False
    is_active: bool = True
    extraction_status: str = "EXTRACTED"
    metadata_completeness: Optional[float] = 1.0
    source_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalReport:
    report_id: uuid.UUID
    object_id: uuid.UUID
    report_type: str = "POWER_BI_PBIP"
    report_definition: Dict[str, Any] = field(default_factory=dict)
    default_page_object_id: Optional[uuid.UUID] = None
    page_count: int = 0
    visual_count: int = 0
    report_configuration: Dict[str, Any] = field(default_factory=dict)
    owner_id: Optional[uuid.UUID] = None
    owner_name: Optional[str] = None
    last_accessed_at: Optional[datetime] = None
    lifecycle_status: str = "ORPHANED"


@dataclass
class CanonicalReportPage:
    page_id: uuid.UUID
    report_id: uuid.UUID
    object_id: uuid.UUID
    page_name: str
    source_native_id: Optional[str] = None
    page_order: int = 0
    page_type: str = "Standard"
    page_properties: Dict[str, Any] = field(default_factory=dict)
    is_hidden: bool = False


@dataclass
class CanonicalVisual:
    visual_id: uuid.UUID
    page_id: uuid.UUID
    object_id: uuid.UUID
    visual_type: str
    source_native_id: Optional[str] = None
    visual_title: Optional[str] = None
    visual_description: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    z_order: int = 0
    visual_configuration: Dict[str, Any] = field(default_factory=dict)
    is_visible: bool = True


@dataclass
class CanonicalVisualBinding:
    visual_binding_id: uuid.UUID
    visual_id: uuid.UUID
    object_id: uuid.UUID
    binding_role: str
    binding_order: int = 0
    aggregation_override: Optional[str] = None
    format_override: Optional[str] = None
    binding_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalBookmark:
    bookmark_id: uuid.UUID
    object_id: uuid.UUID
    bookmark_name: str
    source_native_id: Optional[str] = None
    bookmark_state: Dict[str, Any] = field(default_factory=dict)
    bookmark_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalSemanticModel:
    semantic_model_id: uuid.UUID
    object_id: uuid.UUID
    model_name: str
    model_type: str = "TABULAR_TMDL"
    source_native_id: Optional[str] = None
    model_version: Optional[str] = None
    compatibility_level: Optional[str] = None
    model_definition: Dict[str, Any] = field(default_factory=dict)
    source_connection_summary: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalDataTable:
    data_table_id: uuid.UUID
    object_id: uuid.UUID
    semantic_model_id: uuid.UUID
    table_name: str
    table_type: str
    source_native_id: Optional[str] = None
    schema_name: Optional[str] = None
    description: Optional[str] = None
    is_hidden: bool = False
    storage_mode: Optional[str] = "import"
    source_reference: Dict[str, Any] = field(default_factory=dict)
    table_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalDataColumn:
    data_column_id: uuid.UUID
    object_id: uuid.UUID
    data_table_id: uuid.UUID
    column_name: str
    data_type: str
    source_native_id: Optional[str] = None
    display_name: Optional[str] = None
    source_data_type: Optional[str] = None
    description: Optional[str] = None
    semantic_role: Optional[str] = None
    is_nullable: bool = True
    is_hidden: bool = False
    is_calculated: bool = False
    default_aggregation: Optional[str] = None
    format_string: Optional[str] = None
    column_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalCalculation:
    calculation_id: uuid.UUID
    object_id: uuid.UUID
    calculation_name: str
    calculation_type: str
    expression_language: str
    expression_text: str
    semantic_model_id: Optional[uuid.UUID] = None
    data_table_id: Optional[uuid.UUID] = None
    data_column_id: Optional[uuid.UUID] = None
    normalised_expression: Optional[str] = None
    return_data_type: Optional[str] = None
    aggregation_type: Optional[str] = None
    format_string: Optional[str] = None
    description: Optional[str] = None
    evaluation_context: Optional[str] = None
    expression_parse_status: str = "PARSED"
    expression_ast: Dict[str, Any] = field(default_factory=dict)
    expression_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalRelationship:
    relationship_id: uuid.UUID
    object_id: uuid.UUID
    relationship_type: str = "FOREIGN_KEY"
    from_table_id: Optional[uuid.UUID] = None
    to_table_id: Optional[uuid.UUID] = None
    from_object_id: Optional[uuid.UUID] = None
    to_object_id: Optional[uuid.UUID] = None
    cardinality: str = "oneToMany"
    join_type: Optional[str] = "INNER"
    is_active: bool = True
    cross_filter_direction: Optional[str] = "oneDirection"
    relationship_expression: Optional[str] = None
    relationship_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalModelPartition:
    model_partition_id: uuid.UUID
    semantic_model_id: uuid.UUID
    partition_name: str
    source_native_id: Optional[str] = None
    source_type: Optional[str] = None
    expression_language: Optional[str] = None
    expression_text: Optional[str] = None
    partition_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalNamedExpression:
    named_expression_id: uuid.UUID
    object_id: uuid.UUID
    expression_name: str
    expression_language: str
    expression_text: str
    scope: Optional[str] = "MODEL"
    resolved_reference_object_id: Optional[uuid.UUID] = None
    expression_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalHierarchy:
    hierarchy_id: uuid.UUID
    object_id: uuid.UUID
    semantic_model_id: uuid.UUID
    hierarchy_name: str
    hierarchy_type: str = "STANDARD"
    hierarchy_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalHierarchyLevel:
    hierarchy_level_id: uuid.UUID
    hierarchy_id: uuid.UUID
    level_object_id: uuid.UUID
    level_name: str
    level_order: int
    level_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalFilter:
    filter_id: uuid.UUID
    object_id: uuid.UUID
    filter_name: str
    filter_type: str
    filter_scope: str
    expression_language: Optional[str] = None
    expression_text: Optional[str] = None
    filter_operator: Optional[str] = None
    filter_values: Dict[str, Any] = field(default_factory=dict)
    is_enabled: bool = True
    filter_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalFilterAssignment:
    filter_assignment_id: uuid.UUID
    filter_id: uuid.UUID
    target_object_id: uuid.UUID
    assignment_scope: str
    field_object_id: Optional[uuid.UUID] = None
    assignment_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalMetadataLineageEdge:
    lineage_edge_id: uuid.UUID
    asset_version_id: uuid.UUID
    source_object_id: uuid.UUID
    target_object_id: uuid.UUID
    edge_type: str
    derivation_method: str = "PARSED"
    confidence_score: float = 1.0
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalParserRun:
    parser_run_id: uuid.UUID
    asset_version_id: uuid.UUID
    tenant_id: uuid.UUID
    platform: str
    parser_name: str
    parser_version: str
    run_status: str = "SUCCESSFUL"
    objects_extracted: int = 0
    warnings_count: int = 0
    errors_count: int = 0
    source_artifact_id: Optional[uuid.UUID] = None
    run_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalExtractionError:
    extraction_error_id: uuid.UUID
    parser_run_id: uuid.UUID
    severity: str
    error_code: str
    error_message: str
    source_artifact_id: Optional[uuid.UUID] = None
    object_locator: Dict[str, Any] = field(default_factory=dict)
    is_recoverable: bool = True


@dataclass
class CanonicalIngestionBundle:
    """Complete collection of normalized canonical records ready for persistence."""
    asset: CanonicalAsset
    version: CanonicalAssetVersion
    artifacts: List[CanonicalSourceArtifact] = field(default_factory=list)
    objects: List[CanonicalAnalyticalObject] = field(default_factory=list)
    reports: List[CanonicalReport] = field(default_factory=list)
    pages: List[CanonicalReportPage] = field(default_factory=list)
    visuals: List[CanonicalVisual] = field(default_factory=list)
    visual_bindings: List[CanonicalVisualBinding] = field(default_factory=list)
    bookmarks: List[CanonicalBookmark] = field(default_factory=list)
    semantic_models: List[CanonicalSemanticModel] = field(default_factory=list)
    tables: List[CanonicalDataTable] = field(default_factory=list)
    columns: List[CanonicalDataColumn] = field(default_factory=list)
    calculations: List[CanonicalCalculation] = field(default_factory=list)
    relationships: List[CanonicalRelationship] = field(default_factory=list)
    partitions: List[CanonicalModelPartition] = field(default_factory=list)
    named_expressions: List[CanonicalNamedExpression] = field(default_factory=list)
    hierarchies: List[CanonicalHierarchy] = field(default_factory=list)
    hierarchy_levels: List[CanonicalHierarchyLevel] = field(default_factory=list)
    filters: List[CanonicalFilter] = field(default_factory=list)
    filter_assignments: List[CanonicalFilterAssignment] = field(default_factory=list)
    lineage_edges: List[CanonicalMetadataLineageEdge] = field(default_factory=list)
    parser_runs: List[CanonicalParserRun] = field(default_factory=list)
    extraction_errors: List[CanonicalExtractionError] = field(default_factory=list)
