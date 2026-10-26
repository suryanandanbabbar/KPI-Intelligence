"""
KPI Intelligence — Canonical PostgreSQL to Cosmos DB Migration Dispositions.

Establishes an explicit, executable migration disposition for every canonical table:
- INDEPENDENTLY_PERSISTED: Mapped to a top-level document aggregate in a Cosmos DB container.
- EMBEDDED_AGGREGATED: Mapped as an embedded component within a parent document aggregate.
- INTENTIONALLY_EXCLUDED: Explicitly documented architectural exclusion (reported separately, never counted as persisted).
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from backend.contracts.base import CosmosContainer, DocumentType


class MigrationDispositionType(str, Enum):
    INDEPENDENTLY_PERSISTED = "INDEPENDENTLY_PERSISTED"
    EMBEDDED_AGGREGATED = "EMBEDDED_AGGREGATED"
    INTENTIONALLY_EXCLUDED = "INTENTIONALLY_EXCLUDED"


@dataclass
class TableMigrationDisposition:
    """Explicit migration specification for a single canonical relational table."""
    source_table: str
    disposition: MigrationDispositionType
    target_container: Optional[CosmosContainer] = None
    target_document_type: Optional[str] = None
    parent_table: Optional[str] = None
    parent_relationship: Optional[str] = None
    target_json_path: Optional[str] = None
    exclusion_reason: Optional[str] = None
    handler_function_name: Optional[str] = None


CANONICAL_MIGRATION_REGISTRY: Dict[str, TableMigrationDisposition] = {
    # -------------------------------------------------------------------------
    # Subsystem A — Asset Registry (4 tables)
    # -------------------------------------------------------------------------
    "assets": TableMigrationDisposition(
        source_table="assets",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.METADATA_CATALOG,
        target_document_type=DocumentType.ASSET.value,
        handler_function_name="_process_assets",
    ),
    "asset_versions": TableMigrationDisposition(
        source_table="asset_versions",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.METADATA_CATALOG,
        target_document_type=DocumentType.ASSET_VERSION.value,
        handler_function_name="_process_asset_versions",
    ),
    "ingestion_events": TableMigrationDisposition(
        source_table="ingestion_events",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.OPERATIONAL_AUDIT,
        target_document_type=DocumentType.INGESTION_EVENT.value,
        handler_function_name="_process_ingestion_events",
    ),
    "source_artifacts": TableMigrationDisposition(
        source_table="source_artifacts",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="asset_versions",
        parent_relationship="asset_version_id",
        target_json_path="c.source_artifacts[]",
        handler_function_name="_embed_source_artifacts",
    ),

    # -------------------------------------------------------------------------
    # Subsystem B — Universal Analytical Objects (10 tables)
    # -------------------------------------------------------------------------
    "analytical_objects": TableMigrationDisposition(
        source_table="analytical_objects",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.METADATA_CATALOG,
        target_document_type=DocumentType.ANALYTICAL_OBJECT.value,
        handler_function_name="_process_analytical_objects",
    ),
    "reports": TableMigrationDisposition(
        source_table="reports",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.METADATA_CATALOG,
        target_document_type=DocumentType.REPORT.value,
        handler_function_name="_process_reports",
    ),
    "report_pages": TableMigrationDisposition(
        source_table="report_pages",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="reports",
        parent_relationship="report_id",
        target_json_path="c.pages[]",
        handler_function_name="_embed_report_pages",
    ),
    "visuals": TableMigrationDisposition(
        source_table="visuals",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="reports",
        parent_relationship="page_id -> report_id",
        target_json_path="c.visuals[]",
        handler_function_name="_embed_visuals",
    ),
    "visual_bindings": TableMigrationDisposition(
        source_table="visual_bindings",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="reports",
        parent_relationship="visual_id -> reports",
        target_json_path="c.visual_bindings[]",
        handler_function_name="_embed_visual_bindings",
    ),
    "visual_properties": TableMigrationDisposition(
        source_table="visual_properties",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="reports",
        parent_relationship="visual_id -> reports",
        target_json_path="c.visual_properties[]",
        handler_function_name="_embed_visual_properties",
    ),
    "visual_interactions": TableMigrationDisposition(
        source_table="visual_interactions",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="reports",
        parent_relationship="report_id",
        target_json_path="c.visual_interactions[]",
        handler_function_name="_embed_visual_interactions",
    ),
    "visual_types": TableMigrationDisposition(
        source_table="visual_types",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.KPI_ONTOLOGY,
        target_document_type=DocumentType.PLATFORM_CAPABILITY.value,
        handler_function_name="_process_visual_types",
    ),
    "bookmarks": TableMigrationDisposition(
        source_table="bookmarks",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="reports",
        parent_relationship="object_id -> reports",
        target_json_path="c.bookmarks[]",
        handler_function_name="_embed_bookmarks",
    ),
    "report_navigation": TableMigrationDisposition(
        source_table="report_navigation",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="reports",
        parent_relationship="report_id",
        target_json_path="c.report_navigation[]",
        handler_function_name="_embed_report_navigation",
    ),

    # -------------------------------------------------------------------------
    # Subsystem C — Semantic Models and Calculations (10 tables)
    # -------------------------------------------------------------------------
    "semantic_models": TableMigrationDisposition(
        source_table="semantic_models",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.METADATA_CATALOG,
        target_document_type=DocumentType.SEMANTIC_MODEL.value,
        handler_function_name="_process_semantic_models",
    ),
    "data_tables": TableMigrationDisposition(
        source_table="data_tables",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="semantic_models",
        parent_relationship="semantic_model_id",
        target_json_path="c.data_tables[]",
        handler_function_name="_embed_data_tables",
    ),
    "data_columns": TableMigrationDisposition(
        source_table="data_columns",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="semantic_models",
        parent_relationship="data_table_id -> semantic_models",
        target_json_path="c.data_columns[]",
        handler_function_name="_embed_data_columns",
    ),
    "calculations": TableMigrationDisposition(
        source_table="calculations",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="semantic_models",
        parent_relationship="semantic_model_id",
        target_json_path="c.calculations[]",
        handler_function_name="_embed_calculations",
    ),
    "relationships": TableMigrationDisposition(
        source_table="relationships",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="semantic_models",
        parent_relationship="semantic_model_id",
        target_json_path="c.relationships[]",
        handler_function_name="_embed_relationships",
    ),
    "model_partitions": TableMigrationDisposition(
        source_table="model_partitions",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="semantic_models",
        parent_relationship="semantic_model_id",
        target_json_path="c.model_partitions[]",
        handler_function_name="_embed_model_partitions",
    ),
    "hierarchies": TableMigrationDisposition(
        source_table="hierarchies",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="semantic_models",
        parent_relationship="semantic_model_id",
        target_json_path="c.hierarchies[]",
        handler_function_name="_embed_hierarchies",
    ),
    "hierarchy_levels": TableMigrationDisposition(
        source_table="hierarchy_levels",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="semantic_models",
        parent_relationship="hierarchy_id -> semantic_models",
        target_json_path="c.hierarchy_levels[]",
        handler_function_name="_embed_hierarchy_levels",
    ),
    "parameters": TableMigrationDisposition(
        source_table="parameters",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="semantic_models",
        parent_relationship="object_id -> semantic_models",
        target_json_path="c.parameters[]",
        handler_function_name="_embed_parameters",
    ),
    "named_expressions": TableMigrationDisposition(
        source_table="named_expressions",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="semantic_models",
        parent_relationship="semantic_model_id",
        target_json_path="c.named_expressions[]",
        handler_function_name="_embed_named_expressions",
    ),

    # -------------------------------------------------------------------------
    # Subsystem D — Filters, Security, Data Sources, and Lineage (9 tables)
    # -------------------------------------------------------------------------
    "filters": TableMigrationDisposition(
        source_table="filters",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="reports",
        parent_relationship="object_id",
        target_json_path="c.filters[]",
        handler_function_name="_embed_filters",
    ),
    "filter_assignments": TableMigrationDisposition(
        source_table="filter_assignments",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="reports",
        parent_relationship="filter_id -> reports",
        target_json_path="c.filter_assignments[]",
        handler_function_name="_embed_filter_assignments",
    ),
    "security_roles": TableMigrationDisposition(
        source_table="security_roles",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="semantic_models",
        parent_relationship="object_id -> semantic_models",
        target_json_path="c.security_roles[]",
        handler_function_name="_embed_security_roles",
    ),
    "security_role_filters": TableMigrationDisposition(
        source_table="security_role_filters",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="semantic_models",
        parent_relationship="role_id -> semantic_models",
        target_json_path="c.security_role_filters[]",
        handler_function_name="_embed_security_role_filters",
    ),
    "security_principals": TableMigrationDisposition(
        source_table="security_principals",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.METADATA_CATALOG,
        target_document_type=DocumentType.SECURITY_PRINCIPAL.value,
        handler_function_name="_process_security_principals",
    ),
    "security_object_permissions": TableMigrationDisposition(
        source_table="security_object_permissions",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="assets",
        parent_relationship="object_id -> assets",
        target_json_path="c.security_object_permissions[]",
        handler_function_name="_embed_security_object_permissions",
    ),
    "data_sources": TableMigrationDisposition(
        source_table="data_sources",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="semantic_models",
        parent_relationship="object_id -> semantic_models",
        target_json_path="c.data_sources[]",
        handler_function_name="_embed_data_sources",
    ),
    "query_dependencies": TableMigrationDisposition(
        source_table="query_dependencies",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="semantic_models",
        parent_relationship="semantic_model_id",
        target_json_path="c.query_dependencies[]",
        handler_function_name="_embed_query_dependencies",
    ),
    "metadata_lineage_edges": TableMigrationDisposition(
        source_table="metadata_lineage_edges",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.METADATA_CATALOG,
        target_document_type=DocumentType.LINEAGE_EDGE.value,
        handler_function_name="_process_metadata_lineage_edges",
    ),

    # -------------------------------------------------------------------------
    # Subsystem E — Excel-Specific Metadata (6 tables)
    # -------------------------------------------------------------------------
    "spreadsheet_objects": TableMigrationDisposition(
        source_table="spreadsheet_objects",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="spreadsheet_workbooks",
        parent_relationship="worksheet_object_id -> asset_version_id",
        target_json_path="c.spreadsheet_objects[]",
        handler_function_name="_embed_spreadsheet_objects",
    ),
    "spreadsheet_cells": TableMigrationDisposition(
        source_table="spreadsheet_cells",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="spreadsheet_workbooks",
        parent_relationship="asset_version_id",
        target_json_path="c.spreadsheet_cells[]",
        handler_function_name="_embed_spreadsheet_cells",
    ),
    "spreadsheet_rules": TableMigrationDisposition(
        source_table="spreadsheet_rules",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="spreadsheet_workbooks",
        parent_relationship="asset_version_id",
        target_json_path="c.spreadsheet_rules[]",
        handler_function_name="_embed_spreadsheet_rules",
    ),
    "pivot_caches": TableMigrationDisposition(
        source_table="pivot_caches",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="spreadsheet_workbooks",
        parent_relationship="asset_version_id",
        target_json_path="c.pivot_caches[]",
        handler_function_name="_embed_pivot_caches",
    ),
    "pivot_tables": TableMigrationDisposition(
        source_table="pivot_tables",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="spreadsheet_workbooks",
        parent_relationship="pivot_cache_id -> asset_version_id",
        target_json_path="c.pivot_tables[]",
        handler_function_name="_embed_pivot_tables",
    ),
    "pivot_field_assignments": TableMigrationDisposition(
        source_table="pivot_field_assignments",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="spreadsheet_workbooks",
        parent_relationship="pivot_table_id -> asset_version_id",
        target_json_path="c.pivot_field_assignments[]",
        handler_function_name="_embed_pivot_field_assignments",
    ),

    # -------------------------------------------------------------------------
    # Subsystem F — KPI Ontology and Domain Classification (4 tables)
    # -------------------------------------------------------------------------
    "kpi_ontology_versions": TableMigrationDisposition(
        source_table="kpi_ontology_versions",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.KPI_ONTOLOGY,
        target_document_type=DocumentType.ONTOLOGY_VERSION.value,
        handler_function_name="_process_kpi_ontology_versions",
    ),
    "kpi_ontology_entries": TableMigrationDisposition(
        source_table="kpi_ontology_entries",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.KPI_ONTOLOGY,
        target_document_type=DocumentType.ONTOLOGY_ENTRY.value,
        handler_function_name="_process_kpi_ontology_entries",
    ),
    "business_domains": TableMigrationDisposition(
        source_table="business_domains",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.KPI_ONTOLOGY,
        target_document_type=DocumentType.BUSINESS_DOMAIN.value,
        handler_function_name="_process_business_domains",
    ),
    "domain_classifications": TableMigrationDisposition(
        source_table="domain_classifications",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.KPI_GOVERNANCE,
        target_document_type=DocumentType.DOMAIN_CLASSIFICATION.value,
        handler_function_name="_process_domain_classifications",
    ),

    # -------------------------------------------------------------------------
    # Subsystem G — KPI Candidates and Mapping (5 tables)
    # -------------------------------------------------------------------------
    "kpi_candidates": TableMigrationDisposition(
        source_table="kpi_candidates",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.KPI_GOVERNANCE,
        target_document_type=DocumentType.KPI_CANDIDATE.value,
        handler_function_name="_process_kpi_candidates",
    ),
    "kpi_mapping_runs": TableMigrationDisposition(
        source_table="kpi_mapping_runs",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.KPI_GOVERNANCE,
        target_document_type=DocumentType.KPI_MAPPING_RUN.value,
        handler_function_name="_process_kpi_mapping_runs",
    ),
    "kpi_mappings": TableMigrationDisposition(
        source_table="kpi_mappings",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.KPI_GOVERNANCE,
        target_document_type=DocumentType.KPI_MAPPING.value,
        handler_function_name="_process_kpi_mappings",
    ),
    "kpi_mapping_candidates": TableMigrationDisposition(
        source_table="kpi_mapping_candidates",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="kpi_mappings",
        parent_relationship="kpi_mapping_id",
        target_json_path="c.kpi_mapping_candidates[]",
        handler_function_name="_embed_kpi_mapping_candidates",
    ),
    "mapping_evidence": TableMigrationDisposition(
        source_table="mapping_evidence",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="kpi_mappings",
        parent_relationship="mapping_candidate_id -> kpi_mappings",
        target_json_path="c.mapping_evidence[]",
        handler_function_name="_embed_mapping_evidence",
    ),

    # -------------------------------------------------------------------------
    # Subsystem H — Human Review, Approval, Overrides (4 tables)
    # -------------------------------------------------------------------------
    "mapping_reviews": TableMigrationDisposition(
        source_table="mapping_reviews",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="kpi_mappings",
        parent_relationship="kpi_mapping_id",
        target_json_path="c.mapping_reviews[]",
        handler_function_name="_embed_mapping_reviews",
    ),
    "mapping_approvals": TableMigrationDisposition(
        source_table="mapping_approvals",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.KPI_GOVERNANCE,
        target_document_type=DocumentType.MAPPING_APPROVAL.value,
        handler_function_name="_process_mapping_approvals",
    ),
    "mapping_overrides": TableMigrationDisposition(
        source_table="mapping_overrides",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.KPI_GOVERNANCE,
        target_document_type=DocumentType.MAPPING_OVERRIDE.value,
        handler_function_name="_process_mapping_overrides",
    ),
    "metadata_field_reviews": TableMigrationDisposition(
        source_table="metadata_field_reviews",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.KPI_GOVERNANCE,
        target_document_type=DocumentType.METADATA_FIELD_REVIEW.value,
        handler_function_name="_process_metadata_field_reviews",
    ),

    # -------------------------------------------------------------------------
    # Subsystem I — KPI Rationalisation (3 tables)
    # -------------------------------------------------------------------------
    "kpi_rationalisation_decisions": TableMigrationDisposition(
        source_table="kpi_rationalisation_decisions",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.KPI_GOVERNANCE,
        target_document_type=DocumentType.KPI_RATIONALISATION.value,
        handler_function_name="_process_kpi_rationalisations",
    ),
    "kpi_equivalence_candidates": TableMigrationDisposition(
        source_table="kpi_equivalence_candidates",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="kpi_rationalisation_decisions",
        parent_relationship="rationalisation_decision_id",
        target_json_path="c.kpi_equivalence_candidates[]",
        handler_function_name="_embed_kpi_equivalence_candidates",
    ),
    "rationalisation_evidence": TableMigrationDisposition(
        source_table="rationalisation_evidence",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="kpi_rationalisation_decisions",
        parent_relationship="rationalisation_decision_id",
        target_json_path="c.rationalisation_evidence[]",
        handler_function_name="_embed_rationalisation_evidence",
    ),

    # -------------------------------------------------------------------------
    # Subsystem J — Operations and Audit (6 tables)
    # -------------------------------------------------------------------------
    "platform_capabilities": TableMigrationDisposition(
        source_table="platform_capabilities",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.KPI_ONTOLOGY,
        target_document_type=DocumentType.PLATFORM_CAPABILITY.value,
        handler_function_name="_process_platform_capabilities",
    ),
    "parser_runs": TableMigrationDisposition(
        source_table="parser_runs",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.OPERATIONAL_AUDIT,
        target_document_type=DocumentType.PARSER_RUN.value,
        handler_function_name="_process_parser_runs",
    ),
    "extraction_errors": TableMigrationDisposition(
        source_table="extraction_errors",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.OPERATIONAL_AUDIT,
        target_document_type=DocumentType.EXTRACTION_ERROR.value,
        handler_function_name="_process_extraction_errors",
    ),
    "object_tags": TableMigrationDisposition(
        source_table="object_tags",
        disposition=MigrationDispositionType.EMBEDDED_AGGREGATED,
        parent_table="assets",
        parent_relationship="object_id -> assets",
        target_json_path="c.object_tags[]",
        handler_function_name="_embed_object_tags",
    ),
    "mapping_audit_events": TableMigrationDisposition(
        source_table="mapping_audit_events",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.OPERATIONAL_AUDIT,
        target_document_type=DocumentType.AUDIT_EVENT.value,
        handler_function_name="_process_mapping_audit_events",
    ),
    "ontology_change_events": TableMigrationDisposition(
        source_table="ontology_change_events",
        disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
        target_container=CosmosContainer.OPERATIONAL_AUDIT,
        target_document_type=DocumentType.ONTOLOGY_CHANGE_EVENT.value,
        handler_function_name="_process_ontology_change_events",
    ),
}


def get_disposition_for_table(name: str) -> Optional[TableMigrationDisposition]:
    """Retrieves explicit migration disposition for a table name."""
    return CANONICAL_MIGRATION_REGISTRY.get(name)
