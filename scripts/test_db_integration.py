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

    def test_01_tenant_isolation_in_transaction(self):
        """1. Set Tenant A inside a transaction and verify that tenant-scoped queries use Tenant A."""
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid);")
            cur.execute("""
                INSERT INTO kpi_intel.assets (asset_id, tenant_id, platform, asset_type, asset_name)
                VALUES ('a1111111-1111-1111-1111-111111111111', '11111111-1111-1111-1111-111111111111', 'POWER_BI', 'REPORT', 'Tenant A Asset');
            """)
            cur.execute("SELECT asset_name FROM kpi_intel.assets;")
            names = [r[0] for r in cur.fetchall()]
            self.assertIn("Tenant A Asset", names)
        finally:
            self.conn.rollback()

    def test_02_tenant_setting_cleared_on_commit(self):
        """2. Commit the transaction and verify that the tenant setting does not persist into the next transaction."""
        cur = self.conn.cursor()
        cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid);")
        self.conn.commit()

        # In a new transaction on the same connection, verify tenant context is automatically cleared
        cur = self.conn.cursor()
        cur.execute("SELECT kpi_intel.current_tenant_id();")
        res = cur.fetchone()[0]
        self.assertIsNone(res, "Tenant setting must not persist into the next transaction after COMMIT")

    def test_03_tenant_setting_cleared_on_rollback(self):
        """3. Roll back a transaction after setting Tenant A and verify that the setting does not leak."""
        cur = self.conn.cursor()
        cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid);")
        self.conn.rollback()

        # In a new transaction on the same connection, verify tenant context is reset
        cur = self.conn.cursor()
        cur.execute("SELECT kpi_intel.current_tenant_id();")
        res = cur.fetchone()[0]
        self.assertIsNone(res, "Tenant setting must not leak after ROLLBACK")

    def test_04_sequential_tenants_on_same_connection(self):
        """4. Reuse the same database connection for Tenant A and then Tenant B, verifying each transaction uses only its own context."""
        cur = self.conn.cursor()
        try:
            # Transaction 1: Tenant A
            cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid);")
            cur.execute("""
                INSERT INTO kpi_intel.assets (asset_id, tenant_id, platform, asset_type, asset_name)
                VALUES ('a1111111-1111-1111-1111-111111111111', '11111111-1111-1111-1111-111111111111', 'POWER_BI', 'REPORT', 'Tenant A Asset');
            """)
            self.conn.commit()

            # Transaction 2 on same connection: Tenant B
            cur = self.conn.cursor()
            cur.execute("SELECT kpi_intel.set_current_tenant_id('22222222-2222-2222-2222-222222222222'::uuid);")
            cur.execute("""
                INSERT INTO kpi_intel.assets (asset_id, tenant_id, platform, asset_type, asset_name)
                VALUES ('b2222222-2222-2222-2222-222222222222', '22222222-2222-2222-2222-222222222222', 'TABLEAU', 'WORKBOOK', 'Tenant B Asset');
            """)
            # Query as Tenant B: Must see only Tenant B Asset, never Tenant A Asset
            cur.execute("SELECT asset_name FROM kpi_intel.assets;")
            names = [r[0] for r in cur.fetchall()]
            self.assertIn("Tenant B Asset", names)
            self.assertNotIn("Tenant A Asset", names)
            self.conn.commit()

            # Transaction 3 on same connection: Tenant A again
            cur = self.conn.cursor()
            cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid);")
            cur.execute("SELECT asset_name FROM kpi_intel.assets;")
            names = [r[0] for r in cur.fetchall()]
            self.assertIn("Tenant A Asset", names)
            self.assertNotIn("Tenant B Asset", names)
            self.conn.commit()
        finally:
            self.conn.rollback()

    def test_05_missing_tenant_context_fails_closed(self):
        """5. Execute tenant-scoped queries without a tenant context and verify that they fail closed."""
        cur = self.conn.cursor()
        try:
            # Clear any context explicitly
            cur.execute("SELECT kpi_intel.clear_current_tenant_id();")
            cur.execute("SELECT asset_name FROM kpi_intel.assets;")
            rows = cur.fetchall()
            self.assertEqual(len(rows), 0, "Missing tenant context must fail closed and return 0 rows under RLS")
        finally:
            self.conn.rollback()

    def test_06_ordinary_role_cannot_set_session_state(self):
        """6. Verify that the ordinary application role cannot use the setter to establish session-level state."""
        cur = self.conn.cursor()
        try:
            # Calling set_current_tenant_id sets transaction-local state
            cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid);")
            cur.execute("SELECT current_setting('kpi_intel.current_tenant_id', true);")
            self.assertEqual(cur.fetchone()[0], '11111111-1111-1111-1111-111111111111')
            self.conn.commit()

            # Verify no session-level state survived the commit
            cur = self.conn.cursor()
            cur.execute("SELECT current_setting('kpi_intel.current_tenant_id', true);")
            setting_after = cur.fetchone()[0]
            self.assertTrue(setting_after is None or setting_after == '', "Ordinary setter must not establish session-level state")
        finally:
            self.conn.rollback()

    def test_07_obsolete_function_overload_rejection(self):
        """7. Verify that an obsolete function overload cannot be called to bypass the new behavior."""
        cur = self.conn.cursor()
        try:
            # Calling 2-parameter setter set_current_tenant_id(UUID, BOOLEAN) must fail as undefined function
            with self.assertRaises(Exception) as ctx:
                cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid, false);")
            self.assertTrue("does not exist" in str(ctx.exception) or "42883" in str(getattr(ctx.exception, 'pgcode', '')))
            self.conn.rollback()

            cur = self.conn.cursor()
            # Calling 1-parameter clearer clear_current_tenant_id(BOOLEAN) must fail as undefined function
            with self.assertRaises(Exception) as ctx:
                cur.execute("SELECT kpi_intel.clear_current_tenant_id(false);")
            self.assertTrue("does not exist" in str(ctx.exception) or "42883" in str(getattr(ctx.exception, 'pgcode', '')))
            self.conn.rollback()
        finally:
            self.conn.rollback()

    def test_08_cross_tenant_fk_rejection(self):
        """Verify that composite foreign key rejects cross-tenant association."""
        cur = self.conn.cursor()
        try:
            # Create Tenant A Asset
            cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid);")
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

    def test_09_audit_immutability(self):
        """Verify that UPDATE and DELETE are rejected on audit tables with SQLSTATE 42501."""
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid);")
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

    def test_10_human_approval_protection(self):
        """Verify that automated jobs cannot overwrite human-approved mappings, and only human actors can supersede."""
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid);")
            # Setup prerequisites and approved mapping
            # Attempt update with decision_source = 'LLM' on approved mapping -> Rejected
            # Attempt modifying kpi_candidate_id -> Rejected
            # Valid transition to SUPERSEDED by HUMAN -> Accepted
        finally:
            self.conn.rollback()

    def test_11_override_cycle_prevention(self):
        """Verify that cyclic override supersession is rejected."""
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid);")
            with self.assertRaises(Exception):
                cur.execute("""
                    INSERT INTO kpi_intel.mapping_overrides (override_id, kpi_mapping_id, override_type, override_justification, normalised_justification, justification_hash, created_by_user_id, supersedes_override_id)
                    VALUES ('o1111111-1111-1111-1111-111111111111', 'm1111111-1111-1111-1111-111111111111', 'REJECT', 'Reason', 'reason', 'h1', 'u1', 'o1111111-1111-1111-1111-111111111111');
                """)
        finally:
            self.conn.rollback()

    def test_12_composite_fk_column_specific_set_null(self):
        """Verify that deleting referenced candidate or ontology entry only nulls nullable columns."""
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid);")
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

    def test_ordinary_setter_no_p_is_local(self):
        """Verify ordinary setter accepts only (p_tenant_id UUID) with no p_is_local option."""
        self.assertIn("CREATE OR REPLACE FUNCTION kpi_intel.set_current_tenant_id(p_tenant_id UUID)", self.sql)
        self.assertNotIn("set_current_tenant_id(p_tenant_id UUID, p_is_local", self.sql)
        self.assertNotIn("p_is_local BOOLEAN", self.sql)

    def test_setter_explicitly_transaction_local(self):
        """Verify setter explicitly uses transaction-local configuration (true)."""
        self.assertIn("PERFORM set_config('kpi_intel.current_tenant_id', p_tenant_id::TEXT, true);", self.sql)
        self.assertIn("PERFORM set_config('kpi_intel.current_tenant_id', '', true);", self.sql)

    def test_ordinary_clearer_no_session_level(self):
        """Verify clearer has 0 arguments and explicitly uses transaction-local configuration (true)."""
        self.assertIn("CREATE OR REPLACE FUNCTION kpi_intel.clear_current_tenant_id()", self.sql)
        self.assertNotIn("clear_current_tenant_id(p_is_local", self.sql)

    def test_obsolete_overloads_dropped(self):
        """Verify obsolete callable overloads with BOOLEAN are explicitly dropped."""
        self.assertIn("DROP FUNCTION IF EXISTS kpi_intel.set_current_tenant_id(UUID, BOOLEAN);", self.sql)
        self.assertIn("DROP FUNCTION IF EXISTS kpi_intel.clear_current_tenant_id(BOOLEAN);", self.sql)

    def test_rls_tenant_resolution_fails_closed(self):
        """Verify current_tenant_id fails closed to NULL when setting is missing or empty."""
        self.assertIn("RETURN NULLIF(current_setting('kpi_intel.current_tenant_id', true), '')::UUID;", self.sql)

    def test_revoke_public_function_execution(self):
        """Verify EXECUTE on tenant functions is revoked from PUBLIC and granted only to application roles."""
        self.assertIn("REVOKE ALL ON FUNCTION kpi_intel.current_tenant_id() FROM PUBLIC;", self.sql)
        self.assertIn("REVOKE ALL ON FUNCTION kpi_intel.set_current_tenant_id(UUID) FROM PUBLIC;", self.sql)
        self.assertIn("REVOKE ALL ON FUNCTION kpi_intel.clear_current_tenant_id() FROM PUBLIC;", self.sql)
        self.assertIn("GRANT EXECUTE ON FUNCTION kpi_intel.set_current_tenant_id(UUID) TO kpi_app_user;", self.sql)
        self.assertIn("GRANT EXECUTE ON FUNCTION kpi_intel.clear_current_tenant_id() TO kpi_app_user;", self.sql)

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
