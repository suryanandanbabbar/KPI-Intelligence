"""
KPI Intelligence — Governance Document Contracts (kpi_governance container).

Container: kpi_governance
Partition Key: /tenant_id
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from backend.contracts.base import BaseDocument, DocumentType


@dataclass
class KpiCandidateDocument(BaseDocument):
    """Discovered candidate KPI extracted from calculations, measures, or visual summaries."""
    doc_type: str = DocumentType.KPI_CANDIDATE.value
    asset_version_id: str = ""
    source_object_id: str = ""
    candidate_name: str = ""
    candidate_description: Optional[str] = None
    candidate_expression: Optional[str] = None
    expression_language: str = "DAX"
    normalised_expression: Optional[str] = None
    candidate_type: str = "MEASURE"
    unit: Optional[str] = None
    aggregation_type: Optional[str] = None
    business_domain_id: Optional[str] = None
    candidate_evidence: Dict[str, Any] = field(default_factory=dict)
    discovery_method: str = "SYNTACTIC"
    discovery_version: str = "1.0.0"

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("KpiCandidateDocument requires 'tenant_id'.")
        if not self.candidate_name:
            raise ValueError("KpiCandidateDocument requires 'candidate_name'.")


@dataclass
class ProposalCandidateItem:
    ontology_entry_id: str
    rank: int
    confidence_score: float
    confidence_band: str
    match_score: float
    name_similarity_score: float = 0.0
    definition_similarity_score: float = 0.0
    formula_similarity_score: float = 0.0
    context_similarity_score: float = 0.0
    domain_compatibility_score: float = 0.0
    unit_compatibility_score: float = 0.0
    rationale: str = ""
    supporting_evidence: List[str] = field(default_factory=list)
    contradicting_evidence: List[str] = field(default_factory=list)
    is_recommended: bool = False


@dataclass
class KpiMappingDocument(BaseDocument):
    """Mapping record connecting a candidate KPI to a curated ontology entry."""
    doc_type: str = DocumentType.KPI_MAPPING.value
    kpi_candidate_id: str = ""
    asset_version_id: str = ""
    ontology_version_id: str = ""
    selected_ontology_entry_id: Optional[str] = None
    mapping_status: str = "PROPOSED"  # PROPOSED, APPROVED, REJECTED, OVERRIDDEN
    decision_source: str = "LLM_INFERENCE"  # LLM_INFERENCE, DETERMINISTIC_FALLBACK, HUMAN_OVERRIDE
    mapping_version: int = 1
    input_fingerprint: str = ""
    top_candidates: List[Dict[str, Any]] = field(default_factory=list)
    active_approval: Optional[Dict[str, Any]] = None

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("KpiMappingDocument requires 'tenant_id'.")
        if not self.kpi_candidate_id:
            raise ValueError("KpiMappingDocument requires 'kpi_candidate_id'.")
        valid_statuses = {"PROPOSED", "APPROVED", "REJECTED", "OVERRIDDEN"}
        if self.mapping_status not in valid_statuses:
            raise ValueError(f"Invalid mapping_status '{self.mapping_status}'. Allowed: {valid_statuses}")


@dataclass
class MappingApprovalDocument(BaseDocument):
    """Immutable ledger record of human sign-off approving a candidate mapping."""
    doc_type: str = DocumentType.MAPPING_APPROVAL.value
    kpi_mapping_id: str = ""
    approved_ontology_entry_id: str = ""
    approved_by_user_id: str = ""
    approval_status: str = "ACTIVE"
    approval_version: int = 1
    approved_at: Optional[str] = None
    revoked_at: Optional[str] = None
    revocation_reason: Optional[str] = None

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("MappingApprovalDocument requires 'tenant_id'.")
        if not self.kpi_mapping_id:
            raise ValueError("MappingApprovalDocument requires 'kpi_mapping_id'.")
        if not self.approved_by_user_id:
            raise ValueError("MappingApprovalDocument requires 'approved_by_user_id'.")


@dataclass
class MappingOverrideDocument(BaseDocument):
    """Manual human override record specifying an alternative ontology entry and justification."""
    doc_type: str = DocumentType.MAPPING_OVERRIDE.value
    kpi_mapping_id: str = ""
    override_type: str = "SUBSTITUTION"
    previous_ontology_entry_id: Optional[str] = None
    replacement_ontology_entry_id: str = ""
    override_justification: str = ""
    normalised_justification: Optional[str] = None
    created_by_user_id: str = ""
    is_active: bool = True

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("MappingOverrideDocument requires 'tenant_id'.")
        if not self.override_justification or not self.override_justification.strip():
            raise ValueError("MappingOverrideDocument strictly requires a non-empty 'override_justification'.")


@dataclass
class KpiRationalisationDocument(BaseDocument):
    """Deduplication and consolidation decision across duplicate or equivalent KPIs."""
    doc_type: str = DocumentType.KPI_RATIONALISATION.value
    source_candidate_id: str = ""
    target_candidate_id: str = ""
    canonical_candidate_id: Optional[str] = None
    decision_type: str = "CONSOLIDATE"  # CONSOLIDATE, RETAIN_BOTH, DEPRECATE_SOURCE
    decision_status: str = "PROPOSED"
    decision_justification: Optional[str] = None
    equivalence_score: float = 0.0
    approved_by_user_id: Optional[str] = None
    equivalence_candidates: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("KpiRationalisationDocument requires 'tenant_id'.")
        if not self.source_candidate_id or not self.target_candidate_id:
            raise ValueError("KpiRationalisationDocument requires source and target candidate IDs.")


@dataclass
class DomainClassificationDocument(BaseDocument):
    """Domain classification record mapping an analytical object to a business domain."""
    doc_type: str = DocumentType.DOMAIN_CLASSIFICATION.value
    asset_version_id: str = ""
    target_object_id: str = ""
    domain_id: str = ""
    classification_method: str = "AUTOMATED_TAGGER"
    confidence_score: float = 1.0
    rationale: Optional[str] = None
    is_primary: bool = True
    approval_status: str = "APPROVED"

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("DomainClassificationDocument requires 'tenant_id'.")
        if not self.target_object_id or not self.domain_id:
            raise ValueError("DomainClassificationDocument requires 'target_object_id' and 'domain_id'.")


@dataclass
class MetadataFieldReviewDocument(BaseDocument):
    """Human review and override of specific extracted metadata fields."""
    doc_type: str = DocumentType.METADATA_FIELD_REVIEW.value
    asset_version_id: str = ""
    target_object_id: str = ""
    field_path: str = ""
    source_value_hash: Optional[str] = None
    proposed_value: Any = None
    approved_value: Any = None
    review_status: str = "PENDING"
    reviewed_by_user_id: Optional[str] = None
    reviewed_at: Optional[str] = None
    override_justification: Optional[str] = None

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("MetadataFieldReviewDocument requires 'tenant_id'.")
        if not self.field_path:
            raise ValueError("MetadataFieldReviewDocument requires 'field_path'.")

