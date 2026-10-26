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
  * Deleting an `asset_version` cascades to version-scoped entities (`source_artifacts`, `metadata_lineage_edges`).
  * Deleting a `semantic_model` cascades to its `data_tables`, `calculations`, and `relationships`.
  * Deleting an `analytical_object` cascades to its specific sub-entity (`reports`, `visuals`, `calculations`, etc.) via `ON DELETE CASCADE`.
- **Strict Audit Immutability & Anti-Cascade (`ON DELETE RESTRICT`)**:
  * Deleting an operational `kpi_mappings` row is strictly **prohibited** if audit events exist (`mapping_audit_events.kpi_mapping_id` uses `ON DELETE RESTRICT`).
  * Deleting an ontology version is strictly **prohibited** if ontology change logs exist (`ontology_change_events.ontology_version_id` uses `ON DELETE RESTRICT`).
  * Audit records retain snapshot identifiers (`target_kpi_mapping_id UUID NOT NULL`) ensuring permanent traceability even across lifecycle transitions.
- **Audit & Governance Preservation (`ON DELETE SET NULL`) & Column-Specific Syntax**:
  * Deleting a user does not delete approvals or audit history (`approved_by_user_id` is retained).
  * Deleting a target object sets foreign keys to `NULL` in `query_dependencies` and `mapping_evidence` to preserve historical evidence integrity.
  * **Composite Foreign Keys with Column-Specific `ON DELETE SET NULL` (PostgreSQL 15+)**:
    When a composite foreign key pairs a nullable column with a `NOT NULL` column, standard PostgreSQL `ON DELETE SET NULL` attempts to set *all* referencing columns to NULL, which immediately violates the `NOT NULL` constraint and aborts the transaction. In PostgreSQL 15+, column-specific syntax is utilized to only nullify the nullable referencing column while preserving the immutable parent link:
    - `kpi_mappings`: `FOREIGN KEY (selected_ontology_entry_id, ontology_version_id) REFERENCES kpi_ontology_entries (...) ON DELETE SET NULL (selected_ontology_entry_id)` (preserves `ontology_version_id`).
    - `mapping_approvals`: `FOREIGN KEY (approved_mapping_candidate_id, kpi_mapping_id) REFERENCES kpi_mapping_candidates (...) ON DELETE SET NULL (approved_mapping_candidate_id)` (preserves `kpi_mapping_id`).
    - `mapping_reviews`: `FOREIGN KEY (mapping_candidate_id, kpi_mapping_id) REFERENCES kpi_mapping_candidates (...) ON DELETE SET NULL (mapping_candidate_id)` (preserves `kpi_mapping_id`).
    - `mapping_overrides`: `FOREIGN KEY (mapping_candidate_id, kpi_mapping_id) REFERENCES kpi_mapping_candidates (...) ON DELETE SET NULL (mapping_candidate_id)` (preserves `kpi_mapping_id`).
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

### 2.1 Tenant Boundary Architecture & Trust Model
The canonical model implements defense-in-depth tenant isolation across four distinct layers:

1. **Mandatory Transaction-Local Context Lifecycle & Pool Reuse**:
   - **Mandatory Transaction-Local Setting**: `kpi_intel.set_current_tenant_id(p_tenant_id UUID)` establishes the tenant context scoped strictly to the current database transaction (`set_config('kpi_intel.current_tenant_id', ..., true)`). The application-facing API has no `p_is_local` argument, making session-level state impossible through ordinary operations.
   - **Transaction-Local Clearer**: `kpi_intel.clear_current_tenant_id()` clears the setting within the active transaction scope (`set_config('kpi_intel.current_tenant_id', '', true)`).
   - **Obsolete Overloads Dropped**: Obsolete callable overloads `set_current_tenant_id(UUID, BOOLEAN)` and `clear_current_tenant_id(BOOLEAN)` are explicitly dropped from the schema, preventing callers from passing `false` to request session-level persistence.
   - **Connection Pool Safety (PgBouncer, HikariCP)**: Upon `COMMIT` or `ROLLBACK`, PostgreSQL automatically discards transaction-local configuration parameters. When a connection is returned to the pool or reused for a subsequent request, no leftover tenant context can persist across tenant boundaries.
   - **Missing Context Fails Closed**: `kpi_intel.current_tenant_id()` returns `NULL` if unset or cleared. Under SQL boolean logic, `tenant_id = NULL` evaluates to `NULL` (falsy), immediately blocking all reads and writes across all tenant-scoped tables.
   - **Trust Model & Authorization Boundary**:
     > [!IMPORTANT]
     > A custom PostgreSQL setting is an **authorization context / execution parameter**, NOT an authentication mechanism.
     > Untrusted clients (external end-users, direct web traffic) must NEVER have direct PostgreSQL connection access or permission to invoke `set_current_tenant_id`. The application backend serves as the trusted Policy Enforcement Point (PEP): it authenticates the user (via JWT/OAuth2), verifies tenant authorization, opens a database transaction, and sets the transaction-local tenant context.
   - **Least-Privilege Execution Rights & Search Path**:
     * Execution rights on `current_tenant_id()`, `set_current_tenant_id(UUID)`, and `clear_current_tenant_id()` are explicitly revoked from `PUBLIC` (`REVOKE ALL ON FUNCTION ... FROM PUBLIC`).
     * `kpi_app_user` is granted execution; `kpi_readonly` is granted execution only on `current_tenant_id()`.
     * All context helper functions specify `SECURITY INVOKER SET search_path = pg_catalog, kpi_intel` to eliminate search_path hijacking vulnerabilities.

2. **Complete 61-Table Row-Level Security (RLS) Coverage**:
   All 61 tables in the canonical schema have RLS enabled and explicitly defined:
   - **11 Tenant-Owned Root Tables**: Protected by direct column check `tenant_id = kpi_intel.current_tenant_id()`:
     `assets`, `security_principals`, `asset_versions`, `analytical_objects`, `kpi_candidates`, `kpi_mapping_runs`, `kpi_mappings`, `domain_classifications`, `metadata_field_reviews`, `parser_runs`, `mapping_audit_events`.
   - **44 Tenant-Owned Child Tables**: Protected by parent-derived existence queries (`EXISTS (SELECT 1 FROM parent WHERE parent.tenant_id = kpi_intel.current_tenant_id())`):
     *Subsystem A*: `ingestion_events`, `source_artifacts`.  
     *Subsystem B*: `reports`, `report_pages`, `visuals`, `visual_bindings`, `visual_properties`, `visual_interactions`, `bookmarks`, `report_navigation`.  
     *Subsystem C*: `semantic_models`, `data_tables`, `data_columns`, `calculations`, `relationships`, `model_partitions`, `hierarchies`, `hierarchy_levels`, `parameters`, `named_expressions`.  
     *Subsystem D*: `filters`, `filter_assignments`, `security_roles`, `security_role_filters`, `security_object_permissions`, `data_sources`, `query_dependencies`, `metadata_lineage_edges`.  
     *Subsystem E*: `spreadsheet_cells`, `pivot_caches`, `pivot_tables`, `pivot_field_assignments`, `spreadsheet_objects`, `spreadsheet_rules`.  
     *Subsystem G*: `kpi_mapping_candidates`, `mapping_evidence`.  
     *Subsystem H*: `mapping_reviews`, `mapping_approvals`, `mapping_overrides`.  
     *Subsystem I*: `kpi_equivalence_candidates`, `kpi_rationalisation_decisions`, `rationalisation_evidence`.  
     *Subsystem J*: `extraction_errors`, `object_tags`.  
   - **5 Globally Shared Reference Tables**: Read-only access across all tenants (`FOR SELECT USING (true)`):
     `business_domains`, `visual_types`, `platform_capabilities`, `kpi_ontology_versions`, `kpi_ontology_entries`.
   - **1 System-Owned Operational Table**: Append-only global ledger with read access:
     `ontology_change_events`.

3. **`ENABLE` vs. `FORCE ROW LEVEL SECURITY` & Privileged Role Bypass**:
   - `ENABLE ROW LEVEL SECURITY`: Applies RLS policies to normal database roles, but table owners bypass policies by default.
   - `FORCE ROW LEVEL SECURITY`: Enforces RLS policies unconditionally, even when a query is executed by the table owner. All 55 tenant-scoped tables are configured with `FORCE ROW LEVEL SECURITY`.
   - **Superuser and `BYPASSRLS` Bypass Rule**: In PostgreSQL, superuser roles and roles created with the `BYPASSRLS` attribute *always bypass RLS policies unconditionally*. Therefore, application connection pools must connect using a dedicated non-superuser role (`kpi_app_user`) created with `NOSUPERUSER NOBYPASSRLS`.

4. **Application Roles & Least-Privilege Grants**:
   - **`kpi_app_user`**: Standard application connection pool role.
     * Granted `USAGE` on schema `kpi_intel`.
     * Granted `SELECT, INSERT, UPDATE, DELETE` on operational tables.
     * **Strictly restricted on audit tables**: `REVOKE UPDATE, DELETE, TRUNCATE ON mapping_audit_events, ontology_change_events FROM kpi_app_user, PUBLIC;` and `GRANT SELECT, INSERT ON mapping_audit_events, ontology_change_events TO kpi_app_user;`.
   - **`kpi_readonly`**: Reporting and analytics role with `SELECT` permissions only.

5. **Composite Foreign Key Boundary Invariants**:
   Multi-column foreign keys ensure cross-tenant referencing is physically rejected by the database constraint engine:
   - `(asset_id, tenant_id) REFERENCES assets(asset_id, tenant_id)`
   - `(asset_version_id, tenant_id) REFERENCES asset_versions(asset_version_id, tenant_id)`
   - `(source_object_id, asset_version_id) REFERENCES analytical_objects(object_id, asset_version_id)`
   - `(kpi_candidate_id, asset_version_id) REFERENCES kpi_candidates(kpi_candidate_id, asset_version_id)`
   - `(mapping_candidate_id, kpi_mapping_id) REFERENCES kpi_mapping_candidates(mapping_candidate_id, kpi_mapping_id)`
   - `(approved_mapping_candidate_id, kpi_mapping_id) REFERENCES kpi_mapping_candidates(mapping_candidate_id, kpi_mapping_id)`

### 2.2 Immutable Governance & Integrity Triggers

1. **`trg_protect_human_approval` (Comprehensive Transition Rules)**:
   - **Prohibited Automated Actions**: Automated engines (`decision_source IN ('LLM', 'DETERMINISTIC')`) are strictly prohibited from:
     * Overwriting or mutating any mapping where `OLD.decision_source = 'HUMAN'` or `OLD.mapping_status = 'APPROVED'` (raises SQLSTATE `42501`).
     * Changing `selected_ontology_entry_id` of an approved mapping directly.
     * Resetting `mapping_status` from `APPROVED` back to `PROPOSED` or `UNMAPPED` (raises SQLSTATE `55000`).
     * Mutating structural relational keys: `kpi_candidate_id`, `asset_version_id`, `ontology_version_id`, or `created_at` (raises SQLSTATE `42501`).
   - **Permitted Human Transitions**: Only an authenticated human steward (`decision_source = 'HUMAN'`) can transition an approved mapping to `SUPERSEDED`, `REJECTED`, or `OVERRIDDEN`. The prior approval row in `mapping_approvals` is marked `SUPERSEDED` or `REVOKED` with `revoked_at` and `revocation_reason`, and a new audit event is logged.

2. **`trg_mapping_audit_immutable` & `trg_ontology_audit_immutable`**:
   - Attached to `mapping_audit_events` and `ontology_change_events`.
   - Prohibits all `UPDATE` and `DELETE` operations on audit tables using standard SQLSTATE `42501` (`insufficient_privilege`), guaranteeing tamper-proof, append-only ledgers.

3. **`trg_prevent_override_cycle`**:
   - Attached to `mapping_overrides`.
   - Recursively verifies the `supersedes_override_id` chain to prevent cyclic or self-referential override loops (raises SQLSTATE `23514`).

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

### 5.3 JSONB Semantic Preservation vs. Raw Byte-for-Byte Serialization
- **Semantic Preservation Guarantee**: The canonical model stores the raw original JSON entry in `kpi_ontology_entries.ontology_payload` typed as `JSONB`. PostgreSQL's `JSONB` data type guarantees **100% semantic fidelity**:
  * Scalar data types (integers, floats, strings, booleans, nulls) are preserved without coercion.
  * Unicode and special characters are preserved verbatim.
  * Complex nested structures, arrays, and multi-team enrichment objects retain complete structural hierarchy.
- **Byte Serialization vs. Semantic Storage**:
  * `JSONB` parses JSON into a decomposed binary format: it strips insignificant source whitespace, normalizes object key ordering (by length and binary value), and deduplicates duplicate dictionary keys (keeping the last value per JSON specification).
  * Consequently, `JSONB` guarantees semantic data preservation, NOT identical byte-for-byte serialization or raw whitespace formatting. For metadata governance and analytical search, binary semantic storage is superior, performant, and indexing-capable.
- **Comprehensive Release Diff Detection**:
  The `KPIVersionDiffDetector` engine tracks semantic evolution between ontology releases across all 11 materially relevant business fields:
  1. `source_sector` (`sector`)
  2. `source_subdomain` (`subdomain`)
  3. `source_line_of_business` (`line_of_business`)
  4. `kpi_type` (`kpi_type`)
  5. `business_domain` (`domain`)
  6. `source_status` & `is_active_sector` (`status`, `is_active_sector`)
  7. `valid_dimensions`
  8. `synonyms` (`aliases`)
  9. `formula` (top-level or enrichment calculation)
  10. `definition`
  11. `enrichments` (ordered team-level metadata, field sources, and extra properties)

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

### 8.1 Dual Execution Contract: Flyway vs. Standalone Rerunnability
The migration suite adheres to two distinct but complementary operational contracts:
1. **Flyway Managed CI/CD Deployments (Exact-Once Contract)**:
   - In production and deployment pipelines, Flyway manages migration versioning (`V001__...`, `V002__...`), executing each script strictly once per database instance.
   - Execution status, applied timestamps, and SHA-256 checksums are immutably recorded in `flyway_schema_history`.
2. **Standalone & Sandbox Rerunnability (Idempotent DDL Contract)**:
   - For developer environments, test harness execution, retry runners, and partial-failure recovery, migration scripts must be safely rerunnable without error.
   - All DDL statements utilize idempotent patterns:
     * Columns: `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...`
     * Constraints: `ALTER TABLE ... DROP CONSTRAINT IF EXISTS ... ADD CONSTRAINT ...`
     * Functions: `CREATE OR REPLACE FUNCTION ...`
     * Triggers: `DROP TRIGGER IF EXISTS ... CREATE TRIGGER ...`
     * Policies: `DROP POLICY IF EXISTS ... CREATE POLICY ...`
     * Roles: `DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles ...) THEN CREATE ROLE ...; END IF; END $$;`

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
