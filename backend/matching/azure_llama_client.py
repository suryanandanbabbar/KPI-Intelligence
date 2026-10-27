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

    def build_request_url(self) -> str:
        """
        Constructs the target Azure AI Foundry chat completions URL.
        Preserves path if already specified in AZURE_ENDPOINT; otherwise formats
        the Azure OpenAI or Azure AI Model Inference route.
        """
        endpoint = (self.config.azure_endpoint or "").strip().rstrip("/")
        if not endpoint:
            raise AzureLlamaClientError(
                "AZURE_ENDPOINT is empty or not configured.",
                category="MISSING_CONFIGURATION",
            )

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
        max_attempts = max(1, self.config.max_retries + 1)
        req_timeout = float(self.config.timeout_seconds)

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

                # Other HTTP errors (400, 404, etc.)
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

                # 2. Timeout error -> Bounded retry with backoff
                is_timeout = (
                    isinstance(reason, (TimeoutError, socket.timeout))
                    or "timed out" in reason_str.lower()
                )
                if is_timeout:
                    if attempts < max_attempts:
                        delay = min(10.0, self.config.retry_backoff_seconds * (2 ** (attempts - 1)))
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
                if attempts < max_attempts:
                    delay = min(10.0, self.config.retry_backoff_seconds * (2 ** (attempts - 1)))
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
