# KPI Intelligence — Canonical Data Model & Metadata Architecture

## 1. Project Purpose & Scope

**KPI Intelligence** is an enterprise-grade platform designed to solve semantic fragmentation, KPI sprawl, metric duplication, and untracked calculation drift across heterogeneous Business Intelligence (BI) estates.

Large enterprises routinely operate multiple BI tools concurrently, leading to inconsistent metric calculations (e.g. diverging definitions of "Loss Ratio", "Combined Ratio", or "Customer Acquisition Cost"). KPI Intelligence provides:
- **Universal Metadata Extraction**: Dedicated adapters for extracting schemas, formulas, calculations, and visuals across 5 major BI platforms.
- **Canonical Harmonization**: A single, unified PostgreSQL metadata repository (`kpi_intel` schema) preserving native source expressions, ASTs, and dependencies.
- **Local Ontology Bank**: A version-controlled, isolated repository of 550+ curated industry KPIs (Insurance, Financial, and Operational).
- **Hybrid Semantic Mapping**: AI/LLM semantic reasoning with seamless deterministic rule-based fallback and multi-factor cache reuse.
- **Strict Human Governance**: A comprehensive ledger of human approvals, overrides, and mandatory business justifications.
- **KPI Rationalisation**: Discovery of equivalent and redundant metrics across workbooks with non-destructive governance consolidation decisions.

---

## 2. Supported Platforms & Constraints

| Platform | Format Supported | Supported Extraction Capabilities | Constraints & Caveats |
| :--- | :--- | :--- | :--- |
| **Power BI** | **PBIP ONLY** (Power BI Project) | Report definitions (`.pbir`), TMDL tabular models, measures, relationships, partitions, M queries, visual bindings, RLS. | `.pbix` binary files are **strictly unsupported** due to proprietary binary compression. Must be saved as `.pbip`. |
| **Tableau** | **TWB, TDS, TWBX, TDSX** | Workbooks, worksheets, dashboards, calculated fields, LOD expressions, joins, parameters, custom SQL. | External server-published extracts without embedded metadata require catalog sync. |
| **Excel** | **XLSX ONLY** (OpenXML) | Cell formulas, named ranges, tables, PivotTables, pivot caches, conditional formatting, Power Query mashups. | Does not execute spreadsheet calculation engine; cached formula values are treated as snapshots. |
| **ThoughtSpot**| **TML Packages** | Worksheets, tables, columns, answers, liveboards, aggregate formulas, join paths, RLS. | Unresolved external model references are flagged when TML packages are incomplete. |
| **MicroStrategy**| **Dossier & Project Exports**| Dossiers, reports, cubes, metrics, compound metrics, attributes, facts, security filters. | Requires schema XML/JSON export packages. |

---

## 3. Database Requirements

- **PostgreSQL 15 or higher**: Tested and optimized for PostgreSQL 15 and 16.
- **Required Extensions**:
  - `pgcrypto`: High-entropy UUID generation via `gen_random_uuid()`.
  - `pg_trgm`: Trigram indexing (`gin_trgm_ops`) for fuzzy search over canonical names, KPI entries, and justifications.
  - `btree_gist`: Optional for generalized indexing and exclusion constraints.
- **Hardware / Sizing Recommendation**:
  - Minimum: 2 vCPU, 4 GB RAM, 20 GB SSD.
  - Production (10,000+ BI assets): 8 vCPU, 32 GB RAM, Provisioned IOPS SSD storage.

---

## 4. Canonical Repository Architecture

The canonical schema (`kpi_intel`) is structured into **10 cohesive subsystems comprising 61 tables**:

```
Subsystem A: Asset Registry                     (Tables 1 – 4)
Subsystem B: Universal Analytical Objects       (Tables 5 – 14)
Subsystem C: Semantic Models and Calculations   (Tables 15 – 24)
Subsystem D: Filters, Security & Lineage        (Tables 25 – 33)
Subsystem E: Excel-Specific Metadata            (Tables 34 – 39)
Subsystem F: KPI Ontology & Domain Catalog      (Tables 40 – 43)
Subsystem G: KPI Candidates & Mapping Engine    (Tables 44 – 48)
Subsystem H: Human Review & Override Ledger     (Tables 49 – 52)
Subsystem I: KPI Rationalisation                (Tables 53 – 55)
Subsystem J: Operations, Capabilities & Audit   (Tables 56 – 61)
```

---

## 5. File Inventory & Descriptions

All canonical model deliverables are located in `docs/kpi-intelligence-canonical-model/`:

| File Name | Deliverable | Description |
| :--- | :--- | :--- |
| [`README.md`](file:///Users/surya/Documents/Projects/KPI%20Intelligence/docs/kpi-intelligence-canonical-model/README.md) | Deliverable A | Master overview, platform constraints, installation, and operations. |
| [`canonical_schema.sql`](file:///Users/surya/Documents/Projects/KPI%20Intelligence/docs/kpi-intelligence-canonical-model/canonical_schema.sql) | Deliverable B | Production-grade DDL defining all 61 tables, constraints, indexes, triggers, and seed data. |
| [`data_dictionary.md`](file:///Users/surya/Documents/Projects/KPI%20Intelligence/docs/kpi-intelligence-canonical-model/data_dictionary.md) | Deliverable C | Exhaustive field-level specification documenting all 61 tables and every attribute. |
| [`er_diagram.md`](file:///Users/surya/Documents/Projects/KPI%20Intelligence/docs/kpi-intelligence-canonical-model/er_diagram.md) | Deliverable D | Modular Mermaid ER diagrams with cardinality rationales and table coverage map. |
| [`architecture.md`](file:///Users/surya/Documents/Projects/KPI%20Intelligence/docs/kpi-intelligence-canonical-model/architecture.md) | Deliverable E | End-to-end dataflow flowchart, trust boundaries, failure modes, and lifecycle notes. |
| [`table_inventory.csv`](file:///Users/surya/Documents/Projects/KPI%20Intelligence/docs/kpi-intelligence-canonical-model/table_inventory.csv) | Deliverable F | Machine-readable inventory of all 61 tables with keys, foreign keys, and purposes. |
| [`implementation_notes.md`](file:///Users/surya/Documents/Projects/KPI%20Intelligence/docs/kpi-intelligence-canonical-model/implementation_notes.md) | Deliverable G | Engineering guidelines, cache invalidation, indexing, RLS, and security rules. |
| [`scripts/validate_canonical_model.py`](file:///Users/surya/Documents/Projects/KPI%20Intelligence/scripts/validate_canonical_model.py) | Deliverable H | Comprehensive static and live test suite verifying schema completeness and cross-file integrity. |

---

## 6. How to Apply the SQL Schema & Run Migrations

### 6.1 Direct Application via psql
Connect to your PostgreSQL 15+ database and execute:
```bash
psql "postgresql://postgres:password@localhost:5432/kpi_intelligence_db" -f docs/kpi-intelligence-canonical-model/canonical_schema.sql
```

The script runs within a transaction block (`BEGIN ... COMMIT`) with `\set ON_ERROR_STOP on`. If any constraint or type fails, the transaction cleanly rolls back.

### 6.2 Migration Framework Integration
For Flyway or Liquibase environments:
1. Copy `canonical_schema.sql` into your migrations directory:
   ```bash
   mkdir -p migrations
   cp docs/kpi-intelligence-canonical-model/canonical_schema.sql migrations/V001__canonical_kpi_intelligence_schema.sql
   ```
2. Execute migration via Flyway:
   ```bash
   flyway -url="jdbc:postgresql://localhost:5432/kpi_intelligence_db" -user="postgres" -password="password" migrate
   ```

---

## 7. How to Render Mermaid Diagrams

All diagrams in [`architecture.md`](file:///Users/surya/Documents/Projects/KPI%20Intelligence/docs/kpi-intelligence-canonical-model/architecture.md) and [`er_diagram.md`](file:///Users/surya/Documents/Projects/KPI%20Intelligence/docs/kpi-intelligence-canonical-model/er_diagram.md) use standard Mermaid format:
- **In IDE / Markdown Preview**: Native support in GitHub, GitLab, VS Code (Markdown Preview Mermaid Support extension), and Obsidian.
- **CLI Rendering**: Use `@mermaid-js/mermaid-cli`:
  ```bash
  npx @mermaid-js/mermaid-cli -i docs/kpi-intelligence-canonical-model/architecture.md -o architecture.png
  ```

---

## 8. How to Validate the Schema

A comprehensive validation script is provided in `scripts/validate_canonical_model.py`. It executes deep static verification and, if a PostgreSQL connection is supplied, live database validation:

```bash
# Execute static verification (verifies all 61 tables, columns, indexes, seeds, inventory)
python3 scripts/validate_canonical_model.py

# Optional: Execute against a live PostgreSQL 15+ instance
python3 scripts/validate_canonical_model.py --db-url "postgresql://postgres:password@localhost:5432/kpi_intelligence_db"
```

The script verifies:
1. All 61 tables exist in the DDL.
2. All required columns, types, and defaults exist.
3. Foreign key creation order and target resolution.
4. Trigram, B-tree, and full-text search indexes.
5. All 6 business domains are properly seeded.
6. `table_inventory.csv`, `data_dictionary.md`, and `canonical_schema.sql` are 100% synchronized.
7. Active ontology version and approval invariants.

---

## 9. Implementation Phases

1. **Phase 1: Foundation (Current)**
   - Schema creation (`kpi_intel`), 61 tables, extensions, indexes, triggers, and seed data.
   - Validation test suite and canonical technical documentation.
2. **Phase 2: Platform Adapters**
   - Implement extraction adapters for Power BI PBIP and Excel XLSX.
   - Expression normalization and AST parser pipeline (DAX, M, Excel formulas).
3. **Phase 3: Local Ontology & Matching Engine**
   - Ingest 550+ local JSON KPI Ontology Bank.
   - Implement allowlist metadata redaction firewall.
   - Implement LLM semantic matcher with deterministic fallback and multi-factor cache.
4. **Phase 4: Governance & UI**
   - SME approval interface, override capture with mandatory justifications, and audit trails.
5. **Phase 5: KPI Rationalisation**
   - Cross-asset equivalence scanner and consolidation recommendation engine.

---

## 10. Known Limitations

- **PBIP Dependency**: Power BI legacy `.pbix` binary files cannot be parsed directly; users must save assets in Power BI Desktop developer format (`.pbip`).
- **Static Calculation Snapshots**: Excel cell calculations are not evaluated during extraction; the system records formulas and cached values without running the spreadsheet engine.
- **Third-Party Secret References**: If an external database requires cloud IAM authentication (e.g. Azure Managed Identity or AWS IAM), connection references record the resource ARN without secrets.
