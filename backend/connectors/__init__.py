"""
KPI Intelligence — Connectors Package.
"""

from backend.connectors.base import (
    BaseConnector,
    PlatformType,
    DiagnosticSeverity,
    Diagnostic,
    ArtifactManifestItem,
    PlatformCapability,
    CapabilityStatus,
    ExtractionResult,
)
from backend.connectors.registry import ConnectorRegistry

__all__ = [
    "BaseConnector",
    "PlatformType",
    "DiagnosticSeverity",
    "Diagnostic",
    "ArtifactManifestItem",
    "PlatformCapability",
    "CapabilityStatus",
    "ExtractionResult",
    "ConnectorRegistry",
]
