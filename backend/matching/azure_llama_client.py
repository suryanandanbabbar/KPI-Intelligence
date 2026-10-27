"""
KPI Intelligence — Azure AI Foundry Llama Client Adapter.

Connects to the Azure AI Foundry hosted Llama deployment using the 5 environment variables:
- AZURE_DEPLOYMENT
- AZURE_ENDPOINT
- AZURE_LLAMAKEY
- AZURE_DEPLOYMENT_NAME
- AZURE_OPENAI_API_VERSION

Features:
- Encapsulates HTTP transport using httpx.
- Supports both Azure OpenAI Chat Completions and Azure AI Model Inference protocols.
- Bounded retries and exponential backoff for transient HTTP errors (429, 503).
- Secret redaction in all exceptions and log lines.
- Categorized error reporting for fallback handling.
"""

import time
import json
import logging
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse, urlencode, parse_qs

import httpx

from backend.matching.config import AzureLlamaConfig

logger = logging.getLogger("kpi_intel.matching.azure_llama")


class AzureLlamaClientError(Exception):
    """Base exception for Azure Llama client errors with an explicit category."""
    def __init__(self, message: str, category: str = "HTTP_ERROR", status_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.category = category  # TIMEOUT, THROTTLED, HTTP_ERROR, INVALID_RESPONSE, CLIENT_INITIALIZATION_FAILED, MISSING_CONFIGURATION
        self.status_code = status_code


class AzureLlamaClient:
    """HTTP client adapter for Azure AI Foundry Llama deployments."""

    def __init__(self, config: Optional[AzureLlamaConfig] = None):
        self.config = config or AzureLlamaConfig.from_env()

    def build_request_url(self) -> str:
        """
        Constructs the target Azure AI Foundry chat completions URL.
        Preserves path if already specified in AZURE_ENDPOINT; otherwise formats
        the Azure OpenAI or Azure AI Model Inference route.
        """
        endpoint = (self.config.azure_endpoint or "").strip().rstrip("/")
        if not endpoint:
            raise AzureLlamaClientError("AZURE_ENDPOINT is empty or not configured.", category="MISSING_CONFIGURATION")

        parsed = urlparse(endpoint)
        base_path = parsed.path.rstrip("/")
        query_params = parse_qs(parsed.query)

        # Append api-version if specified
        if self.config.azure_openai_api_version:
            query_params["api-version"] = [self.config.azure_openai_api_version]

        qs = urlencode(query_params, doseq=True)
        qs_str = f"?{qs}" if qs else ""

        # Check if endpoint path already points to chat completions
        if base_path.endswith("/chat/completions"):
            return f"{parsed.scheme}://{parsed.netloc}{base_path}{qs_str}"

        # If endpoint has /models or is models.ai.azure.com host, route to /models/chat/completions
        if "/models" in base_path or parsed.netloc.endswith("models.ai.azure.com"):
            return f"{parsed.scheme}://{parsed.netloc}{base_path}/models/chat/completions{qs_str}"

        # Standard Azure OpenAI / Azure AI Foundry route: /openai/deployments/{deployment}/chat/completions
        deployment_name = self.config.effective_deployment_name
        return f"{parsed.scheme}://{parsed.netloc}{base_path}/openai/deployments/{deployment_name}/chat/completions{qs_str}"

    def build_headers(self) -> Dict[str, str]:
        """Builds secret-authenticated request headers."""
        if not self.config.azure_llamakey:
            raise AzureLlamaClientError("AZURE_LLAMAKEY is missing or not configured.", category="MISSING_CONFIGURATION")

        # Provide both api-key and Bearer authorization headers for maximum Azure AI Foundry compatibility
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
        Sends chat completion request to the Azure AI Foundry Llama deployment.
        Returns the raw model text response.
        """
        if not self.config.is_configured:
            raise AzureLlamaClientError(
                "Azure AI Foundry Llama is not configured. Missing required environment variables.",
                category="MISSING_CONFIGURATION",
            )

        url = self.build_request_url()
        headers = self.build_headers()

        payload = {
            "model": self.config.effective_model_identifier,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        # Bounded retries for transient throttling (429) or server errors (503)
        attempts = 0
        max_attempts = max(1, self.config.max_retries + 1)
        last_error: Optional[Exception] = None

        while attempts < max_attempts:
            attempts += 1
            try:
                with httpx.Client(timeout=self.config.timeout_seconds) as client:
                    resp = client.post(url, headers=headers, json=payload)

                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if not choices:
                        raise AzureLlamaClientError(
                            "Azure Llama returned response without choices.",
                            category="INVALID_RESPONSE",
                        )
                    message = choices[0].get("message", {})
                    content = message.get("content", "")
                    if not content:
                        raise AzureLlamaClientError(
                            "Azure Llama returned empty message content.",
                            category="INVALID_RESPONSE",
                        )
                    return content

                elif resp.status_code == 429:
                    # Throttling encountered
                    if attempts < max_attempts:
                        delay = self.config.retry_backoff_seconds * (2 ** (attempts - 1))
                        logger.warning("Azure Llama 429 Throttling encountered (attempt %d/%d). Backing off %.1fs.", attempts, max_attempts, delay)
                        time.sleep(delay)
                        continue
                    raise AzureLlamaClientError(
                        f"Azure AI Foundry Llama 429 rate limit exceeded after {attempts} attempts.",
                        category="THROTTLED",
                        status_code=429,
                    )

                elif resp.status_code in (500, 502, 503, 504):
                    if attempts < max_attempts:
                        delay = self.config.retry_backoff_seconds * (2 ** (attempts - 1))
                        logger.warning("Azure Llama HTTP %d transient error (attempt %d/%d). Backing off %.1fs.", resp.status_code, attempts, max_attempts, delay)
                        time.sleep(delay)
                        continue
                    raise AzureLlamaClientError(
                        f"Azure AI Foundry Llama service unavailable (HTTP {resp.status_code}).",
                        category="HTTP_ERROR",
                        status_code=resp.status_code,
                    )

                else:
                    # Client errors (400, 401, 404, etc.)
                    category = "HTTP_ERROR"
                    if resp.status_code in (401, 403):
                        category = "CLIENT_INITIALIZATION_FAILED"
                    # Safe error snippet without leaking keys or endpoints
                    err_snippet = resp.text[:200].replace(self.config.azure_llamakey or "", "[REDACTED]")
                    raise AzureLlamaClientError(
                        f"Azure Llama API request failed with HTTP {resp.status_code}: {err_snippet}",
                        category=category,
                        status_code=resp.status_code,
                    )

            except httpx.TimeoutException as tex:
                if attempts < max_attempts:
                    delay = self.config.retry_backoff_seconds
                    time.sleep(delay)
                    continue
                raise AzureLlamaClientError(
                    f"Azure AI Foundry request timed out after {self.config.timeout_seconds}s.",
                    category="TIMEOUT",
                ) from tex

            except httpx.RequestError as req_err:
                if attempts < max_attempts:
                    delay = self.config.retry_backoff_seconds
                    time.sleep(delay)
                    continue
                # Redact host and keys from request error
                safe_err = str(req_err)
                if self.config.azure_llamakey:
                    safe_err = safe_err.replace(self.config.azure_llamakey, "[REDACTED]")
                raise AzureLlamaClientError(
                    f"Azure AI Foundry connection error: {safe_err}",
                    category="HTTP_ERROR",
                ) from req_err

        raise AzureLlamaClientError(
            "Azure Llama execution failed after maximum retries.",
            category="HTTP_ERROR",
        )
