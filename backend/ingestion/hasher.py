"""
KPI Intelligence — Canonical Ingestion Hasher.

Computes deterministic raw content, structural, metadata, and composite hashes
for asset version snapshots and re-ingestion deduplication.
"""

import hashlib
import json
from typing import List, Dict, Any
from backend.connectors.base import ArtifactManifestItem


class IngestionHasher:
    """Computes reproducible content and structural hashes."""

    @staticmethod
    def compute_raw_content_hash(artifacts: List[ArtifactManifestItem]) -> str:
        """
        Computes SHA256 over all project files sorted deterministically by relative path.
        """
        hasher = hashlib.sha256()
        for art in sorted(artifacts, key=lambda a: a.relative_path):
            entry = f"{art.relative_path}:{art.size_bytes}:{art.content_hash}\n"
            hasher.update(entry.encode("utf-8"))
        return hasher.hexdigest()

    @staticmethod
    def compute_structure_hash(raw_model: Dict[str, Any], raw_report: Dict[str, Any]) -> str:
        """
        Computes SHA256 of the structural hierarchy:
        tables, column names, measure names, calculation items, pages, visual types.
        Invariant to formatting whitespace and comments.
        """
        hasher = hashlib.sha256()
        
        # 1. Structural model elements
        tables_summary = []
        if raw_model and "tables" in raw_model:
            for tname in sorted(raw_model["tables"].keys()):
                tbl = raw_model["tables"][tname]
                cols = sorted([c.name for c in tbl.columns])
                meas = sorted([m.name for m in tbl.measures])
                citems = []
                if tbl.calculation_group:
                    citems = sorted([item.name for item in tbl.calculation_group.items])
                tables_summary.append({
                    "table": tname,
                    "columns": cols,
                    "measures": meas,
                    "calc_items": citems
                })
        
        # 2. Structural report elements
        pages_summary = []
        if raw_report and "pages" in raw_report:
            for p in raw_report["pages"]:
                vis_types = sorted([v.visual_type for v in p.visuals])
                pages_summary.append({
                    "page": p.page_name,
                    "visuals": vis_types
                })
                
        structure_repr = json.dumps({
            "tables": tables_summary,
            "pages": pages_summary
        }, sort_keys=True)
        
        hasher.update(structure_repr.encode("utf-8"))
        return hasher.hexdigest()

    @staticmethod
    def compute_metadata_hash(raw_model: Dict[str, Any], raw_report: Dict[str, Any]) -> str:
        """
        Computes SHA256 of semantic properties:
        data types, DAX expression text, format strings, lineage tags.
        """
        hasher = hashlib.sha256()
        metadata_summary = []
        
        if raw_model and "tables" in raw_model:
            for tname in sorted(raw_model["tables"].keys()):
                tbl = raw_model["tables"][tname]
                for c in sorted(tbl.columns, key=lambda x: x.name):
                    metadata_summary.append(f"C:{tname}.{c.name}:{c.data_type}:{c.format_string}:{c.lineage_tag}:{c.expression or ''}")
                for m in sorted(tbl.measures, key=lambda x: x.name):
                    metadata_summary.append(f"M:{tname}.{m.name}:{m.format_string}:{m.lineage_tag}:{m.expression}")
                if tbl.calculation_group:
                    for ci in sorted(tbl.calculation_group.items, key=lambda x: x.name):
                        metadata_summary.append(f"CI:{tname}.{ci.name}:{ci.format_string_definition or ''}:{ci.expression}")
                        
        metadata_repr = "\n".join(metadata_summary)
        hasher.update(metadata_repr.encode("utf-8"))
        return hasher.hexdigest()

    @classmethod
    def compute_composite_content_hash(cls, raw_content_hash: str, structure_hash: str, metadata_hash: str) -> str:
        """
        Computes master composite content hash.
        """
        hasher = hashlib.sha256()
        composite = f"RAW:{raw_content_hash}|STRUCT:{structure_hash}|META:{metadata_hash}"
        hasher.update(composite.encode("utf-8"))
        return hasher.hexdigest()
