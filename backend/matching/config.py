"""
KPI Intelligence — Azure AI Foundry Llama Configuration.

Manages environment settings for the Azure AI Foundry Llama deployment:
- AZURE_DEPLOYMENT
- AZURE_ENDPOINT
- AZURE_LLAMAKEY
- AZURE_DEPLOYMENT_NAME
- AZURE_OPENAI_API_VERSION

Guarantees:
- Never hardcodes credentials or exposes secret keys in logs/reports.
- Safe string representation (__repr__ redacts AZURE_LLAMAKEY).
- Actionable, secret-safe validation errors.
- Non-destructive .env loading without external dependencies.
"""

import os
import re
from typing import Dict, Any, Optional
from dataclasses import dataclass


def load_local_dotenv(dotenv_path: Optional[str] = None) -> None:
    """
    Lightweight, zero-dependency .env loader.
    Loads key=value pairs into os.environ if not already set.
    Does NOT overwrite existing environment variables.
    """
    if dotenv_path is None:
        dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

    if not os.path.exists(dotenv_path):
        return

    try:
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    # Strip wrapping quotes if present
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    if key and key not in os.environ:
                        os.environ[key] = val
    except Exception:
        # Silently pass if file cannot be read
        pass


@dataclass
class AzureLlamaConfig:
    """
    Configuration for Azure AI Foundry Llama deployment.

    Semantics of the two deployment variables:
    - AZURE_DEPLOYMENT_NAME: The Azure deployment resource name (used in URL route paths,
      e.g. /openai/deployments/{AZURE_DEPLOYMENT_NAME}/chat/completions).
    - AZURE_DEPLOYMENT: The model identifier / deployment slug (passed in the JSON request body
      as the 'model' parameter, e.g. 'llama-3.3-70b-instruct').
    If only one is set, the client uses it as the default for both.
    """
    azure_deployment: Optional[str] = None
    azure_endpoint: Optional[str] = None
    azure_llamakey: Optional[str] = None
    azure_deployment_name: Optional[str] = None
    azure_openai_api_version: Optional[str] = None

    # Operational settings
    timeout_seconds: float = 30.0
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0

    @classmethod
    def from_env(cls) -> "AzureLlamaConfig":
        """Loads configuration from process environment after loading local .env if present."""
        load_local_dotenv()

        deployment = cls._clean_env("AZURE_DEPLOYMENT")
        endpoint = cls._clean_env("AZURE_ENDPOINT")
        llamakey = cls._clean_env("AZURE_LLAMAKEY")
        deployment_name = cls._clean_env("AZURE_DEPLOYMENT_NAME")
        api_version = cls._clean_env("AZURE_OPENAI_API_VERSION")

        timeout = float(os.getenv("KPI_LLM_TIMEOUT_SECONDS", "30.0"))
        max_retries = int(os.getenv("KPI_LLM_MAX_RETRIES", "2"))

        return cls(
            azure_deployment=deployment,
            azure_endpoint=endpoint,
            azure_llamakey=llamakey,
            azure_deployment_name=deployment_name,
            azure_openai_api_version=api_version,
            timeout_seconds=timeout,
            max_retries=max_retries,
        )

    @staticmethod
    def _clean_env(name: str) -> Optional[str]:
        val = os.getenv(name, "").strip()
        # Treat empty string or placeholder values as None
        if not val or val.startswith("<") or val.lower() in ("placeholder", "none", "null"):
            return None
        return val

    @property
    def is_configured(self) -> bool:
        """Returns True if minimum required settings for Azure AI Foundry are set."""
        return bool(
            self.azure_endpoint
            and self.azure_llamakey
            and (self.azure_deployment or self.azure_deployment_name)
        )

    @property
    def effective_deployment_name(self) -> str:
        """Returns the deployment name for route paths or body model field."""
        return self.azure_deployment_name or self.azure_deployment or "llama-deployment"

    @property
    def effective_model_identifier(self) -> str:
        """Returns the model identifier for the request payload."""
        return self.azure_deployment or self.azure_deployment_name or "llama"

    def validate(self) -> None:
        """
        Validates configuration and raises ValueError with secret-safe descriptions.
        """
        missing = []
        if not self.azure_endpoint:
            missing.append("AZURE_ENDPOINT")
        if not self.azure_llamakey:
            missing.append("AZURE_LLAMAKEY")
        if not self.azure_deployment and not self.azure_deployment_name:
            missing.append("AZURE_DEPLOYMENT or AZURE_DEPLOYMENT_NAME")

        if missing:
            raise ValueError(
                f"Missing required Azure AI Foundry Llama environment configuration: {', '.join(missing)}. "
                "Ensure these are set in the environment or a local .env file."
            )

        # Basic endpoint scheme validation
        if not (self.azure_endpoint.startswith("https://") or self.azure_endpoint.startswith("http://")):
            raise ValueError(
                f"Invalid AZURE_ENDPOINT scheme. Expected URL starting with 'https://' (or 'http://' for local testing)."
            )

    def to_safe_dict(self) -> Dict[str, Any]:
        """Returns non-sensitive metadata safe for logs, diagnostics, and frontend API responses."""
        safe_endpoint = None
        if self.azure_endpoint:
            # Mask hostname keeping only protocol and domain suffix
            safe_endpoint = re.sub(r"://([^/]+)", "://[REDACTED_HOST]", self.azure_endpoint)

        return {
            "llm_configured": self.is_configured,
            "llm_provider": "Azure AI Foundry (Llama)",
            "llm_deployment": self.azure_deployment,
            "llm_deployment_name": self.azure_deployment_name,
            "effective_deployment": self.effective_deployment_name,
            "api_version": self.azure_openai_api_version,
            "has_endpoint": bool(self.azure_endpoint),
            "has_key": bool(self.azure_llamakey),
            "safe_endpoint": safe_endpoint,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
        }

    def __repr__(self) -> str:
        return (
            f"AzureLlamaConfig(configured={self.is_configured}, "
            f"deployment={self.azure_deployment!r}, "
            f"deployment_name={self.azure_deployment_name!r}, "
            f"api_version={self.azure_openai_api_version!r}, "
            f"endpoint={self.to_safe_dict().get('safe_endpoint')!r}, "
            f"key=[REDACTED])"
        )
