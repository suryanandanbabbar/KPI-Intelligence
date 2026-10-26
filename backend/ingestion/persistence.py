"""
KPI Intelligence — Canonical Persistence Service.

Persists normalized canonical metadata bundles into the 61-table PostgreSQL schema.
Enforces:
1. Mandatory transaction-local tenant context (SELECT kpi_intel.set_current_tenant_id(:tenant_id)).
2. Strict topological sorting of analytical objects and foreign key dependencies.
3. Idempotent upserts (ON CONFLICT DO UPDATE).
4. Dual-mode execution (live PostgreSQL execution when available, or declarative SQL emission).
"""

import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from backend.ingestion.models import CanonicalIngestionBundle, CanonicalAnalyticalObject


def _format_sql_value(val: Any) -> str:
    """Formats a Python value as a valid SQL literal."""
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, datetime):
        return f"'{val.isoformat()}'::timestamptz"
    if isinstance(val, uuid.UUID):
        return f"'{str(val)}'::uuid"
    if isinstance(val, (dict, list)):
        dumped = json.dumps(val).replace("'", "''")
        return f"'{dumped}'::jsonb"
    # string
    cleaned = str(val).replace("'", "''")
    return f"'{cleaned}'"


def sort_analytical_objects_topologically(
    objects: List[CanonicalAnalyticalObject]
) -> List[CanonicalAnalyticalObject]:
    """
    Sorts analytical objects so that parent objects are inserted before child objects.
    Prevents self-referential foreign key constraint violations on parent_object_id.
    """
    id_to_obj = {obj.object_id: obj for obj in objects}
    visited = set()
    ordered: List[CanonicalAnalyticalObject] = []

    def visit(obj: CanonicalAnalyticalObject):
        if obj.object_id in visited:
            return
        if obj.parent_object_id and obj.parent_object_id in id_to_obj:
            parent_obj = id_to_obj[obj.parent_object_id]
            visit(parent_obj)
        visited.add(obj.object_id)
        ordered.append(obj)

    for obj in objects:
        visit(obj)

    return ordered


class CanonicalPersistenceService:
    """Manages transactional persistence of CanonicalIngestionBundle to PostgreSQL."""

    def __init__(self, tenant_id: uuid.UUID):
        self.tenant_id = tenant_id

    def generate_transactional_sql(self, bundle: CanonicalIngestionBundle) -> str:
        """
        Compiles the entire ingestion bundle into a single transaction-safe SQL script
        with mandatory transaction-local tenant context and topological dependency ordering.
        """
        statements: List[str] = []
        statements.append("-- ============================================================================")
        statements.append(f"-- KPI Intelligence Ingestion Transaction for Tenant: {self.tenant_id}")
        statements.append("-- ============================================================================")
        statements.append("BEGIN;")
        statements.append(f"SELECT kpi_intel.set_current_tenant_id('{self.tenant_id}'::uuid);")
        statements.append("")

        # 1. assets
        a = bundle.asset
        statements.append(f"""INSERT INTO kpi_intel.assets (
    asset_id, tenant_id, platform, asset_type, asset_name, asset_description,
    source_native_id, source_native_path, source_version, lifecycle_status
) VALUES (
    {_format_sql_value(a.asset_id)}, {_format_sql_value(a.tenant_id)}, {_format_sql_value(a.platform)},
    {_format_sql_value(a.asset_type)}, {_format_sql_value(a.asset_name)}, {_format_sql_value(a.asset_description)},
    {_format_sql_value(a.source_native_id)}, {_format_sql_value(a.source_native_path)}, {_format_sql_value(a.source_version)},
    {_format_sql_value(a.lifecycle_status)}
) ON CONFLICT (asset_id) DO UPDATE SET
    asset_name = EXCLUDED.asset_name,
    asset_description = EXCLUDED.asset_description,
    last_ingested_at = clock_timestamp(),
    updated_at = clock_timestamp();""")

        # 2. asset_versions
        v = bundle.version
        statements.append(f"""INSERT INTO kpi_intel.asset_versions (
    asset_version_id, asset_id, tenant_id, version_number, content_hash, raw_content_hash,
    structure_hash, metadata_hash, parser_version, schema_version, source_manifest, extraction_status
) VALUES (
    {_format_sql_value(v.asset_version_id)}, {_format_sql_value(v.asset_id)}, {_format_sql_value(v.tenant_id)},
    {_format_sql_value(v.version_number)}, {_format_sql_value(v.content_hash)}, {_format_sql_value(v.raw_content_hash)},
    {_format_sql_value(v.structure_hash)}, {_format_sql_value(v.metadata_hash)}, {_format_sql_value(v.parser_version)},
    {_format_sql_value(v.schema_version)}, {_format_sql_value(v.source_manifest)}, {_format_sql_value(v.extraction_status)}
) ON CONFLICT (asset_id, version_number) DO UPDATE SET
    content_hash = EXCLUDED.content_hash,
    extraction_status = EXCLUDED.extraction_status,
    extraction_completed_at = clock_timestamp();""")

        # 3. Update asset.current_version_id
        statements.append(f"""UPDATE kpi_intel.assets
SET current_version_id = {_format_sql_value(v.asset_version_id)}
WHERE asset_id = {_format_sql_value(a.asset_id)} AND tenant_id = {_format_sql_value(a.tenant_id)};""")

        # 4. source_artifacts
        for art in bundle.artifacts:
            statements.append(f"""INSERT INTO kpi_intel.source_artifacts (
    source_artifact_id, asset_version_id, relative_path, artifact_type,
    content_hash, size_bytes, is_supported, extraction_status
) VALUES (
    {_format_sql_value(art.source_artifact_id)}, {_format_sql_value(art.asset_version_id)}, {_format_sql_value(art.relative_path)},
    {_format_sql_value(art.artifact_type)}, {_format_sql_value(art.content_hash)}, {_format_sql_value(art.size_bytes)},
    {_format_sql_value(art.is_supported)}, {_format_sql_value(art.extraction_status)}
) ON CONFLICT (asset_version_id, relative_path) DO UPDATE SET
    content_hash = EXCLUDED.content_hash,
    extraction_status = EXCLUDED.extraction_status;""")

        # 5. analytical_objects (Topologically sorted)
        sorted_objects = sort_analytical_objects_topologically(bundle.objects)
        for obj in sorted_objects:
            statements.append(f"""INSERT INTO kpi_intel.analytical_objects (
    object_id, asset_version_id, tenant_id, parent_object_id, source_artifact_id,
    platform, object_type, source_native_id, source_native_name, canonical_name,
    display_name, description, is_hidden, is_active, source_metadata
) VALUES (
    {_format_sql_value(obj.object_id)}, {_format_sql_value(obj.asset_version_id)}, {_format_sql_value(obj.tenant_id)},
    {_format_sql_value(obj.parent_object_id)}, {_format_sql_value(obj.source_artifact_id)}, {_format_sql_value(obj.platform)},
    {_format_sql_value(obj.object_type)}, {_format_sql_value(obj.source_native_id)}, {_format_sql_value(obj.source_native_name)},
    {_format_sql_value(obj.canonical_name)}, {_format_sql_value(obj.display_name)}, {_format_sql_value(obj.description)},
    {_format_sql_value(obj.is_hidden)}, {_format_sql_value(obj.is_active)}, {_format_sql_value(obj.source_metadata)}
) ON CONFLICT (object_id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    canonical_name = EXCLUDED.canonical_name,
    is_active = EXCLUDED.is_active,
    updated_at = clock_timestamp();""")

        # 6. reports
        for rep in bundle.reports:
            statements.append(f"""INSERT INTO kpi_intel.reports (
    report_id, object_id, report_type, report_definition, page_count, visual_count,
    report_configuration, owner_id, owner_name, last_accessed_at, lifecycle_status
) VALUES (
    {_format_sql_value(rep.report_id)}, {_format_sql_value(rep.object_id)}, {_format_sql_value(rep.report_type)},
    {_format_sql_value(rep.report_definition)}, {_format_sql_value(rep.page_count)}, {_format_sql_value(rep.visual_count)},
    {_format_sql_value(rep.report_configuration)}, {_format_sql_value(rep.owner_id)}, {_format_sql_value(rep.owner_name)},
    {_format_sql_value(rep.last_accessed_at)}, {_format_sql_value(rep.lifecycle_status)}
) ON CONFLICT (object_id) DO UPDATE SET
    page_count = EXCLUDED.page_count,
    visual_count = EXCLUDED.visual_count,
    report_definition = EXCLUDED.report_definition,
    owner_id = COALESCE(EXCLUDED.owner_id, kpi_intel.reports.owner_id),
    owner_name = COALESCE(EXCLUDED.owner_name, kpi_intel.reports.owner_name),
    last_accessed_at = COALESCE(EXCLUDED.last_accessed_at, kpi_intel.reports.last_accessed_at),
    lifecycle_status = kpi_intel.classify_report_lifecycle(
        COALESCE(EXCLUDED.owner_id, kpi_intel.reports.owner_id),
        COALESCE(EXCLUDED.last_accessed_at, kpi_intel.reports.last_accessed_at)
    );""")

        # 7. report_pages
        for page in bundle.pages:
            statements.append(f"""INSERT INTO kpi_intel.report_pages (
    page_id, report_id, object_id, source_native_id, page_name, page_order, page_type, page_properties, is_hidden
) VALUES (
    {_format_sql_value(page.page_id)}, {_format_sql_value(page.report_id)}, {_format_sql_value(page.object_id)},
    {_format_sql_value(page.source_native_id)}, {_format_sql_value(page.page_name)}, {_format_sql_value(page.page_order)},
    {_format_sql_value(page.page_type)}, {_format_sql_value(page.page_properties)}, {_format_sql_value(page.is_hidden)}
) ON CONFLICT (object_id) DO UPDATE SET
    page_name = EXCLUDED.page_name,
    page_order = EXCLUDED.page_order;""")

        # 8. visuals
        for vis in bundle.visuals:
            statements.append(f"""INSERT INTO kpi_intel.visuals (
    visual_id, page_id, object_id, source_native_id, visual_type, visual_title, visual_description,
    position_x, position_y, width, height, z_order, visual_configuration, is_visible
) VALUES (
    {_format_sql_value(vis.visual_id)}, {_format_sql_value(vis.page_id)}, {_format_sql_value(vis.object_id)},
    {_format_sql_value(vis.source_native_id)}, {_format_sql_value(vis.visual_type)}, {_format_sql_value(vis.visual_title)},
    {_format_sql_value(vis.visual_description)}, {_format_sql_value(vis.position_x)}, {_format_sql_value(vis.position_y)},
    {_format_sql_value(vis.width)}, {_format_sql_value(vis.height)}, {_format_sql_value(vis.z_order)},
    {_format_sql_value(vis.visual_configuration)}, {_format_sql_value(vis.is_visible)}
) ON CONFLICT (object_id) DO UPDATE SET
    visual_title = EXCLUDED.visual_title,
    visual_configuration = EXCLUDED.visual_configuration;""")

        # 9. visual_bindings
        for vb in bundle.visual_bindings:
            statements.append(f"""INSERT INTO kpi_intel.visual_bindings (
    visual_binding_id, visual_id, object_id, binding_role, binding_order,
    aggregation_override, format_override, binding_properties
) VALUES (
    {_format_sql_value(vb.visual_binding_id)}, {_format_sql_value(vb.visual_id)}, {_format_sql_value(vb.object_id)},
    {_format_sql_value(vb.binding_role)}, {_format_sql_value(vb.binding_order)},
    {_format_sql_value(vb.aggregation_override)}, {_format_sql_value(vb.format_override)},
    {_format_sql_value(vb.binding_properties)}
) ON CONFLICT (visual_binding_id) DO NOTHING;""")

        # 10. bookmarks
        for bm in bundle.bookmarks:
            statements.append(f"""INSERT INTO kpi_intel.bookmarks (
    bookmark_id, object_id, source_native_id, bookmark_name, bookmark_state
) VALUES (
    {_format_sql_value(bm.bookmark_id)}, {_format_sql_value(bm.object_id)}, {_format_sql_value(bm.source_native_id)},
    {_format_sql_value(bm.bookmark_name)}, {_format_sql_value(bm.bookmark_state)}
) ON CONFLICT (bookmark_id) DO NOTHING;""")

        # 11. semantic_models
        for sm in bundle.semantic_models:
            statements.append(f"""INSERT INTO kpi_intel.semantic_models (
    semantic_model_id, object_id, source_native_id, model_name, model_type, compatibility_level, model_definition
) VALUES (
    {_format_sql_value(sm.semantic_model_id)}, {_format_sql_value(sm.object_id)}, {_format_sql_value(sm.source_native_id)},
    {_format_sql_value(sm.model_name)}, {_format_sql_value(sm.model_type)}, {_format_sql_value(sm.compatibility_level)},
    {_format_sql_value(sm.model_definition)}
) ON CONFLICT (object_id) DO UPDATE SET
    compatibility_level = EXCLUDED.compatibility_level,
    model_definition = EXCLUDED.model_definition;""")

        # 12. data_tables
        for tbl in bundle.tables:
            statements.append(f"""INSERT INTO kpi_intel.data_tables (
    data_table_id, object_id, semantic_model_id, source_native_id, table_name,
    table_type, description, is_hidden, storage_mode, table_properties
) VALUES (
    {_format_sql_value(tbl.data_table_id)}, {_format_sql_value(tbl.object_id)}, {_format_sql_value(tbl.semantic_model_id)},
    {_format_sql_value(tbl.source_native_id)}, {_format_sql_value(tbl.table_name)}, {_format_sql_value(tbl.table_type)},
    {_format_sql_value(tbl.description)}, {_format_sql_value(tbl.is_hidden)}, {_format_sql_value(tbl.storage_mode)},
    {_format_sql_value(tbl.table_properties)}
) ON CONFLICT (object_id) DO UPDATE SET
    table_name = EXCLUDED.table_name,
    table_type = EXCLUDED.table_type,
    table_properties = EXCLUDED.table_properties;""")

        # 13. data_columns
        for col in bundle.columns:
            statements.append(f"""INSERT INTO kpi_intel.data_columns (
    data_column_id, object_id, data_table_id, source_native_id, column_name, display_name,
    data_type, source_data_type, is_nullable, is_hidden, is_calculated, default_aggregation,
    format_string, column_properties
) VALUES (
    {_format_sql_value(col.data_column_id)}, {_format_sql_value(col.object_id)}, {_format_sql_value(col.data_table_id)},
    {_format_sql_value(col.source_native_id)}, {_format_sql_value(col.column_name)}, {_format_sql_value(col.display_name)},
    {_format_sql_value(col.data_type)}, {_format_sql_value(col.source_data_type)}, {_format_sql_value(col.is_nullable)},
    {_format_sql_value(col.is_hidden)}, {_format_sql_value(col.is_calculated)}, {_format_sql_value(col.default_aggregation)},
    {_format_sql_value(col.format_string)}, {_format_sql_value(col.column_properties)}
) ON CONFLICT (object_id) DO UPDATE SET
    data_type = EXCLUDED.data_type,
    format_string = EXCLUDED.format_string,
    column_properties = EXCLUDED.column_properties;""")

        # 14. calculations
        for calc in bundle.calculations:
            statements.append(f"""INSERT INTO kpi_intel.calculations (
    calculation_id, object_id, semantic_model_id, data_table_id, data_column_id,
    calculation_name, calculation_type, expression_language, expression_text,
    format_string, description, expression_parse_status
) VALUES (
    {_format_sql_value(calc.calculation_id)}, {_format_sql_value(calc.object_id)}, {_format_sql_value(calc.semantic_model_id)},
    {_format_sql_value(calc.data_table_id)}, {_format_sql_value(calc.data_column_id)}, {_format_sql_value(calc.calculation_name)},
    {_format_sql_value(calc.calculation_type)}, {_format_sql_value(calc.expression_language)}, {_format_sql_value(calc.expression_text)},
    {_format_sql_value(calc.format_string)}, {_format_sql_value(calc.description)}, {_format_sql_value(calc.expression_parse_status)}
) ON CONFLICT (object_id) DO UPDATE SET
    expression_text = EXCLUDED.expression_text,
    format_string = EXCLUDED.format_string;""")

        # 15. relationships
        for rel in bundle.relationships:
            statements.append(f"""INSERT INTO kpi_intel.relationships (
    relationship_id, object_id, relationship_type, from_table_id, to_table_id,
    from_object_id, to_object_id, cardinality, is_active, cross_filter_direction, relationship_properties
) VALUES (
    {_format_sql_value(rel.relationship_id)}, {_format_sql_value(rel.object_id)}, {_format_sql_value(rel.relationship_type)},
    {_format_sql_value(rel.from_table_id)}, {_format_sql_value(rel.to_table_id)},
    {_format_sql_value(rel.from_object_id)}, {_format_sql_value(rel.to_object_id)},
    {_format_sql_value(rel.cardinality)}, {_format_sql_value(rel.is_active)},
    {_format_sql_value(rel.cross_filter_direction)}, {_format_sql_value(rel.relationship_properties)}
) ON CONFLICT (object_id) DO UPDATE SET
    cardinality = EXCLUDED.cardinality,
    is_active = EXCLUDED.is_active;""")

        # 16. model_partitions
        for part in bundle.partitions:
            statements.append(f"""INSERT INTO kpi_intel.model_partitions (
    model_partition_id, semantic_model_id, partition_name, source_type,
    expression_language, expression_text, partition_properties
) VALUES (
    {_format_sql_value(part.model_partition_id)}, {_format_sql_value(part.semantic_model_id)},
    {_format_sql_value(part.partition_name)}, {_format_sql_value(part.source_type)},
    {_format_sql_value(part.expression_language)}, {_format_sql_value(part.expression_text)},
    {_format_sql_value(part.partition_properties)}
) ON CONFLICT (model_partition_id) DO NOTHING;""")

        # 17. named_expressions
        for ne in bundle.named_expressions:
            statements.append(f"""INSERT INTO kpi_intel.named_expressions (
    named_expression_id, object_id, expression_name, scope,
    expression_language, expression_text, expression_properties
) VALUES (
    {_format_sql_value(ne.named_expression_id)}, {_format_sql_value(ne.object_id)}, {_format_sql_value(ne.expression_name)},
    {_format_sql_value(ne.scope)}, {_format_sql_value(ne.expression_language)}, {_format_sql_value(ne.expression_text)},
    {_format_sql_value(ne.expression_properties)}
) ON CONFLICT (object_id) DO UPDATE SET
    expression_text = EXCLUDED.expression_text;""")

        # 18. metadata_lineage_edges
        for edge in bundle.lineage_edges:
            statements.append(f"""INSERT INTO kpi_intel.metadata_lineage_edges (
    lineage_edge_id, asset_version_id, source_object_id, target_object_id,
    edge_type, derivation_method, confidence_score, evidence
) VALUES (
    {_format_sql_value(edge.lineage_edge_id)}, {_format_sql_value(edge.asset_version_id)},
    {_format_sql_value(edge.source_object_id)}, {_format_sql_value(edge.target_object_id)},
    {_format_sql_value(edge.edge_type)}, {_format_sql_value(edge.derivation_method)},
    {_format_sql_value(edge.confidence_score)}, {_format_sql_value(edge.evidence)}
) ON CONFLICT (lineage_edge_id) DO NOTHING;""")

        # 19. parser_runs
        for pr in bundle.parser_runs:
            statements.append(f"""INSERT INTO kpi_intel.parser_runs (
    parser_run_id, asset_version_id, tenant_id, platform, parser_name, parser_version,
    run_status, objects_extracted, warnings_count, errors_count, run_metadata
) VALUES (
    {_format_sql_value(pr.parser_run_id)}, {_format_sql_value(pr.asset_version_id)}, {_format_sql_value(pr.tenant_id)},
    {_format_sql_value(pr.platform)}, {_format_sql_value(pr.parser_name)}, {_format_sql_value(pr.parser_version)},
    {_format_sql_value(pr.run_status)}, {_format_sql_value(pr.objects_extracted)},
    {_format_sql_value(pr.warnings_count)}, {_format_sql_value(pr.errors_count)},
    {_format_sql_value(pr.run_metadata)}
) ON CONFLICT (parser_run_id) DO NOTHING;""")

        # 20. extraction_errors
        for err in bundle.extraction_errors:
            statements.append(f"""INSERT INTO kpi_intel.extraction_errors (
    extraction_error_id, parser_run_id, severity, error_code, error_message, is_recoverable
) VALUES (
    {_format_sql_value(err.extraction_error_id)}, {_format_sql_value(err.parser_run_id)},
    {_format_sql_value(err.severity)}, {_format_sql_value(err.error_code)},
    {_format_sql_value(err.error_message)}, {_format_sql_value(err.is_recoverable)}
) ON CONFLICT (extraction_error_id) DO NOTHING;""")

        statements.append("")
        statements.append("COMMIT;")
        return "\n".join(statements)

    def persist(self, bundle: CanonicalIngestionBundle, connection: Optional[Any] = None) -> Dict[str, Any]:
        """
        Executes persistence against live PostgreSQL database if connection is provided,
        or returns declarative SQL execution summary.
        """
        sql = self.generate_transactional_sql(bundle)
        stats = {
            "tenant_id": str(self.tenant_id),
            "asset_id": str(bundle.asset.asset_id),
            "version_id": str(bundle.version.asset_version_id),
            "artifacts_persisted": len(bundle.artifacts),
            "objects_persisted": len(bundle.objects),
            "tables_persisted": len(bundle.tables),
            "columns_persisted": len(bundle.columns),
            "calculations_persisted": len(bundle.calculations),
            "relationships_persisted": len(bundle.relationships),
            "lineage_edges_persisted": len(bundle.lineage_edges),
            "sql_statement_count": sql.count(";") - 2,  # excluding BEGIN and COMMIT
            "executed_live": False
        }

        if connection:
            cursor = connection.cursor()
            try:
                # Set tenant context first
                cursor.execute("SELECT kpi_intel.set_current_tenant_id(%s::uuid);", (str(self.tenant_id),))
                # Execute compiled statements or run queries
                cursor.execute(sql)
                connection.commit()
                stats["executed_live"] = True
            except Exception as e:
                connection.rollback()
                raise e
            finally:
                cursor.close()

        return stats
