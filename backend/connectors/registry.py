"""
KPI Intelligence — Connector Registry.

Central registry for managing platform connector implementations and discovery.
Allows Power BI, Tableau, Excel, ThoughtSpot, and MicroStrategy connectors to be
registered and retrieved uniformly.
"""

from typing import Dict, Type, List, Optional
from backend.connectors.base import BaseConnector, PlatformType, PlatformCapability, CapabilityStatus, ExtractionResult, Diagnostic, DiagnosticSeverity, ArtifactManifestItem


class UnsupportedPlatformConnector(BaseConnector):
    """Stub connector representing registered but unimplemented platforms."""

    def __init__(self, platform_type: PlatformType):
        self._platform = platform_type

    @property
    def platform(self) -> PlatformType:
        return self._platform

    @property
    def parser_name(self) -> str:
        return f"{self._platform.value.lower()}_stub_parser"

    @property
    def parser_version(self) -> str:
        return "0.0.0"

    def discover(self, source_path: str) -> List[ArtifactManifestItem]:
        return []

    def extract(self, source_path: str) -> ExtractionResult:
        diag = Diagnostic(
            code="PLATFORM_CONNECTOR_NOT_IMPLEMENTED",
            message=f"Connector for platform '{self._platform.value}' is planned but not implemented in this phase.",
            severity=DiagnosticSeverity.FATAL,
            is_recoverable=False,
        )
        return ExtractionResult(
            platform=self._platform,
            source_path=source_path,
            asset_name="",
            diagnostics=[diag],
            run_stats={"status": "FAILED", "reason": "UNIMPLEMENTED_PLATFORM"}
        )

    def get_capabilities(self) -> List[PlatformCapability]:
        return [
            PlatformCapability(
                platform=self._platform,
                artifact_type="ANY",
                metadata_type="ALL",
                capability_status=CapabilityStatus.UNSUPPORTED,
                notes=f"Connector for {self._platform.value} is planned in a future development phase."
            )
        ]


class ConnectorRegistry:
    """Registry pattern for BI metadata extraction connectors."""

    _registry: Dict[PlatformType, BaseConnector] = {}

    @classmethod
    def register(cls, connector: BaseConnector) -> None:
        """Register a connector instance for a platform."""
        cls._registry[connector.platform] = connector

    @classmethod
    def get(cls, platform: PlatformType) -> Optional[BaseConnector]:
        """Retrieve the connector for a specific platform."""
        return cls._registry.get(platform)

    @classmethod
    def list_supported_platforms(cls) -> List[PlatformType]:
        """List platforms with active functional connectors."""
        return [
            p for p, c in cls._registry.items()
            if not isinstance(c, UnsupportedPlatformConnector)
        ]

    @classmethod
    def list_all_platforms(cls) -> List[PlatformType]:
        """List all registered platforms."""
        return list(cls._registry.keys())

    @classmethod
    def is_supported(cls, platform: PlatformType) -> bool:
        """Check if a platform has an active functional connector."""
        c = cls._registry.get(platform)
        return c is not None and not isinstance(c, UnsupportedPlatformConnector)


# Pre-register stub connectors for future platforms
for p in [PlatformType.TABLEAU, PlatformType.EXCEL, PlatformType.THOUGHTSPOT, PlatformType.MICROSTRATEGY]:
    ConnectorRegistry.register(UnsupportedPlatformConnector(p))
