"""
KPI Intelligence — Ontology Document Contracts (kpi_ontology container).

Container: kpi_ontology
Partition Key: /business_domain
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from backend.contracts.base import BaseDocument, DocumentType


@dataclass
class OntologyVersionDocument(BaseDocument):
    """Release metadata for a curated KPI bank release."""
    doc_type: str = DocumentType.ONTOLOGY_VERSION.value
    business_domain: str = "GENERAL"  # Partition key
    version_number: str = "1.0.0"
    content_hash: str = ""
    kpi_count: int = 0
    change_summary: Optional[str] = None
    is_active: bool = True

    def validate(self) -> None:
        super().validate()
        if not self.business_domain:
            self.business_domain = "GENERAL"
        if not self.content_hash:
            raise ValueError("OntologyVersionDocument requires 'content_hash'.")


@dataclass
class OntologyEntryDocument(BaseDocument):
    """Curated standard KPI definition from the KPI Bank."""
    doc_type: str = DocumentType.ONTOLOGY_ENTRY.value
    business_domain: str = "CLAIMS_RISK"  # Partition key
    ontology_version_id: str = ""
    kpi_code: str = ""
    kpi_name: str = ""
    kpi_description: Optional[str] = None
    definition: Optional[str] = None
    formula: Optional[str] = None
    unit: Optional[str] = None
    aggregation_method: Optional[str] = None
    synonyms: List[str] = field(default_factory=list)
    valid_dimensions: List[str] = field(default_factory=list)
    source_kpi_id: Optional[str] = None
    source_sector: Optional[str] = None
    source_subdomain: Optional[str] = None
    source_line_of_business: Optional[str] = None
    source_status: Optional[str] = None
    enrichments: Dict[str, Any] = field(default_factory=dict)
    ontology_payload: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        super().validate()
        if not self.business_domain:
            raise ValueError("OntologyEntryDocument requires 'business_domain' as partition key.")
        if not self.kpi_code:
            raise ValueError("OntologyEntryDocument requires 'kpi_code'.")
        if not self.kpi_name:
            raise ValueError("OntologyEntryDocument requires 'kpi_name'.")


@dataclass
class BusinessDomainDocument(BaseDocument):
    """One of the 6 canonical business domains (Claims & Risk, Underwriting, Legal, etc.)."""
    doc_type: str = DocumentType.BUSINESS_DOMAIN.value
    business_domain: str = "SYSTEM"  # Partition key
    domain_code: str = ""
    domain_name: str = ""
    domain_description: Optional[str] = None
    is_active: bool = True

    def validate(self) -> None:
        super().validate()
        if not self.domain_code:
            raise ValueError("BusinessDomainDocument requires 'domain_code'.")
        if not self.domain_name:
            raise ValueError("BusinessDomainDocument requires 'domain_name'.")


@dataclass
class PlatformCapabilityDocument(BaseDocument):
    """Supported metadata features and capabilities by platform version (global reference)."""
    doc_type: str = DocumentType.PLATFORM_CAPABILITY.value
    business_domain: str = "SYSTEM"  # Global partition key
    platform: str = "POWER_BI"
    artifact_type: str = "PBIP"
    metadata_type: str = "TMDL"
    capability_status: str = "SUPPORTED"
    minimum_source_version: Optional[str] = None
    maximum_source_version: Optional[str] = None
    notes: Optional[str] = None
    capability_properties: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        super().validate()
        if not self.platform:
            raise ValueError("PlatformCapabilityDocument requires 'platform'.")

