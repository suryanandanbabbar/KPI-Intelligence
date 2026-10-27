"""
KPI Intelligence — Local Database Management, Inspection, and Verification CLI.

Developer inspection, seeding, and validation CLI for local SQLite persistence.
Supports both:
1. --relational: Complete 61-table relational mirror mirroring canonical_schema.sql.
2. --cosmos: Local Cosmos DB emulation store (cosmos_documents table).
3. --all (default): Applies operations across both relational and Cosmos stores.

Commands:
- python -m backend.storage.cli init [--relational | --cosmos | --all] [--seed]
- python -m backend.storage.cli validate [--relational | --cosmos | --all]
- python -m backend.storage.cli inspect [--relational | --cosmos | --all] [--container <name>] [--tenant <id>] [--doc <id>]
- python -m backend.storage.cli export [--relational | --cosmos | --all] [--output <path>]
- python -m backend.storage.cli reset [--relational | --cosmos | --all] [--force]
"""

import sys
import os
import json
import argparse
from typing import Dict, Any, Optional

from backend.storage.config import StorageConfig
from backend.storage.sqlite.repository import SQLiteRepository
from backend.storage.fixtures import generate_synthetic_fixtures
from backend.contracts.base import CosmosContainer, CONTAINER_PARTITION_KEYS
from backend.storage.sqlite.relational_manager import (
    init_relational_schema,
    validate_relational_schema,
    seed_relational_synthetic_data,
    run_relational_checks,
    inspect_relational_database,
    export_relational_data,
)


REDACTED_FIELDS = {"password", "secret", "token", "client_secret", "key", "authorization"}


def sanitize_dict(data: Any) -> Any:
    """Recursively redacts sensitive fields from dictionary payloads."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if any(s in k.lower() for s in REDACTED_FIELDS):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_dict(v)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_dict(item) for item in data]
    return data


def init_db(
    repo: SQLiteRepository,
    mode: str = "all",
    seed: bool = False,
) -> None:
    """Initializes SQLite schema(s) and optionally loads synthetic seed data."""
    print("=" * 70)
    print("KPI INTELLIGENCE — LOCAL DATABASE INITIALIZATION")
    print(f"Target Database File: {os.path.abspath(repo.db_path)}")
    print(f"Target Mode:          {mode.upper()}")
    print("=" * 70)

    # 1. Cosmos Document Store
    if mode in ("cosmos", "all"):
        repo._ensure_db_initialized()
        print(" [Cosmos Store] Initialized table 'cosmos_documents'.")
        if seed:
            fixtures = generate_synthetic_fixtures()
            total_seeded = 0
            for container, docs in fixtures.items():
                partition_key_attr = "business_domain" if container == CosmosContainer.KPI_ONTOLOGY else "tenant_id"
                for doc in docs:
                    pk = getattr(doc, partition_key_attr) or getattr(doc, "id")
                    repo.upsert_item(container, pk, doc.to_dict())
                    total_seeded += 1
                print(f"   * Container '{container.value}': loaded {len(docs)} synthetic documents.")
            print(f" [Cosmos Store] Seed complete: {total_seeded} synthetic documents inserted.\n")

    # 2. Relational Mirror (61 canonical tables)
    if mode in ("relational", "all"):
        init_relational_schema(repo.db_path)
        print(" [Relational Mirror] Initialized all 61 canonical relational tables.")
        if seed:
            counts = seed_relational_synthetic_data(repo.db_path)
            total_rel_rows = sum(counts.values())
            print(f" [Relational Mirror] Seed complete: {total_rel_rows} records inserted across {len(counts)} canonical tables.")
            checks = run_relational_checks(repo.db_path)
            print(f" [Relational Mirror] Checks: FK violations={checks['foreign_key_violations_count']}, Integrity={checks['integrity_check']}")

    print("=" * 70)


def validate_db(db_path: str, mode: str = "all") -> bool:
    """Runs automated structural and integrity validation."""
    print("=" * 70)
    print("KPI INTELLIGENCE — LOCAL DATABASE VALIDATION")
    print(f"Target Database: {os.path.abspath(db_path)}")
    print("=" * 70)

    overall_pass = True

    if mode in ("relational", "all"):
        print("\n--- 1. RELATIONAL MIRROR VALIDATION ---")
        val = validate_relational_schema(db_path)
        if val["valid"]:
            print(f" [PASS] All {val['tables_count']} canonical tables exist.")
            print(f" [PASS] All {val['total_columns']} canonical columns verified against canonical schema.")
            print(f" [PASS] Foreign Key Check: {val['fk_violations_count']} violations.")
            print(f" [PASS] Integrity Check: {val['integrity_check']}.")
        else:
            print(" [FAIL] Relational schema validation failed!")
            if val["missing_tables"]:
                print(f"        Missing tables: {val['missing_tables']}")
            if val["missing_columns"]:
                print(f"        Missing columns: {val['missing_columns']}")
            if val["fk_violations"]:
                print(f"        FK violations: {val['fk_violations']}")
            overall_pass = False

    if mode in ("cosmos", "all"):
        print("\n--- 2. COSMOS STORE VALIDATION ---")
        if os.path.exists(db_path):
            try:
                repo = SQLiteRepository(db_path)
                diag = repo.check_integrity(deep=True)
                if not diag["healthy"]:
                    print(f" [FAIL] SQLite database integrity check failed: {diag.get('messages')}")
                    overall_pass = False
                else:
                    cnt = repo.inspect_counts()["total_documents"]
                    print(f" [PASS] Table 'cosmos_documents' is healthy (integrity: OK, count: {cnt} docs).")
            except Exception as ex:
                print(f" [FAIL] SQLite database inspection failed: {ex}")
                overall_pass = False
        else:
            print(" [FAIL] SQLite database does not exist.")
            overall_pass = False

    print("\n" + "=" * 70)
    print(f"OVERALL VALIDATION: {'PASSED' if overall_pass else 'FAILED'}")
    print("=" * 70)
    return overall_pass


def inspect_db(
    repo: SQLiteRepository,
    mode: str = "all",
    container_filter: Optional[str] = None,
    tenant_filter: Optional[str] = None,
    doc_id: Optional[str] = None,
) -> None:
    """Inspects local SQLite database contents, relational tables, and cosmos documents."""
    print("=" * 70)
    print("KPI INTELLIGENCE — LOCAL DATABASE INSPECTOR")
    print(f"Target Database: {os.path.abspath(repo.db_path)}")
    print(f"Target Mode:     {mode.upper()}")
    print("=" * 70)

    if not os.path.exists(repo.db_path):
        print(f"[ERROR] Database file not found at: {repo.db_path}")
        print("Run 'python -m backend.storage.cli init' to create it.")
        return

    # Relational summary
    if mode in ("relational", "all"):
        print("\n=== 1. CANONICAL RELATIONAL MIRROR (61 TABLES) ===")
        rel_info = inspect_relational_database(repo.db_path)
        print(f"Canonical Tables: {rel_info.get('tables_count', 0)} / 61")
        print(f"Canonical Columns: {rel_info.get('columns_count', 0)} / 636")
        print(f"Total Rows:        {rel_info.get('total_rows', 0)}")
        print(f"FK Violations:     {rel_info.get('foreign_key_violations', 0)}")
        print(f"Integrity Check:   {rel_info.get('integrity_check', 'unknown')}")
        print("\nSubsystem Row Breakdown:")
        for subsystem, tbls in rel_info.get("subsystems", {}).items():
            sub_total = sum(tbls.values())
            print(f"  [{subsystem}] (Total rows: {sub_total})")
            for t_name, count in tbls.items():
                if count > 0:
                    print(f"    - {t_name:<30}: {count} rows")

    # Cosmos summary
    if mode in ("cosmos", "all"):
        print("\n=== 2. COSMOS EMULATION STORE (cosmos_documents) ===")
        repo._ensure_db_initialized()
        with repo._get_connection() as conn:
            cur = conn.execute("SELECT COUNT(*) AS total FROM cosmos_documents;")
            total = cur.fetchone()["total"]
            print(f"Total Canonical Documents: {total}\n")

            print("--- Containers ---")
            cur = conn.execute(
                "SELECT container_name, COUNT(*) AS cnt FROM cosmos_documents GROUP BY container_name ORDER BY cnt DESC;"
            )
            for r in cur.fetchall():
                print(f"  * {r['container_name']:<24}: {r['cnt']} documents")

            print("\n--- Document Types ---")
            cur = conn.execute(
                "SELECT document_type, COUNT(*) AS cnt FROM cosmos_documents GROUP BY document_type ORDER BY cnt DESC;"
            )
            for r in cur.fetchall():
                print(f"  * {r['document_type']:<24}: {r['cnt']} documents")

            print("\n--- Tenants ---")
            cur = conn.execute(
                "SELECT tenant_id, COUNT(*) AS cnt FROM cosmos_documents GROUP BY tenant_id ORDER BY cnt DESC;"
            )
            for r in cur.fetchall():
                t_label = r["tenant_id"] if r["tenant_id"] else "[Global/Reference]"
                print(f"  * {t_label:<38}: {r['cnt']} documents")

    print("\n" + "=" * 70)


def export_db(repo: SQLiteRepository, mode: str = "all", output_path: Optional[str] = None) -> None:
    """Exports local database data."""
    if mode in ("relational", "all"):
        rel_out = output_path or "local_data/relational_export.json"
        saved = export_relational_data(repo.db_path, rel_out)
        print(f"[SUCCESS] Exported 61 relational tables to: {saved}")

    if mode in ("cosmos", "all"):
        cos_out = output_path if mode == "cosmos" else "local_data/cosmos_documents_export.json"
        repo._ensure_db_initialized()
        with repo._get_connection() as conn:
            cur = conn.execute("SELECT container_name, partition_key, document_id, document_json FROM cosmos_documents;")
            rows = cur.fetchall()
            all_docs = []
            for r in rows:
                doc = json.loads(r["document_json"])
                all_docs.append({
                    "container": r["container_name"],
                    "partition_key": r["partition_key"],
                    "document": sanitize_dict(doc),
                })

        dir_name = os.path.dirname(cos_out)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        with open(cos_out, "w", encoding="utf-8") as f:
            json.dump(all_docs, f, indent=2)

        print(f"[SUCCESS] Exported {len(all_docs)} Cosmos documents to: {cos_out}")


def reset_db(repo: SQLiteRepository, mode: str = "all", force: bool = False) -> None:
    """Resets local SQLite database after confirmation."""
    if not force:
        confirm = input(f"Are you sure you want to reset {mode.upper()} store in {repo.db_path}? (y/N): ")
        if confirm.strip().lower() != "y":
            print("Operation aborted.")
            return

    if mode == "all":
        if os.path.exists(repo.db_path):
            os.remove(repo.db_path)
            print(f"[SUCCESS] Removed local SQLite database file: {repo.db_path}")
    elif mode == "cosmos":
        repo.reset_database()
        print(f"[SUCCESS] Cleared cosmos_documents table in: {repo.db_path}")
    elif mode == "relational":
        if os.path.exists(repo.db_path):
            with repo._get_connection() as conn:
                cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'cosmos_documents' AND name NOT LIKE 'sqlite_%';")
                tables = [r["name"] for r in cur.fetchall()]
                for tbl in tables:
                    conn.execute(f"DROP TABLE IF EXISTS {tbl};")
            print(f"[SUCCESS] Dropped all relational tables in: {repo.db_path}")


def main():
    parser = argparse.ArgumentParser(description="KPI Intelligence Local SQLite Management CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Common store mode argument helper
    def add_mode_args(subp):
        mode_group = subp.add_mutually_exclusive_group()
        mode_group.add_argument("--relational", action="store_true", help="Operate on 61 canonical relational tables")
        mode_group.add_argument("--cosmos", action="store_true", help="Operate on Cosmos DB emulation documents")
        mode_group.add_argument("--all", action="store_true", default=True, help="Operate on both relational and Cosmos stores (default)")

    # init
    init_parser = subparsers.add_parser("init", help="Initialize SQLite schema and optionally seed data")
    add_mode_args(init_parser)
    init_parser.add_argument("--seed", action="store_true", help="Populate with synthetic test fixtures")

    # validate
    val_parser = subparsers.add_parser("validate", help="Validate relational schema and Cosmos store integrity")
    add_mode_args(val_parser)

    # inspect
    inspect_parser = subparsers.add_parser("inspect", help="Inspect local SQLite database")
    add_mode_args(inspect_parser)
    inspect_parser.add_argument("--container", type=str, help="Filter by container name (Cosmos mode)")
    inspect_parser.add_argument("--tenant", type=str, help="Filter by tenant ID (Cosmos mode)")
    inspect_parser.add_argument("--doc", type=str, help="Display specific document by ID (Cosmos mode)")

    # export
    export_parser = subparsers.add_parser("export", help="Export database contents to JSON")
    add_mode_args(export_parser)
    export_parser.add_argument("--output", type=str, help="Output file path")

    # reset
    reset_parser = subparsers.add_parser("reset", help="Clear records from local SQLite database")
    add_mode_args(reset_parser)
    reset_parser.add_argument("--force", action="store_true", help="Bypass confirmation prompt")

    args = parser.parse_args()

    mode = "all"
    if getattr(args, "relational", False):
        mode = "relational"
    elif getattr(args, "cosmos", False):
        mode = "cosmos"

    cfg = StorageConfig.from_env()
    repo = SQLiteRepository(cfg.sqlite_path)

    if args.command == "init":
        init_db(repo, mode=mode, seed=args.seed)
    elif args.command == "validate":
        ok = validate_db(repo.db_path, mode=mode)
        sys.exit(0 if ok else 1)
    elif args.command == "inspect":
        inspect_db(repo, mode=mode, container_filter=args.container, tenant_filter=args.tenant, doc_id=args.doc)
    elif args.command == "export":
        export_db(repo, mode=mode, output_path=args.output)
    elif args.command == "reset":
        reset_db(repo, mode=mode, force=args.force)


if __name__ == "__main__":
    main()
