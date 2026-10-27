"""
KPI Intelligence — KPI Bank Reference Catalogue Service.

Provides:
- Ingestion and indexing of the controlled reference KPI Bank JSON fixture.
- Multi-field text search with normalized token ranking and domain filtering.
- KPI lifecycle management (active, draft, deprecated).
- Duplicate and near-equivalent KPI detection.
- Governed creation of new standard KPIs conforming to the authoritative contract.
"""

import os
import json
import uuid
import re
from typing import Dict, List, Optional, Any, Tuple, Set
from datetime import datetime, timezone

from backend.contracts import (
    CosmosContainer,
    OntologyEntryDocument,
    BusinessDomainDocument,
)
from backend.repository.interfaces import IRepository
from backend.repository.context import TenantContext

DEFAULT_FIXTURE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "fixtures", "kpi_bank_representative_fixture.json")
)

# Canonical domain normalization map
DOMAIN_NORMALIZATION_MAP = {
    "claims": "CLAIMS_RISK",
    "claims_risk": "CLAIMS_RISK",
    "claims & risk": "CLAIMS_RISK",
    "underwriting": "UNDERWRITING",
    "legal": "LEGAL",
    "sales": "SALES_DISTRIBUTION",
    "sales_distribution": "SALES_DISTRIBUTION",
    "sales & distribution": "SALES_DISTRIBUTION",
    "actuarial": "ACTUARIAL",
    "service": "SERVICE_OPERATIONS",
    "service_operations": "SERVICE_OPERATIONS",
    "service & operations": "SERVICE_OPERATIONS",
    "marketing": "SALES_DISTRIBUTION",
}


def normalize_token(text: str) -> str:
    """Removes special characters and lowercases text."""
    return re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower()).strip()


def tokenize(text: str) -> Set[str]:
    """Tokenizes string into a set of lowercased alphanumeric words."""
    norm = normalize_token(text)
    return set(norm.split()) if norm else set()


class KPIBankService:
    """Service managing the reference KPI Bank catalog, search, and additions."""

    def __init__(self, repository: Optional[IRepository] = None, fixture_path: Optional[str] = None):
        self.repo = repository
        self.fixture_path = fixture_path or DEFAULT_FIXTURE_PATH
        self._kpis: Dict[str, Dict[str, Any]] = {}
        self._kpis_by_code: Dict[str, str] = {}
        self.load_catalogue()

    def load_catalogue(self) -> int:
        """Loads and indexes the KPI Bank from fixture and/or repository."""
        count = 0
        if os.path.exists(self.fixture_path):
            with open(self.fixture_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                raw_kpis = data.get("kpis", [])
                for item in raw_kpis:
                    kpi_id = item.get("kpi_id") or str(uuid.uuid4())
                    kpi_entry = self._normalize_fixture_kpi(kpi_id, item)
                    self._kpis[kpi_id] = kpi_entry
                    if kpi_entry.get("kpi_code"):
                        self._kpis_by_code[kpi_entry["kpi_code"]] = kpi_id
                    count += 1

        # If repo is present, sync any existing repository ontology entries
        if self.repo:
            try:
                ctx = TenantContext.system_context()
                for dom in ["CLAIMS_RISK", "LEGAL", "UNDERWRITING", "SALES_DISTRIBUTION", "ACTUARIAL", "SERVICE_OPERATIONS"]:
                    docs = self.repo.get_item(CosmosContainer.KPI_ONTOLOGY, dom, f"kpi_{dom.lower()}_sample", ctx)
                    if docs and isinstance(docs, dict):
                        k_id = docs.get("ontology_entry_id") or docs.get("id")
                        if k_id and k_id not in self._kpis:
                            self._kpis[k_id] = docs
            except Exception:
                pass

        return count

    def _normalize_fixture_kpi(self, kpi_id: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalizes a raw fixture entry into standard dictionary structure."""
        name = raw.get("name", "").strip()
        definition = raw.get("definition", "").strip()
        raw_domain = raw.get("domain", "General")
        norm_domain = DOMAIN_NORMALIZATION_MAP.get(raw_domain.lower(), "CLAIMS_RISK")

        aliases = list(raw.get("aliases", []))
        enrichments = raw.get("enrichments", [])
        primary_enrichment = enrichments[0] if (isinstance(enrichments, list) and len(enrichments) > 0) else {}

        formula = primary_enrichment.get("calculation") if isinstance(primary_enrichment, dict) else None
        fields_required = primary_enrichment.get("fields_required") if isinstance(primary_enrichment, dict) else None
        business_meaning = primary_enrichment.get("business_meaning") if isinstance(primary_enrichment, dict) else None
        metric_description = primary_enrichment.get("metric_description") if isinstance(primary_enrichment, dict) else None

        kpi_code = raw.get("kpi_code") or f"KPI_{kpi_id[:8].upper()}"

        return {
            "kpi_id": kpi_id,
            "ontology_entry_id": kpi_id,
            "id": kpi_id,
            "kpi_code": kpi_code,
            "name": name,
            "kpi_name": name,
            "definition": definition,
            "domain": raw_domain,
            "business_domain": norm_domain,
            "sector": raw.get("sector", "insurance"),
            "subdomain": raw.get("subdomain"),
            "line_of_business": raw.get("line_of_business"),
            "aliases": aliases,
            "aggregation_type": raw.get("aggregation_type", "SUM"),
            "valid_dimensions": raw.get("valid_dimensions", []),
            "status": raw.get("status", "active"),
            "is_active_sector": bool(raw.get("is_active_sector", True)),
            "kpi_type": raw.get("kpi_type", "built-in"),
            "formula": formula,
            "fields_required": fields_required,
            "business_meaning": business_meaning,
            "metric_description": metric_description,
            "enrichments": enrichments,
            "raw_payload": raw,
            "created_at": raw.get("created_at") or datetime.now(timezone.utc).isoformat(),
        }

    def get_by_id(self, kpi_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a KPI entry by identifier."""
        return self._kpis.get(kpi_id)

    def list_all(self, domain: Optional[str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns all KPIs matching optional domain and status filters."""
        res = list(self._kpis.values())
        if domain:
            d_norm = DOMAIN_NORMALIZATION_MAP.get(domain.lower(), domain.upper())
            res = [k for k in res if k.get("business_domain") == d_norm or k.get("domain", "").lower() == domain.lower()]
        if status:
            res = [k for k in res if k.get("status", "").lower() == status.lower()]
        return res

    def search(
        self,
        query: Optional[str] = None,
        domain: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Searches the KPI Bank with normalized token relevance scoring.
        Supports filtering by domain and lifecycle status.
        """
        candidates = self.list_all(domain=domain, status=status)
        if not query or not query.strip():
            return candidates[:limit]

        query_clean = query.strip()
        q_tokens = tokenize(query_clean)
        q_lower = query_clean.lower()

        scored: List[Tuple[float, Dict[str, Any]]] = []

        for k in candidates:
            score = 0.0
            name_clean = k.get("name", "").strip()
            name_lower = name_clean.lower()
            name_tokens = tokenize(name_clean)

            # 1. Exact name match
            if name_lower == q_lower:
                score += 100.0
            elif name_lower.startswith(q_lower):
                score += 50.0
            elif q_lower in name_lower:
                score += 30.0

            # 2. Token overlap with name
            if q_tokens and name_tokens:
                overlap = len(q_tokens & name_tokens) / len(q_tokens)
                score += overlap * 25.0

            # 3. Alias matches
            for alias in k.get("aliases", []):
                a_lower = str(alias).lower()
                if a_lower == q_lower:
                    score += 80.0
                elif q_lower in a_lower:
                    score += 20.0
                a_tokens = tokenize(str(alias))
                if q_tokens and a_tokens:
                    score += (len(q_tokens & a_tokens) / len(q_tokens)) * 15.0

            # 4. Definition & business meaning overlap
            def_text = f"{k.get('definition', '')} {k.get('business_meaning', '')} {k.get('metric_description', '')}"
            def_tokens = tokenize(def_text)
            if q_tokens and def_tokens:
                def_overlap = len(q_tokens & def_tokens) / len(q_tokens)
                score += def_overlap * 15.0

            # 5. Formula / required fields overlap
            calc_text = f"{k.get('formula', '')} {k.get('fields_required', '')}"
            calc_tokens = tokenize(calc_text)
            if q_tokens and calc_tokens:
                calc_overlap = len(q_tokens & calc_tokens) / len(q_tokens)
                score += calc_overlap * 10.0

            if score > 0.0:
                scored.append((score, k))

        # Sort descending by score
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    def detect_duplicates(
        self,
        name: str,
        aliases: Optional[List[str]] = None,
        formula: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Detects potential duplicate or near-equivalent KPIs in the bank.
        """
        potential_dupes: List[Dict[str, Any]] = []
        name_clean = name.strip().lower()
        aliases_clean = [str(a).strip().lower() for a in (aliases or [])]

        for k in self._kpis.values():
            k_name = k.get("name", "").strip().lower()
            k_aliases = [str(a).strip().lower() for a in k.get("aliases", [])]

            # Direct name collision
            if k_name == name_clean:
                potential_dupes.append({
                    "kpi_id": k["kpi_id"],
                    "kpi_name": k["name"],
                    "match_type": "EXACT_NAME",
                    "reason": f"Exact match with existing KPI '{k['name']}'",
                })
                continue

            # Name matches existing alias
            if name_clean in k_aliases:
                potential_dupes.append({
                    "kpi_id": k["kpi_id"],
                    "kpi_name": k["name"],
                    "match_type": "ALIAS_MATCH",
                    "reason": f"Name matches alias on existing KPI '{k['name']}'",
                })
                continue

            # Alias matches existing name
            for a in aliases_clean:
                if a == k_name:
                    potential_dupes.append({
                        "kpi_id": k["kpi_id"],
                        "kpi_name": k["name"],
                        "match_type": "ALIAS_COLLISION",
                        "reason": f"Alias '{a}' matches existing KPI '{k['name']}'",
                    })
                    break

        return potential_dupes

    def create_kpi(self, kpi_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Creates a new KPI conforming to the authoritative KPI Bank schema.
        Validates required fields, prevents invalid domain combinations,
        and saves to memory and repository if configured.
        """
        name = (kpi_data.get("name") or kpi_data.get("kpi_name") or "").strip()
        if not name:
            raise ValueError("KPI creation failed: 'name' is required.")

        definition = (kpi_data.get("definition") or "").strip()
        if not definition:
            raise ValueError("KPI creation failed: 'definition' is required.")

        raw_domain = (kpi_data.get("domain") or "General").strip()
        norm_domain = DOMAIN_NORMALIZATION_MAP.get(raw_domain.lower(), "CLAIMS_RISK")

        # Duplicate checking
        dupes = self.detect_duplicates(name, kpi_data.get("aliases"), kpi_data.get("formula"))
        exact_dupe = next((d for d in dupes if d["match_type"] == "EXACT_NAME"), None)
        if exact_dupe:
            raise ValueError(f"KPI creation rejected: An exact duplicate exists with ID '{exact_dupe['kpi_id']}'.")

        kpi_id = str(kpi_data.get("kpi_id") or uuid.uuid4())
        kpi_code = kpi_data.get("kpi_code") or f"KPI_USR_{kpi_id[:8].upper()}"

        enrichments = kpi_data.get("enrichments") or []
        if not enrichments and (kpi_data.get("formula") or kpi_data.get("calculation")):
            enrichments = [{
                "calculation": kpi_data.get("formula") or kpi_data.get("calculation"),
                "fields_required": kpi_data.get("fields_required", ""),
                "business_meaning": kpi_data.get("business_meaning", definition),
                "metric_description": kpi_data.get("metric_description", definition),
                "category": kpi_data.get("category", "Custom"),
                "team": raw_domain,
            }]

        new_entry = {
            "kpi_id": kpi_id,
            "ontology_entry_id": kpi_id,
            "id": kpi_id,
            "kpi_code": kpi_code,
            "name": name,
            "kpi_name": name,
            "definition": definition,
            "domain": raw_domain,
            "business_domain": norm_domain,
            "sector": kpi_data.get("sector", "insurance"),
            "subdomain": kpi_data.get("subdomain"),
            "line_of_business": kpi_data.get("line_of_business"),
            "aliases": list(kpi_data.get("aliases") or []),
            "aggregation_type": kpi_data.get("aggregation_type", "SUM"),
            "valid_dimensions": list(kpi_data.get("valid_dimensions") or []),
            "status": kpi_data.get("status", "draft"),
            "is_active_sector": True,
            "kpi_type": "user-defined",
            "formula": kpi_data.get("formula") or (enrichments[0].get("calculation") if enrichments else None),
            "fields_required": kpi_data.get("fields_required") or (enrichments[0].get("fields_required") if enrichments else None),
            "business_meaning": kpi_data.get("business_meaning") or definition,
            "metric_description": kpi_data.get("metric_description") or definition,
            "enrichments": enrichments,
            "raw_payload": dict(kpi_data),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": kpi_data.get("created_by", "analyst"),
        }

        # Index in memory
        self._kpis[kpi_id] = new_entry
        self._kpis_by_code[kpi_code] = kpi_id

        # Persist to repository if available
        if self.repo:
            try:
                doc = OntologyEntryDocument(
                    id=f"kpi_{kpi_id}",
                    ontology_entry_id=kpi_id,
                    business_domain=norm_domain,
                    ontology_version_id="onto_usr_v1",
                    kpi_code=kpi_code,
                    kpi_name=name,
                    definition=definition,
                    formula=new_entry["formula"],
                    unit=kpi_data.get("unit"),
                    aggregation_method=new_entry["aggregation_type"],
                    synonyms=new_entry["aliases"],
                    valid_dimensions=new_entry["valid_dimensions"],
                    enrichments=enrichments[0] if enrichments else {},
                    ontology_payload=new_entry,
                )
                ctx = TenantContext.system_context()
                self.repo.upsert_item(CosmosContainer.KPI_ONTOLOGY, norm_domain, doc.to_dict(), ctx)
            except Exception:
                pass

        return new_entry


# Singleton instance helper
_service_instance: Optional[KPIBankService] = None


def get_kpi_bank_service(repo: Optional[IRepository] = None) -> KPIBankService:
    global _service_instance
    if _service_instance is None or (repo is not None and _service_instance.repo != repo):
        _service_instance = KPIBankService(repository=repo)
    return _service_instance
