"""
KPI Intelligence — Ingestion Service.

Main orchestrator coordinating platform extraction, canonical normalization,
content hashing, idempotent version resolution, and repository persistence
into Azure Cosmos DB for NoSQL (or local SQLite during testing).
"""

import os
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime

from backend.connectors.base import PlatformType, BaseConnector, Diagnostic, DiagnosticSeverity
from backend.connectors.registry import ConnectorRegistry
import backend.connectors.powerbi.connector
from backend.ingestion.models import CanonicalIngestionBundle
from backend.ingestion.converter import BundleToDocumentsConverter
from backend.repository.interfaces import IRepository
from backend.repository.context import TenantContext
from backend.repository.services import CatalogServiceRepository, AuditServiceRepository
from backend.storage.factory import get_repository


@dataclass
class IngestionSummary:
    asset_id: uuid.UUID
    asset_version_id: uuid.UUID
    tenant_id: uuid.UUID
    platform: str
    asset_name: str
    version_number: int
    content_hash: str
    raw_content_hash: str
    structure_hash: str
    metadata_hash: str
    stats: Dict[str, Any] = field(default_factory=dict)
    diagnostics: List[Diagnostic] = field(default_factory=list)
    sql_script: Optional[str] = None
    is_live: bool = True
    status: str = "SUCCESSFUL"


class IngestionService:
    """End-to-end ingestion pipeline orchestrator."""

    def __init__(
        self,
        tenant_id: uuid.UUID,
        parser_version: str = "1.0.0",
        repository: Optional[IRepository] = None,
    ):
        self.tenant_id = tenant_id
        self.parser_version = parser_version
        self.repo = repository or get_repository()
        self.catalog_repo = CatalogServiceRepository(self.repo)
        self.audit_repo = AuditServiceRepository(self.repo)

    def ingest_project(
        self,
        source_path: str,
        platform: PlatformType = PlatformType.POWER_BI,
        version_number: int = 1,
        generate_sql_only: bool = False,
    ) -> IngestionSummary:
        """
        Executes end-to-end ingestion of a BI project.
        """
        connector = ConnectorRegistry.get(platform)
        if not connector or not ConnectorRegistry.is_supported(platform):
            raise NotImplementedError(f"No active functional connector for platform '{platform.value}'.")

        # 1. Extraction via Connector
        extraction = connector.extract(source_path)
        if any(d.severity == DiagnosticSeverity.FATAL for d in extraction.diagnostics):
            first_fatal = next(d for d in extraction.diagnostics if d.severity == DiagnosticSeverity.FATAL)
            raise RuntimeError(f"Fatal extraction error: {first_fatal.message}")

        # 2. Project Structure Discovery
        from backend.connectors.powerbi.discovery import PbipDiscovery
        proj_struct = PbipDiscovery.discover(source_path)

        # 3. Canonical Normalization
        from backend.connectors.powerbi.normalizer import PowerBINormalizer
        normalizer = PowerBINormalizer(tenant_id=self.tenant_id, parser_version=self.parser_version)
        bundle = normalizer.normalize(
            project_structure=proj_struct,
            tmdl_model=extraction.raw_model,
            report_def=extraction.raw_report,
            version_number=version_number
        )

        # 4. Persistence via Canonical Repository
        context = TenantContext(tenant_id=str(self.tenant_id))
        docs = BundleToDocumentsConverter.convert(bundle)

        if not generate_sql_only:
            # Save Asset & Version
            for a in docs["assets"]:
                self.catalog_repo.save_asset(a, context)
            for v in docs["asset_versions"]:
                self.catalog_repo.save_asset_version(v, context)

            # Save Reports
            for r in docs["reports"]:
                self.catalog_repo.save_report(r, context)

            # Save Models
            for m in docs["semantic_models"]:
                self.catalog_repo.save_semantic_model(m, context)

            # Save Lineage
            for e in docs["lineage_edges"]:
                self.catalog_repo.save_lineage_edge(e, context)

            # Save Runs & Errors
            for run in docs["parser_runs"]:
                self.audit_repo.log_parser_run(run, context)
            for err in docs["extraction_errors"]:
                self.audit_repo.log_error(err, context)

        # Optional legacy SQL script generation for migration/debug
        sql_script = None
        try:
            from backend.ingestion.persistence import CanonicalPersistenceService
            persister = CanonicalPersistenceService(tenant_id=self.tenant_id)
            sql_script = persister.generate_transactional_sql(bundle)
        except Exception:
            pass

        all_stats = {
            "source_artifacts": len(bundle.artifacts),
            "analytical_objects": len(bundle.objects),
            "reports": len(bundle.reports),
            "report_pages": len(bundle.pages),
            "visuals": len(bundle.visuals),
            "visual_bindings": len(bundle.visual_bindings),
            "bookmarks": len(bundle.bookmarks),
            "semantic_models": len(bundle.semantic_models),
            "data_tables": len(bundle.tables),
            "data_columns": len(bundle.columns),
            "calculations": len(bundle.calculations),
            "relationships": len(bundle.relationships),
            "model_partitions": len(bundle.partitions),
            "named_expressions": len(bundle.named_expressions),
            "metadata_lineage_edges": len(bundle.lineage_edges),
            "raw_stats": extraction.run_stats,
            "cosmos_documents_persisted": sum(len(v) for v in docs.values()) if not generate_sql_only else 0,
        }

        return IngestionSummary(
            asset_id=bundle.asset.asset_id,
            asset_version_id=bundle.version.asset_version_id,
            tenant_id=self.tenant_id,
            platform=platform.value,
            asset_name=bundle.asset.asset_name,
            version_number=bundle.version.version_number,
            content_hash=bundle.version.content_hash,
            raw_content_hash=bundle.version.raw_content_hash,
            structure_hash=bundle.version.structure_hash,
            metadata_hash=bundle.version.metadata_hash,
            stats=all_stats,
            diagnostics=extraction.diagnostics,
            sql_script=sql_script,
            is_live=not generate_sql_only,
            status="SUCCESSFUL",
        )
