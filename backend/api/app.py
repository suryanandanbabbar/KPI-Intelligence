"""
KPI Intelligence — FastAPI Backend Application.

Enterprise REST API providing:
- Health and readiness diagnostics
- Workspace summary and operational metrics
- Domain segregation and classification
- Canonical analytical metadata inspection
- Automated & deterministic KPI mapping execution
- Human approval, rejection, and manual override with mandatory justification
- KPI Bank search and schema-compliant creation
- Persistent learning and override retrieval
- Immutable compliance audit trail
"""

import os
import re
import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator
from fastapi import FastAPI, APIRouter, Depends, Header, Query, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.governance.service import get_governance_service, GovernanceService
from backend.domain.service import DOMAIN_METADATA
from backend.storage.fixtures import TENANT_ALPHA
from backend.repository.context import TenantAccessDeniedError
from backend.repository.interfaces import DocumentNotFoundError, ConcurrencyConflictError
from backend.ingestion.manager import IngestionManager, get_ingestion_manager

logger = logging.getLogger("kpi_intel.api")

# Default CORS origins (explicitly configured, no wildcard with credentials)
DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]


# =============================================================================
# PYDANTIC REQUEST & RESPONSE SCHEMAS
# =============================================================================

class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "kpi-intelligence-api"
    version: str = "1.0.0"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ReadyResponse(BaseModel):
    status: str = "ready"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DomainCorrectionRequest(BaseModel):
    target_object_id: Optional[str] = None
    corrected_domain: str
    previous_domain: Optional[str] = None
    justification: Optional[str] = None
    user_id: str = "analyst"


class MappingRunRequest(BaseModel):
    user_id: str = "analyst"
    force_fallback: bool = False


class ApproveRequest(BaseModel):
    mapping_id: str
    approved_kpi_id: str
    user_id: str = "analyst"


class RejectRequest(BaseModel):
    mapping_id: str
    reason: Optional[str] = None
    user_id: str = "analyst"


class OverrideRequest(BaseModel):
    mapping_id: str
    replacement_kpi_id: str
    override_justification: str
    user_id: str = "analyst"

    @field_validator("override_justification")
    @classmethod
    def validate_justification(cls, v: str) -> str:
        stripped = v.strip() if v else ""
        if len(stripped) < 10:
            raise ValueError("Override justification is strictly required and must contain at least 10 non-whitespace characters.")
        return stripped


class KpiCreateRequest(BaseModel):
    name: str
    definition: str
    domain: str = "General"
    formula: Optional[str] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    dimensions: List[str] = Field(default_factory=list)
    enrichments: Dict[str, Any] = Field(default_factory=dict)
    mapping_id: Optional[str] = None
    user_id: str = "analyst"


class InvalidateOverrideRequest(BaseModel):
    override_id: str
    user_id: str = "analyst"
    reason: str = "Manual invalidation"


# =============================================================================
# DEPENDENCY INJECTION
# =============================================================================

class AppDependencies:
    """Holds injectable services for FastAPI endpoints."""
    def __init__(
        self,
        governance_service: Optional[GovernanceService] = None,
        ingestion_manager: Optional[IngestionManager] = None,
    ):
        self.governance_service = governance_service or get_governance_service()
        self.ingestion_manager = ingestion_manager or get_ingestion_manager(repository=self.governance_service.repo)


_deps_instance: Optional[AppDependencies] = None


def get_dependencies() -> AppDependencies:
    global _deps_instance
    if _deps_instance is None:
        _deps_instance = AppDependencies()
    return _deps_instance


def get_tenant_id(
    x_tenant_id: Optional[str] = Header(default=None),
    tenant_id: Optional[str] = Query(default=None),
) -> str:
    """Extracts tenant ID from header or query param, defaulting to TENANT_ALPHA."""
    return x_tenant_id or tenant_id or TENANT_ALPHA


# =============================================================================
# FASTAPI ROUTER DEFINITION
# =============================================================================

router = APIRouter(prefix="/api/v1", tags=["KPI Intelligence API"])


@router.get("/workspace/summary")
def get_workspace_summary(
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Returns aggregated operational metrics for the workspace."""
    summary = deps.governance_service.get_workspace_summary(tenant_id)
    return {"success": True, "data": summary}


@router.get("/llm/status")
def get_llm_status(deps: AppDependencies = Depends(get_dependencies)):
    """Returns non-sensitive operational status of the Azure AI Foundry Llama deployment."""
    orchestrator = getattr(deps.governance_service, "matcher", None) or getattr(deps.governance_service, "matching", None)
    llm_info = orchestrator.get_status() if orchestrator and hasattr(orchestrator, "get_status") else {
        "llm_configured": False,
        "llm_provider": "Azure AI Foundry (Llama)",
        "fallback_available": True,
    }
    return {"success": True, "data": llm_info}


@router.get("/domains")
def get_domains(deps: AppDependencies = Depends(get_dependencies)):
    """Returns canonical domain classifications with definitions and counts."""
    domains = deps.governance_service.domain_service.get_supported_domains()
    return {"success": True, "data": domains}


@router.get("/domains/{domain}/metrics")
def get_domain_metrics(
    domain: str,
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Returns domain-specific governance and proposal metrics."""
    domain_code = domain.upper()
    domain_fields = deps.governance_service.list_fields_with_mappings(tenant_id, domain=domain_code)

    awaiting = sum(1 for f in domain_fields if f.get("mapping_status") == "PROPOSED")
    approved = sum(1 for f in domain_fields if f.get("mapping_status") in ("APPROVED", "OVERRIDDEN"))
    rejected = sum(1 for f in domain_fields if f.get("mapping_status") == "REJECTED")
    unmapped = sum(1 for f in domain_fields if f.get("mapping_status") == "UNMAPPED")

    return {
        "success": True,
        "data": {
            "domain": domain_code,
            "domain_info": DOMAIN_METADATA.get(domain_code, {}),
            "total_fields": len(domain_fields),
            "awaiting_approval": awaiting,
            "approved": approved,
            "rejected": rejected,
            "unmapped": unmapped,
            "fields": domain_fields,
        },
    }


@router.post("/metadata/fields/{field_id}/domain")
def update_field_domain(
    field_id: str,
    payload: DomainCorrectionRequest,
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Records a human domain correction for a canonical metadata field."""
    target_id = payload.target_object_id or field_id
    res = deps.governance_service.domain_service.record_human_correction(
        tenant_id=tenant_id,
        target_object_id=target_id,
        corrected_domain=payload.corrected_domain,
        user_id=payload.user_id,
        justification=payload.justification,
        previous_domain=payload.previous_domain,
    )
    return {"success": True, "data": res}


@router.post("/domain/classify")
def classify_domain_alias(
    payload: DomainCorrectionRequest,
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Compatibility alias for domain classification / human correction."""
    target_id = payload.target_object_id or "unknown"
    res = deps.governance_service.domain_service.record_human_correction(
        tenant_id=tenant_id,
        target_object_id=target_id,
        corrected_domain=payload.corrected_domain,
        user_id=payload.user_id,
        justification=payload.justification,
        previous_domain=payload.previous_domain,
    )
    return {"success": True, "data": res}


@router.get("/metadata/fields")
def list_metadata_fields(
    domain: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    entity_type: Optional[str] = Query(default=None),
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Returns canonical analytical metadata fields (read strictly from canonical documents)."""
    fields = deps.governance_service.list_fields_with_mappings(
        tenant_id=tenant_id,
        domain=domain,
        status=status,
        entity_type=entity_type,
    )
    return {"success": True, "count": len(fields), "data": fields}


@router.get("/metadata/fields/{field_id}")
def get_metadata_field_detail(
    field_id: str,
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Returns candidate proposals and detail for a single metadata field."""
    candidates_info = deps.governance_service.get_field_candidates(tenant_id, field_id)
    return {"success": True, "data": candidates_info}


@router.get("/mapping/fields/{field_id}/candidates")
def get_field_candidates(
    field_id: str,
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Returns top-3 ranked KPI candidates with structured evidence for a field."""
    candidates_info = deps.governance_service.get_field_candidates(tenant_id, field_id)
    return {"success": True, "data": candidates_info}


@router.get("/mappings/proposals")
@router.get("/mapping/proposals")
def list_mapping_proposals(
    domain: Optional[str] = Query(default=None),
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Lists mapping proposals awaiting human review."""
    fields = deps.governance_service.list_fields_with_mappings(
        tenant_id=tenant_id,
        domain=domain,
        status="PROPOSED",
    )
    return {"success": True, "count": len(fields), "data": fields}


@router.get("/mappings/proposals/{proposal_id}")
def get_mapping_proposal_detail(
    proposal_id: str,
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Returns detailed proposal information for human review."""
    data = deps.governance_service.get_field_candidates(tenant_id, proposal_id)
    return {"success": True, "data": data}


@router.post("/mapping/run")
@router.post("/mappings/run")
def run_mapping_pipeline(
    payload: Optional[MappingRunRequest] = None,
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Executes the mapping pipeline on all extracted canonical metadata fields."""
    import time as _pytime
    start_time = _pytime.time()
    user_id = payload.user_id if payload else "analyst"
    force_fallback = payload.force_fallback if payload else False

    logger.info(
        "POST /api/v1/mapping/run initiated: tenant=%s, user=%s, force_fallback=%s",
        tenant_id,
        user_id,
        force_fallback,
    )
    try:
        res = deps.governance_service.run_mapping_pipeline(
            tenant_id=tenant_id,
            user_id=user_id,
            force_fallback=force_fallback,
        )
        elapsed = round(_pytime.time() - start_time, 2)
        logger.info(
            "POST /api/v1/mapping/run completed in %.2fs: tenant=%s, total=%d, fallback_used=%s",
            elapsed,
            tenant_id,
            res.get("total_fields", 0),
            res.get("fallback_used", False),
        )
        return {"success": True, "data": res}
    except Exception as ex:
        elapsed = round(_pytime.time() - start_time, 2)
        logger.error(
            "POST /api/v1/mapping/run failed after %.2fs for tenant %s: %s",
            elapsed,
            tenant_id,
            str(ex),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Mapping pipeline execution failed: {str(ex)}",
        )


@router.post("/mapping/approve")
@router.post("/mappings/proposals/{proposal_id}/approve")
def approve_mapping(
    payload: ApproveRequest,
    proposal_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """
    Approves a proposed KPI candidate.
    HIGH confidence NEVER auto-approves: explicit human approval is mandatory.
    """
    mapping_id = payload.mapping_id or proposal_id
    if not mapping_id:
        raise HTTPException(status_code=400, detail="'mapping_id' is required.")
    res = deps.governance_service.approve_candidate(
        tenant_id=tenant_id,
        mapping_id=mapping_id,
        approved_kpi_id=payload.approved_kpi_id,
        user_id=payload.user_id,
    )
    return {"success": True, "data": res}


@router.post("/mapping/reject")
@router.post("/mappings/proposals/{proposal_id}/reject")
def reject_mapping(
    payload: RejectRequest,
    proposal_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Rejects a proposed KPI candidate with structured reason tracking."""
    mapping_id = payload.mapping_id or proposal_id
    if not mapping_id:
        raise HTTPException(status_code=400, detail="'mapping_id' is required.")
    res = deps.governance_service.reject_candidate(
        tenant_id=tenant_id,
        mapping_id=mapping_id,
        user_id=payload.user_id,
        reason=payload.reason,
    )
    return {"success": True, "data": res}


@router.post("/mapping/override")
@router.post("/mappings/proposals/{proposal_id}/override")
def override_mapping(
    payload: OverrideRequest,
    proposal_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """
    Overrides candidate mapping with an alternative KPI.
    Strictly requires non-empty justification of at least 10 non-whitespace characters.
    """
    mapping_id = payload.mapping_id or proposal_id
    if not mapping_id:
        raise HTTPException(status_code=400, detail="'mapping_id' is required.")
    res = deps.governance_service.override_mapping(
        tenant_id=tenant_id,
        mapping_id=mapping_id,
        replacement_kpi_id=payload.replacement_kpi_id,
        override_justification=payload.override_justification,
        user_id=payload.user_id,
    )
    return {"success": True, "data": res}


@router.get("/kpi-bank/search")
@router.get("/kpi-bank")
def search_kpi_bank(
    q: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Searches the reference KPI Bank with normalized token and domain matching."""
    results = deps.governance_service.kpi_bank.search(query=q, domain=domain, status=status)
    return {"success": True, "count": len(results), "data": results}


@router.post("/kpi-bank/create", status_code=status.HTTP_201_CREATED)
@router.post("/kpi-bank", status_code=status.HTTP_201_CREATED)
def create_kpi(
    payload: KpiCreateRequest,
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Creates a governed, schema-compliant KPI in the KPI Bank."""
    kpi_dict = payload.model_dump()
    mapping_id = payload.mapping_id
    if mapping_id:
        res = deps.governance_service.create_kpi_and_map(
            tenant_id=tenant_id,
            mapping_id=mapping_id,
            kpi_data=kpi_dict,
            user_id=payload.user_id,
        )
        return {"success": True, "data": res}
    else:
        new_kpi = deps.governance_service.kpi_bank.create_kpi(kpi_dict)
        return {"success": True, "data": new_kpi}


@router.get("/overrides")
def list_overrides(
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Lists active learned overrides and reuse statistics for the tenant."""
    overrides = deps.governance_service.learning_service.list_active_overrides(tenant_id)
    return {"success": True, "count": len(overrides), "data": overrides}


@router.post("/overrides/invalidate")
def invalidate_override(
    payload: InvalidateOverrideRequest,
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Invalidates an active override rule."""
    success = deps.governance_service.learning_service.invalidate_override(
        tenant_id=tenant_id,
        override_id=payload.override_id,
        user_id=payload.user_id,
        reason=payload.reason,
    )
    return {"success": success}


@router.get("/audit/history")
@router.get("/audit/events")
def list_audit_history(
    limit: int = Query(default=50, ge=1, le=500),
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Returns chronological immutable audit records for the tenant."""
    history = deps.governance_service.list_audit_history(tenant_id, limit=limit)
    return {"success": True, "count": len(history), "data": history}


# =============================================================================
# INGESTION & SOURCE UPLOAD ENDPOINTS
# =============================================================================

async def _extract_upload_files(request: Request) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Extracts uploaded files and optional relative_paths from multipart/form-data or application/json,
    using Python standard library to ensure 100% dependency-free operation.
    """
    content_type = request.headers.get("content-type", "")
    body = await request.body()
    files_data = []
    relative_paths_json = None

    if "multipart/form-data" in content_type:
        import email
        from email.policy import default

        raw_headers = f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
        msg = email.message_from_bytes(raw_headers + body, policy=default)
        for part in msg.iter_parts():
            field_name = part.get_param("name", header="content-disposition")
            filename = part.get_filename()
            if filename is not None:
                content = part.get_payload(decode=True) or b""
                files_data.append({
                    "filename": filename,
                    "content": content,
                    "relative_path": filename,
                })
            elif field_name == "relative_paths":
                payload_bytes = part.get_payload(decode=True)
                if payload_bytes:
                    relative_paths_json = payload_bytes.decode("utf-8", errors="replace")
    elif "application/json" in content_type and body:
        import base64
        try:
            payload = json.loads(body.decode("utf-8", errors="replace"))
            for item in payload.get("files", []):
                name = item.get("filename", "unknown.dat")
                content = item.get("content")
                if isinstance(content, str):
                    if item.get("is_base64"):
                        content_bytes = base64.b64decode(content)
                    else:
                        content_bytes = content.encode("utf-8")
                elif isinstance(content, bytes):
                    content_bytes = content
                else:
                    content_bytes = b""
                files_data.append({
                    "filename": name,
                    "content": content_bytes,
                    "relative_path": item.get("relative_path") or name,
                })
            rel_val = payload.get("relative_paths")
            if isinstance(rel_val, list):
                relative_paths_json = json.dumps(rel_val)
            elif isinstance(rel_val, str):
                relative_paths_json = rel_val
        except Exception:
            pass

    return files_data, relative_paths_json


@router.get("/ingestion/supported-formats")
def get_supported_formats(deps: AppDependencies = Depends(get_dependencies)):
    """Returns officially supported ingestion formats and limitations."""
    formats = deps.ingestion_manager.get_supported_formats()
    return {"success": True, "data": formats}


@router.get("/ingestion/sources")
def list_ingested_sources(
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Returns previously ingested assets and reports for the tenant."""
    sources = deps.ingestion_manager.list_ingested_sources(tenant_id)
    return {"success": True, "count": len(sources), "data": sources}


@router.post("/ingestion/uploads")
async def upload_files(
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """
    Uploads a batch of files (e.g. .pbip, .tmdl, .json, or .zip archive)
    and executes ingestion into the canonical catalog.
    """
    files_data, _ = await _extract_upload_files(request)
    if not files_data:
        raise HTTPException(status_code=400, detail="No files provided in upload.")

    result = deps.ingestion_manager.process_file_batch(
        tenant_id=tenant_id,
        files_data=files_data,
    )

    if result.get("status") == "FAILED":
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": result.get("error_message"), "data": result},
        )

    return {"success": True, "data": result}


@router.post("/ingestion/folder-uploads")
async def upload_folder(
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """
    Uploads a folder hierarchy with preserved relative paths
    and executes ingestion into the canonical catalog.
    """
    files_data, relative_paths_str = await _extract_upload_files(request)
    if not files_data:
        raise HTTPException(status_code=400, detail="No files provided in upload.")

    parsed_paths: List[str] = []
    if relative_paths_str:
        try:
            parsed_paths = json.loads(relative_paths_str)
            if not isinstance(parsed_paths, list):
                parsed_paths = []
        except Exception:
            parsed_paths = []

    for idx, f in enumerate(files_data):
        if idx < len(parsed_paths) and parsed_paths[idx]:
            f["relative_path"] = parsed_paths[idx]

    result = deps.ingestion_manager.process_file_batch(
        tenant_id=tenant_id,
        files_data=files_data,
    )

    if result.get("status") == "FAILED":
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": result.get("error_message"), "data": result},
        )

    return {"success": True, "data": result}


@router.get("/ingestion/jobs/{job_id}")
def get_ingestion_job(
    job_id: str,
    tenant_id: str = Depends(get_tenant_id),
    deps: AppDependencies = Depends(get_dependencies),
):
    """Returns status and diagnostic output for an ingestion job."""
    status_rec = deps.ingestion_manager.get_job_status(job_id, tenant_id)
    if not status_rec:
        raise HTTPException(status_code=404, detail=f"Ingestion job {job_id} not found.")
    return {"success": True, "data": status_rec}


# =============================================================================
# APPLICATION FACTORY
# =============================================================================

def create_app(
    governance_service: Optional[GovernanceService] = None,
    ingestion_manager: Optional[IngestionManager] = None,
    cors_origins: Optional[List[str]] = None,
) -> FastAPI:
    """
    Creates and configures the FastAPI application instance with:
    - Typed routing
    - CORS middleware
    - OpenAPI documentation
    - Global exception handlers
    """
    global _deps_instance
    if governance_service is not None or ingestion_manager is not None:
        _deps_instance = AppDependencies(
            governance_service=governance_service,
            ingestion_manager=ingestion_manager,
        )

    app = FastAPI(
        title="KPI Intelligence API",
        description="Canonical model KPI mapping, domain segregation, and human governance API.",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS configuration
    origins = cors_origins or os.getenv("KPI_CORS_ORIGINS", "").split(",")
    origins = [o.strip() for o in origins if o.strip()] or DEFAULT_CORS_ORIGINS

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # Exception Handlers
    @app.exception_handler(TenantAccessDeniedError)
    def tenant_access_handler(request: Request, exc: TenantAccessDeniedError):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"success": False, "error": str(exc)},
        )

    @app.exception_handler(DocumentNotFoundError)
    def not_found_handler(request: Request, exc: DocumentNotFoundError):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"success": False, "error": str(exc)},
        )

    @app.exception_handler(ConcurrencyConflictError)
    def conflict_handler(request: Request, exc: ConcurrencyConflictError):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"success": False, "error": str(exc)},
        )

    @app.exception_handler(ValueError)
    def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": str(exc)},
        )

    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": str(exc)},
        )

    # Health & Readiness Endpoints
    @app.get("/health", response_model=HealthResponse, tags=["Diagnostics"])
    def health_check():
        return HealthResponse()

    @app.get("/ready", response_model=ReadyResponse, tags=["Diagnostics"])
    def ready_check():
        return ReadyResponse()

    # Mount API Router
    app.include_router(router)

    # Optional Production Static Asset Mount (serving built React app)
    dist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
    if os.path.exists(dist_dir):
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")

    return app


# Root FastAPI instance for ASGI servers (e.g. uvicorn backend.api.app:app)
app = create_app()


# =============================================================================
# BACKWARD COMPATIBILITY ADAPTER
# =============================================================================

class KPIIntelligenceAPI:
    """
    Adapter providing handle_request() for tests or scripts,
    routing requests through FastAPI's TestClient.
    """

    def __init__(
        self,
        governance_service: Optional[GovernanceService] = None,
        ingestion_manager: Optional[IngestionManager] = None,
    ):
        from fastapi.testclient import TestClient
        self.fastapi_app = create_app(governance_service=governance_service, ingestion_manager=ingestion_manager)
        self.client = TestClient(self.fastapi_app)

    def handle_request(
        self,
        method: str,
        path: str,
        query_params: Dict[str, List[str]],
        body: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ) -> Tuple[int, Dict[str, Any]]:
        # Normalize headers and query
        flat_query = {k: v[0] if isinstance(v, list) and len(v) > 0 else v for k, v in query_params.items()}
        method_upper = method.upper()

        if method_upper == "GET":
            resp = self.client.get(path, params=flat_query, headers=headers)
        elif method_upper == "POST":
            resp = self.client.post(path, params=flat_query, json=body, headers=headers)
        else:
            return 405, {"success": False, "error": f"Method {method} not allowed"}

        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        return resp.status_code, data
