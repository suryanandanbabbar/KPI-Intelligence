"""
KPI Intelligence — Matching Orchestrator.

Orchestrates the two-stage candidate retrieval and ranking pipeline:
Stage A — Candidate Retrieval:
  Reduces the full reference KPI Bank to a plausible candidate set using exact & normalized name,
  aliases, tokens, domain compatibility, formula overlap, and approved mapping history.

Stage B — Semantic Ranking:
  Executes Azure AI Foundry Llama semantic ranking when configured.
  Applies deterministic fallback if the LLM provider is unavailable, times out, returns malformed
  output, hallucinates non-existent KPI IDs, or fails validation.

Guarantees:
- Never silently switches algorithms: records matching_engine, fallback_used, and category-coded fallback_reason.
- Up to 3 deduplicated candidates per metadata field for each domain.
- Generates deterministic input fingerprints for auditability.
"""

import hashlib
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from backend.kpi_bank.service import KPIBankService, get_kpi_bank_service
from backend.matching.deterministic import DeterministicMatchingEngine
from backend.matching.llm import LLMMatchingEngine, LLMMatchingError

logger = logging.getLogger("kpi_intel.matching.orchestrator")


def compute_input_fingerprint(field: Dict[str, Any], domain: Optional[str]) -> str:
    """Computes SHA-256 fingerprint of the input metadata field."""
    raw = f"{field.get('name')}|{field.get('expression')}|{field.get('description')}|{domain or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class MatchingOrchestrator:
    """Coordinates retrieval, LLM ranking, deterministic fallback, and structured explanations."""

    def __init__(
        self,
        kpi_bank_service: Optional[KPIBankService] = None,
        llm_engine: Optional[LLMMatchingEngine] = None,
        deterministic_engine: Optional[DeterministicMatchingEngine] = None,
    ):
        self.kpi_bank = kpi_bank_service or get_kpi_bank_service()
        self.llm_engine = llm_engine or LLMMatchingEngine()
        self.deterministic_engine = deterministic_engine or DeterministicMatchingEngine()

    def get_status(self) -> Dict[str, Any]:
        """Returns non-sensitive operational status of the matching pipeline."""
        safe_info = self.llm_engine.config.to_safe_dict() if hasattr(self.llm_engine, "config") else {}
        return {
            "llm_configured": self.llm_engine.is_configured,
            "llm_provider": "Azure AI Foundry (Llama)",
            "llm_deployment_label": self.llm_engine.model_name,
            "fallback_available": True,
            "deterministic_version": self.deterministic_engine.VERSION,
            **safe_info,
        }

    def discover_and_rank_candidates(
        self,
        metadata_field: Dict[str, Any],
        domain: Optional[str] = None,
        historical_overrides: Optional[List[Dict[str, Any]]] = None,
        force_fallback: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes complete candidate discovery and ranking for a single metadata field.
        Returns mapping execution metadata and up to 3 ranked candidates with structured evidence.
        """
        fingerprint = compute_input_fingerprint(metadata_field, domain)
        started_at = datetime.now(timezone.utc).isoformat()

        # ---------------------------------------------------------------------
        # Stage A: Candidate Retrieval
        import time as _pytime
        t_stage7_start = _pytime.time()

        # ---------------------------------------------------------------------
        # Stage A: Candidate Retrieval (Bounded to top 8 candidates to avoid oversized prompts)
        # ---------------------------------------------------------------------
        field_name = metadata_field.get("name") or metadata_field.get("candidate_name") or ""
        field_expr = metadata_field.get("expression") or metadata_field.get("candidate_expression") or ""
        query_text = f"{field_name} {field_expr}".strip()

        # Retrieve candidates in target domain (and also general candidates)
        pool = self.kpi_bank.search(query=query_text, domain=domain, limit=8)
        if not pool and domain:
            pool = self.kpi_bank.search(query=query_text, domain=None, limit=8)
        if not pool:
            pool = self.kpi_bank.list_all(domain=domain)[:8]
        if not pool:
            pool = self.kpi_bank.list_all()[:8]

        if not pool:
            # Explicit no-match outcome
            return {
                "input_fingerprint": fingerprint,
                "matching_engine": self.deterministic_engine.VERSION,
                "primary_engine": "NONE",
                "fallback_used": False,
                "fallback_reason": None,
                "candidate_count": 0,
                "top_candidates": [],
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "ranking_duration_ms": round((_pytime.time() - t_stage7_start) * 1000, 2),
            }

        # ---------------------------------------------------------------------
        # Stage B: Semantic Ranking (LLM with Deterministic Fallback)
        # ---------------------------------------------------------------------
        top_candidates: List[Dict[str, Any]] = []
        matching_engine = self.llm_engine.VERSION
        primary_engine = "LLM_INFERENCE"
        fallback_used = False
        fallback_reason: Optional[str] = None

        if not force_fallback:
            try:
                top_candidates = self.llm_engine.match_and_rank(
                    metadata_field=metadata_field,
                    kpi_candidates=pool,
                    domain=domain,
                    historical_overrides=historical_overrides,
                    max_candidates=3,
                )
            except LLMMatchingError as ex:
                fallback_used = True
                fallback_reason = f"{ex.category}: {ex.message}" if ex.message else (ex.category or "LLM_ERROR")
                matching_engine = self.deterministic_engine.VERSION
                logger.info("Switching to deterministic matching engine: %s", fallback_reason)
            except Exception as ex:
                fallback_used = True
                fallback_reason = "UNEXPECTED_ERROR"
                matching_engine = self.deterministic_engine.VERSION
                logger.warning("Switching to deterministic matching engine: %s", ex)
        else:
            fallback_used = True
            fallback_reason = "MANUAL_FORCE_FALLBACK"
            matching_engine = self.deterministic_engine.VERSION

        # Execute deterministic engine if fallback occurred or LLM yielded 0 candidates
        if fallback_used or len(top_candidates) == 0:
            top_candidates = self.deterministic_engine.match_and_rank(
                metadata_field=metadata_field,
                kpi_candidates=pool,
                domain=domain,
                max_candidates=3,
            )
            for c in top_candidates:
                c["fallback_used"] = True
                c["fallback_reason"] = fallback_reason

        completed_at = datetime.now(timezone.utc).isoformat()
        ranking_duration_ms = round((_pytime.time() - t_stage7_start) * 1000, 2)
        logger.info(
            "Stage 7/9 [CANDIDATE_RANKING]: Field '%s' candidate ranking complete in %.2fms (engine=%s, fallback=%s, candidates=%d)",
            field_name,
            ranking_duration_ms,
            matching_engine,
            fallback_used,
            len(top_candidates),
        )

        return {
            "input_fingerprint": fingerprint,
            "matching_engine": matching_engine,
            "primary_engine": primary_engine,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "candidate_count": len(top_candidates),
            "top_candidates": top_candidates,
            "started_at": started_at,
            "completed_at": completed_at,
            "ranking_duration_ms": ranking_duration_ms,
        }


# Singleton instance helper
_orchestrator_instance: Optional[MatchingOrchestrator] = None


def get_matching_orchestrator(
    kpi_bank_service: Optional[KPIBankService] = None,
    llm_engine: Optional[LLMMatchingEngine] = None,
) -> MatchingOrchestrator:
    global _orchestrator_instance
    if _orchestrator_instance is None or kpi_bank_service is not None or llm_engine is not None:
        _orchestrator_instance = MatchingOrchestrator(
            kpi_bank_service=kpi_bank_service,
            llm_engine=llm_engine,
        )
    return _orchestrator_instance
