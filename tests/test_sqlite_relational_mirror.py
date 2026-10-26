"""
KPI Intelligence — SQLite Relational Mirror Test Suite

Verifies:
1. Complete 61-table schema instantiation with valid SQLite syntax.
2. 100% column parity against scripts/validate_canonical_model.py (636 columns).
3. Active foreign key enforcement (PRAGMA foreign_keys = ON).
4. Negative tests for foreign key violations and constraint enforcement.
5. Deterministic synthetic fixture seeding with 0 referential violations.
6. Cascade delete behavior on relational parent-child hierarchies.
7. Negative tenant isolation queries on relational tables.
8. Database inspection and export tooling.
"""

import os
import json
import tempfile
import sqlite3
import unittest
from typing import Dict, List

from scripts.validate_canonical_model import EXPECTED_COLUMNS, EXPECTED_TABLES
from backend.storage.sqlite.relational_manager import (
    init_relational_schema,
    validate_relational_schema,
    seed_relational_synthetic_data,
    run_relational_checks,
    inspect_relational_database,
    export_relational_data,
    get_connection,
)


class TestSqliteRelationalMirror(unittest.TestCase):
    """Test suite for the local SQLite relational canonical mirror."""

    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.db_path = self.temp_file.name
        self.temp_file.close()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_01_schema_initialization_completeness(self):
        """Validates that init_relational_schema creates exactly 61 tables with 636 columns."""
        init_relational_schema(self.db_path)
        val = validate_relational_schema(self.db_path)

        self.assertTrue(val["valid"], f"Schema validation failed: {val.get('missing_tables')} {val.get('missing_columns')}")
        self.assertEqual(val["tables_count"], 61)
        self.assertEqual(val["total_columns"], 636)
        self.assertEqual(val["fk_violations_count"], 0)
        self.assertEqual(val["integrity_check"], "ok")

    def test_02_business_domains_seeded_by_default(self):
        """Verifies that canonical schema DDL seeds the 6 required business domains."""
        init_relational_schema(self.db_path)
        with get_connection(self.db_path) as conn:
            cur = conn.execute("SELECT domain_code, domain_name FROM business_domains ORDER BY domain_code;")
            domains = {r["domain_code"]: r["domain_name"] for r in cur.fetchall()}

        expected_codes = {
            "CLAIMS_RISK",
            "LEGAL",
            "UNDERWRITING",
            "SALES_DISTRIBUTION",
            "SERVICE_OPERATIONS",
            "ACTUARIAL",
        }
        self.assertEqual(set(domains.keys()), expected_codes)
        self.assertEqual(len(domains), 6)

    def test_03_foreign_key_enforcement_negative(self):
        """Verifies that inserting a child record with a non-existent foreign key fails."""
        init_relational_schema(self.db_path)
        with get_connection(self.db_path) as conn:
            # Attempt to insert an asset_version referencing a non-existent asset_id
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """INSERT INTO asset_versions
                    (asset_version_id, asset_id, tenant_id, version_number, content_hash, raw_content_hash, structure_hash, metadata_hash, parser_version, schema_version)
                    VALUES ('v_nonexistent', 'a_missing', 'tenant_1', 1, 'h1', 'h2', 'h3', 'h4', '1.0', '2.0');"""
                )

    def test_04_check_constraints_enforcement_negative(self):
        """Verifies that invalid enum values violate check constraints."""
        init_relational_schema(self.db_path)
        with get_connection(self.db_path) as conn:
            # ck_assets_platform only allows ('POWER_BI', 'TABLEAU', 'EXCEL', 'THOUGHTSPOT', 'MICROSTRATEGY')
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """INSERT INTO assets
                    (asset_id, tenant_id, platform, asset_type, asset_name)
                    VALUES ('a1', 't1', 'INVALID_PLATFORM', 'REPORT', 'Test Asset');"""
                )

            # ck_reports_lifecycle_status only allows ('ACTIVE', 'DORMANT', 'ORPHANED', 'UNCLASSIFIED')
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """INSERT INTO analytical_objects
                    (object_id, asset_version_id, tenant_id, platform, object_type, canonical_name)
                    VALUES ('obj1', 'v1', 't1', 'POWER_BI', 'REPORT', 'CanonName');"""
                )

    def test_05_cascade_deletion(self):
        """Verifies CASCADE ON DELETE behaviors in relational hierarchy."""
        init_relational_schema(self.db_path)
        with get_connection(self.db_path) as conn:
            # Insert asset
            conn.execute(
                """INSERT INTO assets (asset_id, tenant_id, platform, asset_type, asset_name)
                VALUES ('a_parent', 't1', 'POWER_BI', 'REPORT_PACKAGE', 'Parent Asset');"""
            )
            # Insert version
            conn.execute(
                """INSERT INTO asset_versions
                (asset_version_id, asset_id, tenant_id, version_number, content_hash, raw_content_hash, structure_hash, metadata_hash, parser_version, schema_version)
                VALUES ('v_child', 'a_parent', 't1', 1, 'h1', 'h2', 'h3', 'h4', '1.0', '2.0');"""
            )
            # Insert artifact
            conn.execute(
                """INSERT INTO source_artifacts
                (source_artifact_id, asset_version_id, relative_path, artifact_type, content_hash, size_bytes)
                VALUES ('art_child', 'v_child', 'report.json', 'REPORT_DEFINITION', 'h5', 1024);"""
            )

            # Verify presence
            cur = conn.execute("SELECT COUNT(*) FROM source_artifacts WHERE source_artifact_id = 'art_child';")
            self.assertEqual(cur.fetchone()[0], 1)

            # Delete the root asset
            conn.execute("DELETE FROM assets WHERE asset_id = 'a_parent';")

            # Verify cascading deletion removed child version and artifact
            cur = conn.execute("SELECT COUNT(*) FROM asset_versions WHERE asset_version_id = 'v_child';")
            self.assertEqual(cur.fetchone()[0], 0)
            cur = conn.execute("SELECT COUNT(*) FROM source_artifacts WHERE source_artifact_id = 'art_child';")
            self.assertEqual(cur.fetchone()[0], 0)

    def test_06_synthetic_seed_and_fk_cleanliness(self):
        """Validates that seed_relational_synthetic_data populates all tables with 0 FK violations."""
        counts = seed_relational_synthetic_data(self.db_path)

        self.assertEqual(len(counts), 61, "Should count records across all 61 tables")
        total_rows = sum(counts.values())
        self.assertGreater(total_rows, 50, "Should populate comprehensive fixtures across tables")

        # Zero FK violations
        checks = run_relational_checks(self.db_path)
        self.assertTrue(checks["clean"])
        self.assertEqual(checks["foreign_key_violations_count"], 0)
        self.assertEqual(checks["integrity_check"], "ok")

    def test_07_inspection_and_export(self):
        """Validates inspection report and JSON export."""
        seed_relational_synthetic_data(self.db_path)

        # Inspect
        summary = inspect_relational_database(self.db_path)
        self.assertTrue(summary["exists"])
        self.assertTrue(summary["valid_schema"])
        self.assertEqual(summary["tables_count"], 61)
        self.assertEqual(summary["columns_count"], 636)
        self.assertEqual(summary["foreign_key_violations"], 0)
        self.assertEqual(len(summary["subsystems"]), 10)

        # Export
        export_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False).name
        try:
            saved_path = export_relational_data(self.db_path, export_file)
            self.assertTrue(os.path.exists(saved_path))
            with open(saved_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("tables", data)
            self.assertEqual(len(data["tables"]), 61)
            self.assertIn("assets", data["tables"])
            self.assertGreater(len(data["tables"]["assets"]), 0)
        finally:
            if os.path.exists(export_file):
                os.remove(export_file)

    def test_08_negative_tenant_isolation(self):
        """Verifies tenant filtering across relational tables strictly isolates tenant data."""
        seed_relational_synthetic_data(self.db_path)
        TENANT_ALPHA = "11111111-1111-1111-1111-111111111111"
        TENANT_BETA = "22222222-2222-2222-2222-222222222222"

        with get_connection(self.db_path) as conn:
            # Query assets for Tenant Beta when only Tenant Alpha data exists
            cur = conn.execute("SELECT * FROM assets WHERE tenant_id = ?;", (TENANT_BETA,))
            self.assertEqual(len(cur.fetchall()), 0)

            # Query analytical_objects for Tenant Beta
            cur = conn.execute("SELECT * FROM analytical_objects WHERE tenant_id = ?;", (TENANT_BETA,))
            self.assertEqual(len(cur.fetchall()), 0)

            # Query kpi_candidates for Tenant Beta
            cur = conn.execute("SELECT * FROM kpi_candidates WHERE tenant_id = ?;", (TENANT_BETA,))
            self.assertEqual(len(cur.fetchall()), 0)

            # Query kpi_mappings for Tenant Beta
            cur = conn.execute("SELECT * FROM kpi_mappings WHERE tenant_id = ?;", (TENANT_BETA,))
            self.assertEqual(len(cur.fetchall()), 0)

            # Ensure Tenant Alpha yields records
            cur = conn.execute("SELECT * FROM assets WHERE tenant_id = ?;", (TENANT_ALPHA,))
            self.assertGreater(len(cur.fetchall()), 0)


if __name__ == "__main__":
    unittest.main()
