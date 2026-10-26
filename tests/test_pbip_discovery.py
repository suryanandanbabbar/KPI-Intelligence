"""
KPI Intelligence — Power BI Discovery Unit Tests.
"""

import unittest
import os
from backend.connectors.powerbi.discovery import (
    PbipDiscovery,
    detect_artifact_type,
    compute_file_sha256,
)


class TestPbipDiscovery(unittest.TestCase):

    def setUp(self):
        self.ref_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "reference"))

    def test_discover_from_directory(self):
        proj = PbipDiscovery.discover(self.ref_dir)
        self.assertEqual(proj.asset_name, "reference")
        self.assertTrue(proj.pbip_file_path.endswith("reference.pbip"))
        self.assertIsNotNone(proj.report_dir_path)
        self.assertTrue(proj.report_dir_path.endswith("reference.Report"))
        self.assertIsNotNone(proj.semantic_model_dir_path)
        self.assertTrue(proj.semantic_model_dir_path.endswith("reference.SemanticModel"))
        self.assertGreater(len(proj.artifacts), 20)
        self.assertEqual(len(proj.diagnostics), 0)

    def test_discover_from_file_path(self):
        pbip_path = os.path.join(self.ref_dir, "reference.pbip")
        proj = PbipDiscovery.discover(pbip_path)
        self.assertEqual(proj.asset_name, "reference")
        self.assertEqual(proj.pbip_file_path, pbip_path)
        self.assertIsNotNone(proj.report_dir_path)
        self.assertIsNotNone(proj.semantic_model_dir_path)

    def test_nonexistent_path(self):
        proj = PbipDiscovery.discover("/path/to/nowhere/nonexistent")
        self.assertGreater(len(proj.diagnostics), 0)
        self.assertEqual(proj.diagnostics[0].code, "SOURCE_PATH_NOT_FOUND")

    def test_detect_artifact_type(self):
        art_type, mime, supp = detect_artifact_type("model.pbip")
        self.assertEqual(art_type, "PBIP_PROJECT_MANIFEST")
        self.assertTrue(supp)

        art_type, mime, supp = detect_artifact_type("definition.pbir")
        self.assertEqual(art_type, "PBIR_REPORT_DEFINITION")
        self.assertTrue(supp)

        art_type, mime, supp = detect_artifact_type("tables/sales.tmdl")
        self.assertEqual(art_type, "TMDL_TABLE_DEFINITION")
        self.assertTrue(supp)

        art_type, mime, supp = detect_artifact_type("relationships.tmdl")
        self.assertEqual(art_type, "TMDL_RELATIONSHIPS")
        self.assertTrue(supp)

        art_type, mime, supp = detect_artifact_type(".DS_Store")
        self.assertEqual(art_type, "OS_METADATA")
        self.assertFalse(supp)


if __name__ == "__main__":
    unittest.main()
