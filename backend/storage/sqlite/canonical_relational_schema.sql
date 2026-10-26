-- ============================================================================
-- KPI INTELLIGENCE PLATFORM — CANONICAL DATA MODEL DDL (SQLITE MIRROR)
-- Subsystem: Local SQLite Relational Mirror (Developer & Offline Conformance)
-- Description: Complete 61-table relational schema mirroring canonical_schema.sql.
--              Includes all columns, primary keys, foreign keys, and indexes.
-- ============================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    asset_name TEXT NOT NULL,
    asset_description TEXT,
    source_native_id TEXT,
    source_native_path TEXT,
    source_version TEXT,
    created_at_source TEXT,
    modified_at_source TEXT,
    first_ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    current_version_id TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_assets_platform CHECK (platform IN ('POWER_BI', 'TABLEAU', 'EXCEL', 'THOUGHTSPOT', 'MICROSTRATEGY')),
    CONSTRAINT ck_assets_lifecycle_status CHECK (lifecycle_status IN ('ACTIVE', 'ARCHIVED', 'DELETED', 'SUPERSEDED')),
    CONSTRAINT uq_assets_tenant UNIQUE (asset_id, tenant_id),
    CONSTRAINT fk_assets_current_version FOREIGN KEY (current_version_id) REFERENCES asset_versions(asset_version_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS asset_versions (
    asset_version_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    raw_content_hash TEXT NOT NULL,
    structure_hash TEXT NOT NULL,
    metadata_hash TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    source_manifest TEXT NOT NULL DEFAULT '{}',
    extraction_status TEXT NOT NULL DEFAULT 'PENDING',
    extraction_started_at TEXT,
    extraction_completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_asset_versions_asset_version_number UNIQUE (asset_id, version_number),
    CONSTRAINT uq_asset_versions_tenant UNIQUE (asset_version_id, tenant_id),
    CONSTRAINT ck_asset_versions_status CHECK (extraction_status IN ('PENDING', 'SUCCESSFUL', 'PARTIAL', 'FAILED')),
    CONSTRAINT fk_asset_versions_asset_tenant FOREIGN KEY (asset_id, tenant_id) REFERENCES assets(asset_id, tenant_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ingestion_events (
    ingestion_id TEXT PRIMARY KEY,
    asset_version_id TEXT REFERENCES asset_versions(asset_version_id) ON DELETE SET NULL,
    uploaded_by_user_id TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    upload_size_bytes INTEGER NOT NULL,
    upload_source TEXT NOT NULL,
    ingestion_status TEXT NOT NULL DEFAULT 'RECEIVED',
    error_code TEXT,
    error_message TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_ingestion_events_status CHECK (ingestion_status IN ('RECEIVED', 'VALIDATING', 'EXTRACTING', 'COMPLETED', 'FAILED'))
);

CREATE TABLE IF NOT EXISTS source_artifacts (
    source_artifact_id TEXT PRIMARY KEY,
    asset_version_id TEXT NOT NULL REFERENCES asset_versions(asset_version_id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    source_native_id TEXT,
    content_hash TEXT NOT NULL,
    mime_type TEXT,
    size_bytes INTEGER NOT NULL,
    is_supported INTEGER NOT NULL DEFAULT 1,
    extraction_status TEXT NOT NULL DEFAULT 'PENDING',
    extraction_notes TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_source_artifacts_version_path UNIQUE (asset_version_id, relative_path),
    CONSTRAINT ck_source_artifacts_status CHECK (extraction_status IN ('PENDING', 'SUCCESSFUL', 'PARTIAL', 'SKIPPED', 'FAILED'))
);

CREATE TABLE IF NOT EXISTS analytical_objects (
    object_id TEXT PRIMARY KEY,
    asset_version_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    parent_object_id TEXT REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    source_artifact_id TEXT REFERENCES source_artifacts(source_artifact_id) ON DELETE SET NULL,
    platform TEXT NOT NULL,
    object_type TEXT NOT NULL,
    source_native_id TEXT,
    source_native_name TEXT,
    canonical_name TEXT NOT NULL,
    display_name TEXT,
    description TEXT,
    source_path TEXT,
    source_locator TEXT NOT NULL DEFAULT '{}',
    is_hidden INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    extraction_status TEXT NOT NULL DEFAULT 'EXTRACTED',
    metadata_completeness REAL,
    source_metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_analytical_objects_platform CHECK (platform IN ('POWER_BI', 'TABLEAU', 'EXCEL', 'THOUGHTSPOT', 'MICROSTRATEGY')),
    CONSTRAINT ck_analytical_objects_status CHECK (extraction_status IN ('EXTRACTED', 'PARTIAL', 'INFERRED', 'UNRESOLVED', 'FAILED')),
    CONSTRAINT ck_analytical_objects_completeness CHECK (metadata_completeness IS NULL OR (metadata_completeness >= 0.0000 AND metadata_completeness <= 1.0000)),
    CONSTRAINT uq_analytical_objects_version UNIQUE (object_id, asset_version_id),
    CONSTRAINT uq_analytical_objects_tenant UNIQUE (object_id, tenant_id),
    CONSTRAINT fk_analytical_objects_version_tenant FOREIGN KEY (asset_version_id, tenant_id) REFERENCES asset_versions(asset_version_id, tenant_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL UNIQUE REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    report_type TEXT NOT NULL,
    report_definition TEXT NOT NULL DEFAULT '{}',
    default_page_object_id TEXT REFERENCES analytical_objects(object_id) ON DELETE SET NULL,
    page_count INTEGER NOT NULL DEFAULT 0,
    visual_count INTEGER NOT NULL DEFAULT 0,
    report_configuration TEXT NOT NULL DEFAULT '{}',
    owner_id TEXT,
    owner_name TEXT,
    last_accessed_at TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'ORPHANED',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_reports_lifecycle_status CHECK (lifecycle_status IN ('ACTIVE', 'DORMANT', 'ORPHANED', 'UNCLASSIFIED')),
    CONSTRAINT fk_reports_owner FOREIGN KEY (owner_id) REFERENCES security_principals(principal_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS report_pages (
    page_id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
    object_id TEXT NOT NULL UNIQUE REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    source_native_id TEXT,
    page_name TEXT NOT NULL,
    page_order INTEGER NOT NULL DEFAULT 0,
    page_type TEXT NOT NULL,
    page_properties TEXT NOT NULL DEFAULT '{}',
    is_hidden INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS visuals (
    visual_id TEXT PRIMARY KEY,
    page_id TEXT NOT NULL REFERENCES report_pages(page_id) ON DELETE CASCADE,
    object_id TEXT NOT NULL UNIQUE REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    source_native_id TEXT,
    visual_type TEXT NOT NULL,
    visual_title TEXT,
    visual_description TEXT,
    position_x REAL,
    position_y REAL,
    width REAL,
    height REAL,
    z_order INTEGER NOT NULL DEFAULT 0,
    visual_configuration TEXT NOT NULL DEFAULT '{}',
    is_visible INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS visual_bindings (
    visual_binding_id TEXT PRIMARY KEY,
    visual_id TEXT NOT NULL REFERENCES visuals(visual_id) ON DELETE CASCADE,
    object_id TEXT NOT NULL REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    binding_role TEXT NOT NULL,
    binding_order INTEGER NOT NULL DEFAULT 0,
    aggregation_override TEXT,
    format_override TEXT,
    binding_properties TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS visual_properties (
    visual_property_id TEXT PRIMARY KEY,
    visual_id TEXT NOT NULL REFERENCES visuals(visual_id) ON DELETE CASCADE,
    property_path TEXT NOT NULL,
    property_value TEXT NOT NULL DEFAULT '{}',
    expression_language TEXT,
    expression_text TEXT,
    source_properties TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT uq_visual_properties_path UNIQUE (visual_id, property_path)
);

CREATE TABLE IF NOT EXISTS visual_interactions (
    visual_interaction_id TEXT PRIMARY KEY,
    source_visual_id TEXT NOT NULL REFERENCES visuals(visual_id) ON DELETE CASCADE,
    target_visual_id TEXT NOT NULL REFERENCES visuals(visual_id) ON DELETE CASCADE,
    interaction_type TEXT NOT NULL,
    interaction_properties TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT ck_visual_interactions_distinct CHECK (source_visual_id <> target_visual_id)
);

CREATE TABLE IF NOT EXISTS visual_types (
    visual_type_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    native_type TEXT NOT NULL,
    canonical_type TEXT NOT NULL,
    description TEXT,
    type_properties TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT uq_visual_types_platform_native UNIQUE (platform, native_type)
);

CREATE TABLE IF NOT EXISTS bookmarks (
    bookmark_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    source_native_id TEXT,
    bookmark_name TEXT NOT NULL,
    bookmark_state TEXT NOT NULL DEFAULT '{}',
    bookmark_properties TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS report_navigation (
    report_navigation_id TEXT PRIMARY KEY,
    source_object_id TEXT NOT NULL REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    target_object_id TEXT NOT NULL REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    navigation_type TEXT NOT NULL,
    navigation_name TEXT,
    navigation_expression TEXT,
    expression_language TEXT,
    navigation_properties TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS semantic_models (
    semantic_model_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL UNIQUE REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    source_native_id TEXT,
    model_name TEXT NOT NULL,
    model_type TEXT NOT NULL,
    model_version TEXT,
    compatibility_level TEXT,
    model_definition TEXT NOT NULL DEFAULT '{}',
    source_connection_summary TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_tables (
    data_table_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL UNIQUE REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    semantic_model_id TEXT NOT NULL REFERENCES semantic_models(semantic_model_id) ON DELETE CASCADE,
    source_native_id TEXT,
    table_name TEXT NOT NULL,
    schema_name TEXT,
    table_type TEXT NOT NULL,
    description TEXT,
    is_hidden INTEGER NOT NULL DEFAULT 0,
    storage_mode TEXT,
    source_reference TEXT NOT NULL DEFAULT '{}',
    table_properties TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_columns (
    data_column_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL UNIQUE REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    data_table_id TEXT NOT NULL REFERENCES data_tables(data_table_id) ON DELETE CASCADE,
    source_native_id TEXT,
    column_name TEXT NOT NULL,
    display_name TEXT,
    data_type TEXT NOT NULL,
    source_data_type TEXT,
    description TEXT,
    semantic_role TEXT,
    is_nullable INTEGER NOT NULL DEFAULT 1,
    is_hidden INTEGER NOT NULL DEFAULT 0,
    is_calculated INTEGER NOT NULL DEFAULT 0,
    default_aggregation TEXT,
    format_string TEXT,
    column_properties TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS calculations (
    calculation_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL UNIQUE REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    semantic_model_id TEXT REFERENCES semantic_models(semantic_model_id) ON DELETE CASCADE,
    data_table_id TEXT REFERENCES data_tables(data_table_id) ON DELETE SET NULL,
    data_column_id TEXT REFERENCES data_columns(data_column_id) ON DELETE SET NULL,
    calculation_name TEXT NOT NULL,
    calculation_type TEXT NOT NULL,
    expression_language TEXT NOT NULL,
    expression_text TEXT NOT NULL,
    normalised_expression TEXT,
    return_data_type TEXT,
    aggregation_type TEXT,
    format_string TEXT,
    description TEXT,
    evaluation_context TEXT,
    expression_parse_status TEXT NOT NULL DEFAULT 'UNPARSED',
    expression_ast TEXT NOT NULL DEFAULT '{}',
    expression_properties TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_calculations_parse_status CHECK (expression_parse_status IN ('UNPARSED', 'PARSED', 'PARTIAL', 'UNSUPPORTED', 'FAILED'))
);

CREATE TABLE IF NOT EXISTS relationships (
    relationship_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL UNIQUE REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,
    from_table_id TEXT REFERENCES data_tables(data_table_id) ON DELETE CASCADE,
    to_table_id TEXT REFERENCES data_tables(data_table_id) ON DELETE CASCADE,
    from_object_id TEXT REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    to_object_id TEXT REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    cardinality TEXT NOT NULL,
    join_type TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    cross_filter_direction TEXT,
    relationship_expression TEXT,
    relationship_properties TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_relationships_endpoints CHECK ( (from_table_id IS NOT NULL AND to_table_id IS NOT NULL) OR (from_object_id IS NOT NULL AND to_object_id IS NOT NULL) )
);

CREATE TABLE IF NOT EXISTS model_partitions (
    model_partition_id TEXT PRIMARY KEY,
    semantic_model_id TEXT NOT NULL REFERENCES semantic_models(semantic_model_id) ON DELETE CASCADE,
    source_native_id TEXT,
    partition_name TEXT NOT NULL,
    source_type TEXT,
    expression_language TEXT,
    expression_text TEXT,
    partition_properties TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS hierarchies (
    hierarchy_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL UNIQUE REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    semantic_model_id TEXT NOT NULL REFERENCES semantic_models(semantic_model_id) ON DELETE CASCADE,
    hierarchy_name TEXT NOT NULL,
    hierarchy_type TEXT NOT NULL,
    hierarchy_properties TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS hierarchy_levels (
    hierarchy_level_id TEXT PRIMARY KEY,
    hierarchy_id TEXT NOT NULL REFERENCES hierarchies(hierarchy_id) ON DELETE CASCADE,
    level_object_id TEXT NOT NULL REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    level_name TEXT NOT NULL,
    level_order INTEGER NOT NULL,
    level_properties TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT uq_hierarchy_levels_order UNIQUE (hierarchy_id, level_order)
);

CREATE TABLE IF NOT EXISTS parameters (
    parameter_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL UNIQUE REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    parameter_name TEXT NOT NULL,
    data_type TEXT NOT NULL,
    default_value TEXT,
    allowed_values TEXT,
    is_required INTEGER NOT NULL DEFAULT 0,
    parameter_properties TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS named_expressions (
    named_expression_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL UNIQUE REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    expression_name TEXT NOT NULL,
    scope TEXT,
    expression_language TEXT NOT NULL,
    expression_text TEXT NOT NULL,
    resolved_reference_object_id TEXT REFERENCES analytical_objects(object_id) ON DELETE SET NULL,
    expression_properties TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS filters (
    filter_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL UNIQUE REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    filter_name TEXT NOT NULL,
    filter_type TEXT NOT NULL,
    filter_scope TEXT NOT NULL,
    expression_language TEXT,
    expression_text TEXT,
    filter_operator TEXT,
    filter_values TEXT NOT NULL DEFAULT '{}',
    is_enabled INTEGER NOT NULL DEFAULT 1,
    filter_properties TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS filter_assignments (
    filter_assignment_id TEXT PRIMARY KEY,
    filter_id TEXT NOT NULL REFERENCES filters(filter_id) ON DELETE CASCADE,
    target_object_id TEXT NOT NULL REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    field_object_id TEXT REFERENCES analytical_objects(object_id) ON DELETE SET NULL,
    assignment_scope TEXT NOT NULL,
    assignment_properties TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS security_roles (
    security_role_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL UNIQUE REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    role_name TEXT NOT NULL,
    role_type TEXT NOT NULL,
    role_description TEXT,
    role_properties TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS security_role_filters (
    security_role_filter_id TEXT PRIMARY KEY,
    security_role_id TEXT NOT NULL REFERENCES security_roles(security_role_id) ON DELETE CASCADE,
    target_object_id TEXT NOT NULL REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    expression_language TEXT NOT NULL,
    expression_text TEXT NOT NULL,
    normalised_expression TEXT,
    expression_parse_status TEXT NOT NULL DEFAULT 'UNPARSED',
    rule_properties TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT ck_security_role_filters_status CHECK (expression_parse_status IN ('UNPARSED', 'PARSED', 'PARTIAL', 'UNSUPPORTED', 'FAILED'))
);

CREATE TABLE IF NOT EXISTS security_principals (
    principal_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    source_native_id TEXT,
    principal_name TEXT NOT NULL,
    principal_type TEXT NOT NULL,
    principal_properties TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS security_object_permissions (
    permission_id TEXT PRIMARY KEY,
    target_object_id TEXT NOT NULL REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    principal_id TEXT REFERENCES security_principals(principal_id) ON DELETE CASCADE,
    principal_name TEXT,
    permission_type TEXT NOT NULL,
    permission_source TEXT NOT NULL,
    permission_properties TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS data_sources (
    data_source_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL UNIQUE REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    server_reference TEXT,
    database_reference TEXT,
    schema_reference TEXT,
    connection_mode TEXT,
    query_language TEXT,
    query_text TEXT,
    source_properties TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS query_dependencies (
    query_dependency_id TEXT PRIMARY KEY,
    source_object_id TEXT NOT NULL REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    target_object_id TEXT REFERENCES analytical_objects(object_id) ON DELETE SET NULL,
    target_reference TEXT,
    dependency_type TEXT NOT NULL,
    resolution_status TEXT NOT NULL DEFAULT 'UNRESOLVED',
    dependency_properties TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT ck_query_dependencies_status CHECK (resolution_status IN ('RESOLVED', 'INFERRED', 'UNRESOLVED'))
);

CREATE TABLE IF NOT EXISTS metadata_lineage_edges (
    lineage_edge_id TEXT PRIMARY KEY,
    asset_version_id TEXT NOT NULL REFERENCES asset_versions(asset_version_id) ON DELETE CASCADE,
    source_object_id TEXT NOT NULL,
    target_object_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    derivation_method TEXT NOT NULL,
    confidence_score REAL,
    evidence TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_lineage_edges_distinct CHECK (source_object_id <> target_object_id),
    CONSTRAINT ck_lineage_edges_derivation CHECK (derivation_method IN ('PARSED', 'SOURCE_DECLARED', 'INFERRED', 'MANUAL')),
    CONSTRAINT ck_lineage_edges_confidence CHECK (confidence_score IS NULL OR (confidence_score >= 0.0000 AND confidence_score <= 1.0000)),
    CONSTRAINT fk_lineage_edges_source_version FOREIGN KEY (source_object_id, asset_version_id) REFERENCES analytical_objects(object_id, asset_version_id) ON DELETE CASCADE,
    CONSTRAINT fk_lineage_edges_target_version FOREIGN KEY (target_object_id, asset_version_id) REFERENCES analytical_objects(object_id, asset_version_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS spreadsheet_cells (
    spreadsheet_cell_id TEXT PRIMARY KEY,
    asset_version_id TEXT NOT NULL,
    worksheet_object_id TEXT NOT NULL,
    cell_address TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    column_number INTEGER NOT NULL,
    formula_text TEXT,
    cached_value TEXT,
    data_type TEXT,
    number_format TEXT,
    is_hidden INTEGER NOT NULL DEFAULT 0,
    cell_properties TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT uq_spreadsheet_cells_address UNIQUE (worksheet_object_id, cell_address),
    CONSTRAINT fk_spreadsheet_cells_worksheet_version FOREIGN KEY (worksheet_object_id, asset_version_id) REFERENCES analytical_objects(object_id, asset_version_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pivot_caches (
    pivot_cache_id TEXT PRIMARY KEY,
    asset_version_id TEXT NOT NULL REFERENCES asset_versions(asset_version_id) ON DELETE CASCADE,
    source_native_id TEXT,
    source_type TEXT NOT NULL,
    source_reference TEXT NOT NULL DEFAULT '{}',
    refresh_metadata TEXT NOT NULL DEFAULT '{}',
    cache_properties TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS pivot_tables (
    pivot_table_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL UNIQUE REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    worksheet_object_id TEXT NOT NULL REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    pivot_cache_id TEXT REFERENCES pivot_caches(pivot_cache_id) ON DELETE SET NULL,
    pivot_name TEXT NOT NULL,
    source_reference TEXT NOT NULL DEFAULT '{}',
    pivot_properties TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS pivot_field_assignments (
    pivot_field_assignment_id TEXT PRIMARY KEY,
    pivot_table_id TEXT NOT NULL REFERENCES pivot_tables(pivot_table_id) ON DELETE CASCADE,
    field_object_id TEXT REFERENCES analytical_objects(object_id) ON DELETE SET NULL,
    field_reference TEXT NOT NULL,
    assignment_role TEXT NOT NULL,
    aggregation_type TEXT,
    field_order INTEGER NOT NULL DEFAULT 0,
    assignment_properties TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT ck_pivot_assignments_role CHECK (assignment_role IN ('ROW', 'COLUMN', 'FILTER', 'VALUE', 'PAGE', 'OTHER'))
);

CREATE TABLE IF NOT EXISTS spreadsheet_objects (
    spreadsheet_object_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL UNIQUE REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    worksheet_object_id TEXT NOT NULL REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    object_subtype TEXT NOT NULL,
    range_reference TEXT,
    is_hidden INTEGER NOT NULL DEFAULT 0,
    object_properties TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS spreadsheet_rules (
    spreadsheet_rule_id TEXT PRIMARY KEY,
    object_id TEXT REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    worksheet_object_id TEXT NOT NULL REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    rule_type TEXT NOT NULL,
    range_reference TEXT,
    formula_text TEXT,
    expression_language TEXT,
    rule_properties TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS kpi_ontology_versions (
    ontology_version_id TEXT PRIMARY KEY,
    version_number TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    kpi_count INTEGER NOT NULL DEFAULT 0,
    created_by_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    change_summary TEXT,
    is_active INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS kpi_ontology_entries (
    ontology_entry_id TEXT PRIMARY KEY,
    ontology_version_id TEXT NOT NULL REFERENCES kpi_ontology_versions(ontology_version_id) ON DELETE CASCADE,
    kpi_code TEXT NOT NULL,
    kpi_name TEXT NOT NULL,
    kpi_description TEXT,
    business_domain TEXT NOT NULL,
    definition TEXT NOT NULL,
    formula TEXT,
    unit TEXT,
    aggregation_method TEXT,
    synonyms TEXT NOT NULL DEFAULT '[]',
    source_kpi_id TEXT,
    source_sector TEXT,
    source_subdomain TEXT,
    source_line_of_business TEXT,
    source_status TEXT DEFAULT 'active',
    valid_dimensions TEXT NOT NULL DEFAULT '[]',
    enrichments TEXT NOT NULL DEFAULT '[]',
    source_created_at TEXT,
    source_created_by TEXT,
    ontology_payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_kpi_ontology_entries_code UNIQUE (ontology_version_id, kpi_code),
    CONSTRAINT uq_kpi_ontology_entries_version UNIQUE (ontology_entry_id, ontology_version_id)
);

CREATE TABLE IF NOT EXISTS business_domains (
    domain_id TEXT PRIMARY KEY,
    domain_code TEXT NOT NULL UNIQUE,
    domain_name TEXT NOT NULL UNIQUE,
    domain_description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS domain_classifications (
    classification_id TEXT PRIMARY KEY,
    asset_version_id TEXT NOT NULL,
    target_object_id TEXT NOT NULL,
    domain_id TEXT NOT NULL REFERENCES business_domains(domain_id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    classification_method TEXT NOT NULL,
    confidence_score REAL,
    rationale TEXT,
    is_primary INTEGER NOT NULL DEFAULT 0,
    approval_status TEXT NOT NULL DEFAULT 'PENDING',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_domain_classifications_method CHECK (classification_method IN ('LLM', 'DETERMINISTIC', 'HUMAN', 'INHERITED')),
    CONSTRAINT ck_domain_classifications_status CHECK (approval_status IN ('PENDING', 'APPROVED', 'REJECTED', 'OVERRIDDEN')),
    CONSTRAINT ck_domain_classifications_confidence CHECK (confidence_score IS NULL OR (confidence_score >= 0.0000 AND confidence_score <= 1.0000)),
    CONSTRAINT fk_domain_classifications_object_version FOREIGN KEY (target_object_id, asset_version_id) REFERENCES analytical_objects(object_id, asset_version_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS kpi_candidates (
    kpi_candidate_id TEXT PRIMARY KEY,
    asset_version_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    source_object_id TEXT NOT NULL,
    candidate_name TEXT NOT NULL,
    candidate_description TEXT,
    candidate_expression TEXT,
    expression_language TEXT,
    normalised_expression TEXT,
    candidate_type TEXT,
    unit TEXT,
    aggregation_type TEXT,
    business_domain_id TEXT REFERENCES business_domains(domain_id) ON DELETE SET NULL,
    candidate_evidence TEXT NOT NULL DEFAULT '{}',
    discovery_method TEXT NOT NULL,
    discovery_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_kpi_candidates_version UNIQUE (kpi_candidate_id, asset_version_id),
    CONSTRAINT uq_kpi_candidates_tenant UNIQUE (kpi_candidate_id, tenant_id),
    CONSTRAINT fk_kpi_candidates_version_tenant FOREIGN KEY (asset_version_id, tenant_id) REFERENCES asset_versions(asset_version_id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT fk_kpi_candidates_object_version FOREIGN KEY (source_object_id, asset_version_id) REFERENCES analytical_objects(object_id, asset_version_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS kpi_mapping_runs (
    mapping_run_id TEXT PRIMARY KEY,
    asset_version_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    ontology_version_id TEXT NOT NULL REFERENCES kpi_ontology_versions(ontology_version_id) ON DELETE CASCADE,
    candidate_generation_version TEXT NOT NULL,
    mapping_engine_version TEXT NOT NULL,
    primary_engine TEXT NOT NULL,
    fallback_used INTEGER NOT NULL DEFAULT 0,
    llm_provider TEXT,
    llm_model TEXT,
    prompt_version TEXT,
    input_fingerprint TEXT NOT NULL,
    run_status TEXT NOT NULL DEFAULT 'PENDING',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    error_summary TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_mapping_runs_primary_engine CHECK (primary_engine IN ('LLM', 'DETERMINISTIC')),
    CONSTRAINT ck_mapping_runs_status CHECK (run_status IN ('PENDING', 'RUNNING', 'SUCCESSFUL', 'PARTIAL', 'FAILED', 'CANCELLED')),
    CONSTRAINT uq_kpi_mapping_runs_version UNIQUE (mapping_run_id, asset_version_id, ontology_version_id),
    CONSTRAINT fk_kpi_mapping_runs_version_tenant FOREIGN KEY (asset_version_id, tenant_id) REFERENCES asset_versions(asset_version_id, tenant_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS kpi_mappings (
    kpi_mapping_id TEXT PRIMARY KEY,
    kpi_candidate_id TEXT NOT NULL,
    asset_version_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    mapping_run_id TEXT NOT NULL,
    ontology_version_id TEXT NOT NULL REFERENCES kpi_ontology_versions(ontology_version_id) ON DELETE CASCADE,
    selected_ontology_entry_id TEXT,
    mapping_status TEXT NOT NULL DEFAULT 'PROPOSED',
    decision_source TEXT NOT NULL,
    top_candidate_count INTEGER NOT NULL DEFAULT 0,
    input_fingerprint TEXT NOT NULL,
    mapping_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_kpi_mappings_status CHECK (mapping_status IN ('PROPOSED', 'APPROVED', 'REJECTED', 'OVERRIDDEN', 'UNMAPPED', 'SUPERSEDED')),
    CONSTRAINT ck_kpi_mappings_source CHECK (decision_source IN ('LLM', 'DETERMINISTIC', 'HUMAN')),
    CONSTRAINT ck_kpi_mappings_top_count CHECK (top_candidate_count >= 0 AND top_candidate_count <= 3),
    CONSTRAINT uq_kpi_mappings_run_version UNIQUE (kpi_mapping_id, ontology_version_id),
    CONSTRAINT uq_kpi_mappings_asset_version UNIQUE (kpi_mapping_id, asset_version_id),
    CONSTRAINT uq_kpi_mappings_tenant UNIQUE (kpi_mapping_id, tenant_id),
    CONSTRAINT fk_kpi_mappings_candidate_version FOREIGN KEY (kpi_candidate_id, asset_version_id) REFERENCES kpi_candidates(kpi_candidate_id, asset_version_id) ON DELETE CASCADE,
    CONSTRAINT fk_kpi_mappings_run_version FOREIGN KEY (mapping_run_id, asset_version_id, ontology_version_id) REFERENCES kpi_mapping_runs(mapping_run_id, asset_version_id, ontology_version_id) ON DELETE CASCADE,
    CONSTRAINT fk_kpi_mappings_selected_ontology_entry FOREIGN KEY (selected_ontology_entry_id, ontology_version_id) REFERENCES kpi_ontology_entries(ontology_entry_id, ontology_version_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS kpi_mapping_candidates (
    mapping_candidate_id TEXT PRIMARY KEY,
    kpi_mapping_id TEXT NOT NULL REFERENCES kpi_mappings(kpi_mapping_id) ON DELETE CASCADE,
    ontology_entry_id TEXT NOT NULL REFERENCES kpi_ontology_entries(ontology_entry_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    confidence_score REAL NOT NULL,
    confidence_band TEXT NOT NULL,
    match_score REAL,
    name_similarity_score REAL,
    definition_similarity_score REAL,
    formula_similarity_score REAL,
    context_similarity_score REAL,
    domain_compatibility_score REAL,
    unit_compatibility_score REAL,
    rationale TEXT NOT NULL,
    supporting_evidence TEXT NOT NULL DEFAULT '[]',
    contradicting_evidence TEXT NOT NULL DEFAULT '[]',
    is_recommended INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_mapping_candidates_mapping_entry UNIQUE (kpi_mapping_id, ontology_entry_id),
    CONSTRAINT uq_mapping_candidates_mapping_rank UNIQUE (kpi_mapping_id, rank),
    CONSTRAINT uq_kpi_mapping_candidates_mapping UNIQUE (mapping_candidate_id, kpi_mapping_id),
    CONSTRAINT ck_mapping_candidates_rank CHECK (rank >= 1 AND rank <= 3),
    CONSTRAINT ck_mapping_candidates_confidence CHECK (confidence_score >= 0.0000 AND confidence_score <= 1.0000),
    CONSTRAINT ck_mapping_candidates_band CHECK (confidence_band IN ('HIGH', 'MEDIUM', 'LOW', 'UNCERTAIN')),
    CONSTRAINT ck_mapping_candidates_name_sim CHECK (name_similarity_score IS NULL OR (name_similarity_score >= 0.0000 AND name_similarity_score <= 1.0000)),
    CONSTRAINT ck_mapping_candidates_def_sim CHECK (definition_similarity_score IS NULL OR (definition_similarity_score >= 0.0000 AND definition_similarity_score <= 1.0000)),
    CONSTRAINT ck_mapping_candidates_form_sim CHECK (formula_similarity_score IS NULL OR (formula_similarity_score >= 0.0000 AND formula_similarity_score <= 1.0000)),
    CONSTRAINT ck_mapping_candidates_ctx_sim CHECK (context_similarity_score IS NULL OR (context_similarity_score >= 0.0000 AND context_similarity_score <= 1.0000)),
    CONSTRAINT ck_mapping_candidates_dom_sim CHECK (domain_compatibility_score IS NULL OR (domain_compatibility_score >= 0.0000 AND domain_compatibility_score <= 1.0000)),
    CONSTRAINT ck_mapping_candidates_unit_sim CHECK (unit_compatibility_score IS NULL OR (unit_compatibility_score >= 0.0000 AND unit_compatibility_score <= 1.0000))
);

CREATE TABLE IF NOT EXISTS mapping_evidence (
    mapping_evidence_id TEXT PRIMARY KEY,
    mapping_candidate_id TEXT NOT NULL REFERENCES kpi_mapping_candidates(mapping_candidate_id) ON DELETE CASCADE,
    evidence_type TEXT NOT NULL,
    source_object_id TEXT REFERENCES analytical_objects(object_id) ON DELETE SET NULL,
    evidence_text TEXT NOT NULL,
    evidence_payload TEXT NOT NULL DEFAULT '{}',
    polarity TEXT NOT NULL DEFAULT 'SUPPORTS',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_mapping_evidence_polarity CHECK (polarity IN ('SUPPORTS', 'CONTRADICTS', 'NEUTRAL'))
);

CREATE TABLE IF NOT EXISTS mapping_reviews (
    mapping_review_id TEXT PRIMARY KEY,
    kpi_mapping_id TEXT NOT NULL REFERENCES kpi_mappings(kpi_mapping_id) ON DELETE CASCADE,
    mapping_candidate_id TEXT,
    reviewer_user_id TEXT NOT NULL,
    review_action TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'COMPLETED',
    review_comment TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_mapping_reviews_action CHECK (review_action IN ('APPROVE', 'REJECT', 'CHOOSE_ANOTHER', 'ADD_KPI', 'REQUEST_REMAPPING', 'MARK_UNMAPPED')),
    CONSTRAINT ck_mapping_reviews_status CHECK (review_status IN ('PENDING', 'COMPLETED', 'WITHDRAWN')),
    CONSTRAINT fk_mapping_reviews_candidate_mapping FOREIGN KEY (mapping_candidate_id, kpi_mapping_id) REFERENCES kpi_mapping_candidates(mapping_candidate_id, kpi_mapping_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS mapping_approvals (
    mapping_approval_id TEXT PRIMARY KEY,
    kpi_mapping_id TEXT NOT NULL REFERENCES kpi_mappings(kpi_mapping_id) ON DELETE CASCADE,
    approved_mapping_candidate_id TEXT,
    approved_by_user_id TEXT NOT NULL,
    approval_status TEXT NOT NULL DEFAULT 'APPROVED',
    approval_version INTEGER NOT NULL DEFAULT 1,
    approved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TEXT,
    revocation_reason TEXT,
    CONSTRAINT ck_mapping_approvals_status CHECK (approval_status IN ('APPROVED', 'REVOKED', 'SUPERSEDED')),
    CONSTRAINT fk_mapping_approvals_candidate_mapping FOREIGN KEY (approved_mapping_candidate_id, kpi_mapping_id) REFERENCES kpi_mapping_candidates(mapping_candidate_id, kpi_mapping_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS mapping_overrides (
    override_id TEXT PRIMARY KEY,
    kpi_mapping_id TEXT NOT NULL REFERENCES kpi_mappings(kpi_mapping_id) ON DELETE CASCADE,
    mapping_candidate_id TEXT,
    override_type TEXT NOT NULL,
    previous_ontology_entry_id TEXT REFERENCES kpi_ontology_entries(ontology_entry_id) ON DELETE SET NULL,
    replacement_ontology_entry_id TEXT REFERENCES kpi_ontology_entries(ontology_entry_id) ON DELETE SET NULL,
    override_justification TEXT NOT NULL,
    normalised_justification TEXT NOT NULL,
    justification_hash TEXT NOT NULL,
    created_by_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1,
    supersedes_override_id TEXT REFERENCES mapping_overrides(override_id) ON DELETE SET NULL,
    CONSTRAINT ck_mapping_overrides_type CHECK (override_type IN ('REJECT', 'SELECT_ALTERNATIVE', 'ADD_KPI', 'FORCE_UNMAPPED', 'REMAP', 'OTHER')),
    CONSTRAINT ck_mapping_overrides_justification_not_empty CHECK (length(trim(override_justification)) > 0),
    CONSTRAINT fk_mapping_overrides_candidate_mapping FOREIGN KEY (mapping_candidate_id, kpi_mapping_id) REFERENCES kpi_mapping_candidates(mapping_candidate_id, kpi_mapping_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS metadata_field_reviews (
    field_review_id TEXT PRIMARY KEY,
    asset_version_id TEXT NOT NULL,
    target_object_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    field_path TEXT NOT NULL,
    source_value_hash TEXT NOT NULL,
    proposed_value TEXT NOT NULL,
    approved_value TEXT,
    review_status TEXT NOT NULL DEFAULT 'PENDING',
    reviewed_by_user_id TEXT,
    reviewed_at TEXT,
    override_justification TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_field_reviews_status CHECK (review_status IN ('PENDING', 'APPROVED', 'REJECTED', 'OVERRIDDEN')),
    CONSTRAINT fk_metadata_field_reviews_object_version FOREIGN KEY (target_object_id, asset_version_id) REFERENCES analytical_objects(object_id, asset_version_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS kpi_equivalence_candidates (
    equivalence_candidate_id TEXT PRIMARY KEY,
    source_kpi_candidate_id TEXT NOT NULL REFERENCES kpi_candidates(kpi_candidate_id) ON DELETE CASCADE,
    target_kpi_candidate_id TEXT NOT NULL REFERENCES kpi_candidates(kpi_candidate_id) ON DELETE CASCADE,
    comparison_type TEXT NOT NULL,
    name_similarity_score REAL,
    definition_similarity_score REAL,
    formula_similarity_score REAL,
    unit_compatibility_score REAL,
    dependency_similarity_score REAL,
    equivalence_score REAL NOT NULL,
    evidence TEXT NOT NULL DEFAULT '{}',
    review_status TEXT NOT NULL DEFAULT 'PROPOSED',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_equivalence_candidates_distinct CHECK (source_kpi_candidate_id <> target_kpi_candidate_id),
    CONSTRAINT ck_equivalence_candidates_score CHECK (equivalence_score >= 0.0000 AND equivalence_score <= 1.0000),
    CONSTRAINT ck_equivalence_status CHECK (review_status IN ('PROPOSED', 'APPROVED', 'REJECTED', 'SUPERSEDED')),
    CONSTRAINT ck_equivalence_name_sim CHECK (name_similarity_score IS NULL OR (name_similarity_score >= 0.0000 AND name_similarity_score <= 1.0000)),
    CONSTRAINT ck_equivalence_def_sim CHECK (definition_similarity_score IS NULL OR (definition_similarity_score >= 0.0000 AND definition_similarity_score <= 1.0000)),
    CONSTRAINT ck_equivalence_form_sim CHECK (formula_similarity_score IS NULL OR (formula_similarity_score >= 0.0000 AND formula_similarity_score <= 1.0000)),
    CONSTRAINT ck_equivalence_unit_sim CHECK (unit_compatibility_score IS NULL OR (unit_compatibility_score >= 0.0000 AND unit_compatibility_score <= 1.0000)),
    CONSTRAINT ck_equivalence_dep_sim CHECK (dependency_similarity_score IS NULL OR (dependency_similarity_score >= 0.0000 AND dependency_similarity_score <= 1.0000))
);

CREATE TABLE IF NOT EXISTS kpi_rationalisation_decisions (
    rationalisation_decision_id TEXT PRIMARY KEY,
    equivalence_candidate_id TEXT NOT NULL REFERENCES kpi_equivalence_candidates(equivalence_candidate_id) ON DELETE CASCADE,
    decision_type TEXT NOT NULL,
    canonical_kpi_candidate_id TEXT REFERENCES kpi_candidates(kpi_candidate_id) ON DELETE SET NULL,
    approved_by_user_id TEXT NOT NULL,
    decision_justification TEXT NOT NULL,
    decision_status TEXT NOT NULL DEFAULT 'PROPOSED',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_rationalisation_decisions_type CHECK (decision_type IN ('MERGE', 'CONSOLIDATE', 'RETAIN_SEPARATELY', 'REJECT')),
    CONSTRAINT ck_rationalisation_decisions_status CHECK (decision_status IN ('PROPOSED', 'APPROVED', 'REJECTED', 'EXECUTED', 'REVERSED'))
);

CREATE TABLE IF NOT EXISTS rationalisation_evidence (
    rationalisation_evidence_id TEXT PRIMARY KEY,
    rationalisation_decision_id TEXT NOT NULL REFERENCES kpi_rationalisation_decisions(rationalisation_decision_id) ON DELETE CASCADE,
    evidence_type TEXT NOT NULL,
    evidence_text TEXT NOT NULL,
    evidence_payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS platform_capabilities (
    platform_capability_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    metadata_type TEXT NOT NULL,
    capability_status TEXT NOT NULL,
    minimum_source_version TEXT,
    maximum_source_version TEXT,
    notes TEXT,
    capability_properties TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT uq_platform_capabilities UNIQUE (platform, artifact_type, metadata_type),
    CONSTRAINT ck_platform_capabilities_platform CHECK (platform IN ('POWER_BI', 'TABLEAU', 'EXCEL', 'THOUGHTSPOT', 'MICROSTRATEGY')),
    CONSTRAINT ck_platform_capabilities_status CHECK (capability_status IN ('SUPPORTED', 'PARTIAL', 'UNSUPPORTED', 'RUNTIME_DEPENDENT'))
);

CREATE TABLE IF NOT EXISTS parser_runs (
    parser_run_id TEXT PRIMARY KEY,
    asset_version_id TEXT NOT NULL REFERENCES asset_versions(asset_version_id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    source_artifact_id TEXT REFERENCES source_artifacts(source_artifact_id) ON DELETE SET NULL,
    platform TEXT NOT NULL,
    parser_name TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    run_status TEXT NOT NULL DEFAULT 'PENDING',
    objects_extracted INTEGER NOT NULL DEFAULT 0,
    warnings_count INTEGER NOT NULL DEFAULT 0,
    errors_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    run_metadata TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT ck_parser_runs_status CHECK (run_status IN ('PENDING', 'RUNNING', 'SUCCESSFUL', 'PARTIAL', 'FAILED', 'SKIPPED'))
);

CREATE TABLE IF NOT EXISTS extraction_errors (
    extraction_error_id TEXT PRIMARY KEY,
    parser_run_id TEXT NOT NULL REFERENCES parser_runs(parser_run_id) ON DELETE CASCADE,
    source_artifact_id TEXT REFERENCES source_artifacts(source_artifact_id) ON DELETE SET NULL,
    object_locator TEXT NOT NULL DEFAULT '{}',
    severity TEXT NOT NULL,
    error_code TEXT NOT NULL,
    error_message TEXT NOT NULL,
    is_recoverable INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_extraction_errors_severity CHECK (severity IN ('INFO', 'WARNING', 'ERROR', 'FATAL'))
);

CREATE TABLE IF NOT EXISTS object_tags (
    object_tag_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL REFERENCES analytical_objects(object_id) ON DELETE CASCADE,
    tag_name TEXT NOT NULL,
    tag_value TEXT,
    tag_source TEXT NOT NULL DEFAULT 'SOURCE',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_object_tags_source CHECK (tag_source IN ('SOURCE', 'CANONICAL', 'INFERRED', 'USER'))
);

CREATE TABLE IF NOT EXISTS mapping_audit_events (
    mapping_audit_event_id TEXT PRIMARY KEY,
    kpi_mapping_id TEXT REFERENCES kpi_mappings(kpi_mapping_id) ON DELETE RESTRICT,
    target_kpi_mapping_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    actor_user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    previous_state TEXT NOT NULL DEFAULT '{}',
    new_state TEXT NOT NULL DEFAULT '{}',
    event_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ontology_change_events (
    ontology_change_event_id TEXT PRIMARY KEY,
    ontology_version_id TEXT NOT NULL REFERENCES kpi_ontology_versions(ontology_version_id) ON DELETE RESTRICT,
    ontology_entry_id TEXT REFERENCES kpi_ontology_entries(ontology_entry_id) ON DELETE SET NULL,
    actor_user_id TEXT NOT NULL,
    change_type TEXT NOT NULL,
    previous_payload TEXT,
    new_payload TEXT,
    change_justification TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_ontology_change_type CHECK (change_type IN ('ADD', 'UPDATE', 'DEPRECATE', 'RESTORE', 'IMPORT'))
);

-- ============================================================================
-- INDEXES
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_reports_lifecycle_status ON reports (lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_reports_owner_id ON reports (owner_id) WHERE owner_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_reports_last_accessed_at ON reports (last_accessed_at) WHERE last_accessed_at IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_security_principals_native ON security_principals (tenant_id, platform, source_native_id) WHERE source_native_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_security_principals_name ON security_principals (tenant_id, platform, principal_name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kpi_ontology_versions_is_active ON kpi_ontology_versions (is_active) WHERE (is_active = 1);
CREATE UNIQUE INDEX IF NOT EXISTS uq_domain_classifications_primary ON domain_classifications (asset_version_id, target_object_id) WHERE (is_primary = 1 AND approval_status <> 'REJECTED');
CREATE UNIQUE INDEX IF NOT EXISTS uq_mapping_approvals_active ON mapping_approvals (kpi_mapping_id) WHERE (approval_status = 'APPROVED');
CREATE UNIQUE INDEX IF NOT EXISTS uq_kpi_equivalence_candidates_pair ON kpi_equivalence_candidates ( MIN(source_kpi_candidate_id, target_kpi_candidate_id), MAX(source_kpi_candidate_id, target_kpi_candidate_id) );
CREATE UNIQUE INDEX IF NOT EXISTS uq_object_tags ON object_tags (object_id, tag_name, COALESCE(tag_value, ''));
CREATE INDEX IF NOT EXISTS idx_assets_tenant_platform_name ON assets (tenant_id, platform, asset_name);
CREATE INDEX IF NOT EXISTS idx_asset_versions_content_hash ON asset_versions (asset_id, content_hash);
CREATE INDEX IF NOT EXISTS idx_asset_versions_structure_hash ON asset_versions (asset_id, structure_hash);
CREATE INDEX IF NOT EXISTS idx_ingestion_events_version_created ON ingestion_events (asset_version_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_source_artifacts_version_type ON source_artifacts (asset_version_id, artifact_type);
CREATE INDEX IF NOT EXISTS idx_analytical_objects_version_type ON analytical_objects (asset_version_id, object_type);
CREATE INDEX IF NOT EXISTS idx_analytical_objects_platform_native ON analytical_objects (platform, source_native_id);
CREATE INDEX IF NOT EXISTS idx_analytical_objects_parent ON analytical_objects (parent_object_id);
CREATE INDEX IF NOT EXISTS idx_analytical_objects_canonical_trgm ON analytical_objects (canonical_name);
CREATE INDEX IF NOT EXISTS idx_report_pages_report ON report_pages (report_id);
CREATE INDEX IF NOT EXISTS idx_visuals_page ON visuals (page_id);
CREATE INDEX IF NOT EXISTS idx_visual_bindings_visual ON visual_bindings (visual_id);
CREATE INDEX IF NOT EXISTS idx_visual_bindings_object ON visual_bindings (object_id);
CREATE INDEX IF NOT EXISTS idx_data_tables_model_name ON data_tables (semantic_model_id, table_name);
CREATE INDEX IF NOT EXISTS idx_data_columns_table_name ON data_columns (data_table_id, column_name);
CREATE INDEX IF NOT EXISTS idx_calculations_model_type ON calculations (semantic_model_id, calculation_type);
CREATE INDEX IF NOT EXISTS idx_calculations_lang_parse ON calculations (expression_language, expression_parse_status);
CREATE INDEX IF NOT EXISTS idx_relationships_tables ON relationships (from_table_id, to_table_id);
CREATE INDEX IF NOT EXISTS idx_hierarchy_levels_hierarchy ON hierarchy_levels (hierarchy_id);
CREATE INDEX IF NOT EXISTS idx_filters_object ON filters (object_id);
CREATE INDEX IF NOT EXISTS idx_filter_assignments_target ON filter_assignments (target_object_id);
CREATE INDEX IF NOT EXISTS idx_security_role_filters_role ON security_role_filters (security_role_id);
CREATE INDEX IF NOT EXISTS idx_lineage_edges_source_type ON metadata_lineage_edges (source_object_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_lineage_edges_target_type ON metadata_lineage_edges (target_object_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_lineage_edges_version ON metadata_lineage_edges (asset_version_id);
CREATE INDEX IF NOT EXISTS idx_query_deps_source ON query_dependencies (source_object_id);
CREATE INDEX IF NOT EXISTS idx_query_deps_target ON query_dependencies (target_object_id);
CREATE INDEX IF NOT EXISTS idx_spreadsheet_cells_lookup ON spreadsheet_cells (worksheet_object_id, row_number, column_number);
CREATE INDEX IF NOT EXISTS idx_pivot_tables_worksheet ON pivot_tables (worksheet_object_id);
CREATE INDEX IF NOT EXISTS idx_pivot_field_assignments_pivot ON pivot_field_assignments (pivot_table_id);
CREATE INDEX IF NOT EXISTS idx_kpi_ontology_entries_version_code ON kpi_ontology_entries (ontology_version_id, kpi_code);
CREATE INDEX IF NOT EXISTS idx_kpi_ontology_entries_name_trgm ON kpi_ontology_entries (kpi_name);
CREATE INDEX IF NOT EXISTS idx_kpi_ontology_entries_source_kpi_id ON kpi_ontology_entries (ontology_version_id, source_kpi_id);
CREATE INDEX IF NOT EXISTS idx_kpi_ontology_entries_sector_subdomain ON kpi_ontology_entries (source_sector, source_subdomain);
CREATE INDEX IF NOT EXISTS idx_domain_classifications_target_status ON domain_classifications (target_object_id, approval_status);
CREATE INDEX IF NOT EXISTS idx_domain_classifications_version ON domain_classifications (asset_version_id);
CREATE INDEX IF NOT EXISTS idx_kpi_candidates_version_name ON kpi_candidates (asset_version_id, candidate_name);
CREATE INDEX IF NOT EXISTS idx_kpi_candidates_source_object ON kpi_candidates (source_object_id);
CREATE INDEX IF NOT EXISTS idx_kpi_candidates_name_trgm ON kpi_candidates (candidate_name);
CREATE INDEX IF NOT EXISTS idx_kpi_mapping_runs_version ON kpi_mapping_runs (asset_version_id, ontology_version_id);
CREATE INDEX IF NOT EXISTS idx_kpi_mapping_runs_fingerprint ON kpi_mapping_runs (input_fingerprint);
CREATE INDEX IF NOT EXISTS idx_kpi_mappings_candidate_status ON kpi_mappings (kpi_candidate_id, mapping_status);
CREATE INDEX IF NOT EXISTS idx_kpi_mappings_run ON kpi_mappings (mapping_run_id);
CREATE INDEX IF NOT EXISTS idx_kpi_mapping_candidates_mapping_rank ON kpi_mapping_candidates (kpi_mapping_id, rank);
CREATE INDEX IF NOT EXISTS idx_mapping_evidence_candidate ON mapping_evidence (mapping_candidate_id);
CREATE INDEX IF NOT EXISTS idx_mapping_reviews_mapping ON mapping_reviews (kpi_mapping_id);
CREATE INDEX IF NOT EXISTS idx_mapping_approvals_mapping_status ON mapping_approvals (kpi_mapping_id, approval_status);
CREATE INDEX IF NOT EXISTS idx_mapping_overrides_mapping_active ON mapping_overrides (kpi_mapping_id, is_active);
CREATE INDEX IF NOT EXISTS idx_mapping_overrides_justification_hash ON mapping_overrides (justification_hash);
CREATE INDEX IF NOT EXISTS idx_mapping_overrides_justification_trgm ON mapping_overrides (normalised_justification);
CREATE INDEX IF NOT EXISTS idx_mapping_overrides_justification_fts ON mapping_overrides (override_justification);
CREATE INDEX IF NOT EXISTS idx_metadata_field_reviews_version_status ON metadata_field_reviews (asset_version_id, review_status);
CREATE INDEX IF NOT EXISTS idx_kpi_equivalence_source_target ON kpi_equivalence_candidates (source_kpi_candidate_id, target_kpi_candidate_id);
CREATE INDEX IF NOT EXISTS idx_kpi_equivalence_target_source ON kpi_equivalence_candidates (target_kpi_candidate_id, source_kpi_candidate_id);
CREATE INDEX IF NOT EXISTS idx_rationalisation_decisions_equiv ON kpi_rationalisation_decisions (equivalence_candidate_id);
CREATE INDEX IF NOT EXISTS idx_parser_runs_version_status ON parser_runs (asset_version_id, run_status);
CREATE INDEX IF NOT EXISTS idx_extraction_errors_run_severity ON extraction_errors (parser_run_id, severity);
CREATE INDEX IF NOT EXISTS idx_object_tags_object ON object_tags (object_id);
CREATE INDEX IF NOT EXISTS idx_mapping_audit_events_mapping ON mapping_audit_events (kpi_mapping_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ontology_change_events_version ON ontology_change_events (ontology_version_id, created_at DESC);

-- ============================================================================
-- SEED DATA: BUSINESS DOMAINS
-- ============================================================================
INSERT INTO business_domains (domain_id, domain_code, domain_name, domain_description, is_active)
VALUES
    ('a0000000-0000-0000-0000-000000000001', 'CLAIMS_RISK', 'Claims & Risk', 'Insurance claims processing, reserve modeling, loss adjusting, fraud detection, and risk assessment.', 1),
    ('a0000000-0000-0000-0000-000000000002', 'LEGAL', 'Legal', 'Litigation tracking, regulatory compliance, contract management, disputes, and legal spend.', 1),
    ('a0000000-0000-0000-0000-000000000003', 'UNDERWRITING', 'Underwriting', 'Risk selection, policy pricing, capacity allocation, guideline adherence, and exposure analysis.', 1),
    ('a0000000-0000-0000-0000-000000000004', 'SALES_DISTRIBUTION', 'Sales & Distribution', 'Broker/agent performance, commissions, pipeline tracking, customer acquisition, and distribution channel analytics.', 1),
    ('a0000000-0000-0000-0000-000000000005', 'SERVICE_OPERATIONS', 'Service & Operations', 'Policyholder servicing, call center operations, SLA performance, operational efficiency, and transaction turnaround time.', 1),
    ('a0000000-0000-0000-0000-000000000006', 'ACTUARIAL', 'Actuarial', 'Pricing models, loss reserving, capital adequacy, solvency modeling, mortality/morbidity tables, and catastrophe risk analysis.', 1)
ON CONFLICT (domain_code) DO UPDATE
SET domain_name = excluded.domain_name,
    domain_description = excluded.domain_description,
    is_active = excluded.is_active;
