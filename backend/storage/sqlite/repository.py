"""
KPI Intelligence — Local SQLite Storage Adapter.

Implements IRepository over a local SQLite database for developer testing,
fixture generation, and inspection.
Preserves Cosmos DB document contracts and tenant-isolation invariants.
"""

import os
import json
import sqlite3
import hashlib
import uuid
import re
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone

from backend.contracts.base import CosmosContainer, utc_now_iso
from backend.repository.interfaces import (
    IRepository,
    QuerySpec,
    PagedResult,
    DocumentNotFoundError,
    ConcurrencyConflictError,
    RepositoryError,
)
from backend.repository.context import TenantContext, TenantAccessDeniedError

TENANT_SCOPED_CONTAINERS = {
    CosmosContainer.METADATA_CATALOG,
    CosmosContainer.KPI_GOVERNANCE,
    CosmosContainer.OPERATIONAL_AUDIT,
}
GLOBAL_REFERENCE_CONTAINERS = {
    CosmosContainer.KPI_ONTOLOGY,
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cosmos_documents (
    container_name TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    document_id TEXT NOT NULL,
    tenant_id TEXT,
    document_type TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    etag TEXT NOT NULL,
    document_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (container_name, partition_key, document_id)
);

CREATE INDEX IF NOT EXISTS idx_cosmos_docs_tenant 
ON cosmos_documents (container_name, tenant_id, document_type);

CREATE INDEX IF NOT EXISTS idx_cosmos_docs_type 
ON cosmos_documents (container_name, document_type);

CREATE INDEX IF NOT EXISTS idx_cosmos_docs_partition
ON cosmos_documents (container_name, partition_key);
"""


def compute_etag(payload: Dict[str, Any]) -> str:
    """Computes a deterministic hash-based ETag for a document dictionary."""
    clean = dict(payload)
    clean.pop("_etag", None)
    clean.pop("updated_at", None)
    encoded = json.dumps(clean, sort_keys=True).encode("utf-8")
    return f"\"{hashlib.sha256(encoded).hexdigest()[:16]}\""


class SQLiteRepository(IRepository):
    """
    Local SQLite repository storing canonical Cosmos documents in JSON rows.
    Guarantees parameterized query execution, tenant boundary verification,
    and ETag concurrency control.
    """

    def __init__(self, db_path: str = "local_data/kpi_intelligence.sqlite3"):
        self.db_path = db_path
        self._ensure_db_initialized()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _ensure_db_initialized(self) -> None:
        """Creates directory and schema if not present."""
        dir_name = os.path.dirname(self.db_path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)

        with self._get_connection() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    def reset_database(self) -> None:
        """Clears all records from the local SQLite database."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM cosmos_documents;")
            conn.commit()

    def inspect_counts(self) -> Dict[str, Any]:
        """Returns document counts by container, type, and total."""
        with self._get_connection() as conn:
            cur = conn.execute("SELECT COUNT(*) AS total FROM cosmos_documents;")
            total = cur.fetchone()["total"]

            cur = conn.execute("SELECT container_name, COUNT(*) AS cnt FROM cosmos_documents GROUP BY container_name;")
            by_container = {r["container_name"]: r["cnt"] for r in cur.fetchall()}

            cur = conn.execute("SELECT document_type, COUNT(*) AS cnt FROM cosmos_documents GROUP BY document_type;")
            by_type = {r["document_type"]: r["cnt"] for r in cur.fetchall()}

            return {
                "total_documents": total,
                "by_container": by_container,
                "by_type": by_type,
            }


    def get_item(
        self,
        container: CosmosContainer,
        partition_key: str,
        item_id: str,
        tenant_context: Optional[TenantContext] = None,
    ) -> Optional[Dict[str, Any]]:
        if container in TENANT_SCOPED_CONTAINERS:
            if tenant_context is None:
                raise TenantAccessDeniedError(
                    f"Explicit TenantContext is mandatory for tenant-scoped container '{container.value}'."
                )
            if not tenant_context.is_system:
                if str(partition_key).strip().lower() != str(tenant_context.tenant_id).strip().lower():
                    raise TenantAccessDeniedError(
                        f"Partition key '{partition_key}' does not match tenant context '{tenant_context.tenant_id}'."
                    )

        query = """
            SELECT document_json, tenant_id, etag 
            FROM cosmos_documents 
            WHERE container_name = ? AND partition_key = ? AND document_id = ?
        """
        with self._get_connection() as conn:
            cur = conn.execute(query, (container.value, str(partition_key), str(item_id)))
            row = cur.fetchone()
            if not row:
                return None

            data = json.loads(row["document_json"])
            data["_etag"] = row["etag"]

            # Enforce tenant isolation if tenant context provided
            if tenant_context and container in TENANT_SCOPED_CONTAINERS:
                tenant_context.assert_authorized(data.get("tenant_id"))

            return data

    def upsert_item(
        self,
        container: CosmosContainer,
        partition_key: str,
        item: Dict[str, Any],
        tenant_context: Optional[TenantContext] = None,
        etag: Optional[str] = None,
    ) -> Dict[str, Any]:
        doc_id = str(item.get("id", "")).strip()
        if not doc_id:
            raise ValueError("Document item must contain a non-empty 'id'.")

        doc_type = item.get("doc_type", "unknown")
        schema_version = item.get("schema_version", "2.0.0")
        item_tenant = item.get("tenant_id")

        if container in TENANT_SCOPED_CONTAINERS:
            if tenant_context is None:
                raise TenantAccessDeniedError(
                    f"Explicit TenantContext is mandatory for tenant-scoped container '{container.value}'."
                )
            if not tenant_context.is_system:
                if str(partition_key).strip().lower() != str(tenant_context.tenant_id).strip().lower():
                    raise TenantAccessDeniedError(
                        f"Partition key '{partition_key}' does not match tenant context '{tenant_context.tenant_id}'."
                    )
                tenant_context.assert_authorized(item_tenant)
        elif container in GLOBAL_REFERENCE_CONTAINERS:
            if not tenant_context or not tenant_context.is_system:
                raise TenantAccessDeniedError(
                    f"Mutations on global reference container '{container.value}' require system context."
                )

        # Optimistic concurrency check
        new_etag = compute_etag(item)
        now_str = utc_now_iso()

        with self._get_connection() as conn:
            if etag:
                # Check current etag
                cur = conn.execute(
                    "SELECT etag FROM cosmos_documents WHERE container_name = ? AND partition_key = ? AND document_id = ?",
                    (container.value, str(partition_key), doc_id),
                )
                existing = cur.fetchone()
                if existing and existing["etag"] != etag:
                    raise ConcurrencyConflictError(
                        f"ETag mismatch on item '{doc_id}'. Target had '{existing['etag']}', expected '{etag}'."
                    )

            # Check if creating or updating
            cur = conn.execute(
                "SELECT created_at FROM cosmos_documents WHERE container_name = ? AND partition_key = ? AND document_id = ?",
                (container.value, str(partition_key), doc_id),
            )
            existing_row = cur.fetchone()
            created_at = existing_row["created_at"] if existing_row else item.get("created_at", now_str)

            saved_doc = dict(item)
            saved_doc["created_at"] = created_at
            saved_doc["updated_at"] = now_str
            saved_doc["_etag"] = new_etag

            json_blob = json.dumps(saved_doc)

            conn.execute(
                """
                INSERT INTO cosmos_documents (
                    container_name, partition_key, document_id, tenant_id,
                    document_type, schema_version, etag, document_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (container_name, partition_key, document_id) DO UPDATE SET
                    tenant_id = excluded.tenant_id,
                    document_type = excluded.document_type,
                    schema_version = excluded.schema_version,
                    etag = excluded.etag,
                    document_json = excluded.document_json,
                    updated_at = excluded.updated_at
                """,
                (
                    container.value,
                    str(partition_key),
                    doc_id,
                    str(item_tenant) if item_tenant else None,
                    doc_type,
                    schema_version,
                    new_etag,
                    json_blob,
                    created_at,
                    now_str,
                ),
            )
            conn.commit()

        return saved_doc

    def delete_item(
        self,
        container: CosmosContainer,
        partition_key: str,
        item_id: str,
        tenant_context: Optional[TenantContext] = None,
    ) -> bool:
        if container in TENANT_SCOPED_CONTAINERS:
            if tenant_context is None:
                raise TenantAccessDeniedError(
                    f"Explicit TenantContext is mandatory for tenant-scoped container '{container.value}'."
                )
            if not tenant_context.is_system:
                if str(partition_key).strip().lower() != str(tenant_context.tenant_id).strip().lower():
                    raise TenantAccessDeniedError(
                        f"Partition key '{partition_key}' does not match tenant context '{tenant_context.tenant_id}'."
                    )
        elif container in GLOBAL_REFERENCE_CONTAINERS:
            if not tenant_context or not tenant_context.is_system:
                raise TenantAccessDeniedError(
                    f"Deleting from global reference container '{container.value}' requires system context."
                )

        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT tenant_id FROM cosmos_documents WHERE container_name = ? AND partition_key = ? AND document_id = ?",
                (container.value, str(partition_key), str(item_id)),
            )
            row = cur.fetchone()
            if not row:
                return False

            if tenant_context and container in TENANT_SCOPED_CONTAINERS:
                tenant_context.assert_authorized(row["tenant_id"])

            del_cur = conn.execute(
                "DELETE FROM cosmos_documents WHERE container_name = ? AND partition_key = ? AND document_id = ?",
                (container.value, str(partition_key), str(item_id)),
            )
            conn.commit()
            return del_cur.rowcount > 0

    def query_items(
        self,
        container: CosmosContainer,
        partition_key: Optional[str],
        query_spec: QuerySpec,
        tenant_context: Optional[TenantContext] = None,
        page_size: int = 100,
        continuation_token: Optional[str] = None,
    ) -> PagedResult:
        """
        Translates Cosmos SQL query to SQLite query using json_extract.
        Executes strictly parameterized SQL.
        """
        if container in TENANT_SCOPED_CONTAINERS:
            if tenant_context is None:
                raise TenantAccessDeniedError(
                    f"Explicit TenantContext is mandatory for tenant-scoped container '{container.value}'."
                )
            if not tenant_context.is_system:
                if partition_key is None:
                    partition_key = tenant_context.tenant_id
                elif str(partition_key).strip().lower() != str(tenant_context.tenant_id).strip().lower():
                    raise TenantAccessDeniedError(
                        f"Partition key '{partition_key}' does not match tenant context '{tenant_context.tenant_id}'."
                    )
                for p in query_spec.parameters:
                    if p.get("name") in ("@tenant_id", "@__enforced_tenant_id"):
                        if str(p.get("value", "")).strip().lower() != str(tenant_context.tenant_id).strip().lower():
                            raise TenantAccessDeniedError(
                                f"Query parameter '{p.get('name')}={p.get('value')}' conflicts with tenant context '{tenant_context.tenant_id}'."
                            )

        # Parse continuation token as integer offset
        offset = 0
        if continuation_token:
            try:
                offset = int(continuation_token)
            except ValueError:
                offset = 0

        # Build SQLite WHERE clauses
        where_clauses = ["container_name = ?"]
        sql_params: List[Any] = [container.value]

        if partition_key is not None:
            where_clauses.append("partition_key = ?")
            sql_params.append(str(partition_key))

        # Build parameter mapping from query_spec
        param_dict = {p["name"]: p["value"] for p in query_spec.parameters}

        # Parse conditions from query string
        # Examples:
        # SELECT * FROM c WHERE c.tenant_id = @tenant_id AND c.doc_type = @doc_type
        cosmos_sql = query_spec.query

        # If tenant context is present, always enforce tenant filter on tenant-owned containers
        if container in TENANT_SCOPED_CONTAINERS and tenant_context and not tenant_context.is_system:
            where_clauses.append("tenant_id = ?")
            sql_params.append(tenant_context.tenant_id)

        # Extract conditions from WHERE clause
        where_match = re.search(r'WHERE\s+(.*?)(?:\s+ORDER\s+BY|\s*$)', cosmos_sql, re.IGNORECASE | re.DOTALL)
        if where_match:
            raw_conditions = where_match.group(1).strip()
            # Split by AND
            parts = re.split(r'\s+AND\s+', raw_conditions, flags=re.IGNORECASE)
            for part in parts:
                part = part.strip()
                # Check for c.field = @param
                eq_match = re.search(r'c\.([a-zA-Z0-9_]+)\s*=\s*(@[a-zA-Z0-9_]+)', part)
                if eq_match:
                    field_name = eq_match.group(1)
                    param_name = eq_match.group(2)
                    if param_name in param_dict:
                        param_val = param_dict[param_name]
                        # Don't duplicate tenant_id if already added
                        if field_name == "tenant_id" and tenant_context and not tenant_context.is_system:
                            continue
                        if field_name == "tenant_id":
                            where_clauses.append("tenant_id = ?")
                            sql_params.append(str(param_val))
                        elif field_name == "doc_type":
                            where_clauses.append("document_type = ?")
                            sql_params.append(str(param_val))
                        else:
                            where_clauses.append(f"json_extract(document_json, '$.{field_name}') = ?")
                            sql_params.append(str(param_val) if not isinstance(param_val, bool) else (1 if param_val else 0))

        order_by = "created_at DESC"
        if "ORDER BY" in cosmos_sql.upper():
            order_match = re.search(r'ORDER\s+BY\s+c\.([a-zA-Z0-9_]+)(?:\s+(ASC|DESC))?', cosmos_sql, re.IGNORECASE)
            if order_match:
                ob_field = order_match.group(1)
                ob_dir = order_match.group(2) or "ASC"
                if ob_field in ("created_at", "updated_at"):
                    order_by = f"{ob_field} {ob_dir.upper()}"
                else:
                    order_by = f"json_extract(document_json, '$.{ob_field}') {ob_dir.upper()}"

        final_query = f"""
            SELECT document_json, etag 
            FROM cosmos_documents 
            WHERE {' AND '.join(where_clauses)}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
        """
        sql_params.append(page_size)
        sql_params.append(offset)

        items = []
        try:
            with self._get_connection() as conn:
                cur = conn.execute(final_query, sql_params)
                rows = cur.fetchall()
                for r in rows:
                    item_data = json.loads(r["document_json"])
                    item_data["_etag"] = r["etag"]
                    items.append(item_data)
        except TenantAccessDeniedError:
            raise
        except sqlite3.Error as ex:
            raise RepositoryError(f"SQLite error during query_items: {ex}") from ex

        # Defense-in-depth: assert tenant authorization on every returned document
        if container in TENANT_SCOPED_CONTAINERS and tenant_context and not tenant_context.is_system:
            for item_data in items:
                tenant_context.assert_authorized(item_data.get("tenant_id"))

        # Compute next continuation token
        next_token = str(offset + len(items)) if len(items) == page_size else None
        return PagedResult(items=items, continuation_token=next_token, request_charge=1.0)

    def health_check(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT COUNT(*) AS total_docs FROM cosmos_documents;")
            total_docs = cur.fetchone()["total_docs"]

            cur = conn.execute(
                "SELECT container_name, COUNT(*) AS cnt FROM cosmos_documents GROUP BY container_name;"
            )
            container_counts = {r["container_name"]: r["cnt"] for r in cur.fetchall()}

        return {
            "status": "HEALTHY",
            "backend": "sqlite",
            "db_path": self.db_path,
            "total_documents": total_docs,
            "containers": container_counts,
        }
