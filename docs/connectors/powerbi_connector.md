# KPI Intelligence — Power BI PBIP Metadata Connector

## 1. Architectural Overview & Design Principles

The Power BI PBIP Metadata Connector is the primary production BI platform connector for the KPI Intelligence platform. It provides automated metadata extraction, normalization, lineage tracking, and persistence from native Power BI Project (`.pbip`) directories into the hardened 61-table PostgreSQL canonical schema (`kpi_intel`).

```
                                  POWER BI PROJECT (.pbip)
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       ▼                                           ▼
             *.Report / definition.pbir                  *.SemanticModel / definition
             report.json, CustomVisuals                  model.tmdl, tables/*.tmdl, etc.
                       │                                           │
                       ▼                                           ▼
             ┌───────────────────┐                       ┌───────────────────┐
             │   Report Parser   │                       │    TMDL Parser    │
             │   (JSONC Engine)  │                       │   (Lexer/Parser)  │
             └─────────┬─────────┘                       └─────────┬─────────┘
                       │                                           │
                       └─────────────────────┬─────────────────────┘
                                             │
                                             ▼
                               ┌───────────────────────────┐
                               │   Canonical Normalizer    │
                               │   - Deterministic UUIDs   │
                               │   - Identity Hierarchy    │
                               │   - DAX & Join Lineage    │
                               └─────────────┬─────────────┘
                                             │
                                             ▼
                               ┌───────────────────────────┐
                               │     Ingestion Hasher      │
                               │  Raw, Struct, Meta Hashes │
                               └─────────────┬─────────────┘
                                             │
                                             ▼
                               ┌───────────────────────────┐
                               │   Persistence Service     │
                               │  - Transaction Tenancy    │
                               │  - Topological Order      │
                               │  - Upsert (ON CONFLICT)   │
                               └─────────────┬─────────────┘
                                             │
                                             ▼
                              CANONICAL POSTGRESQL (kpi_intel)
```

### Key Architectural Tenets
1. **Extensible Connector Architecture**: Built on `BaseConnector` and `ConnectorRegistry`. Power BI PBIP is the active functional implementation, while Tableau, Excel, ThoughtSpot, and MicroStrategy are registered with explicit declared capabilities and unsupported stubs, enabling modular additions without modifying ingestion pipelines.
2. **Strict Ground-Truth Conformance**: Extraction parsers directly interpret Power BI desktop metadata formats (TMDL specification, PBIR, and Fabric PBIP project layouts).
3. **Transaction-Local Tenancy & Fail-Closed RLS**: Every database write executes `SELECT kpi_intel.set_current_tenant_id(:tenant_id)` within the transaction block. Missing or invalid tenant context fails closed.
4. **Deterministic Identity & Idempotence**: All primary keys for canonical analytical objects are generated via UUIDv5 (`uuid.uuid5(namespace, key)`), guaranteeing repeatable, collision-free identities across re-ingestion runs.
5. **Fine-Grained Lineage Tracing**: Direct parsing of DAX formulas identifies column and measure dependencies, mapping them as directed lineage graph edges alongside relationship joins and visual data bindings.

---

## 2. Parsing Engine Specification

### 2.1 JSONC Parser (`backend.connectors.powerbi.jsonc_parser`)
Power BI project configurations (`.pbip`, `.pbir`, `.pbism`, `report.json`, `diagramLayout.json`) frequently contain JavaScript-style single-line (`//`) and multi-line (`/* ... */`) comments, as well as trailing commas in JSON arrays and objects.

The parser implements a character-level finite state machine that:
* Preserves comment markers inside quoted string literals (preventing corruption of URLs such as `http://example.com/api//v1` or escaped quotes `\"`).
* Strips comments outside string literals while preserving newlines for accurate error line reporting.
* Removes trailing commas before `}` and `]` outside string literals.
* Handles UTF-8 Byte Order Marks (`\ufeff`) seamlessly.

### 2.2 TMDL Parser (`backend.connectors.powerbi.tmdl_parser`)
The Tabular Model Definition Language (TMDL) parser processes hierarchical indentation-delimited metadata files under `definition/`:

| TMDL File / Folder | Canonical Entity Extracted | Key Grammar Rules Handled |
| :--- | :--- | :--- |
| `model.tmdl` | `semantic_models` | Model culture, default data source versions, implicit measure flags, annotations |
| `database.tmdl` | `semantic_models` | Database compatibility level (e.g., `1601`) |
| `relationships.tmdl` | `relationships`, `metadata_lineage_edges` | `fromColumn`, `toColumn`, cardinality (`oneToMany`, etc.), `crossFilteringBehavior`, active flags |
| `expressions.tmdl` | `named_expressions` | Triple-backtick multiline blocks (`` ``` ``) containing Power Query M function definitions |
| `tables/*.tmdl` | `data_tables`, `data_columns`, `calculations`, `model_partitions` | Table declarations, physical columns, calculated columns (`column Col = <DAX>`), measures (`measure M = <DAX>`), calculation groups & calculation items (`calculationItem CI = <DAX>`), formatStringDefinition, partitions (`m` and `calculated`), format strings, lineageTags, annotations |
| `cultures/*.tmdl` | `source_metadata` | Multiline linguistic metadata JSON blocks |

### 2.3 PBIR Report Parser (`backend.connectors.powerbi.report_parser`)
Parses `.Report` metadata folders:
* `definition.pbir`: Resolves PBIR format version (`4.0`) and relative dataset reference (`datasetReference.byPath.path`).
* `report.json`: Extracts report sections (pages), dimensions, display options, embedded stringified JSON configurations, bookmarks, and visual container declarations.
* `CustomVisuals/`: Extracts manifest packages (`package.json`, `pbiviz.json`), custom visual GUIDs, display names, and vendor metadata.

---

## 3. Canonical Normalization Mapping Matrix

The normalizer transforms extracted ASTs into the 61-table canonical schema:

| Subsystem | Canonical Table | Power BI Source Element | Canonical Fields Mapped |
| :--- | :--- | :--- | :--- |
| **A. Asset Registry** | `assets` | `.pbip` file & project directory | `asset_id` (UUIDv5), `tenant_id`, `platform='POWER_BI'`, `asset_type='REPORT'`, `asset_name`, `source_native_path`, `current_version_id` |
| | `asset_versions` | Release snapshot | `asset_version_id` (UUIDv5), `version_number`, `content_hash`, `raw_content_hash`, `structure_hash`, `metadata_hash`, `extraction_status` |
| | `source_artifacts` | Individual bundle files | `source_artifact_id`, `relative_path`, `artifact_type`, `content_hash`, `size_bytes`, `is_supported` |
| **B. Analytical Objects** | `analytical_objects` | Polymorphic identity registry | Universal registry row for every semantic model, table, column, calculation, relationship, report, page, visual, bookmark, and named expression. Enforces `parent_object_id` hierarchy. |
| | `reports` | `.Report` folder | `report_id`, `object_id`, `report_type='POWER_BI_PBIP'`, `page_count`, `visual_count`, `report_configuration`, `owner_id`, `owner_name`, `last_accessed_at`, `lifecycle_status` |
| | `report_pages` | `report.json` sections | `page_id`, `report_id`, `object_id`, `source_native_id`, `page_name`, `page_order`, `page_properties` |
| | `visuals` | `visualContainers` | `visual_id`, `page_id`, `object_id`, `visual_type`, `visual_title`, `position_x`, `position_y`, `width`, `height`, `z_order` |
| | `visual_bindings` | Visual projections | `visual_binding_id`, `visual_id`, `object_id` (bound column/calc), `binding_role`, `binding_order` |
| | `bookmarks` | `report.json` bookmarks | `bookmark_id`, `object_id`, `source_native_id`, `bookmark_name`, `bookmark_state` |
| **C. Semantic Models** | `semantic_models` | `model.tmdl`, `database.tmdl` | `semantic_model_id`, `object_id`, `model_name`, `model_type='TABULAR_TMDL'`, `compatibility_level`, `model_definition` |
| | `data_tables` | `tables/*.tmdl` | `data_table_id`, `object_id`, `semantic_model_id`, `table_name`, `table_type` (`PHYSICAL`, `CALCULATED`, `CALCULATION_GROUP`, `INFO_VIEW`), `storage_mode` |
| | `data_columns` | Table column definitions | `data_column_id`, `object_id`, `data_table_id`, `column_name`, `data_type`, `source_data_type`, `is_calculated`, `summarize_by`, `format_string` |
| | `calculations` | Table measures, calc columns, calc items | `calculation_id`, `object_id`, `semantic_model_id`, `data_table_id`, `calculation_name`, `calculation_type` (`MEASURE`, `CALCULATED_COLUMN`, `CALCULATION_ITEM`), `expression_language='DAX'`, `expression_text`, `format_string` |
| | `relationships` | `relationships.tmdl` | `relationship_id`, `object_id`, `from_table_id`, `to_table_id`, `from_object_id`, `to_object_id`, `cardinality`, `is_active`, `cross_filter_direction` |
| | `model_partitions` | Table partitions | `model_partition_id`, `semantic_model_id`, `partition_name`, `source_type` (`M`/`DAX`), `expression_text`, `mode` |
| | `named_expressions` | `expressions.tmdl` | `named_expression_id`, `object_id`, `expression_name`, `expression_language='M'`, `expression_text`, `scope='MODEL'` |
| **D. Lineage** | `metadata_lineage_edges` | DAX formulas, joins, visual bindings | `source_object_id`, `target_object_id`, `edge_type` (`MEASURE_DEPENDENCY`, `RELATIONSHIP_JOIN`, `VISUAL_DATA_BINDING`), `derivation_method` (`PARSED`, `SOURCE_DECLARED`), `confidence_score=1.0` |
| **J. Operations** | `parser_runs` | Execution audit | `parser_run_id`, `asset_version_id`, `tenant_id`, `platform='POWER_BI'`, `parser_name`, `run_status`, `objects_extracted`, `warnings_count`, `errors_count` |
| | `extraction_errors` | Extraction diagnostics | `extraction_error_id`, `parser_run_id`, `severity`, `error_code`, `error_message`, `is_recoverable` |
| | `platform_capabilities` | Supported platform matrix | Declared capabilities for `POWER_BI` across TMDL, DAX, relationships, M expressions, bookmarks, and visual bindings. |

---

### 3.1 Dashboard Ownership & Last-Access Analysis

#### Authoritative Source Distinction: Desktop PBIP vs. Runtime Telemetry
Power BI Project (`.pbip`) files are developer desktop project artifacts designed for local authoring and Git version control. They contain report presentation layout (`report.json`), canvas options, theme references, and tabular model scripts (`definition/*.tmdl`).

* **Absence of Runtime Access Logs in PBIP**: Desktop PBIP repositories do **not** record report view events, user interaction logs, or consumer access timestamps. Runtime telemetry is created only when reports are published to and accessed within the Power BI Service or Fabric workspace.
* **Authoritative External System of Record**: The authoritative sources for Power BI report access events are:
  1. **Power BI Service Activity Events API**: `GET https://api.powerbi.com/v1.0/myorg/admin/activityevents?startDateTime='...'&endDateTime='...'` (tracks `ViewReport`, `ExportArtifact`, `DeleteReport` events by user UPN/Object ID).
  2. **Microsoft 365 Unified Audit Log (UAL)**: Retrieved via `Search-UnifiedAuditLog -RecordType PowerBIAudit` or the Microsoft Graph Management API.
* **Anti-Pattern Prohibitions**:
  - The connector **never** synthesizes `last_accessed_at` from filesystem timestamps (`mtime`, `ctime`), Git commit timestamps, or ingestion run timestamps.
  - The connector **never** infers `owner_id` from local OS filesystem file ownership or Git committer identity.
* **Normalization & Persistence Contract**:
  - When authoritative owner/access attributes are absent in the PBIP source, the normalizer populates `owner_id = NULL`, `owner_name = NULL`, and `last_accessed_at = NULL`.
  - Under the canonical classification rule, an unowned report evaluates to `lifecycle_status = 'ORPHANED'`.
  - On re-ingestion, SQL `ON CONFLICT (object_id) DO UPDATE` applies `COALESCE(EXCLUDED.owner_id, reports.owner_id)` and `COALESCE(EXCLUDED.last_accessed_at, reports.last_accessed_at)`, ensuring that existing verified ownership or access data populated via service APIs or administrative review is preserved idempotently.

---

## 4. Verification Against Reference Power BI Project

The connector was executed and verified against the actual reference Power BI project located at `reference/reference.pbip`:

```
reference/
├── reference.pbip
├── reference.Report/
│   ├── definition.pbir
│   ├── report.json
│   ├── StaticResources/
│   └── CustomVisuals/
└── reference.SemanticModel/
    ├── definition.pbism
    ├── diagramLayout.json
    ├── DAXQueries/
    └── definition/
        ├── database.tmdl
        ├── model.tmdl
        ├── relationships.tmdl
        ├── expressions.tmdl
        ├── cultures/nl-NL.tmdl
        └── tables/*.tmdl (15 tables)
```

### Verified Extraction & Normalization Metrics

| Canonical Metric | Verified Count | Notes & Highlights |
| :--- | :---: | :--- |
| **Source Artifacts** | **39** | Cataloged across `.pbip`, `.pbir`, `.pbism`, `.tmdl`, `.json`, `.dax`, `.pbiviz.json` |
| **Analytical Objects** | **251** | Universal polymorphic registry entries with strict topological parentage |
| **Semantic Models** | **1** | Model `Model` (Compatibility Level `1601`, Culture `nl-NL`) |
| **Data Tables** | **15** | Physical tables (`verkoop`, `produkt`, `klant`, `categorie`), Calculated tables (`_Field_param_product`, `_INFO_*`), Date tables (`Datum tabel`, `Invoked Function`), Calculation Groups (`Calc group Time intelligence`), Layout tables (`_Measures_base`, `_Measures_layout`, `_Measures_DAX`) |
| **Data Columns** | **208** | Physical and calculated columns across all 15 tables |
| **Calculations** | **16** | 8 Measures (`Omzet`, `# verkopen`, `avg verkopen`, `# bestellingen`, `Hide visuals *`), 6 Calculation Items (`Waarde`, `MTD maar niet voor avg verkopen`, `YTD`, `LASTDATE`, `Moving average`, `Vorige maand`), 2 Calculated Columns (`verkoop[Prijs product]`, `produkt[j]`) |
| **Relationships** | **4** | Validated foreign key joins (`verkoop.klantkey -> klant.key`, `verkoop.productkey -> produkt.key`, `produkt.categoriekey -> categorie.key`, `verkoop.orderdate -> Datum tabel.Date`) |
| **Model Partitions** | **14** | M partitions (`mode: import`) and calculated partitions |
| **Named Expressions** | **1** | `Query1` Power Query M date table generator (17,125 characters) |
| **Reports** | **1** | PBIR Version 4.0, Theme `City_Park37178596000909025.json` |
| **Report Pages** | **1** | `Page 1` (ID `044f6210ac66344853be`, 1280x720) |
| **Bookmarks** | **4** | `Alleen grafiek`, `Alles`, `Met kleine`, `Zonder kliene` |
| **Metadata Lineage Edges** | **22** | 4 `RELATIONSHIP_JOIN` + 18 `MEASURE_DEPENDENCY` parsed from DAX expressions |
| **Generated SQL Statements** | **656** | Transaction-local tenant setter + topological inserts wrapped in `BEGIN ... COMMIT` |

---

## 5. Tenancy, Security, and Persistence Guarantees

### 5.1 Mandatory Transaction-Local Tenant Context
The persistence engine enforces that every transaction sets the tenant context before any tenant-scoped operations:
```sql
BEGIN;
SELECT kpi_intel.set_current_tenant_id('11111111-1111-1111-1111-111111111111'::uuid);

-- All subsequent INSERT statements include matching tenant_id
INSERT INTO kpi_intel.assets (asset_id, tenant_id, ...) VALUES (...);
...
COMMIT;
```
If a query runs without tenant context or if a tenant mismatch occurs, PostgreSQL row-level security (`FORCE ROW LEVEL SECURITY`) rejects the operation.

### 5.2 Topological Dependency Ordering
To prevent self-referential foreign key constraint violations on `analytical_objects.parent_object_id`, analytical objects are sorted using a directed dependency graph:
1. Root objects (`parent_object_id IS NULL`: `SEMANTIC_MODEL`, `REPORT`)
2. Model-level objects (`DATA_TABLE`, `REPORT_PAGE`, `BOOKMARK`, `RELATIONSHIP`, `NAMED_EXPRESSION`)
3. Table-level objects (`DATA_COLUMN`, `CALCULATION` measures/items, `VISUAL`)
4. Column-level objects (calculated column calculations)
5. Visual bindings and lineage edges

---

## 6. CLI Usage Guide

The CLI entrypoint is located at `scripts/ingest_powerbi.py`:

```bash
# Basic ingestion in dry-run mode (declarative SQL validation)
python3 scripts/ingest_powerbi.py --source reference --dry-run

# Ingest with explicit tenant UUID and export compiled SQL and JSON
python3 scripts/ingest_powerbi.py \
  --source reference \
  --tenant-id "a0000000-0000-0000-0000-000000000001" \
  --output-sql "dist/ingest_reference.sql" \
  --output-json "dist/ingest_reference.json"

# Ingest directly into live PostgreSQL database
python3 scripts/ingest_powerbi.py \
  --source reference \
  --tenant-id "a0000000-0000-0000-0000-000000000001" \
  --db-url "postgresql://kpi_app_user:password@localhost:5432/kpi_intelligence"
```

### CLI Command Options
* `--source`: Path to `.pbip` file or project directory (default: `reference`).
* `--tenant-id`: Tenant UUID for row-level security isolation (default: `11111111-1111-1111-1111-111111111111`).
* `--db-url`: PostgreSQL connection URL (or set `DATABASE_URL` environment variable).
* `--version-number`: Version sequence number for this asset snapshot (default: `1`).
* `--output-sql`: File path to write the compiled transactional SQL statements.
* `--output-json`: File path to write the normalized ingestion summary JSON.
* `--dry-run`: Parse and validate without executing live database modifications.

---

## 7. Automated Test Suite Summary

The Power BI connector is validated by 31 dedicated unit and integration tests across 6 suites:

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

* `tests/test_jsonc_parser.py`: 7 tests verifying comment stripping, trailing comma elimination, URL preservation, and string escape handling.
* `tests/test_tmdl_parser.py`: 7 tests verifying table definitions, calculated columns, calculation groups & items, relationships, multiline backticks, and identifier unquoting.
* `tests/test_pbip_discovery.py`: 5 tests verifying directory discovery, file discovery, path traversal rejection, and artifact classification.
* `tests/test_powerbi_normalizer.py`: 6 tests verifying deterministic UUID generation, object hierarchy, calculation types, relationships, lineage edge extraction, and audit runs.
* `tests/test_powerbi_persistence.py`: 3 tests verifying topological sorting, transactional SQL structure, tenant setter statements, and declarative execution stats.
* `tests/test_powerbi_end_to_end.py`: 3 tests verifying central registry integration, complete end-to-end extraction against the reference project, and unsupported platform rejection.

All 31 tests pass cleanly alongside the existing 36 schema checks, 12 schema integrity tests, 19 KPI Bank tests, and 24 database integration tests.
