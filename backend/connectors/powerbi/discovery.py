"""
KPI Intelligence — Power BI Project Discovery.

Discovers and validates Power BI Project (.pbip) bundles, resolves report and
semantic model directories with resilient path resolution, guards against path
traversal, and catalogs all source artifacts with deterministic hashes.
"""

import os
import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from backend.connectors.base import ArtifactManifestItem, Diagnostic, DiagnosticSeverity
from backend.connectors.powerbi.jsonc_parser import parse_jsonc_file
from backend.ingestion.paths import safe_open, to_extended_path, strip_extended_prefix


@dataclass
class PbipProjectStructure:
    project_root: str
    pbip_file_path: str
    asset_name: str
    pbip_version: str
    report_dir_path: Optional[str] = None
    semantic_model_dir_path: Optional[str] = None
    artifacts: List[ArtifactManifestItem] = field(default_factory=list)
    diagnostics: List[Diagnostic] = field(default_factory=list)
    settings: Dict[str, str] = field(default_factory=dict)


def compute_file_sha256(filepath: str) -> str:
    """Computes sha256 checksum of a file on disk with long path support."""
    hasher = hashlib.sha256()
    with safe_open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def detect_artifact_type(relative_path: str) -> Tuple[str, Optional[str], bool]:
    """
    Returns (artifact_type, mime_type, is_supported) based on relative file path.
    """
    norm = relative_path.replace("\\", "/").lower()
    base = os.path.basename(norm)
    
    if base in (".ds_store", "thumbs.db", "desktop.ini"):
        return "OS_METADATA", "application/octet-stream", False
        
    if norm.endswith(".pbip"):
        return "PBIP_PROJECT_MANIFEST", "application/json", True
    if norm.endswith(".pbir"):
        return "PBIR_REPORT_DEFINITION", "application/json", True
    if norm.endswith(".pbism"):
        return "PBISM_MODEL_DEFINITION", "application/json", True
    if base == "report.json":
        return "REPORT_LAYOUT", "application/json", True
    if base == "page.json":
        return "PBIR_PAGE_DEFINITION", "application/json", True
    if base == "visual.json":
        return "PBIR_VISUAL_DEFINITION", "application/json", True
    if base == "pages.json":
        return "PBIR_PAGES_METADATA", "application/json", True
    if base == "diagramlayout.json":
        return "DIAGRAM_LAYOUT", "application/json", True
    if norm.endswith(".tmdl"):
        if "/tables/" in norm or norm.startswith("tables/"):
            return "TMDL_TABLE_DEFINITION", "text/plain", True
        elif norm.endswith("relationships.tmdl"):
            return "TMDL_RELATIONSHIPS", "text/plain", True
        elif norm.endswith("expressions.tmdl"):
            return "TMDL_EXPRESSIONS", "text/plain", True
        elif norm.endswith("model.tmdl"):
            return "TMDL_MODEL", "text/plain", True
        elif norm.endswith("database.tmdl"):
            return "TMDL_DATABASE", "text/plain", True
        elif "/cultures/" in norm or norm.startswith("cultures/"):
            return "TMDL_CULTURE_LINGUISTIC", "text/plain", True
        return "TMDL_METADATA", "text/plain", True
    if norm.endswith(".dax"):
        return "DAX_QUERY", "text/plain", True
    if "/customvisuals/" in norm or norm.startswith("customvisuals/"):
        if base == "package.json":
            return "CUSTOM_VISUAL_MANIFEST", "application/json", True
        elif norm.endswith(".pbiviz.json"):
            return "CUSTOM_VISUAL_RESOURCES", "application/json", True
    if "/basethemes/" in norm or norm.startswith("basethemes/") or "/registeredresources/" in norm or norm.startswith("registeredresources/") or norm.endswith(".json"):
        return "THEME_OR_JSON_RESOURCE", "application/json", True
        
    return "GENERIC_RESOURCE", "application/octet-stream", True


class PbipDiscovery:
    """Discovers and catalogs Power BI Project structure and artifacts."""

    @classmethod
    def discover(cls, source_path: str) -> PbipProjectStructure:
        """
        Discovers PBIP project given a .pbip file path or a directory containing one.
        """
        abs_source = os.path.abspath(source_path)
        diagnostics: List[Diagnostic] = []

        if not os.path.exists(abs_source):
            diagnostics.append(Diagnostic(
                code="SOURCE_PATH_NOT_FOUND",
                message=f"Provided source path does not exist: {abs_source}",
                severity=DiagnosticSeverity.FATAL,
                is_recoverable=False
            ))
            return PbipProjectStructure(
                project_root=abs_source,
                pbip_file_path="",
                asset_name=os.path.basename(abs_source),
                pbip_version="",
                diagnostics=diagnostics
            )

        # Determine project root and pbip file
        if os.path.isfile(abs_source):
            if not abs_source.endswith(".pbip"):
                diagnostics.append(Diagnostic(
                    code="INVALID_FILE_TYPE",
                    message=f"Expected .pbip file, got: {abs_source}",
                    severity=DiagnosticSeverity.ERROR,
                    is_recoverable=False
                ))
            pbip_file = abs_source
            project_root = os.path.dirname(abs_source)
        else:
            project_root = abs_source
            pbip_candidates = [
                os.path.join(project_root, f) for f in os.listdir(project_root)
                if f.endswith(".pbip") and not f.startswith(".")
            ]
            if pbip_candidates:
                pbip_file = sorted(pbip_candidates)[0]
            else:
                diagnostics.append(Diagnostic(
                    code="NO_PBIP_FILE_FOUND",
                    message=f"No .pbip file found in directory: {project_root}",
                    severity=DiagnosticSeverity.FATAL,
                    is_recoverable=False
                ))
                return PbipProjectStructure(
                    project_root=project_root,
                    pbip_file_path="",
                    asset_name=os.path.basename(project_root),
                    pbip_version="",
                    diagnostics=diagnostics
                )

        asset_name = os.path.splitext(os.path.basename(pbip_file))[0]

        # Parse .pbip manifest
        pbip_version = "1.0"
        settings = {}
        report_path_in_pbip = None

        try:
            pbip_data = parse_jsonc_file(pbip_file)
            pbip_version = str(pbip_data.get("version", "1.0"))
            settings = pbip_data.get("settings", {})
            artifacts_list = pbip_data.get("artifacts", [])
            for art in artifacts_list:
                if isinstance(art, dict) and "report" in art:
                    report_path_in_pbip = art["report"].get("path")
        except Exception as e:
            diagnostics.append(Diagnostic(
                code="PBIP_PARSE_ERROR",
                message=f"Failed to parse .pbip file: {e}",
                severity=DiagnosticSeverity.ERROR,
                source_artifact=os.path.basename(pbip_file)
            ))

        # Resolve .Report folder
        resolved_report_dir = None
        if report_path_in_pbip:
            candidate = os.path.normpath(os.path.join(project_root, report_path_in_pbip))
            if os.path.isdir(candidate):
                resolved_report_dir = candidate

        if not resolved_report_dir:
            # Fallback: scan for any *.Report directory
            for item in sorted(os.listdir(project_root)):
                c = os.path.join(project_root, item)
                if os.path.isdir(c) and item.endswith(".Report"):
                    resolved_report_dir = c
                    break

        if not resolved_report_dir:
            diagnostics.append(Diagnostic(
                code="REPORT_DIR_NOT_FOUND",
                message="Could not resolve .Report directory for PBIP project.",
                severity=DiagnosticSeverity.WARNING
            ))

        # Resolve .SemanticModel folder
        resolved_model_dir = None
        if resolved_report_dir:
            pbir_path = os.path.join(resolved_report_dir, "definition.pbir")
            if os.path.exists(pbir_path):
                try:
                    pbir_data = parse_jsonc_file(pbir_path)
                    ds_ref = pbir_data.get("datasetReference", {})
                    if "byPath" in ds_ref and "path" in ds_ref["byPath"]:
                        model_rel = ds_ref["byPath"]["path"]
                        candidate = os.path.normpath(os.path.join(resolved_report_dir, model_rel))
                        if os.path.isdir(candidate):
                            resolved_model_dir = candidate
                except Exception:
                    pass

        if not resolved_model_dir:
            # Fallback: scan for any *.SemanticModel directory in project_root
            for item in sorted(os.listdir(project_root)):
                c = os.path.join(project_root, item)
                if os.path.isdir(c) and item.endswith(".SemanticModel"):
                    resolved_model_dir = c
                    break

        if not resolved_model_dir:
            diagnostics.append(Diagnostic(
                code="SEMANTIC_MODEL_DIR_NOT_FOUND",
                message="Could not resolve .SemanticModel directory for PBIP project.",
                severity=DiagnosticSeverity.WARNING
            ))

        # Scan all files in project root to build artifact manifest
        artifact_items: List[ArtifactManifestItem] = []
        ext_project_root = to_extended_path(project_root)
        for root, dirs, files in os.walk(ext_project_root):
            norm_root = strip_extended_prefix(root)
            for fname in sorted(files):
                full_path = os.path.join(norm_root, fname)
                rel_path = os.path.relpath(full_path, project_root).replace("\\", "/")
                
                # Check path traversal / symlink escape
                real_path = os.path.realpath(full_path)
                if not real_path.startswith(os.path.realpath(project_root)):
                    diagnostics.append(Diagnostic(
                        code="ILLEGAL_PATH_TRAVERSAL",
                        message=f"Symlink or path outside project root detected: {rel_path}",
                        severity=DiagnosticSeverity.ERROR,
                        is_recoverable=False
                    ))
                    continue

                try:
                    size = os.path.getsize(to_extended_path(full_path))
                    chash = compute_file_sha256(full_path)
                    art_type, mime, is_supp = detect_artifact_type(rel_path)
                    artifact_items.append(ArtifactManifestItem(
                        relative_path=rel_path,
                        artifact_type=art_type,
                        size_bytes=size,
                        content_hash=chash,
                        is_supported=is_supp,
                        mime_type=mime
                    ))
                except Exception as ex:
                    diagnostics.append(Diagnostic(
                        code="ARTIFACT_READ_ERROR",
                        message=f"Error reading artifact {rel_path}: {ex}",
                        severity=DiagnosticSeverity.WARNING
                    ))

        return PbipProjectStructure(
            project_root=project_root,
            pbip_file_path=pbip_file,
            asset_name=asset_name,
            pbip_version=pbip_version,
            report_dir_path=resolved_report_dir,
            semantic_model_dir_path=resolved_model_dir,
            artifacts=artifact_items,
            diagnostics=diagnostics,
            settings=settings
        )
