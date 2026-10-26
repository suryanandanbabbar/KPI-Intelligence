# KPI Intelligence — Technical Implementation & Engineering Notes

This document provides architectural guidance, operational protocols, database integrity rules, and security enforcement mechanisms for the canonical data model (`kpi_intel`).

---

## 1. Database Integrity Rules & Referential Design

### 1.1 Surrogate Key & Identifier Strategy
- **UUID Primary Keys**: Every table uses a version 4 UUID (`gen_random_uuid()` via PostgreSQL native engine or `pgcrypto`). This guarantees distributed key generation safety across parallel ingestion workers without sequence locks or coordination bottlenecks.
- **Decoupled Identity vs. Natural Naming**: Natural source names (e.g. `[Loss Ratio]`) are never used as primary or foreign keys. Column and table names change frequently across BI releases; surrogate keys isolate downstream lineage from upstream cosmetic refactoring.
- **Timestamps**: All timestamps are typed as `TIMESTAMPTZ` (UTC). Timestamps are populated with `clock_timestamp()` by default to accurately record wall-clock event execution across long-running ingestion transactions.

### 1.2 Referential Actions & Cascade Policies
- **Parent Container Cascades (`ON DELETE CASCADE`)**:
  * Deleting an `asset_version` cascades to all version-contained entities (`analytical_objects`, `reports`, `calculations`, `source_artifacts`, `metadata_lineage_edges`).
  * Deleting a `semantic_model` cascades to its `data_tables`, `calculations`, and `relationships`.
  * Deleting an `analytical_object` cascades to its specific sub-entity (`reports`, `visuals`, `calculations`, etc.) via `ON DELETE CASCADE`.
- **Audit & Governance Preservation (`ON DELETE SET NULL`)**:
  * Deleting a user does not delete approvals or audit history (`approved_by_user_id` is retained).
  * Deleting a target object sets foreign keys to `NULL` in `query_dependencies` and `mapping_evidence` to preserve historical evidence integrity.
- **Circular Foreign Key Management**:
  * `assets.current_version_id` points to `asset_versions.asset_version_id`, while `asset_versions.asset_id` points to `assets.asset_id`.
  * To resolve this cleanly during DDL execution, `assets` is created first without the foreign key constraint, `asset_versions` is created second, and the circular constraint `fk_assets_current_version` is applied via `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ... ON DELETE SET NULL`.

### 1.3 Strict Database Invariants & Partial Indexes
1. **Single Active Ontology Version**:
   - The platform permits multiple historical versions of the 550+ KPI Ontology Bank for auditability and historical replay, but enforces **exactly at most one active version** at any given moment.
   - Enforced in PostgreSQL via a unique partial index:
     ```sql
     CREATE UNIQUE INDEX uq_kpi_ontology_versions_is_active 
     ON kpi_intel.kpi_ontology_versions (is_active) 
     WHERE (is_active = true);
     ```
2. **Single Active Approval per KPI Mapping**:
   - A source candidate mapping can have multiple historical approvals that were subsequently revoked or superseded, but must have **at most one current active approval**:
     ```sql
     CREATE UNIQUE INDEX uq_mapping_approvals_active 
     ON kpi_intel.mapping_approvals (kpi_mapping_id) 
     WHERE (approval_status = 'APPROVED');
     ```
3. **Single Effective Primary Domain**:
   - An analytical object or KPI candidate can belong to secondary domains, but can have **at most one effective primary domain** per asset version:
     ```sql
     CREATE UNIQUE INDEX uq_domain_classifications_primary 
     ON kpi_intel.domain_classifications (asset_version_id, target_object_id) 
     WHERE (is_primary = true AND approval_status <> 'REJECTED');
     ```
4. **Symmetrical KPI Equivalence Prevention**:
   - To prevent duplicate reversed pairs `(A, B)` and `(B, A)` in rationalisation scans:
     ```sql
     CREATE UNIQUE INDEX uq_kpi_equivalence_candidates_pair 
     ON kpi_intel.kpi_equivalence_candidates (
         LEAST(source_kpi_candidate_id, target_kpi_candidate_id),
         GREATEST(source_kpi_candidate_id, target_kpi_candidate_id)
     );
     ```
5. **Handling Nullable Natural Identifiers in Security Principals**:
   - PostgreSQL treats `NULL` values as distinct in standard unique constraints, which can permit unwanted duplicate rows. We enforce uniqueness with two complementary partial indexes:
     ```sql
     CREATE UNIQUE INDEX uq_security_principals_native 
     ON kpi_intel.security_principals (tenant_id, platform, source_native_id) 
     WHERE source_native_id IS NOT NULL;

     CREATE UNIQUE INDEX uq_security_principals_name 
     ON kpi_intel.security_principals (tenant_id, platform, principal_name) 
     WHERE source_native_id IS NULL;
     ```

---

## 2. Multi-Tenant Isolation & Access Control

### 2.1 Tenant Boundary Architecture
- **Logical Tenant Isolation**: Multi-tenancy is enforced at the data layer using `tenant_id` on root entities (`assets`, `security_principals`).
- **PostgreSQL Row-Level Security (RLS)**:
  For multi-tenant SaaS deployments, PostgreSQL RLS policies should be applied on `assets` and propagated via session context variables:
  ```sql
  ALTER TABLE kpi_intel.assets ENABLE ROW LEVEL SECURITY;
  
  CREATE POLICY tenant_isolation_policy ON kpi_intel.assets
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
  ```
- **Connection Pooling & Session Variables**:
  Application connection pools (e.g. PgBouncer or HikariCP) must execute `SET LOCAL app.current_tenant_id = '<tenant-uuid>'` at transaction start.

---

## 3. Sensitive Metadata & Privacy Redaction

### 3.1 Trust Boundary & Zero Business Row Invariant
- **The Zero Business Row Rule**: The platform extracts only schema, formula, lineage, and visual layout metadata. **No business transaction rows, policyholder names, or claim values are ever stored in the database.**
- **Excel Cell Formula Protection**: When scanning Excel sheets, the adapter extracts formulas and number formats. If `cached_value` is retained, it is scrubbed of PII and restricted to numeric evaluation snapshots.

### 3.2 Data Source Redaction Protocol
- In `data_sources`:
  * Connection strings containing passwords, private keys, or SAS tokens are parsed and scrubbed using regex redaction prior to database write.
  * Server IPs and database names are sanitized (`[REDACTED_SERVER]`) unless explicitly whitelisted for enterprise lineage auditing.
  * Embedded SQL queries in Tableau custom SQL or Power Query M queries are filtered to remove inline credentials or hardcoded customer IDs.

### 3.3 LLM Purpose-Built Payload Isolation
Before any metadata is dispatched to the LLM for semantic mapping:
1. The metadata payload is projected through an **Allowlist Compiler**.
2. Only the following fields are transmitted:
   - Candidate canonical name
   - Formula text and normalized AST summary
   - Aggregation type and inferred unit
   - Enclosing report/visual context title
   - Target business domain
3. All internal database UUIDs, user IDs, raw server references, and source file paths are omitted.

---

## 4. Indexing Strategy & Performance Engineering

### 4.1 Access Patterns & Index Matrix
The schema defines 32 specialized indexes addressing critical operational access paths:

| Table | Index Columns | Index Type | Target Query Pattern |
| :--- | :--- | :--- | :--- |
| `assets` | `(tenant_id, platform, asset_name)` | B-Tree | Tenant asset catalog searches and sorting. |
| `asset_versions` | `(asset_id, content_hash)` | B-Tree | Ingestion deduplication; checking if an uploaded package already exists. |
| `asset_versions` | `(asset_id, structure_hash)` | B-Tree | Structural change detection across releases. |
| `analytical_objects` | `(asset_version_id, object_type)`| B-Tree | Filtering all measures, visuals, or tables within an asset version. |
| `analytical_objects` | `(canonical_name)` | GIN (`gin_trgm_ops`) | Fuzzy trigram search for cross-platform object discovery. |
| `calculations` | `(semantic_model_id, calculation_type)` | B-Tree | Retrieving all measures in a tabular model. |
| `calculations` | `(expression_language, expression_parse_status)` | B-Tree | Worker queue queries for expression parsing. |
| `metadata_lineage_edges` | `(source_object_id, edge_type)` | B-Tree | Upstream dependency graph traversal. |
| `metadata_lineage_edges` | `(target_object_id, edge_type)` | B-Tree | Downstream visual impact analysis. |
| `kpi_ontology_entries` | `(ontology_version_id, kpi_code)`| B-Tree | Direct ontology lookup by stable KPI code. |
| `kpi_ontology_entries` | `(kpi_name)` | GIN (`gin_trgm_ops`) | Substring and fuzzy matching against the 550+ KPI bank. |
| `mapping_overrides` | `(justification_hash)` | B-Tree | Fast duplicate justification lookup. |
| `mapping_overrides` | `(normalised_justification)` | GIN (`gin_trgm_ops`) | Fuzzy similarity search across historical justifications. |
| `mapping_overrides` | `to_tsvector('english', override_justification)` | GIN (FTS) | Full-text search for semantic justification retrieval. |

---

## 5. Local Ontology JSON & Database Reconciliation

### 5.1 The Local JSON Storage Mandate
- The KPI Ontology Bank (~550+ industry KPIs) is stored as an internal JSON resource within the application deployment package.
- **NO EXTERNAL HTTP CALLS**: The system never queries an external API or remote service to retrieve the ontology.

### 5.2 Safe Dual-Write & Non-Atomic Synchronization Protocol
File system updates and PostgreSQL transactions cannot participate in a single two-phase commit (2PC) without specialized distributed transaction managers. We implement a **fail-safe staged synchronization protocol**:

```mermaid
sequenceDiagram
    participant User as SME / User
    participant App as Application Service
    participant FS as Local File System (JSON)
    participant DB as PostgreSQL (kpi_intel)

    User->>App: Request Add / Update KPI Entry
    App->>App: 1. Validate against JSON Schema
    App->>App: 2. Compute new content_hash & increment version
    App->>FS: 3. Write to temporary file (ontology.tmp.json)
    App->>FS: 4. Atomic file rename (atomic POSIX rename)
    Note over FS,DB: File is safely updated; now synchronize DB
    App->>DB: 5. BEGIN TRANSACTION
    App->>DB: 6. INSERT new version in kpi_ontology_versions
    App->>DB: 7. INSERT / UPDATE kpi_ontology_entries
    App->>DB: 8. INSERT ontology_change_events (audit log)
    App->>DB: 9. UPDATE kpi_ontology_versions SET is_active = true
    App->>DB: 10. COMMIT TRANSACTION
    DB-->>App: Success
    App-->>User: KPI Added & Synchronized
```

*Recovery Handling*:
- If database write fails after file update, the application recovery service detects that `local_file.content_hash != db_active_version.content_hash` on startup, enters auto-reconciliation, and replays the database transaction from the local JSON file.

---

## 6. Mapping Cache & Fingerprint Invalidation

### 6.1 Multi-Input Fingerprint Composition
A candidate mapping is safely retrieved from cache if and only if **all** contributing factors are identical:
$$\text{Input Fingerprint} = \text{SHA256}\Big(\text{AST Hash} \parallel \text{Lineage Dependencies} \parallel \text{Domain} \parallel \text{Ontology Version} \parallel \text{Engine Version} \parallel \text{Prompt Version} \parallel \text{Active Override Hash}\Big)$$

### 6.2 Invalidation Matrix
| Event | Scope of Invalidation | Strategy |
| :--- | :--- | :--- |
| **Source Formula Modified** | Specific KPI Candidate | Candidate input fingerprint changes; triggers new mapping run for this candidate only. |
| **Ontology Bank Updated** | Specific Business Domain | Only candidates belonging to the affected domain are flagged for selective re-evaluation. |
| **New Override Created** | Candidate & Equivalent KPIs | If a user overrides candidate $A$, any unapproved mappings matching the same fingerprint are updated. Approved mappings are untouched. |
| **LLM Engine / Prompt Upgraded**| Global | Cached results remain valid for approved mappings. Unapproved proposed mappings are re-evaluated against the new engine version. |

---

## 7. Human Governance & Override Hierarchy

### 7.1 Human Approval Invariant
- Automated mapping runs (`LLM` or `DETERMINISTIC`) can propose candidates.
- **Only an authenticated human steward can mark a mapping `APPROVED`.**
- Once a mapping has an active approval in `mapping_approvals`, no background ingestion or automated pipeline is permitted to overwrite or supersede it.

### 7.2 Override Retrieval Priority Pipeline
When a candidate is evaluated, the system queries historical human decisions using this 5-stage priority hierarchy:
1. **Priority 1 (Exact Asset & Object)**: Prior override on the exact same `(asset_id, source_native_id)`.
2. **Priority 2 (Exact Candidate Fingerprint)**: Prior override matching the exact normalized formula and dependency fingerprint.
3. **Priority 3 (High-Confidence Normalised Equivalence)**: Prior override matching identical normalized name, return type, and AST structure.
4. **Priority 4 (Active Approved Mappings)**: Mappings approved by SMEs for identical semantic concepts.
5. **Priority 5 (Justification Search)**: Text similarity search across `normalised_justification` to retrieve contextual decisions.

---

## 8. Database Migrations, Versioning & Operational Maintenance

### 8.1 Repeatable Migration Strategy
- DDL scripts are versioned sequentially:
  `migrations/V001__canonical_kpi_intelligence_schema.sql`, `migrations/V002__...`
- Migrations must be idempotent, wrapping changes in transactions (`BEGIN ... COMMIT`) and using `IF NOT EXISTS` syntax where applicable.

### 8.2 Backup & Disaster Recovery
- **Daily Physical Backups**: Managed via `pg_dump -Fc` or automated WAL archiving (pgBackRest / AWS RDS Automated Backups).
- **Point-In-Time Recovery (PITR)**: Enable continuous archiving of write-ahead logs (WAL) with a minimum 14-day retention window.
- **RTO / RPO Targets**:
  * Recovery Point Objective (RPO): $< 5$ minutes (via WAL streaming).
  * Recovery Time Objective (RTO): $< 30$ minutes.

---

## 9. Production-Readiness Gaps & Future Enhancements

1. **pgvector Integration**: Future versions should integrate the PostgreSQL `pgvector` extension to enable native vector embeddings for semantic KPI similarity search alongside trigram matching.
2. **Distributed AST Parser Microservice**: For massive enterprise PBIP repositories (100,000+ measures), DAX and M syntax parsing should be offloaded from web workers into an asynchronous distributed Celery/RabbitMQ worker pool.
3. **Automated Tenant Sharding**: If metadata volume exceeds 50 million analytical objects, table partitioning by `tenant_id` or Citus-based horizontal sharding should be implemented.
