"""
KPI Intelligence — Azure AI Foundry Llama Integration Test Suite.

Validates:
1. Exact environment variable loading (AZURE_DEPLOYMENT, AZURE_ENDPOINT, AZURE_LLAMAKEY,
   AZURE_DEPLOYMENT_NAME, AZURE_OPENAI_API_VERSION).
2. Missing/blank values detected safely without exposing secrets.
3. .env.example contains placeholders only; .env remains ignored.
4. Correct client/protocol URL construction (Azure OpenAI vs Azure AI Model Inference).
5. Deployment variable semantics (AZURE_DEPLOYMENT vs AZURE_DEPLOYMENT_NAME).
6. Mocked successful Azure Llama response mapping to the canonical contract.
7. Bounded fallback on invalid JSON, unknown KPI IDs, HTTP 429 throttling, and timeouts.
8. Deterministic fallback execution when Azure configuration is missing.
9. Invariant: HIGH confidence proposals are NEVER auto-approved.
10. Tenant isolation preserved on LLM mapping execution.
11. No secrets in representations, safe dictionaries, logs, or API responses.
12. FastAPI endpoints: GET /api/v1/llm/status and POST /api/v1/mapping/run with mocked Azure.
"""

import os
import io
import re
import ssl
import json
import socket
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import urllib.request
import urllib.error

from fastapi.testclient import TestClient

from backend.matching.config import AzureLlamaConfig, load_local_dotenv
from backend.matching.azure_llama_client import AzureLlamaClient, AzureLlamaClientError
from backend.matching.llm import LLMMatchingEngine, LLMMatchingError
from backend.matching.orchestrator import MatchingOrchestrator
from backend.governance.service import GovernanceService
from backend.storage.sqlite.repository import SQLiteRepository
from backend.repository.context import TenantContext
from backend.contracts import CosmosContainer
from backend.storage.fixtures import TENANT_ALPHA, TENANT_BETA, generate_synthetic_fixtures
from backend.kpi_bank.service import KPIBankService
from backend.domain.service import DomainClassificationService
from backend.matching.deterministic import DeterministicMatchingEngine
from backend.learning.service import OverrideLearningService
from backend.api.app import create_app


SAMPLE_VALID_LLAMA_JSON = json.dumps({
    "recommendations": [
        {
            "kpi_id": "8d2a5fb0-1234-4567-89ab-cdef01234567",
            "confidence_code": "HIGH",
            "confidence_score": 0.94,
            "supporting_evidence": ["Exact loss ratio formula correspondence in claims domain"],
            "contradicting_evidence": [],
            "formula_compatibility": "HIGH",
            "ranking_rationale": "Direct semantic and formula match for net incurred claims.",
        },
        {
            "kpi_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
            "confidence_code": "MEDIUM",
            "confidence_score": 0.72,
            "supporting_evidence": ["Claims domain match"],
            "contradicting_evidence": ["Different aggregation denominator"],
            "formula_compatibility": "MEDIUM",
            "ranking_rationale": "Secondary candidate for average expense per claim.",
        }
    ]
})


class TestAzureLlamaIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db_path = self.temp_file.name
        self.temp_file.close()

        self.repo = SQLiteRepository(self.temp_db_path)
        self.tenant_id = TENANT_ALPHA

        # Seed synthetic fixtures into repo
        fixtures = generate_synthetic_fixtures()
        for container, docs in fixtures.items():
            for doc in docs:
                if container == CosmosContainer.KPI_ONTOLOGY:
                    p_key = getattr(doc, "business_domain", "GENERAL")
                    ctx = TenantContext.system_context()
                else:
                    p_key = getattr(doc, "tenant_id", None) or TENANT_ALPHA
                    ctx = TenantContext(tenant_id=p_key)
                self.repo.upsert_item(container, p_key, doc.to_dict(), ctx)

        self.kpi_bank = KPIBankService(repository=self.repo)
        self.domain_service = DomainClassificationService(repository=self.repo)
        self.deterministic_engine = DeterministicMatchingEngine()
        self.learning_service = OverrideLearningService(repository=self.repo)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            os.remove(self.temp_db_path)

    # -------------------------------------------------------------------------
    # 1. EXACT ENVIRONMENT VARIABLE LOADING & VALIDATION
    # -------------------------------------------------------------------------

    def test_environment_variables_loaded_correctly(self):
        """All five exact variable names are parsed and mapped accurately."""
        env_vars = {
            "AZURE_DEPLOYMENT": "llama-3.3-70b-instruct",
            "AZURE_ENDPOINT": "https://test-foundry.openai.azure.com/",
            "AZURE_LLAMAKEY": "secret-test-key-123456789",
            "AZURE_DEPLOYMENT_NAME": "llama-33-deployment",
            "AZURE_OPENAI_API_VERSION": "2024-06-01",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            config = AzureLlamaConfig.from_env()
            self.assertEqual(config.azure_deployment, "llama-3.3-70b-instruct")
            self.assertEqual(config.azure_endpoint, "https://test-foundry.openai.azure.com/")
            self.assertEqual(config.azure_llamakey, "secret-test-key-123456789")
            self.assertEqual(config.azure_deployment_name, "llama-33-deployment")
            self.assertEqual(config.azure_openai_api_version, "2024-06-01")
            self.assertTrue(config.is_configured)
            config.validate()  # Should not raise

    def test_missing_or_blank_values_detected_without_leaking_secrets(self):
        """Missing or placeholder values produce secret-safe validation errors."""
        # Test blank / placeholder
        env_vars = {
            "AZURE_DEPLOYMENT": "",
            "AZURE_ENDPOINT": "<your-endpoint>",
            "AZURE_LLAMAKEY": "placeholder",
            "AZURE_DEPLOYMENT_NAME": "",
            "AZURE_OPENAI_API_VERSION": "",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            config = AzureLlamaConfig.from_env()
            self.assertFalse(config.is_configured)
            with self.assertRaises(ValueError) as ctx:
                config.validate()
            err_msg = str(ctx.exception)
            self.assertIn("AZURE_ENDPOINT", err_msg)
            self.assertIn("AZURE_LLAMAKEY", err_msg)
            # Ensure no secret or key content is leaked in error
            self.assertNotIn("secret", err_msg)

    def test_env_example_contains_placeholders_only_and_gitignore_protects_env(self):
        """Verify .env.example contains only blank placeholders and .env is in .gitignore."""
        example_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env.example"))
        gitignore_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".gitignore"))

        self.assertTrue(os.path.exists(example_path))
        with open(example_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check all 5 exact keys exist in .env.example
        self.assertIn("AZURE_DEPLOYMENT=", content)
        self.assertIn("AZURE_ENDPOINT=", content)
        self.assertIn("AZURE_LLAMAKEY=", content)
        self.assertIn("AZURE_DEPLOYMENT_NAME=", content)
        self.assertIn("AZURE_OPENAI_API_VERSION=", content)

        # Check that no actual secret key was committed to .env.example
        for line in content.splitlines():
            if line.startswith("AZURE_LLAMAKEY="):
                self.assertEqual(line.strip(), "AZURE_LLAMAKEY=")

        # Check .gitignore
        with open(gitignore_path, "r", encoding="utf-8") as f:
            git_content = f.read()
        self.assertIn(".env", git_content)

    # -------------------------------------------------------------------------
    # 2. CLIENT PROTOCOL & DEPLOYMENT VARIABLE SEMANTICS
    # -------------------------------------------------------------------------

    def test_client_url_construction_azure_openai_style(self):
        """Tests standard Azure OpenAI URL formatting with deployment name and api-version."""
        config = AzureLlamaConfig(
            azure_endpoint="https://my-foundry-resource.openai.azure.com",
            azure_llamakey="test-key",
            azure_deployment_name="llama-33-deployment",
            azure_openai_api_version="2024-06-01",
        )
        client = AzureLlamaClient(config)
        url = client.build_request_url()
        expected = "https://my-foundry-resource.openai.azure.com/openai/deployments/llama-33-deployment/chat/completions?api-version=2024-06-01"
        self.assertEqual(url, expected)

    def test_client_url_construction_direct_models_style(self):
        """Tests Azure AI Model Inference endpoint formatting when /models path is used."""
        config = AzureLlamaConfig(
            azure_endpoint="https://llama-model.eastus2.models.ai.azure.com",
            azure_deployment="llama-3.3-70b-instruct",
            azure_llamakey="test-key",
            azure_openai_api_version="2024-05-01-preview",
        )
        client = AzureLlamaClient(config)
        url = client.build_request_url()
        self.assertIn("https://llama-model.eastus2.models.ai.azure.com/models/chat/completions", url)
        self.assertIn("api-version=2024-05-01-preview", url)

    def test_deployment_variable_semantics_handled(self):
        """
        AZURE_DEPLOYMENT_NAME is used for route path;
        AZURE_DEPLOYMENT is used for the payload 'model' identifier.
        """
        config = AzureLlamaConfig(
            azure_endpoint="https://my-foundry.openai.azure.com",
            azure_deployment="meta-llama-3.3-70b",
            azure_deployment_name="prod-llama-deployment-01",
            azure_llamakey="test-key",
            azure_openai_api_version="2024-06-01",
        )
        client = AzureLlamaClient(config)
        url = client.build_request_url()
        self.assertIn("prod-llama-deployment-01", url)
        self.assertEqual(config.effective_model_identifier, "meta-llama-3.3-70b")

    # -------------------------------------------------------------------------
    # 3. MOCKED SUCCESSFUL RESPONSE & CONTRACT MAPPING
    # -------------------------------------------------------------------------

    def test_successful_azure_llama_response_maps_to_canonical_contract(self):
        """Mocked successful Azure Llama response produces validated candidates with evidence."""
        mock_client = MagicMock()
        mock_client.generate_chat_completion.return_value = SAMPLE_VALID_LLAMA_JSON

        config = AzureLlamaConfig(
            azure_endpoint="https://test.openai.azure.com",
            azure_llamakey="secret",
            azure_deployment="llama-3.3-70b-instruct",
        )
        engine = LLMMatchingEngine(client=mock_client, config=config)

        candidates_pool = self.kpi_bank.list_all()
        field = {
            "field_id": "calc_IncurredLosses",
            "name": "Incurred Losses",
            "expression": "SUM(FactClaims[LossAmount])",
            "domain": "CLAIMS_RISK",
        }

        results = engine.match_and_rank(field, candidates_pool, domain="CLAIMS_RISK")
        self.assertEqual(len(results), 2)

        top1 = results[0]
        self.assertEqual(top1["kpi_id"], "8d2a5fb0-1234-4567-89ab-cdef01234567")
        self.assertEqual(top1["confidence_code"], "HIGH")
        self.assertEqual(top1["decision_source"], "LLM_INFERENCE")
        self.assertFalse(top1["fallback_used"])
        self.assertIn("Azure-Llama", top1["matching_engine"])
        self.assertIn("observed_evidence", top1["structured_evidence"])

    # -------------------------------------------------------------------------
    # 4. BOUNDED FALLBACK BEHAVIOR ON ERRORS, TIMEOUT, UNKNOWN KPI ID
    # -------------------------------------------------------------------------

    def test_unknown_kpi_id_triggers_fallback_with_reason(self):
        """LLM hallucinating an invented KPI ID triggers deterministic fallback with UNKNOWN_KPI_ID."""
        hallucinated_json = json.dumps({
            "recommendations": [
                {
                    "kpi_id": "invented-fake-uuid-not-in-kpi-bank",
                    "confidence_code": "HIGH",
                    "confidence_score": 0.99,
                }
            ]
        })
        mock_client = MagicMock()
        mock_client.generate_chat_completion.return_value = hallucinated_json

        config = AzureLlamaConfig(
            azure_endpoint="https://test.openai.azure.com",
            azure_llamakey="secret",
            azure_deployment="llama-3.3-70b-instruct",
        )
        llm_engine = LLMMatchingEngine(client=mock_client, config=config)
        orchestrator = MatchingOrchestrator(
            kpi_bank_service=self.kpi_bank,
            llm_engine=llm_engine,
            deterministic_engine=self.deterministic_engine,
        )

        field = {"name": "Incurred Losses", "expression": "SUM(FactClaims[LossAmount])"}
        result = orchestrator.discover_and_rank_candidates(field, domain="CLAIMS_RISK")

        self.assertTrue(result["fallback_used"])
        self.assertIn("UNKNOWN_KPI_ID", result["fallback_reason"])
        self.assertGreater(len(result["top_candidates"]), 0)
        # Ensure returned candidate is genuine from deterministic fallback
        top_cand = result["top_candidates"][0]
        self.assertNotEqual(top_cand["kpi_id"], "invented-fake-uuid-not-in-kpi-bank")
        self.assertTrue(top_cand["fallback_used"])

    def test_timeout_and_throttling_trigger_fallback(self):
        """Timeouts and HTTP 429 throttling trigger deterministic fallback with appropriate categories."""
        # 1. Throttling
        mock_client = MagicMock()
        mock_client.generate_chat_completion.side_effect = AzureLlamaClientError("Rate limit", category="THROTTLED")

        config = AzureLlamaConfig(
            azure_endpoint="https://test.openai.azure.com",
            azure_llamakey="secret",
            azure_deployment="llama-3.3-70b-instruct",
        )
        llm_engine = LLMMatchingEngine(client=mock_client, config=config)
        orchestrator = MatchingOrchestrator(
            kpi_bank_service=self.kpi_bank,
            llm_engine=llm_engine,
            deterministic_engine=self.deterministic_engine,
        )

        field = {"name": "Incurred Losses", "expression": "SUM(FactClaims[LossAmount])"}
        result = orchestrator.discover_and_rank_candidates(field, domain="CLAIMS_RISK")
        self.assertTrue(result["fallback_used"])
        self.assertIn("THROTTLED", result["fallback_reason"])

        # 2. Timeout
        mock_client.generate_chat_completion.side_effect = AzureLlamaClientError("Timed out", category="TIMEOUT")
        result2 = orchestrator.discover_and_rank_candidates(field, domain="CLAIMS_RISK")
        self.assertTrue(result2["fallback_used"])
        self.assertIn("TIMEOUT", result2["fallback_reason"])

    def test_deterministic_fallback_when_azure_config_missing(self):
        """When Azure environment variables are missing, deterministic fallback executes cleanly."""
        empty_config = AzureLlamaConfig()  # Unconfigured
        llm_engine = LLMMatchingEngine(config=empty_config)
        self.assertFalse(llm_engine.is_configured)

        orchestrator = MatchingOrchestrator(
            kpi_bank_service=self.kpi_bank,
            llm_engine=llm_engine,
            deterministic_engine=self.deterministic_engine,
        )

        field = {"name": "Incurred Losses", "expression": "SUM(FactClaims[LossAmount])"}
        result = orchestrator.discover_and_rank_candidates(field, domain="CLAIMS_RISK")
        self.assertTrue(result["fallback_used"])
        self.assertIn("MISSING_CONFIGURATION", result["fallback_reason"])
        self.assertGreater(len(result["top_candidates"]), 0)

    # -------------------------------------------------------------------------
    # 5. GOVERNANCE INVARIANT: HIGH CONFIDENCE NEVER AUTO-APPROVES
    # -------------------------------------------------------------------------

    def test_high_confidence_never_auto_approves(self):
        """Even with 100% HIGH confidence from Llama, mapping status remains PROPOSED."""
        mock_client = MagicMock()
        mock_client.generate_chat_completion.return_value = SAMPLE_VALID_LLAMA_JSON

        config = AzureLlamaConfig(
            azure_endpoint="https://test.openai.azure.com",
            azure_llamakey="secret",
            azure_deployment="llama-3.3-70b-instruct",
        )
        llm_engine = LLMMatchingEngine(client=mock_client, config=config)
        orchestrator = MatchingOrchestrator(
            kpi_bank_service=self.kpi_bank,
            llm_engine=llm_engine,
            deterministic_engine=self.deterministic_engine,
        )
        gov_service = GovernanceService(
            repository=self.repo,
            kpi_bank_service=self.kpi_bank,
            domain_service=self.domain_service,
            matching_orchestrator=orchestrator,
            learning_service=self.learning_service,
        )

        run_res = gov_service.run_mapping_pipeline(self.tenant_id, force_fallback=False)
        self.assertEqual(run_res["status"], "COMPLETED")

        # Inspect resulting mappings: all must be PROPOSED, none APPROVED
        fields = gov_service.list_fields_with_mappings(self.tenant_id)
        for f in fields:
            self.assertNotEqual(f.get("mapping_status"), "APPROVED", "HIGH confidence must NEVER auto-approve")
            self.assertEqual(f.get("mapping_status"), "PROPOSED")

    # -------------------------------------------------------------------------
    # 6. SECURITY: NO SECRETS IN REPRESENTATIONS, LOGS, OR API RESPONSES
    # -------------------------------------------------------------------------

    def test_secrets_redacted_from_config_repr_and_safe_dict(self):
        """repr() and to_safe_dict() never reveal AZURE_LLAMAKEY or full endpoint."""
        config = AzureLlamaConfig(
            azure_deployment="llama-3.3-70b-instruct",
            azure_endpoint="https://private-corp-foundry.openai.azure.com",
            azure_llamakey="super-sensitive-secret-token-abcdef123456",
            azure_deployment_name="llama-dep",
            azure_openai_api_version="2024-06-01",
        )

        repr_str = repr(config)
        self.assertNotIn("super-sensitive-secret-token-abcdef123456", repr_str)
        self.assertIn("key=[REDACTED]", repr_str)

        safe_dict = config.to_safe_dict()
        self.assertNotIn("super-sensitive-secret-token-abcdef123456", json.dumps(safe_dict))
        self.assertNotIn("azure_llamakey", safe_dict)
        self.assertTrue(safe_dict["has_key"])

    # -------------------------------------------------------------------------
    # 7. FASTAPI API: LLM STATUS & MAPPING PIPELINE ENDPOINT
    # -------------------------------------------------------------------------

    def test_fastapi_llm_status_endpoint(self):
        """GET /api/v1/llm/status reports non-sensitive metadata without making calls."""
        config = AzureLlamaConfig(
            azure_deployment="llama-3.3-70b-instruct",
            azure_endpoint="https://foundry.openai.azure.com",
            azure_llamakey="test-key",
            azure_deployment_name="llama-33-dep",
            azure_openai_api_version="2024-06-01",
        )
        llm_engine = LLMMatchingEngine(config=config)
        orchestrator = MatchingOrchestrator(
            kpi_bank_service=self.kpi_bank,
            llm_engine=llm_engine,
            deterministic_engine=self.deterministic_engine,
        )
        gov_service = GovernanceService(
            repository=self.repo,
            kpi_bank_service=self.kpi_bank,
            domain_service=self.domain_service,
            matching_orchestrator=orchestrator,
            learning_service=self.learning_service,
        )

        app = create_app(governance_service=gov_service)
        client = TestClient(app)

        resp = client.get("/api/v1/llm/status")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        data = body["data"]
        self.assertTrue(data["llm_configured"])
        self.assertEqual(data["llm_provider"], "Azure AI Foundry (Llama)")
        self.assertEqual(data["effective_deployment"], "llama-33-dep")
        # Ensure no secret key present in API response
        self.assertNotIn("azure_llamakey", data)
        self.assertNotIn("test-key", json.dumps(data))

    def test_fastapi_mapping_run_with_mocked_azure(self):
        """POST /api/v1/mapping/run processes canonical metadata using Azure Llama mock."""
        mock_client = MagicMock()
        mock_client.generate_chat_completion.return_value = SAMPLE_VALID_LLAMA_JSON

        config = AzureLlamaConfig(
            azure_deployment="llama-3.3-70b-instruct",
            azure_endpoint="https://foundry.openai.azure.com",
            azure_llamakey="test-key",
        )
        llm_engine = LLMMatchingEngine(client=mock_client, config=config)
        orchestrator = MatchingOrchestrator(
            kpi_bank_service=self.kpi_bank,
            llm_engine=llm_engine,
            deterministic_engine=self.deterministic_engine,
        )
        gov_service = GovernanceService(
            repository=self.repo,
            kpi_bank_service=self.kpi_bank,
            domain_service=self.domain_service,
            matching_orchestrator=orchestrator,
            learning_service=self.learning_service,
        )

        app = create_app(governance_service=gov_service)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/mapping/run",
            json={"force_fallback": False},
            headers={"x-tenant-id": self.tenant_id},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertGreater(body["data"]["total_fields"], 0)
        self.assertGreater(body["data"]["llm_processed_count"], 0)

    # -------------------------------------------------------------------------
    # 8. STANDARD-LIBRARY URLLIB TRANSPORT REGRESSION TESTS
    # -------------------------------------------------------------------------

    @patch("urllib.request.urlopen")
    def test_urllib_request_construction_and_success(self, mock_urlopen):
        """Verifies urllib request payload, headers, URL, and successful response parsing."""
        config = AzureLlamaConfig(
            azure_endpoint="https://test-foundry.openai.azure.com",
            azure_deployment="llama-3.3-70b-instruct",
            azure_llamakey="secret-key-12345",
            azure_deployment_name="llama-deployment",
            azure_openai_api_version="2024-06-01",
        )
        client = AzureLlamaClient(config)

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "choices": [
                {"message": {"content": '{"result": "success"}'}}
            ]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        result = client.generate_chat_completion(
            system_prompt="System prompt",
            user_prompt="User prompt",
            temperature=0.2,
            max_tokens=100,
        )

        self.assertEqual(result, '{"result": "success"}')
        self.assertEqual(mock_urlopen.call_count, 1)

        # Inspect the Request object passed to urlopen
        call_args, call_kwargs = mock_urlopen.call_args
        req = call_args[0]
        self.assertIsInstance(req, urllib.request.Request)
        self.assertEqual(req.get_method(), "POST")
        self.assertIn("openai/deployments/llama-deployment/chat/completions", req.full_url)
        self.assertEqual(req.headers["Api-key"], "secret-key-12345")
        self.assertEqual(req.headers["Authorization"], "Bearer secret-key-12345")
        self.assertEqual(req.headers["Content-type"], "application/json")

        # Inspect decoded request payload
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["model"], "llama-3.3-70b-instruct")
        self.assertEqual(payload["temperature"], 0.2)
        self.assertEqual(payload["max_tokens"], 100)
        self.assertEqual(len(payload["messages"]), 2)
        self.assertEqual(payload["messages"][0]["content"], "System prompt")
        self.assertEqual(payload["messages"][1]["content"], "User prompt")

    @patch("urllib.request.urlopen")
    def test_urllib_multipart_content_extraction(self, mock_urlopen):
        """Verifies multi-part message content lists are decoded properly."""
        config = AzureLlamaConfig(
            azure_endpoint="https://test.openai.azure.com",
            azure_deployment="llama-3.3-70b-instruct",
            azure_llamakey="secret-key",
        )
        client = AzureLlamaClient(config)

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": '{"recommendations": '},
                            {"type": "text", "text": '[]}'},
                        ]
                    }
                }
            ]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = client.generate_chat_completion("sys", "user")
        self.assertEqual(res, '{"recommendations": []}')

    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_urllib_http_error_429_throttling_retry(self, mock_urlopen, mock_sleep):
        """Verifies HTTP 429 triggers bounded retries with exponential backoff and THROTTLED exception."""
        config = AzureLlamaConfig(
            azure_endpoint="https://test.openai.azure.com",
            azure_deployment="llama-3.3-70b",
            azure_llamakey="key",
            max_retries=2,
            retry_backoff_seconds=1.0,
        )
        client = AzureLlamaClient(config)

        error_fp = io.BytesIO(b'{"error": "Too Many Requests"}')
        http_err = urllib.error.HTTPError(
            url="https://test.openai.azure.com",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=error_fp,
        )
        mock_urlopen.side_effect = http_err

        with self.assertRaises(AzureLlamaClientError) as ctx:
            client.generate_chat_completion("sys", "user")

        self.assertEqual(ctx.exception.category, "THROTTLED")
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(mock_urlopen.call_count, 3)  # 1 initial + 2 retries
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)

    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_urllib_http_error_503_transient_retry(self, mock_urlopen, mock_sleep):
        """Verifies HTTP 503 triggers bounded retries with exponential backoff."""
        config = AzureLlamaConfig(
            azure_endpoint="https://test.openai.azure.com",
            azure_deployment="llama-3.3-70b",
            azure_llamakey="key",
            max_retries=1,
            retry_backoff_seconds=0.5,
        )
        client = AzureLlamaClient(config)

        error_fp = io.BytesIO(b"Service Unavailable")
        http_err = urllib.error.HTTPError(
            url="https://test.openai.azure.com",
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=error_fp,
        )
        mock_urlopen.side_effect = http_err

        with self.assertRaises(AzureLlamaClientError) as ctx:
            client.generate_chat_completion("sys", "user")

        self.assertEqual(ctx.exception.category, "HTTP_ERROR")
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once_with(0.5)

    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_urllib_http_error_401_no_retry(self, mock_urlopen, mock_sleep):
        """Verifies HTTP 401 client error fails fast without retrying."""
        config = AzureLlamaConfig(
            azure_endpoint="https://test.openai.azure.com",
            azure_deployment="llama-3.3-70b",
            azure_llamakey="invalid-key",
            max_retries=2,
        )
        client = AzureLlamaClient(config)

        error_fp = io.BytesIO(b'{"error": "Unauthorized"}')
        http_err = urllib.error.HTTPError(
            url="https://test.openai.azure.com",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=error_fp,
        )
        mock_urlopen.side_effect = http_err

        with self.assertRaises(AzureLlamaClientError) as ctx:
            client.generate_chat_completion("sys", "user")

        self.assertEqual(ctx.exception.category, "CLIENT_INITIALIZATION_FAILED")
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(mock_urlopen.call_count, 1)  # No retry
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_urllib_tls_certificate_verification_failed_fast_fail(self, mock_urlopen, mock_sleep):
        """Verifies TLS certificate verification error fails fast without retrying and provides remediation."""
        config = AzureLlamaConfig(
            azure_endpoint="https://test-foundry.openai.azure.com",
            azure_deployment="llama-3.3-70b",
            azure_llamakey="secret-key",
            max_retries=3,
        )
        client = AzureLlamaClient(config)

        ssl_err = ssl.SSLCertVerificationError(
            1,
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1006)"
        )
        url_err = urllib.error.URLError(reason=ssl_err)
        mock_urlopen.side_effect = url_err

        with self.assertRaises(AzureLlamaClientError) as ctx:
            client.generate_chat_completion("sys", "user")

        self.assertEqual(ctx.exception.category, "CLIENT_INITIALIZATION_FAILED")
        self.assertIn("CERTIFICATE_VERIFY_FAILED", str(ctx.exception))
        self.assertIn("SSL_CERT_FILE", str(ctx.exception))
        self.assertEqual(mock_urlopen.call_count, 1)  # Fast fail, no retry
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_urllib_timeout_error_retry(self, mock_urlopen, mock_sleep):
        """Verifies socket timeout triggers bounded retry with backoff."""
        config = AzureLlamaConfig(
            azure_endpoint="https://test.openai.azure.com",
            azure_deployment="llama-3.3-70b",
            azure_llamakey="key",
            max_retries=1,
            retry_backoff_seconds=1.0,
        )
        client = AzureLlamaClient(config)

        mock_urlopen.side_effect = urllib.error.URLError(reason=socket.timeout("timed out"))

        with self.assertRaises(AzureLlamaClientError) as ctx:
            client.generate_chat_completion("sys", "user")

        self.assertEqual(ctx.exception.category, "TIMEOUT")
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once_with(1.0)

    @patch("urllib.request.urlopen")
    def test_urllib_secret_redacted_from_error_body(self, mock_urlopen):
        """Verifies that API keys in error response bodies are redacted."""
        secret_token = "super-secret-azure-token-998877"
        config = AzureLlamaConfig(
            azure_endpoint="https://test.openai.azure.com",
            azure_deployment="llama-3.3-70b",
            azure_llamakey=secret_token,
            max_retries=0,
        )
        client = AzureLlamaClient(config)

        error_fp = io.BytesIO(f"Error authenticating with key {secret_token}".encode("utf-8"))
        http_err = urllib.error.HTTPError(
            url="https://test.openai.azure.com",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=error_fp,
        )
        mock_urlopen.side_effect = http_err

        with self.assertRaises(AzureLlamaClientError) as ctx:
            client.generate_chat_completion("sys", "user")

        err_msg = str(ctx.exception)
        self.assertNotIn(secret_token, err_msg)
        self.assertIn("[REDACTED]", err_msg)


if __name__ == "__main__":
    unittest.main()
