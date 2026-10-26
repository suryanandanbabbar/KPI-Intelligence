"""
KPI Intelligence — Canonical Ingestion Bundle to Cosmos Documents Converter.

Transforms in-memory extraction bundles into strongly typed Cosmos DB NoSQL documents:
- Preserves full metadata fidelity
- Normalizes relational component hierarchies into document aggregates
- Embeds report pages and visual layouts inside ReportDocument
- Embeds tables, columns, measures, relationships, hierarchies, and filters inside SemanticModelDocument
- Emits universal AnalyticalObjectDocument records for full analytical registry tracking
"""

import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import asdict
from backend.ingestion.models import CanonicalIngestionBundle
from backend.contracts import (
    AssetDocument,
    AssetVersionDocument,
    ReportDocument,
    SemanticModelDocument,
    AnalyticalObjectDocument,
    SecurityPrincipalDocument,
    LineageEdgeDocument,
    ParserRunDocument,
    ExtractionErrorDocument,
    LifecycleStatus,
)


class BundleToDocumentsConverter:
    """Converts a CanonicalIngestionBundle into Cosmos DB document contracts."""

    @staticmethod
    def convert(bundle: CanonicalIngestionBundle) -> Dict[str, List[Any]]:
        tenant_str = str(bundle.asset.tenant_id)

        # 1. Asset Document
        asset_doc = AssetDocument(
            id=f"asset_{bundle.asset.asset_id}",
            asset_id=str(bundle.asset.asset_id),
            tenant_id=tenant_str,
            platform=bundle.asset.platform,
            asset_name=bundle.asset.asset_name,
            asset_type=bundle.asset.asset_type,
            asset_description=bundle.asset.asset_description,
            source_native_id=bundle.asset.source_native_id,
            source_native_path=bundle.asset.source_native_path,
            source_version=bundle.asset.source_version,
            current_version_id=f"ver_{bundle.version.asset_version_id}",
            lifecycle_status=bundle.asset.lifecycle_status,
        )

        # 2. Asset Version Document
        artifacts_data = []
        for art in bundle.artifacts:
            artifacts_data.append({
                "source_artifact_id": str(art.source_artifact_id),
                "relative_path": art.relative_path,
                "artifact_type": art.artifact_type,
                "content_hash": art.content_hash,
                "size_bytes": art.size_bytes,
                "mime_type": art.mime_type,
                "is_supported": art.is_supported,
                "extraction_status": art.extraction_status,
            })

        version_doc = AssetVersionDocument(
            id=f"ver_{bundle.version.asset_version_id}",
            asset_version_id=str(bundle.version.asset_version_id),
            tenant_id=tenant_str,
            asset_id=asset_doc.id,
            version_number=bundle.version.version_number,
            content_hash=bundle.version.content_hash,
            raw_content_hash=bundle.version.raw_content_hash,
            structure_hash=bundle.version.structure_hash,
            metadata_hash=bundle.version.metadata_hash,
            parser_version=bundle.version.parser_version,
            source_manifest=bundle.version.source_manifest,
            artifacts=artifacts_data,
            source_artifacts=artifacts_data,
        )

        # 3. Visual Bindings grouped by visual_id
        bindings_by_visual: Dict[str, List[Dict[str, Any]]] = {}
        all_bindings_data: List[Dict[str, Any]] = []
        for b in bundle.visual_bindings:
            b_dict = {
                "visual_binding_id": str(b.visual_binding_id),
                "visual_id": str(b.visual_id),
                "object_id": str(b.object_id),
                "binding_role": b.binding_role,
                "binding_order": b.binding_order,
                "aggregation_override": b.aggregation_override,
                "format_override": b.format_override,
                "binding_properties": b.binding_properties,
            }
            bindings_by_visual.setdefault(str(b.visual_id), []).append(b_dict)
            all_bindings_data.append(b_dict)

        # 4. Visuals grouped by page_id
        visuals_by_page: Dict[str, List[Dict[str, Any]]] = {}
        all_visuals_data: List[Dict[str, Any]] = []
        for v in bundle.visuals:
            v_dict = {
                "visual_id": str(v.visual_id),
                "page_id": str(v.page_id),
                "object_id": str(v.object_id),
                "visual_type": v.visual_type,
                "source_native_id": v.source_native_id,
                "visual_title": v.visual_title,
                "visual_description": v.visual_description,
                "position_x": v.position_x,
                "position_y": v.position_y,
                "width": v.width,
                "height": v.height,
                "z_order": v.z_order,
                "visual_configuration": v.visual_configuration,
                "is_visible": v.is_visible,
                "bindings": bindings_by_visual.get(str(v.visual_id), []),
            }
            visuals_by_page.setdefault(str(v.page_id), []).append(v_dict)
            all_visuals_data.append(v_dict)

        # 5. Report Documents (with embedded pages, visuals, bindings, and bookmarks)
        report_docs = []
        for rep in bundle.reports:
            # Aggregate pages belonging to this report
            rep_pages = []
            rep_visuals = []
            rep_bindings = []

            for p in bundle.pages:
                if str(p.report_id) == str(rep.report_id):
                    page_viss = visuals_by_page.get(str(p.page_id), [])
                    rep_pages.append({
                        "page_id": str(p.page_id),
                        "page_name": p.page_name,
                        "page_order": p.page_order,
                        "page_type": p.page_type,
                        "is_hidden": p.is_hidden,
                        "properties": p.page_properties,
                        "visuals": page_viss,
                    })
                    rep_visuals.extend(page_viss)
                    for pv in page_viss:
                        rep_bindings.extend(pv.get("bindings", []))

            # Bookmarks
            rep_bookmarks = []
            for bm in bundle.bookmarks:
                rep_bookmarks.append({
                    "bookmark_id": str(bm.bookmark_id),
                    "bookmark_name": bm.bookmark_name,
                    "source_native_id": bm.source_native_id,
                    "state": bm.bookmark_state,
                })

            last_acc_str = rep.last_accessed_at.isoformat() if rep.last_accessed_at else None
            owner_str = str(rep.owner_id) if rep.owner_id else None

            rep_doc = ReportDocument(
                id=f"rep_{rep.report_id}",
                report_id=str(rep.report_id),
                object_id=str(rep.object_id),
                tenant_id=tenant_str,
                asset_id=asset_doc.id,
                asset_version_id=version_doc.id,
                platform=bundle.asset.platform,
                report_name=bundle.asset.asset_name,
                report_type=rep.report_type,
                report_definition=rep.report_definition,
                default_page_object_id=str(rep.default_page_object_id) if rep.default_page_object_id else None,
                owner_id=owner_str,
                owner_name=rep.owner_name,
                last_accessed_at=last_acc_str,
                lifecycle_status=rep.lifecycle_status,
                page_count=rep.page_count,
                visual_count=rep.visual_count,
                report_configuration=rep.report_configuration,
                pages=rep_pages,
                report_pages=rep_pages,
                visuals=rep_visuals if rep_visuals else all_visuals_data,
                visual_bindings=rep_bindings if rep_bindings else all_bindings_data,
                bookmarks=rep_bookmarks,
            )
            report_docs.append(rep_doc)

        # 6. Hierarchy levels grouped by hierarchy_id
        levels_by_hierarchy: Dict[str, List[Dict[str, Any]]] = {}
        all_levels_data: List[Dict[str, Any]] = []
        for lvl in bundle.hierarchy_levels:
            lvl_dict = {
                "hierarchy_level_id": str(lvl.hierarchy_level_id),
                "hierarchy_id": str(lvl.hierarchy_id),
                "level_object_id": str(lvl.level_object_id),
                "level_name": lvl.level_name,
                "level_order": lvl.level_order,
                "level_properties": lvl.level_properties,
            }
            levels_by_hierarchy.setdefault(str(lvl.hierarchy_id), []).append(lvl_dict)
            all_levels_data.append(lvl_dict)

        # 7. Semantic Model Documents (with embedded tables, measures, relationships, hierarchies, filters)
        model_docs = []
        for sm in bundle.semantic_models:
            # Tables and Columns
            sm_tables = []
            sm_all_columns = []
            for t in bundle.tables:
                if str(t.semantic_model_id) == str(sm.semantic_model_id):
                    # Columns for table
                    tbl_cols = []
                    for c in bundle.columns:
                        if str(c.data_table_id) == str(t.data_table_id):
                            col_dict = {
                                "column_id": str(c.data_column_id),
                                "data_column_id": str(c.data_column_id),
                                "column_name": c.column_name,
                                "display_name": c.display_name,
                                "data_type": c.data_type,
                                "source_data_type": c.source_data_type,
                                "is_calculated": c.is_calculated,
                                "default_aggregation": c.default_aggregation,
                                "format_string": c.format_string,
                            }
                            tbl_cols.append(col_dict)
                            sm_all_columns.append(col_dict)
                    sm_tables.append({
                        "table_id": str(t.data_table_id),
                        "data_table_id": str(t.data_table_id),
                        "table_name": t.table_name,
                        "table_type": t.table_type,
                        "storage_mode": t.storage_mode,
                        "description": t.description,
                        "is_hidden": t.is_hidden,
                        "columns": tbl_cols,
                    })

            # Calculations / Measures
            sm_calcs = []
            for calc in bundle.calculations:
                if str(calc.semantic_model_id) == str(sm.semantic_model_id):
                    sm_calcs.append({
                        "calculation_id": str(calc.calculation_id),
                        "calculation_name": calc.calculation_name,
                        "calculation_type": calc.calculation_type,
                        "expression_language": calc.expression_language,
                        "expression_text": calc.expression_text,
                        "format_string": calc.format_string,
                        "description": calc.description,
                    })

            # Relationships
            sm_rels = []
            for rel in bundle.relationships:
                sm_rels.append({
                    "relationship_id": str(rel.relationship_id),
                    "from_table_id": str(rel.from_table_id) if rel.from_table_id else None,
                    "to_table_id": str(rel.to_table_id) if rel.to_table_id else None,
                    "cardinality": rel.cardinality,
                    "cross_filter_direction": rel.cross_filter_direction,
                    "is_active": rel.is_active,
                })

            # Partitions
            sm_parts = []
            for p in bundle.partitions:
                if str(p.semantic_model_id) == str(sm.semantic_model_id):
                    sm_parts.append({
                        "partition_id": str(p.model_partition_id),
                        "model_partition_id": str(p.model_partition_id),
                        "partition_name": p.partition_name,
                        "source_type": p.source_type,
                        "expression_language": p.expression_language,
                        "expression_text": p.expression_text,
                    })

            # Named Expressions
            sm_exprs = []
            for expr in bundle.named_expressions:
                sm_exprs.append({
                    "expression_id": str(expr.named_expression_id),
                    "named_expression_id": str(expr.named_expression_id),
                    "expression_name": expr.expression_name,
                    "expression_language": expr.expression_language,
                    "expression_text": expr.expression_text,
                    "scope": expr.scope,
                })

            # Hierarchies
            sm_hierarchies = []
            for h in bundle.hierarchies:
                if str(h.semantic_model_id) == str(sm.semantic_model_id):
                    sm_hierarchies.append({
                        "hierarchy_id": str(h.hierarchy_id),
                        "object_id": str(h.object_id),
                        "hierarchy_name": h.hierarchy_name,
                        "hierarchy_type": h.hierarchy_type,
                        "hierarchy_properties": h.hierarchy_properties,
                        "levels": levels_by_hierarchy.get(str(h.hierarchy_id), []),
                    })

            # Filters
            sm_filters = []
            for f in bundle.filters:
                sm_filters.append({
                    "filter_id": str(f.filter_id),
                    "object_id": str(f.object_id),
                    "filter_name": f.filter_name,
                    "filter_type": f.filter_type,
                    "filter_scope": f.filter_scope,
                    "expression_language": f.expression_language,
                    "expression_text": f.expression_text,
                    "filter_operator": f.filter_operator,
                    "filter_values": f.filter_values,
                    "is_enabled": f.is_enabled,
                    "filter_properties": f.filter_properties,
                })

            # Filter assignments
            sm_filter_assignments = []
            for fa in bundle.filter_assignments:
                sm_filter_assignments.append({
                    "filter_assignment_id": str(fa.filter_assignment_id),
                    "filter_id": str(fa.filter_id),
                    "target_object_id": str(fa.target_object_id),
                    "assignment_scope": fa.assignment_scope,
                    "field_object_id": str(fa.field_object_id) if fa.field_object_id else None,
                    "assignment_properties": fa.assignment_properties,
                })

            sm_doc = SemanticModelDocument(
                id=f"model_{sm.semantic_model_id}",
                semantic_model_id=str(sm.semantic_model_id),
                object_id=str(sm.object_id),
                tenant_id=tenant_str,
                asset_id=asset_doc.id,
                asset_version_id=version_doc.id,
                model_name=sm.model_name,
                model_type=sm.model_type,
                model_version=sm.model_version,
                compatibility_level=int(sm.compatibility_level) if sm.compatibility_level else None,
                model_definition=sm.model_definition,
                source_connection_summary=sm.source_connection_summary,
                source_native_id=sm.source_native_id,
                tables=sm_tables,
                data_tables=sm_tables,
                data_columns=sm_all_columns,
                calculations=sm_calcs,
                relationships=sm_rels,
                partitions=sm_parts,
                model_partitions=sm_parts,
                named_expressions=sm_exprs,
                hierarchies=sm_hierarchies,
                hierarchy_levels=all_levels_data,
                filters=sm_filters,
                filter_assignments=sm_filter_assignments,
            )
            model_docs.append(sm_doc)

        # 8. Analytical Objects
        analytical_docs = []
        for obj in bundle.objects:
            analytical_docs.append(AnalyticalObjectDocument(
                id=f"obj_{obj.object_id}",
                object_id=str(obj.object_id),
                tenant_id=tenant_str,
                asset_version_id=version_doc.id,
                parent_object_id=str(obj.parent_object_id) if obj.parent_object_id else None,
                source_artifact_id=str(obj.source_artifact_id) if obj.source_artifact_id else None,
                platform=obj.platform,
                object_type=obj.object_type,
                source_native_id=obj.source_native_id,
                source_native_name=obj.source_native_name,
                canonical_name=obj.canonical_name,
                display_name=obj.display_name,
                description=obj.description,
                source_path=obj.source_path,
                source_locator=obj.source_locator,
                is_hidden=obj.is_hidden,
                is_active=obj.is_active,
                extraction_status=obj.extraction_status,
                metadata_completeness=obj.metadata_completeness,
                source_metadata=obj.source_metadata,
            ))

        # 9. Lineage Edges
        edge_docs = []
        for edge in bundle.lineage_edges:
            edge_docs.append(LineageEdgeDocument(
                id=f"edge_{edge.lineage_edge_id}",
                tenant_id=tenant_str,
                asset_version_id=version_doc.id,
                source_object_id=str(edge.source_object_id),
                target_object_id=str(edge.target_object_id),
                edge_type=edge.edge_type,
                derivation_method=edge.derivation_method,
                confidence_score=edge.confidence_score,
                evidence=edge.evidence,
            ))

        # 10. Parser Runs
        run_docs = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for run in bundle.parser_runs:
            run_docs.append(ParserRunDocument(
                id=f"run_{run.parser_run_id}",
                parser_run_id=str(run.parser_run_id),
                tenant_id=tenant_str,
                asset_version_id=version_doc.id,
                platform=run.platform,
                parser_name=run.parser_name,
                parser_version=run.parser_version,
                run_status=run.run_status,
                objects_extracted=run.objects_extracted,
                warnings_count=run.warnings_count,
                errors_count=run.errors_count,
                source_artifact_id=str(run.source_artifact_id) if run.source_artifact_id else None,
                started_at=getattr(run, "started_at", now_iso),
                completed_at=getattr(run, "completed_at", now_iso),
                run_metadata=run.run_metadata,
            ))

        # 11. Extraction Errors
        error_docs = []
        for err in bundle.extraction_errors:
            loc = err.object_locator if isinstance(err.object_locator, str) else json.dumps(err.object_locator)
            error_docs.append(ExtractionErrorDocument(
                id=f"err_{err.extraction_error_id}",
                extraction_error_id=str(err.extraction_error_id),
                tenant_id=tenant_str,
                parser_run_id=f"run_{err.parser_run_id}",
                severity=err.severity,
                error_code=err.error_code,
                error_message=err.error_message,
                object_locator=loc,
                is_recoverable=err.is_recoverable,
            ))

        # 12. Security Principals (if present on bundle)
        principal_docs = []
        for sp in getattr(bundle, "security_principals", []):
            principal_docs.append(SecurityPrincipalDocument(
                id=f"principal_{sp.principal_id}",
                principal_id=str(sp.principal_id),
                tenant_id=tenant_str,
                platform=getattr(sp, "platform", "POWER_BI"),
                source_native_id=getattr(sp, "source_native_id", None),
                principal_name=getattr(sp, "principal_name", ""),
                principal_type=getattr(sp, "principal_type", "USER"),
                principal_properties=getattr(sp, "principal_properties", {}),
            ))

        return {
            "assets": [asset_doc],
            "asset_versions": [version_doc],
            "reports": report_docs,
            "semantic_models": model_docs,
            "analytical_objects": analytical_docs,
            "lineage_edges": edge_docs,
            "parser_runs": run_docs,
            "extraction_errors": error_docs,
            "security_principals": principal_docs,
        }
