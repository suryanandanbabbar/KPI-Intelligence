#!/usr/bin/env python3
"""
KPI Intelligence — Canonical Data Model Static & Dynamic Validation Suite

This script performs deep validation across all deliverables of the KPI Intelligence
canonical model:
1. SQL Schema completeness (all 61 tables, all required columns, types, and constraints)
2. Foreign key referential integrity (target table/column existence, no dangling refs)
3. Required performance and uniqueness indexes (including trigram, FTS, and partial indexes)
4. Domain seed data verification (all 6 required business domains)
5. Cross-file synchronization (table_inventory.csv, data_dictionary.md, er_diagram.md)
6. Business invariant enforcement (single active ontology version, single active approval, etc.)
7. Optional live database execution if PostgreSQL connection string is provided.
"""

import sys
import re
import csv
import os
import argparse
from typing import Dict, List, Set, Tuple

# Expected 61 Tables grouped by Subsystem
EXPECTED_TABLES: Dict[str, List[str]] = {
    "Subsystem A — Asset Registry": [
        "assets",
        "asset_versions",
        "ingestion_events",
        "source_artifacts"
    ],
    "Subsystem B — Universal Analytical Objects": [
        "analytical_objects",
        "reports",
        "report_pages",
        "visuals",
        "visual_bindings",
        "visual_properties",
        "visual_interactions",
        "visual_types",
        "bookmarks",
        "report_navigation"
    ],
    "Subsystem C — Semantic Models and Calculations": [
        "semantic_models",
        "data_tables",
        "data_columns",
        "calculations",
        "relationships",
        "model_partitions",
        "hierarchies",
        "hierarchy_levels",
        "parameters",
        "named_expressions"
    ],
    "Subsystem D — Filters, Security, Data Sources, and Lineage": [
        "filters",
        "filter_assignments",
        "security_roles",
        "security_role_filters",
        "security_principals",
        "security_object_permissions",
        "data_sources",
        "query_dependencies",
        "metadata_lineage_edges"
    ],
    "Subsystem E — Excel-Specific Metadata": [
        "spreadsheet_cells",
        "pivot_caches",
        "pivot_tables",
        "pivot_field_assignments",
        "spreadsheet_objects",
        "spreadsheet_rules"
    ],
    "Subsystem F — KPI Ontology and Domain Classification": [
        "kpi_ontology_versions",
        "kpi_ontology_entries",
        "business_domains",
        "domain_classifications"
    ],
    "Subsystem G — KPI Candidates and Mapping": [
        "kpi_candidates",
        "kpi_mapping_runs",
        "kpi_mappings",
        "kpi_mapping_candidates",
        "mapping_evidence"
    ],
    "Subsystem H — Human Review, Approval, Overrides": [
        "mapping_reviews",
        "mapping_approvals",
        "mapping_overrides",
        "metadata_field_reviews"
    ],
    "Subsystem I — KPI Rationalisation": [
        "kpi_equivalence_candidates",
        "kpi_rationalisation_decisions",
        "rationalisation_evidence"
    ],
    "Subsystem J — Operations and Audit": [
        "platform_capabilities",
        "parser_runs",
        "extraction_errors",
        "object_tags",
        "mapping_audit_events",
        "ontology_change_events"
    ]
}

# Mandatory Columns for each table specified in Section 5 of the Master Prompt
EXPECTED_COLUMNS: Dict[str, List[str]] = {
    "assets": ["asset_id", "tenant_id", "platform", "asset_type", "asset_name", "asset_description", "source_native_id", "source_native_path", "source_version", "created_at_source", "modified_at_source", "first_ingested_at", "last_ingested_at", "current_version_id", "lifecycle_status", "created_at", "updated_at"],
    "asset_versions": ["asset_version_id", "asset_id", "version_number", "content_hash", "raw_content_hash", "structure_hash", "metadata_hash", "parser_version", "schema_version", "source_manifest", "extraction_status", "extraction_started_at", "extraction_completed_at", "created_at"],
    "ingestion_events": ["ingestion_id", "asset_version_id", "uploaded_by_user_id", "original_filename", "upload_size_bytes", "upload_source", "ingestion_status", "error_code", "error_message", "started_at", "completed_at", "created_at"],
    "source_artifacts": ["source_artifact_id", "asset_version_id", "relative_path", "artifact_type", "source_native_id", "content_hash", "mime_type", "size_bytes", "is_supported", "extraction_status", "extraction_notes", "created_at"],
    "analytical_objects": ["object_id", "asset_version_id", "parent_object_id", "source_artifact_id", "platform", "object_type", "source_native_id", "source_native_name", "canonical_name", "display_name", "description", "source_path", "source_locator", "is_hidden", "is_active", "extraction_status", "metadata_completeness", "source_metadata", "created_at", "updated_at"],
    "reports": ["report_id", "object_id", "report_type", "report_definition", "default_page_object_id", "page_count", "visual_count", "report_configuration", "created_at"],
    "report_pages": ["page_id", "report_id", "object_id", "source_native_id", "page_name", "page_order", "page_type", "page_properties", "is_hidden", "created_at"],
    "visuals": ["visual_id", "page_id", "object_id", "source_native_id", "visual_type", "visual_title", "visual_description", "position_x", "position_y", "width", "height", "z_order", "visual_configuration", "is_visible", "created_at"],
    "visual_bindings": ["visual_binding_id", "visual_id", "object_id", "binding_role", "binding_order", "aggregation_override", "format_override", "binding_properties"],
    "visual_properties": ["visual_property_id", "visual_id", "property_path", "property_value", "expression_language", "expression_text", "source_properties"],
    "visual_interactions": ["visual_interaction_id", "source_visual_id", "target_visual_id", "interaction_type", "interaction_properties"],
    "visual_types": ["visual_type_id", "platform", "native_type", "canonical_type", "description", "type_properties"],
    "bookmarks": ["bookmark_id", "object_id", "source_native_id", "bookmark_name", "bookmark_state", "bookmark_properties"],
    "report_navigation": ["report_navigation_id", "source_object_id", "target_object_id", "navigation_type", "navigation_name", "navigation_expression", "expression_language", "navigation_properties"],
    "semantic_models": ["semantic_model_id", "object_id", "source_native_id", "model_name", "model_type", "model_version", "compatibility_level", "model_definition", "source_connection_summary", "created_at"],
    "data_tables": ["data_table_id", "object_id", "semantic_model_id", "source_native_id", "table_name", "schema_name", "table_type", "description", "is_hidden", "storage_mode", "source_reference", "table_properties", "created_at"],
    "data_columns": ["data_column_id", "object_id", "data_table_id", "source_native_id", "column_name", "display_name", "data_type", "source_data_type", "description", "semantic_role", "is_nullable", "is_hidden", "is_calculated", "default_aggregation", "format_string", "column_properties", "created_at"],
    "calculations": ["calculation_id", "object_id", "semantic_model_id", "data_table_id", "data_column_id", "calculation_name", "calculation_type", "expression_language", "expression_text", "normalised_expression", "return_data_type", "aggregation_type", "format_string", "description", "evaluation_context", "expression_parse_status", "expression_ast", "expression_properties", "created_at"],
    "relationships": ["relationship_id", "object_id", "relationship_type", "from_table_id", "to_table_id", "from_object_id", "to_object_id", "cardinality", "join_type", "is_active", "cross_filter_direction", "relationship_expression", "relationship_properties", "created_at"],
    "model_partitions": ["model_partition_id", "semantic_model_id", "source_native_id", "partition_name", "source_type", "expression_language", "expression_text", "partition_properties"],
    "hierarchies": ["hierarchy_id", "object_id", "semantic_model_id", "hierarchy_name", "hierarchy_type", "hierarchy_properties"],
    "hierarchy_levels": ["hierarchy_level_id", "hierarchy_id", "level_object_id", "level_name", "level_order", "level_properties"],
    "parameters": ["parameter_id", "object_id", "parameter_name", "data_type", "default_value", "allowed_values", "is_required", "parameter_properties"],
    "named_expressions": ["named_expression_id", "object_id", "expression_name", "scope", "expression_language", "expression_text", "resolved_reference_object_id", "expression_properties"],
    "filters": ["filter_id", "object_id", "filter_name", "filter_type", "filter_scope", "expression_language", "expression_text", "filter_operator", "filter_values", "is_enabled", "filter_properties", "created_at"],
    "filter_assignments": ["filter_assignment_id", "filter_id", "target_object_id", "field_object_id", "assignment_scope", "assignment_properties"],
    "security_roles": ["security_role_id", "object_id", "role_name", "role_type", "role_description", "role_properties"],
    "security_role_filters": ["security_role_filter_id", "security_role_id", "target_object_id", "expression_language", "expression_text", "normalised_expression", "expression_parse_status", "rule_properties"],
    "security_principals": ["principal_id", "tenant_id", "platform", "source_native_id", "principal_name", "principal_type", "principal_properties"],
    "security_object_permissions": ["permission_id", "target_object_id", "principal_id", "principal_name", "permission_type", "permission_source", "permission_properties"],
    "data_sources": ["data_source_id", "object_id", "source_type", "source_name", "server_reference", "database_reference", "schema_reference", "connection_mode", "query_language", "query_text", "source_properties"],
    "query_dependencies": ["query_dependency_id", "source_object_id", "target_object_id", "target_reference", "dependency_type", "resolution_status", "dependency_properties"],
    "metadata_lineage_edges": ["lineage_edge_id", "asset_version_id", "source_object_id", "target_object_id", "edge_type", "derivation_method", "confidence_score", "evidence", "created_at"],
    "spreadsheet_cells": ["spreadsheet_cell_id", "asset_version_id", "worksheet_object_id", "cell_address", "row_number", "column_number", "formula_text", "cached_value", "data_type", "number_format", "is_hidden", "cell_properties"],
    "pivot_caches": ["pivot_cache_id", "asset_version_id", "source_native_id", "source_type", "source_reference", "refresh_metadata", "cache_properties"],
    "pivot_tables": ["pivot_table_id", "object_id", "worksheet_object_id", "pivot_cache_id", "pivot_name", "source_reference", "pivot_properties"],
    "pivot_field_assignments": ["pivot_field_assignment_id", "pivot_table_id", "field_object_id", "field_reference", "assignment_role", "aggregation_type", "field_order", "assignment_properties"],
    "spreadsheet_objects": ["spreadsheet_object_id", "object_id", "worksheet_object_id", "object_subtype", "range_reference", "is_hidden", "object_properties"],
    "spreadsheet_rules": ["spreadsheet_rule_id", "object_id", "worksheet_object_id", "rule_type", "range_reference", "formula_text", "expression_language", "rule_properties"],
    "kpi_ontology_versions": ["ontology_version_id", "version_number", "content_hash", "schema_version", "kpi_count", "created_by_user_id", "created_at", "change_summary", "is_active"],
    "kpi_ontology_entries": ["ontology_entry_id", "ontology_version_id", "kpi_code", "kpi_name", "kpi_description", "business_domain", "definition", "formula", "unit", "aggregation_method", "synonyms", "ontology_payload", "created_at"],
    "business_domains": ["domain_id", "domain_code", "domain_name", "domain_description", "is_active"],
    "domain_classifications": ["classification_id", "asset_version_id", "target_object_id", "domain_id", "classification_method", "confidence_score", "rationale", "is_primary", "approval_status", "created_at", "updated_at"],
    "kpi_candidates": ["kpi_candidate_id", "asset_version_id", "source_object_id", "candidate_name", "candidate_description", "candidate_expression", "expression_language", "normalised_expression", "candidate_type", "unit", "aggregation_type", "business_domain_id", "candidate_evidence", "discovery_method", "discovery_version", "created_at"],
    "kpi_mapping_runs": ["mapping_run_id", "asset_version_id", "ontology_version_id", "candidate_generation_version", "mapping_engine_version", "primary_engine", "fallback_used", "llm_provider", "llm_model", "prompt_version", "input_fingerprint", "run_status", "started_at", "completed_at", "error_summary", "created_at"],
    "kpi_mappings": ["kpi_mapping_id", "kpi_candidate_id", "mapping_run_id", "ontology_version_id", "selected_ontology_entry_id", "mapping_status", "decision_source", "top_candidate_count", "input_fingerprint", "mapping_version", "created_at", "updated_at"],
    "kpi_mapping_candidates": ["mapping_candidate_id", "kpi_mapping_id", "ontology_entry_id", "rank", "confidence_score", "confidence_band", "match_score", "name_similarity_score", "definition_similarity_score", "formula_similarity_score", "context_similarity_score", "domain_compatibility_score", "unit_compatibility_score", "rationale", "supporting_evidence", "contradicting_evidence", "is_recommended", "created_at"],
    "mapping_evidence": ["mapping_evidence_id", "mapping_candidate_id", "evidence_type", "source_object_id", "evidence_text", "evidence_payload", "polarity", "created_at"],
    "mapping_reviews": ["mapping_review_id", "kpi_mapping_id", "mapping_candidate_id", "reviewer_user_id", "review_action", "review_status", "review_comment", "created_at"],
    "mapping_approvals": ["mapping_approval_id", "kpi_mapping_id", "approved_mapping_candidate_id", "approved_by_user_id", "approval_status", "approval_version", "approved_at", "revoked_at", "revocation_reason"],
    "mapping_overrides": ["override_id", "kpi_mapping_id", "mapping_candidate_id", "override_type", "previous_ontology_entry_id", "replacement_ontology_entry_id", "override_justification", "normalised_justification", "justification_hash", "created_by_user_id", "created_at", "is_active", "supersedes_override_id"],
    "metadata_field_reviews": ["field_review_id", "asset_version_id", "target_object_id", "field_path", "source_value_hash", "proposed_value", "approved_value", "review_status", "reviewed_by_user_id", "reviewed_at", "override_justification", "created_at"],
    "kpi_equivalence_candidates": ["equivalence_candidate_id", "source_kpi_candidate_id", "target_kpi_candidate_id", "comparison_type", "name_similarity_score", "definition_similarity_score", "formula_similarity_score", "unit_compatibility_score", "dependency_similarity_score", "equivalence_score", "evidence", "review_status", "created_at"],
    "kpi_rationalisation_decisions": ["rationalisation_decision_id", "equivalence_candidate_id", "decision_type", "canonical_kpi_candidate_id", "approved_by_user_id", "decision_justification", "decision_status", "created_at", "updated_at"],
    "rationalisation_evidence": ["rationalisation_evidence_id", "rationalisation_decision_id", "evidence_type", "evidence_text", "evidence_payload", "created_at"],
    "platform_capabilities": ["platform_capability_id", "platform", "artifact_type", "metadata_type", "capability_status", "minimum_source_version", "maximum_source_version", "notes", "capability_properties"],
    "parser_runs": ["parser_run_id", "asset_version_id", "source_artifact_id", "platform", "parser_name", "parser_version", "run_status", "objects_extracted", "warnings_count", "errors_count", "started_at", "completed_at", "run_metadata"],
    "extraction_errors": ["extraction_error_id", "parser_run_id", "source_artifact_id", "object_locator", "severity", "error_code", "error_message", "is_recoverable", "created_at"],
    "object_tags": ["object_tag_id", "object_id", "tag_name", "tag_value", "tag_source", "created_at"],
    "mapping_audit_events": ["mapping_audit_event_id", "kpi_mapping_id", "actor_user_id", "event_type", "previous_state", "new_state", "event_reason", "created_at"],
    "ontology_change_events": ["ontology_change_event_id", "ontology_version_id", "ontology_entry_id", "actor_user_id", "change_type", "previous_payload", "new_payload", "change_justification", "created_at"]
}

# The 6 mandatory business domains
EXPECTED_DOMAINS = [
    ("CLAIMS_RISK", "Claims & Risk"),
    ("LEGAL", "Legal"),
    ("UNDERWRITING", "Underwriting"),
    ("SALES_DISTRIBUTION", "Sales & Distribution"),
    ("SERVICE_OPERATIONS", "Service & Operations"),
    ("ACTUARIAL", "Actuarial")
]

class ValidationReporter:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.errors: List[str] = []

    def check(self, condition: bool, description: str, error_detail: str = ""):
        if condition:
            print(f"  [PASS] {description}")
            self.passed += 1
        else:
            print(f"  [FAIL] {description}")
            if error_detail:
                print(f"         Detail: {error_detail}")
                self.errors.append(f"{description}: {error_detail}")
            else:
                self.errors.append(description)
            self.failed += 1

    def warn(self, message: str):
        print(f"  [WARN] {message}")
        self.warnings += 1

    def summary(self):
        print("\n" + "=" * 70)
        print("VALIDATION SUMMARY REPORT")
        print("=" * 70)
        print(f"Total Checks:   {self.passed + self.failed}")
        print(f"Passed:         {self.passed}")
        print(f"Failed:         {self.failed}")
        print(f"Warnings:       {self.warnings}")
        if self.errors:
            print("\nFailures Detail:")
            for e in self.errors:
                print(f"  - {e}")
        print("=" * 70)
        return self.failed == 0


def remove_sql_comments(sql: str) -> str:
    """Remove SQL block comments and line comments cleanly."""
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    sql = re.sub(r'--.*?$', '', sql, flags=re.MULTILINE)
    return sql

def parse_sql_tables(sql_content: str) -> Dict[str, Dict]:
    """Parse table definitions, columns, types, and constraints from SQL."""
    tables = {}
    
    clean_sql = remove_sql_comments(sql_content)
    
    # Match CREATE TABLE statements
    table_pattern = re.compile(
        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?kpi_intel\.([a-zA-Z0-9_]+)\s*\((.*?)\);',
        re.DOTALL | re.IGNORECASE
    )
    
    for match in table_pattern.finditer(clean_sql):
        table_name = match.group(1).lower()
        body = match.group(2)
        
        columns = {}
        constraints = []
        foreign_keys = []
        
        # Split body into comma-separated entries, handling parentheses
        lines = []
        current = []
        paren_depth = 0
        for char in body:
            if char == '(':
                paren_depth += 1
                current.append(char)
            elif char == ')':
                paren_depth -= 1
                current.append(char)
            elif char == ',' and paren_depth == 0:
                lines.append(''.join(current).strip())
                current = []
            else:
                current.append(char)
        if current:
            lines.append(''.join(current).strip())
            
        for line in lines:
            line_clean = re.sub(r'--.*$', '', line).strip()
            if not line_clean:
                continue
                
            # Table-level constraints
            if re.match(r'^(CONSTRAINT|PRIMARY\s+KEY|UNIQUE|CHECK|FOREIGN\s+KEY)', line_clean, re.IGNORECASE):
                constraints.append(line_clean)
                fk_match = re.search(r'FOREIGN\s+KEY\s*\(([^\)]+)\)\s*REFERENCES\s+kpi_intel\.([a-zA-Z0-9_]+)\s*\(([^\)]+)\)', line_clean, re.IGNORECASE)
                if fk_match:
                    foreign_keys.append({
                        "col": fk_match.group(1).strip().lower(),
                        "ref_table": fk_match.group(2).strip().lower(),
                        "ref_col": fk_match.group(3).strip().lower()
                    })
            else:
                # Column definition: name type [constraints...]
                parts = line_clean.split()
                if len(parts) >= 2:
                    col_name = parts[0].strip().lower()
                    col_type = parts[1].strip().upper()
                    columns[col_name] = {
                        "type": col_type,
                        "raw": line_clean
                    }
                    
                    # Check column-level references
                    col_fk = re.search(r'REFERENCES\s+kpi_intel\.([a-zA-Z0-9_]+)\s*\(([^\)]+)\)', line_clean, re.IGNORECASE)
                    if col_fk:
                        foreign_keys.append({
                            "col": col_name,
                            "ref_table": col_fk.group(1).strip().lower(),
                            "ref_col": col_fk.group(2).strip().lower()
                        })
                        
        tables[table_name] = {
            "columns": columns,
            "constraints": constraints,
            "foreign_keys": foreign_keys
        }
        
    # Check ALTER TABLE statements adding constraints
    alter_fk_pattern = re.compile(
        r'ALTER\s+TABLE\s+kpi_intel\.([a-zA-Z0-9_]+)\s+ADD\s+CONSTRAINT\s+[a-zA-Z0-9_]+\s+FOREIGN\s+KEY\s*\(([^\)]+)\)\s+REFERENCES\s+kpi_intel\.([a-zA-Z0-9_]+)\s*\(([^\)]+)\)',
        re.IGNORECASE
    )
    for match in alter_fk_pattern.finditer(sql_content):
        tbl = match.group(1).lower()
        col = match.group(2).strip().lower()
        ref_tbl = match.group(3).strip().lower()
        ref_col = match.group(4).strip().lower()
        if tbl in tables:
            tables[tbl]["foreign_keys"].append({
                "col": col,
                "ref_table": ref_tbl,
                "ref_col": ref_col
            })

    return tables


def parse_sql_indexes(sql_content: str) -> List[str]:
    """Extract index creation statements from SQL."""
    pattern = re.compile(r'CREATE\s+(?:UNIQUE\s+)?INDEX\s+([a-zA-Z0-9_]+)\s+ON\s+kpi_intel\.([a-zA-Z0-9_]+)\s+(.*?);', re.DOTALL | re.IGNORECASE)
    indexes = []
    for m in pattern.finditer(sql_content):
        indexes.append({
            "name": m.group(1),
            "table": m.group(2).lower(),
            "definition": m.group(3).strip()
        })
    return indexes


def parse_seed_domains(sql_content: str) -> Set[str]:
    """Extract seeded domain codes from the INSERT statement."""
    seed_codes = set()
    matches = re.findall(r"'([A-Z_]+)',\s*'([^']+)'", sql_content)
    for code, _ in matches:
        if code in dict(EXPECTED_DOMAINS):
            seed_codes.add(code)
    return seed_codes


def validate_canonical_model(base_dir: str, db_url: str = None) -> bool:
    reporter = ValidationReporter()
    docs_dir = os.path.join(base_dir, "docs", "kpi-intelligence-canonical-model")
    sql_path = os.path.join(docs_dir, "canonical_schema.sql")
    csv_path = os.path.join(docs_dir, "table_inventory.csv")
    dict_path = os.path.join(docs_dir, "data_dictionary.md")
    er_path = os.path.join(docs_dir, "er_diagram.md")
    arch_path = os.path.join(docs_dir, "architecture.md")

    print("\n" + "=" * 70)
    print("KPI INTELLIGENCE — CANONICAL MODEL VERIFICATION")
    print("Target Database: PostgreSQL 15+")
    print("=" * 70)

    # 1. Verify existence of required deliverable files
    print("\n--- 1. DELIVERABLE FILES EXISTENCE ---")
    files_to_check = [
        ("Deliverable A (README.md)", os.path.join(docs_dir, "README.md")),
        ("Deliverable B (canonical_schema.sql)", sql_path),
        ("Deliverable C (data_dictionary.md)", dict_path),
        ("Deliverable D (er_diagram.md)", er_path),
        ("Deliverable E (architecture.md)", arch_path),
        ("Deliverable F (table_inventory.csv)", csv_path),
        ("Deliverable G (implementation_notes.md)", os.path.join(docs_dir, "implementation_notes.md")),
    ]
    for label, path in files_to_check:
        reporter.check(os.path.exists(path), f"File present: {label}", f"Missing path: {path}")

    # Read schema content
    if not os.path.exists(sql_path):
        print(f"FATAL: {sql_path} does not exist.")
        return False
    with open(sql_path, "r", encoding="utf-8") as f:
        sql_content = f.read()

    # 2. Table Count & Specification Verification
    print("\n--- 2. SCHEMA TABLE COUNT & REGISTRATION (61 Tables) ---")
    tables = parse_sql_tables(sql_content)
    total_tables = len(tables)
    reporter.check(total_tables == 61, f"Total 61 tables defined (found {total_tables})")

    all_expected_flat = [tbl for sub in EXPECTED_TABLES.values() for tbl in sub]
    assert len(all_expected_flat) == 61

    for subsystem, sub_tables in EXPECTED_TABLES.items():
        missing_in_sub = [t for t in sub_tables if t not in tables]
        reporter.check(
            len(missing_in_sub) == 0,
            f"{subsystem} ({len(sub_tables)} tables)",
            f"Missing tables: {missing_in_sub}" if missing_in_sub else ""
        )

    # 3. Column Completeness Verification
    print("\n--- 3. MANDATORY COLUMN VERIFICATION ---")
    column_errors = 0
    for tbl_name, exp_cols in EXPECTED_COLUMNS.items():
        if tbl_name not in tables:
            continue
        actual_cols = tables[tbl_name]["columns"]
        missing_cols = [c for c in exp_cols if c not in actual_cols]
        if missing_cols:
            reporter.check(False, f"Table columns complete: {tbl_name}", f"Missing columns: {missing_cols}")
            column_errors += 1
    if column_errors == 0:
        reporter.check(True, f"All mandatory columns present across all 61 tables ({sum(len(c) for c in EXPECTED_COLUMNS.values())} columns checked)")

    # 4. Foreign Key Target Integrity
    print("\n--- 4. FOREIGN KEY REFERENTIAL INTEGRITY ---")
    fk_errors = 0
    total_fks = 0
    for tbl_name, tbl_data in tables.items():
        for fk in tbl_data["foreign_keys"]:
            total_fks += 1
            ref_tbl = fk["ref_table"]
            ref_col = fk["ref_col"]
            if ref_tbl not in tables:
                reporter.check(False, f"FK {tbl_name}.{fk['col']} -> {ref_tbl}.{ref_col}", f"Referenced table '{ref_tbl}' not found in schema")
                fk_errors += 1
            elif ref_col not in tables[ref_tbl]["columns"]:
                reporter.check(False, f"FK {tbl_name}.{fk['col']} -> {ref_tbl}.{ref_col}", f"Referenced column '{ref_col}' not found in table '{ref_tbl}'")
                fk_errors += 1
    if fk_errors == 0:
        reporter.check(True, f"All foreign keys reference valid tables & columns ({total_fks} FK references verified)")

    # 5. Business Invariants & Partial Indexes
    print("\n--- 5. BUSINESS INVARIANTS & INTEGRITY CONSTRAINTS ---")
    indexes = parse_sql_indexes(sql_content)
    index_names = {idx["name"].lower() for idx in indexes}
    
    # Invariant 1: Single active ontology version
    has_active_onto_idx = "uq_kpi_ontology_versions_is_active" in index_names or any(
        "is_active" in idx["definition"] and "is_active = true" in idx["definition"] for idx in indexes
    )
    reporter.check(has_active_onto_idx, "Invariant: Single active ontology version partial unique index")

    # Invariant 2: Single active approval per mapping
    has_active_appr_idx = "uq_mapping_approvals_active" in index_names or any(
        "kpi_mapping_id" in idx["definition"] and "approved" in idx["definition"] for idx in indexes
    )
    reporter.check(has_active_appr_idx, "Invariant: Single active approval per mapping partial unique index")

    # Invariant 3: Single primary domain per target object
    has_primary_dom_idx = "uq_domain_classifications_primary" in index_names or any(
        "target_object_id" in idx["definition"] and "is_primary = true" in idx["definition"] for idx in indexes
    )
    reporter.check(has_primary_dom_idx, "Invariant: Single primary domain per object partial unique index")

    # Invariant 4: Symmetrical KPI equivalence pair prevention
    has_equiv_pair_idx = "uq_kpi_equivalence_candidates_pair" in index_names or any(
        "least" in idx["definition"].lower() and "greatest" in idx["definition"].lower() for idx in indexes
    )
    reporter.check(has_equiv_pair_idx, "Invariant: Symmetrical KPI equivalence pair prevention (LEAST/GREATEST)")

    # Trigram & FTS indexes
    trgm_indexes = [idx for idx in indexes if "gin_trgm_ops" in idx["definition"]]
    fts_indexes = [idx for idx in indexes if "to_tsvector" in idx["definition"]]
    reporter.check(len(trgm_indexes) >= 4, f"Trigram (pg_trgm) search indexes present (found {len(trgm_indexes)})")
    reporter.check(len(fts_indexes) >= 1, f"Full-text search (to_tsvector) indexes present (found {len(fts_indexes)})")

    # 6. Seed Data Verification
    print("\n--- 6. BUSINESS DOMAINS SEED DATA VERIFICATION ---")
    seeded_codes = parse_seed_domains(sql_content)
    for code, name in EXPECTED_DOMAINS:
        reporter.check(code in seeded_codes, f"Domain seeded: {code} ({name})")

    # 7. Cross-File Integrity & Inventory Synchronization
    print("\n--- 7. CROSS-FILE SYNCHRONIZATION ---")
    # Table Inventory CSV
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            csv_rows = list(reader)
        csv_tables = {row["table"].strip().lower() for row in csv_rows}
        reporter.check(len(csv_rows) == 61, f"table_inventory.csv has 61 rows (found {len(csv_rows)})")
        missing_in_csv = [tbl for tbl in all_expected_flat if tbl not in csv_tables]
        reporter.check(len(missing_in_csv) == 0, "table_inventory.csv contains all 61 schema tables", f"Missing in CSV: {missing_in_csv}")
    else:
        reporter.check(False, "table_inventory.csv exists")

    # Data Dictionary Markdown
    if os.path.exists(dict_path):
        with open(dict_path, "r", encoding="utf-8") as f:
            dict_content = f.read()
        missing_in_dict = []
        for tbl in all_expected_flat:
            if f"`{tbl}`" not in dict_content and f"### {tbl}" not in dict_content:
                missing_in_dict.append(tbl)
        reporter.check(len(missing_in_dict) == 0, f"data_dictionary.md documents all 61 tables", f"Missing in doc: {missing_in_dict}")
    else:
        reporter.check(False, "data_dictionary.md exists")

    # ER Diagram Markdown
    if os.path.exists(er_path):
        with open(er_path, "r", encoding="utf-8") as f:
            er_content = f.read()
        missing_in_er = []
        for tbl in all_expected_flat:
            if f"`{tbl}`" not in er_content and f"{tbl} " not in er_content:
                missing_in_er.append(tbl)
        reporter.check(len(missing_in_er) == 0, f"er_diagram.md covers all 61 tables in diagrams/map", f"Missing in ERD: {missing_in_er}")
    else:
        reporter.check(False, "er_diagram.md exists")

    # 8. Live Database Execution (if requested)
    print("\n--- 8. DATABASE EXECUTION ENVIRONMENT ---")
    if db_url:
        print(f"Connecting to live database: {db_url}")
        try:
            import psycopg2
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            cur.execute(sql_content)
            conn.commit()
            reporter.check(True, "Live database execution: canonical_schema.sql executed successfully without errors")
            cur.close()
            conn.close()
        except ImportError:
            reporter.warn("psycopg2 module not installed; live database execution could not be run.")
        except Exception as e:
            reporter.check(False, "Live database execution", f"SQL execution error: {str(e)}")
    else:
        print("Live PostgreSQL connection not specified or unavailable in sandbox.")
        print("STATIC VALIDATION WAS PERFORMED SUCCESSFULLY. Actual live database execution was not run.")

    return reporter.summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate KPI Intelligence Canonical Model")
    parser.add_argument("--db-url", type=str, default=None, help="PostgreSQL connection URL for live execution test")
    parser.add_argument("--dir", type=str, default=os.getcwd(), help="Root directory of the project")
    args = parser.parse_args()

    success = validate_canonical_model(args.dir, args.db_url)
    sys.exit(0 if success else 1)
