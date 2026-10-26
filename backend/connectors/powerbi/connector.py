"""
KPI Intelligence — Power BI PBIP Connector.

Production connector implementation for Power BI Projects (.pbip).
Integrates discovery, TMDL semantic model parsing, PBIR report parsing,
JSONC decoding, diagnostic collection, and declared platform capabilities.
"""

import os
from typing import List, Dict, Any, Optional

from backend.connectors.base import (
    BaseConnector,
    PlatformType,
    ArtifactManifestItem,
    ExtractionResult,
    PlatformCapability,
    CapabilityStatus,
    Diagnostic,
    DiagnosticSeverity,
)
from backend.connectors.registry import ConnectorRegistry
from backend.connectors.powerbi.discovery import PbipDiscovery, PbipProjectStructure
from backend.connectors.powerbi.tmdl_parser import TmdlParser, TmdlModel
from backend.connectors.powerbi.report_parser import ReportParser, ReportDefinition


class PowerBIConnector(BaseConnector):
    """Production Power BI PBIP metadata connector."""

    def __init__(self, parser_version: str = "1.0.0"):
        self._parser_version = parser_version

    @property
    def platform(self) -> PlatformType:
        return PlatformType.POWER_BI

    @property
    def parser_name(self) -> str:
        return "powerbi_pbip_connector"

    @property
    def parser_version(self) -> str:
        return self._parser_version

    def discover(self, source_path: str) -> List[ArtifactManifestItem]:
        """Discovers all source artifacts within a PBIP bundle."""
        proj = PbipDiscovery.discover(source_path)
        return proj.artifacts

    def extract(self, source_path: str) -> ExtractionResult:
        """
        Executes complete metadata extraction across the PBIP project bundle:
        discovers files, parses TMDL tabular model, parses report layout and visuals.
        """
        proj = PbipDiscovery.discover(source_path)
        diagnostics: List[Diagnostic] = list(proj.diagnostics)
        
        tmdl_model: Optional[TmdlModel] = None
        if proj.semantic_model_dir_path:
            try:
                tmdl_model = TmdlParser.parse_semantic_model_directory(proj.semantic_model_dir_path)
            except Exception as e:
                diagnostics.append(Diagnostic(
                    code="TMDL_EXTRACTION_FAILED",
                    message=f"Failed to parse TMDL semantic model directory: {e}",
                    severity=DiagnosticSeverity.ERROR,
                    source_artifact=os.path.basename(proj.semantic_model_dir_path)
                ))

        report_def: Optional[ReportDefinition] = None
        if proj.report_dir_path:
            try:
                report_def = ReportParser.parse_report_directory(proj.report_dir_path, asset_name=proj.asset_name)
            except Exception as e:
                diagnostics.append(Diagnostic(
                    code="REPORT_EXTRACTION_FAILED",
                    message=f"Failed to parse report directory: {e}",
                    severity=DiagnosticSeverity.ERROR,
                    source_artifact=os.path.basename(proj.report_dir_path)
                ))

        run_stats = {
            "pbip_version": proj.pbip_version,
            "artifact_count": len(proj.artifacts),
            "table_count": len(tmdl_model.tables) if tmdl_model else 0,
            "relationship_count": len(tmdl_model.relationships) if tmdl_model else 0,
            "expression_count": len(tmdl_model.expressions) if tmdl_model else 0,
            "page_count": len(report_def.pages) if report_def else 0,
            "bookmark_count": len(report_def.bookmarks) if report_def else 0,
            "custom_visual_count": len(report_def.custom_visuals) if report_def else 0,
        }

        return ExtractionResult(
            platform=self.platform,
            source_path=source_path,
            asset_name=proj.asset_name,
            artifacts=proj.artifacts,
            raw_model=tmdl_model,
            raw_report=report_def,
            diagnostics=diagnostics,
            metadata={"settings": proj.settings, "pbip_file": proj.pbip_file_path},
            run_stats=run_stats
        )

    def get_capabilities(self) -> List[PlatformCapability]:
        """Returns declared metadata capabilities for Power BI PBIP."""
        return [
            PlatformCapability(
                platform=PlatformType.POWER_BI,
                artifact_type="PBIP",
                metadata_type="SEMANTIC_MODEL_TMDL",
                capability_status=CapabilityStatus.SUPPORTED,
                notes="Full support for TMDL tabular models, tables, columns, partitions, hierarchies"
            ),
            PlatformCapability(
                platform=PlatformType.POWER_BI,
                artifact_type="PBIP",
                metadata_type="DAX_CALCULATIONS",
                capability_status=CapabilityStatus.SUPPORTED,
                notes="Support for measures, calculated columns, calculation groups, and dependency extraction"
            ),
            PlatformCapability(
                platform=PlatformType.POWER_BI,
                artifact_type="PBIP",
                metadata_type="RELATIONSHIPS",
                capability_status=CapabilityStatus.SUPPORTED,
                notes="Support for model relationships, cardinality, and cross-filtering behavior"
            ),
            PlatformCapability(
                platform=PlatformType.POWER_BI,
                artifact_type="PBIP",
                metadata_type="REPORT_LAYOUT",
                capability_status=CapabilityStatus.SUPPORTED,
                notes="Support for report sections/pages, visual containers, bookmarks, and theme references"
            ),
            PlatformCapability(
                platform=PlatformType.POWER_BI,
                artifact_type="PBIP",
                metadata_type="M_EXPRESSIONS",
                capability_status=CapabilityStatus.SUPPORTED,
                notes="Support for Power Query shared M queries and parameters"
            ),
            PlatformCapability(
                platform=PlatformType.POWER_BI,
                artifact_type="PBIP",
                metadata_type="CUSTOM_VISUALS",
                capability_status=CapabilityStatus.SUPPORTED,
                notes="Support for custom visual packages, guids, and visual metadata"
            ),
            PlatformCapability(
                platform=PlatformType.POWER_BI,
                artifact_type="PBIP",
                metadata_type="ROW_LEVEL_SECURITY",
                capability_status=CapabilityStatus.SUPPORTED,
                notes="Support for TMDL role definitions and table filter predicates"
            ),
        ]


# Register Power BI connector with the central registry
ConnectorRegistry.register(PowerBIConnector())
