"""
KPI Intelligence — PBIP Path Resilience & Windows Long-Path Regression Tests.

Validates:
1. PBIP ingestion using a short, configurable temporary root (KPI_TEMP_DIR).
2. Deeply nested report and visual directory structures (PBIR format).
3. Preservation of original project-relative paths.
4. Successful processing and canonical extraction of nested visual.json files.
5. Concurrent ingestion jobs receiving isolated, collision-free temporary workspaces.
6. Automatic temporary workspace cleanup after successful ingestion.
7. Cleanup and safe recovery after ingestion failure.
8. Descriptive failure when configured temporary directory is unavailable or unwritable.
9. Cross-platform path construction (extended-length \\\\?\\ syntax, UNC handling, sanitization).
10. Component length validation (max 255 chars per filename/directory).
"""

import os
import sys
import shutil
import tempfile
import unittest
from unittest.mock import patch

from backend.storage.sqlite.repository import SQLiteRepository
from backend.repository.context import TenantContext
from backend.contracts import CosmosContainer, DocumentType
from backend.storage.fixtures import TENANT_ALPHA, generate_synthetic_fixtures
from backend.ingestion.manager import IngestionManager
from backend.ingestion.paths import (
    to_extended_path,
    strip_extended_prefix,
    sanitize_path_for_diagnostics,
    validate_path_component_lengths,
    generate_short_job_id,
    resolve_staging_root,
    format_path_error_diagnostic,
    safe_makedirs,
    safe_open,
    safe_rmtree,
)
from backend.connectors.powerbi.discovery import PbipDiscovery, detect_artifact_type
from backend.connectors.powerbi.report_parser import ReportParser, ReportDefinition


class TestPbipPathResilience(unittest.TestCase):
    def setUp(self):
        # Create isolated temporary database for test
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db_path = self.temp_file.name
        self.temp_file.close()

        self.custom_temp_dir = tempfile.mkdtemp(prefix="kpi_short_tmp_")
        self.repo = SQLiteRepository(self.temp_db_path)
        self.tenant_id = TENANT_ALPHA

        # Seed minimal fixtures
        fixtures = generate_synthetic_fixtures()
        for container, docs in fixtures.items():
            for doc in docs:
                p_key = getattr(doc, "business_domain", "GENERAL") if container == CosmosContainer.KPI_ONTOLOGY else (getattr(doc, "tenant_id", None) or TENANT_ALPHA)
                ctx = TenantContext.system_context() if container == CosmosContainer.KPI_ONTOLOGY else TenantContext(tenant_id=p_key)
                self.repo.upsert_item(container, p_key, doc.to_dict(), ctx)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.unlink(self.temp_db_path)
            except Exception:
                pass
        if os.path.exists(self.custom_temp_dir):
            shutil.rmtree(self.custom_temp_dir, ignore_errors=True)

    def _create_deep_pbir_batch(self, base_name: str = "Loss Ratio") -> list:
        """
        Constructs an in-memory 39-file PBIP project batch with deep nesting resembling:
        <base_name>/<base_name>.Report/definition/pages/<page_guid>/visuals/<visual_guid>/visual.json
        """
        files = []

        # 1. PBIP manifest
        pbip_content = f'{{"version": "1.0", "artifacts": [{{"report": {{"path": "{base_name}.Report"}}}}]}}'.encode("utf-8")
        files.append({
            "filename": f"{base_name}.pbip",
            "relative_path": f"{base_name}/{base_name}.pbip",
            "content": pbip_content,
        })

        # 2. .Report / definition.pbir
        pbir_content = f'{{"version": "1.0", "datasetReference": {{"byPath": {{"path": "../{base_name}.SemanticModel"}}}}}}'.encode("utf-8")
        files.append({
            "filename": "definition.pbir",
            "relative_path": f"{base_name}/{base_name}.Report/definition.pbir",
            "content": pbir_content,
        })

        # 3. .Report / definition / report.json
        rep_json = b'{"theme": "CY24SU10", "config": "{}", "filters": []}'
        files.append({
            "filename": "report.json",
            "relative_path": f"{base_name}/{base_name}.Report/definition/report.json",
            "content": rep_json,
        })

        # 4. Deeply nested PBIR pages and visuals
        pages_meta = b'{"pageOrder": ["Page_Executive_001", "Page_Claims_002"]}'
        files.append({
            "filename": "pages.json",
            "relative_path": f"{base_name}/{base_name}.Report/definition/pages/pages.json",
            "content": pages_meta,
        })

        # Page 1 & Visuals
        page1_dir = "Page_Executive_Summary_LongIdentifier_Section123456789"
        page1_json = b'{"name": "Page_Executive_001", "displayName": "Executive Summary", "width": 1280, "height": 720}'
        files.append({
            "filename": "page.json",
            "relative_path": f"{base_name}/{base_name}.Report/definition/pages/{page1_dir}/page.json",
            "content": page1_json,
        })

        # 4 visuals under Page 1 with long GUID folder names
        for v_num in range(1, 5):
            v_dir = f"VisualContainer_DeeplyNested_Component_Guid_{v_num:04d}_0123456789abcdef"
            v_content = f"""{{
                "name": "Visual_Card_{v_num}",
                "position": {{"x": 10, "y": {v_num * 50}, "z": {v_num}, "width": 300, "height": 100}},
                "visual": {{
                    "visualType": "card",
                    "query": {{
                        "queryState": {{
                            "Values": {{
                                "projections": [
                                    {{"queryRef": "Loss Ratio.IncurredLosses"}}
                                ]
                            }}
                        }}
                    }},
                    "objects": {{
                        "title": [{{"properties": {{"text": {{"expr": {{"Literal": {{"Value": "'Incurred Losses {v_num}'"}}}}}}}}}}]
                    }}
                }}
            }}""".encode("utf-8")
            files.append({
                "filename": "visual.json",
                "relative_path": f"{base_name}/{base_name}.Report/definition/pages/{page1_dir}/visuals/{v_dir}/visual.json",
                "content": v_content,
            })

        # 5. .SemanticModel / definition / TMDL files
        files.append({
            "filename": "definition.pbism",
            "relative_path": f"{base_name}/{base_name}.SemanticModel/definition.pbism",
            "content": b'{"version": "1.0"}',
        })
        files.append({
            "filename": "database.tmdl",
            "relative_path": f"{base_name}/{base_name}.SemanticModel/definition/database.tmdl",
            "content": b"database 'Loss Ratio'\n\tcompatibilityLevel: 1567\n",
        })
        files.append({
            "filename": "model.tmdl",
            "relative_path": f"{base_name}/{base_name}.SemanticModel/definition/model.tmdl",
            "content": b"model Model\n\tculture: en-US\n",
        })
        files.append({
            "filename": "relationships.tmdl",
            "relative_path": f"{base_name}/{base_name}.SemanticModel/definition/relationships.tmdl",
            "content": b"",
        })
        files.append({
            "filename": "expressions.tmdl",
            "relative_path": f"{base_name}/{base_name}.SemanticModel/definition/expressions.tmdl",
            "content": b"",
        })
        # Add tables
        claims_tmdl = b"""table 'Loss Ratio'
\tlineageTag: tag-loss-ratio
\tmeasure 'Incurred Losses' = SUM('Loss Ratio'[LossAmount])
\t\tformatString: \$#,##0
\tcolumn LossAmount
\t\tdataType: int64
\t\tsummarizeBy: sum
"""
        files.append({
            "filename": "Loss Ratio.tmdl",
            "relative_path": f"{base_name}/{base_name}.SemanticModel/definition/tables/Loss Ratio.tmdl",
            "content": claims_tmdl,
        })

        return files

    def test_short_temporary_root_resolution(self):
        """1. Tests that IngestionManager resolves to the short temporary directory when configured."""
        with patch.dict(os.environ, {"KPI_TEMP_DIR": self.custom_temp_dir}):
            mgr = IngestionManager(repository=self.repo)
            self.assertEqual(mgr.staging_root, os.path.abspath(self.custom_temp_dir))

    def test_deep_pbir_ingestion_success(self):
        """2, 3, 4. Tests PBIP ingestion with deep PBIR report definition, visual bindings, and path preservation."""
        mgr = IngestionManager(repository=self.repo, staging_root=self.custom_temp_dir)
        files = self._create_deep_pbir_batch("Loss Ratio")

        result = mgr.process_file_batch(self.tenant_id, files)

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["files_received"], len(files))
        self.assertEqual(result["files_processed"], len(files))
        self.assertIsNotNone(result["asset_id"])
        self.assertEqual(result["asset_name"], "Loss Ratio")

        # Verify reports and visuals were persisted in repository
        ctx = TenantContext(tenant_id=self.tenant_id)
        reports = self.repo.query_items(
            CosmosContainer.METADATA_CATALOG,
            self.tenant_id,
            type("Spec", (), {"query": "SELECT * FROM c WHERE c.tenant_id = @t AND c.doc_type = @dt", "parameters": [{"name": "@t", "value": self.tenant_id}, {"name": "@dt", "value": DocumentType.REPORT.value}]})(),
            ctx
        )
        self.assertTrue(len(reports.items) > 0)
        rep = reports.items[0]
        self.assertEqual(len(rep.get("pages", [])), 1)
        self.assertEqual(len(rep["pages"][0].get("visuals", [])), 4)

    def test_concurrent_jobs_receive_isolated_workspaces(self):
        """5. Verifies concurrent jobs receive isolated, collision-safe temporary directories."""
        id1, dir1 = generate_short_job_id()
        id2, dir2 = generate_short_job_id()

        self.assertNotEqual(id1, id2)
        self.assertNotEqual(dir1, dir2)
        self.assertTrue(dir1.startswith("j_"))
        self.assertTrue(dir2.startswith("j_"))
        self.assertEqual(len(dir1), 14)  # j_ + 12 hex chars

    def test_cleanup_after_successful_ingestion(self):
        """6. Confirms that temporary staging folders are completely cleaned up upon success."""
        mgr = IngestionManager(repository=self.repo, staging_root=self.custom_temp_dir)
        files = self._create_deep_pbir_batch("Loss Ratio")

        res = mgr.process_file_batch(self.tenant_id, files)
        self.assertEqual(res["status"], "COMPLETED")

        # Verify no remaining subfolders in staging root
        remaining = os.listdir(self.custom_temp_dir)
        self.assertEqual(remaining, [])

    def test_cleanup_after_ingestion_failure(self):
        """7. Confirms that temporary staging folders are safely cleaned up even if ingestion fails."""
        mgr = IngestionManager(repository=self.repo, staging_root=self.custom_temp_dir)
        # Invalid batch: no .pbip file
        bad_files = [{"filename": "orphan.txt", "relative_path": "orphan.txt", "content": b"hello"}]

        res = mgr.process_file_batch(self.tenant_id, bad_files)
        self.assertEqual(res["status"], "FAILED")

        # Verify staging folder is cleaned up
        remaining = os.listdir(self.custom_temp_dir)
        self.assertEqual(remaining, [])

    def test_unavailable_configured_temporary_directory(self):
        """8. Confirms clear diagnostic error when configured directory is unwritable or invalid."""
        unwritable_path = "/root/prohibited_kpi_tmp_test"
        if sys.platform == "win32":
            unwritable_path = "Z:\\nonexistent_network_drive\\kpi_tmp"

        with patch.dict(os.environ, {"KPI_TEMP_DIR": unwritable_path}):
            with self.assertRaises(PermissionError) as ctx:
                resolve_staging_root()
            self.assertIn("cannot be created", str(ctx.exception))

    def test_cross_platform_path_construction(self):
        """9. Validates extended-length Windows syntax, UNC handling, and diagnostic sanitization."""
        # Simulated Windows drive path
        with patch("backend.ingestion.paths.is_windows", return_value=True):
            ext_drive = to_extended_path("C:/kpi_tmp/sub/file.json")
            self.assertEqual(ext_drive, "\\\\?\\C:\\kpi_tmp\\sub\\file.json")

            # UNC path
            ext_unc = to_extended_path("//corp.server/share/folder/file.json")
            self.assertTrue(ext_unc.startswith("\\\\?\\UNC\\corp.server\\share"))

            # Idempotency
            self.assertEqual(to_extended_path(ext_drive), ext_drive)

            # Strip prefix
            self.assertEqual(strip_extended_prefix(ext_drive), "C:\\kpi_tmp\\sub\\file.json")

        # Non-Windows should not prepend \\?\
        with patch("backend.ingestion.paths.is_windows", return_value=False):
            unix_path = to_extended_path("/tmp/kpi_tmp/sub/file.json")
            self.assertFalse(unix_path.startswith("\\\\?\\"))

        # Diagnostic sanitization
        win_user_path = "C:\\Users\\JohnDoe\\OneDrive\\Projects\\KPI\\file.json"
        sanitized = sanitize_path_for_diagnostics(win_user_path)
        self.assertNotIn("JohnDoe", sanitized)
        self.assertIn("[REDACTED_USER]", sanitized)

    def test_component_length_validation(self):
        """10. Confirms that an individual path component exceeding 255 chars is flagged explicitly."""
        overlong_name = "A" * 256
        rel_path = f"folder/{overlong_name}/file.json"

        with self.assertRaises(ValueError) as ctx:
            validate_path_component_lengths(rel_path)
        self.assertIn("exceeds maximum component length of 255 characters", str(ctx.exception))

    def test_winerror_206_diagnostic_formatting(self):
        """Validates that WinError 206 produces actionable non-secret diagnostic telemetry."""
        fake_os_err = OSError("The filename or extension is too long")
        setattr(fake_os_err, "winerror", 206)

        diag = format_path_error_diagnostic(
            "C:\\Users\\TestUser\\VeryLongDirectoryPath\\visual.json",
            "write_staged_file",
            fake_os_err
        )

        self.assertEqual(diag["code"], "PATH_LENGTH_EXCEEDED")
        self.assertEqual(diag["operation"], "write_staged_file")
        self.assertNotIn("TestUser", diag["sanitized_path"])
        self.assertIn("KPI_TEMP_DIR", diag["remediation"])

    def test_artifact_detection_for_pbir(self):
        """Verifies detect_artifact_type recognizes PBIR page and visual definitions as supported."""
        t1, m1, s1 = detect_artifact_type("definition/pages/Page1/page.json")
        self.assertEqual(t1, "PBIR_PAGE_DEFINITION")
        self.assertTrue(s1)

        t2, m2, s2 = detect_artifact_type("definition/pages/Page1/visuals/Vis1/visual.json")
        self.assertEqual(t2, "PBIR_VISUAL_DEFINITION")
        self.assertTrue(s2)

        t3, m3, s3 = detect_artifact_type("definition/pages/pages.json")
        self.assertEqual(t3, "PBIR_PAGES_METADATA")
        self.assertTrue(s3)


if __name__ == "__main__":
    unittest.main()
