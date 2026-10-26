-- ============================================================================
-- KPI INTELLIGENCE PLATFORM — CANONICAL DATA MODEL DDL
-- Subsystem: Canonical Metadata Repository (PostgreSQL 15+)
-- Schema: kpi_intel
-- Description: Complete production-grade DDL defining all 61 canonical tables,
--              constraints, indexes, triggers, seed data, and foreign keys.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- ----------------------------------------------------------------------------
-- 1. EXTENSIONS & SCHEMA INITIALIZATION
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gist";

CREATE SCHEMA IF NOT EXISTS kpi_intel;

SET search_path = kpi_intel, public;

-- ----------------------------------------------------------------------------
-- 2. UTILITY FUNCTIONS & PROCEDURES
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION kpi_intel.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = clock_timestamp();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SUBSYSTEM A: ASSET REGISTRY
-- ============================================================================

-- 1. assets
-- Represents the logical analytical asset independently of individual uploads.
CREATE TABLE kpi_intel.assets (
    asset_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    platform TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    asset_name TEXT NOT NULL,
    asset_description TEXT,
    source_native_id TEXT,
    source_native_path TEXT,
    source_version TEXT,
    created_at_source TIMESTAMPTZ,
    modified_at_source TIMESTAMPTZ,
    first_ingested_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    last_ingested_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    -- Foreign key to asset_versions added via ALTER TABLE
    current_version_id UUID,
    lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_assets_platform CHECK (platform IN ('POWER_BI', 'TABLEAU', 'EXCEL', 'THOUGHTSPOT', 'MICROSTRATEGY')),
    CONSTRAINT ck_assets_lifecycle_status CHECK (lifecycle_status IN ('ACTIVE', 'ARCHIVED', 'DELETED', 'SUPERSEDED'))
);

COMMENT ON TABLE kpi_intel.assets IS 'Represents logical analytical assets (e.g. workbook, project, report package) across BI platforms.';
COMMENT ON COLUMN kpi_intel.assets.current_version_id IS 'Points to the currently active or resolved asset version.';
COMMENT ON COLUMN kpi_intel.assets.tenant_id IS 'Logical tenant boundary for multi-tenant isolation.';

CREATE TRIGGER trg_assets_updated_at
BEFORE UPDATE ON kpi_intel.assets
FOR EACH ROW EXECUTE FUNCTION kpi_intel.set_updated_at();

-- 2. asset_versions
-- Immutable versions of an asset representing a specific content/metadata state.
CREATE TABLE kpi_intel.asset_versions (
    asset_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id UUID NOT NULL REFERENCES kpi_intel.assets(asset_id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    raw_content_hash TEXT NOT NULL,
    structure_hash TEXT NOT NULL,
    metadata_hash TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    source_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    extraction_status TEXT NOT NULL DEFAULT 'PENDING',
    extraction_started_at TIMESTAMPTZ,
    extraction_completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_asset_versions_asset_version_number UNIQUE (asset_id, version_number),
    CONSTRAINT ck_asset_versions_status CHECK (extraction_status IN ('PENDING', 'SUCCESSFUL', 'PARTIAL', 'FAILED'))
);

COMMENT ON TABLE kpi_intel.asset_versions IS 'Immutable snapshots of asset metadata and file structural definitions.';

-- Add circular foreign key from assets to asset_versions now that asset_versions exists
ALTER TABLE kpi_intel.assets
ADD CONSTRAINT fk_assets_current_version
FOREIGN KEY (current_version_id)
REFERENCES kpi_intel.asset_versions(asset_version_id)
ON DELETE SET NULL;

-- 3. ingestion_events
-- Records each upload or ingestion attempt independently of version creation.
CREATE TABLE kpi_intel.ingestion_events (
    ingestion_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_version_id UUID REFERENCES kpi_intel.asset_versions(asset_version_id) ON DELETE SET NULL,
    uploaded_by_user_id UUID NOT NULL,
    original_filename TEXT NOT NULL,
    upload_size_bytes BIGINT NOT NULL,
    upload_source TEXT NOT NULL,
    ingestion_status TEXT NOT NULL DEFAULT 'RECEIVED',
    error_code TEXT,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_ingestion_events_status CHECK (ingestion_status IN ('RECEIVED', 'VALIDATING', 'EXTRACTING', 'COMPLETED', 'FAILED'))
);

COMMENT ON TABLE kpi_intel.ingestion_events IS 'Audit ledger of physical uploads and ingestion pipeline processing executions.';

-- 4. source_artifacts
-- Individual files within a source project, package, or archive.
CREATE TABLE kpi_intel.source_artifacts (
    source_artifact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_version_id UUID NOT NULL REFERENCES kpi_intel.asset_versions(asset_version_id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    source_native_id TEXT,
    content_hash TEXT NOT NULL,
    mime_type TEXT,
    size_bytes BIGINT NOT NULL,
    is_supported BOOLEAN NOT NULL DEFAULT true,
    extraction_status TEXT NOT NULL DEFAULT 'PENDING',
    extraction_notes JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_source_artifacts_version_path UNIQUE (asset_version_id, relative_path),
    CONSTRAINT ck_source_artifacts_status CHECK (extraction_status IN ('PENDING', 'SUCCESSFUL', 'PARTIAL', 'SKIPPED', 'FAILED'))
);

COMMENT ON TABLE kpi_intel.source_artifacts IS 'File-level manifest of source artifacts (e.g. .pbir, .tmdl, .twb, worksheet xml).';


-- ============================================================================
-- SUBSYSTEM B: UNIVERSAL ANALYTICAL OBJECTS
-- ============================================================================

-- 5. analytical_objects
-- Universal identity registry for all BI metadata objects across all platforms.
CREATE TABLE kpi_intel.analytical_objects (
    object_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_version_id UUID NOT NULL REFERENCES kpi_intel.asset_versions(asset_version_id) ON DELETE CASCADE,
    parent_object_id UUID REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    source_artifact_id UUID REFERENCES kpi_intel.source_artifacts(source_artifact_id) ON DELETE SET NULL,
    platform TEXT NOT NULL,
    object_type TEXT NOT NULL,
    source_native_id TEXT,
    source_native_name TEXT,
    canonical_name TEXT NOT NULL,
    display_name TEXT,
    description TEXT,
    source_path TEXT,
    source_locator JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_hidden BOOLEAN NOT NULL DEFAULT false,
    is_active BOOLEAN NOT NULL DEFAULT true,
    extraction_status TEXT NOT NULL DEFAULT 'EXTRACTED',
    metadata_completeness NUMERIC(5,4),
    source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_analytical_objects_platform CHECK (platform IN ('POWER_BI', 'TABLEAU', 'EXCEL', 'THOUGHTSPOT', 'MICROSTRATEGY')),
    CONSTRAINT ck_analytical_objects_status CHECK (extraction_status IN ('EXTRACTED', 'PARTIAL', 'INFERRED', 'UNRESOLVED', 'FAILED')),
    CONSTRAINT ck_analytical_objects_completeness CHECK (metadata_completeness IS NULL OR (metadata_completeness >= 0.0000 AND metadata_completeness <= 1.0000))
);

COMMENT ON TABLE kpi_intel.analytical_objects IS 'Universal polymorphous identity registry for all discovered BI metadata entities.';

CREATE TRIGGER trg_analytical_objects_updated_at
BEFORE UPDATE ON kpi_intel.analytical_objects
FOR EACH ROW EXECUTE FUNCTION kpi_intel.set_updated_at();

-- 6. reports
-- Specialized analytical report or dashboard representation.
CREATE TABLE kpi_intel.reports (
    report_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID NOT NULL UNIQUE REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    report_type TEXT NOT NULL,
    report_definition JSONB NOT NULL DEFAULT '{}'::jsonb,
    default_page_object_id UUID REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE SET NULL,
    page_count INTEGER NOT NULL DEFAULT 0,
    visual_count INTEGER NOT NULL DEFAULT 0,
    report_configuration JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- 7. report_pages
-- Individual pages, tabs, canvas sheets, or story points within a report.
CREATE TABLE kpi_intel.report_pages (
    page_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id UUID NOT NULL REFERENCES kpi_intel.reports(report_id) ON DELETE CASCADE,
    object_id UUID NOT NULL UNIQUE REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    source_native_id TEXT,
    page_name TEXT NOT NULL,
    page_order INTEGER NOT NULL DEFAULT 0,
    page_type TEXT NOT NULL,
    page_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_hidden BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- 8. visuals
-- Visual charts, cards, tables, maps, or containers within a report page.
CREATE TABLE kpi_intel.visuals (
    visual_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id UUID NOT NULL REFERENCES kpi_intel.report_pages(page_id) ON DELETE CASCADE,
    object_id UUID NOT NULL UNIQUE REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    source_native_id TEXT,
    visual_type TEXT NOT NULL,
    visual_title TEXT,
    visual_description TEXT,
    position_x NUMERIC,
    position_y NUMERIC,
    width NUMERIC,
    height NUMERIC,
    z_order INTEGER NOT NULL DEFAULT 0,
    visual_configuration JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_visible BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- 9. visual_bindings
-- Bindings of measures, columns, and dimensions to visual roles/axes.
CREATE TABLE kpi_intel.visual_bindings (
    visual_binding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    visual_id UUID NOT NULL REFERENCES kpi_intel.visuals(visual_id) ON DELETE CASCADE,
    object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    binding_role TEXT NOT NULL,
    binding_order INTEGER NOT NULL DEFAULT 0,
    aggregation_override TEXT,
    format_override TEXT,
    binding_properties JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 10. visual_properties
-- Granular visual-level format properties, conditional formats, and dynamic rules.
CREATE TABLE kpi_intel.visual_properties (
    visual_property_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    visual_id UUID NOT NULL REFERENCES kpi_intel.visuals(visual_id) ON DELETE CASCADE,
    property_path TEXT NOT NULL,
    property_value JSONB NOT NULL DEFAULT '{}'::jsonb,
    expression_language TEXT,
    expression_text TEXT,
    source_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_visual_properties_path UNIQUE (visual_id, property_path)
);

-- 11. visual_interactions
-- Cross-filtering, highlighting, and drilling interactions between visual pairs.
CREATE TABLE kpi_intel.visual_interactions (
    visual_interaction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_visual_id UUID NOT NULL REFERENCES kpi_intel.visuals(visual_id) ON DELETE CASCADE,
    target_visual_id UUID NOT NULL REFERENCES kpi_intel.visuals(visual_id) ON DELETE CASCADE,
    interaction_type TEXT NOT NULL,
    interaction_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_visual_interactions_distinct CHECK (source_visual_id <> target_visual_id)
);

-- 12. visual_types
-- Standard mapping taxonomy from platform-native visual identifiers to canonical types.
CREATE TABLE kpi_intel.visual_types (
    visual_type_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform TEXT NOT NULL,
    native_type TEXT NOT NULL,
    canonical_type TEXT NOT NULL,
    description TEXT,
    type_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_visual_types_platform_native UNIQUE (platform, native_type)
);

-- 13. bookmarks
-- Saved state snapshots, personal views, and visual filters.
CREATE TABLE kpi_intel.bookmarks (
    bookmark_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    source_native_id TEXT,
    bookmark_name TEXT NOT NULL,
    bookmark_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    bookmark_properties JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 14. report_navigation
-- Action links, drill-through targets, URL actions, and page-to-page navigation.
CREATE TABLE kpi_intel.report_navigation (
    report_navigation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    target_object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    navigation_type TEXT NOT NULL,
    navigation_name TEXT,
    navigation_expression TEXT,
    expression_language TEXT,
    navigation_properties JSONB NOT NULL DEFAULT '{}'::jsonb
);


-- ============================================================================
-- SUBSYSTEM C: SEMANTIC MODELS AND CALCULATIONS
-- ============================================================================

-- 15. semantic_models
-- Semantic datasets, cubes, data models, or ThoughtSpot worksheets.
CREATE TABLE kpi_intel.semantic_models (
    semantic_model_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID NOT NULL UNIQUE REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    source_native_id TEXT,
    model_name TEXT NOT NULL,
    model_type TEXT NOT NULL,
    model_version TEXT,
    compatibility_level TEXT,
    model_definition JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_connection_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- 16. data_tables
-- Logical, physical, or calculated tables within a semantic model.
CREATE TABLE kpi_intel.data_tables (
    data_table_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID NOT NULL UNIQUE REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    semantic_model_id UUID NOT NULL REFERENCES kpi_intel.semantic_models(semantic_model_id) ON DELETE CASCADE,
    source_native_id TEXT,
    table_name TEXT NOT NULL,
    schema_name TEXT,
    table_type TEXT NOT NULL,
    description TEXT,
    is_hidden BOOLEAN NOT NULL DEFAULT false,
    storage_mode TEXT,
    source_reference JSONB NOT NULL DEFAULT '{}'::jsonb,
    table_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- 17. data_columns
-- Columns belonging to data tables, including physical and calculated columns.
CREATE TABLE kpi_intel.data_columns (
    data_column_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID NOT NULL UNIQUE REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    data_table_id UUID NOT NULL REFERENCES kpi_intel.data_tables(data_table_id) ON DELETE CASCADE,
    source_native_id TEXT,
    column_name TEXT NOT NULL,
    display_name TEXT,
    data_type TEXT NOT NULL,
    source_data_type TEXT,
    description TEXT,
    semantic_role TEXT,
    is_nullable BOOLEAN NOT NULL DEFAULT true,
    is_hidden BOOLEAN NOT NULL DEFAULT false,
    is_calculated BOOLEAN NOT NULL DEFAULT false,
    default_aggregation TEXT,
    format_string TEXT,
    column_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- 18. calculations
-- Measures, calculated columns, metrics, and formula expressions.
CREATE TABLE kpi_intel.calculations (
    calculation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID NOT NULL UNIQUE REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    semantic_model_id UUID REFERENCES kpi_intel.semantic_models(semantic_model_id) ON DELETE CASCADE,
    data_table_id UUID REFERENCES kpi_intel.data_tables(data_table_id) ON DELETE SET NULL,
    data_column_id UUID REFERENCES kpi_intel.data_columns(data_column_id) ON DELETE SET NULL,
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
    expression_ast JSONB NOT NULL DEFAULT '{}'::jsonb,
    expression_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_calculations_parse_status CHECK (expression_parse_status IN ('UNPARSED', 'PARSED', 'PARTIAL', 'UNSUPPORTED', 'FAILED'))
);

-- 19. relationships
-- Joins, relationships, and active cross-table navigation in the semantic model.
CREATE TABLE kpi_intel.relationships (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID NOT NULL UNIQUE REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,
    from_table_id UUID REFERENCES kpi_intel.data_tables(data_table_id) ON DELETE CASCADE,
    to_table_id UUID REFERENCES kpi_intel.data_tables(data_table_id) ON DELETE CASCADE,
    from_object_id UUID REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    to_object_id UUID REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    cardinality TEXT NOT NULL,
    join_type TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    cross_filter_direction TEXT,
    relationship_expression TEXT,
    relationship_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_relationships_endpoints CHECK (
        (from_table_id IS NOT NULL AND to_table_id IS NOT NULL) OR
        (from_object_id IS NOT NULL AND to_object_id IS NOT NULL)
    )
);

-- 20. model_partitions
-- Physical partitions, query partitions, or incremental load ranges.
CREATE TABLE kpi_intel.model_partitions (
    model_partition_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    semantic_model_id UUID NOT NULL REFERENCES kpi_intel.semantic_models(semantic_model_id) ON DELETE CASCADE,
    source_native_id TEXT,
    partition_name TEXT NOT NULL,
    source_type TEXT,
    expression_language TEXT,
    expression_text TEXT,
    partition_properties JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 21. hierarchies
-- Dimensional hierarchies defined within semantic models.
CREATE TABLE kpi_intel.hierarchies (
    hierarchy_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID NOT NULL UNIQUE REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    semantic_model_id UUID NOT NULL REFERENCES kpi_intel.semantic_models(semantic_model_id) ON DELETE CASCADE,
    hierarchy_name TEXT NOT NULL,
    hierarchy_type TEXT NOT NULL,
    hierarchy_properties JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 22. hierarchy_levels
-- Ordered levels within a dimensional hierarchy.
CREATE TABLE kpi_intel.hierarchy_levels (
    hierarchy_level_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hierarchy_id UUID NOT NULL REFERENCES kpi_intel.hierarchies(hierarchy_id) ON DELETE CASCADE,
    level_object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    level_name TEXT NOT NULL,
    level_order INTEGER NOT NULL,
    level_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_hierarchy_levels_order UNIQUE (hierarchy_id, level_order)
);

-- 23. parameters
-- What-if parameters, report parameters, or query variables.
CREATE TABLE kpi_intel.parameters (
    parameter_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID NOT NULL UNIQUE REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    parameter_name TEXT NOT NULL,
    data_type TEXT NOT NULL,
    default_value JSONB,
    allowed_values JSONB,
    is_required BOOLEAN NOT NULL DEFAULT false,
    parameter_properties JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 24. named_expressions
-- Power Query / M shared queries, named calculations, or semantic constants.
CREATE TABLE kpi_intel.named_expressions (
    named_expression_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID NOT NULL UNIQUE REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    expression_name TEXT NOT NULL,
    scope TEXT,
    expression_language TEXT NOT NULL,
    expression_text TEXT NOT NULL,
    resolved_reference_object_id UUID REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE SET NULL,
    expression_properties JSONB NOT NULL DEFAULT '{}'::jsonb
);


-- ============================================================================
-- SUBSYSTEM D: FILTERS, SECURITY, DATA SOURCES, AND LINEAGE
-- ============================================================================

-- 25. filters
-- Standard report, page, visual, and model-level filtering predicates.
CREATE TABLE kpi_intel.filters (
    filter_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID NOT NULL UNIQUE REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    filter_name TEXT NOT NULL,
    filter_type TEXT NOT NULL,
    filter_scope TEXT NOT NULL,
    expression_language TEXT,
    expression_text TEXT,
    filter_operator TEXT,
    filter_values JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    filter_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- 26. filter_assignments
-- Association of filters to specific target objects and filtered fields.
CREATE TABLE kpi_intel.filter_assignments (
    filter_assignment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filter_id UUID NOT NULL REFERENCES kpi_intel.filters(filter_id) ON DELETE CASCADE,
    target_object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    field_object_id UUID REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE SET NULL,
    assignment_scope TEXT NOT NULL,
    assignment_properties JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 27. security_roles
-- Row-level security (RLS) or object-level security (OLS) role declarations.
CREATE TABLE kpi_intel.security_roles (
    security_role_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID NOT NULL UNIQUE REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    role_name TEXT NOT NULL,
    role_type TEXT NOT NULL,
    role_description TEXT,
    role_properties JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 28. security_role_filters
-- Security predicate expressions restricting table rows or columns for a role.
CREATE TABLE kpi_intel.security_role_filters (
    security_role_filter_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    security_role_id UUID NOT NULL REFERENCES kpi_intel.security_roles(security_role_id) ON DELETE CASCADE,
    target_object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    expression_language TEXT NOT NULL,
    expression_text TEXT NOT NULL,
    normalised_expression TEXT,
    expression_parse_status TEXT NOT NULL DEFAULT 'UNPARSED',
    rule_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_security_role_filters_status CHECK (expression_parse_status IN ('UNPARSED', 'PARSED', 'PARTIAL', 'UNSUPPORTED', 'FAILED'))
);

-- 29. security_principals
-- Users, groups, roles, or service principals referenced in permissions.
CREATE TABLE kpi_intel.security_principals (
    principal_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    platform TEXT NOT NULL,
    source_native_id TEXT,
    principal_name TEXT NOT NULL,
    principal_type TEXT NOT NULL,
    principal_properties JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Unique constraints handling nullable source_native_id
CREATE UNIQUE INDEX uq_security_principals_native 
ON kpi_intel.security_principals (tenant_id, platform, source_native_id) 
WHERE source_native_id IS NOT NULL;

CREATE UNIQUE INDEX uq_security_principals_name 
ON kpi_intel.security_principals (tenant_id, platform, principal_name) 
WHERE source_native_id IS NULL;

-- 30. security_object_permissions
-- Explicit permissions granted on analytical objects to security principals.
CREATE TABLE kpi_intel.security_object_permissions (
    permission_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    principal_id UUID REFERENCES kpi_intel.security_principals(principal_id) ON DELETE CASCADE,
    principal_name TEXT,
    permission_type TEXT NOT NULL,
    permission_source TEXT NOT NULL,
    permission_properties JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 31. data_sources
-- Underlying databases, warehouses, extracts, or APIs feeding semantic models.
CREATE TABLE kpi_intel.data_sources (
    data_source_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID NOT NULL UNIQUE REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    server_reference TEXT,
    database_reference TEXT,
    schema_reference TEXT,
    connection_mode TEXT,
    query_language TEXT,
    query_text TEXT,
    source_properties JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 32. query_dependencies
-- Query-to-query, view-to-table, or M-query reference dependencies.
CREATE TABLE kpi_intel.query_dependencies (
    query_dependency_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    target_object_id UUID REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE SET NULL,
    target_reference TEXT,
    dependency_type TEXT NOT NULL,
    resolution_status TEXT NOT NULL DEFAULT 'UNRESOLVED',
    dependency_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_query_dependencies_status CHECK (resolution_status IN ('RESOLVED', 'INFERRED', 'UNRESOLVED'))
);

-- 33. metadata_lineage_edges
-- Directed graph of fine-grained metadata lineage across analytical objects.
CREATE TABLE kpi_intel.metadata_lineage_edges (
    lineage_edge_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_version_id UUID NOT NULL REFERENCES kpi_intel.asset_versions(asset_version_id) ON DELETE CASCADE,
    source_object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    target_object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL,
    derivation_method TEXT NOT NULL,
    confidence_score NUMERIC(5,4),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_lineage_edges_distinct CHECK (source_object_id <> target_object_id),
    CONSTRAINT ck_lineage_edges_derivation CHECK (derivation_method IN ('PARSED', 'SOURCE_DECLARED', 'INFERRED', 'MANUAL')),
    CONSTRAINT ck_lineage_edges_confidence CHECK (confidence_score IS NULL OR (confidence_score >= 0.0000 AND confidence_score <= 1.0000))
);


-- ============================================================================
-- SUBSYSTEM E: EXCEL-SPECIFIC METADATA
-- ============================================================================

-- 34. spreadsheet_cells
-- Granular cell coordinates, formulas, and cached evaluation snapshots in XLSX.
CREATE TABLE kpi_intel.spreadsheet_cells (
    spreadsheet_cell_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_version_id UUID NOT NULL REFERENCES kpi_intel.asset_versions(asset_version_id) ON DELETE CASCADE,
    worksheet_object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    cell_address TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    column_number INTEGER NOT NULL,
    formula_text TEXT,
    cached_value JSONB,
    data_type TEXT,
    number_format TEXT,
    is_hidden BOOLEAN NOT NULL DEFAULT false,
    cell_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_spreadsheet_cells_address UNIQUE (worksheet_object_id, cell_address)
);

-- 35. pivot_caches
-- PivotTable underlying data cache definitions and connection links.
CREATE TABLE kpi_intel.pivot_caches (
    pivot_cache_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_version_id UUID NOT NULL REFERENCES kpi_intel.asset_versions(asset_version_id) ON DELETE CASCADE,
    source_native_id TEXT,
    source_type TEXT NOT NULL,
    source_reference JSONB NOT NULL DEFAULT '{}'::jsonb,
    refresh_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    cache_properties JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 36. pivot_tables
-- PivotTable visual layouts and report views in Excel worksheets.
CREATE TABLE kpi_intel.pivot_tables (
    pivot_table_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID NOT NULL UNIQUE REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    worksheet_object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    pivot_cache_id UUID REFERENCES kpi_intel.pivot_caches(pivot_cache_id) ON DELETE SET NULL,
    pivot_name TEXT NOT NULL,
    source_reference JSONB NOT NULL DEFAULT '{}'::jsonb,
    pivot_properties JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 37. pivot_field_assignments
-- Pivot field roles (Row, Column, Value, Filter, Page) and aggregations.
CREATE TABLE kpi_intel.pivot_field_assignments (
    pivot_field_assignment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pivot_table_id UUID NOT NULL REFERENCES kpi_intel.pivot_tables(pivot_table_id) ON DELETE CASCADE,
    field_object_id UUID REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE SET NULL,
    field_reference TEXT NOT NULL,
    assignment_role TEXT NOT NULL,
    aggregation_type TEXT,
    field_order INTEGER NOT NULL DEFAULT 0,
    assignment_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_pivot_assignments_role CHECK (assignment_role IN ('ROW', 'COLUMN', 'FILTER', 'VALUE', 'PAGE', 'OTHER'))
);

-- 38. spreadsheet_objects
-- Named ranges, shapes, hyperlinks, and chart objects embedded in sheets.
CREATE TABLE kpi_intel.spreadsheet_objects (
    spreadsheet_object_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID NOT NULL UNIQUE REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    worksheet_object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    object_subtype TEXT NOT NULL,
    range_reference TEXT,
    is_hidden BOOLEAN NOT NULL DEFAULT false,
    object_properties JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 39. spreadsheet_rules
-- Conditional formatting rules, data validation rules, and cell constraints.
CREATE TABLE kpi_intel.spreadsheet_rules (
    spreadsheet_rule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    worksheet_object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    rule_type TEXT NOT NULL,
    range_reference TEXT,
    formula_text TEXT,
    expression_language TEXT,
    rule_properties JSONB NOT NULL DEFAULT '{}'::jsonb
);


-- ============================================================================
-- SUBSYSTEM F: KPI ONTOLOGY AND DOMAIN CLASSIFICATION
-- ============================================================================

-- 40. kpi_ontology_versions
-- Version registry for the local 550+ KPI Ontology Bank.
CREATE TABLE kpi_intel.kpi_ontology_versions (
    ontology_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_number TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    kpi_count INTEGER NOT NULL DEFAULT 0,
    created_by_user_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    change_summary TEXT,
    is_active BOOLEAN NOT NULL DEFAULT false
);

-- Enforce exactly at most one active ontology version across the system
CREATE UNIQUE INDEX uq_kpi_ontology_versions_is_active 
ON kpi_intel.kpi_ontology_versions (is_active) 
WHERE (is_active = true);

-- 41. kpi_ontology_entries
-- Canonical KPI definitions preserved from the local JSON ontology bank.
CREATE TABLE kpi_intel.kpi_ontology_entries (
    ontology_entry_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ontology_version_id UUID NOT NULL REFERENCES kpi_intel.kpi_ontology_versions(ontology_version_id) ON DELETE CASCADE,
    kpi_code TEXT NOT NULL,
    kpi_name TEXT NOT NULL,
    kpi_description TEXT,
    business_domain TEXT NOT NULL,
    definition TEXT NOT NULL,
    formula TEXT,
    unit TEXT,
    aggregation_method TEXT,
    synonyms JSONB NOT NULL DEFAULT '[]'::jsonb,
    ontology_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_kpi_ontology_entries_code UNIQUE (ontology_version_id, kpi_code)
);

-- 42. business_domains
-- Canonical business domains used for categorization and access scoping.
CREATE TABLE kpi_intel.business_domains (
    domain_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_code TEXT NOT NULL UNIQUE,
    domain_name TEXT NOT NULL UNIQUE,
    domain_description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true
);

-- 43. domain_classifications
-- Classifications of assets, reports, pages, visuals, and KPI candidates into domains.
CREATE TABLE kpi_intel.domain_classifications (
    classification_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_version_id UUID NOT NULL REFERENCES kpi_intel.asset_versions(asset_version_id) ON DELETE CASCADE,
    target_object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    domain_id UUID NOT NULL REFERENCES kpi_intel.business_domains(domain_id) ON DELETE CASCADE,
    classification_method TEXT NOT NULL,
    confidence_score NUMERIC(5,4),
    rationale TEXT,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    approval_status TEXT NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_domain_classifications_method CHECK (classification_method IN ('LLM', 'DETERMINISTIC', 'HUMAN', 'INHERITED')),
    CONSTRAINT ck_domain_classifications_status CHECK (approval_status IN ('PENDING', 'APPROVED', 'REJECTED', 'OVERRIDDEN')),
    CONSTRAINT ck_domain_classifications_confidence CHECK (confidence_score IS NULL OR (confidence_score >= 0.0000 AND confidence_score <= 1.0000))
);

-- Enforce at most one effective primary domain per target object and version
CREATE UNIQUE INDEX uq_domain_classifications_primary 
ON kpi_intel.domain_classifications (asset_version_id, target_object_id) 
WHERE (is_primary = true AND approval_status <> 'REJECTED');

CREATE TRIGGER trg_domain_classifications_updated_at
BEFORE UPDATE ON kpi_intel.domain_classifications
FOR EACH ROW EXECUTE FUNCTION kpi_intel.set_updated_at();


-- ============================================================================
-- SUBSYSTEM G: KPI CANDIDATES AND MAPPING
-- ============================================================================

-- 44. kpi_candidates
-- Source calculations, measures, or visual cards discovered as potential KPIs.
CREATE TABLE kpi_intel.kpi_candidates (
    kpi_candidate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_version_id UUID NOT NULL REFERENCES kpi_intel.asset_versions(asset_version_id) ON DELETE CASCADE,
    source_object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    candidate_name TEXT NOT NULL,
    candidate_description TEXT,
    candidate_expression TEXT,
    expression_language TEXT,
    normalised_expression TEXT,
    candidate_type TEXT,
    unit TEXT,
    aggregation_type TEXT,
    business_domain_id UUID REFERENCES kpi_intel.business_domains(domain_id) ON DELETE SET NULL,
    candidate_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    discovery_method TEXT NOT NULL,
    discovery_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- 45. kpi_mapping_runs
-- Batch execution record of ontology matching (LLM or deterministic fallback).
CREATE TABLE kpi_intel.kpi_mapping_runs (
    mapping_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_version_id UUID NOT NULL REFERENCES kpi_intel.asset_versions(asset_version_id) ON DELETE CASCADE,
    ontology_version_id UUID NOT NULL REFERENCES kpi_intel.kpi_ontology_versions(ontology_version_id) ON DELETE CASCADE,
    candidate_generation_version TEXT NOT NULL,
    mapping_engine_version TEXT NOT NULL,
    primary_engine TEXT NOT NULL,
    fallback_used BOOLEAN NOT NULL DEFAULT false,
    llm_provider TEXT,
    llm_model TEXT,
    prompt_version TEXT,
    input_fingerprint TEXT NOT NULL,
    run_status TEXT NOT NULL DEFAULT 'PENDING',
    started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ,
    error_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_mapping_runs_primary_engine CHECK (primary_engine IN ('LLM', 'DETERMINISTIC')),
    CONSTRAINT ck_mapping_runs_status CHECK (run_status IN ('PENDING', 'RUNNING', 'SUCCESSFUL', 'PARTIAL', 'FAILED', 'CANCELLED'))
);

-- 46. kpi_mappings
-- Current mapping relationship between a source candidate and the ontology bank.
CREATE TABLE kpi_intel.kpi_mappings (
    kpi_mapping_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kpi_candidate_id UUID NOT NULL REFERENCES kpi_intel.kpi_candidates(kpi_candidate_id) ON DELETE CASCADE,
    mapping_run_id UUID NOT NULL REFERENCES kpi_intel.kpi_mapping_runs(mapping_run_id) ON DELETE CASCADE,
    ontology_version_id UUID NOT NULL REFERENCES kpi_intel.kpi_ontology_versions(ontology_version_id) ON DELETE CASCADE,
    selected_ontology_entry_id UUID REFERENCES kpi_intel.kpi_ontology_entries(ontology_entry_id) ON DELETE SET NULL,
    mapping_status TEXT NOT NULL DEFAULT 'PROPOSED',
    decision_source TEXT NOT NULL,
    top_candidate_count INTEGER NOT NULL DEFAULT 0,
    input_fingerprint TEXT NOT NULL,
    mapping_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_kpi_mappings_status CHECK (mapping_status IN ('PROPOSED', 'APPROVED', 'REJECTED', 'OVERRIDDEN', 'UNMAPPED', 'SUPERSEDED')),
    CONSTRAINT ck_kpi_mappings_source CHECK (decision_source IN ('LLM', 'DETERMINISTIC', 'HUMAN')),
    CONSTRAINT ck_kpi_mappings_top_count CHECK (top_candidate_count >= 0 AND top_candidate_count <= 3)
);

CREATE TRIGGER trg_kpi_mappings_updated_at
BEFORE UPDATE ON kpi_intel.kpi_mappings
FOR EACH ROW EXECUTE FUNCTION kpi_intel.set_updated_at();

-- 47. kpi_mapping_candidates
-- Ranked proposals (maximum top 3) from the matching engines.
CREATE TABLE kpi_intel.kpi_mapping_candidates (
    mapping_candidate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kpi_mapping_id UUID NOT NULL REFERENCES kpi_intel.kpi_mappings(kpi_mapping_id) ON DELETE CASCADE,
    ontology_entry_id UUID NOT NULL REFERENCES kpi_intel.kpi_ontology_entries(ontology_entry_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    confidence_score NUMERIC(5,4) NOT NULL,
    confidence_band TEXT NOT NULL,
    match_score NUMERIC,
    name_similarity_score NUMERIC(5,4),
    definition_similarity_score NUMERIC(5,4),
    formula_similarity_score NUMERIC(5,4),
    context_similarity_score NUMERIC(5,4),
    domain_compatibility_score NUMERIC(5,4),
    unit_compatibility_score NUMERIC(5,4),
    rationale TEXT NOT NULL,
    supporting_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    contradicting_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_recommended BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_mapping_candidates_mapping_entry UNIQUE (kpi_mapping_id, ontology_entry_id),
    CONSTRAINT uq_mapping_candidates_mapping_rank UNIQUE (kpi_mapping_id, rank),
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

-- 48. mapping_evidence
-- Granular evidence items supporting or contradicting a candidate match.
CREATE TABLE kpi_intel.mapping_evidence (
    mapping_evidence_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mapping_candidate_id UUID NOT NULL REFERENCES kpi_intel.kpi_mapping_candidates(mapping_candidate_id) ON DELETE CASCADE,
    evidence_type TEXT NOT NULL,
    source_object_id UUID REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE SET NULL,
    evidence_text TEXT NOT NULL,
    evidence_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    polarity TEXT NOT NULL DEFAULT 'SUPPORTS',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_mapping_evidence_polarity CHECK (polarity IN ('SUPPORTS', 'CONTRADICTS', 'NEUTRAL'))
);


-- ============================================================================
-- SUBSYSTEM H: HUMAN REVIEW, APPROVAL, OVERRIDES
-- ============================================================================

-- 49. mapping_reviews
-- Review workflow actions taken by human subject matter experts.
CREATE TABLE kpi_intel.mapping_reviews (
    mapping_review_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kpi_mapping_id UUID NOT NULL REFERENCES kpi_intel.kpi_mappings(kpi_mapping_id) ON DELETE CASCADE,
    mapping_candidate_id UUID REFERENCES kpi_intel.kpi_mapping_candidates(mapping_candidate_id) ON DELETE SET NULL,
    reviewer_user_id UUID NOT NULL,
    review_action TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'COMPLETED',
    review_comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_mapping_reviews_action CHECK (review_action IN ('APPROVE', 'REJECT', 'CHOOSE_ANOTHER', 'ADD_KPI', 'REQUEST_REMAPPING', 'MARK_UNMAPPED')),
    CONSTRAINT ck_mapping_reviews_status CHECK (review_status IN ('PENDING', 'COMPLETED', 'WITHDRAWN'))
);

-- 50. mapping_approvals
-- Formal approval ledger; approved mappings become immutable ground truth.
CREATE TABLE kpi_intel.mapping_approvals (
    mapping_approval_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kpi_mapping_id UUID NOT NULL REFERENCES kpi_intel.kpi_mappings(kpi_mapping_id) ON DELETE CASCADE,
    approved_mapping_candidate_id UUID REFERENCES kpi_intel.kpi_mapping_candidates(mapping_candidate_id) ON DELETE SET NULL,
    approved_by_user_id UUID NOT NULL,
    approval_status TEXT NOT NULL DEFAULT 'APPROVED',
    approval_version INTEGER NOT NULL DEFAULT 1,
    approved_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    revoked_at TIMESTAMPTZ,
    revocation_reason TEXT,
    CONSTRAINT ck_mapping_approvals_status CHECK (approval_status IN ('APPROVED', 'REVOKED', 'SUPERSEDED'))
);

-- Enforce exactly one active approval per mapping
CREATE UNIQUE INDEX uq_mapping_approvals_active 
ON kpi_intel.mapping_approvals (kpi_mapping_id) 
WHERE (approval_status = 'APPROVED');

-- 51. mapping_overrides
-- User overrides of engine proposals with mandatory rationale for learning.
CREATE TABLE kpi_intel.mapping_overrides (
    override_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kpi_mapping_id UUID NOT NULL REFERENCES kpi_intel.kpi_mappings(kpi_mapping_id) ON DELETE CASCADE,
    mapping_candidate_id UUID REFERENCES kpi_intel.kpi_mapping_candidates(mapping_candidate_id) ON DELETE SET NULL,
    override_type TEXT NOT NULL,
    previous_ontology_entry_id UUID REFERENCES kpi_intel.kpi_ontology_entries(ontology_entry_id) ON DELETE SET NULL,
    replacement_ontology_entry_id UUID REFERENCES kpi_intel.kpi_ontology_entries(ontology_entry_id) ON DELETE SET NULL,
    override_justification TEXT NOT NULL,
    normalised_justification TEXT NOT NULL,
    justification_hash TEXT NOT NULL,
    created_by_user_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    is_active BOOLEAN NOT NULL DEFAULT true,
    supersedes_override_id UUID REFERENCES kpi_intel.mapping_overrides(override_id) ON DELETE SET NULL,
    CONSTRAINT ck_mapping_overrides_type CHECK (override_type IN ('REJECT', 'SELECT_ALTERNATIVE', 'ADD_KPI', 'FORCE_UNMAPPED', 'REMAP', 'OTHER')),
    CONSTRAINT ck_mapping_overrides_justification_not_empty CHECK (length(trim(override_justification)) > 0)
);

-- 52. metadata_field_reviews
-- Human overrides and reviews of specific extracted metadata attributes.
CREATE TABLE kpi_intel.metadata_field_reviews (
    field_review_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_version_id UUID NOT NULL REFERENCES kpi_intel.asset_versions(asset_version_id) ON DELETE CASCADE,
    target_object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    field_path TEXT NOT NULL,
    source_value_hash TEXT NOT NULL,
    proposed_value JSONB NOT NULL,
    approved_value JSONB,
    review_status TEXT NOT NULL DEFAULT 'PENDING',
    reviewed_by_user_id UUID,
    reviewed_at TIMESTAMPTZ,
    override_justification TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_field_reviews_status CHECK (review_status IN ('PENDING', 'APPROVED', 'REJECTED', 'OVERRIDDEN'))
);


-- ============================================================================
-- SUBSYSTEM I: KPI RATIONALISATION
-- ============================================================================

-- 53. kpi_equivalence_candidates
-- Identified potential duplicates, redundant calculations, or equivalent metrics.
CREATE TABLE kpi_intel.kpi_equivalence_candidates (
    equivalence_candidate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_kpi_candidate_id UUID NOT NULL REFERENCES kpi_intel.kpi_candidates(kpi_candidate_id) ON DELETE CASCADE,
    target_kpi_candidate_id UUID NOT NULL REFERENCES kpi_intel.kpi_candidates(kpi_candidate_id) ON DELETE CASCADE,
    comparison_type TEXT NOT NULL,
    name_similarity_score NUMERIC(5,4),
    definition_similarity_score NUMERIC(5,4),
    formula_similarity_score NUMERIC(5,4),
    unit_compatibility_score NUMERIC(5,4),
    dependency_similarity_score NUMERIC(5,4),
    equivalence_score NUMERIC(5,4) NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_status TEXT NOT NULL DEFAULT 'PROPOSED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_equivalence_candidates_distinct CHECK (source_kpi_candidate_id <> target_kpi_candidate_id),
    CONSTRAINT ck_equivalence_candidates_score CHECK (equivalence_score >= 0.0000 AND equivalence_score <= 1.0000),
    CONSTRAINT ck_equivalence_status CHECK (review_status IN ('PROPOSED', 'APPROVED', 'REJECTED', 'SUPERSEDED')),
    CONSTRAINT ck_equivalence_name_sim CHECK (name_similarity_score IS NULL OR (name_similarity_score >= 0.0000 AND name_similarity_score <= 1.0000)),
    CONSTRAINT ck_equivalence_def_sim CHECK (definition_similarity_score IS NULL OR (definition_similarity_score >= 0.0000 AND definition_similarity_score <= 1.0000)),
    CONSTRAINT ck_equivalence_form_sim CHECK (formula_similarity_score IS NULL OR (formula_similarity_score >= 0.0000 AND formula_similarity_score <= 1.0000)),
    CONSTRAINT ck_equivalence_unit_sim CHECK (unit_compatibility_score IS NULL OR (unit_compatibility_score >= 0.0000 AND unit_compatibility_score <= 1.0000)),
    CONSTRAINT ck_equivalence_dep_sim CHECK (dependency_similarity_score IS NULL OR (dependency_similarity_score >= 0.0000 AND dependency_similarity_score <= 1.0000))
);

-- Symmetrical uniqueness to prevent candidate pair inversions (A,B) and (B,A)
CREATE UNIQUE INDEX uq_kpi_equivalence_candidates_pair 
ON kpi_intel.kpi_equivalence_candidates (
    LEAST(source_kpi_candidate_id, target_kpi_candidate_id),
    GREATEST(source_kpi_candidate_id, target_kpi_candidate_id)
);

-- 54. kpi_rationalisation_decisions
-- Human-governed consolidation decisions (merge, consolidate, retain, reject).
CREATE TABLE kpi_intel.kpi_rationalisation_decisions (
    rationalisation_decision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    equivalence_candidate_id UUID NOT NULL REFERENCES kpi_intel.kpi_equivalence_candidates(equivalence_candidate_id) ON DELETE CASCADE,
    decision_type TEXT NOT NULL,
    canonical_kpi_candidate_id UUID REFERENCES kpi_intel.kpi_candidates(kpi_candidate_id) ON DELETE SET NULL,
    approved_by_user_id UUID NOT NULL,
    decision_justification TEXT NOT NULL,
    decision_status TEXT NOT NULL DEFAULT 'PROPOSED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_rationalisation_decisions_type CHECK (decision_type IN ('MERGE', 'CONSOLIDATE', 'RETAIN_SEPARATELY', 'REJECT')),
    CONSTRAINT ck_rationalisation_decisions_status CHECK (decision_status IN ('PROPOSED', 'APPROVED', 'REJECTED', 'EXECUTED', 'REVERSED'))
);

CREATE TRIGGER trg_kpi_rationalisation_decisions_updated_at
BEFORE UPDATE ON kpi_intel.kpi_rationalisation_decisions
FOR EACH ROW EXECUTE FUNCTION kpi_intel.set_updated_at();

-- 55. rationalisation_evidence
-- Lineage, visual usage, and calculation proof supporting a rationalisation decision.
CREATE TABLE kpi_intel.rationalisation_evidence (
    rationalisation_evidence_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rationalisation_decision_id UUID NOT NULL REFERENCES kpi_intel.kpi_rationalisation_decisions(rationalisation_decision_id) ON DELETE CASCADE,
    evidence_type TEXT NOT NULL,
    evidence_text TEXT NOT NULL,
    evidence_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);


-- ============================================================================
-- SUBSYSTEM J: OPERATIONS AND AUDIT
-- ============================================================================

-- 56. platform_capabilities
-- Extraction capabilities and feature support matrix across source platforms.
CREATE TABLE kpi_intel.platform_capabilities (
    platform_capability_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    metadata_type TEXT NOT NULL,
    capability_status TEXT NOT NULL,
    minimum_source_version TEXT,
    maximum_source_version TEXT,
    notes TEXT,
    capability_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_platform_capabilities UNIQUE (platform, artifact_type, metadata_type),
    CONSTRAINT ck_platform_capabilities_platform CHECK (platform IN ('POWER_BI', 'TABLEAU', 'EXCEL', 'THOUGHTSPOT', 'MICROSTRATEGY')),
    CONSTRAINT ck_platform_capabilities_status CHECK (capability_status IN ('SUPPORTED', 'PARTIAL', 'UNSUPPORTED', 'RUNTIME_DEPENDENT'))
);

-- 57. parser_runs
-- Execution logs of platform-specific metadata parsing adapters.
CREATE TABLE kpi_intel.parser_runs (
    parser_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_version_id UUID NOT NULL REFERENCES kpi_intel.asset_versions(asset_version_id) ON DELETE CASCADE,
    source_artifact_id UUID REFERENCES kpi_intel.source_artifacts(source_artifact_id) ON DELETE SET NULL,
    platform TEXT NOT NULL,
    parser_name TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    run_status TEXT NOT NULL DEFAULT 'PENDING',
    objects_extracted INTEGER NOT NULL DEFAULT 0,
    warnings_count INTEGER NOT NULL DEFAULT 0,
    errors_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ,
    run_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_parser_runs_status CHECK (run_status IN ('PENDING', 'RUNNING', 'SUCCESSFUL', 'PARTIAL', 'FAILED', 'SKIPPED'))
);

-- 58. extraction_errors
-- Detailed parser warnings, partial failure diagnostics, and syntax errors.
CREATE TABLE kpi_intel.extraction_errors (
    extraction_error_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parser_run_id UUID NOT NULL REFERENCES kpi_intel.parser_runs(parser_run_id) ON DELETE CASCADE,
    source_artifact_id UUID REFERENCES kpi_intel.source_artifacts(source_artifact_id) ON DELETE SET NULL,
    object_locator JSONB NOT NULL DEFAULT '{}'::jsonb,
    severity TEXT NOT NULL,
    error_code TEXT NOT NULL,
    error_message TEXT NOT NULL,
    is_recoverable BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_extraction_errors_severity CHECK (severity IN ('INFO', 'WARNING', 'ERROR', 'FATAL'))
);

-- 59. object_tags
-- Multi-source taxonomy, business tags, and source metadata labels.
CREATE TABLE kpi_intel.object_tags (
    object_tag_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id UUID NOT NULL REFERENCES kpi_intel.analytical_objects(object_id) ON DELETE CASCADE,
    tag_name TEXT NOT NULL,
    tag_value TEXT,
    tag_source TEXT NOT NULL DEFAULT 'SOURCE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_object_tags_source CHECK (tag_source IN ('SOURCE', 'CANONICAL', 'INFERRED', 'USER'))
);

-- Unique index treating NULL tag_value uniformly
CREATE UNIQUE INDEX uq_object_tags 
ON kpi_intel.object_tags (object_id, tag_name, COALESCE(tag_value, ''));

-- 60. mapping_audit_events
-- Complete immutable audit trail of state transitions in the mapping lifecycle.
CREATE TABLE kpi_intel.mapping_audit_events (
    mapping_audit_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kpi_mapping_id UUID NOT NULL REFERENCES kpi_intel.kpi_mappings(kpi_mapping_id) ON DELETE CASCADE,
    actor_user_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    previous_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    new_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    event_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- 61. ontology_change_events
-- Immutable audit log recording additions and modifications to the local ontology.
CREATE TABLE kpi_intel.ontology_change_events (
    ontology_change_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ontology_version_id UUID NOT NULL REFERENCES kpi_intel.kpi_ontology_versions(ontology_version_id) ON DELETE CASCADE,
    ontology_entry_id UUID REFERENCES kpi_intel.kpi_ontology_entries(ontology_entry_id) ON DELETE SET NULL,
    actor_user_id UUID NOT NULL,
    change_type TEXT NOT NULL,
    previous_payload JSONB,
    new_payload JSONB,
    change_justification TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_ontology_change_type CHECK (change_type IN ('ADD', 'UPDATE', 'DEPRECATE', 'RESTORE', 'IMPORT'))
);


-- ============================================================================
-- 3. COMPREHENSIVE PERFORMANCE & ACCESS PATTERN INDEXES
-- ============================================================================

-- Subsystem A Indexes
CREATE INDEX idx_assets_tenant_platform_name ON kpi_intel.assets (tenant_id, platform, asset_name);
CREATE INDEX idx_asset_versions_content_hash ON kpi_intel.asset_versions (asset_id, content_hash);
CREATE INDEX idx_asset_versions_structure_hash ON kpi_intel.asset_versions (asset_id, structure_hash);
CREATE INDEX idx_ingestion_events_version_created ON kpi_intel.ingestion_events (asset_version_id, created_at DESC);
CREATE INDEX idx_source_artifacts_version_type ON kpi_intel.source_artifacts (asset_version_id, artifact_type);

-- Subsystem B Indexes
CREATE INDEX idx_analytical_objects_version_type ON kpi_intel.analytical_objects (asset_version_id, object_type);
CREATE INDEX idx_analytical_objects_platform_native ON kpi_intel.analytical_objects (platform, source_native_id);
CREATE INDEX idx_analytical_objects_parent ON kpi_intel.analytical_objects (parent_object_id);
CREATE INDEX idx_analytical_objects_canonical_trgm ON kpi_intel.analytical_objects USING gin (canonical_name gin_trgm_ops);
CREATE INDEX idx_report_pages_report ON kpi_intel.report_pages (report_id);
CREATE INDEX idx_visuals_page ON kpi_intel.visuals (page_id);
CREATE INDEX idx_visual_bindings_visual ON kpi_intel.visual_bindings (visual_id);
CREATE INDEX idx_visual_bindings_object ON kpi_intel.visual_bindings (object_id);

-- Subsystem C Indexes
CREATE INDEX idx_data_tables_model_name ON kpi_intel.data_tables (semantic_model_id, table_name);
CREATE INDEX idx_data_columns_table_name ON kpi_intel.data_columns (data_table_id, column_name);
CREATE INDEX idx_calculations_model_type ON kpi_intel.calculations (semantic_model_id, calculation_type);
CREATE INDEX idx_calculations_lang_parse ON kpi_intel.calculations (expression_language, expression_parse_status);
CREATE INDEX idx_relationships_tables ON kpi_intel.relationships (from_table_id, to_table_id);
CREATE INDEX idx_hierarchy_levels_hierarchy ON kpi_intel.hierarchy_levels (hierarchy_id);

-- Subsystem D Indexes
CREATE INDEX idx_filters_object ON kpi_intel.filters (object_id);
CREATE INDEX idx_filter_assignments_target ON kpi_intel.filter_assignments (target_object_id);
CREATE INDEX idx_security_role_filters_role ON kpi_intel.security_role_filters (security_role_id);
CREATE INDEX idx_lineage_edges_source_type ON kpi_intel.metadata_lineage_edges (source_object_id, edge_type);
CREATE INDEX idx_lineage_edges_target_type ON kpi_intel.metadata_lineage_edges (target_object_id, edge_type);
CREATE INDEX idx_lineage_edges_version ON kpi_intel.metadata_lineage_edges (asset_version_id);
CREATE INDEX idx_query_deps_source ON kpi_intel.query_dependencies (source_object_id);
CREATE INDEX idx_query_deps_target ON kpi_intel.query_dependencies (target_object_id);

-- Subsystem E Indexes
CREATE INDEX idx_spreadsheet_cells_lookup ON kpi_intel.spreadsheet_cells (worksheet_object_id, row_number, column_number);
CREATE INDEX idx_pivot_tables_worksheet ON kpi_intel.pivot_tables (worksheet_object_id);
CREATE INDEX idx_pivot_field_assignments_pivot ON kpi_intel.pivot_field_assignments (pivot_table_id);

-- Subsystem F Indexes
CREATE INDEX idx_kpi_ontology_entries_version_code ON kpi_intel.kpi_ontology_entries (ontology_version_id, kpi_code);
CREATE INDEX idx_kpi_ontology_entries_name_trgm ON kpi_intel.kpi_ontology_entries USING gin (kpi_name gin_trgm_ops);
CREATE INDEX idx_domain_classifications_target_status ON kpi_intel.domain_classifications (target_object_id, approval_status);
CREATE INDEX idx_domain_classifications_version ON kpi_intel.domain_classifications (asset_version_id);

-- Subsystem G Indexes
CREATE INDEX idx_kpi_candidates_version_name ON kpi_intel.kpi_candidates (asset_version_id, candidate_name);
CREATE INDEX idx_kpi_candidates_source_object ON kpi_intel.kpi_candidates (source_object_id);
CREATE INDEX idx_kpi_candidates_name_trgm ON kpi_intel.kpi_candidates USING gin (candidate_name gin_trgm_ops);
CREATE INDEX idx_kpi_mapping_runs_version ON kpi_intel.kpi_mapping_runs (asset_version_id, ontology_version_id);
CREATE INDEX idx_kpi_mapping_runs_fingerprint ON kpi_intel.kpi_mapping_runs (input_fingerprint);
CREATE INDEX idx_kpi_mappings_candidate_status ON kpi_intel.kpi_mappings (kpi_candidate_id, mapping_status);
CREATE INDEX idx_kpi_mappings_run ON kpi_intel.kpi_mappings (mapping_run_id);
CREATE INDEX idx_kpi_mapping_candidates_mapping_rank ON kpi_intel.kpi_mapping_candidates (kpi_mapping_id, rank);
CREATE INDEX idx_mapping_evidence_candidate ON kpi_intel.mapping_evidence (mapping_candidate_id);

-- Subsystem H Indexes
CREATE INDEX idx_mapping_reviews_mapping ON kpi_intel.mapping_reviews (kpi_mapping_id);
CREATE INDEX idx_mapping_approvals_mapping_status ON kpi_intel.mapping_approvals (kpi_mapping_id, approval_status);
CREATE INDEX idx_mapping_overrides_mapping_active ON kpi_intel.mapping_overrides (kpi_mapping_id, is_active);
CREATE INDEX idx_mapping_overrides_justification_hash ON kpi_intel.mapping_overrides (justification_hash);
CREATE INDEX idx_mapping_overrides_justification_trgm ON kpi_intel.mapping_overrides USING gin (normalised_justification gin_trgm_ops);
CREATE INDEX idx_mapping_overrides_justification_fts ON kpi_intel.mapping_overrides USING gin (to_tsvector('english', override_justification));
CREATE INDEX idx_metadata_field_reviews_version_status ON kpi_intel.metadata_field_reviews (asset_version_id, review_status);

-- Subsystem I Indexes
CREATE INDEX idx_kpi_equivalence_source_target ON kpi_intel.kpi_equivalence_candidates (source_kpi_candidate_id, target_kpi_candidate_id);
CREATE INDEX idx_kpi_equivalence_target_source ON kpi_intel.kpi_equivalence_candidates (target_kpi_candidate_id, source_kpi_candidate_id);
CREATE INDEX idx_rationalisation_decisions_equiv ON kpi_intel.kpi_rationalisation_decisions (equivalence_candidate_id);

-- Subsystem J Indexes
CREATE INDEX idx_parser_runs_version_status ON kpi_intel.parser_runs (asset_version_id, run_status);
CREATE INDEX idx_extraction_errors_run_severity ON kpi_intel.extraction_errors (parser_run_id, severity);
CREATE INDEX idx_object_tags_object ON kpi_intel.object_tags (object_id);
CREATE INDEX idx_mapping_audit_events_mapping ON kpi_intel.mapping_audit_events (kpi_mapping_id, created_at DESC);
CREATE INDEX idx_ontology_change_events_version ON kpi_intel.ontology_change_events (ontology_version_id, created_at DESC);


-- ============================================================================
-- 4. SEED DATA: BUSINESS DOMAINS
-- ============================================================================
INSERT INTO kpi_intel.business_domains (domain_id, domain_code, domain_name, domain_description, is_active)
VALUES
    ('a0000000-0000-0000-0000-000000000001', 'CLAIMS_RISK', 'Claims & Risk', 'Insurance claims processing, reserve modeling, loss adjusting, fraud detection, and risk assessment.', true),
    ('a0000000-0000-0000-0000-000000000002', 'LEGAL', 'Legal', 'Litigation tracking, regulatory compliance, contract management, disputes, and legal spend.', true),
    ('a0000000-0000-0000-0000-000000000003', 'UNDERWRITING', 'Underwriting', 'Risk selection, policy pricing, capacity allocation, guideline adherence, and exposure analysis.', true),
    ('a0000000-0000-0000-0000-000000000004', 'SALES_DISTRIBUTION', 'Sales & Distribution', 'Broker/agent performance, commissions, pipeline tracking, customer acquisition, and distribution channel analytics.', true),
    ('a0000000-0000-0000-0000-000000000005', 'SERVICE_OPERATIONS', 'Service & Operations', 'Policyholder servicing, call center operations, SLA performance, operational efficiency, and transaction turnaround time.', true),
    ('a0000000-0000-0000-0000-000000000006', 'ACTUARIAL', 'Actuarial', 'Pricing models, loss reserving, capital adequacy, solvency modeling, mortality/morbidity tables, and catastrophe risk analysis.', true)
ON CONFLICT (domain_code) DO UPDATE
SET domain_name = EXCLUDED.domain_name,
    domain_description = EXCLUDED.domain_description,
    is_active = EXCLUDED.is_active;

COMMIT;
