"""
KPI Intelligence — Connector Base Framework.

Defines the contract, common types, and abstract base classes for platform metadata connectors.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod


class PlatformType(str, Enum):
    POWER_BI = "POWER_BI"
    TABLEAU = "TABLEAU"
    EXCEL = "EXCEL"
    THOUGHTSPOT = "THOUGHTSPOT"
    MICROSTRATEGY = "MICROSTRATEGY"


class DiagnosticSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"


class CapabilityStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    RUNTIME_DEPENDENT = "RUNTIME_DEPENDENT"


@dataclass
class Diagnostic:
    code: str
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.INFO
    source_artifact: Optional[str] = None
    locator: Dict[str, Any] = field(default_factory=dict)
    is_recoverable: bool = True


@dataclass
class ArtifactManifestItem:
    relative_path: str
    artifact_type: str
    size_bytes: int
    content_hash: str
    is_supported: bool = True
    mime_type: Optional[str] = None
    extraction_notes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlatformCapability:
    platform: PlatformType
    artifact_type: str
    metadata_type: str
    capability_status: CapabilityStatus
    minimum_source_version: Optional[str] = None
    maximum_source_version: Optional[str] = None
    notes: Optional[str] = None
    capability_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    platform: PlatformType
    source_path: str
    asset_name: str
    artifacts: List[ArtifactManifestItem] = field(default_factory=list)
    raw_model: Optional[Dict[str, Any]] = None
    raw_report: Optional[Dict[str, Any]] = None
    diagnostics: List[Diagnostic] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    run_stats: Dict[str, Any] = field(default_factory=dict)


class BaseConnector(ABC):
    """Abstract base class for all platform metadata extraction connectors."""

    @property
    @abstractmethod
    def platform(self) -> PlatformType:
        """The source BI platform supported by this connector."""
        pass

    @property
    @abstractmethod
    def parser_name(self) -> str:
        """Name of the parser component."""
        pass

    @property
    @abstractmethod
    def parser_version(self) -> str:
        """Semantic version of the parser implementation."""
        pass

    @abstractmethod
    def discover(self, source_path: str) -> List[ArtifactManifestItem]:
        """Discovers and catalogs all artifacts within the source project bundle."""
        pass

    @abstractmethod
    def extract(self, source_path: str) -> ExtractionResult:
        """Extracts and parses all metadata from the source project."""
        pass

    @abstractmethod
    def get_capabilities(self) -> List[PlatformCapability]:
        """Returns the declared platform extraction capabilities."""
        pass
