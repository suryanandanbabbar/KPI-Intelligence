#!/usr/bin/env python3
"""
KPI Intelligence — KPI Bank JSON Parser, Validator, and Normalizer

This module implements the complete parsing, validation, diagnostic, and canonical mapping
pipeline for the local KPI Ontology Bank JSON resource.

Key Architectural Invariants:
1. 100% Lossless Source Preservation: Complete original record stored in ontology_payload.
2. Source Taxonomy vs Application Classification: Source domain (e.g. 'Marketing') is preserved
   verbatim and never conflated with the 6 application business domains.
3. Multi-Enrichment Integrity: Ordered array of enrichments preserved without flattening.
4. Structured Diagnostics: Validation produces explicit diagnostics with severity and action.
5. Deduplication & Provenance: Source identifiers and workbook provenance are preserved.
"""

import json
import re
import hashlib
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Set

# The 6 seeded canonical application business domains for reference
APPLICATION_BUSINESS_DOMAINS = {
    "CLAIMS_RISK": "Claims & Risk",
    "LEGAL": "Legal",
    "UNDERWRITING": "Underwriting",
    "SALES_DISTRIBUTION": "Sales & Distribution",
    "SERVICE_OPERATIONS": "Service & Operations",
    "ACTUARIAL": "Actuarial"
}

# Known suspicious placeholder tokens in legacy or malformed exports
SUSPICIOUS_PLACEHOLDERS = {"excel", "11m", "tbd", "n/a", "none", "temp", "placeholder"}


class DiagnosticSeverity:
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"


class DiagnosticAction:
    ACCEPTED = "ACCEPTED"
    ACCEPTED_WITH_WARNING = "ACCEPTED_WITH_WARNING"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


class KPIValidationDiagnostic:
    def __init__(
        self,
        record_id: Optional[str],
        json_path: str,
        error_code: str,
        message: str,
        severity: str,
        action: str
    ):
        self.record_id = record_id
        self.json_path = json_path
        self.error_code = error_code
        self.message = message
        self.severity = severity
        self.action = action

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "json_path": self.json_path,
            "error_code": self.error_code,
            "message": self.message,
            "severity": self.severity,
            "action": self.action
        }

    def __repr__(self) -> str:
        return f"[{self.severity}:{self.error_code}] {self.json_path} -> {self.message} ({self.action})"


class NormalizedKPIEntry:
    def __init__(
        self,
        kpi_code: str,
        source_kpi_id: str,
        kpi_name: str,
        kpi_description: Optional[str],
        business_domain: str,
        definition: str,
        formula: Optional[str],
        unit: Optional[str],
        aggregation_method: Optional[str],
        synonyms: List[str],
        source_sector: Optional[str],
        source_subdomain: Optional[str],
        source_line_of_business: Optional[str],
        source_status: str,
        is_active_sector: bool,
        embedding_model: Optional[str],
        kpi_type: str,
        valid_dimensions: List[str],
        enrichments: List[Dict[str, Any]],
        source_created_at: Optional[datetime],
        source_created_by: Optional[str],
        ontology_payload: Dict[str, Any],
        diagnostics: List[KPIValidationDiagnostic]
    ):
        self.kpi_code = kpi_code
        self.source_kpi_id = source_kpi_id
        self.kpi_name = kpi_name
        self.kpi_description = kpi_description
        self.business_domain = business_domain
        self.definition = definition
        self.formula = formula
        self.unit = unit
        self.aggregation_method = aggregation_method
        self.synonyms = synonyms
        self.source_sector = source_sector
        self.source_subdomain = source_subdomain
        self.source_line_of_business = source_line_of_business
        self.source_status = source_status
        self.is_active_sector = is_active_sector
        self.embedding_model = embedding_model
        self.kpi_type = kpi_type
        self.valid_dimensions = valid_dimensions
        self.enrichments = enrichments
        self.source_created_at = source_created_at
        self.source_created_by = source_created_by
        self.ontology_payload = ontology_payload
        self.diagnostics = diagnostics

    def to_record_dict(self, ontology_version_id: Optional[str] = None) -> Dict[str, Any]:
        """Convert to SQL-insertable record dictionary for kpi_ontology_entries."""
        return {
            "ontology_version_id": ontology_version_id,
            "kpi_code": self.kpi_code,
            "source_kpi_id": self.source_kpi_id,
            "kpi_name": self.kpi_name,
            "kpi_description": self.kpi_description,
            "business_domain": self.business_domain,
            "definition": self.definition,
            "formula": self.formula,
            "unit": self.unit,
            "aggregation_method": self.aggregation_method,
            "synonyms": json.dumps(self.synonyms),
            "source_sector": self.source_sector,
            "source_subdomain": self.source_subdomain,
            "source_line_of_business": self.source_line_of_business,
            "source_status": self.source_status,
            "valid_dimensions": json.dumps(self.valid_dimensions),
            "enrichments": json.dumps(self.enrichments),
            "source_created_at": self.source_created_at.isoformat() if self.source_created_at else None,
            "source_created_by": self.source_created_by,
            "ontology_payload": json.dumps(self.ontology_payload)
        }

    def compute_content_hash(self) -> str:
        """Deterministic hash of canonical business content for change detection."""
        hasher = hashlib.sha256()
        key_content = {
            "name": self.kpi_name,
            "definition": self.definition,
            "formula": self.formula,
            "aggregation_method": self.aggregation_method,
            "synonyms": sorted(self.synonyms),
            "valid_dimensions": sorted(self.valid_dimensions),
            "enrichments": self.enrichments,
            "status": self.source_status
        }
        hasher.update(json.dumps(key_content, sort_keys=True).encode("utf-8"))
        return hasher.hexdigest()


class KPIBankParseResult:
    def __init__(self):
        self.accepted_entries: List[NormalizedKPIEntry] = []
        self.quarantined_entries: List[Tuple[Dict[str, Any], List[KPIValidationDiagnostic]]] = []
        self.rejected_records: List[Tuple[Any, List[KPIValidationDiagnostic]]] = []
        self.diagnostics: List[KPIValidationDiagnostic] = []
        self.raw_content_hash: str = ""
        self.total_records_processed: int = 0

    @property
    def is_successful(self) -> bool:
        return len(self.rejected_records) == 0


class KPIBankParser:
    """Parser and validator for the KPI Ontology Bank."""

    def __init__(self, strict_mode: bool = False):
        self.strict_mode = strict_mode

    def parse_file(self, file_path: str) -> KPIBankParseResult:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return self.parse_json_string(content)

    def parse_json_string(self, json_str: str) -> KPIBankParseResult:
        result = KPIBankParseResult()
        result.raw_content_hash = hashlib.sha256(json_str.encode("utf-8")).hexdigest()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            diag = KPIValidationDiagnostic(
                record_id=None,
                json_path="$",
                error_code="ERR_MALFORMED_JSON",
                message=f"JSON decoding failed: {str(e)}",
                severity=DiagnosticSeverity.FATAL,
                action=DiagnosticAction.REJECTED
            )
            result.diagnostics.append(diag)
            result.rejected_records.append((json_str, [diag]))
            return result

        raw_list: List[Any] = []
        if isinstance(data, list):
            raw_list = data
        elif isinstance(data, dict):
            if "kpis" in data and isinstance(data["kpis"], list):
                raw_list = data["kpis"]
            else:
                # Single KPI record
                raw_list = [data]
        else:
            diag = KPIValidationDiagnostic(
                record_id=None,
                json_path="$",
                error_code="ERR_INVALID_ROOT_TYPE",
                message="Root JSON must be an array of KPI records or an object containing a 'kpis' array.",
                severity=DiagnosticSeverity.FATAL,
                action=DiagnosticAction.REJECTED
            )
            result.diagnostics.append(diag)
            result.rejected_records.append((data, [diag]))
            return result

        result.total_records_processed = len(raw_list)
        seen_ids: Set[str] = set()

        for idx, item in enumerate(raw_list):
            item_path = f"kpis[{idx}]"
            self._process_raw_entry(item, item_path, seen_ids, result)

        return result

    def _process_raw_entry(
        self,
        raw_entry: Any,
        item_path: str,
        seen_ids: Set[str],
        result: KPIBankParseResult
    ):
        diags: List[KPIValidationDiagnostic] = []

        if not isinstance(raw_entry, dict):
            diag = KPIValidationDiagnostic(
                record_id=None,
                json_path=item_path,
                error_code="ERR_RECORD_NOT_OBJECT",
                message=f"Record at {item_path} is of type {type(raw_entry).__name__}, expected JSON object.",
                severity=DiagnosticSeverity.ERROR,
                action=DiagnosticAction.REJECTED
            )
            result.diagnostics.append(diag)
            result.rejected_records.append((raw_entry, [diag]))
            return

        # 1. Identifier Validation (kpi_id)
        kpi_id = raw_entry.get("kpi_id")
        if not kpi_id or not isinstance(kpi_id, str) or not kpi_id.strip():
            diag = KPIValidationDiagnostic(
                record_id=None,
                json_path=f"{item_path}.kpi_id",
                error_code="ERR_MISSING_KPI_ID",
                message="Mandatory field 'kpi_id' is missing, null, or empty.",
                severity=DiagnosticSeverity.ERROR,
                action=DiagnosticAction.REJECTED
            )
            diags.append(diag)
            result.diagnostics.append(diag)
            result.rejected_records.append((raw_entry, diags))
            return

        kpi_id = kpi_id.strip()

        # Duplicate KPI ID check within import batch
        if kpi_id in seen_ids:
            diag = KPIValidationDiagnostic(
                record_id=kpi_id,
                json_path=f"{item_path}.kpi_id",
                error_code="ERR_DUPLICATE_KPI_ID",
                message=f"Duplicate kpi_id '{kpi_id}' encountered within the same import payload.",
                severity=DiagnosticSeverity.ERROR,
                action=DiagnosticAction.REJECTED
            )
            diags.append(diag)
            result.diagnostics.append(diag)
            result.rejected_records.append((raw_entry, diags))
            return
        seen_ids.add(kpi_id)

        # 2. Mandatory Name Validation
        name = raw_entry.get("name")
        if not name or not isinstance(name, str) or not name.strip():
            diag = KPIValidationDiagnostic(
                record_id=kpi_id,
                json_path=f"{item_path}.name",
                error_code="ERR_MISSING_NAME",
                message="Mandatory field 'name' is missing, null, or empty.",
                severity=DiagnosticSeverity.ERROR,
                action=DiagnosticAction.REJECTED
            )
            diags.append(diag)
            result.diagnostics.append(diag)
            result.rejected_records.append((raw_entry, diags))
            return
        name = name.strip()

        # 3. Mandatory Definition Validation
        definition = raw_entry.get("definition")
        if not definition or not isinstance(definition, str):
            diag = KPIValidationDiagnostic(
                record_id=kpi_id,
                json_path=f"{item_path}.definition",
                error_code="WARN_MISSING_DEFINITION",
                message="Field 'definition' is missing or not a string. Defaulting to name.",
                severity=DiagnosticSeverity.WARNING,
                action=DiagnosticAction.ACCEPTED_WITH_WARNING
            )
            diags.append(diag)
            definition = name
        else:
            definition = definition.strip()

        # 4. Domain & Taxonomy Preservation
        source_domain = raw_entry.get("domain", "Unclassified")
        if not isinstance(source_domain, str):
            source_domain = str(source_domain)
        source_domain = source_domain.strip()

        # Informational check: Is source domain outside the 6 application business domains?
        canonical_codes = set(APPLICATION_BUSINESS_DOMAINS.keys())
        canonical_names = {v.lower() for v in APPLICATION_BUSINESS_DOMAINS.values()}
        if source_domain.upper() not in canonical_codes and source_domain.lower() not in canonical_names:
            diag = KPIValidationDiagnostic(
                record_id=kpi_id,
                json_path=f"{item_path}.domain",
                error_code="INFO_SOURCE_DOMAIN_CROSSWALK_PENDING",
                message=f"Source domain '{source_domain}' is preserved natively; explicit crosswalk to canonical domains is pending.",
                severity=DiagnosticSeverity.INFO,
                action=DiagnosticAction.ACCEPTED
            )
            diags.append(diag)

        # 5. Timestamp Parsing & Validation
        raw_created_at = raw_entry.get("created_at")
        parsed_created_at: Optional[datetime] = None
        if raw_created_at is not None:
            if isinstance(raw_created_at, str):
                try:
                    # Clean potential trailing Z or microseconds
                    clean_ts = raw_created_at.replace("Z", "+00:00")
                    parsed_created_at = datetime.fromisoformat(clean_ts)
                except ValueError:
                    diag = KPIValidationDiagnostic(
                        record_id=kpi_id,
                        json_path=f"{item_path}.created_at",
                        error_code="WARN_INVALID_TIMESTAMP_FORMAT",
                        message=f"Value '{raw_created_at}' is not valid ISO-8601. Preserving in raw payload; canonical column set to NULL.",
                        severity=DiagnosticSeverity.WARNING,
                        action=DiagnosticAction.ACCEPTED_WITH_WARNING
                    )
                    diags.append(diag)
            else:
                diag = KPIValidationDiagnostic(
                    record_id=kpi_id,
                    json_path=f"{item_path}.created_at",
                    error_code="WARN_NON_STRING_TIMESTAMP",
                    message=f"Timestamp is of type {type(raw_created_at).__name__}. Canonical column set to NULL.",
                    severity=DiagnosticSeverity.WARNING,
                    action=DiagnosticAction.ACCEPTED_WITH_WARNING
                )
                diags.append(diag)

        # 6. Aliases / Synonyms Array Validation
        raw_aliases = raw_entry.get("aliases")
        valid_aliases: List[str] = []
        if raw_aliases is not None:
            if isinstance(raw_aliases, list):
                for a_idx, alias in enumerate(raw_aliases):
                    if isinstance(alias, str) and alias.strip():
                        valid_aliases.append(alias.strip())
                    else:
                        diag = KPIValidationDiagnostic(
                            record_id=kpi_id,
                            json_path=f"{item_path}.aliases[{a_idx}]",
                            error_code="WARN_NON_STRING_ALIAS",
                            message=f"Non-string alias '{alias}' ignored in normalized synonyms.",
                            severity=DiagnosticSeverity.WARNING,
                            action=DiagnosticAction.ACCEPTED_WITH_WARNING
                        )
                        diags.append(diag)
            else:
                diag = KPIValidationDiagnostic(
                    record_id=kpi_id,
                    json_path=f"{item_path}.aliases",
                    error_code="WARN_ALIASES_NOT_LIST",
                    message=f"Field 'aliases' is of type {type(raw_aliases).__name__}, expected list.",
                    severity=DiagnosticSeverity.WARNING,
                    action=DiagnosticAction.ACCEPTED_WITH_WARNING
                )
                diags.append(diag)

        # 7. Valid Dimensions Array Validation
        raw_dims = raw_entry.get("valid_dimensions")
        valid_dimensions: List[str] = []
        if raw_dims is not None:
            if isinstance(raw_dims, list):
                for d_idx, dim in enumerate(raw_dims):
                    if isinstance(dim, str) and dim.strip():
                        valid_dimensions.append(dim.strip())
            else:
                diag = KPIValidationDiagnostic(
                    record_id=kpi_id,
                    json_path=f"{item_path}.valid_dimensions",
                    error_code="WARN_DIMENSIONS_NOT_LIST",
                    message=f"Field 'valid_dimensions' is {type(raw_dims).__name__}, expected list.",
                    severity=DiagnosticSeverity.WARNING,
                    action=DiagnosticAction.ACCEPTED_WITH_WARNING
                )
                diags.append(diag)

        # 8. Enrichments Array & Provenance Validation
        raw_enrichments = raw_entry.get("enrichments")
        clean_enrichments: List[Dict[str, Any]] = []
        primary_formula: Optional[str] = None
        primary_desc: Optional[str] = None

        if raw_enrichments is not None:
            if isinstance(raw_enrichments, list):
                for e_idx, enrichment in enumerate(raw_enrichments):
                    e_path = f"{item_path}.enrichments[{e_idx}]"
                    if not isinstance(enrichment, dict):
                        diag = KPIValidationDiagnostic(
                            record_id=kpi_id,
                            json_path=e_path,
                            error_code="ERR_ENRICHMENT_NOT_OBJECT",
                            message=f"Enrichment item is of type {type(enrichment).__name__}, expected object.",
                            severity=DiagnosticSeverity.ERROR,
                            action=DiagnosticAction.QUARANTINED
                        )
                        diags.append(diag)
                        continue

                    clean_enrichments.append(enrichment)

                    # Extract primary calculation from first valid enrichment
                    if primary_formula is None and enrichment.get("calculation"):
                        calc = enrichment.get("calculation")
                        if isinstance(calc, str) and calc.strip():
                            primary_formula = calc.strip()

                    # Extract primary metric description
                    if primary_desc is None and enrichment.get("metric_description"):
                        desc = enrichment.get("metric_description")
                        if isinstance(desc, str) and desc.strip():
                            primary_desc = desc.strip()

                    # Inspect suspicious placeholders in field_sources
                    field_sources = enrichment.get("field_sources")
                    if isinstance(field_sources, dict):
                        for f_key, f_val in field_sources.items():
                            if isinstance(f_val, str) and f_val.lower().strip() in SUSPICIOUS_PLACEHOLDERS:
                                diag = KPIValidationDiagnostic(
                                    record_id=kpi_id,
                                    json_path=f"{e_path}.field_sources.{f_key}",
                                    error_code="WARN_SUSPICIOUS_FIELD_SOURCE_PLACEHOLDER",
                                    message=f"Suspicious placeholder value '{f_val}' in field_sources for key '{f_key}'. Preserved as-is.",
                                    severity=DiagnosticSeverity.WARNING,
                                    action=DiagnosticAction.ACCEPTED_WITH_WARNING
                                )
                                diags.append(diag)
            else:
                diag = KPIValidationDiagnostic(
                    record_id=kpi_id,
                    json_path=f"{item_path}.enrichments",
                    error_code="WARN_ENRICHMENTS_NOT_LIST",
                    message=f"Field 'enrichments' is of type {type(raw_enrichments).__name__}, expected list.",
                    severity=DiagnosticSeverity.WARNING,
                    action=DiagnosticAction.ACCEPTED_WITH_WARNING
                )
                diags.append(diag)

        # 9. Unit & Aggregation Method
        aggregation_type = raw_entry.get("aggregation_type")
        if aggregation_type and isinstance(aggregation_type, str):
            aggregation_method = aggregation_type.strip()
        else:
            aggregation_method = None

        # Derive unit if possible
        unit = None
        if aggregation_method == "PCT":
            unit = "PERCENTAGE"
        elif aggregation_method == "CURRENCY":
            unit = "CURRENCY"
        elif aggregation_method == "DAYS":
            unit = "DAYS"

        # Construct normalized entry
        kpi_code = f"KPI_{re.sub(r'[^A-Z0-9]+', '_', name.upper()).strip('_')}"
        if not kpi_code or kpi_code == "KPI_":
            kpi_code = f"KPI_{kpi_id[:8].upper()}"

        normalized_entry = NormalizedKPIEntry(
            kpi_code=kpi_code,
            source_kpi_id=kpi_id,
            kpi_name=name,
            kpi_description=primary_desc or definition,
            business_domain=source_domain,
            definition=definition,
            formula=primary_formula,
            unit=unit,
            aggregation_method=aggregation_method,
            synonyms=valid_aliases,
            source_sector=raw_entry.get("sector"),
            source_subdomain=raw_entry.get("subdomain"),
            source_line_of_business=raw_entry.get("line_of_business"),
            source_status=str(raw_entry.get("status", "active")),
            is_active_sector=bool(raw_entry.get("is_active_sector", True)),
            embedding_model=raw_entry.get("embedding_model"),
            kpi_type=str(raw_entry.get("kpi_type", "built-in")),
            valid_dimensions=valid_dimensions,
            enrichments=clean_enrichments,
            source_created_at=parsed_created_at,
            source_created_by=raw_entry.get("created_by"),
            ontology_payload=raw_entry,  # 100% complete lossless original dictionary
            diagnostics=diags
        )

        result.diagnostics.extend(diags)

        # Check quarantine vs accepted
        has_quarantine_error = any(d.action == DiagnosticAction.QUARANTINED for d in diags)
        if has_quarantine_error and self.strict_mode:
            result.quarantined_entries.append((raw_entry, diags))
        else:
            result.accepted_entries.append(normalized_entry)


class KPIVersionDiffDetector:
    """Detects semantic additions, modifications, and deprecations between two ontology releases."""

    @staticmethod
    def compare_releases(
        prior_entries: List[NormalizedKPIEntry],
        new_entries: List[NormalizedKPIEntry]
    ) -> Dict[str, Any]:
        prior_map = {e.source_kpi_id: e for e in prior_entries}
        new_map = {e.source_kpi_id: e for e in new_entries}

        added = []
        updated = []
        unchanged = []
        removed = []

        for kpi_id, new_e in new_map.items():
            if kpi_id not in prior_map:
                added.append(new_e)
            else:
                prior_e = prior_map[kpi_id]
                if prior_e.compute_content_hash() != new_e.compute_content_hash():
                    updated.append({
                        "kpi_id": kpi_id,
                        "name": new_e.kpi_name,
                        "prior_hash": prior_e.compute_content_hash(),
                        "new_hash": new_e.compute_content_hash(),
                        "changes": {
                            "definition_changed": prior_e.definition != new_e.definition,
                            "formula_changed": prior_e.formula != new_e.formula,
                            "status_changed": prior_e.source_status != new_e.source_status,
                            "aliases_changed": sorted(prior_e.synonyms) != sorted(new_e.synonyms)
                        }
                    })
                else:
                    unchanged.append(new_e)

        for kpi_id, prior_e in prior_map.items():
            if kpi_id not in new_map:
                removed.append(prior_e)

        return {
            "total_prior": len(prior_entries),
            "total_new": len(new_entries),
            "added_count": len(added),
            "updated_count": len(updated),
            "unchanged_count": len(unchanged),
            "removed_count": len(removed),
            "added": added,
            "updated": updated,
            "removed": removed
        }
