"""
KPI Intelligence — Azure AI Foundry Llama Client Adapter (urllib Implementation).

Connects to the Azure AI Foundry hosted Llama deployment using Python standard library urllib,
following the Alteryx reference transport architecture.

Configured via the 5 environment variables:
- AZURE_DEPLOYMENT
- AZURE_ENDPOINT
- AZURE_LLAMAKEY
- AZURE_DEPLOYMENT_NAME
- AZURE_OPENAI_API_VERSION

Features:
- Standard-library HTTP transport using urllib.request and urllib.error (zero external HTTP dependencies).
- Strict TLS certificate verification using system trust store and standard SSL_CERT_FILE configuration.
- Supports both Azure OpenAI Chat Completions and Azure AI Model Inference protocols.
- Bounded retries and exponential backoff for transient HTTP errors (429, 500, 502, 503, 504) and timeouts.
- Fast-fail without retries for deterministic TLS certificate-verification and authentication errors.
- Secret-safe redaction in all exceptions, diagnostics, and log entries.
"""

import os
import ssl
import time
import json
import socket
import logging
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse, urlencode, parse_qs
import urllib.request
import urllib.error

from backend.matching.config import AzureLlamaConfig

logger = logging.getLogger("kpi_intel.matching.azure_llama")


class AzureLlamaClientError(Exception):
    """Base exception for Azure Llama client errors with an explicit category."""

    def __init__(
        self,
        message: str,
        category: str = "HTTP_ERROR",
        status_code: Optional[int] = None,
    ):
        super().__init__(message)
        self.message = message
        self.category = category  # TIMEOUT, THROTTLED, HTTP_ERROR, INVALID_RESPONSE, CLIENT_INITIALIZATION_FAILED, MISSING_CONFIGURATION
        self.status_code = status_code


class AzureLlamaClient:
    """Standard-library urllib client adapter for Azure AI Foundry Llama deployments."""

    def __init__(self, config: Optional[AzureLlamaConfig] = None):
        self.config = config or AzureLlamaConfig.from_env()
        self.total_retry_wait_seconds: float = 0.0

    def classify_endpoint(self) -> str:
        """Sanitized endpoint classification for diagnostics and route selection."""
        endpoint = (self.config.azure_endpoint or "").strip().lower()
        if not endpoint:
            return "Unconfigured"
        parsed = urlparse(endpoint)
        netloc = parsed.netloc.lower()
        if "openai.azure.com" in netloc:
            return "Azure OpenAI"
        if "services.ai.azure.com" in netloc or "ai.azure.com" in netloc:
            return "Azure AI Foundry / Model Inference"
        if "cognitiveservices.azure.com" in netloc:
            return "Azure Cognitive Services"
        return "OpenAI-compatible"

    def build_request_url(self) -> str:
        """
        Constructs the target Azure AI Foundry or Azure OpenAI chat completions URL.
        
        Properly resolves and normalizes:
        1. Full chat completions endpoints (e.g. https://.../chat/completions)
        2. Azure AI Foundry endpoints (*.services.ai.azure.com, *.ai.azure.com, *.models.ai.azure.com, *.inference.ai.azure.com)
           - Resource root: https://res.services.ai.azure.com -> https://res.services.ai.azure.com/models/chat/completions
           - Explicit /models: https://res.services.ai.azure.com/models -> https://res.services.ai.azure.com/models/chat/completions (no duplicate /models)
           - Explicit /v1: https://res.services.ai.azure.com/v1 -> https://res.services.ai.azure.com/v1/chat/completions
           - Explicit /deployments/: preserves path and appends /chat/completions
        3. Azure OpenAI endpoints (*.openai.azure.com)
           - Resource root: https://res.openai.azure.com -> https://res.openai.azure.com/openai/deployments/{deployment}/chat/completions?api-version=...
           - Explicit deployment: https://res.openai.azure.com/openai/deployments/{deployment} -> https://res.openai.azure.com/openai/deployments/{deployment}/chat/completions?api-version=...
        4. Azure Cognitive Services (*.cognitiveservices.azure.com)
        5. OpenAI-compatible / Custom endpoints (e.g. http://localhost:8000/v1 -> http://localhost:8000/v1/chat/completions)
        """
        endpoint = (self.config.azure_endpoint or "").strip()
        if not endpoint:
            raise AzureLlamaClientError(
                "AZURE_ENDPOINT is empty or not configured.",
                category="MISSING_CONFIGURATION",
            )

        parsed = urlparse(endpoint)
        if not parsed.scheme or not parsed.netloc:
            raise AzureLlamaClientError(
                f"AZURE_ENDPOINT '{endpoint}' is not a valid URL.",
                category="MISSING_CONFIGURATION",
            )

        base = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        path = parsed.path.rstrip("/")
        netloc_lower = parsed.netloc.lower()
        deployment_name = self.config.effective_deployment_name

        # Parse existing query parameters from the endpoint
        query_params = parse_qs(parsed.query)

        # 1. Direct full completion path provided
        if path.endswith("/chat/completions"):
            resolved_path = path
            if self.config.azure_openai_api_version and "api-version" not in query_params:
                query_params["api-version"] = [self.config.azure_openai_api_version]
            qs = urlencode(query_params, doseq=True)
            return f"{base}{resolved_path}{'?' + qs if qs else ''}"

        # 2. Azure OpenAI endpoints (*.openai.azure.com)
        if "openai.azure.com" in netloc_lower:
            api_ver = self.config.azure_openai_api_version or "2024-06-01"
            if "api-version" not in query_params:
                query_params["api-version"] = [api_ver]
            qs = urlencode(query_params, doseq=True)
            qs_str = f"?{qs}" if qs else ""

            if "/deployments/" in path:
                return f"{base}{path}/chat/completions{qs_str}"
            if path.endswith("/openai/v1") or path.endswith("/v1"):
                return f"{base}{path}/chat/completions{qs_str}"
            return f"{base}/openai/deployments/{deployment_name}/chat/completions{qs_str}"

        # 3. Azure AI Foundry / MaaS endpoints (*.services.ai.azure.com, *.ai.azure.com, *.models.ai.azure.com, *.inference.ai.azure.com)
        if "services.ai.azure.com" in netloc_lower or "ai.azure.com" in netloc_lower:
            # Azure AI Model Inference API does not use Azure OpenAI date-based versions (e.g. 2024-06-01).
            # Only include api-version if present in endpoint URL or explicitly specified with a foundry preview version.
            if self.config.azure_openai_api_version and "api-version" not in query_params:
                if self.config.azure_openai_api_version != "2024-06-01":
                    query_params["api-version"] = [self.config.azure_openai_api_version]
            qs = urlencode(query_params, doseq=True)
            qs_str = f"?{qs}" if qs else ""

            if "/deployments/" in path:
                return f"{base}{path}/chat/completions{qs_str}"
            if path in ("", "/"):
                return f"{base}/models/chat/completions{qs_str}"
            if path.endswith("/models"):
                return f"{base}{path}/chat/completions{qs_str}"
            if path.endswith("/v1"):
                return f"{base}{path}/chat/completions{qs_str}"
            return f"{base}{path}/models/chat/completions{qs_str}"

        # 4. Azure Cognitive Services (*.cognitiveservices.azure.com)
        if "cognitiveservices.azure.com" in netloc_lower:
            api_ver = self.config.azure_openai_api_version or "2024-06-01"
            if "api-version" not in query_params:
                query_params["api-version"] = [api_ver]
            qs = urlencode(query_params, doseq=True)
            qs_str = f"?{qs}" if qs else ""

            if "/deployments/" in path:
                return f"{base}{path}/chat/completions{qs_str}"
            return f"{base}/openai/deployments/{deployment_name}/chat/completions{qs_str}"

        # 5. Generic / OpenAI-compatible paths
        if self.config.azure_openai_api_version and "api-version" not in query_params:
            query_params["api-version"] = [self.config.azure_openai_api_version]
        qs = urlencode(query_params, doseq=True)
        qs_str = f"?{qs}" if qs else ""

        if path.endswith("/v1") or path.endswith("/models"):
            return f"{base}{path}/chat/completions{qs_str}"
        if path in ("", "/"):
            return f"{base}/v1/chat/completions{qs_str}"
        return f"{base}{path}/chat/completions{qs_str}"

    def build_headers(self) -> Dict[str, str]:
        """Builds secret-authenticated request headers for the Azure endpoint."""
        if not self.config.azure_llamakey:
            raise AzureLlamaClientError(
                "AZURE_LLAMAKEY is missing or not configured.",
                category="MISSING_CONFIGURATION",
            )

        # Provide Content-Type, api-key, and Bearer authorization headers
        return {
            "Content-Type": "application/json",
            "api-key": self.config.azure_llamakey,
            "Authorization": f"Bearer {self.config.azure_llamakey}",
            "User-Agent": "KPI-Intelligence-AzureLlama/1.0",
        }

    def generate_chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        """
        Sends a chat completion request to the Azure AI Foundry Llama deployment using urllib.
        Returns the raw model text response.

        Adopts the Alteryx transport pattern with:
        - urllib.request.Request with JSON bytes
        - urllib.request.urlopen with strict TLS validation
        - HTTPError and URLError handling with secret-safe redaction
        - Bounded exponential backoff for transient failures (429, 500, 502, 503, 504, timeouts)
        - Fast failure without retries for certificate verification failures
        """
        if not self.config.is_configured:
            raise AzureLlamaClientError(
                "Azure AI Foundry Llama is not configured. Missing required environment variables.",
                category="MISSING_CONFIGURATION",
            )

        url = self.build_request_url()
        headers = self.build_headers()
        parsed_url = urlparse(url)
        endpoint_type = self.classify_endpoint()
        req_timeout = float(self.config.timeout_seconds)

        # Safe diagnostic logging (no secrets, keys, or authorization headers logged)
        logger.info(
            "Azure LLM request dispatch: method=POST endpoint_type='%s' host='%s' path='%s' "
            "deployment_configured=%s timeout=%.1fs",
            endpoint_type,
            parsed_url.netloc,
            parsed_url.path,
            bool(self.config.effective_deployment_name),
            req_timeout,
        )

        payload: Dict[str, Any] = {
            "model": self.config.effective_model_identifier,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        # Bounded retries for transient failures
        attempts = 0
        timeout_attempts = 0
        max_attempts = max(1, self.config.max_retries + 1)
        max_timeout_attempts = max(1, self.config.effective_max_timeout_retries + 1)

        while attempts < max_attempts:
            attempts += 1
            try:
                req_bytes = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url=url,
                    data=req_bytes,
                    headers=headers,
                    method="POST",
                )

                # Standard urllib HTTPS execution with default SSL context (validates certificate)
                with urllib.request.urlopen(req, timeout=req_timeout) as response:
                    status_code = getattr(response, "status", None) or response.getcode()
                    if status_code != 200:
                        raise AzureLlamaClientError(
                            f"Azure Llama API returned non-200 HTTP status {status_code}.",
                            category="HTTP_ERROR",
                            status_code=status_code,
                        )

                    resp_bytes = response.read()
                    resp_text = resp_bytes.decode("utf-8", errors="replace")
                    data = json.loads(resp_text)

                # Parse choices from chat completion response
                choices = data.get("choices", [])
                if not choices:
                    raise AzureLlamaClientError(
                        "Azure Llama returned response without choices.",
                        category="INVALID_RESPONSE",
                    )

                first_choice = choices[0] if isinstance(choices, list) and choices else {}
                message = first_choice.get("message", {}) if isinstance(first_choice, dict) else {}
                content = message.get("content") if isinstance(message, dict) else None
                if content is None and isinstance(first_choice, dict):
                    content = first_choice.get("text")

                # Handle multi-part content list (e.g. [{"type": "text", "text": "..."}])
                if isinstance(content, list):
                    parts = []
                    for p in content:
                        if isinstance(p, dict):
                            parts.append(p.get("text") or p.get("content") or "")
                        elif isinstance(p, str):
                            parts.append(p)
                    content_str = "".join(parts).strip()
                elif isinstance(content, dict):
                    content_str = json.dumps(content)
                elif content is not None:
                    content_str = str(content).strip()
                else:
                    content_str = ""

                if not content_str:
                    raise AzureLlamaClientError(
                        "Azure Llama returned empty message content.",
                        category="INVALID_RESPONSE",
                    )

                return content_str

            except urllib.error.HTTPError as he:
                status_code = getattr(he, "code", 0)
                error_body = ""
                try:
                    error_body = he.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    pass

                # Sanitize error body to prevent leaking secrets in logs/exceptions
                sanitized_body = error_body
                if self.config.azure_llamakey:
                    sanitized_body = sanitized_body.replace(self.config.azure_llamakey, "[REDACTED]")

                is_transient = status_code in (429, 500, 502, 503, 504)
                if is_transient and attempts < max_attempts:
                    delay = min(10.0, self.config.retry_backoff_seconds * (2 ** (attempts - 1)))
                    self.total_retry_wait_seconds += delay
                    logger.warning(
                        "Azure Llama HTTP %d transient error (attempt %d/%d). Backing off %.1fs.",
                        status_code,
                        attempts,
                        max_attempts,
                        delay,
                    )
                    time.sleep(delay)
                    continue

                if status_code == 429:
                    raise AzureLlamaClientError(
                        f"Azure AI Foundry Llama 429 rate limit exceeded after {attempts} attempts.",
                        category="THROTTLED",
                        status_code=429,
                    ) from he

                if status_code in (401, 403):
                    raise AzureLlamaClientError(
                        f"Azure Llama API authentication/authorization failed (HTTP {status_code}): {sanitized_body[:200]}",
                        category="CLIENT_INITIALIZATION_FAILED",
                        status_code=status_code,
                    ) from he

                if status_code in (500, 502, 503, 504):
                    raise AzureLlamaClientError(
                        f"Azure AI Foundry Llama service unavailable (HTTP {status_code}): {sanitized_body[:200]}",
                        category="HTTP_ERROR",
                        status_code=status_code,
                    ) from he

                if status_code == 404:
                    logger.error(
                        "Azure LLM request returned HTTP 404 (Resource Not Found). "
                        "Endpoint type: '%s', Host: '%s', Path: '%s', Deployment: '%s', Query: '%s'. "
                        "Server response: %s",
                        endpoint_type,
                        parsed_url.netloc,
                        parsed_url.path,
                        self.config.effective_deployment_name or "(none)",
                        parsed_url.query or "(none)",
                        sanitized_body[:200] if sanitized_body else "(empty)",
                    )
                    raise AzureLlamaClientError(
                        f"Azure LLM resource not found (HTTP 404) at '{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}'. "
                        f"Endpoint type: '{endpoint_type}'. "
                        f"Deployment: '{self.config.effective_deployment_name}'. "
                        "Actionable guidance: Verify your AZURE_ENDPOINT, AZURE_DEPLOYMENT, and AZURE_DEPLOYMENT_NAME. "
                        "1. For Azure AI Foundry (services.ai.azure.com / ai.azure.com), ensure your model is deployed and target route is '/models/chat/completions'. "
                        "2. For Azure OpenAI (openai.azure.com / cognitiveservices.azure.com), verify AZURE_DEPLOYMENT_NAME matches your Azure deployment name and AZURE_OPENAI_API_VERSION is valid for your resource. "
                        f"Server response: {sanitized_body[:200] if sanitized_body else '(empty)'}",
                        category="HTTP_ERROR",
                        status_code=404,
                    ) from he

                # Other HTTP errors (400, etc.)
                raise AzureLlamaClientError(
                    f"Azure Llama API request failed with HTTP {status_code}: {sanitized_body[:200]}",
                    category="HTTP_ERROR",
                    status_code=status_code,
                ) from he

            except urllib.error.URLError as ue:
                reason = getattr(ue, "reason", None)
                reason_str = str(reason or "")

                # 1. TLS Certificate Verification Failure -> Fast fail without retry
                is_ssl_cert_error = (
                    isinstance(reason, ssl.SSLCertVerificationError)
                    or "certificate verify failed" in reason_str.lower()
                    or "unable to get local issuer certificate" in reason_str.lower()
                    or "self signed certificate" in reason_str.lower()
                )
                if is_ssl_cert_error:
                    safe_err = reason_str
                    if self.config.azure_llamakey:
                        safe_err = safe_err.replace(self.config.azure_llamakey, "[REDACTED]")
                    logger.error("Azure AI Foundry TLS certificate verification failed: %s", safe_err)
                    raise AzureLlamaClientError(
                        f"Azure AI Foundry TLS certificate verification failed: {safe_err}. "
                        "Ensure your enterprise root certificate is installed in the Windows system trust store, "
                        "or configure the SSL_CERT_FILE environment variable with your CA bundle.",
                        category="CLIENT_INITIALIZATION_FAILED",
                    ) from ue

                # 2. Timeout error -> Bounded retry with backoff (controlled by effective_max_timeout_retries)
                is_timeout = (
                    isinstance(reason, (TimeoutError, socket.timeout))
                    or "timed out" in reason_str.lower()
                )
                if is_timeout:
                    timeout_attempts += 1
                    if timeout_attempts < max_timeout_attempts and attempts < max_attempts:
                        delay = min(10.0, self.config.retry_backoff_seconds * (2 ** (attempts - 1)))
                        self.total_retry_wait_seconds += delay
                        logger.warning(
                            "Azure Llama request timed out (attempt %d/%d). Backing off %.1fs.",
                            attempts,
                            max_attempts,
                            delay,
                        )
                        time.sleep(delay)
                        continue
                    raise AzureLlamaClientError(
                        f"Azure AI Foundry request timed out after {req_timeout}s.",
                        category="TIMEOUT",
                    ) from ue

                # 3. General network connection failure -> Bounded retry with backoff
                if attempts < max_attempts:
                    delay = min(10.0, self.config.retry_backoff_seconds * (2 ** (attempts - 1)))
                    self.total_retry_wait_seconds += delay
                    logger.warning(
                        "Azure Llama connection error (attempt %d/%d): %s. Backing off %.1fs.",
                        attempts,
                        max_attempts,
                        reason_str,
                        delay,
                    )
                    time.sleep(delay)
                    continue

                safe_err = reason_str
                if self.config.azure_llamakey:
                    safe_err = safe_err.replace(self.config.azure_llamakey, "[REDACTED]")
                raise AzureLlamaClientError(
                    f"Azure AI Foundry connection error: {safe_err}",
                    category="HTTP_ERROR",
                ) from ue

            except (TimeoutError, socket.timeout) as te:
                timeout_attempts += 1
                if timeout_attempts < max_timeout_attempts and attempts < max_attempts:
                    delay = min(10.0, self.config.retry_backoff_seconds * (2 ** (attempts - 1)))
                    self.total_retry_wait_seconds += delay
                    logger.warning(
                        "Azure Llama timeout encountered (attempt %d/%d). Backing off %.1fs.",
                        attempts,
                        max_attempts,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                raise AzureLlamaClientError(
                    f"Azure AI Foundry request timed out after {req_timeout}s.",
                    category="TIMEOUT",
                ) from te

            except json.JSONDecodeError as jde:
                raise AzureLlamaClientError(
                    f"Azure Llama returned malformed JSON response: {jde}",
                    category="INVALID_RESPONSE",
                ) from jde

        raise AzureLlamaClientError(
            "Azure Llama execution failed after maximum retries.",
            category="HTTP_ERROR",
        )
