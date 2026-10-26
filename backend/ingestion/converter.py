"""
KPI Intelligence — Canonical Ingestion Bundle to Cosmos Documents Converter.

Transforms in-memory extraction bundles into strongly typed Cosmos DB NoSQL documents:
- Preserves full metadata fidelity
- Normalizes relational component hierarchies into document aggregates
- Embeds report pages and visual layouts inside ReportDocument
- Embeds tables, columns, measures, and relationships inside SemanticModelDocument
"""

import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Tuple
from dataclasses import asdict
from backend.ingestion.models import CanonicalIngestionBundle
from backend.contracts import (
    AssetDocument,
    AssetVersionDocument,
    ReportDocument,
    SemanticModelDocument,
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
        )

        # 3. Report Documents (with embedded pages and bookmarks)
        report_docs = []
        for rep in bundle.reports:
            # Aggregate pages belonging to this report
            rep_pages = []
            for p in bundle.pages:
                if str(p.report_id) == str(rep.report_id):
                    rep_pages.append({
                        "page_id": str(p.page_id),
                        "page_name": p.page_name,
                        "page_order": p.page_order,
                        "page_type": p.page_type,
                        "is_hidden": p.is_hidden,
                        "properties": p.page_properties,
                    })

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
                tenant_id=tenant_str,
                asset_id=asset_doc.id,
                asset_version_id=version_doc.id,
                platform=bundle.asset.platform,
                report_name=bundle.asset.asset_name,
                report_type=rep.report_type,
                owner_id=owner_str,
                owner_name=rep.owner_name,
                last_accessed_at=last_acc_str,
                lifecycle_status=rep.lifecycle_status,
                page_count=rep.page_count,
                visual_count=rep.visual_count,
                report_configuration=rep.report_configuration,
                pages=rep_pages,
                bookmarks=rep_bookmarks,
            )
            report_docs.append(rep_doc)

        # 4. Semantic Model Documents (with embedded tables, measures, relationships)
        model_docs = []
        for sm in bundle.semantic_models:
            # Tables and Columns
            sm_tables = []
            for t in bundle.tables:
                if str(t.semantic_model_id) == str(sm.semantic_model_id):
                    # Columns for table
                    tbl_cols = []
                    for c in bundle.columns:
                        if str(c.data_table_id) == str(t.data_table_id):
                            tbl_cols.append({
                                "column_id": str(c.data_column_id),
                                "column_name": c.column_name,
                                "display_name": c.display_name,
                                "data_type": c.data_type,
                                "source_data_type": c.source_data_type,
                                "is_calculated": c.is_calculated,
                                "default_aggregation": c.default_aggregation,
                                "format_string": c.format_string,
                            })
                    sm_tables.append({
                        "table_id": str(t.data_table_id),
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
                    "expression_name": expr.expression_name,
                    "expression_language": expr.expression_language,
                    "expression_text": expr.expression_text,
                    "scope": expr.scope,
                })

            sm_doc = SemanticModelDocument(
                id=f"model_{sm.semantic_model_id}",
                tenant_id=tenant_str,
                asset_id=asset_doc.id,
                asset_version_id=version_doc.id,
                model_name=sm.model_name,
                model_type=sm.model_type,
                compatibility_level=sm.compatibility_level,
                model_definition=sm.model_definition,
                tables=sm_tables,
                calculations=sm_calcs,
                relationships=sm_rels,
                partitions=sm_parts,
                named_expressions=sm_exprs,
            )
            model_docs.append(sm_doc)

        # 5. Lineage Edges
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

        # 6. Parser Runs
        run_docs = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for run in bundle.parser_runs:
            run_docs.append(ParserRunDocument(
                id=f"run_{run.parser_run_id}",
                tenant_id=tenant_str,
                asset_version_id=version_doc.id,
                platform=run.platform,
                parser_name=run.parser_name,
                parser_version=run.parser_version,
                run_status=run.run_status,
                objects_extracted=run.objects_extracted,
                warnings_count=run.warnings_count,
                errors_count=run.errors_count,
                started_at=getattr(run, "started_at", now_iso),
                completed_at=getattr(run, "completed_at", now_iso),
                run_metadata=run.run_metadata,
            ))

        # 7. Extraction Errors
        error_docs = []
        for err in bundle.extraction_errors:
            loc = err.object_locator if isinstance(err.object_locator, str) else json.dumps(err.object_locator)
            error_docs.append(ExtractionErrorDocument(
                id=f"err_{err.extraction_error_id}",
                tenant_id=tenant_str,
                parser_run_id=str(err.parser_run_id),
                severity=err.severity,
                error_code=err.error_code,
                error_message=err.error_message,
                object_locator=loc,
                is_recoverable=err.is_recoverable,
            ))

        return {
            "assets": [asset_doc],
            "asset_versions": [version_doc],
            "reports": report_docs,
            "semantic_models": model_docs,
            "lineage_edges": edge_docs,
            "parser_runs": run_docs,
            "extraction_errors": error_docs,
        }
