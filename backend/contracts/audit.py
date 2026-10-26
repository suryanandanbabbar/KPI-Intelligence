"""
KPI Intelligence — Operational Audit Document Contracts (operational_audit container).

Container: operational_audit
Partition Key: /tenant_id
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from backend.contracts.base import BaseDocument, DocumentType


@dataclass
class ParserRunDocument(BaseDocument):
    """Execution telemetry record for platform metadata extraction (90-day transient retention)."""
    doc_type: str = DocumentType.PARSER_RUN.value
    parser_run_id: Optional[str] = None
    asset_version_id: str = ""
    platform: str = "POWER_BI"
    parser_name: str = "PowerBIParser"
    parser_version: str = "1.0.0"
    run_status: str = "SUCCESSFUL"
    objects_extracted: int = 0
    warnings_count: int = 0
    errors_count: int = 0
    source_artifact_id: Optional[str] = None
    started_at: str = ""
    completed_at: str = ""
    run_metadata: Dict[str, Any] = field(default_factory=dict)
    ttl: Optional[int] = 7776000  # 90 days transient retention

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("ParserRunDocument requires 'tenant_id'.")
        if not self.parser_run_id:
            self.parser_run_id = self.id


@dataclass
class ExtractionErrorDocument(BaseDocument):
    """Structured diagnostic / error during parsing and normalization (90-day transient retention)."""
    doc_type: str = DocumentType.EXTRACTION_ERROR.value
    extraction_error_id: Optional[str] = None
    parser_run_id: str = ""
    severity: str = "ERROR"  # INFO, WARNING, ERROR, FATAL
    error_code: str = ""
    error_message: str = ""
    source_artifact_id: Optional[str] = None
    object_locator: Optional[str] = None
    is_recoverable: bool = False
    ttl: Optional[int] = 7776000  # 90 days transient retention

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("ExtractionErrorDocument requires 'tenant_id'.")
        if not self.error_message:
            raise ValueError("ExtractionErrorDocument requires 'error_message'.")
        if not self.extraction_error_id:
            self.extraction_error_id = self.id


@dataclass
class MappingAuditEventDocument(BaseDocument):
    """Immutable audit entry recording mapping state transitions (Permanent Compliance Retention: Never Purged)."""
    doc_type: str = DocumentType.AUDIT_EVENT.value
    mapping_audit_event_id: Optional[str] = None
    kpi_mapping_id: str = ""
    target_kpi_mapping_id: Optional[str] = None
    actor_user_id: str = ""
    event_type: str = ""  # CREATED, PROPOSED, APPROVED, OVERRIDDEN
    previous_state: Dict[str, Any] = field(default_factory=dict)
    new_state: Dict[str, Any] = field(default_factory=dict)
    old_state: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None
    event_reason: Optional[str] = None
    ttl: Optional[int] = -1  # Indefinite retention (never deleted)

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("MappingAuditEventDocument requires 'tenant_id'.")
        if not self.kpi_mapping_id:
            raise ValueError("MappingAuditEventDocument requires 'kpi_mapping_id'.")
        if not self.actor_user_id:
            raise ValueError("MappingAuditEventDocument requires 'actor_user_id'.")
        if not self.mapping_audit_event_id:
            self.mapping_audit_event_id = self.id
        if not self.previous_state and self.old_state:
            self.previous_state = self.old_state
        if not self.event_reason and self.reason:
            self.event_reason = self.reason


@dataclass
class IngestionEventDocument(BaseDocument):
    """Audit log of physical file upload attempts (Permanent Retention)."""
    doc_type: str = DocumentType.INGESTION_EVENT.value
    ingestion_id: Optional[str] = None
    asset_version_id: str = ""
    uploaded_by_user_id: Optional[str] = None
    original_filename: str = ""
    upload_size_bytes: int = 0
    upload_source: str = "CLI"
    ingestion_status: str = "COMPLETED"
    started_at: str = ""
    completed_at: str = ""
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    ttl: Optional[int] = -1  # Indefinite retention

    def validate(self) -> None:
        super().validate()
        if not self.tenant_id:
            raise ValueError("IngestionEventDocument requires 'tenant_id'.")
        if not self.ingestion_id:
            self.ingestion_id = self.id


@dataclass
class OntologyChangeEventDocument(BaseDocument):
    """Immutable audit log of mutations to the curated KPI bank (Permanent Retention)."""
    doc_type: str = DocumentType.ONTOLOGY_CHANGE_EVENT.value
    ontology_change_event_id: Optional[str] = None
    ontology_version_id: str = ""
    ontology_entry_id: Optional[str] = None
    actor_user_id: str = ""
    change_type: str = ""  # CREATED, UPDATED, DEPRECATED
    previous_payload: Dict[str, Any] = field(default_factory=dict)
    new_payload: Dict[str, Any] = field(default_factory=dict)
    change_justification: Optional[str] = None
    business_domain: str = "GENERAL"  # Partition key for global ontology audit
    ttl: Optional[int] = -1  # Indefinite retention

    def validate(self) -> None:
        super().validate()
        if not self.actor_user_id:
            raise ValueError("OntologyChangeEventDocument requires 'actor_user_id'.")
        if not self.ontology_change_event_id:
            self.ontology_change_event_id = self.id
