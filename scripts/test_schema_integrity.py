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
                ref_col = fk["ref_col"]
                self.assertIn(ref_tbl, self.tables, f"FK {table_name}.{fk['col']} references non-existent table {ref_tbl}")
                self.assertIn(ref_col, self.tables[ref_tbl]["columns"], f"FK {table_name}.{fk['col']} references non-existent col {ref_tbl}.{ref_col}")

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

    def test_full_validation_runner(self):
        """Execute full validation suite."""
        success = validate_canonical_model(REPO_ROOT)
        self.assertTrue(success, "Validation suite failed")


if __name__ == "__main__":
    unittest.main()
