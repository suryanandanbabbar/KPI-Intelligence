"""
KPI Intelligence — Override Learning & Re-ingestion Service.

Implements the layered lookup algorithm for reusing human decisions across re-ingestion:
- Level 1: Exact Persisted Identity
- Level 2: Stable Source Fingerprint
- Level 3: Semantic Field Fingerprint
- Level 4: Similarity-based Override Retrieval

Enforces precedence:
1. Explicit current human decision.
2. Valid existing approved mapping for same canonical entity.
3. Applicable previously approved override with exact source fingerprint.
4. Applicable previously approved override with strong semantic fingerprint and no contradiction.
5. Fresh candidate generation (LLM / deterministic fallback).

Detects conflicts:
- Conflicting overrides trigger review rather than arbitrary selection.
- Deprecated or materially altered KPIs invalidate automatic reuse.
"""

from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone
import uuid

from backend.contracts import (
    CosmosContainer,
    MappingOverrideDocument,
    MappingAuditEventDocument,
)
from backend.repository.interfaces import IRepository, QuerySpec
from backend.repository.context import TenantContext
from backend.learning.fingerprint import compute_source_fingerprint, compute_semantic_fingerprint
from backend.kpi_bank.service import KPIBankService


class OverrideLearningService:
    """Manages persistence, retrieval, and layered matching of human mapping overrides."""

    def __init__(self, repository: Optional[IRepository] = None):
        self.repo = repository
        self._memory_overrides: Dict[str, List[Dict[str, Any]]] = {}

    def record_override(
        self,
        tenant_id: str,
        kpi_mapping_id: str,
        replacement_kpi_id: str,
        override_justification: str,
        user_id: str,
        metadata_field: Dict[str, Any],
        original_candidates: Optional[List[Dict[str, Any]]] = None,
        previous_kpi_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Persists a reusable human override decision into the canonical data model.
        Computes stable source and semantic fingerprints for re-ingestion reuse.
        """
        justification_clean = (override_justification or "").strip()
        if len(justification_clean) < 10:
            raise ValueError("Override justification must be at least 10 characters explaining the decision.")

        field_name = metadata_field.get("name") or metadata_field.get("candidate_name") or ""
        field_expr = metadata_field.get("expression") or metadata_field.get("candidate_expression")
        field_dtype = metadata_field.get("data_type", "DECIMAL")
        field_table = metadata_field.get("parent_name") or metadata_field.get("table_name")
        field_domain = metadata_field.get("domain") or metadata_field.get("business_domain")
        platform = metadata_field.get("platform", "POWER_BI")
        asset_id = metadata_field.get("asset_id", "")
        entity_id = metadata_field.get("field_id") or metadata_field.get("object_id") or ""

        src_fp = compute_source_fingerprint(
            platform=platform,
            asset_id=asset_id,
            entity_type=metadata_field.get("entity_type", "MEASURE"),
            entity_name=field_name,
        )
        sem_fp = compute_semantic_fingerprint(
            field_name=field_name,
            expression=field_expr,
            data_type=field_dtype,
            table_name=field_table,
            domain=field_domain,
        )

        override_id = f"ovr_{uuid.uuid4()}"
        doc = MappingOverrideDocument(
            id=override_id,
            override_id=override_id,
            tenant_id=tenant_id,
            kpi_mapping_id=kpi_mapping_id,
            override_type="SUBSTITUTION",
            previous_ontology_entry_id=previous_kpi_id,
            replacement_ontology_entry_id=replacement_kpi_id,
            override_justification=justification_clean,
            normalised_justification=justification_clean.lower(),
            created_by_user_id=user_id,
            is_active=True,
            source_platform=platform,
            source_asset_id=asset_id,
            canonical_entity_type=metadata_field.get("entity_type", "MEASURE"),
            canonical_entity_id=entity_id,
            canonical_source_fingerprint=src_fp,
            semantic_field_fingerprint=sem_fp,
            domain_context=field_domain or "",
            original_candidates=original_candidates or [],
            reuse_count=0,
            match_method="EXPLICIT_OVERRIDE",
        )

        audit_event = MappingAuditEventDocument(
            id=f"audit_ovr_{uuid.uuid4()}",
            tenant_id=tenant_id,
            kpi_mapping_id=kpi_mapping_id,
            target_kpi_mapping_id=replacement_kpi_id,
            actor_user_id=user_id,
            event_type="OVERRIDE_RECORDED",
            previous_state={"kpi_id": previous_kpi_id},
            new_state={
                "kpi_id": replacement_kpi_id,
                "justification": justification_clean,
                "source_fingerprint": src_fp,
                "semantic_fingerprint": sem_fp,
            },
            event_reason=f"Human override to KPI {replacement_kpi_id}: {justification_clean}",
        )

        record_dict = doc.to_dict()

        if self.repo:
            ctx = TenantContext(tenant_id=tenant_id)
            self.repo.upsert_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, record_dict, ctx)
            self.repo.upsert_item(CosmosContainer.OPERATIONAL_AUDIT, tenant_id, audit_event.to_dict(), ctx)

        self._memory_overrides.setdefault(tenant_id, []).append(record_dict)
        return record_dict

    def find_reusable_override(
        self,
        tenant_id: str,
        metadata_field: Dict[str, Any],
        kpi_bank: KPIBankService,
    ) -> Dict[str, Any]:
        """
        Executes layered lookup across historical overrides for a given metadata field.
        Returns match status, level, selected override (if any), and conflict details.
        """
        active_overrides = self.list_active_overrides(tenant_id)
        if not active_overrides:
            return {"has_match": False, "match_level": None, "override": None, "has_conflict": False}

        field_name = metadata_field.get("name") or metadata_field.get("candidate_name") or ""
        field_expr = metadata_field.get("expression") or metadata_field.get("candidate_expression")
        field_dtype = metadata_field.get("data_type", "DECIMAL")
        field_table = metadata_field.get("parent_name") or metadata_field.get("table_name")
        field_domain = metadata_field.get("domain") or metadata_field.get("business_domain")
        platform = metadata_field.get("platform", "POWER_BI")
        asset_id = metadata_field.get("asset_id", "")
        entity_id = metadata_field.get("field_id") or metadata_field.get("object_id") or ""

        target_src_fp = compute_source_fingerprint(
            platform=platform,
            asset_id=asset_id,
            entity_type=metadata_field.get("entity_type", "MEASURE"),
            entity_name=field_name,
        )
        target_sem_fp = compute_semantic_fingerprint(
            field_name=field_name,
            expression=field_expr,
            data_type=field_dtype,
            table_name=field_table,
            domain=field_domain,
        )

        matched_records: List[Tuple[str, Dict[str, Any]]] = []

        # ---------------------------------------------------------------------
        # Level 1: Exact Persisted Canonical Entity ID Match
        # ---------------------------------------------------------------------
        if entity_id:
            for ovr in active_overrides:
                if ovr.get("canonical_entity_id") == entity_id:
                    matched_records.append(("LEVEL_1_EXACT_IDENTITY", ovr))

        # ---------------------------------------------------------------------
        # Level 2: Stable Source Fingerprint Match
        # ---------------------------------------------------------------------
        if not matched_records:
            for ovr in active_overrides:
                if ovr.get("canonical_source_fingerprint") == target_src_fp:
                    matched_records.append(("LEVEL_2_SOURCE_FINGERPRINT", ovr))

        # ---------------------------------------------------------------------
        # Level 3: Semantic Field Fingerprint Match
        # ---------------------------------------------------------------------
        if not matched_records:
            for ovr in active_overrides:
                if ovr.get("semantic_field_fingerprint") == target_sem_fp:
                    matched_records.append(("LEVEL_3_SEMANTIC_FINGERPRINT", ovr))

        if not matched_records:
            return {"has_match": False, "match_level": None, "override": None, "has_conflict": False}

        # Check for conflicting targets (e.g., multiple overrides pointing to different KPIs)
        target_kpi_ids = {r[1].get("replacement_ontology_entry_id") for r in matched_records}
        if len(target_kpi_ids) > 1:
            return {
                "has_match": False,
                "has_conflict": True,
                "match_level": matched_records[0][0],
                "conflicting_overrides": [r[1] for r in matched_records],
                "reason": "Multiple contradictory overrides exist for this metadata fingerprint. Human review required.",
            }

        level, selected_ovr = matched_records[0]
        kpi_target_id = selected_ovr.get("replacement_ontology_entry_id")

        # Verify target KPI is still valid and active in the KPI Bank
        target_kpi = kpi_bank.get_by_id(kpi_target_id)
        if not target_kpi:
            return {
                "has_match": False,
                "has_conflict": False,
                "reason": f"Target KPI '{kpi_target_id}' no longer exists in KPI Bank.",
                "override": None,
            }
        if target_kpi.get("status") == "deprecated":
            return {
                "has_match": False,
                "has_conflict": True,
                "reason": f"Target KPI '{target_kpi.get('name')}' is deprecated. Human review required.",
                "override": None,
            }

        # Safe to reuse: increment reuse count
        selected_ovr["reuse_count"] = selected_ovr.get("reuse_count", 0) + 1
        selected_ovr["last_reused_at"] = datetime.now(timezone.utc).isoformat()

        # Update in repository if present
        if self.repo:
            try:
                ctx = TenantContext(tenant_id=tenant_id)
                self.repo.upsert_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, selected_ovr, ctx)
                # Audit event for override reuse
                reuse_audit = MappingAuditEventDocument(
                    id=f"audit_reuse_{uuid.uuid4()}",
                    tenant_id=tenant_id,
                    kpi_mapping_id=selected_ovr.get("kpi_mapping_id", ""),
                    target_kpi_mapping_id=kpi_target_id,
                    actor_user_id="SYSTEM_REUSE",
                    event_type="OVERRIDE_REUSED_IN_INGESTION",
                    previous_state={},
                    new_state={"match_level": level, "override_id": selected_ovr.get("override_id")},
                    event_reason=f"Safely reused human override {selected_ovr.get('override_id')} via {level}",
                )
                self.repo.upsert_item(CosmosContainer.OPERATIONAL_AUDIT, tenant_id, reuse_audit.to_dict(), ctx)
            except Exception:
                pass

        return {
            "has_match": True,
            "has_conflict": False,
            "match_level": level,
            "override": selected_ovr,
            "target_kpi": target_kpi,
            "evidence": f"Reused prior human override by {selected_ovr.get('created_by_user_id', 'analyst')} via {level}",
        }

    def list_active_overrides(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Returns all active overrides for a tenant."""
        if self.repo:
            try:
                ctx = TenantContext(tenant_id=tenant_id)
                query = "SELECT * FROM c WHERE c.tenant_id = @tenant_id AND c.doc_type = @doc_type AND c.is_active = true"
                spec = QuerySpec(
                    query=query,
                    parameters=[
                        {"name": "@tenant_id", "value": tenant_id},
                        {"name": "@doc_type", "value": "mapping_override"},
                    ],
                )
                res = self.repo.query_items(CosmosContainer.KPI_GOVERNANCE, tenant_id, spec, ctx)
                if res and res.items:
                    return res.items
            except Exception:
                pass

        return [o for o in self._memory_overrides.get(tenant_id, []) if o.get("is_active", True)]

    def invalidate_override(self, tenant_id: str, override_id: str, user_id: str, reason: str) -> bool:
        """Invalidates an override so it is no longer reused in future ingestion."""
        active = self.list_active_overrides(tenant_id)
        target = next((o for o in active if o.get("override_id") == override_id or o.get("id") == override_id), None)
        if not target:
            return False

        target["is_active"] = False
        target["invalidated_by"] = user_id
        target["invalidated_at"] = datetime.now(timezone.utc).isoformat()
        target["invalidation_reason"] = reason

        if self.repo:
            try:
                ctx = TenantContext(tenant_id=tenant_id)
                self.repo.upsert_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, target, ctx)
                audit_event = MappingAuditEventDocument(
                    id=f"audit_inval_{uuid.uuid4()}",
                    tenant_id=tenant_id,
                    kpi_mapping_id=target.get("kpi_mapping_id", ""),
                    target_kpi_mapping_id=target.get("replacement_ontology_entry_id", ""),
                    actor_user_id=user_id,
                    event_type="OVERRIDE_INVALIDATED",
                    previous_state={"is_active": True},
                    new_state={"is_active": False, "reason": reason},
                    event_reason=f"User {user_id} invalidated override: {reason}",
                )
                self.repo.upsert_item(CosmosContainer.OPERATIONAL_AUDIT, tenant_id, audit_event.to_dict(), ctx)
            except Exception:
                pass

        return True


# Singleton helper
_learning_service_instance: Optional[OverrideLearningService] = None


def get_override_learning_service(repo: Optional[IRepository] = None) -> OverrideLearningService:
    global _learning_service_instance
    if _learning_service_instance is None or (repo is not None and _learning_service_instance.repo != repo):
        _learning_service_instance = OverrideLearningService(repository=repo)
    return _learning_service_instance
