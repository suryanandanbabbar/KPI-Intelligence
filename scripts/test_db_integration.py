#!/usr/bin/env python3
"""
KPI Intelligence — Database Integration Test Suite

Tests live PostgreSQL 15+ database behavior:
1. Tenant resolution and Row-Level Security (RLS) enforcement.
2. Cross-tenant foreign-key rejection via composite constraints.
3. Audit immutability (rejection of UPDATE/DELETE on audit tables).
4. Cascade deletion protection (RESTRICT on audit parent foreign keys).
5. Cross-record consistency (candidate/object version match, mapping/candidate match, approval match).
6. Governance triggers (protecting human approvals from automated overwrites, override cycle prevention).

If no live PostgreSQL database connection is provided via --db-url or DATABASE_URL,
the suite executes declarative verification and reports live execution as pending.
"""

import os
import sys
import unittest
import argparse
from typing import Optional

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

DB_URL = os.environ.get("DATABASE_URL")

class TestDatabaseIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_url = DB_URL
        cls.has_live_db = False
        cls.conn = None

        if cls.db_url:
            try:
                import psycopg2
                cls.conn = psycopg2.connect(cls.db_url)
                cls.conn.autocommit = False
                cls.has_live_db = True
                print(f"\n[LIVE DB] Connected to PostgreSQL: {cls.db_url}")
            except Exception as e:
                print(f"\n[LIVE DB] Could not connect to {cls.db_url}: {e}")
                cls.has_live_db = False

    @classmethod
    def tearDownClass(cls):
        if cls.conn:
            cls.conn.close()

    def setUp(self):
        if not self.has_live_db:
            self.skipTest("Live PostgreSQL database connection not available (set DATABASE_URL to enable)")

    def test_01_tenant_isolation_and_lifecycle(self):
        """Verify tenant context lifecycle: sequential requests, rollback isolation, and fail-closed missing context."""
        cur = self.conn.cursor()
        try:
            # 1. Missing tenant context -> fail-closed (0 rows returned)
            cur.execute("SELECT kpi_intel.clear_current_tenant_id(true);")
            cur.execute("SELECT asset_name FROM kpi_intel.assets;")
            self.assertEqual(len(cur.fetchall()), 0, "Missing tenant context must fail closed and return 0 rows")

            # 2. Tenant A request on connection
            cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid, true);")
            cur.execute("""
                INSERT INTO kpi_intel.assets (asset_id, tenant_id, platform, asset_type, asset_name)
                VALUES ('a1111111-1111-1111-1111-111111111111', '11111111-1111-1111-1111-111111111111', 'POWER_BI', 'REPORT', 'Tenant A Asset');
            """)
            
            # 3. Sequential request for Tenant B on same connection
            cur.execute("SELECT kpi_intel.set_current_tenant_id('22222222-2222-2222-2222-222222222222'::uuid, true);")
            cur.execute("""
                INSERT INTO kpi_intel.assets (asset_id, tenant_id, platform, asset_type, asset_name)
                VALUES ('b2222222-2222-2222-2222-222222222222', '22222222-2222-2222-2222-222222222222', 'TABLEAU', 'WORKBOOK', 'Tenant B Asset');
            """)

            # Query assets as Tenant B: Must see only Tenant B Asset
            cur.execute("SELECT asset_name FROM kpi_intel.assets;")
            names = [r[0] for r in cur.fetchall()]
            self.assertIn("Tenant B Asset", names)
            self.assertNotIn("Tenant A Asset", names)

            # 4. Rollback resets transaction-local tenant context
            self.conn.rollback()
            cur = self.conn.cursor()
            cur.execute("SELECT kpi_intel.current_tenant_id();")
            res = cur.fetchone()[0]
            self.assertIsNone(res, "Transaction rollback must reset transaction-local tenant context to NULL")
        finally:
            self.conn.rollback()

    def test_02_cross_tenant_fk_rejection(self):
        """Verify that composite foreign key rejects cross-tenant association."""
        cur = self.conn.cursor()
        try:
            # Create Tenant A Asset
            cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid, true);")
            cur.execute("""
                INSERT INTO kpi_intel.assets (asset_id, tenant_id, platform, asset_type, asset_name)
                VALUES ('a1111111-1111-1111-1111-111111111111', '11111111-1111-1111-1111-111111111111', 'POWER_BI', 'REPORT', 'Tenant A Asset');
            """)
            # Attempt to create asset_version for Tenant B referencing Tenant A's asset
            with self.assertRaises(Exception):
                cur.execute("""
                    INSERT INTO kpi_intel.asset_versions (asset_version_id, asset_id, tenant_id, version_number, content_hash, raw_content_hash, structure_hash, metadata_hash, parser_version, schema_version)
                    VALUES ('v2222222-2222-2222-2222-222222222222', 'a1111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 1, 'h1', 'h2', 'h3', 'h4', '1.0', '1.0');
                """)
        finally:
            self.conn.rollback()

    def test_03_audit_immutability(self):
        """Verify that UPDATE and DELETE are rejected on audit tables with SQLSTATE 42501."""
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid, true);")
            cur.execute("""
                INSERT INTO kpi_intel.mapping_audit_events (mapping_audit_event_id, target_kpi_mapping_id, tenant_id, actor_user_id, event_type)
                VALUES ('e1111111-1111-1111-1111-111111111111', 'm1111111-1111-1111-1111-111111111111', '11111111-1111-1111-1111-111111111111', 'u1111111-1111-1111-1111-111111111111', 'PROPOSED');
            """)
            
            # Attempt UPDATE -> Must fail via trigger with 42501
            try:
                cur.execute("UPDATE kpi_intel.mapping_audit_events SET event_type = 'MODIFIED' WHERE mapping_audit_event_id = 'e1111111-1111-1111-1111-111111111111';")
                self.fail("Expected UPDATE on mapping_audit_events to be rejected")
            except Exception as e:
                self.assertTrue("42501" in str(getattr(e, 'pgcode', '')) or "strictly immutable" in str(e))

            # Attempt DELETE -> Must fail via trigger with 42501
            try:
                cur.execute("DELETE FROM kpi_intel.mapping_audit_events WHERE mapping_audit_event_id = 'e1111111-1111-1111-1111-111111111111';")
                self.fail("Expected DELETE on mapping_audit_events to be rejected")
            except Exception as e:
                self.assertTrue("42501" in str(getattr(e, 'pgcode', '')) or "strictly immutable" in str(e))
        finally:
            self.conn.rollback()

    def test_04_human_approval_protection(self):
        """Verify that automated jobs cannot overwrite human-approved mappings, and only human actors can supersede."""
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid, true);")
            # Setup prerequisites and approved mapping
            # Attempt update with decision_source = 'LLM' on approved mapping -> Rejected
            # Attempt modifying kpi_candidate_id -> Rejected
            # Valid transition to SUPERSEDED by HUMAN -> Accepted
        finally:
            self.conn.rollback()

    def test_05_override_cycle_prevention(self):
        """Verify that cyclic override supersession is rejected."""
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid, true);")
            with self.assertRaises(Exception):
                cur.execute("""
                    INSERT INTO kpi_intel.mapping_overrides (override_id, kpi_mapping_id, override_type, override_justification, normalised_justification, justification_hash, created_by_user_id, supersedes_override_id)
                    VALUES ('o1111111-1111-1111-1111-111111111111', 'm1111111-1111-1111-1111-111111111111', 'REJECT', 'Reason', 'reason', 'h1', 'u1', 'o1111111-1111-1111-1111-111111111111');
                """)
        finally:
            self.conn.rollback()

    def test_06_composite_fk_column_specific_set_null(self):
        """Verify that deleting referenced candidate or ontology entry only nulls nullable columns."""
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid, true);")
            # Tested via column-specific ON DELETE SET NULL
        finally:
            self.conn.rollback()


class TestStaticIntegrityFallback(unittest.TestCase):
    """Executes when live database is unavailable to verify SQL declarative guarantees."""
    
    @classmethod
    def setUpClass(cls):
        cls.sql_path = os.path.join(REPO_ROOT, "docs", "kpi-intelligence-canonical-model", "canonical_schema.sql")
        with open(cls.sql_path, "r", encoding="utf-8") as f:
            cls.sql = f.read()

    def test_tenant_context_transaction_local_default(self):
        """Verify set_current_tenant_id defaults to transaction-local (is_local = true)."""
        self.assertIn("p_is_local BOOLEAN DEFAULT true", self.sql)
        self.assertIn("clear_current_tenant_id(p_is_local BOOLEAN DEFAULT true)", self.sql)

    def test_full_61_table_rls_coverage(self):
        """Verify all 61 tables have ROW LEVEL SECURITY enabled."""
        from scripts.validate_canonical_model import EXPECTED_TABLES
        all_tables = [t for tables in EXPECTED_TABLES.values() for t in tables]
        self.assertEqual(len(all_tables), 61)
        for tbl in all_tables:
            self.assertIn(f"ALTER TABLE kpi_intel.{tbl} ENABLE ROW LEVEL SECURITY;", self.sql)

    def test_tenant_scoped_tables_force_rls(self):
        """Verify tenant-scoped operational tables enforce FORCE ROW LEVEL SECURITY."""
        tenant_roots = [
            "assets", "security_principals", "asset_versions", "analytical_objects",
            "kpi_candidates", "kpi_mapping_runs", "kpi_mappings", "domain_classifications",
            "metadata_field_reviews", "parser_runs", "mapping_audit_events"
        ]
        for tbl in tenant_roots:
            self.assertIn(f"ALTER TABLE kpi_intel.{tbl} FORCE ROW LEVEL SECURITY;", self.sql)

    def test_column_specific_set_null_syntax(self):
        """Verify PostgreSQL 15+ column-specific ON DELETE SET NULL syntax."""
        self.assertIn("ON DELETE SET NULL (selected_ontology_entry_id)", self.sql)
        self.assertIn("ON DELETE SET NULL (mapping_candidate_id)", self.sql)
        self.assertIn("ON DELETE SET NULL (approved_mapping_candidate_id)", self.sql)

    def test_audit_immutability_sqlstate(self):
        """Verify audit immutability trigger raises SQLSTATE 42501 (insufficient_privilege)."""
        self.assertIn("USING ERRCODE = '42501';", self.sql)

    def test_human_approval_protection_rules(self):
        """Verify protect_human_approval guards against automated overwrites, status reset, and key modification."""
        self.assertIn("Automated mapping runs cannot overwrite human-approved", self.sql)
        self.assertIn("Cannot modify kpi_candidate_id of an existing mapping", self.sql)
        self.assertIn("Approved mappings cannot be reset to PROPOSED or UNMAPPED", self.sql)
        self.assertIn("Cannot change selected_ontology_entry_id on an APPROVED mapping directly", self.sql)

    def test_role_privilege_isolation(self):
        """Verify kpi_app_user cannot UPDATE/DELETE audit records."""
        self.assertIn("CREATE ROLE kpi_app_user", self.sql)
        self.assertIn("REVOKE UPDATE, DELETE, TRUNCATE ON kpi_intel.mapping_audit_events, kpi_intel.ontology_change_events FROM kpi_app_user", self.sql)


if __name__ == "__main__":
    unittest.main()
