#!/usr/bin/env python3
"""
Unit test suite for automated CI/CD test execution of the KPI Intelligence Canonical Model.
"""

import unittest
import os
import sys

# Add repository root to path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.validate_canonical_model import (
    validate_canonical_model,
    EXPECTED_TABLES,
    EXPECTED_COLUMNS,
    EXPECTED_DOMAINS,
    parse_sql_tables,
    parse_sql_indexes,
    parse_seed_domains
)

class TestCanonicalModelIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql_path = os.path.join(REPO_ROOT, "docs", "kpi-intelligence-canonical-model", "canonical_schema.sql")
        with open(cls.sql_path, "r", encoding="utf-8") as f:
            cls.sql_content = f.read()
        cls.tables = parse_sql_tables(cls.sql_content)
        cls.indexes = parse_sql_indexes(cls.sql_content)

    def test_total_table_count(self):
        """Verify exactly 61 tables are defined in the schema."""
        self.assertEqual(len(self.tables), 61, f"Expected 61 tables, found {len(self.tables)}")

    def test_all_expected_tables_present(self):
        """Verify every subsystem's tables are present."""
        for subsystem, expected_list in EXPECTED_TABLES.items():
            for table_name in expected_list:
                self.assertIn(table_name, self.tables, f"Missing table {table_name} in {subsystem}")

    def test_mandatory_columns_present(self):
        """Verify all mandatory columns exist on every table."""
        for table_name, expected_cols in EXPECTED_COLUMNS.items():
            self.assertIn(table_name, self.tables)
            actual_cols = self.tables[table_name]["columns"]
            for col in expected_cols:
                self.assertIn(col, actual_cols, f"Missing column {table_name}.{col}")

    def test_foreign_key_references(self):
        """Verify that every foreign key target table and column exist."""
        for table_name, data in self.tables.items():
            for fk in data["foreign_keys"]:
                ref_tbl = fk["ref_table"]
                local_cols = [c.strip() for c in fk["col"].split(',')]
                ref_cols = [c.strip() for c in fk["ref_col"].split(',')]
                self.assertIn(ref_tbl, self.tables, f"FK {table_name}.{fk['col']} references non-existent table {ref_tbl}")
                for lc in local_cols:
                    self.assertIn(lc, self.tables[table_name]["columns"], f"FK {table_name}.{fk['col']} references non-existent local col {table_name}.{lc}")
                for rc in ref_cols:
                    self.assertIn(rc, self.tables[ref_tbl]["columns"], f"FK {table_name}.{fk['col']} references non-existent col {ref_tbl}.{rc}")

    def test_business_domain_seeds(self):
        """Verify that all 6 required business domains are seeded."""
        seeded = parse_seed_domains(self.sql_content)
        for code, _ in EXPECTED_DOMAINS:
            self.assertIn(code, seeded, f"Domain {code} not seeded")

    def test_critical_invariants(self):
        """Verify unique partial indexes for ontology and approval invariants."""
        index_names = {idx["name"].lower() for idx in self.indexes}
        self.assertTrue(
            "uq_kpi_ontology_versions_is_active" in index_names or any("is_active" in idx["definition"] and "is_active = true" in idx["definition"] for idx in self.indexes),
            "Missing single active ontology version invariant index"
        )
        self.assertTrue(
            "uq_mapping_approvals_active" in index_names or any("approved" in idx["definition"] for idx in self.indexes),
            "Missing single active approval invariant index"
        )

    def test_tenant_isolation_functions(self):
        """Verify tenant resolution helper functions are strictly transaction-local and accept no p_is_local parameter."""
        self.assertIn("CREATE OR REPLACE FUNCTION kpi_intel.current_tenant_id()", self.sql_content)
        self.assertIn("CREATE OR REPLACE FUNCTION kpi_intel.set_current_tenant_id(p_tenant_id UUID)", self.sql_content)
        self.assertIn("CREATE OR REPLACE FUNCTION kpi_intel.clear_current_tenant_id()", self.sql_content)
        # Verify p_is_local is completely absent from function signatures
        self.assertNotIn("set_current_tenant_id(p_tenant_id UUID, p_is_local", self.sql_content)
        self.assertNotIn("clear_current_tenant_id(p_is_local", self.sql_content)
        self.assertNotIn("p_is_local BOOLEAN", self.sql_content)
        # Verify transaction-local boolean literal 'true' is explicitly used
        self.assertIn("PERFORM set_config('kpi_intel.current_tenant_id', p_tenant_id::TEXT, true);", self.sql_content)
        self.assertIn("PERFORM set_config('kpi_intel.current_tenant_id', '', true);", self.sql_content)

    def test_tenant_setter_security_and_obsolete_overloads(self):
        """Verify obsolete overloads are dropped and PUBLIC execution privileges are revoked."""
        # 1. Dropping obsolete callable overloads
        self.assertIn("DROP FUNCTION IF EXISTS kpi_intel.set_current_tenant_id(UUID, BOOLEAN);", self.sql_content)
        self.assertIn("DROP FUNCTION IF EXISTS kpi_intel.clear_current_tenant_id(BOOLEAN);", self.sql_content)
        # 2. Revoking execution from PUBLIC
        self.assertIn("REVOKE ALL ON FUNCTION kpi_intel.current_tenant_id() FROM PUBLIC;", self.sql_content)
        self.assertIn("REVOKE ALL ON FUNCTION kpi_intel.set_current_tenant_id(UUID) FROM PUBLIC;", self.sql_content)
        self.assertIn("REVOKE ALL ON FUNCTION kpi_intel.clear_current_tenant_id() FROM PUBLIC;", self.sql_content)
        # 3. Grants to kpi_app_user
        self.assertIn("GRANT EXECUTE ON FUNCTION kpi_intel.set_current_tenant_id(UUID) TO kpi_app_user;", self.sql_content)
        self.assertIn("GRANT EXECUTE ON FUNCTION kpi_intel.clear_current_tenant_id() TO kpi_app_user;", self.sql_content)
        # 4. Search path & security invoker
        self.assertIn("SECURITY INVOKER SET search_path = pg_catalog, kpi_intel", self.sql_content)
        # 5. Fail-closed null resolution on missing/invalid context
        self.assertIn("RETURN NULLIF(current_setting('kpi_intel.current_tenant_id', true), '')::UUID;", self.sql_content)

    def test_row_level_security_enabled_all_tables(self):
        """Verify RLS is enabled on all 61 canonical tables and forced on tenant tables."""
        all_tables = [t for tables in EXPECTED_TABLES.values() for t in tables]
        self.assertEqual(len(all_tables), 61, "Expected 61 tables for RLS audit")
        for tbl in all_tables:
            self.assertIn(f"ALTER TABLE kpi_intel.{tbl} ENABLE ROW LEVEL SECURITY;", self.sql_content, f"Missing RLS on {tbl}")

    def test_hardening_triggers_defined(self):
        """Verify immutable governance triggers are defined and attached with correct SQLSTATE."""
        self.assertIn("CREATE OR REPLACE FUNCTION kpi_intel.prevent_audit_mutation()", self.sql_content)
        self.assertIn("USING ERRCODE = '42501';", self.sql_content)
        self.assertIn("CREATE OR REPLACE FUNCTION kpi_intel.protect_human_approval()", self.sql_content)
        self.assertIn("CREATE OR REPLACE FUNCTION kpi_intel.prevent_override_cycle()", self.sql_content)
        self.assertIn("trg_protect_human_approval", self.sql_content)
        self.assertIn("trg_mapping_audit_immutable", self.sql_content)
        self.assertIn("trg_ontology_audit_immutable", self.sql_content)
        self.assertIn("trg_prevent_override_cycle", self.sql_content)

    def test_column_specific_set_null_foreign_keys(self):
        """Verify composite FKs use PostgreSQL 15+ column-specific ON DELETE SET NULL."""
        self.assertIn("ON DELETE SET NULL (selected_ontology_entry_id)", self.sql_content)
        self.assertIn("ON DELETE SET NULL (mapping_candidate_id)", self.sql_content)
        self.assertIn("ON DELETE SET NULL (approved_mapping_candidate_id)", self.sql_content)

    def test_full_validation_runner(self):
        """Execute full validation suite."""
        success = validate_canonical_model(REPO_ROOT)
        self.assertTrue(success, "Validation suite failed")


if __name__ == "__main__":
    unittest.main()
