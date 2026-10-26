"""
KPI Intelligence — Power BI Normalizer Unit Tests.
"""

import unittest
import uuid
import os
from backend.connectors.powerbi.discovery import PbipDiscovery
from backend.connectors.powerbi.tmdl_parser import TmdlParser
from backend.connectors.powerbi.report_parser import ReportParser
from backend.connectors.powerbi.normalizer import PowerBINormalizer, make_deterministic_uuid


class TestPowerBINormalizer(unittest.TestCase):

    def setUp(self):
        self.ref_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "reference"))
        self.proj = PbipDiscovery.discover(self.ref_dir)
        self.model = TmdlParser.parse_semantic_model_directory(self.proj.semantic_model_dir_path)
        self.report = ReportParser.parse_report_directory(self.proj.report_dir_path, asset_name=self.proj.asset_name)
        self.tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        self.normalizer = PowerBINormalizer(tenant_id=self.tenant_id)
        self.bundle = self.normalizer.normalize(
            project_structure=self.proj,
            tmdl_model=self.model,
            report_def=self.report,
            version_number=1
        )

    def test_deterministic_uuids(self):
        # Normalizing again with identical inputs must produce exact same UUIDs
        bundle2 = self.normalizer.normalize(
            project_structure=self.proj,
            tmdl_model=self.model,
            report_def=self.report,
            version_number=1
        )
        self.assertEqual(self.bundle.asset.asset_id, bundle2.asset.asset_id)
        self.assertEqual(self.bundle.version.asset_version_id, bundle2.version.asset_version_id)
        self.assertEqual(self.bundle.version.content_hash, bundle2.version.content_hash)
        self.assertEqual(len(self.bundle.objects), len(bundle2.objects))
        for o1, o2 in zip(self.bundle.objects, bundle2.objects):
            self.assertEqual(o1.object_id, o2.object_id)

    def test_asset_and_version(self):
        self.assertEqual(self.bundle.asset.platform, "POWER_BI")
        self.assertEqual(self.bundle.asset.asset_name, "reference")
        self.assertEqual(self.bundle.asset.tenant_id, self.tenant_id)
        self.assertEqual(self.bundle.version.version_number, 1)
        self.assertEqual(self.bundle.version.extraction_status, "SUCCESSFUL")
        self.assertIsNotNone(self.bundle.version.content_hash)

    def test_analytical_objects_hierarchy(self):
        obj_dict = {o.object_id: o for o in self.bundle.objects}
        
        # Semantic model object has no parent
        sm_obj = next(o for o in self.bundle.objects if o.object_type == "SEMANTIC_MODEL")
        self.assertIsNone(sm_obj.parent_object_id)

        # Tables have semantic model as parent
        for tbl in self.bundle.tables:
            tbl_obj = obj_dict[tbl.object_id]
            self.assertEqual(tbl_obj.parent_object_id, sm_obj.object_id)

        # Columns have their table as parent
        for col in self.bundle.columns:
            col_obj = obj_dict[col.object_id]
            self.assertEqual(col_obj.parent_object_id, col.data_table_id)

    def test_calculations_count_and_types(self):
        # 8 measures, 6 calc items, 2 calc columns = 16 calculations
        self.assertEqual(len(self.bundle.calculations), 16)
        calc_types = [c.calculation_type for c in self.bundle.calculations]
        self.assertEqual(calc_types.count("MEASURE"), 8)
        self.assertEqual(calc_types.count("CALCULATION_ITEM"), 6)
        self.assertEqual(calc_types.count("CALCULATED_COLUMN"), 2)

    def test_relationships_count(self):
        self.assertEqual(len(self.bundle.relationships), 4)

    def test_lineage_edges_extraction(self):
        # Lineage edges must include MEASURE_DEPENDENCY and RELATIONSHIP_JOIN
        edge_types = {e.edge_type for e in self.bundle.lineage_edges}
        self.assertIn("RELATIONSHIP_JOIN", edge_types)
        self.assertIn("MEASURE_DEPENDENCY", edge_types)
        self.assertGreaterEqual(len(self.bundle.lineage_edges), 20)

    def test_parser_run_and_errors(self):
        self.assertEqual(len(self.bundle.parser_runs), 1)
        pr = self.bundle.parser_runs[0]
        self.assertEqual(pr.platform, "POWER_BI")
        self.assertEqual(pr.run_status, "SUCCESSFUL")
        self.assertEqual(pr.objects_extracted, len(self.bundle.objects))
        self.assertEqual(pr.errors_count, 0)


if __name__ == "__main__":
    unittest.main()
