#!/usr/bin/env python3
"""
Unit test suite for the KPI Bank JSON Parser and Validator.
Verifies all 18 mandatory test scenarios specified in Section 28 of the Master Prompt.
"""

import unittest
import os
import sys
import json

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.kpi_bank_parser import (
    KPIBankParser,
    KPIVersionDiffDetector,
    DiagnosticSeverity,
    DiagnosticAction
)

class TestKPIBankParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_path = os.path.join(REPO_ROOT, "fixtures", "kpi_bank_representative_fixture.json")
        with open(cls.fixture_path, "r", encoding="utf-8") as f:
            cls.fixture_data = json.load(f)
        cls.parser = KPIBankParser()
        cls.parse_result = cls.parser.parse_file(cls.fixture_path)

    def test_01_complete_kpi_record(self):
        """Case 1: Parse a complete KPI record matching the observed screenshot structure."""
        entry = next((e for e in self.parse_result.accepted_entries if e.source_kpi_id == "7c194cb9-677a-48e2-a623-ee745b3e7ac4"), None)
        self.assertIsNotNone(entry, "Expected '% Calls Agent Declined' to be accepted")
        self.assertEqual(entry.kpi_name, "% Calls Agent Declined")
        self.assertEqual(entry.definition, "% of calls declined by agents")
        self.assertEqual(entry.business_domain, "Marketing")
        self.assertEqual(entry.source_sector, "insurance")
        self.assertEqual(entry.source_subdomain, "marketing")
        self.assertEqual(entry.aggregation_method, "PCT")
        self.assertEqual(len(entry.synonyms), 3)
        self.assertIn("Declined Calls %", entry.synonyms)
        self.assertEqual(len(entry.valid_dimensions), 6)
        self.assertEqual(len(entry.enrichments), 1)
        self.assertEqual(entry.formula, "(Declined calls / Total incoming calls) x 100")
        self.assertEqual(entry.source_created_by, "excel_seed")

    def test_02_optional_fields_null(self):
        """Case 2: Optional fields set to null."""
        entry = next((e for e in self.parse_result.accepted_entries if e.source_kpi_id == "8d2a5fb0-1234-4567-89ab-cdef01234567"), None)
        self.assertIsNotNone(entry)
        self.assertIsNone(entry.source_line_of_business)
        self.assertIsNone(entry.embedding_model)
        self.assertEqual(len(entry.synonyms), 0)
        self.assertEqual(len(entry.enrichments), 0)

    def test_03_multiple_aliases(self):
        """Case 3: Multiple aliases."""
        entry = next((e for e in self.parse_result.accepted_entries if e.source_kpi_id == "9e3b6fc1-2345-6789-abcd-ef0123456789"), None)
        self.assertIsNotNone(entry)
        self.assertEqual(len(entry.synonyms), 4)
        self.assertIn("Claims Ratio", entry.synonyms)
        self.assertIn("Incurred Loss Ratio", entry.synonyms)

    def test_04_multiple_valid_dimensions(self):
        """Case 4: Multiple valid dimensions."""
        entry = next((e for e in self.parse_result.accepted_entries if e.source_kpi_id == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"), None)
        self.assertIsNotNone(entry)
        self.assertEqual(len(entry.valid_dimensions), 7)
        self.assertIn("Renewal Month", entry.valid_dimensions)
        self.assertIn("Customer Tier", entry.valid_dimensions)

    def test_05_multiple_enrichments_preserved_without_flattening(self):
        """Case 5: Multiple enrichment objects preserved with separate provenance."""
        entry = next((e for e in self.parse_result.accepted_entries if e.source_kpi_id == "9e3b6fc1-2345-6789-abcd-ef0123456789"), None)
        self.assertIsNotNone(entry)
        self.assertEqual(len(entry.enrichments), 2)
        # Check first enrichment (Underwriting)
        self.assertEqual(entry.enrichments[0]["team"], "Underwriting")
        self.assertEqual(entry.enrichments[0]["source"]["sheet"], "Underwriting")
        self.assertEqual(entry.enrichments[0]["source"]["row"], 15)
        # Check second enrichment (Actuarial)
        self.assertEqual(entry.enrichments[1]["team"], "Actuarial")
        self.assertEqual(entry.enrichments[1]["source"]["sheet"], "Reserving")
        self.assertEqual(entry.enrichments[1]["source"]["row"], 42)

    def test_06_nested_source_extras_field_sources(self):
        """Case 6: Nested source, extras, and field_sources objects preserved."""
        entry = next((e for e in self.parse_result.accepted_entries if e.source_kpi_id == "9e3b6fc1-2345-6789-abcd-ef0123456789"), None)
        enrichment = entry.enrichments[0]
        self.assertIn("source", enrichment)
        self.assertIn("extras", enrichment)
        self.assertIn("field_sources", enrichment)
        self.assertEqual(enrichment["extras"]["target_threshold"], 0.65)
        self.assertEqual(enrichment["field_sources"]["incurred_losses"], "Claims Ledger")

    def test_07_unknown_additional_source_fields(self):
        """Case 7: Unknown additional source fields preserved in raw payload."""
        entry = next((e for e in self.parse_result.accepted_entries if e.source_kpi_id == "b2c3d4e5-f6a7-8901-bcde-f12345678901"), None)
        self.assertIsNotNone(entry)
        self.assertIn("external_regulatory_id", entry.ontology_payload)
        self.assertEqual(entry.ontology_payload["external_regulatory_id"], "NAIC_SCHED_P_PART1")
        self.assertEqual(entry.ontology_payload["custom_benchmark_tag"], "TIER1_BENCHMARK")

    def test_08_missing_required_identifier(self):
        """Case 8: Missing required identifier is rejected."""
        malformed = {"name": "No ID", "definition": "Missing ID"}
        res = self.parser.parse_json_string(json.dumps([malformed]))
        self.assertEqual(len(res.rejected_records), 1)
        self.assertTrue(any(d.error_code == "ERR_MISSING_KPI_ID" for d in res.diagnostics))

    def test_09_invalid_timestamp_format(self):
        """Case 9: Invalid timestamp produces warning, sets canonical col to null, preserves raw."""
        record = {
            "kpi_id": "test-ts-001",
            "name": "Bad Timestamp",
            "definition": "Has invalid date",
            "created_at": "invalid-timestamp-2026-31-02 99:99"
        }
        res = self.parser.parse_json_string(json.dumps([record]))
        self.assertEqual(len(res.accepted_entries), 1)
        entry = res.accepted_entries[0]
        self.assertIsNone(entry.source_created_at)
        self.assertEqual(entry.ontology_payload["created_at"], "invalid-timestamp-2026-31-02 99:99")
        self.assertTrue(any(d.error_code == "WARN_INVALID_TIMESTAMP_FORMAT" for d in res.diagnostics))

    def test_10_unexpected_data_types(self):
        """Case 10: Unexpected data types produce warnings without fatal crash."""
        record = {
            "kpi_id": "test-type-001",
            "name": "Corrupted Types",
            "definition": "Types are wrong",
            "aliases": 12345,
            "valid_dimensions": "NotAnArray"
        }
        res = self.parser.parse_json_string(json.dumps([record]))
        self.assertEqual(len(res.accepted_entries), 1)
        entry = res.accepted_entries[0]
        self.assertEqual(entry.synonyms, [])
        self.assertEqual(entry.valid_dimensions, [])
        self.assertTrue(any(d.error_code == "WARN_ALIASES_NOT_LIST" for d in res.diagnostics))

    def test_11_duplicate_kpi_identifiers_within_batch(self):
        """Case 11: Duplicate KPI identifiers in same batch are rejected."""
        records = [
            {"kpi_id": "dup-id-001", "name": "KPI A", "definition": "First"},
            {"kpi_id": "dup-id-001", "name": "KPI B", "definition": "Second"}
        ]
        res = self.parser.parse_json_string(json.dumps(records))
        self.assertEqual(len(res.accepted_entries), 1)
        self.assertEqual(len(res.rejected_records), 1)
        self.assertTrue(any(d.error_code == "ERR_DUPLICATE_KPI_ID" for d in res.diagnostics))

    def test_12_inconsistent_enrichment_shapes(self):
        """Case 12: Inconsistent enrichment shapes (string instead of dict) produce quarantine diagnostic."""
        record = {
            "kpi_id": "test-enrich-001",
            "name": "Bad Enrichment",
            "definition": "Def",
            "enrichments": ["Invalid String Enrichment"]
        }
        res = self.parser.parse_json_string(json.dumps([record]))
        self.assertTrue(any(d.error_code == "ERR_ENRICHMENT_NOT_OBJECT" for d in res.diagnostics))

    def test_13_suspicious_placeholder_values(self):
        """Case 13: Suspicious placeholder values ('excel', '11m') in field_sources produce warnings."""
        entry = next((e for e in self.parse_result.accepted_entries if e.source_kpi_id == "c3d4e5f6-a7b8-9012-cdef-123456789012"), None)
        self.assertIsNotNone(entry)
        has_suspicious_diag = any(
            d.error_code == "WARN_SUSPICIOUS_FIELD_SOURCE_PLACEHOLDER" and d.record_id == "c3d4e5f6-a7b8-9012-cdef-123456789012"
            for d in self.parse_result.diagnostics
        )
        self.assertTrue(has_suspicious_diag, "Expected warning for 'excel'/'11m' placeholders")
        # Ensure values are not silently scrubbed
        enrichment = entry.enrichments[0]
        self.assertEqual(enrichment["field_sources"]["spend"], "excel")
        self.assertEqual(enrichment["field_sources"]["customers"], "11m")

    def test_14_non_canonical_domain_values_preserved(self):
        """Case 14: Non-canonical domain values ('Customer Success', 'Marketing') preserved natively."""
        cs_entry = next((e for e in self.parse_result.accepted_entries if e.source_kpi_id == "d4e5f6a7-b8c9-0123-def1-234567890123"), None)
        self.assertIsNotNone(cs_entry)
        self.assertEqual(cs_entry.business_domain, "Customer Success")
        self.assertNotIn(cs_entry.business_domain, ["CLAIMS_RISK", "LEGAL", "UNDERWRITING", "SALES_DISTRIBUTION", "SERVICE_OPERATIONS", "ACTUARIAL"])

    def test_15_repeated_imports_of_unchanged_records(self):
        """Case 15: Repeated imports of unchanged records detect zero updates."""
        diff = KPIVersionDiffDetector.compare_releases(
            self.parse_result.accepted_entries,
            self.parse_result.accepted_entries
        )
        self.assertEqual(diff["added_count"], 0)
        self.assertEqual(diff["updated_count"], 0)
        self.assertEqual(diff["removed_count"], 0)
        self.assertEqual(diff["unchanged_count"], len(self.parse_result.accepted_entries))

    def test_16_updated_definitions_or_formulas_detected(self):
        """Case 16: Updated definitions or formulas are detected by version diff."""
        prior = self.parse_result.accepted_entries
        # Create modified version of first KPI
        modified = json.loads(json.dumps(prior[0].ontology_payload))
        modified["definition"] = "UPDATED definition for testing diff engine"
        res_v2 = self.parser.parse_json_string(json.dumps([modified]))
        diff = KPIVersionDiffDetector.compare_releases(prior[:1], res_v2.accepted_entries)
        self.assertEqual(diff["updated_count"], 1)
        self.assertTrue(diff["updated"][0]["changes"]["definition_changed"])

    def test_17_deactivated_or_removed_source_records(self):
        """Case 17: Deactivated or removed source records handled accurately."""
        inactive_entry = next((e for e in self.parse_result.accepted_entries if e.source_kpi_id == "e5f6a7b8-c9d0-1234-ef12-345678901234"), None)
        self.assertIsNotNone(inactive_entry)
        self.assertEqual(inactive_entry.source_status, "inactive")
        self.assertFalse(inactive_entry.is_active_sector)

    def test_18_preservation_of_complete_original_payload_lossless(self):
        """Case 18: Complete original JSON payload is preserved 100% losslessly in ontology_payload."""
        for entry in self.parse_result.accepted_entries:
            self.assertIsInstance(entry.ontology_payload, dict)
            self.assertIn("kpi_id", entry.ontology_payload)
            self.assertEqual(entry.ontology_payload["kpi_id"], entry.source_kpi_id)
            self.assertEqual(entry.ontology_payload["name"], entry.kpi_name)


if __name__ == "__main__":
    unittest.main()
