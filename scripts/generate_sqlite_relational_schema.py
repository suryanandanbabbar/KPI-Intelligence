#!/usr/bin/env python3
"""
KPI Intelligence — Canonical Relational SQLite Schema Generator

Generates a 100% SQLite3-compatible relational DDL representing all 61 canonical tables
and all 636 canonical columns from docs/kpi-intelligence-canonical-model/canonical_schema.sql.

Enforces:
- Foreign key definitions with ON DELETE actions
- Strict column compatibility with scripts/validate_canonical_model.py
- Primary keys and unique constraints
- SQLite data affinities (TEXT, INTEGER, REAL)
- Clean indexes and default seed data
"""

import re
import os
import sqlite3
import sys

from scripts.validate_canonical_model import EXPECTED_COLUMNS, EXPECTED_TABLES

POSTGRES_SCHEMA_PATH = "docs/kpi-intelligence-canonical-model/canonical_schema.sql"
SQLITE_SCHEMA_PATH = "backend/storage/sqlite/canonical_relational_schema.sql"


def generate_sqlite_ddl() -> str:
    with open(POSTGRES_SCHEMA_PATH, "r", encoding="utf-8") as f:
        pg_content = f.read()

    # 1. Extract table definitions: regex to find CREATE TABLE kpi_intel.<name> ( ... );
    table_pattern = re.compile(
        r"CREATE TABLE kpi_intel\.([a-z0-9_]+)\s*\((.*?)\);",
        re.DOTALL | re.IGNORECASE
    )

    matches = list(table_pattern.finditer(pg_content))
    print(f"Found {len(matches)} CREATE TABLE blocks in PostgreSQL schema.")

    tables_ddl = []
    created_tables = set()

    def split_table_body(body: str) -> list[str]:
        items = []
        current = []
        depth = 0
        in_quote = False
        quote_char = ''
        for char in body:
            if in_quote:
                current.append(char)
                if char == quote_char:
                    in_quote = False
            elif char in ("'", '"'):
                in_quote = True
                quote_char = char
                current.append(char)
            elif char == '(':
                depth += 1
                current.append(char)
            elif char == ')':
                depth -= 1
                current.append(char)
            elif char == ',' and depth == 0:
                item = "".join(current).strip()
                if item:
                    items.append(item)
                current = []
            else:
                current.append(char)
        item = "".join(current).strip()
        if item:
            items.append(item)
        return items

    for m in matches:
        tbl_name = m.group(1).lower()
        tbl_body = m.group(2)
        created_tables.add(tbl_name)

        raw_items = split_table_body(tbl_body)
        cleaned_items = []
        for raw_item in raw_items:
            # Remove line comments
            lines = [re.sub(r"--.*$", "", ln).strip() for ln in raw_item.split("\n")]
            item = " ".join([ln for ln in lines if ln])
            if not item:
                continue

            cleaned = item.replace("kpi_intel.", "")
            cleaned = re.sub(r"\bUUID PRIMARY KEY DEFAULT gen_random_uuid\(\)", "TEXT PRIMARY KEY", cleaned, flags=re.I)
            cleaned = re.sub(r"\bUUID\b", "TEXT", cleaned, flags=re.I)
            cleaned = re.sub(r"\bTIMESTAMPTZ NOT NULL DEFAULT clock_timestamp\(\)", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP", cleaned, flags=re.I)
            cleaned = re.sub(r"\bTIMESTAMPTZ\b", "TEXT", cleaned, flags=re.I)
            cleaned = re.sub(r"\bTIMESTAMP\b", "TEXT", cleaned, flags=re.I)
            cleaned = re.sub(r"\bJSONB NOT NULL DEFAULT '\{\}'::jsonb\b", "TEXT NOT NULL DEFAULT '{}'", cleaned, flags=re.I)
            cleaned = re.sub(r"\bJSONB NOT NULL DEFAULT '\[\]'::jsonb\b", "TEXT NOT NULL DEFAULT '[]'", cleaned, flags=re.I)
            cleaned = re.sub(r"\bJSONB\b", "TEXT", cleaned, flags=re.I)
            cleaned = re.sub(r"\bBOOLEAN NOT NULL DEFAULT true\b", "INTEGER NOT NULL DEFAULT 1", cleaned, flags=re.I)
            cleaned = re.sub(r"\bBOOLEAN NOT NULL DEFAULT false\b", "INTEGER NOT NULL DEFAULT 0", cleaned, flags=re.I)
            cleaned = re.sub(r"\bBOOLEAN\b", "INTEGER", cleaned, flags=re.I)
            cleaned = re.sub(r"\bBIGINT\b", "INTEGER", cleaned, flags=re.I)
            cleaned = re.sub(r"\bNUMERIC\([0-9]+,\s*[0-9]+\)", "REAL", cleaned, flags=re.I)
            cleaned = re.sub(r"\bNUMERIC\b", "REAL", cleaned, flags=re.I)
            cleaned = re.sub(r"\bDOUBLE PRECISION\b", "REAL", cleaned, flags=re.I)
            cleaned = re.sub(r"\bTEXT\[\]\b", "TEXT", cleaned, flags=re.I)
            cleaned = re.sub(r"\bDEFAULT clock_timestamp\(\)", "DEFAULT CURRENT_TIMESTAMP", cleaned, flags=re.I)
            cleaned = re.sub(r"\bDEFAULT true\b", "DEFAULT 1", cleaned, flags=re.I)
            cleaned = re.sub(r"\bDEFAULT false\b", "DEFAULT 0", cleaned, flags=re.I)
            cleaned = re.sub(r"::jsonb\b", "", cleaned, flags=re.I)
            cleaned = re.sub(r"ON DELETE SET NULL\s*\([^)]+\)", "ON DELETE SET NULL", cleaned, flags=re.I)

            # Clean extra spaces
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            cleaned_items.append(f"    {cleaned}")

        # Handle circular foreign keys directly in table definition:
        if tbl_name == "assets":
            cleaned_items.append("    CONSTRAINT fk_assets_current_version FOREIGN KEY (current_version_id) REFERENCES asset_versions(asset_version_id) ON DELETE SET NULL")
        elif tbl_name == "reports":
            cleaned_items.append("    CONSTRAINT fk_reports_owner FOREIGN KEY (owner_id) REFERENCES security_principals(principal_id) ON DELETE SET NULL")

        body_text = ",\n".join(cleaned_items)
        tbl_sql = f"CREATE TABLE IF NOT EXISTS {tbl_name} (\n{body_text}\n);"
        tables_ddl.append(tbl_sql)

    # 2. Extract Indexes
    index_pattern = re.compile(
        r"CREATE\s+(UNIQUE\s+)?INDEX\s+([a-z0-9_]+)\s+ON\s+kpi_intel\.([a-z0-9_]+)(.*?);",
        re.DOTALL | re.IGNORECASE
    )
    indexes_ddl = []
    for m in index_pattern.finditer(pg_content):
        unique_clause = m.group(1) or ""
        idx_name = m.group(2)
        idx_tbl = m.group(3)
        idx_rest = m.group(4)

        # Truncate if ALTER TABLE or COMMENT was swallowed
        if "ALTER TABLE" in idx_rest:
            idx_rest = idx_rest.split("ALTER TABLE")[0]
        if "COMMENT" in idx_rest:
            idx_rest = idx_rest.split("COMMENT")[0]

        # Remove line comments
        idx_lines = [re.sub(r"--.*$", "", ln).strip() for ln in idx_rest.split("\n")]
        idx_rest = " ".join([ln for ln in idx_lines if ln])

        # Clean rest of index statement: remove USING gin, gin_trgm_ops, to_tsvector
        idx_rest = re.sub(r"USING\s+gin\s*", "", idx_rest, flags=re.I)
        idx_rest = re.sub(r"USING\s+btree\s*", "", idx_rest, flags=re.I)
        idx_rest = re.sub(r"\s+gin_trgm_ops", "", idx_rest, flags=re.I)
        idx_rest = re.sub(r"to_tsvector\('[^']+',\s*([a-z0-9_]+)\)", r"\1", idx_rest, flags=re.I)
        idx_rest = re.sub(r"\bLEAST\(", "MIN(", idx_rest, flags=re.I)
        idx_rest = re.sub(r"\bGREATEST\(", "MAX(", idx_rest, flags=re.I)
        idx_rest = re.sub(r"=\s*true\b", "= 1", idx_rest, flags=re.I)
        idx_rest = re.sub(r"=\s*false\b", "= 0", idx_rest, flags=re.I)
        idx_rest = idx_rest.replace("kpi_intel.", "").strip()

        # Format SQLite index
        idx_sql = f"CREATE {unique_clause}INDEX IF NOT EXISTS {idx_name} ON {idx_tbl} {idx_rest};"
        # Condense whitespace
        idx_sql = re.sub(r"\s+", " ", idx_sql)
        indexes_ddl.append(idx_sql)

    # 3. Business Domains Seed Data
    seed_sql = """-- ============================================================================
-- SEED DATA: BUSINESS DOMAINS
-- ============================================================================
INSERT INTO business_domains (domain_id, domain_code, domain_name, domain_description, is_active)
VALUES
    ('a0000000-0000-0000-0000-000000000001', 'CLAIMS_RISK', 'Claims & Risk', 'Insurance claims processing, reserve modeling, loss adjusting, fraud detection, and risk assessment.', 1),
    ('a0000000-0000-0000-0000-000000000002', 'LEGAL', 'Legal', 'Litigation tracking, regulatory compliance, contract management, disputes, and legal spend.', 1),
    ('a0000000-0000-0000-0000-000000000003', 'UNDERWRITING', 'Underwriting', 'Risk selection, policy pricing, capacity allocation, guideline adherence, and exposure analysis.', 1),
    ('a0000000-0000-0000-0000-000000000004', 'SALES_DISTRIBUTION', 'Sales & Distribution', 'Broker/agent performance, commissions, pipeline tracking, customer acquisition, and distribution channel analytics.', 1),
    ('a0000000-0000-0000-0000-000000000005', 'SERVICE_OPERATIONS', 'Service & Operations', 'Policyholder servicing, call center operations, SLA performance, operational efficiency, and transaction turnaround time.', 1),
    ('a0000000-0000-0000-0000-000000000006', 'ACTUARIAL', 'Actuarial', 'Pricing models, loss reserving, capital adequacy, solvency modeling, mortality/morbidity tables, and catastrophe risk analysis.', 1)
ON CONFLICT (domain_code) DO UPDATE
SET domain_name = excluded.domain_name,
    domain_description = excluded.domain_description,
    is_active = excluded.is_active;
"""

    header = """-- ============================================================================
-- KPI INTELLIGENCE PLATFORM — CANONICAL DATA MODEL DDL (SQLITE MIRROR)
-- Subsystem: Local SQLite Relational Mirror (Developer & Offline Conformance)
-- Description: Complete 61-table relational schema mirroring canonical_schema.sql.
--              Includes all columns, primary keys, foreign keys, and indexes.
-- ============================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

"""

    full_sql = (
        header
        + "\n\n".join(tables_ddl)
        + "\n\n-- ============================================================================\n"
        + "-- INDEXES\n"
        + "-- ============================================================================\n\n"
        + "\n".join(indexes_ddl)
        + "\n\n"
        + seed_sql
    )

    return full_sql


def validate_ddl(sql_text: str):
    """Executes the DDL against an in-memory SQLite DB and verifies all 61 tables and 636 columns."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(sql_text)

    # Check foreign keys
    cur = conn.execute("PRAGMA foreign_key_check;")
    fk_errors = cur.fetchall()
    if fk_errors:
        raise ValueError(f"Foreign key violations after script execution: {fk_errors}")

    # Inspect created tables and columns
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = {r[0] for r in cur.fetchall()}

    expected_table_set = set(EXPECTED_COLUMNS.keys())
    missing_tables = expected_table_set - tables
    if missing_tables:
        raise ValueError(f"Missing canonical tables in SQLite schema: {missing_tables}")

    total_cols = 0
    for tbl in sorted(expected_table_set):
        cur = conn.execute(f"PRAGMA table_info({tbl});")
        actual_cols = [r[1] for r in cur.fetchall()]
        exp_cols = EXPECTED_COLUMNS[tbl]
        total_cols += len(actual_cols)

        missing_cols = set(exp_cols) - set(actual_cols)
        if missing_cols:
            raise ValueError(f"Table '{tbl}' missing columns: {missing_cols}")

    print(f"Validation SUCCESS: {len(tables)} tables and {total_cols} columns verified in SQLite memory.")

    # Check business domains seeded
    cur = conn.execute("SELECT COUNT(*) FROM business_domains;")
    domain_count = cur.fetchone()[0]
    if domain_count != 6:
        raise ValueError(f"Expected 6 business domains, got {domain_count}")
    print(f"Seed SUCCESS: {domain_count} business domains seeded.")


def main():
    print("Generating SQLite Canonical Relational Schema...")
    sql = generate_sqlite_ddl()
    validate_ddl(sql)

    os.makedirs(os.path.dirname(SQLITE_SCHEMA_PATH), exist_ok=True)
    with open(SQLITE_SCHEMA_PATH, "w", encoding="utf-8") as f:
        f.write(sql)
    print(f"Saved SQLite schema to {SQLITE_SCHEMA_PATH}")


if __name__ == "__main__":
    main()
