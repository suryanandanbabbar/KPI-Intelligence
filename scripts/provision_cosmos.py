#!/usr/bin/env python3
"""
KPI Intelligence — Azure Cosmos DB for NoSQL Provisioning CLI.

Idempotently provisions the production Azure Cosmos DB database and
containers with exact partition keys, indexing policies, and default TTLs.
Can authenticate via Azure Managed Identity (DefaultAzureCredential) or Account Key.
"""

import os
import sys
import json
import argparse
from typing import Dict, Any, Optional

# Ensure repository root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def load_containers_spec(spec_path: Optional[str] = None) -> Dict[str, Any]:
    """Loads declarative container definitions from JSON specification."""
    if not spec_path:
        spec_path = os.path.join(REPO_ROOT, "infra", "cosmos", "containers.json")

    if os.path.isfile(spec_path):
        with open(spec_path, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        # Fallback inline defaults
        return {
            "database": {"name": "kpi_intelligence"},
            "containers": [
                {
                    "name": "metadata_catalog",
                    "partitionKey": {"paths": ["/tenant_id"], "kind": "Hash", "version": 2},
                    "defaultTtl": -1,
                },
                {
                    "name": "kpi_governance",
                    "partitionKey": {"paths": ["/tenant_id"], "kind": "Hash", "version": 2},
                    "defaultTtl": -1,
                },
                {
                    "name": "kpi_ontology",
                    "partitionKey": {"paths": ["/business_domain"], "kind": "Hash", "version": 2},
                    "defaultTtl": -1,
                },
                {
                    "name": "operational_audit",
                    "partitionKey": {"paths": ["/tenant_id"], "kind": "Hash", "version": 2},
                    "defaultTtl": 7776000,
                },
            ]
        }


def provision_cosmos(
    endpoint: str,
    database_name: str,
    key: Optional[str] = None,
    use_managed_identity: bool = True,
    spec_path: Optional[str] = None,
    dry_run: bool = False,
) -> None:
    """Provisions Cosmos DB database and containers idempotently."""
    spec = load_containers_spec(spec_path)
    db_name = database_name or spec.get("database", {}).get("name", "kpi_intelligence")
    containers = spec.get("containers", [])

    print("======================================================================")
    print("KPI INTELLIGENCE — AZURE COSMOS DB PROVISIONING")
    print(f"Endpoint:         {endpoint}")
    print(f"Database:         {db_name}")
    print(f"Authentication:   {'Managed Identity (DefaultAzureCredential)' if use_managed_identity else 'Account Key'}")
    print(f"Containers to configure: {len(containers)}")
    print(f"Dry Run:          {'YES' if dry_run else 'NO'}")
    print("======================================================================\n")

    if dry_run:
        print("[DRY RUN] Plan of operations:")
        print(f"  1. Ensure database '{db_name}' exists.")
        for c in containers:
            c_name = c["name"]
            pk_paths = c.get("partitionKey", {}).get("paths", ["/tenant_id"])
            ttl = c.get("defaultTtl", -1)
            print(f"  2. Ensure container '{c_name}' exists with partition key {pk_paths} and default TTL {ttl}s.")
        print("\n[DRY RUN] Completed without applying changes.")
        return

    try:
        from azure.cosmos import CosmosClient, PartitionKey
        from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosHttpResponseError
    except ImportError:
        print("Error: azure-cosmos package is not installed. Install with 'pip install azure-cosmos azure-identity'.", file=sys.stderr)
        sys.exit(1)

    # Establish client credential
    if use_managed_identity:
        try:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
        except ImportError:
            print("Error: azure-identity package is not installed for Managed Identity.", file=sys.stderr)
            sys.exit(1)
    else:
        if not key:
            print("Error: Account key is required when use_managed_identity is False.", file=sys.stderr)
            sys.exit(1)
        credential = key

    client = CosmosClient(endpoint, credential=credential)

    # 1. Provision Database
    print(f"[*] Provisioning database '{db_name}'...")
    try:
        db = client.create_database_if_not_exists(id=db_name)
        print(f"    -> Database '{db_name}' ready.")
    except Exception as ex:
        print(f"    -> Failed to create/verify database: {ex}", file=sys.stderr)
        sys.exit(1)

    # 2. Provision Containers
    for c in containers:
        c_name = c["name"]
        pk_path = c.get("partitionKey", {}).get("paths", ["/tenant_id"])[0]
        pk = PartitionKey(path=pk_path)
        indexing_policy = c.get("indexingPolicy")
        default_ttl = c.get("defaultTtl", -1)

        print(f"[*] Provisioning container '{c_name}' (Partition Key: {pk_path}, TTL: {default_ttl}s)...")
        try:
            container = db.create_container_if_not_exists(
                id=c_name,
                partition_key=pk,
                indexing_policy=indexing_policy,
                default_ttl=default_ttl if default_ttl != -1 else None,
            )
            print(f"    -> Container '{c_name}' ready.")
        except Exception as ex:
            print(f"    -> Failed to configure container '{c_name}': {ex}", file=sys.stderr)
            sys.exit(1)

    print("\n======================================================================")
    print("SUCCESS: Cosmos DB database and containers successfully provisioned.")
    print("======================================================================")


def main():
    parser = argparse.ArgumentParser(
        description="Provision Azure Cosmos DB for NoSQL database and containers for KPI Intelligence."
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("COSMOS_ENDPOINT", "https://localhost:8081"),
        help="Cosmos DB endpoint URI (default: COSMOS_ENDPOINT env var or emulator)"
    )
    parser.add_argument(
        "--database",
        default=os.getenv("COSMOS_DATABASE", "kpi_intelligence"),
        help="Cosmos DB database name (default: kpi_intelligence)"
    )
    parser.add_argument(
        "--key",
        default=os.getenv("COSMOS_KEY"),
        help="Cosmos DB master key (optional; defaults to Managed Identity if omitted)"
    )
    parser.add_argument(
        "--use-managed-identity",
        action="store_true",
        default=os.getenv("COSMOS_USE_MANAGED_IDENTITY", "true").lower() in ("true", "1", "yes"),
        help="Use Azure Managed Identity (DefaultAzureCredential)"
    )
    parser.add_argument(
        "--spec",
        default=None,
        help="Path to containers JSON specification file"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and print provisioning plan without making live calls"
    )

    args = parser.parse_args()

    # If key was explicitly passed via CLI, disable managed identity unless specified
    use_mi = args.use_managed_identity and not bool(args.key)

    provision_cosmos(
        endpoint=args.endpoint,
        database_name=args.database,
        key=args.key,
        use_managed_identity=use_mi,
        spec_path=args.spec,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
