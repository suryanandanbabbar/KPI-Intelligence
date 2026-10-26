"""
KPI Intelligence — Unit Tests for PostgreSQL to Cosmos DB Migration Tool.

Verifies:
1. Support for all 61 canonical table names and legacy aliases in TABLE_ALIASES.
2. Ingestion and document conversion with canonical table names.
3. Backward compatibility with legacy canonical_* and standard_kpi table keys.
4. Correct embedding of child relational rows into document aggregates.
5. Dry-run execution without persistence.
6. Clean persistence to SQLite repository with proper partition keys and tenant context.
"""

import os
import uuid
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from scripts.validate_canonical_model import EXPECTED_COLUMNS
from scripts.migrate_postgres_to_cosmos import TABLE_ALIASES, PostgresToCosmosMigrator, get_table_rows
from backend.storage.sqlite.repository import SQLiteRepository
from backend.contracts import CosmosContainer, LifecycleStatus
from backend.repository.context import TenantContext
from backend.migration.dispositions import (
    CANONICAL_MIGRATION_REGISTRY,
    TableMigrationDisposition,
    MigrationDispositionType,
)


class TestPostgresToCosmosMigrator(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db_path = self.temp_file.name
        self.temp_file.close()

        self.repo = SQLiteRepository(self.temp_db_path)
        self.tenant_id = str(uuid.uuid4())
        self.migrator = PostgresToCosmosMigrator(self.repo, self.tenant_id)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.unlink(self.temp_db_path)
            except OSError:
                pass

    def test_all_61_canonical_tables_covered(self):
        """Validates that all 61 canonical tables in EXPECTED_COLUMNS are in TABLE_ALIASES."""
        expected_tables = set(EXPECTED_COLUMNS.keys())
        alias_tables = set(TABLE_ALIASES.keys())

        missing = expected_tables - alias_tables
        self.assertEqual(len(missing), 0, f"Missing tables from TABLE_ALIASES: {missing}")
        self.assertEqual(len(alias_tables), 61)

    def test_get_table_rows_resolution(self):
        """Validates that get_table_rows handles canonical names and legacy aliases."""
        data = {
            "assets": [{"asset_id": "a1"}],
            "canonical_report": [{"report_id": "r1"}],
            "standard_kpi": [{"kpi_id": "k1"}],
        }

        self.assertEqual(get_table_rows(data, "assets"), [{"asset_id": "a1"}])
        self.assertEqual(get_table_rows(data, "reports"), [{"report_id": "r1"}])
        self.assertEqual(get_table_rows(data, "kpi_ontology_entries"), [{"kpi_id": "k1"}])
        self.assertEqual(get_table_rows(data, "nonexistent"), [])

    def test_migration_with_canonical_table_names(self):
        """Validates migration using canonical table names."""
        aid = str(uuid.uuid4())
        vid = str(uuid.uuid4())
        rid = str(uuid.uuid4())
        pid = str(uuid.uuid4())
        vis_id = str(uuid.uuid4())
        mid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        calc_id = str(uuid.uuid4())

        canonical_data = {
            "assets": [
                {
                    "asset_id": aid,
                    "tenant_id": self.tenant_id,
                    "platform": "POWER_BI",
                    "asset_name": "Sales Workspace",
                    "asset_type": "REPORT_AND_MODEL",
                    "lifecycle_status": "ACTIVE",
                }
            ],
            "asset_versions": [
                {
                    "asset_version_id": vid,
                    "asset_id": aid,
                    "tenant_id": self.tenant_id,
                    "version_number": 1,
                    "content_hash": "hash_v1",
                }
            ],
            "reports": [
                {
                    "report_id": rid,
                    "tenant_id": self.tenant_id,
                    "asset_id": aid,
                    "asset_version_id": vid,
                    "report_name": "Quarterly Revenue",
                    "report_type": "POWER_BI_PBIP",
                    "owner_name": "Finance Lead",
                    "lifecycle_status": "ACTIVE",
                }
            ],
            "report_pages": [
                {
                    "page_id": pid,
                    "report_id": rid,
                    "page_name": "Executive Dashboard",
                    "display_order": 1,
                }
            ],
            "visuals": [
                {
                    "visual_id": vis_id,
                    "page_id": pid,
                    "visual_type": "barChart",
                    "visual_title": "Territory Performance",
                }
            ],
            "visual_bindings": [
                {
                    "visual_binding_id": str(uuid.uuid4()),
                    "visual_id": vis_id,
                    "binding_role": "Values",
                    "binding_order": 1,
                }
            ],
            "semantic_models": [
                {
                    "semantic_model_id": mid,
                    "tenant_id": self.tenant_id,
                    "asset_id": aid,
                    "asset_version_id": vid,
                    "model_name": "Enterprise Data Model",
                    "compatibility_level": "1567",
                }
            ],
            "data_tables": [
                {
                    "data_table_id": tid,
                    "semantic_model_id": mid,
                    "table_name": "FactSales",
                }
            ],
            "data_columns": [
                {
                    "data_column_id": cid,
                    "data_table_id": tid,
                    "column_name": "SalesAmount",
                    "data_type": "decimal",
                }
            ],
            "calculations": [
                {
                    "calculation_id": calc_id,
                    "semantic_model_id": mid,
                    "calculation_name": "TotalRevenue",
                    "expression_text": "SUM(FactSales[SalesAmount])",
                }
            ],
            "security_principals": [
                {
                    "principal_id": str(uuid.uuid4()),
                    "tenant_id": self.tenant_id,
                    "platform": "POWER_BI",
                    "principal_name": "finance_team@corp.com",
                    "principal_type": "GROUP",
                }
            ],
            "parser_runs": [
                {
                    "parser_run_id": str(uuid.uuid4()),
                    "asset_version_id": vid,
                    "tenant_id": self.tenant_id,
                    "platform": "POWER_BI",
                    "parser_name": "PBIP",
                    "parser_version": "1.0.0",
                }
            ],
        }

        stats = self.migrator.migrate_from_dict(canonical_data, dry_run=False)

        # Assert reconciliation stats
        self.assertIn("assets", stats["mapped_tables"])
        self.assertIn("reports", stats["mapped_tables"])
        self.assertIn("semantic_models", stats["mapped_tables"])
        self.assertIn("security_principals", stats["mapped_tables"])
        self.assertIn("parser_runs", stats["mapped_tables"])

        # Assert embedded counts
        self.assertEqual(stats["embedded_elements"]["report_pages"], 1)
        self.assertEqual(stats["embedded_elements"]["visuals"], 1)
        self.assertEqual(stats["embedded_elements"]["visual_bindings"], 1)
        self.assertEqual(stats["embedded_elements"]["data_tables"], 1)
        self.assertEqual(stats["embedded_elements"]["data_columns"], 1)
        self.assertEqual(stats["embedded_elements"]["calculations"], 1)

        # Verify persisted documents in repository
        ctx = TenantContext(tenant_id=self.tenant_id)

        rep_doc = self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_id, f"rep_{rid}", tenant_context=ctx)
        self.assertIsNotNone(rep_doc)
        self.assertEqual(rep_doc["report_name"], "Quarterly Revenue")
        self.assertEqual(len(rep_doc["pages"]), 1)
        self.assertEqual(len(rep_doc["visuals"]), 1)
        self.assertEqual(len(rep_doc["visual_bindings"]), 1)

        model_doc = self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_id, f"model_{mid}", tenant_context=ctx)
        self.assertIsNotNone(model_doc)
        self.assertEqual(model_doc["model_name"], "Enterprise Data Model")
        self.assertEqual(len(model_doc["tables"]), 1)
        self.assertEqual(len(model_doc["calculations"]), 1)

    def test_migration_with_legacy_aliases(self):
        """Validates migration using legacy table names (e.g. canonical_asset, canonical_report)."""
        aid = str(uuid.uuid4())
        rid = str(uuid.uuid4())

        legacy_data = {
            "canonical_asset": [
                {
                    "asset_id": aid,
                    "tenant_id": self.tenant_id,
                    "platform": "POWER_BI",
                    "asset_name": "Legacy Asset",
                }
            ],
            "canonical_report": [
                {
                    "report_id": rid,
                    "tenant_id": self.tenant_id,
                    "asset_id": aid,
                    "report_name": "Legacy Report",
                }
            ],
        }

        stats = self.migrator.migrate_from_dict(legacy_data, dry_run=False)

        self.assertIn("assets", stats["mapped_tables"])
        self.assertIn("reports", stats["mapped_tables"])

        ctx = TenantContext(tenant_id=self.tenant_id)
        asset_doc = self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_id, f"asset_{aid}", tenant_context=ctx)
        self.assertIsNotNone(asset_doc)
        self.assertEqual(asset_doc["asset_name"], "Legacy Asset")

    def test_dry_run_does_not_persist(self):
        """Validates that dry_run=True produces reconciliation stats without persisting to repo."""
        aid = str(uuid.uuid4())
        data = {
            "assets": [
                {
                    "asset_id": aid,
                    "tenant_id": self.tenant_id,
                    "asset_name": "Dry Run Asset",
                }
            ]
        }

        stats = self.migrator.migrate_from_dict(data, dry_run=True)
        self.assertIn("assets", stats["mapped_tables"])
        self.assertEqual(stats["rows_persisted"], 0)

        ctx = TenantContext(tenant_id=self.tenant_id)
        doc = self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_id, f"asset_{aid}", tenant_context=ctx)
        self.assertIsNone(doc)

    def test_canonical_migration_registry_matches_expected_columns(self):
        """Validates that all 61 canonical tables in EXPECTED_COLUMNS have explicit dispositions."""
        from backend.migration.dispositions import CANONICAL_MIGRATION_REGISTRY, MigrationDispositionType

        exp_tables = set(EXPECTED_COLUMNS.keys())
        reg_tables = set(CANONICAL_MIGRATION_REGISTRY.keys())

        missing = exp_tables - reg_tables
        extra = reg_tables - exp_tables

        self.assertEqual(len(missing), 0, f"Missing tables in migration registry: {missing}")
        self.assertEqual(len(extra), 0, f"Extra tables in migration registry: {extra}")
        self.assertEqual(len(reg_tables), 61)

        # Count dispositions
        indep = [t for t, d in CANONICAL_MIGRATION_REGISTRY.items() if d.disposition == MigrationDispositionType.INDEPENDENTLY_PERSISTED]
        embed = [t for t, d in CANONICAL_MIGRATION_REGISTRY.items() if d.disposition == MigrationDispositionType.EMBEDDED_AGGREGATED]
        excl = [t for t, d in CANONICAL_MIGRATION_REGISTRY.items() if d.disposition == MigrationDispositionType.INTENTIONALLY_EXCLUDED]

        self.assertEqual(len(indep), 25)
        self.assertEqual(len(embed), 36)
        self.assertEqual(len(excl), 0)

    def test_all_61_table_handlers_exist_and_callable(self):
        """Validates that every canonical table has an executable handler method on PostgresToCosmosMigrator."""
        from backend.migration.dispositions import CANONICAL_MIGRATION_REGISTRY

        for tbl, disp in CANONICAL_MIGRATION_REGISTRY.items():
            handler_name = disp.handler_function_name
            self.assertTrue(
                hasattr(PostgresToCosmosMigrator, handler_name),
                f"Missing handler method {handler_name} on PostgresToCosmosMigrator for table {tbl}"
            )
            handler = getattr(self.migrator, handler_name)
            self.assertTrue(
                callable(handler),
                f"Handler {handler_name} on PostgresToCosmosMigrator is not callable for table {tbl}"
            )

    def test_full_synthetic_migration_dry_run(self):
        """Validates deterministic dry-run migration across all 61 canonical tables."""
        synth_dataset = {}
        for tbl, cols in EXPECTED_COLUMNS.items():
            row = {c: "test" for c in cols}
            for k in list(row.keys()):
                if "id" in k:
                    row[k] = str(uuid.uuid4())
                elif "version_number" in k or "order" in k or "count" in k or "bytes" in k or "number" in k:
                    row[k] = 1
                elif "is_" in k:
                    row[k] = True
                elif "score" in k:
                    row[k] = 1.0
                elif "hash" in k:
                    row[k] = "hash_123"
            row["tenant_id"] = self.tenant_id
            if "source_candidate_id" in row:
                row["source_candidate_id"] = str(uuid.uuid4())
            if "target_candidate_id" in row:
                row["target_candidate_id"] = str(uuid.uuid4())
            if "source_object_id" in row:
                row["source_object_id"] = str(uuid.uuid4())
            if "target_object_id" in row:
                row["target_object_id"] = str(uuid.uuid4())
            if "override_justification" in row:
                row["override_justification"] = "Manual override justification"
            synth_dataset[tbl] = [row]

        stats = self.migrator.migrate_from_dict(synth_dataset, dry_run=True)

        self.assertEqual(stats["canonical_tables_discovered"], 61)
        self.assertEqual(stats["canonical_tables_completed"], 61)
        self.assertEqual(stats["canonical_tables_failed"], 0)
        self.assertEqual(stats["failed_tables"], [])
        self.assertEqual(stats["target_documents_produced"], 25)
        self.assertEqual(stats["rows_persisted"], 0)
        self.assertEqual(len(stats["embedded_elements"]), 36)

    def test_persistence_of_diverse_subsystems(self):
        """Validates persistence and retrieval of diverse subsystems in SQLiteRepository."""
        aid = str(uuid.uuid4())
        vid = str(uuid.uuid4())
        ingest_id = str(uuid.uuid4())
        cap_id = str(uuid.uuid4())
        onto_evt_id = str(uuid.uuid4())

        dataset = {
            "assets": [{
                "asset_id": aid,
                "tenant_id": self.tenant_id,
                "platform": "POWER_BI",
                "asset_name": "Subsystem Test Asset",
            }],
            "asset_versions": [{
                "asset_version_id": vid,
                "asset_id": aid,
                "tenant_id": self.tenant_id,
                "version_number": 1,
                "content_hash": "hash_v1",
            }],
            "source_artifacts": [{
                "source_artifact_id": str(uuid.uuid4()),
                "asset_version_id": vid,
                "relative_path": "model.tmdl",
                "artifact_type": "MODEL",
                "content_hash": "hash_art_1",
                "size_bytes": 500,
            }],
            "ingestion_events": [{
                "ingestion_event_id": ingest_id,
                "tenant_id": self.tenant_id,
                "asset_version_id": vid,
                "uploaded_by_user_id": "operator",
                "original_filename": "report.pbip",
                "upload_size_bytes": 1024,
                "upload_source": "CLI",
                "ingestion_status": "COMPLETED",
            }],
            "platform_capabilities": [{
                "platform_capability_id": cap_id,
                "platform": "POWER_BI",
                "artifact_type": "PBIP",
                "metadata_type": "TMDL",
                "capability_status": "SUPPORTED",
            }],
            "ontology_change_events": [{
                "change_event_id": onto_evt_id,
                "tenant_id": self.tenant_id,
                "ontology_version_id": "ont_v1",
                "ontology_entry_id": "kpi_1",
                "actor_user_id": "lead_architect",
                "change_type": "ADD",
                "change_justification": "Initial standard KPI population",
            }],
        }

        stats = self.migrator.migrate_from_dict(dataset, dry_run=False)

        self.assertEqual(stats["canonical_tables_completed"], 6)
        self.assertEqual(stats["canonical_tables_failed"], 0)
        self.assertEqual(stats["rows_persisted"], 5)  # 5 independent documents

        ctx = TenantContext(tenant_id=self.tenant_id)
        sys_ctx = TenantContext.system_context()

        # Verify Asset Version with embedded source_artifacts
        ver_doc = self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_id, f"ver_{vid}", tenant_context=ctx)
        self.assertIsNotNone(ver_doc)
        self.assertEqual(len(ver_doc["source_artifacts"]), 1)
        self.assertEqual(ver_doc["source_artifacts"][0]["relative_path"], "model.tmdl")

        # Verify Ingestion Event in OPERATIONAL_AUDIT
        ingest_doc = self.repo.get_item(CosmosContainer.OPERATIONAL_AUDIT, self.tenant_id, f"ingest_{ingest_id}", tenant_context=ctx)
        self.assertIsNotNone(ingest_doc)
        self.assertEqual(ingest_doc["original_filename"], "report.pbip")

        # Verify Platform Capability in KPI_ONTOLOGY with SYSTEM partition key
        cap_doc = self.repo.get_item(CosmosContainer.KPI_ONTOLOGY, "SYSTEM", f"cap_{cap_id}", tenant_context=sys_ctx)
        self.assertIsNotNone(cap_doc)
        self.assertEqual(cap_doc["capability_status"], "SUPPORTED")

        # Verify Ontology Change Event in OPERATIONAL_AUDIT
        onto_doc = self.repo.get_item(CosmosContainer.OPERATIONAL_AUDIT, self.tenant_id, f"onto_evt_{onto_evt_id}", tenant_context=ctx)
        self.assertIsNotNone(onto_doc)
        self.assertEqual(onto_doc["actor_user_id"], "lead_architect")

    def test_declared_handler_is_actually_invoked(self):
        """Verifies that the handler declared in CANONICAL_MIGRATION_REGISTRY is dynamically invoked."""
        aid = str(uuid.uuid4())
        data = {
            "assets": [
                {
                    "asset_id": aid,
                    "tenant_id": self.tenant_id,
                    "platform": "POWER_BI",
                    "asset_name": "Handler Verification Asset",
                }
            ]
        }
        with patch.object(self.migrator, "_process_assets", wraps=self.migrator._process_assets) as spy_handler:
            stats = self.migrator.migrate_from_dict(data, dry_run=True)
            spy_handler.assert_called_once()
            self.assertIn("_process_assets", stats["invoked_handlers"])
            self.assertIn("assets", stats["completed_tables"])

    def test_changing_registry_handler_changes_execution(self):
        """Verifies that patching a table's handler in CANONICAL_MIGRATION_REGISTRY alters runtime execution."""
        custom_called = []

        def _custom_handler(raw_rows, **kwargs):
            custom_called.append(len(raw_rows))
            return []

        setattr(self.migrator, "_custom_handler", _custom_handler)

        disp_orig = CANONICAL_MIGRATION_REGISTRY["assets"]
        custom_disp = TableMigrationDisposition(
            source_table="assets",
            disposition=disp_orig.disposition,
            target_container=disp_orig.target_container,
            target_document_type=disp_orig.target_document_type,
            handler_function_name="_custom_handler",
        )

        with patch.dict("scripts.migrate_postgres_to_cosmos.CANONICAL_MIGRATION_REGISTRY", {"assets": custom_disp}):
            data = {"assets": [{"asset_id": "a1", "tenant_id": self.tenant_id, "asset_name": "Test"}]}
            stats = self.migrator.migrate_from_dict(data, dry_run=True)
            self.assertEqual(len(custom_called), 1)
            self.assertEqual(custom_called[0], 1)
            self.assertIn("_custom_handler", stats["invoked_handlers"])

    def test_embedded_disposition_honored_and_populates_parent(self):
        """Verifies that EMBEDDED_AGGREGATED tables are embedded into their parent aggregate."""
        aid = str(uuid.uuid4())
        vid = str(uuid.uuid4())
        art_id = str(uuid.uuid4())
        data = {
            "asset_versions": [
                {
                    "asset_version_id": vid,
                    "asset_id": aid,
                    "tenant_id": self.tenant_id,
                    "version_number": 1,
                    "content_hash": "h_v1",
                }
            ],
            "source_artifacts": [
                {
                    "source_artifact_id": art_id,
                    "asset_version_id": vid,
                    "relative_path": "definition.pbir",
                    "artifact_type": "REPORT",
                    "content_hash": "art_h",
                    "size_bytes": 1024,
                }
            ],
        }

        stats = self.migrator.migrate_from_dict(data, dry_run=True)
        self.assertEqual(stats["embedded_elements"]["source_artifacts"], 1)
        self.assertIn("source_artifacts", stats["completed_tables"])
        self.assertIn("asset_versions", stats["completed_tables"])

        ver_docs = self.migrator.last_target_docs.get(CosmosContainer.METADATA_CATALOG.value, [])
        self.assertEqual(len(ver_docs), 1)
        self.assertEqual(len(ver_docs[0].source_artifacts), 1)
        self.assertEqual(ver_docs[0].source_artifacts[0]["source_artifact_id"], art_id)
        self.assertEqual(ver_docs[0].source_artifacts[0]["relative_path"], "definition.pbir")

    def test_independent_persistence_routes_to_correct_container(self):
        """Verifies that independently persisted tables route their documents to the declared target container."""
        rid = str(uuid.uuid4())
        kpi_map_id = str(uuid.uuid4())
        ont_id = str(uuid.uuid4())
        ingest_id = str(uuid.uuid4())

        data = {
            "reports": [{
                "report_id": rid,
                "tenant_id": self.tenant_id,
                "asset_id": "a1",
                "asset_version_id": "v1",
                "report_name": "Catalog Report",
            }],
            "kpi_mappings": [{
                "kpi_mapping_id": kpi_map_id,
                "tenant_id": self.tenant_id,
                "mapping_run_id": "mrun_1",
                "source_object_id": "obj_1",
                "ontology_entry_id": "kpi_1",
                "mapping_status": "APPROVED",
                "confidence_score": 0.95,
            }],
            "kpi_ontology_entries": [{
                "ontology_entry_id": ont_id,
                "business_domain": "CLAIMS",
                "ontology_version_id": "ver_1",
                "kpi_code": "CLM_001",
                "kpi_name": "Ontology Claim KPI",
            }],
            "ingestion_events": [{
                "ingestion_id": ingest_id,
                "tenant_id": self.tenant_id,
                "asset_version_id": "v1",
                "uploaded_by_user_id": "u1",
                "original_filename": "f.pbip",
                "upload_size_bytes": 100,
                "upload_source": "CLI",
                "ingestion_status": "COMPLETED",
            }],
        }

        self.migrator.migrate_from_dict(data, dry_run=True)
        catalog_docs = self.migrator.last_target_docs.get(CosmosContainer.METADATA_CATALOG.value, [])
        governance_docs = self.migrator.last_target_docs.get(CosmosContainer.KPI_GOVERNANCE.value, [])
        ontology_docs = self.migrator.last_target_docs.get(CosmosContainer.KPI_ONTOLOGY.value, [])
        audit_docs = self.migrator.last_target_docs.get(CosmosContainer.OPERATIONAL_AUDIT.value, [])

        self.assertTrue(any(d.id == f"rep_{rid}" for d in catalog_docs))
        self.assertTrue(any(d.id == f"map_{kpi_map_id}" for d in governance_docs))
        self.assertTrue(any(d.id == f"kpi_{ont_id}" for d in ontology_docs))
        self.assertTrue(any(d.id == f"ingest_{ingest_id}" for d in audit_docs))

    def test_dry_run_produces_conversions_without_persisting(self):
        """Verifies that dry-run converts contracts and registers documents with zero persisted rows."""
        aid = str(uuid.uuid4())
        data = {
            "assets": [{
                "asset_id": aid,
                "tenant_id": self.tenant_id,
                "platform": "POWER_BI",
                "asset_name": "Dry Run Test Asset",
            }]
        }

        stats = self.migrator.migrate_from_dict(data, dry_run=True)
        self.assertEqual(stats["rows_persisted"], 0)
        self.assertEqual(stats["target_documents_produced"], 1)
        self.assertEqual(len(self.migrator.last_target_docs[CosmosContainer.METADATA_CATALOG.value]), 1)

        ctx = TenantContext(tenant_id=self.tenant_id)
        doc = self.repo.get_item(CosmosContainer.METADATA_CATALOG, self.tenant_id, f"asset_{aid}", tenant_context=ctx)
        self.assertIsNone(doc)

    def test_empty_table_behavior(self):
        """Verifies that empty source tables complete cleanly without errors or spurious documents."""
        data = {
            "assets": [],
            "source_artifacts": [],
        }

        stats = self.migrator.migrate_from_dict(data, dry_run=True)
        self.assertEqual(stats["canonical_tables_discovered"], 2)
        self.assertEqual(stats["canonical_tables_completed"], 2)
        self.assertEqual(stats["canonical_tables_failed"], 0)
        self.assertEqual(stats["target_documents_produced"], 0)
        self.assertEqual(stats["rows_persisted"], 0)

    def test_missing_or_invalid_handler_fails_preflight(self):
        """Verifies that an invalid or non-existent handler in the registry fails preflight validation and raises ValueError."""
        disp_orig = CANONICAL_MIGRATION_REGISTRY["assets"]
        invalid_disp = TableMigrationDisposition(
            source_table="assets",
            disposition=disp_orig.disposition,
            target_container=disp_orig.target_container,
            target_document_type=disp_orig.target_document_type,
            handler_function_name="_nonexistent_missing_handler_xyz",
        )

        with patch.dict("scripts.migrate_postgres_to_cosmos.CANONICAL_MIGRATION_REGISTRY", {"assets": invalid_disp}):
            is_valid, errors = self.migrator.validate_registry()
            self.assertFalse(is_valid)
            self.assertTrue(any("_nonexistent_missing_handler_xyz" in err for err in errors))

            with self.assertRaises(ValueError) as cm:
                self.migrator.migrate_from_dict({"assets": [{"asset_id": "a1"}]})
            self.assertIn("preflight validation failed", str(cm.exception))

    def test_runtime_handler_failure_recorded_in_failed_tables(self):
        """Verifies that an unexpected exception during handler execution is safely recorded in failed_tables."""
        aid = str(uuid.uuid4())
        data = {
            "assets": [{
                "asset_id": aid,
                "tenant_id": self.tenant_id,
                "asset_name": "Exploding Asset",
            }]
        }

        def _exploding_handler(raw_rows, **kwargs):
            raise RuntimeError("Deliberate injection failure in handler")

        with patch.object(self.migrator, "_process_assets", _exploding_handler):
            stats = self.migrator.migrate_from_dict(data, dry_run=True)
            self.assertIn("assets", stats["failed_tables"])
            self.assertEqual(stats["canonical_tables_failed"], 1)
            self.assertEqual(stats["target_documents_produced"], 0)


if __name__ == "__main__":
    unittest.main()

