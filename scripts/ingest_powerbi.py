#!/usr/bin/env python3
"""
KPI Intelligence — Power BI PBIP Metadata Ingestion CLI.

CLI tool for extracting metadata from Power BI Projects (.pbip),
normalizing into canonical data model documents, and persisting
to Azure Cosmos DB for NoSQL (or local SQLite during development/test).
"""

import os
import sys
import argparse
import json
import uuid

# Ensure repository root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.connectors.base import PlatformType
from backend.ingestion.service import IngestionService
from backend.storage.config import StorageConfig, StorageBackendType
from backend.storage.factory import get_repository


def main():
    parser = argparse.ArgumentParser(
        description="Ingest Power BI PBIP metadata into KPI Intelligence canonical model (Cosmos DB / SQLite)."
    )
    parser.add_argument(
        "--source",
        default="reference",
        help="Path to .pbip file or directory containing a Power BI project (default: reference)"
    )
    parser.add_argument(
        "--tenant-id",
        default="11111111-1111-1111-1111-111111111111",
        help="Tenant UUID for isolation and partition routing"
    )
    parser.add_argument(
        "--backend",
        choices=["sqlite", "cosmos"],
        default=None,
        help="Storage backend override (default: KPI_STORAGE_BACKEND env var or sqlite in dev)"
    )
    parser.add_argument(
        "--version-number",
        type=int,
        default=1,
        help="Asset version number (default: 1)"
    )
    parser.add_argument(
        "--output-sql",
        help="Optional path to output the compiled transactional SQL script (legacy/debug)"
    )
    parser.add_argument(
        "--output-json",
        help="Optional path to output the normalized metadata summary as JSON"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform parsing and normalization without persisting documents"
    )

    args = parser.parse_args()

    try:
        tenant_uuid = uuid.UUID(args.tenant_id)
    except ValueError:
        print(f"Error: Invalid tenant UUID: {args.tenant_id}", file=sys.stderr)
        sys.exit(1)

    if args.backend:
        os.environ["KPI_STORAGE_BACKEND"] = args.backend

    try:
        cfg = StorageConfig.from_env()
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    print("======================================================================")
    print("KPI INTELLIGENCE — POWER BI PBIP METADATA INGESTION")
    print(f"Source:          {args.source}")
    print(f"Tenant ID:       {tenant_uuid}")
    print(f"Version:         #{args.version_number}")
    print(f"Storage Backend: {cfg.backend.value.upper()} (Env: {cfg.environment.value})")
    print(f"Dry Run:         {'YES' if args.dry_run else 'NO'}")
    print("======================================================================\n")

    repo = None
    if not args.dry_run:
        try:
            repo = get_repository(cfg)
        except Exception as e:
            print(f"Error initializing repository backend: {e}", file=sys.stderr)
            sys.exit(1)

    service = IngestionService(tenant_id=tenant_uuid, repository=repo)
    
    try:
        summary = service.ingest_project(
            source_path=args.source,
            platform=PlatformType.POWER_BI,
            version_number=args.version_number,
            generate_sql_only=args.dry_run
        )
    except Exception as ex:
        print(f"Ingestion failed: {ex}", file=sys.stderr)
        sys.exit(1)

    # Save SQL output if requested
    if args.output_sql and summary.sql_script:
        out_sql_dir = os.path.dirname(os.path.abspath(args.output_sql))
        os.makedirs(out_sql_dir, exist_ok=True)
        with open(args.output_sql, "w", encoding="utf-8") as f:
            f.write(summary.sql_script)
        print(f"Exported transactional SQL ({len(summary.sql_script)} chars) to: {args.output_sql}")

    # Save JSON output if requested
    if args.output_json:
        out_json_dir = os.path.dirname(os.path.abspath(args.output_json))
        os.makedirs(out_json_dir, exist_ok=True)
        summary_dict = {
            "asset_id": str(summary.asset_id),
            "asset_version_id": str(summary.asset_version_id),
            "tenant_id": str(summary.tenant_id),
            "platform": summary.platform,
            "asset_name": summary.asset_name,
            "version_number": summary.version_number,
            "content_hash": summary.content_hash,
            "raw_content_hash": summary.raw_content_hash,
            "structure_hash": summary.structure_hash,
            "metadata_hash": summary.metadata_hash,
            "stats": summary.stats,
            "diagnostics": [
                {"code": d.code, "message": d.message, "severity": d.severity.value}
                for d in summary.diagnostics
            ],
            "is_live": summary.is_live,
            "status": summary.status
        }
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(summary_dict, f, indent=2)
        print(f"Exported metadata summary to: {args.output_json}")

    print("\n--- INGESTION SUMMARY ---")
    print(f"Status:                     {summary.status}")
    print(f"Asset Name:                 {summary.asset_name}")
    print(f"Asset ID:                   {summary.asset_id}")
    print(f"Version ID:                 {summary.asset_version_id}")
    print(f"Content Hash:               {summary.content_hash}")
    print(f"Cosmos Documents Persisted: {summary.stats.get('cosmos_documents_persisted', 0)}")
    print(f"Source Artifacts:           {summary.stats.get('source_artifacts', 0)}")
    print(f"Reports:                    {summary.stats.get('reports', 0)}")
    print(f"Report Pages:               {summary.stats.get('report_pages', 0)}")
    print(f"Visuals:                    {summary.stats.get('visuals', 0)}")
    print(f"Semantic Models:            {summary.stats.get('semantic_models', 0)}")
    print(f"Data Tables:                {summary.stats.get('data_tables', 0)}")
    print(f"Data Columns:               {summary.stats.get('data_columns', 0)}")
    print(f"Calculations (Measures):    {summary.stats.get('calculations', 0)}")
    print(f"Relationships:              {summary.stats.get('relationships', 0)}")
    print(f"Lineage Edges:              {summary.stats.get('metadata_lineage_edges', 0)}")
    print(f"Backend Target:             {cfg.backend.value.upper()}")
    print("======================================================================\n")


if __name__ == "__main__":
    main()

