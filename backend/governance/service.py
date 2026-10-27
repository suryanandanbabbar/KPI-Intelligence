"""
KPI Intelligence — Enterprise Governance & Mapping Workflow Service.

Orchestrates:
1. Canonical Metadata Extraction:
   Reads extracted analytical metadata EXCLUSIVELY from the canonical data model
   (SemanticModelDocument, ReportDocument, AnalyticalObjectDocument).
   NEVER reopens or reads raw original files.
2. Domain Segregation:
   Applies DomainClassificationService to assign primary and secondary domains.
3. Candidate Mapping & LLM/Deterministic Fallback:
   Orchestrates retrieval and ranking, populates KpiMappingRunDocument and KpiMappingDocument.
4. Human Approval Workflow:
   Manages explicit human approval, rejection, and manual override with mandatory justification.
5. Re-ingestion Decision Reuse:
   Integrates OverrideLearningService to reuse historical approved decisions across re-ingestions.
6. Real-time Workspace Metrics and Audit History.
"""

import os
import uuid
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from backend.contracts import (
    CosmosContainer,
    DocumentType,
    ReportDocument,
    SemanticModelDocument,
    AnalyticalObjectDocument,
    KpiCandidateDocument,
    KpiMappingDocument,
    KpiMappingRunDocument,
    MappingApprovalDocument,
    MappingOverrideDocument,
    MappingAuditEventDocument,
)
from backend.repository.interfaces import IRepository, QuerySpec
from backend.repository.context import TenantContext
from backend.kpi_bank.service import KPIBankService, get_kpi_bank_service
from backend.domain.service import DomainClassificationService, get_domain_service, DOMAIN_METADATA
from backend.matching.orchestrator import MatchingOrchestrator, get_matching_orchestrator
from backend.learning.service import OverrideLearningService, get_override_learning_service

logger = logging.getLogger("kpi_intel.governance.service")


class GovernanceService:
    """End-to-end service coordinating analytical metadata mapping and human governance."""

    def __init__(
        self,
        repository: IRepository,
        kpi_bank_service: Optional[KPIBankService] = None,
        domain_service: Optional[DomainClassificationService] = None,
        matching_orchestrator: Optional[MatchingOrchestrator] = None,
        learning_service: Optional[OverrideLearningService] = None,
    ):
        self.repo = repository
        self.kpi_bank = kpi_bank_service or get_kpi_bank_service(repository)
        self.domain_service = domain_service or get_domain_service(repository)
        self.matcher = matching_orchestrator or get_matching_orchestrator(self.kpi_bank)
        self.matching = self.matcher
        self.learning_service = learning_service or get_override_learning_service(repository)

    # =========================================================================
    # 1. CANONICAL METADATA EXTRACTION (EXCLUSIVELY FROM CANONICAL MODEL)
    # =========================================================================

    def extract_canonical_metadata_fields(self, tenant_id: str) -> List[Dict[str, Any]]:
        """
        Reads analytical metadata exclusively from the canonical data model (catalog container).
        Extracts calculations/measures, data columns, and visual objects without opening source files.
        """
        ctx = TenantContext(tenant_id=tenant_id)
        fields: List[Dict[str, Any]] = []

        # 1. Read Semantic Models from Catalog
        query_models = "SELECT * FROM c WHERE c.tenant_id = @tenant_id AND c.doc_type = @doc_type"
        spec_models = QuerySpec(
            query=query_models,
            parameters=[
                {"name": "@tenant_id", "value": tenant_id},
                {"name": "@doc_type", "value": DocumentType.SEMANTIC_MODEL.value},
            ],
        )
        res_models = self.repo.query_items(CosmosContainer.METADATA_CATALOG, tenant_id, spec_models, ctx)
        models = res_models.items if res_models else []

        for m in models:
            m_id = m.get("semantic_model_id") or m.get("id")
            m_name = m.get("model_name", "Model")
            asset_id = m.get("asset_id", "")

            # Measures / Calculations
            for calc in m.get("calculations", []):
                c_name = calc.get("calculation_name") or calc.get("name") or "Measure"
                c_expr = calc.get("expression") or calc.get("expression_text") or ""
                c_desc = calc.get("description")
                c_id = f"calc_{calc.get('calculation_id') or c_name}"

                classif = self.domain_service.classify_metadata_field(
                    field_name=c_name,
                    expression=c_expr,
                    description=c_desc,
                    parent_name=m_name,
                )

                fields.append({
                    "field_id": c_id,
                    "name": c_name,
                    "candidate_name": c_name,
                    "entity_type": "MEASURE",
                    "expression": c_expr,
                    "candidate_expression": c_expr,
                    "description": c_desc,
                    "data_type": "DECIMAL",
                    "parent_type": "SEMANTIC_MODEL",
                    "parent_name": m_name,
                    "parent_id": m_id,
                    "asset_id": asset_id,
                    "domain": classif["primary_domain"],
                    "business_domain": classif["primary_domain"],
                    "secondary_domains": classif["secondary_domains"],
                    "domain_confidence": classif["confidence_code"],
                    "domain_evidence": classif["supporting_evidence"],
                    "source_model": m_name,
                })

            # Data Columns
            for tbl in m.get("tables", []):
                t_name = tbl.get("table_name", "Table")
                for col in tbl.get("columns", []):
                    col_name = col if isinstance(col, str) else col.get("column_name", "Col")
                    col_id = f"col_{t_name}_{col_name}"
                    col_dtype = col.get("data_type", "VARCHAR") if isinstance(col, dict) else "VARCHAR"

                    classif = self.domain_service.classify_metadata_field(
                        field_name=col_name,
                        expression=None,
                        description=None,
                        parent_name=t_name,
                    )

                    fields.append({
                        "field_id": col_id,
                        "name": col_name,
                        "candidate_name": col_name,
                        "entity_type": "COLUMN",
                        "expression": None,
                        "candidate_expression": None,
                        "description": f"Column {col_name} on table {t_name}",
                        "data_type": col_dtype,
                        "parent_type": "TABLE",
                        "parent_name": t_name,
                        "parent_id": m_id,
                        "asset_id": asset_id,
                        "domain": classif["primary_domain"],
                        "business_domain": classif["primary_domain"],
                        "secondary_domains": classif["secondary_domains"],
                        "domain_confidence": classif["confidence_code"],
                        "domain_evidence": classif["supporting_evidence"],
                        "source_model": m_name,
                    })

        # 2. Read Reports from Catalog for Visuals
        query_reps = "SELECT * FROM c WHERE c.tenant_id = @tenant_id AND c.doc_type = @doc_type"
        spec_reps = QuerySpec(
            query=query_reps,
            parameters=[
                {"name": "@tenant_id", "value": tenant_id},
                {"name": "@doc_type", "value": DocumentType.REPORT.value},
            ],
        )
        res_reps = self.repo.query_items(CosmosContainer.METADATA_CATALOG, tenant_id, spec_reps, ctx)
        reports = res_reps.items if res_reps else []

        for r in reports:
            r_id = r.get("report_id") or r.get("id")
            r_name = r.get("report_name", "Report")
            asset_id = r.get("asset_id", "")

            for vis in r.get("visuals", []):
                v_title = vis.get("visual_title") or vis.get("title") or vis.get("visual_type")
                if not v_title:
                    continue
                v_id = f"vis_{vis.get('visual_id') or uuid.uuid4()}"
                v_type = vis.get("visual_type", "visual")

                classif = self.domain_service.classify_metadata_field(
                    field_name=v_title,
                    expression=None,
                    description=f"Visual {v_type} in {r_name}",
                    parent_name=r_name,
                )

                fields.append({
                    "field_id": v_id,
                    "name": v_title,
                    "candidate_name": v_title,
                    "entity_type": "VISUAL",
                    "expression": None,
                    "candidate_expression": None,
                    "description": f"Visual {v_type} in report {r_name}",
                    "data_type": "VISUAL",
                    "parent_type": "REPORT",
                    "parent_name": r_name,
                    "parent_id": r_id,
                    "asset_id": asset_id,
                    "domain": classif["primary_domain"],
                    "business_domain": classif["primary_domain"],
                    "secondary_domains": classif["secondary_domains"],
                    "domain_confidence": classif["confidence_code"],
                    "domain_evidence": classif["supporting_evidence"],
                    "source_model": r_name,
                })

        return fields

    # =========================================================================
    # 2. RUN MAPPING PIPELINE
    # =========================================================================

    def run_mapping_pipeline(
        self,
        tenant_id: str,
        user_id: str = "analyst",
        force_fallback: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes end-to-end mapping on all canonical metadata fields:
        1. Checks for reusable historical overrides (Learning layer).
        2. Generates candidate rankings via LLM / deterministic fallback.
        3. Persists KpiCandidateDocument, KpiMappingDocument, and KpiMappingRunDocument.
        """
        import time as _pytime
        t0 = _pytime.time()
        logger.info(
            "Stage 1/9 [REQUEST_RECEIVED]: Mapping pipeline initiated: tenant=%s, user=%s, force_fallback=%s",
            tenant_id,
            user_id,
            force_fallback,
        )

        ctx = TenantContext(tenant_id=tenant_id)

        # Stage 2: Canonical Metadata Extraction
        t_start_canonical = _pytime.time()
        fields = self.extract_canonical_metadata_fields(tenant_id)
        t_canonical_loaded = _pytime.time()
        canonical_duration_ms = round((t_canonical_loaded - t_start_canonical) * 1000, 2)
        total_fields = len(fields)
        logger.info(
            "Stage 2/9 [CANONICAL_LOADED]: %d canonical metadata fields loaded in %.2fms for tenant %s",
            total_fields,
            canonical_duration_ms,
            tenant_id,
        )

        # Stage 3: Domain Segregation & Boundary Verification
        t_start_domain = _pytime.time()
        domain_distribution: Dict[str, int] = {}
        for f in fields:
            dom = f.get("domain", "GENERAL")
            domain_distribution[dom] = domain_distribution.get(dom, 0) + 1
        t_domain_segregated = _pytime.time()
        domain_duration_ms = round((t_domain_segregated - t_start_domain) * 1000, 2)
        logger.info(
            "Stage 3/9 [DOMAIN_SEGREGATION]: %d domains segregated across %d fields in %.2fms: %s",
            len(domain_distribution),
            total_fields,
            domain_duration_ms,
            domain_distribution,
        )

        run_id = f"run_{uuid.uuid4()}"
        started_at = datetime.now(timezone.utc).isoformat()
        auto_reused_count = 0
        llm_processed_count = 0
        fallback_processed_count = 0
        llm_requests_attempted = 0
        llm_successful_evaluations = 0
        llm_failed_or_timed_out = 0
        llm_cached_evaluations = 0
        llm_latencies_ms: List[float] = []
        mappings_produced: List[Dict[str, Any]] = []

        # Circuit breaker, in-run cache, and total execution budget controls
        in_run_cache: Dict[Any, Any] = {}
        llm_circuit_open = False
        llm_circuit_reason: Optional[str] = None
        budget_exhausted = False
        pipeline_budget_seconds = float(os.getenv("KPI_PIPELINE_TOTAL_BUDGET_SECONDS", "90.0"))
        budget_buffer_seconds = min(15.0, pipeline_budget_seconds * 0.2)
        budget_threshold_seconds = max(0.001, pipeline_budget_seconds - budget_buffer_seconds)
        total_ranking_time_ms = 0.0

        for idx, field in enumerate(fields):
            field_id = field["field_id"]
            field_domain = field["domain"]
            elapsed_so_far = _pytime.time() - t0

            # Guard against exceeding total execution budget
            # If elapsed time reaches threshold, fast-fail remaining fields to deterministic fallback
            if elapsed_so_far >= budget_threshold_seconds and not llm_circuit_open and not force_fallback:
                llm_circuit_open = True
                budget_exhausted = True
                llm_circuit_reason = (
                    f"PIPELINE_BUDGET_REACHED: Elapsed time ({elapsed_so_far:.1f}s) reached threshold of "
                    f"{pipeline_budget_seconds:.1f}s budget. Fast-falling back remaining fields."
                )
                logger.warning(llm_circuit_reason)

            # Determine whether to execute deterministic fallback for this field
            field_force_fallback = force_fallback or llm_circuit_open

            # 1. Check Learning Service for reusable override
            override_match = self.learning_service.find_reusable_override(tenant_id, field, self.kpi_bank)

            if override_match["has_match"] and not override_match["has_conflict"]:
                auto_reused_count += 1
                selected_kpi = override_match["target_kpi"]
                ovr = override_match["override"]
                mapping_id = f"map_{field_id}"

                mapping_doc = KpiMappingDocument(
                    id=mapping_id,
                    kpi_mapping_id=mapping_id,
                    tenant_id=tenant_id,
                    kpi_candidate_id=f"cand_{field_id}",
                    mapping_run_id=run_id,
                    selected_ontology_entry_id=selected_kpi["kpi_id"],
                    mapping_status="APPROVED",
                    decision_source="HUMAN_OVERRIDE_REUSED",
                    confidence_band="HIGH",
                    confidence_score=1.0,
                    match_score=1.0,
                    top_candidates=[{
                        "kpi_id": selected_kpi["kpi_id"],
                        "kpi_name": selected_kpi["name"],
                        "confidence_code": "HIGH",
                        "confidence_score": 1.0,
                        "ranking_rationale": override_match["evidence"],
                        "is_recommended": True,
                    }],
                )
                self.repo.upsert_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, mapping_doc.to_dict(), ctx)
                mappings_produced.append(mapping_doc.to_dict())
                continue

            # 2. Invoke Matching Orchestrator (Stages 4-7)
            import copy
            from backend.matching.orchestrator import compute_input_fingerprint
            field_fp = compute_input_fingerprint(field, field_domain)

            if not field_force_fallback and field_fp in in_run_cache:
                match_res = copy.deepcopy(in_run_cache[field_fp])
                match_res["cached"] = True
            else:
                t_field_rank_start = _pytime.time()
                match_res = self.matcher.discover_and_rank_candidates(
                    metadata_field=field,
                    domain=field_domain,
                    force_fallback=field_force_fallback,
                )
                t_field_rank_end = _pytime.time()
                total_ranking_time_ms += (t_field_rank_end - t_field_rank_start) * 1000

                # Cache successful LLM outcome for deduplication across identical signatures
                if not match_res.get("fallback_used") and match_res.get("candidate_count", 0) > 0:
                    in_run_cache[field_fp] = match_res

            # Telemetry tracking for LLM attempts, successes, and cache hits
            if match_res.get("cached"):
                llm_cached_evaluations += 1
            elif match_res.get("llm_attempted"):
                llm_requests_attempted += 1
                if match_res.get("llm_success"):
                    llm_successful_evaluations += 1
                    lat = match_res.get("llm_latency_ms", 0.0)
                    if lat > 0:
                        llm_latencies_ms.append(lat)
                else:
                    llm_failed_or_timed_out += 1

            # If an unforced LLM failure or timeout occurred, trip circuit breaker for remaining fields
            if match_res["fallback_used"] and not force_fallback and not llm_circuit_open:
                fallback_reason_str = match_res.get("fallback_reason") or ""
                # Trip circuit on persistent infrastructural/timeout issues
                is_circuit_trigger = any(
                    trigger in fallback_reason_str
                    for trigger in ("TIMEOUT", "HTTP_ERROR", "CLIENT_INITIALIZATION_FAILED", "MISSING_CONFIGURATION", "503", "429")
                )
                if is_circuit_trigger:
                    llm_circuit_open = True
                    llm_circuit_reason = (
                        f"CIRCUIT_BREAKER_TRIPPED: Field '{field['name']}' encountered {fallback_reason_str}. "
                        "Fast-failover to deterministic matching enabled for subsequent fields in this run."
                    )
                    logger.warning(llm_circuit_reason)

            if match_res["fallback_used"]:
                fallback_processed_count += 1
            else:
                llm_processed_count += 1

            top_recs = match_res.get("top_candidates", [])
            primary_rec = top_recs[0] if top_recs else {}
            mapping_id = f"map_{field_id}"

            cand_doc = KpiCandidateDocument(
                id=f"cand_{field_id}",
                kpi_candidate_id=f"cand_{field_id}",
                tenant_id=tenant_id,
                candidate_name=field["name"],
                candidate_expression=field.get("expression"),
                candidate_type=field.get("entity_type", "MEASURE"),
                business_domain_id=field_domain,
            )
            self.repo.upsert_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, cand_doc.to_dict(), ctx)

            mapping_doc = KpiMappingDocument(
                id=mapping_id,
                kpi_mapping_id=mapping_id,
                tenant_id=tenant_id,
                kpi_candidate_id=cand_doc.id,
                mapping_run_id=run_id,
                selected_ontology_entry_id=primary_rec.get("kpi_id") if primary_rec else None,
                mapping_status="PROPOSED",
                decision_source=primary_rec.get("decision_source", "DETERMINISTIC_FALLBACK" if match_res["fallback_used"] else ("LLM_INFERENCE_CACHED" if match_res.get("cached") else "LLM_INFERENCE")),
                mapping_engine_version=match_res["matching_engine"],
                input_fingerprint=match_res["input_fingerprint"],
                confidence_band=primary_rec.get("confidence_code", "UNCLASSIFIED"),
                confidence_score=primary_rec.get("confidence_score", 0.0),
                match_score=primary_rec.get("match_score", 0.0),
                top_candidate_count=len(top_recs),
                top_candidates=top_recs,
            )
            self.repo.upsert_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, mapping_doc.to_dict(), ctx)
            mappings_produced.append(mapping_doc.to_dict())

        # Stage 8: Persistence
        t_start_persist = _pytime.time()
        completed_at = datetime.now(timezone.utc).isoformat()
        duration = round(_pytime.time() - t0, 2)

        run_doc = KpiMappingRunDocument(
            id=run_id,
            mapping_run_id=run_id,
            tenant_id=tenant_id,
            primary_engine="LLM_INFERENCE" if llm_processed_count > 0 else "DETERMINISTIC_FALLBACK",
            fallback_used=(fallback_processed_count > 0 or force_fallback),
            mapping_engine_version="2.2.0",
            run_status="COMPLETED",
            started_at=started_at,
            completed_at=completed_at,
        )
        self.repo.upsert_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, run_doc.to_dict(), ctx)
        t_persist_end = _pytime.time()
        persist_duration_ms = round((t_persist_end - t_start_persist) * 1000, 2)

        logger.info(
            "Stage 8/9 [PERSISTENCE]: %d mapping documents and run record '%s' persisted in %.2fms",
            len(mappings_produced),
            run_id,
            persist_duration_ms,
        )

        # Stage 9: Duration & Structured Measurement Metrics
        llm_avg_latency_ms = round(sum(llm_latencies_ms) / len(llm_latencies_ms), 2) if llm_latencies_ms else 0.0
        sorted_latencies = sorted(llm_latencies_ms)
        llm_p95_latency_ms = round(sorted_latencies[int(len(sorted_latencies) * 0.95)], 2) if sorted_latencies else 0.0
        
        # Retry wait duration from client if available
        llm_retry_wait_ms = 0.0
        if hasattr(self.matcher, "llm_engine") and hasattr(self.matcher.llm_engine, "client") and self.matcher.llm_engine.client:
            llm_retry_wait_ms = round(getattr(self.matcher.llm_engine.client, "total_retry_wait_seconds", 0.0) * 1000, 2)
            
        non_llm_duration_ms = round(max(0.0, (duration * 1000) - sum(llm_latencies_ms)), 2)

        if llm_processed_count == total_fields and total_fields > 0:
            coverage_type = "FULL_LLM"
        elif llm_processed_count > 0:
            coverage_type = "PARTIAL_LLM"
        else:
            coverage_type = "DETERMINISTIC_ONLY"

        if budget_exhausted:
            explanation = (
                f"Pipeline total execution budget of {pipeline_budget_seconds:.1f}s reached at threshold. "
                f"{llm_processed_count} fields evaluated via LLM ({llm_successful_evaluations} direct calls, {llm_cached_evaluations} fingerprint cache hits). "
                f"Remaining {fallback_processed_count} fields safely processed via deterministic fallback."
            )
        elif llm_circuit_open:
            explanation = (
                f"LLM circuit breaker tripped ({llm_circuit_reason}). "
                f"{llm_processed_count} fields evaluated via LLM. Remaining fields evaluated via deterministic fallback."
            )
        elif force_fallback:
            explanation = "Manual force fallback was requested. All fields evaluated via deterministic matching."
        else:
            explanation = f"Mapping complete: {llm_processed_count} evaluated via LLM, {fallback_processed_count} via fallback, {auto_reused_count} reused from learning."

        logger.info(
            "Stage 9/9 [PIPELINE_COMPLETED]: Tenant %s completed in %.2fs: %d fields (LLM: %d [direct=%d, cached=%d], Fallback: %d, Reused: %d, Coverage: %s, BudgetExhausted: %s)",
            tenant_id,
            duration,
            total_fields,
            llm_processed_count,
            llm_successful_evaluations,
            llm_cached_evaluations,
            fallback_processed_count,
            auto_reused_count,
            coverage_type,
            budget_exhausted,
        )

        return {
            "mapping_run_id": run_id,
            "total_fields": total_fields,
            "total_fields_processed": total_fields,
            "fields_considered": total_fields,
            "auto_reused_overrides": auto_reused_count,
            "auto_reused_from_learning": auto_reused_count,
            "llm_processed_count": llm_processed_count,
            "fallback_processed_count": fallback_processed_count,
            "llm_requests_attempted": llm_requests_attempted,
            "llm_successful_evaluations": llm_successful_evaluations,
            "llm_failed_or_timed_out": llm_failed_or_timed_out,
            "llm_cached_evaluations": llm_cached_evaluations,
            "coverage_type": coverage_type,
            "budget_exhausted": budget_exhausted,
            "budget_limit_seconds": pipeline_budget_seconds,
            "explanation": explanation,
            "status": "COMPLETED",
            "fallback_used": (fallback_processed_count > 0 or force_fallback),
            "fallback_reason": llm_circuit_reason if llm_circuit_open else None,
            "circuit_tripped": llm_circuit_open,
            "circuit_reason": llm_circuit_reason,
            "primary_engine": "LLM_INFERENCE" if llm_processed_count > 0 else "DETERMINISTIC_FALLBACK",
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_seconds": duration,
            "stage_timings": {
                "canonical_loaded_ms": canonical_duration_ms,
                "domain_segregation_ms": domain_duration_ms,
                "candidate_ranking_ms": round(total_ranking_time_ms, 2),
                "persistence_ms": persist_duration_ms,
                "overall_duration_seconds": duration,
                "llm_avg_latency_ms": llm_avg_latency_ms,
                "llm_p95_latency_ms": llm_p95_latency_ms,
                "llm_retry_wait_ms": llm_retry_wait_ms,
                "non_llm_duration_ms": non_llm_duration_ms,
            },
        }

    # =========================================================================
    # 3. HUMAN GOVERNANCE ACTIONS (APPROVAL, REJECTION, OVERRIDE)
    # =========================================================================

    def approve_candidate(
        self,
        tenant_id: str,
        mapping_id: str,
        approved_kpi_id: str,
        user_id: str = "analyst",
    ) -> Dict[str, Any]:
        """
        Executes human approval of a proposed candidate.
        Persists MappingApprovalDocument and updates KpiMappingDocument to APPROVED.
        HIGH confidence NEVER auto-approves: human action is strictly required.
        """
        ctx = TenantContext(tenant_id=tenant_id)
        mapping_data = self.repo.get_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, mapping_id, ctx)
        if not mapping_data:
            raise ValueError(f"Mapping '{mapping_id}' not found.")

        target_kpi = self.kpi_bank.get_by_id(approved_kpi_id)
        if not target_kpi:
            raise ValueError(f"KPI '{approved_kpi_id}' does not exist in KPI Bank.")

        approval_id = f"app_{uuid.uuid4()}"
        approval_doc = MappingApprovalDocument(
            id=approval_id,
            mapping_approval_id=approval_id,
            tenant_id=tenant_id,
            kpi_mapping_id=mapping_id,
            approved_ontology_entry_id=approved_kpi_id,
            approved_by_user_id=user_id,
            approval_status="ACTIVE",
            approved_at=datetime.now(timezone.utc).isoformat(),
        )

        mapping_data["mapping_status"] = "APPROVED"
        mapping_data["selected_ontology_entry_id"] = approved_kpi_id
        mapping_data["active_approval"] = approval_doc.to_dict()

        audit_doc = MappingAuditEventDocument(
            id=f"audit_app_{uuid.uuid4()}",
            tenant_id=tenant_id,
            kpi_mapping_id=mapping_id,
            target_kpi_mapping_id=approved_kpi_id,
            actor_user_id=user_id,
            event_type="MAPPING_APPROVED",
            previous_state={"status": "PROPOSED"},
            new_state={"status": "APPROVED", "kpi_id": approved_kpi_id},
            event_reason=f"Approved mapping to KPI '{target_kpi['name']}'",
        )

        self.repo.upsert_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, approval_doc.to_dict(), ctx)
        self.repo.upsert_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, mapping_data, ctx)
        self.repo.upsert_item(CosmosContainer.OPERATIONAL_AUDIT, tenant_id, audit_doc.to_dict(), ctx)

        return {
            "mapping_id": mapping_id,
            "approved_kpi_id": approved_kpi_id,
            "status": "APPROVED",
            "approved_by": user_id,
            "timestamp": approval_doc.approved_at,
        }

    def reject_candidate(
        self,
        tenant_id: str,
        mapping_id: str,
        user_id: str = "analyst",
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Rejects a proposed candidate.
        Leaves the field unmapped/unresolved without assigning an alternative.
        """
        ctx = TenantContext(tenant_id=tenant_id)
        mapping_data = self.repo.get_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, mapping_id, ctx)
        if not mapping_data:
            raise ValueError(f"Mapping '{mapping_id}' not found.")

        old_status = mapping_data.get("mapping_status", "PROPOSED")
        mapping_data["mapping_status"] = "REJECTED"
        mapping_data["selected_ontology_entry_id"] = None

        audit_doc = MappingAuditEventDocument(
            id=f"audit_rej_{uuid.uuid4()}",
            tenant_id=tenant_id,
            kpi_mapping_id=mapping_id,
            actor_user_id=user_id,
            event_type="MAPPING_REJECTED",
            previous_state={"status": old_status},
            new_state={"status": "REJECTED"},
            event_reason=reason or f"User {user_id} rejected candidate mapping",
        )

        self.repo.upsert_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, mapping_data, ctx)
        self.repo.upsert_item(CosmosContainer.OPERATIONAL_AUDIT, tenant_id, audit_doc.to_dict(), ctx)

        return {
            "mapping_id": mapping_id,
            "status": "REJECTED",
            "rejected_by": user_id,
            "reason": reason,
        }

    def override_mapping(
        self,
        tenant_id: str,
        mapping_id: str,
        replacement_kpi_id: str,
        override_justification: str,
        user_id: str = "analyst",
    ) -> Dict[str, Any]:
        """
        Substitutes candidate with an alternative KPI from the KPI Bank.
        Strictly requires non-empty override justification (>= 10 chars).
        Persists decision for permanent re-ingestion reuse via OverrideLearningService.
        """
        ctx = TenantContext(tenant_id=tenant_id)
        mapping_data = self.repo.get_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, mapping_id, ctx)
        if not mapping_data:
            raise ValueError(f"Mapping '{mapping_id}' not found.")

        target_kpi = self.kpi_bank.get_by_id(replacement_kpi_id)
        if not target_kpi:
            raise ValueError(f"Replacement KPI '{replacement_kpi_id}' not found in KPI Bank.")

        # Reconstruct metadata field snapshot
        field_id = mapping_id.replace("map_", "")
        cand_id = mapping_data.get("kpi_candidate_id")
        cand_data = self.repo.get_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, cand_id, ctx) if cand_id else {}
        field_snapshot = {
            "field_id": field_id,
            "name": cand_data.get("candidate_name", field_id) if cand_data else field_id,
            "expression": cand_data.get("candidate_expression") if cand_data else None,
            "domain": cand_data.get("business_domain_id") if cand_data else "GENERAL",
            "entity_type": cand_data.get("candidate_type", "MEASURE") if cand_data else "MEASURE",
        }

        # 1. Record override and compute learning fingerprints
        prev_kpi = mapping_data.get("selected_ontology_entry_id")
        ovr_record = self.learning_service.record_override(
            tenant_id=tenant_id,
            kpi_mapping_id=mapping_id,
            replacement_kpi_id=replacement_kpi_id,
            override_justification=override_justification,
            user_id=user_id,
            metadata_field=field_snapshot,
            original_candidates=mapping_data.get("top_candidates", []),
            previous_kpi_id=prev_kpi,
        )

        # 2. Update mapping status to OVERRIDDEN
        mapping_data["mapping_status"] = "OVERRIDDEN"
        mapping_data["selected_ontology_entry_id"] = replacement_kpi_id
        mapping_data["override_justification"] = override_justification
        mapping_data["decision_source"] = "HUMAN_OVERRIDE"
        self.repo.upsert_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, mapping_data, ctx)

        return {
            "mapping_id": mapping_id,
            "replacement_kpi_id": replacement_kpi_id,
            "kpi_name": target_kpi.get("name"),
            "status": "OVERRIDDEN",
            "override_justification": override_justification,
            "override_id": ovr_record["override_id"],
            "user_id": user_id,
        }

    def create_kpi_and_map(
        self,
        tenant_id: str,
        mapping_id: str,
        kpi_data: Dict[str, Any],
        user_id: str = "analyst",
    ) -> Dict[str, Any]:
        """
        Creates a new KPI in the KPI Bank, then maps the current metadata field to it.
        Creation and mapping are separate governed actions.
        """
        # 1. Create KPI in KPI Bank
        new_kpi = self.kpi_bank.create_kpi(kpi_data)
        new_kpi_id = new_kpi["kpi_id"]

        # 2. Map field to newly created KPI with justification
        justification = kpi_data.get("creation_justification") or f"Created new standard KPI '{new_kpi['name']}'"
        override_res = self.override_mapping(
            tenant_id=tenant_id,
            mapping_id=mapping_id,
            replacement_kpi_id=new_kpi_id,
            override_justification=justification,
            user_id=user_id,
        )

        return {
            "new_kpi": new_kpi,
            "mapping": override_res,
        }

    # =========================================================================
    # 4. WORKSPACE METRICS AND QUERIES
    # =========================================================================

    def get_workspace_summary(self, tenant_id: str) -> Dict[str, Any]:
        """Returns live summary metrics across all analytical metadata and mapping workflow."""
        ctx = TenantContext(tenant_id=tenant_id)
        fields = self.extract_canonical_metadata_fields(tenant_id)

        # Query existing mappings
        query_maps = "SELECT * FROM c WHERE c.tenant_id = @tenant_id AND c.doc_type = @doc_type"
        spec_maps = QuerySpec(
            query=query_maps,
            parameters=[
                {"name": "@tenant_id", "value": tenant_id},
                {"name": "@doc_type", "value": DocumentType.KPI_MAPPING.value},
            ],
        )
        res_maps = self.repo.query_items(CosmosContainer.KPI_GOVERNANCE, tenant_id, spec_maps, ctx)
        mappings = res_maps.items if res_maps else []
        mapping_by_id = {m.get("kpi_mapping_id") or m.get("id"): m for m in mappings}

        status_counts = {"PROPOSED": 0, "APPROVED": 0, "REJECTED": 0, "OVERRIDDEN": 0, "UNMAPPED": 0}
        domain_counts: Dict[str, int] = {d: 0 for d in DOMAIN_METADATA.keys()}
        domain_counts["UNCLASSIFIED"] = 0

        engine_counts = {"LLM_INFERENCE": 0, "DETERMINISTIC_FALLBACK": 0, "HUMAN_OVERRIDE_REUSED": 0}

        for f in fields:
            f_dom = f.get("domain", "UNCLASSIFIED")
            domain_counts[f_dom] = domain_counts.get(f_dom, 0) + 1

            m_id = f"map_{f['field_id']}"
            if m_id in mapping_by_id:
                m = mapping_by_id[m_id]
                stat = m.get("mapping_status", "PROPOSED")
                status_counts[stat] = status_counts.get(stat, 0) + 1
                source = m.get("decision_source", "DETERMINISTIC_FALLBACK")
                engine_counts[source] = engine_counts.get(source, 0) + 1
            else:
                status_counts["UNMAPPED"] += 1

        active_overrides = self.learning_service.list_active_overrides(tenant_id)
        llm_status = self.matcher.get_status() if hasattr(self.matcher, "get_status") else {}

        return {
            "total_canonical_entities": len(fields),
            "status_counts": status_counts,
            "domain_distribution": domain_counts,
            "engine_counts": engine_counts,
            "awaiting_review": status_counts.get("PROPOSED", 0),
            "approved_mappings": status_counts.get("APPROVED", 0) + status_counts.get("OVERRIDDEN", 0),
            "unmapped_fields": status_counts.get("UNMAPPED", 0),
            "rejected_suggestions": status_counts.get("REJECTED", 0),
            "total_active_overrides": len(active_overrides),
            "operating_status": "ONLINE (LLM preferred, deterministic fallback active)",
            "llm_status": llm_status,
        }

    def list_fields_with_mappings(
        self,
        tenant_id: str,
        domain: Optional[str] = None,
        status: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Returns metadata fields joined with their current mapping decisions and top candidates."""
        ctx = TenantContext(tenant_id=tenant_id)
        fields = self.extract_canonical_metadata_fields(tenant_id)

        query_maps = "SELECT * FROM c WHERE c.tenant_id = @tenant_id AND c.doc_type = @doc_type"
        spec_maps = QuerySpec(
            query=query_maps,
            parameters=[
                {"name": "@tenant_id", "value": tenant_id},
                {"name": "@doc_type", "value": DocumentType.KPI_MAPPING.value},
            ],
        )
        res_maps = self.repo.query_items(CosmosContainer.KPI_GOVERNANCE, tenant_id, spec_maps, ctx)
        mappings = res_maps.items if res_maps else []
        mapping_by_id = {m.get("kpi_mapping_id") or m.get("id"): m for m in mappings}

        results = []
        for f in fields:
            if domain and f.get("domain", "").upper() != domain.upper():
                continue
            if entity_type and f.get("entity_type", "").upper() != entity_type.upper():
                continue

            m_id = f"map_{f['field_id']}"
            m = mapping_by_id.get(m_id, {})
            m_stat = m.get("mapping_status", "UNMAPPED")

            if status and m_stat.upper() != status.upper():
                continue

            top_candidates = m.get("top_candidates", [])
            lead = top_candidates[0] if top_candidates else {}

            item = dict(f)
            item["mapping_id"] = m_id
            item["mapping_status"] = m_stat
            item["decision_source"] = m.get("decision_source", "NONE")
            item["confidence_band"] = m.get("confidence_band", "UNCLASSIFIED")
            item["confidence_score"] = m.get("confidence_score", 0.0)
            item["selected_kpi_id"] = m.get("selected_ontology_entry_id")
            item["top_candidate_name"] = lead.get("kpi_name")
            item["top_candidate_id"] = lead.get("kpi_id")
            item["top_candidates"] = top_candidates
            results.append(item)

        return results

    def get_field_candidates(self, tenant_id: str, field_id: str) -> Dict[str, Any]:
        """Returns candidate recommendations and structured evidence for a single field."""
        ctx = TenantContext(tenant_id=tenant_id)
        mapping_id = f"map_{field_id}"
        m_data = self.repo.get_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, mapping_id, ctx)
        fields = self.extract_canonical_metadata_fields(tenant_id)
        target = next((f for f in fields if f["field_id"] == field_id), None)

        if not m_data:
            # Generate on demand if not yet mapped
            if not target:
                raise ValueError(f"Field '{field_id}' not found in canonical metadata.")

            res = self.matcher.discover_and_rank_candidates(target, domain=target.get("domain"))
            return {
                "field_id": field_id,
                "mapping_id": mapping_id,
                "field": target,
                "mapping_status": "PROPOSED",
                "top_candidates": res.get("top_candidates", []),
                "matching_engine": res.get("matching_engine"),
                "fallback_used": res.get("fallback_used"),
            }

        return {
            "field_id": field_id,
            "mapping_id": mapping_id,
            "field": target or {"field_id": field_id, "name": field_id, "domain": "GENERAL"},
            "mapping_status": m_data.get("mapping_status"),
            "selected_kpi_id": m_data.get("selected_ontology_entry_id"),
            "top_candidates": m_data.get("top_candidates", []),
            "matching_engine": m_data.get("mapping_engine_version"),
            "decision_source": m_data.get("decision_source"),
        }

    def list_audit_history(self, tenant_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns immutable compliance audit trail from operational_audit container."""
        ctx = TenantContext(tenant_id=tenant_id)
        query = "SELECT * FROM c WHERE c.tenant_id = @tenant_id AND c.doc_type = @doc_type ORDER BY c.created_at DESC"
        spec = QuerySpec(
            query=query,
            parameters=[
                {"name": "@tenant_id", "value": tenant_id},
                {"name": "@doc_type", "value": DocumentType.AUDIT_EVENT.value},
            ],
        )
        res = self.repo.query_items(CosmosContainer.OPERATIONAL_AUDIT, tenant_id, spec, ctx, page_size=limit)
        return res.items if res else []


# Singleton helper
_governance_service_instance: Optional[GovernanceService] = None


def get_governance_service(repository: Optional[IRepository] = None) -> GovernanceService:
    global _governance_service_instance
    if _governance_service_instance is None or (repository is not None and _governance_service_instance.repo != repository):
        from backend.storage.factory import get_repository
        repo = repository or get_repository()
        _governance_service_instance = GovernanceService(repository=repo)
    return _governance_service_instance
