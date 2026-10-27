"""
KPI Intelligence — Deterministic Metadata Fingerprinting.

Computes:
1. Stable Source Fingerprint (Level 2):
   Based on stable source platform, asset identity, object type, and canonical object path.
2. Semantic Field Fingerprint (Level 3):
   Based on normalized field name, formula signature, data type, table context, and business domain.
"""

import hashlib
import re
from typing import Dict, Any, Optional


def normalize_expression(expr: Optional[str]) -> str:
    """Normalizes a calculation or DAX expression to extract canonical structure."""
    if not expr:
        return ""
    # Strip whitespace, comments, case
    clean = re.sub(r"--.*$", "", expr, flags=re.MULTILINE)
    clean = re.sub(r"//.*$", "", clean, flags=re.MULTILINE)
    clean = re.sub(r"\s+", " ", clean).strip().lower()
    return clean


def compute_source_fingerprint(
    platform: str,
    asset_id: str,
    entity_type: str,
    entity_name: str,
    source_native_id: Optional[str] = None,
) -> str:
    """
    Computes a deterministic hash representing the stable source identity.
    """
    p_norm = (platform or "POWER_BI").upper().strip()
    a_norm = (asset_id or "").strip()
    t_norm = (entity_type or "MEASURE").upper().strip()
    n_norm = (entity_name or "").strip().lower()
    s_norm = (source_native_id or "").strip()

    raw = f"{p_norm}|{a_norm}|{t_norm}|{n_norm}|{s_norm}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def compute_semantic_fingerprint(
    field_name: str,
    expression: Optional[str] = None,
    data_type: Optional[str] = None,
    table_name: Optional[str] = None,
    domain: Optional[str] = None,
) -> str:
    """
    Computes a normalized semantic field fingerprint for renamed/recreated entities.
    """
    # Name normalized
    name_norm = re.sub(r"[^a-zA-Z0-9]", "", (field_name or "").lower())
    # Expression structure
    expr_norm = normalize_expression(expression)
    expr_hash = hashlib.sha256(expr_norm.encode("utf-8")).hexdigest()[:12] if expr_norm else "no_expr"
    # Table & Data Type
    tbl_norm = (table_name or "").strip().lower()
    dtype_norm = (data_type or "DECIMAL").strip().upper()
    dom_norm = (domain or "GENERAL").strip().upper()

    raw = f"{name_norm}|{expr_hash}|{tbl_norm}|{dtype_norm}|{dom_norm}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
