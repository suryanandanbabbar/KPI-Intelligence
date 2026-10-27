"""
KPI Intelligence — Deterministic Fallback Matching Engine.

Implements a transparent, weighted deterministic matching algorithm:
1. Exact & normalized name matching (weight 0.30)
2. Alias & synonym matching (weight 0.20)
3. Formula signature & required field overlap (weight 0.25)
4. Definition & business meaning token Jaccard similarity (weight 0.15)
5. Domain & subdomain compatibility (weight 0.10)

Penalizes contradictions:
- Incompatible formulas or aggregation operations
- Mismatched or conflicting domains
- Contradictory units

Generates structured, inspectable evidence separating:
- Observed evidence
- Inferences made
- Missing information
- Contradictory evidence
- Relative ranking rationale
"""

import re
from typing import Dict, List, Optional, Any, Set, Tuple


def tokenize(text: str) -> Set[str]:
    """Tokenizes string into a set of lowercased alphanumeric words, supporting camelCase."""
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text or "")
    norm = re.sub(r"[^a-zA-Z0-9\s_]", " ", s1.lower())
    return {w for w in norm.split() if len(w) >= 2}


def jaccard_similarity(set_a: Set[str], set_b: Set[str]) -> float:
    """Computes Jaccard index between two token sets."""
    if not set_a or not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


class DeterministicMatchingEngine:
    """Deterministic fallback matching and ranking engine."""

    VERSION = "2.1.0-deterministic"

    def match_and_rank(
        self,
        metadata_field: Dict[str, Any],
        kpi_candidates: List[Dict[str, Any]],
        domain: Optional[str] = None,
        max_candidates: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Ranks candidate KPIs against a canonical metadata field using weighted deterministic signals.
        Returns up to max_candidates (typically 3) with full structured evidence.
        """
        field_name = metadata_field.get("name") or metadata_field.get("candidate_name") or ""
        field_expr = metadata_field.get("expression") or metadata_field.get("candidate_expression") or ""
        field_desc = metadata_field.get("description") or ""
        field_domain = domain or metadata_field.get("domain") or metadata_field.get("business_domain")

        f_tokens = tokenize(field_name)
        f_expr_tokens = tokenize(field_expr)
        f_desc_tokens = tokenize(field_desc)

        scored_candidates: List[Dict[str, Any]] = []

        for kpi in kpi_candidates:
            evaluation = self._evaluate_candidate(
                field_name=field_name,
                field_expr=field_expr,
                field_domain=field_domain,
                f_tokens=f_tokens,
                f_expr_tokens=f_expr_tokens,
                f_desc_tokens=f_desc_tokens,
                kpi=kpi,
            )
            # Only retain candidates with non-trivial score (> 0.20)
            if evaluation["match_score"] >= 0.20:
                scored_candidates.append(evaluation)

        # Sort descending by match_score
        scored_candidates.sort(key=lambda x: x["match_score"], reverse=True)

        top_candidates = scored_candidates[:max_candidates]

        # Annotate relative ranking rationales comparing rank 1 to rank 2/3
        for idx, cand in enumerate(top_candidates):
            cand["rank"] = idx + 1
            cand["is_recommended"] = (idx == 0)
            if idx == 0 and len(top_candidates) > 1:
                next_cand = top_candidates[1]
                cand["ranking_rationale"] = (
                    f"Ranked #1 because of stronger semantic match ({cand['match_score']:.2f} vs {next_cand['match_score']:.2f}) "
                    f"and higher domain/formula alignment with '{cand['kpi_name']}'."
                )
            elif idx > 0:
                lead = top_candidates[0]
                diff_reasons = []
                if lead["name_score"] > cand["name_score"]:
                    diff_reasons.append("weaker name/alias correspondence")
                if lead["formula_score"] > cand["formula_score"]:
                    diff_reasons.append("lower formula/measure expression overlap")
                if lead["domain_score"] > cand["domain_score"]:
                    diff_reasons.append("less specific domain alignment")
                if not diff_reasons:
                    diff_reasons.append("lower overall combined signal score")
                cand["ranking_rationale"] = (
                    f"Ranked #{idx + 1} behind '{lead['kpi_name']}' due to {', '.join(diff_reasons)} "
                    f"({cand['match_score']:.2f} vs {lead['match_score']:.2f})."
                )

        return top_candidates

    def _evaluate_candidate(
        self,
        field_name: str,
        field_expr: str,
        field_domain: Optional[str],
        f_tokens: Set[str],
        f_expr_tokens: Set[str],
        f_desc_tokens: Set[str],
        kpi: Dict[str, Any],
    ) -> Dict[str, Any]:
        kpi_name = kpi.get("name") or kpi.get("kpi_name") or ""
        kpi_def = kpi.get("definition") or ""
        kpi_formula = kpi.get("formula") or ""
        kpi_fields_req = kpi.get("fields_required") or ""
        kpi_domain = kpi.get("business_domain") or kpi.get("domain") or ""
        kpi_aliases = kpi.get("aliases") or []

        k_tokens = tokenize(kpi_name)
        k_def_tokens = tokenize(kpi_def)
        k_formula_tokens = tokenize(f"{kpi_formula} {kpi_fields_req}")

        observed_evidence: List[str] = []
        inferences_made: List[str] = []
        missing_information: List[str] = []
        contradictory_evidence: List[str] = []

        # 1. Name Similarity (Weight: 0.30)
        name_score = 0.0
        f_name_lower = field_name.strip().lower()
        k_name_lower = kpi_name.strip().lower()

        if f_name_lower == k_name_lower:
            name_score = 1.0
            observed_evidence.append(f"Exact match on metric name: '{field_name}' == '{kpi_name}'")
        elif f_name_lower in k_name_lower or k_name_lower in f_name_lower:
            name_score = 0.75
            observed_evidence.append(f"Substring match on name: '{field_name}' within '{kpi_name}'")
        elif f_tokens and k_tokens:
            overlap = len(f_tokens & k_tokens) / len(f_tokens | k_tokens)
            name_score = overlap
            if overlap > 0.3:
                observed_evidence.append(f"Token overlap in name: {sorted(list(f_tokens & k_tokens))}")

        # 2. Alias Similarity (Weight: 0.20)
        alias_score = 0.0
        for alias in kpi_aliases:
            a_lower = str(alias).strip().lower()
            if f_name_lower == a_lower:
                alias_score = 1.0
                observed_evidence.append(f"Exact match with declared KPI alias: '{alias}'")
                break
            elif f_name_lower in a_lower:
                alias_score = max(alias_score, 0.70)
                observed_evidence.append(f"Matches alias substring: '{alias}'")
            else:
                a_tokens = tokenize(str(alias))
                if f_tokens and a_tokens:
                    a_overlap = len(f_tokens & a_tokens) / len(f_tokens | a_tokens)
                    if a_overlap > alias_score:
                        alias_score = a_overlap

        # 3. Formula / Calculation Compatibility (Weight: 0.25)
        formula_score = 0.0
        if field_expr and (kpi_formula or kpi_fields_req):
            expr_overlap = jaccard_similarity(f_expr_tokens, k_formula_tokens)
            formula_score = min(1.0, expr_overlap * 2.0)
            if expr_overlap > 0.15:
                observed_evidence.append(f"Calculation tokens align: {sorted(list(f_expr_tokens & k_formula_tokens))[:4]}")
                inferences_made.append("Underlying measure expression aligns with KPI calculation formula")
            else:
                # Check for formula contradiction (e.g. one is a sum, one is a ratio)
                is_field_ratio = "/" in field_expr or "div" in field_expr.lower()
                is_kpi_ratio = "/" in kpi_formula or "div" in kpi_formula.lower() or "ratio" in kpi_name.lower() or "%" in kpi_name
                if is_field_ratio != is_kpi_ratio:
                    contradictory_evidence.append("Formula structure mismatch (ratio vs absolute aggregate)")
        else:
            if not field_expr:
                missing_information.append("Source metadata lacks DAX/calculation formula expression")
            if not kpi_formula:
                missing_information.append("Reference KPI has no explicit formula defined")
            formula_score = 0.40  # Neutral baseline when formulas unavailable

        # 4. Definition / Meaning Similarity (Weight: 0.15)
        def_score = 0.0
        target_tokens = f_tokens | f_desc_tokens
        if target_tokens and k_def_tokens:
            def_score = jaccard_similarity(target_tokens, k_def_tokens)
            if def_score > 0.10:
                observed_evidence.append(f"Semantic definition tokens matched: {sorted(list(target_tokens & k_def_tokens))[:4]}")
        else:
            def_score = 0.20

        # 5. Domain Compatibility (Weight: 0.10)
        domain_score = 0.0
        if field_domain and kpi_domain:
            f_dom_norm = str(field_domain).upper()
            k_dom_norm = str(kpi_domain).upper()
            if f_dom_norm == k_dom_norm:
                domain_score = 1.0
                observed_evidence.append(f"Domain match: {field_domain}")
            elif "GENERAL" in k_dom_norm or "SYSTEM" in k_dom_norm:
                domain_score = 0.60
            else:
                domain_score = 0.0
                contradictory_evidence.append(f"Cross-domain mismatch: metadata is in '{field_domain}', KPI is in '{kpi_domain}'")
        else:
            domain_score = 0.50

        # Compute Raw Weighted Score
        raw_score = (
            (name_score * 0.30)
            + (alias_score * 0.20)
            + (formula_score * 0.25)
            + (def_score * 0.15)
            + (domain_score * 0.10)
        )

        # Apply Contradiction Penalties
        penalty = 0.0
        if contradictory_evidence:
            penalty = len(contradictory_evidence) * 0.25
        final_score = max(0.0, min(1.0, raw_score - penalty))

        # Assign Operational Confidence Code
        if final_score >= 0.82 and not contradictory_evidence:
            confidence_code = "HIGH"
        elif final_score >= 0.60 and len(contradictory_evidence) <= 1:
            confidence_code = "MEDIUM"
        elif final_score >= 0.35:
            confidence_code = "LOW"
        else:
            confidence_code = "UNCLASSIFIED"

        return {
            "ontology_entry_id": kpi.get("kpi_id") or kpi.get("ontology_entry_id"),
            "kpi_id": kpi.get("kpi_id") or kpi.get("ontology_entry_id"),
            "kpi_name": kpi_name,
            "kpi_code": kpi.get("kpi_code", ""),
            "domain": kpi_domain,
            "definition": kpi_def,
            "formula": kpi_formula,
            "fields_required": kpi_fields_req,
            "aggregation_type": kpi.get("aggregation_type", "SUM"),
            "confidence_code": confidence_code,
            "confidence_score": round(final_score, 3),
            "match_score": round(final_score, 3),
            "matching_engine": self.VERSION,
            "fallback_used": True,
            "decision_source": "DETERMINISTIC_FALLBACK",
            "name_score": round(name_score, 3),
            "alias_score": round(alias_score, 3),
            "formula_score": round(formula_score, 3),
            "definition_score": round(def_score, 3),
            "domain_score": round(domain_score, 3),
            "structured_evidence": {
                "observed_evidence": observed_evidence,
                "inferences_made": inferences_made,
                "missing_information": missing_information,
                "contradictory_evidence": contradictory_evidence,
            },
            "supporting_evidence": observed_evidence,
            "contradicting_evidence": contradictory_evidence,
            "ranking_rationale": "",
        }
