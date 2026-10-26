"""
KPI Intelligence — Power BI Persistence Unit Tests.
"""

import unittest
import uuid
import os
from backend.connectors.powerbi.discovery import PbipDiscovery
from backend.connectors.powerbi.tmdl_parser import TmdlParser
from backend.connectors.powerbi.report_parser import ReportParser
from backend.connectors.powerbi.normalizer import PowerBINormalizer
from backend.ingestion.persistence import CanonicalPersistenceService, sort_analytical_objects_topologically


class TestPowerBiPersistence(unittest.TestCase):

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
        self.persister = CanonicalPersistenceService(tenant_id=self.tenant_id)

    def test_topological_sort_analytical_objects(self):
        sorted_objs = sort_analytical_objects_topologically(self.bundle.objects)
        self.assertEqual(len(sorted_objs), len(self.bundle.objects))

        # Assert every parent appears BEFORE its children in sorted_objs
        seen_ids = set()
        for obj in sorted_objs:
            if obj.parent_object_id:
                self.assertIn(
                    obj.parent_object_id,
                    seen_ids,
                    f"Parent {obj.parent_object_id} must appear before child {obj.object_id} ({obj.canonical_name})"
                )
            seen_ids.add(obj.object_id)

    def test_generate_transactional_sql_structure(self):
        sql = self.persister.generate_transactional_sql(self.bundle)

        # 1. Must start with transaction and set_current_tenant_id
        self.assertIn("BEGIN;", sql)
        self.assertIn(f"SELECT kpi_intel.set_current_tenant_id('{self.tenant_id}'::uuid);", sql)
        self.assertTrue(sql.rstrip().endswith("COMMIT;"))

        # 2. Must contain inserts for all subsystems
        self.assertIn("INSERT INTO kpi_intel.assets", sql)
        self.assertIn("INSERT INTO kpi_intel.asset_versions", sql)
        self.assertIn("INSERT INTO kpi_intel.source_artifacts", sql)
        self.assertIn("INSERT INTO kpi_intel.analytical_objects", sql)
        self.assertIn("INSERT INTO kpi_intel.reports", sql)
        self.assertIn("INSERT INTO kpi_intel.report_pages", sql)
        self.assertIn("INSERT INTO kpi_intel.semantic_models", sql)
        self.assertIn("INSERT INTO kpi_intel.data_tables", sql)
        self.assertIn("INSERT INTO kpi_intel.data_columns", sql)
        self.assertIn("INSERT INTO kpi_intel.calculations", sql)
        self.assertIn("INSERT INTO kpi_intel.relationships", sql)
        self.assertIn("INSERT INTO kpi_intel.model_partitions", sql)
        self.assertIn("INSERT INTO kpi_intel.named_expressions", sql)
        self.assertIn("INSERT INTO kpi_intel.metadata_lineage_edges", sql)
        self.assertIn("INSERT INTO kpi_intel.parser_runs", sql)

    def test_declarative_persist_summary(self):
        res = self.persister.persist(self.bundle, connection=None)
        self.assertEqual(res["tenant_id"], str(self.tenant_id))
        self.assertEqual(res["tables_persisted"], 15)
        self.assertEqual(res["columns_persisted"], 208)
        self.assertEqual(res["calculations_persisted"], 16)
        self.assertEqual(res["relationships_persisted"], 4)
        self.assertFalse(res["executed_live"])


if __name__ == "__main__":
    unittest.main()
