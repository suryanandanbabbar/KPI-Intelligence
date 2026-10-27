"""
KPI Intelligence — Business Domain Segregation and Classification Service.

Enforces:
- 5 primary supported business domains:
  1. Claims & Risk (CLAIMS_RISK)
  2. Legal (LEGAL)
  3. Underwriting (UNDERWRITING)
  4. Sales & Distribution (SALES_DISTRIBUTION)
  5. Actuarial (ACTUARIAL)
  Plus Service & Operations (SERVICE_OPERATIONS) for backward compatibility.
- Never merges Legal and Underwriting.
- Object-level classification (Report, Semantic Model, Table, Column, Measure, Visual).
- Primary and secondary domain identification with confidence codes (HIGH, MEDIUM, LOW, UNCLASSIFIED).
- Persistent human domain corrections with audit events.
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Tuple, Set
import re
import uuid
from datetime import datetime, timezone

from backend.contracts import (
    CosmosContainer,
    DomainClassificationDocument,
    MappingAuditEventDocument,
)
from backend.repository.interfaces import IRepository
from backend.repository.context import TenantContext


class BusinessDomainType(str, Enum):
    CLAIMS_RISK = "CLAIMS_RISK"
    LEGAL = "LEGAL"
    UNDERWRITING = "UNDERWRITING"
    SALES_DISTRIBUTION = "SALES_DISTRIBUTION"
    ACTUARIAL = "ACTUARIAL"
    SERVICE_OPERATIONS = "SERVICE_OPERATIONS"


DOMAIN_METADATA: Dict[str, Dict[str, Any]] = {
    BusinessDomainType.CLAIMS_RISK.value: {
        "code": "CLAIMS_RISK",
        "name": "Claims & Risk",
        "description": "Insurance claims processing, indemnity loss, reserves, recovery, subrogation, and fraud mitigation.",
        "icon": "shield.lefthalf.filled",
        "keywords": {
            "claim", "claims", "loss", "losses", "incurred", "paid", "indemnity", "reserve", "reserving",
            "salvage", "subrogation", "fraud", "adjuster", "litigated", "severity", "frequency", "catastrophe",
            "incident", "settlement", "ibnr", "case_reserve"
        },
    },
    BusinessDomainType.LEGAL.value: {
        "code": "LEGAL",
        "name": "Legal",
        "description": "Corporate governance, litigation defense, legal counsel billing, regulatory compliance, and statutory filings.",
        "icon": "scalemass",
        "keywords": {
            "legal", "litigation", "counsel", "attorney", "lawsuit", "court", "compliance", "regulatory",
            "statutory", "defense", "verdict", "dispute", "contract", "settled", "arbitration", "subpoena"
        },
    },
    BusinessDomainType.UNDERWRITING.value: {
        "code": "UNDERWRITING",
        "name": "Underwriting",
        "description": "Risk selection, policy issuance, capacity allocation, rating guidelines, and binder authorization.",
        "icon": "doc.text.magnifyingglass",
        "keywords": {
            "underwriting", "underwriter", "binder", "bind", "pricing", "rate", "capacity", "submission",
            "guideline", "quote", "quoted", "declination", "risk_appetite", "acceptance", "hit_ratio",
            "exposure", "tiv", "deductible", "limit", "endorsement", "facultative", "treaty"
        },
    },
    BusinessDomainType.SALES_DISTRIBUTION.value: {
        "code": "SALES_DISTRIBUTION",
        "name": "Sales & Distribution",
        "description": "Broker production, agency management, written premium, renewals, commissions, and new business pipeline.",
        "icon": "chart.line.uptrend.xyaxis",
        "keywords": {
            "sales", "distribution", "broker", "agency", "agent", "producer", "production", "commission",
            "written_premium", "gwp", "nwp", "new_business", "renewal", "retention", "pipeline", "campaign",
            "conversion", "cross_sell", "lead", "premium"
        },
    },
    BusinessDomainType.ACTUARIAL.value: {
        "code": "ACTUARIAL",
        "name": "Actuarial",
        "description": "Statistical modeling, loss triangles, pricing adequacy, capital reserving, solvency II, and rate making.",
        "icon": "function",
        "keywords": {
            "actuarial", "actuary", "triangle", "development", "link_ratio", "tail_factor", "ibnr", "solvency",
            "pricing_adequacy", "credibility", "pure_premium", "loss_cost", "discounting", "stochastic",
            "probabilistic", "var", "tvar", "trend_factor"
        },
    },
    BusinessDomainType.SERVICE_OPERATIONS.value: {
        "code": "SERVICE_OPERATIONS",
        "name": "Service & Operations",
        "description": "Policyholder servicing, call center operations, SLA compliance, document processing, and customer satisfaction.",
        "icon": "gearshape.2",
        "keywords": {
            "service", "operations", "call_center", "sla", "turnaround", "csat", "nps", "inquiry",
            "telephony", "first_call_resolution", "queue", "agent_declined", "abandonment", "policyholder"
        },
    },
}


def tokenize_words(text: str) -> Set[str]:
    """Tokenizes string into a set of lowercased alphanumeric words, supporting camelCase."""
    # Split camelCase e.g. IncurredLossRatio -> Incurred Loss Ratio
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text or "")
    norm = re.sub(r"[^a-zA-Z0-9\s_]", " ", s1.lower())
    return {w for w in norm.split() if len(w) >= 3}


class DomainClassificationService:
    """Service responsible for classifying analytical metadata into business domains."""

    def __init__(self, repository: Optional[IRepository] = None):
        self.repo = repository

    def get_supported_domains(self) -> List[Dict[str, Any]]:
        """Returns the supported business domain definitions with metadata."""
        return list(DOMAIN_METADATA.values())

    def classify_metadata_field(
        self,
        field_name: str,
        expression: Optional[str] = None,
        description: Optional[str] = None,
        parent_name: Optional[str] = None,
        parent_domain: Optional[str] = None,
        lineage: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Classifies an analytical metadata field (Measure, Column, Visual, Table) into a business domain.
        Returns primary domain, secondary domains, confidence code, confidence score, and supporting evidence.
        """
        combined_text = f"{field_name} {expression or ''} {description or ''} {parent_name or ''} {' '.join(lineage or [])}"
        tokens = tokenize_words(combined_text)

        domain_scores: Dict[str, float] = {}
        matched_evidence: Dict[str, List[str]] = {}

        for domain_code, meta in DOMAIN_METADATA.items():
            kw_set = meta["keywords"]
            matches = tokens & kw_set
            matched_evidence[domain_code] = sorted(list(matches))

            # Base score from keyword overlap
            score = min(1.0, len(matches) * 0.28)

            # Bonus if parent context matches domain
            if parent_domain and parent_domain.upper() == domain_code:
                score = min(1.0, score + 0.20)

            # Bonus if field name explicitly contains domain keyword
            field_tokens = tokenize_words(field_name)
            if field_tokens & kw_set:
                score = min(1.0, score + 0.25)

            domain_scores[domain_code] = round(score, 3)

        # Sort domains by score
        sorted_domains = sorted(domain_scores.items(), key=lambda x: x[1], reverse=True)
        top_domain, top_score = sorted_domains[0]
        second_domain, second_score = sorted_domains[1]

        # Determine confidence code
        if top_score >= 0.75:
            confidence_code = "HIGH"
        elif top_score >= 0.45:
            confidence_code = "MEDIUM"
        elif top_score >= 0.20:
            confidence_code = "LOW"
        else:
            confidence_code = "UNCLASSIFIED"
            top_domain = "UNCLASSIFIED"

        secondary_domains = []
        if confidence_code != "UNCLASSIFIED" and second_score >= 0.40 and (top_score - second_score) <= 0.25:
            secondary_domains.append(second_domain)

        return {
            "primary_domain": top_domain,
            "secondary_domains": secondary_domains,
            "confidence_code": confidence_code,
            "confidence_score": top_score if confidence_code != "UNCLASSIFIED" else 0.0,
            "classification_method": "SYNTACTIC_HEURISTIC",
            "supporting_evidence": matched_evidence.get(top_domain, []) if confidence_code != "UNCLASSIFIED" else [],
            "all_domain_scores": domain_scores,
            "classified_at": datetime.now(timezone.utc).isoformat(),
        }

    def record_human_correction(
        self,
        tenant_id: str,
        target_object_id: str,
        corrected_domain: str,
        user_id: str,
        justification: Optional[str] = None,
        previous_domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Records a human correction/override of a domain classification.
        Persists DomainClassificationDocument and MappingAuditEventDocument.
        """
        norm_domain = corrected_domain.upper()
        if norm_domain not in DOMAIN_METADATA:
            raise ValueError(f"Invalid domain '{corrected_domain}'. Supported: {list(DOMAIN_METADATA.keys())}")

        doc = DomainClassificationDocument(
            id=f"domclass_{target_object_id}",
            classification_id=f"domclass_{target_object_id}",
            tenant_id=tenant_id,
            target_object_id=target_object_id,
            domain_id=norm_domain,
            classification_method="HUMAN_OVERRIDE",
            confidence_score=1.0,
            rationale=justification or f"Human corrected to {norm_domain}",
            is_primary=True,
            approval_status="APPROVED",
        )

        audit_event = MappingAuditEventDocument(
            id=f"audit_dom_{uuid.uuid4()}",
            tenant_id=tenant_id,
            kpi_mapping_id=f"dom_{target_object_id}",
            actor_user_id=user_id,
            event_type="DOMAIN_CLASSIFICATION_CORRECTED",
            previous_state={"domain": previous_domain},
            new_state={"domain": norm_domain, "justification": justification},
            event_reason=justification or f"User {user_id} corrected domain",
        )

        if self.repo:
            ctx = TenantContext(tenant_id=tenant_id)
            self.repo.upsert_item(CosmosContainer.KPI_GOVERNANCE, tenant_id, doc.to_dict(), ctx)
            self.repo.upsert_item(CosmosContainer.OPERATIONAL_AUDIT, tenant_id, audit_event.to_dict(), ctx)

        return {
            "target_object_id": target_object_id,
            "corrected_domain": norm_domain,
            "classification_method": "HUMAN_OVERRIDE",
            "corrected_by": user_id,
            "justification": justification,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# Singleton helper
_domain_service_instance: Optional[DomainClassificationService] = None


def get_domain_service(repo: Optional[IRepository] = None) -> DomainClassificationService:
    global _domain_service_instance
    if _domain_service_instance is None or (repo is not None and _domain_service_instance.repo != repo):
        _domain_service_instance = DomainClassificationService(repository=repo)
    return _domain_service_instance
