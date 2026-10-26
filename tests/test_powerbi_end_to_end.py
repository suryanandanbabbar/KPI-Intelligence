"""
KPI Intelligence — Power BI End-to-End Connector Tests.
"""

import unittest
import uuid
import os

from backend.connectors.base import PlatformType, CapabilityStatus
from backend.connectors.registry import ConnectorRegistry
from backend.connectors.powerbi.connector import PowerBIConnector
from backend.ingestion.service import IngestionService


class TestPowerBiEndToEnd(unittest.TestCase):

    def setUp(self):
        self.ref_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "reference"))
        self.tenant_id = uuid.UUID("a0000000-0000-0000-0000-000000000001")

    def test_registry_configuration(self):
        # Power BI must be supported and registered
        self.assertTrue(ConnectorRegistry.is_supported(PlatformType.POWER_BI))
        connector = ConnectorRegistry.get(PlatformType.POWER_BI)
        self.assertIsInstance(connector, PowerBIConnector)

        # Other platforms must be registered as unsupported
        self.assertFalse(ConnectorRegistry.is_supported(PlatformType.TABLEAU))
        self.assertFalse(ConnectorRegistry.is_supported(PlatformType.EXCEL))
        self.assertFalse(ConnectorRegistry.is_supported(PlatformType.THOUGHTSPOT))
        self.assertFalse(ConnectorRegistry.is_supported(PlatformType.MICROSTRATEGY))

        # Check declared capabilities
        caps = connector.get_capabilities()
        self.assertGreaterEqual(len(caps), 5)
        cap_statuses = {c.capability_status for c in caps}
        self.assertIn(CapabilityStatus.SUPPORTED, cap_statuses)

    def test_end_to_end_ingestion_reference_project(self):
        service = IngestionService(tenant_id=self.tenant_id)
        summary = service.ingest_project(
            source_path=self.ref_dir,
            platform=PlatformType.POWER_BI,
            version_number=1,
            generate_sql_only=True
        )

        self.assertEqual(summary.status, "SUCCESSFUL")
        self.assertEqual(summary.platform, "POWER_BI")
        self.assertEqual(summary.asset_name, "reference")
        self.assertEqual(summary.version_number, 1)

        # Verify verified counts
        stats = summary.stats
        self.assertEqual(stats["source_artifacts"], 39)
        self.assertEqual(stats["analytical_objects"], 251)
        self.assertEqual(stats["reports"], 1)
        self.assertEqual(stats["report_pages"], 1)
        self.assertEqual(stats["bookmarks"], 4)
        self.assertEqual(stats["semantic_models"], 1)
        self.assertEqual(stats["data_tables"], 15)
        self.assertEqual(stats["data_columns"], 208)
        self.assertEqual(stats["calculations"], 16)
        self.assertEqual(stats["relationships"], 4)
        self.assertEqual(stats["model_partitions"], 14)
        self.assertEqual(stats["named_expressions"], 1)
        self.assertEqual(stats["metadata_lineage_edges"], 22)

        # Verify SQL script generated
        self.assertIsNotNone(summary.sql_script)
        self.assertIn(f"SELECT kpi_intel.set_current_tenant_id('{self.tenant_id}'::uuid);", summary.sql_script)
        self.assertIn("BEGIN;", summary.sql_script)
        self.assertIn("COMMIT;", summary.sql_script)

    def test_unsupported_platform_raises_error(self):
        service = IngestionService(tenant_id=self.tenant_id)
        with self.assertRaises(NotImplementedError):
            service.ingest_project(
                source_path=self.ref_dir,
                platform=PlatformType.TABLEAU,
                generate_sql_only=True
            )


if __name__ == "__main__":
    unittest.main()
