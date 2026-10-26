"""
KPI Intelligence — Power BI Report Parser.

Parses Power BI Report definitions (.pbir, report.json, custom visuals, themes)
into structured Python dataclasses representing reports, pages, visual containers,
bindings, visual properties, bookmarks, and filters.
"""

import os
import json
import uuid
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
from backend.connectors.powerbi.jsonc_parser import parse_jsonc, parse_jsonc_file


@dataclass
class ReportVisualBinding:
    binding_role: str
    target_entity: Optional[str] = None
    target_property: Optional[str] = None
    aggregation: Optional[str] = None
    format_override: Optional[str] = None
    binding_order: int = 0
    binding_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReportVisual:
    visual_id: str
    visual_type: str
    title: Optional[str] = None
    description: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    z_order: int = 0
    is_visible: bool = True
    bindings: List[ReportVisualBinding] = field(default_factory=list)
    visual_properties: Dict[str, Any] = field(default_factory=dict)
    filters: List[Dict[str, Any]] = field(default_factory=list)
    raw_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReportPage:
    source_native_id: str
    page_name: str
    page_order: int = 0
    page_type: str = "Standard"
    width: Optional[float] = 1280.0
    height: Optional[float] = 720.0
    is_hidden: bool = False
    visuals: List[ReportVisual] = field(default_factory=list)
    filters: List[Dict[str, Any]] = field(default_factory=list)
    page_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReportBookmark:
    bookmark_id: str
    display_name: str
    active_section: Optional[str] = None
    target_visual_names: List[str] = field(default_factory=list)
    bookmark_state: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReportCustomVisual:
    guid: str
    name: str
    display_name: str
    version: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReportDefinition:
    report_name: str
    pbir_version: Optional[str] = None
    dataset_reference_path: Optional[str] = None
    theme: Optional[str] = None
    pages: List[ReportPage] = field(default_factory=list)
    bookmarks: List[ReportBookmark] = field(default_factory=list)
    custom_visuals: List[ReportCustomVisual] = field(default_factory=list)
    report_filters: List[Dict[str, Any]] = field(default_factory=list)
    report_configuration: Dict[str, Any] = field(default_factory=dict)
    owner_id: Optional[Union[str, uuid.UUID]] = None
    owner_name: Optional[str] = None
    last_accessed_at: Optional[datetime] = None


def _safe_json_unpack(val: Any) -> Any:
    """Helper to decode embedded stringified JSON fields safely."""
    if isinstance(val, str):
        val_str = val.strip()
        if (val_str.startswith("{") and val_str.endswith("}")) or (val_str.startswith("[") and val_str.endswith("]")):
            try:
                return parse_jsonc(val_str)
            except Exception:
                return val
    return val


class ReportParser:
    """Parser for Power BI .Report folders."""

    @classmethod
    def parse_report_directory(cls, report_dir_path: str, asset_name: str = "Report") -> ReportDefinition:
        """Parses an entire *.Report directory."""
        rep = ReportDefinition(report_name=asset_name)

        # 1. Parse definition.pbir
        pbir_path = os.path.join(report_dir_path, "definition.pbir")
        if os.path.exists(pbir_path):
            try:
                pbir_data = parse_jsonc_file(pbir_path)
                rep.pbir_version = str(pbir_data.get("version", ""))
                ds_ref = pbir_data.get("datasetReference", {})
                if "byPath" in ds_ref and "path" in ds_ref["byPath"]:
                    rep.dataset_reference_path = ds_ref["byPath"]["path"]
            except Exception as e:
                pass

        # 2. Parse report.json
        rep_json_path = os.path.join(report_dir_path, "report.json")
        if os.path.exists(rep_json_path):
            try:
                raw_json = parse_jsonc_file(rep_json_path)
                cls._parse_report_json(raw_json, rep)
            except Exception as e:
                pass

        # 3. Parse CustomVisuals
        custom_vis_dir = os.path.join(report_dir_path, "CustomVisuals")
        if os.path.exists(custom_vis_dir):
            for vfolder in sorted(os.listdir(custom_vis_dir)):
                pkg_json = os.path.join(custom_vis_dir, vfolder, "package.json")
                if os.path.exists(pkg_json):
                    try:
                        pkg_data = parse_jsonc_file(pkg_json)
                        vis_info = pkg_data.get("visual", {})
                        author_info = pkg_data.get("author", {})
                        author_name = author_info.get("name", "") if isinstance(author_info, dict) else str(author_info)
                        cv = ReportCustomVisual(
                            guid=vis_info.get("guid", vfolder),
                            name=vis_info.get("name", vfolder),
                            display_name=vis_info.get("displayName", vis_info.get("name", vfolder)),
                            version=vis_info.get("version", pkg_data.get("version")),
                            description=vis_info.get("description"),
                            author=author_name,
                            properties=pkg_data
                        )
                        rep.custom_visuals.append(cv)
                    except Exception:
                        pass

        return rep

    @classmethod
    def _parse_report_json(cls, data: Dict[str, Any], rep: ReportDefinition) -> None:
        """Parses report.json contents into ReportDefinition."""
        rep.theme = data.get("theme")
        
        # Check for authoritative owner/access metadata if explicitly present
        if "owner_id" in data and data["owner_id"]:
            rep.owner_id = data["owner_id"]
        if "owner_name" in data and data["owner_name"]:
            rep.owner_name = str(data["owner_name"])
        if "last_accessed_at" in data and data["last_accessed_at"]:
            if isinstance(data["last_accessed_at"], datetime):
                rep.last_accessed_at = data["last_accessed_at"]
            elif isinstance(data["last_accessed_at"], str):
                try:
                    rep.last_accessed_at = datetime.fromisoformat(data["last_accessed_at"])
                except Exception:
                    pass

        # Unpack top-level config (which can be a stringified JSON)
        raw_config = _safe_json_unpack(data.get("config", {}))
        if isinstance(raw_config, dict):
            rep.report_configuration = raw_config
            # Extract bookmarks from config
            bookmarks_list = raw_config.get("bookmarks", [])
            for bm in bookmarks_list:
                if isinstance(bm, dict):
                    bm_id = bm.get("name", "")
                    disp_name = bm.get("displayName", bm_id)
                    exp_state = bm.get("explorationState", {})
                    active_sec = exp_state.get("activeSection") if isinstance(exp_state, dict) else None
                    opts = bm.get("options", {})
                    targets = opts.get("targetVisualNames", []) if isinstance(opts, dict) else []
                    rep.bookmarks.append(ReportBookmark(
                        bookmark_id=bm_id,
                        display_name=disp_name,
                        active_section=active_sec,
                        target_visual_names=targets,
                        bookmark_state=bm
                    ))

        # Unpack report-level filters
        raw_filters = _safe_json_unpack(data.get("filters", []))
        if isinstance(raw_filters, list):
            rep.report_filters = raw_filters

        # Parse sections (pages)
        sections = data.get("sections", [])
        for order, sec in enumerate(sections):
            if not isinstance(sec, dict):
                continue
            sec_name = sec.get("name", f"section_{order}")
            disp_name = sec.get("displayName", sec_name)
            width = sec.get("width", 1280.0)
            height = sec.get("height", 720.0)
            
            # Page config
            sec_config = _safe_json_unpack(sec.get("config", {}))
            sec_filters = _safe_json_unpack(sec.get("filters", []))
            if not isinstance(sec_filters, list):
                sec_filters = []
                
            page = ReportPage(
                source_native_id=sec_name,
                page_name=disp_name,
                page_order=order,
                width=float(width) if width is not None else 1280.0,
                height=float(height) if height is not None else 720.0,
                filters=sec_filters,
                page_properties=sec_config if isinstance(sec_config, dict) else {}
            )
            
            # Parse visual containers
            vcontainers = sec.get("visualContainers", [])
            for v_idx, vc in enumerate(vcontainers):
                if not isinstance(vc, dict):
                    continue
                visual = cls._parse_visual_container(vc, v_idx)
                page.visuals.append(visual)
                
            rep.pages.append(page)

    @classmethod
    def _parse_visual_container(cls, vc: Dict[str, Any], default_idx: int) -> ReportVisual:
        """Parses a single visualContainer object."""
        vc_id = str(vc.get("id", default_idx))
        x = vc.get("x")
        y = vc.get("y")
        width = vc.get("width")
        height = vc.get("height")
        z = vc.get("z", default_idx)
        
        vc_config = _safe_json_unpack(vc.get("config", {}))
        vc_filters = _safe_json_unpack(vc.get("filters", []))
        if not isinstance(vc_filters, list):
            vc_filters = []
            
        vis_type = "unknown"
        vis_name = vc_id
        title = None
        description = None
        bindings: List[ReportVisualBinding] = []
        vis_props: Dict[str, Any] = {}
        
        if isinstance(vc_config, dict):
            vis_name = vc_config.get("name", vc_id)
            single_vis = vc_config.get("singleVisual", {})
            if isinstance(single_vis, dict):
                vis_type = single_vis.get("visualType", "unknown")
                objects = single_vis.get("objects", {})
                if isinstance(objects, dict):
                    vis_props = objects
                    title_obj = objects.get("title", [{}])
                    if isinstance(title_obj, list) and len(title_obj) > 0:
                        props = title_obj[0].get("properties", {})
                        text_expr = props.get("text", {}).get("expr", {}).get("Literal", {}).get("Value")
                        if text_expr:
                            title = str(text_expr).strip("'\"")
                            
                # Extract visual bindings / projections
                projections = single_vis.get("projections", {})
                binding_order = 0
                if isinstance(projections, dict):
                    for role, proj_list in projections.items():
                        if isinstance(proj_list, list):
                            for proj in proj_list:
                                binding_order += 1
                                qref = proj.get("queryRef", "") if isinstance(proj, dict) else ""
                                entity = None
                                prop = None
                                if "." in qref:
                                    parts = qref.split(".", 1)
                                    entity = parts[0]
                                    prop = parts[1]
                                bindings.append(ReportVisualBinding(
                                    binding_role=role,
                                    target_entity=entity,
                                    target_property=prop,
                                    binding_order=binding_order,
                                    binding_properties=proj if isinstance(proj, dict) else {}
                                ))

        return ReportVisual(
            visual_id=vis_name,
            visual_type=vis_type,
            title=title,
            description=description,
            position_x=float(x) if x is not None else None,
            position_y=float(y) if y is not None else None,
            width=float(width) if width is not None else None,
            height=float(height) if height is not None else None,
            z_order=int(z) if z is not None else default_idx,
            bindings=bindings,
            visual_properties=vis_props,
            filters=vc_filters,
            raw_config=vc_config if isinstance(vc_config, dict) else {}
        )
