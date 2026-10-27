"""
KPI Intelligence — Canonical Relational Database Manager (SQLite Mirror)

Provides offline developer, inspection, and verification tooling for the
complete 61-table canonical relational model in SQLite.

Functions:
- init_relational_schema: Executes canonical_relational_schema.sql with PRAGMA foreign_keys = ON.
- validate_relational_schema: Confirms all 61 tables and 636 columns match EXPECTED_COLUMNS.
- seed_relational_synthetic_data: Populates deterministic synthetic fixtures across canonical tables.
- run_relational_checks: Executes PRAGMA foreign_key_check and PRAGMA integrity_check.
- inspect_relational_database: Produces human-readable and structured inspection reports.
- export_relational_data: Dumps relational records to JSON or SQL format.
"""

import os
import sys
import json
import sqlite3
import datetime
from typing import Dict, List, Any, Optional, Tuple

from backend.storage.config import StorageConfig
from scripts.validate_canonical_model import EXPECTED_COLUMNS, EXPECTED_TABLES

SCHEMA_SQL_PATH = os.path.join(
    os.path.dirname(__file__), "canonical_relational_schema.sql"
)


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Resolves local SQLite database path as an absolute path."""
    if custom_path:
        return os.path.abspath(custom_path)
    config = StorageConfig.from_env()
    return os.path.abspath(config.sqlite_path)


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Returns SQLite connection with foreign keys enabled and WAL mode."""
    path = get_db_path(db_path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_relational_schema(db_path: Optional[str] = None) -> None:
    """Initializes all 61 canonical relational tables from canonical_relational_schema.sql."""
    if not os.path.exists(SCHEMA_SQL_PATH):
        raise FileNotFoundError(f"Canonical SQLite schema not found at: {SCHEMA_SQL_PATH}")

    with open(SCHEMA_SQL_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with get_connection(db_path) as conn:
        conn.executescript(schema_sql)


def validate_relational_schema(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Validates that the SQLite database has:
    1. Exactly 61 canonical tables.
    2. All 636 expected canonical columns matching EXPECTED_COLUMNS.
    3. Zero foreign key violations.
    4. Clean integrity check.
    """
    with get_connection(db_path) as conn:
        # 1. Fetch tables
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'cosmos_documents';"
        )
        existing_tables = {r["name"] for r in cur.fetchall()}

        expected_table_set = set(EXPECTED_COLUMNS.keys())
        missing_tables = sorted(list(expected_table_set - existing_tables))
        unexpected_tables = sorted(list(existing_tables - expected_table_set))

        # 2. Check columns per table
        table_reports = {}
        total_columns = 0
        missing_columns = {}
        for tbl in sorted(expected_table_set):
            if tbl in existing_tables:
                cur = conn.execute(f"PRAGMA table_info({tbl});")
                actual_cols = [r["name"] for r in cur.fetchall()]
                exp_cols = EXPECTED_COLUMNS[tbl]
                total_columns += len(actual_cols)
                missing = [c for c in exp_cols if c not in actual_cols]
                if missing:
                    missing_columns[tbl] = missing
                table_reports[tbl] = {
                    "expected": len(exp_cols),
                    "actual": len(actual_cols),
                    "valid": len(missing) == 0,
                    "missing": missing,
                }
            else:
                table_reports[tbl] = {
                    "expected": len(EXPECTED_COLUMNS[tbl]),
                    "actual": 0,
                    "valid": False,
                    "missing": EXPECTED_COLUMNS[tbl],
                }

        # 3. Foreign key check
        cur = conn.execute("PRAGMA foreign_key_check;")
        fk_violations = [dict(r) for r in cur.fetchall()]

        # 4. Integrity check
        cur = conn.execute("PRAGMA integrity_check;")
        integrity_res = cur.fetchone()[0]

        is_valid = (
            len(missing_tables) == 0
            and len(missing_columns) == 0
            and len(fk_violations) == 0
            and integrity_res == "ok"
        )

        return {
            "valid": is_valid,
            "tables_count": len(existing_tables),
            "expected_tables_count": len(expected_table_set),
            "missing_tables": missing_tables,
            "unexpected_tables": unexpected_tables,
            "total_columns": total_columns,
            "expected_columns": sum(len(c) for c in EXPECTED_COLUMNS.values()),
            "missing_columns": missing_columns,
            "fk_violations": fk_violations,
            "fk_violations_count": len(fk_violations),
            "integrity_check": integrity_res,
            "tables": table_reports,
        }


def run_relational_checks(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Runs PRAGMA foreign_key_check and PRAGMA integrity_check."""
    with get_connection(db_path) as conn:
        cur = conn.execute("PRAGMA foreign_key_check;")
        fk_rows = [dict(r) for r in cur.fetchall()]
        cur = conn.execute("PRAGMA integrity_check;")
        integrity = cur.fetchone()[0]

    return {
        "foreign_key_violations": fk_rows,
        "foreign_key_violations_count": len(fk_rows),
        "integrity_check": integrity,
        "clean": len(fk_rows) == 0 and integrity == "ok",
    }


def seed_relational_synthetic_data(db_path: Optional[str] = None) -> Dict[str, int]:
    """
    Populates deterministic synthetic fixtures across canonical tables in SQLite.
    Maintains 100% referential integrity with PRAGMA foreign_keys = ON.
    """
    init_relational_schema(db_path)

    # Identifiers
    TENANT_ALPHA = "11111111-1111-1111-1111-111111111111"
    TENANT_BETA = "22222222-2222-2222-2222-222222222222"

    USER_ALICE = "aaaa0000-0000-0000-0000-000000000001"
    USER_BOB = "bbbb0000-0000-0000-0000-000000000002"

    ASSET_PBI = "a1110000-0000-0000-0000-000000000001"
    ASSET_VER_PBI = "v1110000-0000-0000-0000-000000000001"
    ART_PBI = "art10000-0000-0000-0000-000000000001"
    INGEST_PBI = "ing10000-0000-0000-0000-000000000001"

    # Objects
    OBJ_REPORT = "obj10000-0000-0000-0000-000000000001"
    OBJ_PAGE = "obj20000-0000-0000-0000-000000000002"
    OBJ_VISUAL = "obj30000-0000-0000-0000-000000000003"
    OBJ_VISUAL_2 = "obj30000-0000-0000-0000-000000000033"
    VISUAL_ID_2 = "vis20000-0000-0000-0000-000000000002"
    OBJ_MODEL = "obj40000-0000-0000-0000-000000000004"
    OBJ_TABLE_FACT = "obj50000-0000-0000-0000-000000000005"
    OBJ_TABLE_DIM = "obj60000-0000-0000-0000-000000000006"
    OBJ_COL_LOSS = "obj70000-0000-0000-0000-000000000007"
    OBJ_COL_PREM = "obj80000-0000-0000-0000-000000000008"
    OBJ_CALC = "obj90000-0000-0000-0000-000000000009"
    OBJ_REL = "obj01000-0000-0000-0000-000000000010"
    OBJ_SPREADSHEET = "obj02000-0000-0000-0000-000000000020"

    REPORT_ID = "rep10000-0000-0000-0000-000000000001"
    PAGE_ID = "pag10000-0000-0000-0000-000000000001"
    VISUAL_ID = "vis10000-0000-0000-0000-000000000001"

    MODEL_ID = "sem10000-0000-0000-0000-000000000001"
    TBL_FACT_ID = "tbl10000-0000-0000-0000-000000000001"
    TBL_DIM_ID = "tbl20000-0000-0000-0000-000000000002"
    COL_LOSS_ID = "col10000-0000-0000-0000-000000000001"
    COL_PREM_ID = "col20000-0000-0000-0000-000000000002"
    CALC_ID = "clc10000-0000-0000-0000-000000000001"
    REL_ID = "rel10000-0000-0000-0000-000000000001"

    ONTO_VER_ID = "ontov000-0000-0000-0000-000000000001"
    ONTO_ENTRY_1 = "ontoe000-0000-0000-0000-000000000001"
    ONTO_ENTRY_2 = "ontoe000-0000-0000-0000-000000000002"
    DOMAIN_CLAIMS = "a0000000-0000-0000-0000-000000000001"

    CANDIDATE_1 = "cand0000-0000-0000-0000-000000000001"
    CANDIDATE_2 = "cand0000-0000-0000-0000-000000000002"
    RUN_ID = "run10000-0000-0000-0000-000000000001"
    MAPPING_ID = "map10000-0000-0000-0000-000000000001"
    MAPPING_CAND_ID = "mcnd0000-0000-0000-0000-000000000001"
    EVIDENCE_ID = "evid0000-0000-0000-0000-000000000001"
    APPROVAL_ID = "appr0000-0000-0000-0000-000000000001"
    OVERRIDE_ID = "ovrd0000-0000-0000-0000-000000000001"

    counts = {}

    with get_connection(db_path) as conn:
        # Subsystem D: Principals
        conn.execute(
            """INSERT OR IGNORE INTO security_principals
            (principal_id, tenant_id, platform, source_native_id, principal_name, principal_type, principal_properties)
            VALUES (?, ?, 'POWER_BI', 'p_alice', 'Alice SME', 'USER', '{}');""",
            (USER_ALICE, TENANT_ALPHA)
        )
        conn.execute(
            """INSERT OR IGNORE INTO security_principals
            (principal_id, tenant_id, platform, source_native_id, principal_name, principal_type, principal_properties)
            VALUES (?, ?, 'POWER_BI', 'p_bob', 'Bob Analyst', 'USER', '{}');""",
            (USER_BOB, TENANT_ALPHA)
        )

        # Subsystem A: Assets & Versions
        conn.execute(
            """INSERT OR REPLACE INTO assets
            (asset_id, tenant_id, platform, asset_type, asset_name, asset_description, source_native_id, lifecycle_status)
            VALUES (?, ?, 'POWER_BI', 'REPORT_PACKAGE', 'Claims Analytics Executive Dashboard', 'Synthetic claims dashboard', 'pbip_001', 'ACTIVE');""",
            (ASSET_PBI, TENANT_ALPHA)
        )
        conn.execute(
            """INSERT OR REPLACE INTO asset_versions
            (asset_version_id, asset_id, tenant_id, version_number, content_hash, raw_content_hash, structure_hash, metadata_hash, parser_version, schema_version, extraction_status)
            VALUES (?, ?, ?, 1, 'hash_c_01', 'hash_r_01', 'hash_s_01', 'hash_m_01', '1.0.0', '2.0.0', 'SUCCESSFUL');""",
            (ASSET_VER_PBI, ASSET_PBI, TENANT_ALPHA)
        )
        # Update current_version_id in assets
        conn.execute(
            "UPDATE assets SET current_version_id = ? WHERE asset_id = ?;",
            (ASSET_VER_PBI, ASSET_PBI)
        )

        conn.execute(
            """INSERT OR REPLACE INTO source_artifacts
            (source_artifact_id, asset_version_id, relative_path, artifact_type, content_hash, size_bytes, is_supported, extraction_status)
            VALUES (?, ?, 'Claims.pbip', 'PROJECT_FILE', 'hash_art_01', 2048, 1, 'SUCCESSFUL');""",
            (ART_PBI, ASSET_VER_PBI)
        )

        conn.execute(
            """INSERT OR REPLACE INTO ingestion_events
            (ingestion_id, asset_version_id, uploaded_by_user_id, original_filename, upload_size_bytes, upload_source, ingestion_status)
            VALUES (?, ?, ?, 'Claims.pbip', 2048, 'CLI_TOOL', 'COMPLETED');""",
            (INGEST_PBI, ASSET_VER_PBI, USER_ALICE)
        )

        # Subsystem B: Analytical Objects
        analytical_objs = [
            (OBJ_REPORT, ASSET_VER_PBI, TENANT_ALPHA, None, ART_PBI, 'POWER_BI', 'REPORT', 'rep_01', 'Claims Report', 'Claims_Report', 'Claims Report'),
            (OBJ_PAGE, ASSET_VER_PBI, TENANT_ALPHA, OBJ_REPORT, ART_PBI, 'POWER_BI', 'PAGE', 'pag_01', 'Executive Summary', 'Exec_Summary', 'Executive Summary'),
            (OBJ_VISUAL, ASSET_VER_PBI, TENANT_ALPHA, OBJ_PAGE, ART_PBI, 'POWER_BI', 'VISUAL', 'vis_01', 'Loss Ratio KPI Card', 'Loss_Ratio_Card', 'Loss Ratio KPI Card'),
            (OBJ_VISUAL_2, ASSET_VER_PBI, TENANT_ALPHA, OBJ_PAGE, ART_PBI, 'POWER_BI', 'VISUAL', 'vis_02', 'Loss Trend Chart', 'Loss_Trend_Chart', 'Loss Trend Chart'),
            (OBJ_MODEL, ASSET_VER_PBI, TENANT_ALPHA, None, ART_PBI, 'POWER_BI', 'SEMANTIC_MODEL', 'mod_01', 'Claims Model', 'Claims_Model', 'Claims Model'),
            (OBJ_TABLE_FACT, ASSET_VER_PBI, TENANT_ALPHA, OBJ_MODEL, ART_PBI, 'POWER_BI', 'DATA_TABLE', 'tbl_fact', 'Fact_Claims', 'Fact_Claims', 'Fact Claims'),
            (OBJ_TABLE_DIM, ASSET_VER_PBI, TENANT_ALPHA, OBJ_MODEL, ART_PBI, 'POWER_BI', 'DATA_TABLE', 'tbl_dim', 'Dim_Policy', 'Dim_Policy', 'Dim Policy'),
            (OBJ_COL_LOSS, ASSET_VER_PBI, TENANT_ALPHA, OBJ_TABLE_FACT, ART_PBI, 'POWER_BI', 'DATA_COLUMN', 'col_loss', 'Incurred_Loss', 'Incurred_Loss', 'Incurred Loss'),
            (OBJ_COL_PREM, ASSET_VER_PBI, TENANT_ALPHA, OBJ_TABLE_FACT, ART_PBI, 'POWER_BI', 'DATA_COLUMN', 'col_prem', 'Earned_Premium', 'Earned_Premium', 'Earned Premium'),
            (OBJ_CALC, ASSET_VER_PBI, TENANT_ALPHA, OBJ_MODEL, ART_PBI, 'POWER_BI', 'CALCULATION', 'calc_loss_ratio', 'Loss Ratio', 'Loss_Ratio', 'Loss Ratio'),
            (OBJ_REL, ASSET_VER_PBI, TENANT_ALPHA, OBJ_MODEL, ART_PBI, 'POWER_BI', 'RELATIONSHIP', 'rel_claims_policy', 'Rel_Claims_Policy', 'Rel_Claims_Policy', 'Claims to Policy'),
            (OBJ_SPREADSHEET, ASSET_VER_PBI, TENANT_ALPHA, None, ART_PBI, 'POWER_BI', 'WORKSHEET', 'sheet_01', 'Summary Sheet', 'Summary_Sheet', 'Summary Sheet'),
        ]
        for obj in analytical_objs:
            conn.execute(
                """INSERT OR REPLACE INTO analytical_objects
                (object_id, asset_version_id, tenant_id, parent_object_id, source_artifact_id, platform, object_type, source_native_id, source_native_name, canonical_name, display_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                obj
            )

        # Reports & Visuals
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO reports
            (report_id, object_id, report_type, default_page_object_id, page_count, visual_count, owner_id, owner_name, last_accessed_at, lifecycle_status)
            VALUES (?, ?, 'POWER_BI_PBIP', ?, 1, 1, ?, 'Alice SME', ?, 'ACTIVE');""",
            (REPORT_ID, OBJ_REPORT, OBJ_PAGE, USER_ALICE, now_iso)
        )
        conn.execute(
            """INSERT OR REPLACE INTO report_pages
            (page_id, report_id, object_id, source_native_id, page_name, page_order, page_type)
            VALUES (?, ?, ?, 'p1', 'Executive Summary', 1, 'STANDARD');""",
            (PAGE_ID, REPORT_ID, OBJ_PAGE)
        )
        conn.execute(
            """INSERT OR REPLACE INTO visuals
            (visual_id, page_id, object_id, source_native_id, visual_type, visual_title)
            VALUES (?, ?, ?, 'v1', 'card', 'Incurred Loss Ratio');""",
            (VISUAL_ID, PAGE_ID, OBJ_VISUAL)
        )
        conn.execute(
            """INSERT OR REPLACE INTO visuals
            (visual_id, page_id, object_id, source_native_id, visual_type, visual_title)
            VALUES (?, ?, ?, 'v2', 'lineChart', 'Loss Ratio Trend');""",
            (VISUAL_ID_2, PAGE_ID, OBJ_VISUAL_2)
        )
        conn.execute(
            """INSERT OR REPLACE INTO visual_bindings
            (visual_binding_id, visual_id, object_id, binding_role, binding_order)
            VALUES ('vb100000-0000-0000-0000-000000000001', ?, ?, 'Values', 1);""",
            (VISUAL_ID, OBJ_CALC)
        )
        conn.execute(
            """INSERT OR REPLACE INTO visual_properties
            (visual_property_id, visual_id, property_path, property_value)
            VALUES ('vp100000-0000-0000-0000-000000000001', ?, 'title.text', 'Incurred Loss Ratio');""",
            (VISUAL_ID,)
        )
        conn.execute(
            """INSERT OR REPLACE INTO visual_interactions
            (visual_interaction_id, source_visual_id, target_visual_id, interaction_type)
            VALUES ('vi100000-0000-0000-0000-000000000001', ?, ?, 'CROSS_FILTER');""",
            (VISUAL_ID, VISUAL_ID_2)
        )
        conn.execute(
            """INSERT OR REPLACE INTO visual_types
            (visual_type_id, platform, native_type, canonical_type, description)
            VALUES ('vt100000-0000-0000-0000-000000000001', 'POWER_BI', 'card', 'CARD', 'KPI Card visual');"""
        )
        conn.execute(
            """INSERT OR REPLACE INTO bookmarks
            (bookmark_id, object_id, source_native_id, bookmark_name)
            VALUES ('bm100000-0000-0000-0000-000000000001', ?, 'bm_default', 'Default View');""",
            (OBJ_REPORT,)
        )
        conn.execute(
            """INSERT OR REPLACE INTO report_navigation
            (report_navigation_id, source_object_id, target_object_id, navigation_type, navigation_name)
            VALUES ('rn100000-0000-0000-0000-000000000001', ?, ?, 'PAGE_NAV', 'To Summary');""",
            (OBJ_REPORT, OBJ_PAGE)
        )

        # Subsystem C: Semantic Models
        conn.execute(
            """INSERT OR REPLACE INTO semantic_models
            (semantic_model_id, object_id, source_native_id, model_name, model_type, compatibility_level)
            VALUES (?, ?, 'Claims_Model', 'Claims Model', 'TABULAR', 1567);""",
            (MODEL_ID, OBJ_MODEL)
        )
        conn.execute(
            """INSERT OR REPLACE INTO data_tables
            (data_table_id, object_id, semantic_model_id, source_native_id, table_name, table_type)
            VALUES (?, ?, ?, 'Fact_Claims', 'Fact_Claims', 'FACT');""",
            (TBL_FACT_ID, OBJ_TABLE_FACT, MODEL_ID)
        )
        conn.execute(
            """INSERT OR REPLACE INTO data_tables
            (data_table_id, object_id, semantic_model_id, source_native_id, table_name, table_type)
            VALUES (?, ?, ?, 'Dim_Policy', 'Dim_Policy', 'DIMENSION');""",
            (TBL_DIM_ID, OBJ_TABLE_DIM, MODEL_ID)
        )
        conn.execute(
            """INSERT OR REPLACE INTO data_columns
            (data_column_id, object_id, data_table_id, source_native_id, column_name, data_type, semantic_role)
            VALUES (?, ?, ?, 'Incurred_Loss', 'Incurred_Loss', 'REAL', 'MEASURE_BASE');""",
            (COL_LOSS_ID, OBJ_COL_LOSS, TBL_FACT_ID)
        )
        conn.execute(
            """INSERT OR REPLACE INTO data_columns
            (data_column_id, object_id, data_table_id, source_native_id, column_name, data_type, semantic_role)
            VALUES (?, ?, ?, 'Earned_Premium', 'Earned_Premium', 'REAL', 'MEASURE_BASE');""",
            (COL_PREM_ID, OBJ_COL_PREM, TBL_FACT_ID)
        )
        conn.execute(
            """INSERT OR REPLACE INTO calculations
            (calculation_id, object_id, semantic_model_id, data_table_id, data_column_id, calculation_name, calculation_type, expression_language, expression_text, return_data_type)
            VALUES (?, ?, ?, ?, ?, 'Loss Ratio', 'MEASURE', 'DAX', 'DIVIDE(SUM(Fact_Claims[Incurred_Loss]), SUM(Fact_Claims[Earned_Premium]))', 'REAL');""",
            (CALC_ID, OBJ_CALC, MODEL_ID, TBL_FACT_ID, COL_LOSS_ID)
        )
        conn.execute(
            """INSERT OR REPLACE INTO relationships
            (relationship_id, object_id, relationship_type, from_table_id, to_table_id, from_object_id, to_object_id, cardinality, join_type)
            VALUES (?, ?, 'ONE_TO_MANY', ?, ?, ?, ?, 'MANY_TO_ONE', 'INNER');""",
            (REL_ID, OBJ_REL, TBL_FACT_ID, TBL_DIM_ID, OBJ_TABLE_FACT, OBJ_TABLE_DIM)
        )
        conn.execute(
            """INSERT OR REPLACE INTO model_partitions
            (model_partition_id, semantic_model_id, source_native_id, partition_name, source_type)
            VALUES ('mp100000-0000-0000-0000-000000000001', ?, 'part_2025', 'Partition 2025', 'M_QUERY');""",
            (MODEL_ID,)
        )
        conn.execute(
            """INSERT OR REPLACE INTO hierarchies
            (hierarchy_id, object_id, semantic_model_id, hierarchy_name, hierarchy_type)
            VALUES ('h1000000-0000-0000-0000-000000000001', ?, ?, 'Time Hierarchy', 'CALENDAR');""",
            (OBJ_MODEL, MODEL_ID)
        )
        conn.execute(
            """INSERT OR REPLACE INTO hierarchy_levels
            (hierarchy_level_id, hierarchy_id, level_object_id, level_name, level_order)
            VALUES ('hl100000-0000-0000-0000-000000000001', 'h1000000-0000-0000-0000-000000000001', ?, 'Year', 1);""",
            (OBJ_COL_LOSS,)
        )
        conn.execute(
            """INSERT OR REPLACE INTO parameters
            (parameter_id, object_id, parameter_name, data_type, default_value)
            VALUES ('param000-0000-0000-0000-000000000001', ?, 'LossThreshold', 'REAL', '100000.0');""",
            (OBJ_MODEL,)
        )
        conn.execute(
            """INSERT OR REPLACE INTO named_expressions
            (named_expression_id, object_id, expression_name, scope, expression_language, expression_text)
            VALUES ('nexp0000-0000-0000-0000-000000000001', ?, 'fn_FormatCurrency', 'GLOBAL', 'M', 'each Text.From(_)');""",
            (OBJ_MODEL,)
        )

        # Subsystem D: Filters, Lineage, Roles, Data Sources
        conn.execute(
            """INSERT OR REPLACE INTO filters
            (filter_id, object_id, filter_name, filter_type, filter_scope)
            VALUES ('flt10000-0000-0000-0000-000000000001', ?, 'Active Policies Only', 'BASIC', 'REPORT');""",
            (OBJ_REPORT,)
        )
        conn.execute(
            """INSERT OR REPLACE INTO filter_assignments
            (filter_assignment_id, filter_id, target_object_id, field_object_id, assignment_scope)
            VALUES ('fa100000-0000-0000-0000-000000000001', 'flt10000-0000-0000-0000-000000000001', ?, ?, 'REPORT');""",
            (OBJ_REPORT, OBJ_COL_LOSS)
        )
        conn.execute(
            """INSERT OR REPLACE INTO security_roles
            (security_role_id, object_id, role_name, role_type)
            VALUES ('secr0000-0000-0000-0000-000000000001', ?, 'Underwriter Role', 'ROW_LEVEL_SECURITY');""",
            (OBJ_MODEL,)
        )
        conn.execute(
            """INSERT OR REPLACE INTO security_role_filters
            (security_role_filter_id, security_role_id, target_object_id, expression_language, expression_text)
            VALUES ('srf10000-0000-0000-0000-000000000001', 'secr0000-0000-0000-0000-000000000001', ?, 'DAX', '[Region] = "EAST"');""",
            (OBJ_TABLE_FACT,)
        )
        conn.execute(
            """INSERT OR REPLACE INTO security_object_permissions
            (permission_id, target_object_id, principal_id, principal_name, permission_type, permission_source)
            VALUES ('perm0000-0000-0000-0000-000000000001', ?, ?, 'Alice SME', 'READ', 'DIRECT');""",
            (OBJ_REPORT, USER_ALICE)
        )
        conn.execute(
            """INSERT OR REPLACE INTO data_sources
            (data_source_id, object_id, source_type, source_name, server_reference, database_reference)
            VALUES ('dsrc0000-0000-0000-0000-000000000001', ?, 'AZURE_SQL', 'ClaimsDB', 'sql.claims.corp', 'ClaimsDB_Prod');""",
            (OBJ_MODEL,)
        )
        conn.execute(
            """INSERT OR REPLACE INTO query_dependencies
            (query_dependency_id, source_object_id, target_object_id, target_reference, dependency_type)
            VALUES ('qdep0000-0000-0000-0000-000000000001', ?, ?, 'ClaimsDB.Fact_Claims', 'DATABASE_TABLE');""",
            (OBJ_TABLE_FACT, OBJ_TABLE_DIM)
        )
        conn.execute(
            """INSERT OR REPLACE INTO metadata_lineage_edges
            (lineage_edge_id, asset_version_id, source_object_id, target_object_id, edge_type, derivation_method, confidence_score)
            VALUES ('lin10000-0000-0000-0000-000000000001', ?, ?, ?, 'DERIVED_FROM', 'PARSED', 1.0);""",
            (ASSET_VER_PBI, OBJ_CALC, OBJ_COL_LOSS)
        )

        # Subsystem E: Spreadsheet Metadata
        conn.execute(
            """INSERT OR REPLACE INTO spreadsheet_cells
            (spreadsheet_cell_id, asset_version_id, worksheet_object_id, cell_address, row_number, column_number, formula_text, cached_value, data_type)
            VALUES ('sc100000-0000-0000-0000-000000000001', ?, ?, 'B2', 2, 2, '=SUM(B3:B10)', '500000', 'NUMERIC');""",
            (ASSET_VER_PBI, OBJ_SPREADSHEET)
        )
        conn.execute(
            """INSERT OR REPLACE INTO pivot_caches
            (pivot_cache_id, asset_version_id, source_native_id, source_type, source_reference)
            VALUES ('pc100000-0000-0000-0000-000000000001', ?, 'cache_1', 'WORKSHEET', 'Sheet1!$A$1:$F$100');""",
            (ASSET_VER_PBI,)
        )
        conn.execute(
            """INSERT OR REPLACE INTO pivot_tables
            (pivot_table_id, object_id, worksheet_object_id, pivot_cache_id, pivot_name)
            VALUES ('pt100000-0000-0000-0000-000000000001', ?, ?, 'pc100000-0000-0000-0000-000000000001', 'PivotTableClaims');""",
            (OBJ_SPREADSHEET, OBJ_SPREADSHEET)
        )
        conn.execute(
            """INSERT OR REPLACE INTO pivot_field_assignments
            (pivot_field_assignment_id, pivot_table_id, field_object_id, field_reference, assignment_role)
            VALUES ('pfa10000-0000-0000-0000-000000000001', 'pt100000-0000-0000-0000-000000000001', ?, 'Loss_Amount', 'VALUE');""",
            (OBJ_COL_LOSS,)
        )
        conn.execute(
            """INSERT OR REPLACE INTO spreadsheet_objects
            (spreadsheet_object_id, object_id, worksheet_object_id, object_subtype, range_reference)
            VALUES ('so100000-0000-0000-0000-000000000001', ?, ?, 'CHART', 'Sheet1!$D$2:$J$15');""",
            (OBJ_SPREADSHEET, OBJ_SPREADSHEET)
        )
        conn.execute(
            """INSERT OR REPLACE INTO spreadsheet_rules
            (spreadsheet_rule_id, object_id, worksheet_object_id, rule_type, range_reference, formula_text)
            VALUES ('sr100000-0000-0000-0000-000000000001', ?, ?, 'CONDITIONAL_FORMATTING', 'Sheet1!$B$2:$B$100', 'B2>10000');""",
            (OBJ_SPREADSHEET, OBJ_SPREADSHEET)
        )

        # Subsystem F: Ontology
        conn.execute(
            """INSERT OR REPLACE INTO kpi_ontology_versions
            (ontology_version_id, version_number, content_hash, schema_version, kpi_count, created_by_user_id, is_active)
            VALUES (?, '1.0.0', 'hash_onto_01', '2.0.0', 2, ?, 1);""",
            (ONTO_VER_ID, USER_ALICE)
        )
        conn.execute(
            """INSERT OR REPLACE INTO kpi_ontology_entries
            (ontology_entry_id, ontology_version_id, kpi_code, kpi_name, kpi_description, business_domain, definition, formula, unit, aggregation_method, source_kpi_id)
            VALUES (?, ?, 'CLM_001', 'Incurred Loss Ratio', 'Claims loss ratio', 'CLAIMS_RISK', 'Total losses / premium', '[Incurred Losses] / [Earned Premium]', 'PERCENTAGE', 'RATIO', 'SRC_CLM_01');""",
            (ONTO_ENTRY_1, ONTO_VER_ID)
        )
        conn.execute(
            """INSERT OR REPLACE INTO kpi_ontology_entries
            (ontology_entry_id, ontology_version_id, kpi_code, kpi_name, kpi_description, business_domain, definition, formula, unit, aggregation_method, source_kpi_id)
            VALUES (?, ?, 'UND_001', 'Combined Ratio', 'Underwriting combined ratio', 'UNDERWRITING', 'Incurred losses + expenses / premium', '([Losses] + [Expenses]) / [Premium]', 'PERCENTAGE', 'RATIO', 'SRC_UND_01');""",
            (ONTO_ENTRY_2, ONTO_VER_ID)
        )
        conn.execute(
            """INSERT OR REPLACE INTO domain_classifications
            (classification_id, asset_version_id, tenant_id, target_object_id, domain_id, classification_method, confidence_score, is_primary, approval_status)
            VALUES ('dc100000-0000-0000-0000-000000000001', ?, ?, ?, ?, 'LLM', 0.98, 1, 'APPROVED');""",
            (ASSET_VER_PBI, TENANT_ALPHA, OBJ_REPORT, DOMAIN_CLAIMS)
        )

        # Subsystem G: Candidates & Mappings
        conn.execute(
            """INSERT OR REPLACE INTO kpi_candidates
            (kpi_candidate_id, asset_version_id, tenant_id, source_object_id, candidate_name, candidate_expression, expression_language, candidate_type, unit, business_domain_id, discovery_method, discovery_version)
            VALUES (?, ?, ?, ?, 'Incurred Loss Ratio', 'DIVIDE(SUM(Fact_Claims[Incurred_Loss]), SUM(Fact_Claims[Earned_Premium]))', 'DAX', 'CALCULATED_MEASURE', 'PERCENTAGE', ?, 'PARSER_EXTRACTION', '1.0.0');""",
            (CANDIDATE_1, ASSET_VER_PBI, TENANT_ALPHA, OBJ_CALC, DOMAIN_CLAIMS)
        )
        conn.execute(
            """INSERT OR REPLACE INTO kpi_candidates
            (kpi_candidate_id, asset_version_id, tenant_id, source_object_id, candidate_name, candidate_expression, expression_language, candidate_type, unit, business_domain_id, discovery_method, discovery_version)
            VALUES (?, ?, ?, ?, 'Loss Amount', 'SUM(Fact_Claims[Incurred_Loss])', 'DAX', 'BASE_MEASURE', 'CURRENCY', ?, 'PARSER_EXTRACTION', '1.0.0');""",
            (CANDIDATE_2, ASSET_VER_PBI, TENANT_ALPHA, OBJ_COL_LOSS, DOMAIN_CLAIMS)
        )
        conn.execute(
            """INSERT OR REPLACE INTO kpi_mapping_runs
            (mapping_run_id, asset_version_id, tenant_id, ontology_version_id, candidate_generation_version, mapping_engine_version, primary_engine, input_fingerprint, run_status)
            VALUES (?, ?, ?, ?, '1.0.0', '1.0.0', 'LLM', 'fp_claims_01', 'SUCCESSFUL');""",
            (RUN_ID, ASSET_VER_PBI, TENANT_ALPHA, ONTO_VER_ID)
        )
        conn.execute(
            """INSERT OR REPLACE INTO kpi_mappings
            (kpi_mapping_id, kpi_candidate_id, mapping_run_id, tenant_id, asset_version_id, ontology_version_id, selected_ontology_entry_id, mapping_status, decision_source, top_candidate_count, input_fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'APPROVED', 'HUMAN', 1, 'fp_claims_01');""",
            (MAPPING_ID, CANDIDATE_1, RUN_ID, TENANT_ALPHA, ASSET_VER_PBI, ONTO_VER_ID, ONTO_ENTRY_1)
        )
        conn.execute(
            """INSERT OR REPLACE INTO kpi_mapping_candidates
            (mapping_candidate_id, kpi_mapping_id, ontology_entry_id, rank, confidence_score, confidence_band, match_score, rationale, is_recommended)
            VALUES (?, ?, ?, 1, 0.98, 'HIGH', 0.98, 'Direct formula and semantic equivalence to standard loss ratio', 1);""",
            (MAPPING_CAND_ID, MAPPING_ID, ONTO_ENTRY_1)
        )
        conn.execute(
            """INSERT OR REPLACE INTO mapping_evidence
            (mapping_evidence_id, mapping_candidate_id, evidence_type, source_object_id, evidence_text, polarity)
            VALUES (?, ?, 'DAX_FORMULA_MATCH', ?, 'Formula matches [Incurred Losses] / [Earned Premium]', 'SUPPORTS');""",
            (EVIDENCE_ID, MAPPING_CAND_ID, OBJ_CALC)
        )

        # Subsystem H: Review, Approvals, Overrides
        conn.execute(
            """INSERT OR REPLACE INTO mapping_reviews
            (mapping_review_id, kpi_mapping_id, mapping_candidate_id, reviewer_user_id, review_action, review_status, review_comment)
            VALUES ('rev10000-0000-0000-0000-000000000001', ?, ?, ?, 'APPROVE', 'COMPLETED', 'Verified by Claims Actuary');""",
            (MAPPING_ID, MAPPING_CAND_ID, USER_ALICE)
        )
        conn.execute(
            """INSERT OR REPLACE INTO mapping_approvals
            (mapping_approval_id, kpi_mapping_id, approved_mapping_candidate_id, approved_by_user_id, approval_status, approval_version)
            VALUES (?, ?, ?, ?, 'APPROVED', 1);""",
            (APPROVAL_ID, MAPPING_ID, MAPPING_CAND_ID, USER_ALICE)
        )
        conn.execute(
            """INSERT OR REPLACE INTO mapping_overrides
            (override_id, kpi_mapping_id, mapping_candidate_id, override_type, previous_ontology_entry_id, replacement_ontology_entry_id, override_justification, normalised_justification, justification_hash, created_by_user_id, is_active)
            VALUES (?, ?, ?, 'SELECT_ALTERNATIVE', ?, ?, 'Reclassified to formal loss ratio', 'reclassified to formal loss ratio', 'hash_just_01', ?, 1);""",
            (OVERRIDE_ID, MAPPING_ID, MAPPING_CAND_ID, ONTO_ENTRY_2, ONTO_ENTRY_1, USER_ALICE)
        )
        conn.execute(
            """INSERT OR REPLACE INTO metadata_field_reviews
            (field_review_id, asset_version_id, tenant_id, target_object_id, field_path, source_value_hash, proposed_value, approved_value, review_status, reviewed_by_user_id)
            VALUES ('fr100000-0000-0000-0000-000000000001', ?, ?, ?, 'display_name', 'hash_disp_01', 'Executive Loss Ratio', 'Executive Loss Ratio', 'APPROVED', ?);""",
            (ASSET_VER_PBI, TENANT_ALPHA, OBJ_REPORT, USER_ALICE)
        )

        # Subsystem I: Rationalisation
        conn.execute(
            """INSERT OR REPLACE INTO kpi_equivalence_candidates
            (equivalence_candidate_id, source_kpi_candidate_id, target_kpi_candidate_id, comparison_type, equivalence_score, review_status)
            VALUES ('eq100000-0000-0000-0000-000000000001', ?, ?, 'CALCULATION_EQUIVALENCE', 0.85, 'APPROVED');""",
            (CANDIDATE_1, CANDIDATE_2)
        )
        conn.execute(
            """INSERT OR REPLACE INTO kpi_rationalisation_decisions
            (rationalisation_decision_id, equivalence_candidate_id, decision_type, canonical_kpi_candidate_id, approved_by_user_id, decision_justification, decision_status)
            VALUES ('rd100000-0000-0000-0000-000000000001', 'eq100000-0000-0000-0000-000000000001', 'MERGE', ?, ?, 'Merged duplicate base formula into ratio measure', 'APPROVED');""",
            (CANDIDATE_1, USER_ALICE)
        )
        conn.execute(
            """INSERT OR REPLACE INTO rationalisation_evidence
            (rationalisation_evidence_id, rationalisation_decision_id, evidence_type, evidence_text)
            VALUES ('re100000-0000-0000-0000-000000000001', 'rd100000-0000-0000-0000-000000000001', 'AST_EQUIVALENCE', 'AST subtrees identical across models');"""
        )

        # Subsystem J: Operations & Audit
        conn.execute(
            """INSERT OR REPLACE INTO platform_capabilities
            (platform_capability_id, platform, artifact_type, metadata_type, capability_status)
            VALUES ('pcp00000-0000-0000-0000-000000000001', 'POWER_BI', 'PBIP', 'REPORT_METADATA', 'SUPPORTED');"""
        )
        conn.execute(
            """INSERT OR REPLACE INTO parser_runs
            (parser_run_id, asset_version_id, tenant_id, source_artifact_id, platform, parser_name, parser_version, run_status, objects_extracted, warnings_count, errors_count)
            VALUES ('pr100000-0000-0000-0000-000000000001', ?, ?, ?, 'POWER_BI', 'PbipParser', '1.0.0', 'SUCCESSFUL', 11, 0, 0);""",
            (ASSET_VER_PBI, TENANT_ALPHA, ART_PBI)
        )
        conn.execute(
            """INSERT OR REPLACE INTO extraction_errors
            (extraction_error_id, parser_run_id, source_artifact_id, severity, error_code, error_message, is_recoverable)
            VALUES ('ee100000-0000-0000-0000-000000000001', 'pr100000-0000-0000-0000-000000000001', ?, 'WARNING', 'WARN_UNSUPPORTED_THEME', 'Custom theme JSON not parsed', 1);""",
            (ART_PBI,)
        )
        conn.execute(
            """INSERT OR REPLACE INTO object_tags
            (object_tag_id, object_id, tag_name, tag_value, tag_source)
            VALUES ('tag10000-0000-0000-0000-000000000001', ?, 'Tier', 'Gold', 'CANONICAL');""",
            (OBJ_REPORT,)
        )
        conn.execute(
            """INSERT OR REPLACE INTO mapping_audit_events
            (mapping_audit_event_id, tenant_id, kpi_mapping_id, target_kpi_mapping_id, actor_user_id, event_type, previous_state, new_state, event_reason)
            VALUES ('mae10000-0000-0000-0000-000000000001', ?, ?, ?, ?, 'STATUS_CHANGED', 'PROPOSED', 'APPROVED', 'Actuary approval');""",
            (TENANT_ALPHA, MAPPING_ID, MAPPING_ID, USER_ALICE)
        )
        conn.execute(
            """INSERT OR REPLACE INTO ontology_change_events
            (ontology_change_event_id, ontology_version_id, ontology_entry_id, actor_user_id, change_type, change_justification)
            VALUES ('oce10000-0000-0000-0000-000000000001', ?, ?, ?, 'ADD', 'Initial definition of CLM_001');""",
            (ONTO_VER_ID, ONTO_ENTRY_1, USER_ALICE)
        )

        # Count records in all 61 tables
        for tbl in sorted(EXPECTED_COLUMNS.keys()):
            cur = conn.execute(f"SELECT COUNT(*) FROM {tbl};")
            counts[tbl] = cur.fetchone()[0]

    # Verify 0 foreign key violations after seeding
    checks = run_relational_checks(db_path)
    if not checks["clean"]:
        raise ValueError(f"Foreign key violations detected after seeding: {checks['foreign_key_violations']}")

    return counts


def inspect_relational_database(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Generates a complete summary of the local SQLite relational database."""
    path = get_db_path(db_path)
    if not os.path.exists(path):
        return {"exists": False, "path": path}

    file_size_bytes = os.path.getsize(path)
    val_report = validate_relational_schema(path)

    counts_by_subsystem = {}
    total_rows = 0

    with get_connection(path) as conn:
        for subsystem, tables in EXPECTED_TABLES.items():
            counts_by_subsystem[subsystem] = {}
            for tbl in tables:
                try:
                    cur = conn.execute(f"SELECT COUNT(*) FROM {tbl};")
                    cnt = cur.fetchone()[0]
                    counts_by_subsystem[subsystem][tbl] = cnt
                    total_rows += cnt
                except Exception:
                    counts_by_subsystem[subsystem][tbl] = 0

    return {
        "exists": True,
        "path": os.path.abspath(path),
        "file_size_bytes": file_size_bytes,
        "valid_schema": val_report["valid"],
        "tables_count": val_report["tables_count"],
        "columns_count": val_report["total_columns"],
        "foreign_key_violations": val_report["fk_violations_count"],
        "integrity_check": val_report["integrity_check"],
        "total_rows": total_rows,
        "subsystems": counts_by_subsystem,
    }


def export_relational_data(db_path: Optional[str] = None, output_path: Optional[str] = None) -> str:
    """Exports all relational tables and their records to a formatted JSON bundle."""
    path = get_db_path(db_path)
    if not output_path:
        output_path = os.path.splitext(path)[0] + "_export.json"

    export_bundle = {
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "database_path": os.path.abspath(path),
        "tables": {},
    }

    with get_connection(path) as conn:
        for tbl in sorted(EXPECTED_COLUMNS.keys()):
            try:
                cur = conn.execute(f"SELECT * FROM {tbl};")
                rows = [dict(r) for r in cur.fetchall()]
                export_bundle["tables"][tbl] = rows
            except Exception as e:
                export_bundle["tables"][tbl] = {"error": str(e)}

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export_bundle, f, indent=2, default=str)

    return os.path.abspath(output_path)
