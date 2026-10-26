"""
KPI Intelligence — Power BI Metadata Normalizer.

Transforms raw parsed Power BI project ASTs (PBIP, TMDL model, PBIR report)
into normalized canonical records conforming to the 61-table PostgreSQL schema.
Implements deterministic UUID generation, hierarchical analytical object registry,
fine-grained metadata lineage extraction, and audit tracking.
"""

import uuid
import re
import os
from typing import Dict, List, Optional, Tuple, Any

from backend.connectors.powerbi.discovery import PbipProjectStructure
from backend.connectors.powerbi.tmdl_parser import TmdlModel, TmdlTable, TmdlColumn, TmdlMeasure
from backend.connectors.powerbi.report_parser import ReportDefinition, ReportPage, ReportVisual
from backend.connectors.base import Diagnostic, DiagnosticSeverity
from backend.ingestion.hasher import IngestionHasher
from backend.ingestion.models import (
    CanonicalAsset,
    CanonicalAssetVersion,
    CanonicalSourceArtifact,
    CanonicalAnalyticalObject,
    CanonicalReport,
    CanonicalReportPage,
    CanonicalVisual,
    CanonicalVisualBinding,
    CanonicalBookmark,
    CanonicalSemanticModel,
    CanonicalDataTable,
    CanonicalDataColumn,
    CanonicalCalculation,
    CanonicalRelationship,
    CanonicalModelPartition,
    CanonicalNamedExpression,
    CanonicalMetadataLineageEdge,
    CanonicalParserRun,
    CanonicalExtractionError,
    CanonicalIngestionBundle,
)


def make_deterministic_uuid(namespace: uuid.UUID, key: str) -> uuid.UUID:
    """Generates a reproducible UUIDv5 from a namespace and string key."""
    return uuid.uuid5(namespace, key)


class PowerBINormalizer:
    """Normalizes Power BI metadata into canonical schema structures."""

    def __init__(self, tenant_id: uuid.UUID, parser_version: str = "1.0.0"):
        self.tenant_id = tenant_id
        self.parser_version = parser_version
        self.namespace = uuid.NAMESPACE_URL

    def normalize(
        self,
        project_structure: PbipProjectStructure,
        tmdl_model: Optional[TmdlModel] = None,
        report_def: Optional[ReportDefinition] = None,
        version_number: int = 1,
    ) -> CanonicalIngestionBundle:
        """
        Main normalization method transforming parsed ASTs into CanonicalIngestionBundle.
        """
        asset_name = project_structure.asset_name
        
        # 1. Deterministic Root UUIDs
        asset_id = make_deterministic_uuid(
            self.namespace,
            f"kpi_intel:asset:{self.tenant_id}:POWER_BI:{asset_name}"
        )
        asset_version_id = make_deterministic_uuid(
            self.namespace,
            f"kpi_intel:version:{asset_id}:{version_number}"
        )
        
        # 2. Source Artifacts
        artifacts: List[CanonicalSourceArtifact] = []
        artifact_path_to_id: Dict[str, uuid.UUID] = {}
        for art in project_structure.artifacts:
            art_id = make_deterministic_uuid(
                self.namespace,
                f"kpi_intel:artifact:{asset_version_id}:{art.relative_path}"
            )
            artifact_path_to_id[art.relative_path] = art_id
            artifacts.append(CanonicalSourceArtifact(
                source_artifact_id=art_id,
                asset_version_id=asset_version_id,
                relative_path=art.relative_path,
                artifact_type=art.artifact_type,
                content_hash=art.content_hash,
                size_bytes=art.size_bytes,
                mime_type=art.mime_type,
                is_supported=art.is_supported,
                extraction_status="SUCCESSFUL" if art.is_supported else "SKIPPED"
            ))

        # 3. Compute Hashes
        raw_model_dict = {"tables": tmdl_model.tables} if tmdl_model else {}
        raw_report_dict = {"pages": report_def.pages} if report_def else {}
        
        raw_content_hash = IngestionHasher.compute_raw_content_hash(project_structure.artifacts)
        structure_hash = IngestionHasher.compute_structure_hash(raw_model_dict, raw_report_dict)
        metadata_hash = IngestionHasher.compute_metadata_hash(raw_model_dict, raw_report_dict)
        content_hash = IngestionHasher.compute_composite_content_hash(
            raw_content_hash, structure_hash, metadata_hash
        )

        # 4. Canonical Asset & Asset Version
        asset = CanonicalAsset(
            asset_id=asset_id,
            tenant_id=self.tenant_id,
            platform="POWER_BI",
            asset_type="REPORT",
            asset_name=asset_name,
            asset_description=f"Power BI PBIP Project: {asset_name}",
            source_native_id=asset_name,
            source_native_path=project_structure.pbip_file_path,
            source_version=project_structure.pbip_version,
            lifecycle_status="ACTIVE",
            current_version_id=asset_version_id
        )

        version = CanonicalAssetVersion(
            asset_version_id=asset_version_id,
            asset_id=asset_id,
            tenant_id=self.tenant_id,
            version_number=version_number,
            content_hash=content_hash,
            raw_content_hash=raw_content_hash,
            structure_hash=structure_hash,
            metadata_hash=metadata_hash,
            parser_version=self.parser_version,
            schema_version="1.0.0",
            source_manifest={"pbip_version": project_structure.pbip_version, "artifact_count": len(artifacts)},
            extraction_status="SUCCESSFUL"
        )

        # Initialize bundle collections
        objects: List[CanonicalAnalyticalObject] = []
        reports: List[CanonicalReport] = []
        pages: List[CanonicalReportPage] = []
        visuals: List[CanonicalVisual] = []
        visual_bindings: List[CanonicalVisualBinding] = []
        bookmarks: List[CanonicalBookmark] = []
        semantic_models: List[CanonicalSemanticModel] = []
        tables: List[CanonicalDataTable] = []
        columns: List[CanonicalDataColumn] = []
        calculations: List[CanonicalCalculation] = []
        relationships: List[CanonicalRelationship] = []
        partitions: List[CanonicalModelPartition] = []
        named_expressions: List[CanonicalNamedExpression] = []
        lineage_edges: List[CanonicalMetadataLineageEdge] = []

        # Lookup registries for cross-object resolution
        # qualified_name (e.g. "verkoop.aantal") -> object_id
        column_lookup: Dict[str, uuid.UUID] = {}
        # measure_name -> object_id
        measure_lookup: Dict[str, uuid.UUID] = {}
        # table_name -> CanonicalDataTable
        table_lookup: Dict[str, CanonicalDataTable] = {}

        # 5. Normalize Semantic Model
        if tmdl_model:
            model_obj_id = make_deterministic_uuid(
                self.namespace,
                f"kpi_intel:obj:{asset_version_id}:SEMANTIC_MODEL:{tmdl_model.name}"
            )
            # Find source artifact for model
            model_art_id = None
            for rpath, aid in artifact_path_to_id.items():
                if rpath.endswith("model.tmdl"):
                    model_art_id = aid
                    break

            objects.append(CanonicalAnalyticalObject(
                object_id=model_obj_id,
                asset_version_id=asset_version_id,
                tenant_id=self.tenant_id,
                parent_object_id=None,
                source_artifact_id=model_art_id,
                platform="POWER_BI",
                object_type="SEMANTIC_MODEL",
                source_native_id=tmdl_model.name,
                source_native_name=tmdl_model.name,
                canonical_name=tmdl_model.name,
                display_name=tmdl_model.name,
                source_metadata={"culture": tmdl_model.culture, "compatibility_level": tmdl_model.compatibility_level}
            ))

            semantic_model = CanonicalSemanticModel(
                semantic_model_id=model_obj_id,
                object_id=model_obj_id,
                model_name=tmdl_model.name,
                model_type="TABULAR_TMDL",
                source_native_id=tmdl_model.name,
                compatibility_level=tmdl_model.compatibility_level,
                model_definition={
                    "culture": tmdl_model.culture,
                    "defaultPowerBIDataSourceVersion": tmdl_model.default_powerbi_data_source_version,
                    "discourageImplicitMeasures": tmdl_model.discourage_implicit_measures,
                    "annotations": tmdl_model.annotations
                }
            )
            semantic_models.append(semantic_model)

            # 5a. Tables & Columns & Measures
            for tname, tbl in tmdl_model.tables.items():
                # Find artifact for this table
                tbl_art_id = None
                for rpath, aid in artifact_path_to_id.items():
                    if f"/tables/{tname}.tmdl" in rpath or rpath.endswith(f"/{tname}.tmdl"):
                        tbl_art_id = aid
                        break

                table_obj_id = make_deterministic_uuid(
                    self.namespace,
                    f"kpi_intel:obj:{asset_version_id}:DATA_TABLE:{tname}"
                )

                # Determine table type
                if tbl.calculation_group:
                    table_type = "CALCULATION_GROUP"
                elif tname.startswith("_INFO_"):
                    table_type = "INFO_VIEW"
                elif any(p.partition_type == "calculated" for p in tbl.partitions):
                    table_type = "CALCULATED"
                else:
                    table_type = "PHYSICAL"

                objects.append(CanonicalAnalyticalObject(
                    object_id=table_obj_id,
                    asset_version_id=asset_version_id,
                    tenant_id=self.tenant_id,
                    parent_object_id=model_obj_id,
                    source_artifact_id=tbl_art_id,
                    platform="POWER_BI",
                    object_type="DATA_TABLE",
                    source_native_id=tbl.lineage_tag or tname,
                    source_native_name=tname,
                    canonical_name=tname,
                    display_name=tname,
                    description=tbl.description,
                    is_hidden=tbl.is_hidden,
                    source_metadata=tbl.annotations
                ))

                data_table = CanonicalDataTable(
                    data_table_id=table_obj_id,
                    object_id=table_obj_id,
                    semantic_model_id=model_obj_id,
                    source_native_id=tbl.lineage_tag or tname,
                    table_name=tname,
                    table_type=table_type,
                    description=tbl.description,
                    is_hidden=tbl.is_hidden,
                    storage_mode="import",
                    table_properties=tbl.properties
                )
                tables.append(data_table)
                table_lookup[tname] = data_table

                # 5b. Columns
                for col in tbl.columns:
                    col_key = f"{tname}.{col.name}"
                    col_obj_id = make_deterministic_uuid(
                        self.namespace,
                        f"kpi_intel:obj:{asset_version_id}:DATA_COLUMN:{col_key}"
                    )
                    column_lookup[col_key] = col_obj_id
                    column_lookup[col.name] = col_obj_id  # fallback unqualified

                    objects.append(CanonicalAnalyticalObject(
                        object_id=col_obj_id,
                        asset_version_id=asset_version_id,
                        tenant_id=self.tenant_id,
                        parent_object_id=table_obj_id,
                        source_artifact_id=tbl_art_id,
                        platform="POWER_BI",
                        object_type="DATA_COLUMN",
                        source_native_id=col.lineage_tag or col.name,
                        source_native_name=col.name,
                        canonical_name=col_key,
                        display_name=col.name,
                        is_hidden=col.is_hidden,
                        source_metadata=col.annotations
                    ))

                    data_col = CanonicalDataColumn(
                        data_column_id=col_obj_id,
                        object_id=col_obj_id,
                        data_table_id=table_obj_id,
                        source_native_id=col.lineage_tag or col.name,
                        column_name=col.name,
                        display_name=col.name,
                        data_type=col.data_type or "string",
                        source_data_type=col.data_type,
                        is_nullable=True,
                        is_hidden=col.is_hidden,
                        is_calculated=col.is_calculated,
                        default_aggregation=col.summarize_by or "none",
                        format_string=col.format_string,
                        column_properties=col.properties
                    )
                    columns.append(data_col)

                    # If column is calculated, register calculation record
                    if col.is_calculated and col.expression:
                        calc_col_obj_id = make_deterministic_uuid(
                            self.namespace,
                            f"kpi_intel:obj:{asset_version_id}:CALCULATION:{col_key}"
                        )
                        objects.append(CanonicalAnalyticalObject(
                            object_id=calc_col_obj_id,
                            asset_version_id=asset_version_id,
                            tenant_id=self.tenant_id,
                            parent_object_id=col_obj_id,
                            source_artifact_id=tbl_art_id,
                            platform="POWER_BI",
                            object_type="CALCULATION",
                            source_native_id=col.lineage_tag or col.name,
                            source_native_name=col.name,
                            canonical_name=f"calc:{col_key}",
                            display_name=col.name
                        ))
                        calculations.append(CanonicalCalculation(
                            calculation_id=calc_col_obj_id,
                            object_id=calc_col_obj_id,
                            calculation_name=col.name,
                            calculation_type="CALCULATED_COLUMN",
                            expression_language="DAX",
                            expression_text=col.expression,
                            semantic_model_id=model_obj_id,
                            data_table_id=table_obj_id,
                            data_column_id=col_obj_id,
                            format_string=col.format_string
                        ))

                # 5c. Measures
                for meas in tbl.measures:
                    meas_key = f"{tname}.{meas.name}"
                    meas_obj_id = make_deterministic_uuid(
                        self.namespace,
                        f"kpi_intel:obj:{asset_version_id}:CALCULATION:MEASURE:{meas_key}"
                    )
                    measure_lookup[meas.name] = meas_obj_id
                    measure_lookup[meas_key] = meas_obj_id

                    objects.append(CanonicalAnalyticalObject(
                        object_id=meas_obj_id,
                        asset_version_id=asset_version_id,
                        tenant_id=self.tenant_id,
                        parent_object_id=table_obj_id,
                        source_artifact_id=tbl_art_id,
                        platform="POWER_BI",
                        object_type="CALCULATION",
                        source_native_id=meas.lineage_tag or meas.name,
                        source_native_name=meas.name,
                        canonical_name=meas_key,
                        display_name=meas.name,
                        description=meas.description,
                        is_hidden=meas.is_hidden,
                        source_metadata=meas.annotations
                    ))

                    calculations.append(CanonicalCalculation(
                        calculation_id=meas_obj_id,
                        object_id=meas_obj_id,
                        calculation_name=meas.name,
                        calculation_type="MEASURE",
                        expression_language="DAX",
                        expression_text=meas.expression,
                        semantic_model_id=model_obj_id,
                        data_table_id=table_obj_id,
                        format_string=meas.format_string,
                        description=meas.description
                    ))

                # 5d. Calculation Group Items
                if tbl.calculation_group:
                    for citem in tbl.calculation_group.items:
                        item_key = f"{tname}.{citem.name}"
                        item_obj_id = make_deterministic_uuid(
                            self.namespace,
                            f"kpi_intel:obj:{asset_version_id}:CALCULATION:CALC_ITEM:{item_key}"
                        )
                        objects.append(CanonicalAnalyticalObject(
                            object_id=item_obj_id,
                            asset_version_id=asset_version_id,
                            tenant_id=self.tenant_id,
                            parent_object_id=table_obj_id,
                            source_artifact_id=tbl_art_id,
                            platform="POWER_BI",
                            object_type="CALCULATION",
                            source_native_name=citem.name,
                            canonical_name=item_key,
                            display_name=citem.name
                        ))
                        calculations.append(CanonicalCalculation(
                            calculation_id=item_obj_id,
                            object_id=item_obj_id,
                            calculation_name=citem.name,
                            calculation_type="CALCULATION_ITEM",
                            expression_language="DAX",
                            expression_text=citem.expression,
                            semantic_model_id=model_obj_id,
                            data_table_id=table_obj_id,
                            format_string=citem.format_string_definition
                        ))

                # 5e. Partitions
                for part in tbl.partitions:
                    part_id = make_deterministic_uuid(
                        self.namespace,
                        f"kpi_intel:partition:{model_obj_id}:{tname}:{part.name}"
                    )
                    partitions.append(CanonicalModelPartition(
                        model_partition_id=part_id,
                        semantic_model_id=model_obj_id,
                        partition_name=part.name,
                        source_type=part.partition_type.upper(),
                        expression_language="M" if part.partition_type == "m" else "DAX",
                        expression_text=part.source_expression,
                        partition_properties={"mode": part.mode}
                    ))

            # 5f. Relationships
            rel_art_id = None
            for rpath, aid in artifact_path_to_id.items():
                if rpath.endswith("relationships.tmdl"):
                    rel_art_id = aid
                    break

            for rel in tmdl_model.relationships:
                rel_obj_id = make_deterministic_uuid(
                    self.namespace,
                    f"kpi_intel:obj:{asset_version_id}:RELATIONSHIP:{rel.relationship_id}"
                )
                from_table = table_lookup.get(rel.from_table)
                to_table = table_lookup.get(rel.to_table)
                from_col_id = column_lookup.get(f"{rel.from_table}.{rel.from_column}")
                to_col_id = column_lookup.get(f"{rel.to_table}.{rel.to_column}")

                objects.append(CanonicalAnalyticalObject(
                    object_id=rel_obj_id,
                    asset_version_id=asset_version_id,
                    tenant_id=self.tenant_id,
                    parent_object_id=model_obj_id,
                    source_artifact_id=rel_art_id,
                    platform="POWER_BI",
                    object_type="RELATIONSHIP",
                    source_native_id=rel.relationship_id,
                    source_native_name=f"{rel.from_table} -> {rel.to_table}",
                    canonical_name=f"rel:{rel.relationship_id}",
                    display_name=f"{rel.from_table}.{rel.from_column} -> {rel.to_table}.{rel.to_column}"
                ))

                relationships.append(CanonicalRelationship(
                    relationship_id=rel_obj_id,
                    object_id=rel_obj_id,
                    relationship_type="FOREIGN_KEY",
                    from_table_id=from_table.data_table_id if from_table else None,
                    to_table_id=to_table.data_table_id if to_table else None,
                    from_object_id=from_col_id or (from_table.object_id if from_table else None),
                    to_object_id=to_col_id or (to_table.object_id if to_table else None),
                    cardinality=rel.cardinality,
                    cross_filter_direction=rel.cross_filtering_behavior,
                    is_active=rel.is_active,
                    relationship_properties=rel.properties
                ))

                # Add relationship lineage edge if columns resolved
                if from_col_id and to_col_id and from_col_id != to_col_id:
                    edge_id = make_deterministic_uuid(
                        self.namespace,
                        f"kpi_intel:edge:{asset_version_id}:{from_col_id}:{to_col_id}:RELATIONSHIP_JOIN"
                    )
                    lineage_edges.append(CanonicalMetadataLineageEdge(
                        lineage_edge_id=edge_id,
                        asset_version_id=asset_version_id,
                        source_object_id=from_col_id,
                        target_object_id=to_col_id,
                        edge_type="RELATIONSHIP_JOIN",
                        derivation_method="SOURCE_DECLARED",
                        confidence_score=1.0,
                        evidence={"relationship_id": rel.relationship_id}
                    ))

            # 5g. Named Expressions (Power Query shared expressions)
            expr_art_id = None
            for rpath, aid in artifact_path_to_id.items():
                if rpath.endswith("expressions.tmdl"):
                    expr_art_id = aid
                    break

            for ename, expr in tmdl_model.expressions.items():
                expr_obj_id = make_deterministic_uuid(
                    self.namespace,
                    f"kpi_intel:obj:{asset_version_id}:NAMED_EXPRESSION:{ename}"
                )
                objects.append(CanonicalAnalyticalObject(
                    object_id=expr_obj_id,
                    asset_version_id=asset_version_id,
                    tenant_id=self.tenant_id,
                    parent_object_id=model_obj_id,
                    source_artifact_id=expr_art_id,
                    platform="POWER_BI",
                    object_type="NAMED_EXPRESSION",
                    source_native_id=expr.lineage_tag or ename,
                    source_native_name=ename,
                    canonical_name=f"expr:{ename}",
                    display_name=ename
                ))
                named_expressions.append(CanonicalNamedExpression(
                    named_expression_id=expr_obj_id,
                    object_id=expr_obj_id,
                    expression_name=ename,
                    expression_language="M",
                    expression_text=expr.expression_text,
                    scope="MODEL",
                    expression_properties=expr.annotations
                ))

        # 6. Normalize Report & Pages & Visuals & Bookmarks
        if report_def:
            rep_art_id = None
            for rpath, aid in artifact_path_to_id.items():
                if rpath.endswith("report.json"):
                    rep_art_id = aid
                    break

            report_obj_id = make_deterministic_uuid(
                self.namespace,
                f"kpi_intel:obj:{asset_version_id}:REPORT:{report_def.report_name}"
            )

            objects.append(CanonicalAnalyticalObject(
                object_id=report_obj_id,
                asset_version_id=asset_version_id,
                tenant_id=self.tenant_id,
                parent_object_id=None,
                source_artifact_id=rep_art_id,
                platform="POWER_BI",
                object_type="REPORT",
                source_native_id=report_def.report_name,
                source_native_name=report_def.report_name,
                canonical_name=report_def.report_name,
                display_name=report_def.report_name,
                source_metadata={"theme": report_def.theme, "pbir_version": report_def.pbir_version}
            ))

            canonical_rep = CanonicalReport(
                report_id=report_obj_id,
                object_id=report_obj_id,
                report_type="POWER_BI_PBIP",
                report_definition={
                    "pbir_version": report_def.pbir_version,
                    "dataset_reference_path": report_def.dataset_reference_path,
                    "theme": report_def.theme
                },
                page_count=len(report_def.pages),
                visual_count=sum(len(p.visuals) for p in report_def.pages),
                report_configuration=report_def.report_configuration
            )
            reports.append(canonical_rep)

            # Pages
            for page in report_def.pages:
                page_obj_id = make_deterministic_uuid(
                    self.namespace,
                    f"kpi_intel:obj:{asset_version_id}:REPORT_PAGE:{page.source_native_id}"
                )
                objects.append(CanonicalAnalyticalObject(
                    object_id=page_obj_id,
                    asset_version_id=asset_version_id,
                    tenant_id=self.tenant_id,
                    parent_object_id=report_obj_id,
                    source_artifact_id=rep_art_id,
                    platform="POWER_BI",
                    object_type="REPORT_PAGE",
                    source_native_id=page.source_native_id,
                    source_native_name=page.page_name,
                    canonical_name=f"{report_def.report_name}.{page.page_name}",
                    display_name=page.page_name,
                    is_hidden=page.is_hidden
                ))

                canonical_page = CanonicalReportPage(
                    page_id=page_obj_id,
                    report_id=report_obj_id,
                    object_id=page_obj_id,
                    page_name=page.page_name,
                    source_native_id=page.source_native_id,
                    page_order=page.page_order,
                    page_type=page.page_type,
                    page_properties=page.page_properties,
                    is_hidden=page.is_hidden
                )
                pages.append(canonical_page)

                # Visuals
                for vis in page.visuals:
                    vis_obj_id = make_deterministic_uuid(
                        self.namespace,
                        f"kpi_intel:obj:{asset_version_id}:VISUAL:{page.source_native_id}:{vis.visual_id}"
                    )
                    objects.append(CanonicalAnalyticalObject(
                        object_id=vis_obj_id,
                        asset_version_id=asset_version_id,
                        tenant_id=self.tenant_id,
                        parent_object_id=page_obj_id,
                        source_artifact_id=rep_art_id,
                        platform="POWER_BI",
                        object_type="VISUAL",
                        source_native_id=vis.visual_id,
                        source_native_name=vis.title or vis.visual_type,
                        canonical_name=f"{page.page_name}.vis.{vis.visual_id}",
                        display_name=vis.title or f"{vis.visual_type} visual"
                    ))

                    canonical_vis = CanonicalVisual(
                        visual_id=vis_obj_id,
                        page_id=page_obj_id,
                        object_id=vis_obj_id,
                        visual_type=vis.visual_type,
                        source_native_id=vis.visual_id,
                        visual_title=vis.title,
                        visual_description=vis.description,
                        position_x=vis.position_x,
                        position_y=vis.position_y,
                        width=vis.width,
                        height=vis.height,
                        z_order=vis.z_order,
                        visual_configuration=vis.raw_config,
                        is_visible=vis.is_visible
                    )
                    visuals.append(canonical_vis)

                    # Visual Bindings
                    for b_idx, binding in enumerate(vis.bindings):
                        # Attempt to resolve bound object in semantic model
                        target_obj_id = None
                        if binding.target_entity and binding.target_property:
                            target_obj_id = column_lookup.get(f"{binding.target_entity}.{binding.target_property}")
                            if not target_obj_id:
                                target_obj_id = measure_lookup.get(binding.target_property)
                        elif binding.target_property:
                            target_obj_id = measure_lookup.get(binding.target_property) or column_lookup.get(binding.target_property)

                        if target_obj_id:
                            vb_id = make_deterministic_uuid(
                                self.namespace,
                                f"kpi_intel:vb:{vis_obj_id}:{target_obj_id}:{binding.binding_role}:{b_idx}"
                            )
                            visual_bindings.append(CanonicalVisualBinding(
                                visual_binding_id=vb_id,
                                visual_id=vis_obj_id,
                                object_id=target_obj_id,
                                binding_role=binding.binding_role,
                                binding_order=binding.binding_order,
                                aggregation_override=binding.aggregation,
                                format_override=binding.format_override,
                                binding_properties=binding.binding_properties
                            ))

                            # Add visual data binding lineage edge
                            edge_id = make_deterministic_uuid(
                                self.namespace,
                                f"kpi_intel:edge:{asset_version_id}:{target_obj_id}:{vis_obj_id}:VISUAL_DATA_BINDING"
                            )
                            lineage_edges.append(CanonicalMetadataLineageEdge(
                                lineage_edge_id=edge_id,
                                asset_version_id=asset_version_id,
                                source_object_id=target_obj_id,
                                target_object_id=vis_obj_id,
                                edge_type="VISUAL_DATA_BINDING",
                                derivation_method="PARSED",
                                confidence_score=1.0,
                                evidence={"binding_role": binding.binding_role, "visual_type": vis.visual_type}
                            ))

            # Bookmarks
            for bm in report_def.bookmarks:
                bm_obj_id = make_deterministic_uuid(
                    self.namespace,
                    f"kpi_intel:obj:{asset_version_id}:BOOKMARK:{bm.bookmark_id}"
                )
                objects.append(CanonicalAnalyticalObject(
                    object_id=bm_obj_id,
                    asset_version_id=asset_version_id,
                    tenant_id=self.tenant_id,
                    parent_object_id=report_obj_id,
                    source_artifact_id=rep_art_id,
                    platform="POWER_BI",
                    object_type="BOOKMARK",
                    source_native_id=bm.bookmark_id,
                    source_native_name=bm.display_name,
                    canonical_name=f"bookmark:{bm.bookmark_id}",
                    display_name=bm.display_name
                ))
                bookmarks.append(CanonicalBookmark(
                    bookmark_id=bm_obj_id,
                    object_id=bm_obj_id,
                    bookmark_name=bm.display_name,
                    source_native_id=bm.bookmark_id,
                    bookmark_state=bm.bookmark_state
                ))

        # 7. Extract DAX Measure & Calculation Lineage Dependencies
        dax_pattern = re.compile(r"(?:'([^']+)'|([a-zA-Z0-9_#$ -]+))?\[([^\]]+)\]")
        for calc in calculations:
            if not calc.expression_text:
                continue
            matches = dax_pattern.findall(calc.expression_text)
            for m in matches:
                tbl_part = m[0] or m[1]
                prop_part = m[2]
                
                dep_id = None
                if tbl_part and prop_part:
                    dep_id = column_lookup.get(f"{tbl_part}.{prop_part}")
                elif prop_part:
                    dep_id = measure_lookup.get(prop_part) or column_lookup.get(prop_part)

                if dep_id and dep_id != calc.object_id:
                    edge_id = make_deterministic_uuid(
                        self.namespace,
                        f"kpi_intel:edge:{asset_version_id}:{dep_id}:{calc.object_id}:MEASURE_DEPENDENCY"
                    )
                    lineage_edges.append(CanonicalMetadataLineageEdge(
                        lineage_edge_id=edge_id,
                        asset_version_id=asset_version_id,
                        source_object_id=dep_id,
                        target_object_id=calc.object_id,
                        edge_type="MEASURE_DEPENDENCY",
                        derivation_method="PARSED",
                        confidence_score=1.0,
                        evidence={"match": f"{tbl_part}[{prop_part}]" if tbl_part else f"[{prop_part}]"}
                    ))

        # 8. Parser Run & Extraction Errors Audit
        parser_run_id = make_deterministic_uuid(
            self.namespace,
            f"kpi_intel:parser_run:{asset_version_id}:{self.parser_version}"
        )
        warn_cnt = sum(1 for d in project_structure.diagnostics if d.severity == DiagnosticSeverity.WARNING)
        err_cnt = sum(1 for d in project_structure.diagnostics if d.severity in (DiagnosticSeverity.ERROR, DiagnosticSeverity.FATAL))

        parser_run = CanonicalParserRun(
            parser_run_id=parser_run_id,
            asset_version_id=asset_version_id,
            tenant_id=self.tenant_id,
            platform="POWER_BI",
            parser_name="powerbi_pbip_connector",
            parser_version=self.parser_version,
            run_status="SUCCESSFUL" if err_cnt == 0 else "PARTIAL",
            objects_extracted=len(objects),
            warnings_count=warn_cnt,
            errors_count=err_cnt,
            run_metadata={
                "asset_name": asset_name,
                "table_count": len(tables),
                "column_count": len(columns),
                "calculation_count": len(calculations),
                "relationship_count": len(relationships),
                "page_count": len(pages),
                "visual_count": len(visuals),
                "lineage_edge_count": len(lineage_edges)
            }
        )

        extraction_errors: List[CanonicalExtractionError] = []
        for idx, d in enumerate(project_structure.diagnostics):
            err_id = make_deterministic_uuid(
                self.namespace,
                f"kpi_intel:error:{parser_run_id}:{idx}:{d.code}"
            )
            extraction_errors.append(CanonicalExtractionError(
                extraction_error_id=err_id,
                parser_run_id=parser_run_id,
                severity=d.severity.value,
                error_code=d.code,
                error_message=d.message,
                object_locator=d.locator,
                is_recoverable=d.is_recoverable
            ))

        return CanonicalIngestionBundle(
            asset=asset,
            version=version,
            artifacts=artifacts,
            objects=objects,
            reports=reports,
            pages=pages,
            visuals=visuals,
            visual_bindings=visual_bindings,
            bookmarks=bookmarks,
            semantic_models=semantic_models,
            tables=tables,
            columns=columns,
            calculations=calculations,
            relationships=relationships,
            partitions=partitions,
            named_expressions=named_expressions,
            hierarchies=[],
            hierarchy_levels=[],
            filters=[],
            filter_assignments=[],
            lineage_edges=lineage_edges,
            parser_runs=[parser_run],
            extraction_errors=extraction_errors
        )
