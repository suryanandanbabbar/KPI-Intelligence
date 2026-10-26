"""
KPI Intelligence — Negative Unit Tests for Cross-Representation Validator.

Verifies that deliberate corruptions and regressions are caught and cause validation failure:
1. Invalid target container name.
2. Missing canonical column from traceability matrix.
3. Extra/unknown canonical column in traceability matrix.
4. Non-lossless status on a mapped field.
5. Unresolved top-level JSON path against contract attributes.
6. Unresolved nested collection JSON path.
7. Governance audit contract with finite TTL (violating permanent retention).
8. Operational diagnostics contract with permanent TTL (violating 90-day retention).
9. Missing DocumentType contract registration.
"""

import os
import csv
import copy
import tempfile
import unittest
from unittest.mock import patch

from scripts.validate_cross_representation import (
    validate_traceability_matrix,
    validate_traceability_runtime_values,
    validate_document_contracts,
    validate_cosmos_contracts_ttl,
    CSV_PATH,
    TYPE_TO_CLASSES,
)
from backend.contracts import (
    DocumentType,
    MappingAuditEventDocument,
    ParserRunDocument,
)


class TestValidatorNegative(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Read the real baseline CSV
        cls.baseline_rows = []
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            cls.fieldnames = reader.fieldnames
            for r in reader:
                cls.baseline_rows.append(r)

    def _write_temp_csv(self, rows) -> str:
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", encoding="utf-8")
        writer = csv.DictWriter(tmp, fieldnames=self.fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        tmp.close()
        return tmp.name

    def test_invalid_target_container_fails(self):
        """Corrupting target_container to an invalid name must fail validation."""
        corrupted_rows = [copy.deepcopy(r) for r in self.baseline_rows]
        corrupted_rows[0]["target_container"] = "corrupted_container_xyz"

        tmp_path = self._write_temp_csv(corrupted_rows)
        try:
            is_valid, details = validate_traceability_matrix(tmp_path)
            self.assertFalse(is_valid)
            self.assertGreater(details["invalid_containers_count"], 0)
        finally:
            os.unlink(tmp_path)

    def test_missing_canonical_column_fails(self):
        """Omitting a required canonical column from the matrix must fail validation."""
        corrupted_rows = [copy.deepcopy(r) for r in self.baseline_rows[1:]]  # Drop first row

        tmp_path = self._write_temp_csv(corrupted_rows)
        try:
            is_valid, details = validate_traceability_matrix(tmp_path)
            self.assertFalse(is_valid)
            self.assertGreater(len(details["missing_in_csv"]), 0)
        finally:
            os.unlink(tmp_path)

    def test_extra_non_canonical_column_fails(self):
        """Adding a column that does not exist in the canonical schema must fail validation."""
        corrupted_rows = [copy.deepcopy(r) for r in self.baseline_rows]
        extra_row = copy.deepcopy(corrupted_rows[0])
        extra_row["source_column"] = "nonexistent_bogus_col_123"
        corrupted_rows.append(extra_row)

        tmp_path = self._write_temp_csv(corrupted_rows)
        try:
            is_valid, details = validate_traceability_matrix(tmp_path)
            self.assertFalse(is_valid)
            self.assertGreater(len(details["extra_in_csv"]), 0)
        finally:
            os.unlink(tmp_path)

    def test_non_lossless_status_fails(self):
        """Setting lossless_status to 'lossy' must fail validation."""
        corrupted_rows = [copy.deepcopy(r) for r in self.baseline_rows]
        corrupted_rows[0]["lossless_status"] = "lossy"

        tmp_path = self._write_temp_csv(corrupted_rows)
        try:
            is_valid, details = validate_traceability_matrix(tmp_path)
            self.assertFalse(is_valid)
            self.assertGreater(details["non_lossless_count"], 0)
        finally:
            os.unlink(tmp_path)

    def test_unresolved_top_level_json_path_fails(self):
        """Specifying a nonexistent top-level JSON path must fail validation."""
        corrupted_rows = [copy.deepcopy(r) for r in self.baseline_rows]
        corrupted_rows[0]["target_json_path"] = "c.nonexistent_bogus_field_xyz"

        tmp_path = self._write_temp_csv(corrupted_rows)
        try:
            is_valid, details = validate_traceability_matrix(tmp_path)
            self.assertFalse(is_valid)
            self.assertGreater(details["unresolved_paths_count"], 0)
        finally:
            os.unlink(tmp_path)

    def test_unresolved_nested_collection_field_fails(self):
        """Specifying a nonexistent field inside an embedded collection must fail validation."""
        corrupted_rows = [copy.deepcopy(r) for r in self.baseline_rows]
        # Find a row targeting a collection
        target_idx = None
        for i, r in enumerate(corrupted_rows):
            if "[]" in r["target_json_path"]:
                target_idx = i
                break
        self.assertIsNotNone(target_idx)

        coll = corrupted_rows[target_idx]["target_json_path"].split(".")[1]
        corrupted_rows[target_idx]["target_json_path"] = f"c.{coll}.nonexistent_bogus_field_xyz"

        tmp_path = self._write_temp_csv(corrupted_rows)
        try:
            is_valid, details = validate_traceability_matrix(tmp_path)
            self.assertFalse(is_valid)
            self.assertGreater(details["unresolved_paths_count"], 0)
        finally:
            os.unlink(tmp_path)

    def test_invalid_governance_audit_ttl_fails(self):
        """MappingAuditEventDocument with finite TTL must fail validation."""
        with patch.object(MappingAuditEventDocument, "__init__", lambda self, **kw: setattr(self, "ttl", 3600)):
            is_valid, details = validate_cosmos_contracts_ttl()
            self.assertFalse(is_valid)
            self.assertFalse(details["audit_retention_permanent"])

    def test_invalid_operational_diagnostics_ttl_fails(self):
        """ParserRunDocument with infinite TTL must fail validation."""
        with patch.object(ParserRunDocument, "__init__", lambda self, **kw: setattr(self, "ttl", -1)):
            is_valid, details = validate_cosmos_contracts_ttl()
            self.assertFalse(is_valid)
            self.assertFalse(details["operational_retention_transient"])

    def test_missing_document_contract_registration_fails(self):
        """Missing contract mapping in TYPE_TO_CLASSES must fail validation."""
        mock_classes = copy.deepcopy(TYPE_TO_CLASSES)
        mock_classes.pop("asset", None)
        with patch.dict("scripts.validate_cross_representation.TYPE_TO_CLASSES", mock_classes, clear=True):
            is_valid, details = validate_document_contracts()
            self.assertFalse(is_valid)
            self.assertIn("asset", details["missing_types"])

    def test_alias_only_registration_without_registry_entry_fails(self):
        """Registering a table in TABLE_ALIASES without CANONICAL_MIGRATION_REGISTRY entry fails."""
        from scripts.validate_cross_representation import validate_migration_coverage
        from backend.migration.dispositions import CANONICAL_MIGRATION_REGISTRY

        # Simulate removing 'reports' from CANONICAL_MIGRATION_REGISTRY while remaining in TABLE_ALIASES
        mock_reg = copy.deepcopy(CANONICAL_MIGRATION_REGISTRY)
        mock_reg.pop("reports", None)
        with patch.dict("scripts.validate_cross_representation.CANONICAL_MIGRATION_REGISTRY", mock_reg, clear=True):
            is_valid, details = validate_migration_coverage()
            self.assertFalse(is_valid)
            self.assertIn("reports", details["missing_in_registry"])

    def test_missing_handler_method_on_migrator_fails(self):
        """Specifying a non-existent handler on CANONICAL_MIGRATION_REGISTRY fails validation."""
        from scripts.validate_cross_representation import validate_migration_coverage
        from backend.migration.dispositions import CANONICAL_MIGRATION_REGISTRY, TableMigrationDisposition, MigrationDispositionType

        mock_reg = copy.deepcopy(CANONICAL_MIGRATION_REGISTRY)
        mock_reg["reports"] = TableMigrationDisposition(
            source_table="reports",
            disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
            target_container=CANONICAL_MIGRATION_REGISTRY["reports"].target_container,
            target_document_type=CANONICAL_MIGRATION_REGISTRY["reports"].target_document_type,
            handler_function_name="_nonexistent_bogus_handler_123",
        )
        with patch.dict("scripts.validate_cross_representation.CANONICAL_MIGRATION_REGISTRY", mock_reg, clear=True):
            is_valid, details = validate_migration_coverage()
            self.assertFalse(is_valid)
            self.assertGreater(len(details["unhandled_tables"]), 0)
            self.assertEqual(details["unhandled_tables"][0][0], "reports")

    def test_invalid_disposition_specification_fails(self):
        """An INDEPENDENTLY_PERSISTED table missing target_container fails validation."""
        from scripts.validate_cross_representation import validate_migration_coverage
        from backend.migration.dispositions import CANONICAL_MIGRATION_REGISTRY, TableMigrationDisposition, MigrationDispositionType

        mock_reg = copy.deepcopy(CANONICAL_MIGRATION_REGISTRY)
        mock_reg["reports"] = TableMigrationDisposition(
            source_table="reports",
            disposition=MigrationDispositionType.INDEPENDENTLY_PERSISTED,
            target_container=None,
            target_document_type=None,
            handler_function_name="_process_reports",
        )
        with patch.dict("scripts.validate_cross_representation.CANONICAL_MIGRATION_REGISTRY", mock_reg, clear=True):
            is_valid, details = validate_migration_coverage()
            self.assertFalse(is_valid)
            self.assertGreater(len(details["invalid_dispositions"]), 0)

    def test_migration_execution_failure_fails_validator(self):
        """A failure during deterministic synthetic migration execution causes validator failure."""
        from scripts.validate_cross_representation import validate_migration_coverage
        from scripts.migrate_postgres_to_cosmos import PostgresToCosmosMigrator

        def faulty_process_assets(self, raw_rows, **kwargs):
            raise RuntimeError("Deliberate injection failure in _process_assets")

        with patch.object(PostgresToCosmosMigrator, "_process_assets", faulty_process_assets):
            is_valid, details = validate_migration_coverage()
            self.assertFalse(is_valid)
            self.assertFalse(details["execution_passed"])
            self.assertGreater(details["execution_stats"]["failed"], 0)
            self.assertIn("assets", details["execution_stats"]["failed_tables"])

    def test_serialized_value_mismatch_fails_runtime_validation(self):
        """A mismatch between canonical source canary value and serialized output fails runtime validation."""
        from scripts.migrate_postgres_to_cosmos import PostgresToCosmosMigrator

        orig_process = PostgresToCosmosMigrator._process_assets

        def corrupted_process_assets(migrator_self, raw_rows, **kwargs):
            docs = orig_process(migrator_self, raw_rows, **kwargs)
            for d in docs:
                d.asset_name = "corrupted_non_matching_asset_name_value"
            return docs

        with patch.object(PostgresToCosmosMigrator, "_process_assets", corrupted_process_assets):
            is_valid, details = validate_traceability_runtime_values()
            self.assertFalse(is_valid)
            self.assertGreater(len(details["value_mismatches"]), 0)
            mismatch_tables = [m[0] for m in details["value_mismatches"]]
            mismatch_cols = [m[1] for m in details["value_mismatches"]]
            self.assertIn("assets", mismatch_tables)
            self.assertIn("asset_name", mismatch_cols)

    def test_missing_serialized_field_fails_runtime_validation(self):
        """Omitting a required mapped field from serialized document fails runtime validation."""
        from scripts.migrate_postgres_to_cosmos import PostgresToCosmosMigrator

        orig_process = PostgresToCosmosMigrator._process_assets

        def missing_field_process_assets(migrator_self, raw_rows, **kwargs):
            docs = orig_process(migrator_self, raw_rows, **kwargs)
            for d in docs:
                orig_to_dict = d.to_dict
                def patched_to_dict():
                    res = orig_to_dict()
                    res.pop("asset_name", None)
                    return res
                d.to_dict = patched_to_dict
            return docs

        with patch.object(PostgresToCosmosMigrator, "_process_assets", missing_field_process_assets):
            is_valid, details = validate_traceability_runtime_values()
            self.assertFalse(is_valid)
            self.assertGreater(len(details["missing_target_values"]), 0)
            missing_cols = [m[1] for m in details["missing_target_values"]]
            self.assertIn("asset_name", missing_cols)


if __name__ == "__main__":
    unittest.main()

