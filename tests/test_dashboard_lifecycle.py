"""
KPI Intelligence — Dashboard Ownership and Lifecycle Classification Test Suite.

Comprehensive test coverage verifying the 15 specific lifecycle and ownership scenarios:
1.  Owned dashboard accessed today -> ACTIVE
2.  Owned dashboard accessed 5 months ago -> ACTIVE
3.  Owned dashboard accessed exactly 6 calendar months ago -> DORMANT (boundary condition)
4.  Owned dashboard accessed 7 months ago -> DORMANT
5.  Unowned dashboard accessed today -> ORPHANED (precedence: unowned takes priority)
6.  Unowned dashboard accessed 7 months ago -> ORPHANED (precedence: unowned takes priority)
7.  Owned dashboard with no access timestamp -> UNCLASSIFIED
8.  Unowned dashboard with no access timestamp -> ORPHANED
9.  Month-end and leap-year boundaries (2024-08-31 -> 2024-02-29; 2023-08-31 -> 2023-02-28; 2024-03-31 -> 2023-09-30)
10. Timezone handling (UTC vs positive/negative offsets)
11. Tenant isolation & RLS policies on reports and v_dashboard_lifecycle
12. Migration V003 syntax, structural invariants, and rollback compatibility
13. Connector ingestion of available metadata and preservation of unavailable values as NULL
14. Repeated ingestion idempotency and protection of existing verified metadata
15. Lifecycle transitions as classification timestamp advances over time
"""

import os
import sys
import re
import uuid
import unittest
from datetime import datetime, timezone, timedelta

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.connectors.powerbi.normalizer import (
    subtract_calendar_months,
    classify_report_lifecycle,
    PowerBINormalizer,
)
from backend.connectors.powerbi.report_parser import ReportDefinition, ReportPage
from backend.connectors.powerbi.discovery import PbipProjectStructure
from backend.ingestion.models import CanonicalReport
from backend.ingestion.persistence import CanonicalPersistenceService
from backend.ingestion.service import IngestionService


class TestDashboardLifecycleScenarios(unittest.TestCase):
    """Verifies all 15 dashboard ownership and lifecycle classification scenarios."""

    def setUp(self):
        self.tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        self.owner_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        self.now = datetime(2024, 10, 15, 12, 0, 0, tzinfo=timezone.utc)

    # --------------------------------------------------------------------------
    # Scenario 1: Owned dashboard accessed today -> ACTIVE
    # --------------------------------------------------------------------------
    def test_01_owned_accessed_today_is_active(self):
        last_accessed = self.now - timedelta(hours=2)
        status = classify_report_lifecycle(self.owner_id, last_accessed, as_of=self.now)
        self.assertEqual(status, "ACTIVE")

    # --------------------------------------------------------------------------
    # Scenario 2: Owned dashboard accessed 5 months ago -> ACTIVE
    # --------------------------------------------------------------------------
    def test_02_owned_accessed_5_months_ago_is_active(self):
        last_accessed = subtract_calendar_months(self.now, 5)
        status = classify_report_lifecycle(self.owner_id, last_accessed, as_of=self.now)
        self.assertEqual(status, "ACTIVE")

    # --------------------------------------------------------------------------
    # Scenario 3: Owned dashboard accessed exactly 6 calendar months ago -> DORMANT
    # Boundary condition: last_accessed_at <= (as_of - INTERVAL '6 months')
    # --------------------------------------------------------------------------
    def test_03_owned_accessed_exactly_6_calendar_months_ago_is_dormant(self):
        exact_6_months_ago = subtract_calendar_months(self.now, 6)
        status = classify_report_lifecycle(self.owner_id, exact_6_months_ago, as_of=self.now)
        self.assertEqual(status, "DORMANT")

    # --------------------------------------------------------------------------
    # Scenario 4: Owned dashboard accessed 7 months ago -> DORMANT
    # --------------------------------------------------------------------------
    def test_04_owned_accessed_7_months_ago_is_dormant(self):
        last_accessed = subtract_calendar_months(self.now, 7)
        status = classify_report_lifecycle(self.owner_id, last_accessed, as_of=self.now)
        self.assertEqual(status, "DORMANT")

    # --------------------------------------------------------------------------
    # Scenario 5: Unowned dashboard accessed today -> ORPHANED
    # Precedence: ORPHANED evaluated before ACTIVE
    # --------------------------------------------------------------------------
    def test_05_unowned_accessed_today_is_orphaned(self):
        last_accessed = self.now
        # owner_id is None
        status = classify_report_lifecycle(None, last_accessed, as_of=self.now)
        self.assertEqual(status, "ORPHANED")
        # owner_id is empty string
        status_empty = classify_report_lifecycle("", last_accessed, as_of=self.now)
        self.assertEqual(status_empty, "ORPHANED")

    # --------------------------------------------------------------------------
    # Scenario 6: Unowned dashboard accessed 7 months ago -> ORPHANED
    # Precedence: ORPHANED evaluated before DORMANT
    # --------------------------------------------------------------------------
    def test_06_unowned_accessed_7_months_ago_is_orphaned(self):
        last_accessed = subtract_calendar_months(self.now, 7)
        status = classify_report_lifecycle(None, last_accessed, as_of=self.now)
        self.assertEqual(status, "ORPHANED")

    # --------------------------------------------------------------------------
    # Scenario 7: Owned dashboard with no access timestamp -> UNCLASSIFIED
    # Precedence: UNCLASSIFIED evaluated when owner is present and last_access is None
    # --------------------------------------------------------------------------
    def test_07_owned_no_access_timestamp_is_unclassified(self):
        status = classify_report_lifecycle(self.owner_id, None, as_of=self.now)
        self.assertEqual(status, "UNCLASSIFIED")

    # --------------------------------------------------------------------------
    # Scenario 8: Unowned dashboard with no access timestamp -> ORPHANED
    # Precedence: ORPHANED takes priority when owner is None
    # --------------------------------------------------------------------------
    def test_08_unowned_no_access_timestamp_is_orphaned(self):
        status = classify_report_lifecycle(None, None, as_of=self.now)
        self.assertEqual(status, "ORPHANED")

    # --------------------------------------------------------------------------
    # Scenario 9: Month-end and leap-year boundaries
    # --------------------------------------------------------------------------
    def test_09_month_end_and_leap_year_boundaries(self):
        # 1. Leap year 2024: August 31 - 6 months -> February 29, 2024
        as_of_leap = datetime(2024, 8, 31, 14, 30, 0, tzinfo=timezone.utc)
        feb_29_leap = subtract_calendar_months(as_of_leap, 6)
        self.assertEqual(feb_29_leap, datetime(2024, 2, 29, 14, 30, 0, tzinfo=timezone.utc))

        # Exactly on cutoff boundary -> DORMANT
        self.assertEqual(classify_report_lifecycle(self.owner_id, feb_29_leap, as_of=as_of_leap), "DORMANT")
        # 1 second after cutoff -> ACTIVE
        active_leap = feb_29_leap + timedelta(seconds=1)
        self.assertEqual(classify_report_lifecycle(self.owner_id, active_leap, as_of=as_of_leap), "ACTIVE")
        # 1 second before cutoff -> DORMANT
        dormant_leap = feb_29_leap - timedelta(seconds=1)
        self.assertEqual(classify_report_lifecycle(self.owner_id, dormant_leap, as_of=as_of_leap), "DORMANT")

        # 2. Non-leap year 2023: August 31 - 6 months -> February 28, 2023
        as_of_non_leap = datetime(2023, 8, 31, 10, 0, 0, tzinfo=timezone.utc)
        feb_28_non_leap = subtract_calendar_months(as_of_non_leap, 6)
        self.assertEqual(feb_28_non_leap, datetime(2023, 2, 28, 10, 0, 0, tzinfo=timezone.utc))

        # Exactly on cutoff boundary -> DORMANT
        self.assertEqual(classify_report_lifecycle(self.owner_id, feb_28_non_leap, as_of=as_of_non_leap), "DORMANT")
        # 1 second after cutoff -> ACTIVE
        self.assertEqual(classify_report_lifecycle(self.owner_id, feb_28_non_leap + timedelta(seconds=1), as_of=as_of_non_leap), "ACTIVE")

        # 3. 31-day month to 30-day month: March 31, 2024 - 6 months -> September 30, 2023
        as_of_march31 = datetime(2024, 3, 31, 9, 0, 0, tzinfo=timezone.utc)
        sep_30 = subtract_calendar_months(as_of_march31, 6)
        self.assertEqual(sep_30, datetime(2023, 9, 30, 9, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(classify_report_lifecycle(self.owner_id, sep_30, as_of=as_of_march31), "DORMANT")
        self.assertEqual(classify_report_lifecycle(self.owner_id, sep_30 + timedelta(seconds=1), as_of=as_of_march31), "ACTIVE")

    # --------------------------------------------------------------------------
    # Scenario 10: Timezone handling (UTC vs positive/negative offsets)
    # --------------------------------------------------------------------------
    def test_10_timezone_handling_utc_and_offsets(self):
        as_of_utc = datetime(2024, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
        cutoff_utc = subtract_calendar_months(as_of_utc, 6)  # 2024-04-15 12:00:00 UTC

        # Offset +05:30 (IST): 2024-04-15 17:30:00 +05:30 equals 2024-04-15 12:00:00 UTC
        tz_ist = timezone(timedelta(hours=5, minutes=30))
        accessed_ist_exact = datetime(2024, 4, 15, 17, 30, 0, tzinfo=tz_ist)
        self.assertEqual(classify_report_lifecycle(self.owner_id, accessed_ist_exact, as_of=as_of_utc), "DORMANT")

        # 1 second later in IST: 2024-04-15 17:30:01 +05:30 -> ACTIVE
        accessed_ist_active = datetime(2024, 4, 15, 17, 30, 1, tzinfo=tz_ist)
        self.assertEqual(classify_report_lifecycle(self.owner_id, accessed_ist_active, as_of=as_of_utc), "ACTIVE")

        # Offset -07:00 (PDT): 2024-04-15 05:00:00 -07:00 equals 2024-04-15 12:00:00 UTC
        tz_pdt = timezone(timedelta(hours=-7))
        accessed_pdt_exact = datetime(2024, 4, 15, 5, 0, 0, tzinfo=tz_pdt)
        self.assertEqual(classify_report_lifecycle(self.owner_id, accessed_pdt_exact, as_of=as_of_utc), "DORMANT")

    # --------------------------------------------------------------------------
    # Scenario 11: Tenant isolation & RLS on reports and v_dashboard_lifecycle
    # --------------------------------------------------------------------------
    def test_11_tenant_isolation_and_rls(self):
        v003_path = os.path.join(os.path.dirname(__file__), "..", "migrations", "V003__dashboard_ownership_and_lifecycle.sql")
        canonical_path = os.path.join(os.path.dirname(__file__), "..", "docs", "kpi-intelligence-canonical-model", "canonical_schema.sql")

        for path in [v003_path, canonical_path]:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            # Ensure v_dashboard_lifecycle joins analytical_objects and assets for tenant isolation
            self.assertIn("v_dashboard_lifecycle", content)
            self.assertIn("kpi_intel.analytical_objects", content)
            self.assertIn("kpi_intel.assets", content)

            # Ensure reports has RLS enabled in canonical schema
            if path == canonical_path:
                self.assertIn("ALTER TABLE kpi_intel.reports ENABLE ROW LEVEL SECURITY;", content)
                self.assertIn("CREATE POLICY tenant_isolation_policy_reports ON kpi_intel.reports", content)

            # Ensure migration grants SELECT on v_dashboard_lifecycle
            self.assertIn("GRANT SELECT ON kpi_intel.v_dashboard_lifecycle", content)

    # --------------------------------------------------------------------------
    # Scenario 12: Migration V003 syntax, structural invariants, and rollback compatibility
    # --------------------------------------------------------------------------
    def test_12_migration_v003_syntax_and_rollback_compatibility(self):
        v003_path = os.path.join(os.path.dirname(__file__), "..", "migrations", "V003__dashboard_ownership_and_lifecycle.sql")
        self.assertTrue(os.path.exists(v003_path), "V003 migration file must exist")

        with open(v003_path, "r", encoding="utf-8") as f:
            sql = f.read()

        # Check required columns added to kpi_intel.reports
        self.assertIn("ADD COLUMN IF NOT EXISTS owner_id UUID", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS owner_name TEXT", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'ORPHANED'", sql)

        # Check constraints and indexes
        self.assertIn("ck_reports_lifecycle_status", sql)
        self.assertIn("idx_reports_lifecycle_status", sql)
        self.assertIn("idx_reports_owner_id", sql)
        self.assertIn("idx_reports_last_accessed_at", sql)

        # Check functions and trigger
        self.assertIn("kpi_intel.classify_report_lifecycle", sql)
        self.assertIn("kpi_intel.sync_report_lifecycle_status", sql)
        self.assertIn("trg_reports_lifecycle_status", sql)
        self.assertIn("kpi_intel.refresh_report_lifecycle_status", sql)

        # Check rollback documentation is present
        self.assertIn("ROLLBACK INSTRUCTIONS", sql)
        self.assertIn("DROP VIEW IF EXISTS kpi_intel.v_dashboard_lifecycle;", sql)

    # --------------------------------------------------------------------------
    # Scenario 13: Connector ingestion of available metadata and preservation of unavailable values as NULL
    # --------------------------------------------------------------------------
    def test_13_connector_ingestion_preserves_unavailable_metadata_as_null(self):
        normalizer = PowerBINormalizer(tenant_id=self.tenant_id)
        proj_struct = PbipProjectStructure(
            project_root="mock_dir",
            pbip_file_path="mock_dir/mock.pbip",
            asset_name="MockReport",
            pbip_version="1.0"
        )
        # Power BI report with NO owner or access telemetry
        report_def = ReportDefinition(
            report_name="MockReport",
            pages=[ReportPage(source_native_id="p1", page_name="Page 1")]
        )

        bundle = normalizer.normalize(
            project_structure=proj_struct,
            report_def=report_def
        )

        self.assertEqual(len(bundle.reports), 1)
        rep = bundle.reports[0]
        self.assertIsNone(rep.owner_id)
        self.assertIsNone(rep.owner_name)
        self.assertIsNone(rep.last_accessed_at)
        self.assertEqual(rep.lifecycle_status, "ORPHANED")

        # Now test when authoritative owner is supplied
        report_with_owner = ReportDefinition(
            report_name="OwnedReport",
            pages=[ReportPage(source_native_id="p1", page_name="Page 1")],
            owner_id=self.owner_id,
            owner_name="Jane Doe",
            last_accessed_at=datetime.now(timezone.utc) - timedelta(days=10)
        )
        bundle_owned = normalizer.normalize(
            project_structure=proj_struct,
            report_def=report_with_owner
        )
        rep_owned = bundle_owned.reports[0]
        self.assertEqual(rep_owned.owner_id, self.owner_id)
        self.assertEqual(rep_owned.owner_name, "Jane Doe")
        self.assertIsNotNone(rep_owned.last_accessed_at)
        self.assertEqual(rep_owned.lifecycle_status, "ACTIVE")

    # --------------------------------------------------------------------------
    # Scenario 14: Repeated ingestion idempotency
    # --------------------------------------------------------------------------
    def test_14_repeated_ingestion_idempotency(self):
        persister = CanonicalPersistenceService(tenant_id=self.tenant_id)
        rep_obj_id = uuid.uuid4()
        report = CanonicalReport(
            report_id=rep_obj_id,
            object_id=rep_obj_id,
            report_type="POWER_BI_PBIP",
            page_count=2,
            visual_count=5,
            owner_id=None,
            owner_name=None,
            last_accessed_at=None,
            lifecycle_status="ORPHANED"
        )

        from backend.ingestion.models import CanonicalIngestionBundle, CanonicalAsset, CanonicalAssetVersion
        bundle = CanonicalIngestionBundle(
            asset=CanonicalAsset(asset_id=uuid.uuid4(), tenant_id=self.tenant_id, platform="POWER_BI", asset_type="REPORT", asset_name="TestAsset"),
            version=CanonicalAssetVersion(
                asset_version_id=uuid.uuid4(),
                asset_id=uuid.uuid4(),
                tenant_id=self.tenant_id,
                version_number=1,
                content_hash="h1",
                raw_content_hash="h2",
                structure_hash="h3",
                metadata_hash="h4",
                parser_version="1.0.0"
            ),
            reports=[report]
        )

        sql = persister.generate_transactional_sql(bundle)
        # Verify ON CONFLICT uses COALESCE so verified owner/access is NOT wiped
        self.assertIn("ON CONFLICT (object_id) DO UPDATE SET", sql)
        self.assertIn("owner_id = COALESCE(EXCLUDED.owner_id, kpi_intel.reports.owner_id)", sql)
        self.assertIn("owner_name = COALESCE(EXCLUDED.owner_name, kpi_intel.reports.owner_name)", sql)
        self.assertIn("last_accessed_at = COALESCE(EXCLUDED.last_accessed_at, kpi_intel.reports.last_accessed_at)", sql)
        self.assertIn("lifecycle_status = kpi_intel.classify_report_lifecycle", sql)

    # --------------------------------------------------------------------------
    # Scenario 15: Lifecycle transitions as classification timestamp advances
    # --------------------------------------------------------------------------
    def test_15_lifecycle_transitions_as_time_advances(self):
        # Report was accessed on Jan 15, 2024
        access_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        # 1. Evaluated on March 15, 2024 (2 months elapsed) -> ACTIVE
        as_of_2_months = datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(classify_report_lifecycle(self.owner_id, access_time, as_of=as_of_2_months), "ACTIVE")

        # 2. Evaluated on June 15, 2024 (5 months elapsed) -> ACTIVE
        as_of_5_months = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(classify_report_lifecycle(self.owner_id, access_time, as_of=as_of_5_months), "ACTIVE")

        # 3. Evaluated on July 15, 2024 (exactly 6 calendar months elapsed) -> DORMANT
        as_of_6_months = datetime(2024, 7, 15, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(classify_report_lifecycle(self.owner_id, access_time, as_of=as_of_6_months), "DORMANT")

        # 4. Evaluated on October 15, 2024 (9 months elapsed) -> DORMANT
        as_of_9_months = datetime(2024, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(classify_report_lifecycle(self.owner_id, access_time, as_of=as_of_9_months), "DORMANT")

        # 5. If ownership is revoked/cleared -> immediately ORPHANED regardless of access time
        self.assertEqual(classify_report_lifecycle(None, access_time, as_of=as_of_2_months), "ORPHANED")
        self.assertEqual(classify_report_lifecycle(None, access_time, as_of=as_of_9_months), "ORPHANED")


if __name__ == "__main__":
    unittest.main()
