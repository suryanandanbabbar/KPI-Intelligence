"""
KPI Intelligence — Canonical Document Contracts (Base & Enums).

Defines the fundamental data contracts for Azure Cosmos DB for NoSQL documents:
- Strict schema versioning
- Deterministic document typing
- Multi-tenant boundary definition
- Serialization and validation utilities
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass, field, asdict


CURRENT_SCHEMA_VERSION = "2.0.0"


class DocumentType(str, Enum):
    # Catalog Container
    ASSET = "asset"
    ASSET_VERSION = "asset_version"
    REPORT = "report"
    SEMANTIC_MODEL = "semantic_model"
    ANALYTICAL_OBJECT = "analytical_object"
    LINEAGE_EDGE = "lineage_edge"
    SPREADSHEET_WORKBOOK = "spreadsheet_workbook"

    # Governance Container
    KPI_CANDIDATE = "kpi_candidate"
    KPI_MAPPING = "kpi_mapping"
    KPI_MAPPING_RUN = "kpi_mapping_run"
    MAPPING_APPROVAL = "mapping_approval"
    MAPPING_OVERRIDE = "mapping_override"
    KPI_RATIONALISATION = "kpi_rationalisation"
    DOMAIN_CLASSIFICATION = "domain_classification"
    METADATA_FIELD_REVIEW = "metadata_field_review"

    # Ontology Container
    ONTOLOGY_VERSION = "ontology_version"
    ONTOLOGY_ENTRY = "ontology_entry"
    BUSINESS_DOMAIN = "business_domain"
    PLATFORM_CAPABILITY = "platform_capability"

    # Operational Audit Container
    PARSER_RUN = "parser_run"
    EXTRACTION_ERROR = "extraction_error"
    AUDIT_EVENT = "audit_event"
    INGESTION_EVENT = "ingestion_event"
    ONTOLOGY_CHANGE_EVENT = "ontology_change_event"


class CosmosContainer(str, Enum):
    METADATA_CATALOG = "metadata_catalog"
    KPI_GOVERNANCE = "kpi_governance"
    KPI_ONTOLOGY = "kpi_ontology"
    OPERATIONAL_AUDIT = "operational_audit"


CONTAINER_PARTITION_KEYS = {
    CosmosContainer.METADATA_CATALOG: "/tenant_id",
    CosmosContainer.KPI_GOVERNANCE: "/tenant_id",
    CosmosContainer.KPI_ONTOLOGY: "/business_domain",
    CosmosContainer.OPERATIONAL_AUDIT: "/tenant_id",
}


def utc_now_iso() -> str:
    """Returns current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BaseDocument:
    """Base model for all Cosmos DB NoSQL documents in KPI Intelligence."""
    id: str
    doc_type: str
    schema_version: str = CURRENT_SCHEMA_VERSION
    tenant_id: Optional[str] = None  # None only for global reference data (e.g. ontology)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    ttl: Optional[int] = None  # -1 for indefinite retention, seconds for transient retention
    _etag: Optional[str] = None
    extra_properties: Dict[str, Any] = field(default_factory=dict)


    def validate(self) -> None:
        """Validates fundamental document invariants."""
        if not self.id or not str(self.id).strip():
            raise ValueError("Document 'id' cannot be null or empty.")
        if not self.doc_type or not str(self.doc_type).strip():
            raise ValueError("Document 'doc_type' cannot be null or empty.")
        if not self.schema_version:
            raise ValueError("Document 'schema_version' is required.")

    def to_dict(self) -> Dict[str, Any]:
        """Serializes document to dictionary for persistence."""
        self.validate()
        d = asdict(self)
        # Pull extra properties to top-level if needed, or preserve as structured
        if "_etag" in d and d["_etag"] is None:
            del d["_etag"]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseDocument":
        """Deserializes dictionary to BaseDocument."""
        clean = dict(data)
        etag = clean.pop("_etag", None)
        extra = clean.pop("extra_properties", {})
        known_fields = {f for f in cls.__dataclass_fields__}
        filtered = {}
        for k, v in clean.items():
            if k in known_fields:
                filtered[k] = v
            else:
                extra[k] = v
        obj = cls(**filtered, extra_properties=extra)
        obj._etag = etag
        return obj
