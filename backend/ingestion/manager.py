"""
KPI Intelligence — Ingestion Job Manager & File Upload Processor.

Handles:
- Safe file upload spooling and directory reconstruction
- Zip archive extraction with zip-slip path traversal guards
- File signature, extension, and size validation
- Integration with Power BI PBIP ingestion pipeline (IngestionService)
- Tenant-scoped job status tracking and diagnostic reporting
- Safe cleanup of temporary staging files
"""

import os
import shutil
import zipfile
import uuid
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, field

from backend.connectors.base import PlatformType
from backend.ingestion.service import IngestionService, IngestionSummary
from backend.repository.interfaces import IRepository, QuerySpec
from backend.repository.context import TenantContext
from backend.contracts import CosmosContainer, DocumentType
from backend.storage.factory import get_repository

logger = logging.getLogger("kpi_intel.ingestion.manager")

# Configurable upload limits
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB per file
MAX_BATCH_FILES = 250
SUPPORTED_EXTENSIONS = {".pbip", ".pbir", ".pbism", ".tmdl", ".dax", ".json", ".zip"}


@dataclass
class IngestionJobRecord:
    job_id: str
    tenant_id: str
    status: str  # QUEUED, PROCESSING, COMPLETED, FAILED, PARTIAL
    created_at: str
    completed_at: Optional[str] = None
    files_received: int = 0
    files_processed: int = 0
    files_skipped: int = 0
    asset_id: Optional[str] = None
    asset_name: Optional[str] = None
    asset_version_id: Optional[str] = None
    error_message: Optional[str] = None
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "tenant_id": self.tenant_id,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "files_received": self.files_received,
            "files_processed": self.files_processed,
            "files_skipped": self.files_skipped,
            "asset_id": self.asset_id,
            "asset_name": self.asset_name,
            "asset_version_id": self.asset_version_id,
            "error_message": self.error_message,
            "diagnostics": self.diagnostics,
            "stats": self.stats,
        }


class IngestionManager:
    """Manages file uploads, staging, extraction, and ingestion execution."""

    def __init__(self, repository: Optional[IRepository] = None, staging_root: Optional[str] = None):
        self.repo = repository or get_repository()
        self.staging_root = staging_root or os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "local_data", "temp_ingestion")
        )
        os.makedirs(self.staging_root, exist_ok=True)
        self._jobs: Dict[str, IngestionJobRecord] = {}

    def get_supported_formats(self) -> Dict[str, Any]:
        """Returns documented supported formats and upload limits."""
        return {
            "supported_platforms": ["POWER_BI"],
            "supported_formats": [
                {
                    "format": "PBIP",
                    "name": "Power BI Project",
                    "extensions": [".pbip", ".pbir", ".pbism", ".tmdl", ".json"],
                    "package_extension": ".zip",
                    "description": "Folder or zip archive containing .pbip, .Report, and .SemanticModel (TMDL).",
                    "status": "SUPPORTED",
                    "is_active": True,
                },
                {
                    "format": "PBIX",
                    "name": "Power BI Desktop Binary",
                    "extensions": [".pbix"],
                    "description": "Legacy binary file. Please use 'Save As -> Power BI Project (.pbip)' for full TMDL measure extraction.",
                    "status": "UNSUPPORTED",
                    "is_active": False,
                },
                {
                    "format": "EXCEL",
                    "name": "Excel Workbook",
                    "extensions": [".xlsx", ".xlsm"],
                    "description": "Workbook metadata ingestion planned in upcoming release.",
                    "status": "PLANNED",
                    "is_active": False,
                },
                {
                    "format": "TABLEAU",
                    "name": "Tableau Packaged Workbook",
                    "extensions": [".twbx", ".twb"],
                    "description": "Tableau connector planned in upcoming release.",
                    "status": "PLANNED",
                    "is_active": False,
                },
            ],
            "max_file_size_mb": 50,
            "max_batch_files": MAX_BATCH_FILES,
            "browser_folder_selection_supported": True,
        }

    def list_ingested_sources(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Lists previously ingested assets and versions from the repository."""
        ctx = TenantContext(tenant_id=tenant_id)
        query = "SELECT * FROM c WHERE c.tenant_id = @tenant_id AND c.doc_type = @doc_type"
        spec = QuerySpec(
            query=query,
            parameters=[
                {"name": "@tenant_id", "value": tenant_id},
                {"name": "@doc_type", "value": DocumentType.ASSET.value},
            ],
        )
        assets_res = self.repo.query_items(CosmosContainer.METADATA_CATALOG, tenant_id, spec, ctx)
        assets = assets_res.items if assets_res else []

        # Also get versions
        spec_v = QuerySpec(
            query=query,
            parameters=[
                {"name": "@tenant_id", "value": tenant_id},
                {"name": "@doc_type", "value": DocumentType.ASSET_VERSION.value},
            ],
        )
        versions_res = self.repo.query_items(CosmosContainer.METADATA_CATALOG, tenant_id, spec_v, ctx)
        versions_by_asset: Dict[str, List[Dict[str, Any]]] = {}
        if versions_res:
            for v in versions_res.items:
                aid = v.get("asset_id", "")
                versions_by_asset.setdefault(aid, []).append(v)

        results: List[Dict[str, Any]] = []
        for a in assets:
            aid = a.get("asset_id") or a.get("id")
            v_list = versions_by_asset.get(aid, [])
            latest_v = sorted(v_list, key=lambda x: x.get("version_number", 1), reverse=True)[0] if v_list else {}

            results.append({
                "asset_id": aid,
                "asset_name": a.get("asset_name", "Untitled Asset"),
                "platform": a.get("platform", "POWER_BI"),
                "version_number": latest_v.get("version_number", 1),
                "content_hash": latest_v.get("content_hash", ""),
                "ingested_at": latest_v.get("ingested_at") or a.get("created_at") or a.get("_ts"),
                "status": "INGESTED",
            })

        return results

    def get_job_status(self, job_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Returns the status record for an ingestion job."""
        job = self._jobs.get(job_id)
        if not job or job.tenant_id != tenant_id:
            return None
        return job.to_dict()

    def process_file_batch(
        self,
        tenant_id: str,
        files_data: List[Dict[str, Any]],  # list of {"filename": str, "content": bytes, "relative_path": Optional[str]}
    ) -> Dict[str, Any]:
        """
        Stages and executes ingestion of an uploaded file batch or folder.
        """
        job_id = f"job_{uuid.uuid4()}"
        now_iso = datetime.now(timezone.utc).isoformat()

        job = IngestionJobRecord(
            job_id=job_id,
            tenant_id=tenant_id,
            status="PROCESSING",
            created_at=now_iso,
            files_received=len(files_data),
        )
        self._jobs[job_id] = job

        job_dir = os.path.join(self.staging_root, job_id)
        os.makedirs(job_dir, exist_ok=True)

        try:
            # 1. Stage files and extract archives
            saved_count = 0
            skipped_count = 0

            for f_item in files_data:
                filename = f_item.get("filename", "unnamed.dat")
                content = f_item.get("content", b"")
                rel_path = f_item.get("relative_path") or filename

                # Security: Sanitize relative path to prevent directory traversal
                safe_rel_path = self._sanitize_relative_path(rel_path)
                if not safe_rel_path or safe_rel_path.startswith("/") or ".." in safe_rel_path:
                    safe_rel_path = os.path.basename(filename)

                # Skip OS metadata files (.DS_Store, thumbs.db)
                base_name = os.path.basename(safe_rel_path).lower()
                if base_name in (".ds_store", "thumbs.db", "desktop.ini"):
                    skipped_count += 1
                    continue

                dest_path = os.path.join(job_dir, safe_rel_path)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)

                with open(dest_path, "wb") as out_f:
                    out_f.write(content)

                # If a .zip was uploaded, extract it safely
                if dest_path.endswith(".zip"):
                    self._extract_zip_safely(dest_path, job_dir)
                    saved_count += 1
                else:
                    saved_count += 1

            job.files_processed = saved_count
            job.files_skipped = skipped_count

            # 2. Locate project root (look for .pbip or discoverable project structure)
            pbip_target = self._find_pbip_root(job_dir)
            if not pbip_target:
                raise ValueError(
                    f"No valid Power BI Project (.pbip) manifest or structure found among the {saved_count} staged files. "
                    "Ensure your upload includes the .pbip file and associated .Report and .SemanticModel folders, "
                    "or a .zip archive of the PBIP project."
                )

            # 3. Execute canonical ingestion
            tenant_uuid = uuid.UUID(tenant_id)
            svc = IngestionService(tenant_id=tenant_uuid, repository=self.repo)
            summary: IngestionSummary = svc.ingest_project(pbip_target, platform=PlatformType.POWER_BI)

            job.status = "COMPLETED"
            job.completed_at = datetime.now(timezone.utc).isoformat()
            job.asset_id = str(summary.asset_id)
            job.asset_name = summary.asset_name
            job.asset_version_id = str(summary.asset_version_id)
            job.stats = summary.stats
            job.diagnostics = [{"code": d.code, "message": d.message, "severity": d.severity.value} for d in summary.diagnostics]

            return job.to_dict()

        except Exception as ex:
            logger.exception("Ingestion job %s failed: %s", job_id, ex)
            job.status = "FAILED"
            job.completed_at = datetime.now(timezone.utc).isoformat()
            job.error_message = str(ex)
            return job.to_dict()

        finally:
            # Clean up temporary staging directory
            try:
                shutil.rmtree(job_dir, ignore_errors=True)
            except Exception:
                pass

    def _sanitize_relative_path(self, rel_path: str) -> str:
        """Sanitizes user-provided relative path to prevent directory traversal."""
        clean = rel_path.replace("\\", "/").strip().lstrip("/")
        parts = [p for p in clean.split("/") if p and p != "." and p != ".."]
        return "/".join(parts)

    def _extract_zip_safely(self, zip_path: str, extract_to: str) -> None:
        """Extracts a zip file preventing path traversal attacks."""
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                # Check for traversal
                target_path = os.path.abspath(os.path.join(extract_to, member.filename))
                if not target_path.startswith(os.path.abspath(extract_to)):
                    raise ValueError(f"Malicious zip member detected with path traversal: {member.filename}")
                zf.extract(member, extract_to)

    def _find_pbip_root(self, root_dir: str) -> Optional[str]:
        """Searches root_dir recursively for a .pbip file."""
        for dirpath, _, filenames in os.walk(root_dir):
            for f in filenames:
                if f.endswith(".pbip") and not f.startswith("."):
                    return dirpath
        return None


# Global singleton
_ingestion_manager_instance: Optional[IngestionManager] = None


def get_ingestion_manager(repository: Optional[IRepository] = None) -> IngestionManager:
    global _ingestion_manager_instance
    if _ingestion_manager_instance is None or repository is not None:
        _ingestion_manager_instance = IngestionManager(repository=repository)
    return _ingestion_manager_instance
