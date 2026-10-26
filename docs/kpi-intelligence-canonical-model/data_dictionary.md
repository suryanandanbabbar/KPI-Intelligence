# KPI Intelligence — Canonical Data Dictionary

## 1. Overview & Architectural Conventions

This data dictionary provides the exhaustive technical, structural, semantic, and security specification for all **61 tables** in the `kpi_intel` canonical metadata schema (PostgreSQL 15+).

### Universal Classification Legend
Every field is classified into one of five architectural tiers:
- **`Source-Native`**: Extracted directly from source files (PBIP, TWB/TDS, XLSX, TML, MSTR) without alterations.
- **`Canonical`**: Normalised representation harmonised across all five platforms.
- **`Inferred`**: Derived by parsing ASTs, dependency graphs, or heuristics.
- **`Operational`**: System telemetry, hashes, version numbers, parser diagnostics, and execution states.
- **`Governance`**: Human approvals, overrides, user reviews, rationalisation choices, and audit logs.

### Security & Privacy Rules
- **Zero Raw Business Data Rows**: No table contains customer records, transactional balances, claim details, or row data.
- **Credential Redaction**: Connection strings, passwords, and tokens are strictly scrubbed before persistence.
- **LLM Privacy Boundary**: The LLM receives only allowlisted metadata projections (names, formulas, domain, units).

---

# Subsystem A: Asset Registry

### 1. `assets`
- **Purpose**: Represents the logical analytical asset (workbook, PBIP project, dossier, liveboard) independently of individual file uploads.
- **Data Grain**: One record per logical BI asset within a tenant boundary.
- **Primary Key**: `asset_id` (UUID).
- **Foreign Keys**: `current_version_id` references `asset_versions(asset_version_id)` ON DELETE SET NULL.
- **Populating Platforms**: All (Power BI, Tableau, Excel, ThoughtSpot, MicroStrategy).
- **Security / Redaction**: `tenant_id` scopes row-level multi-tenant isolation. No secrets persisted.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning | Example Values |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `asset_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Unique canonical identifier for the logical asset. | `c1d2e3f4-...` |
| `tenant_id` | UUID | No | None | None | Governance | Tenant boundary identifier for multi-tenant isolation. | `11111111-...` |
| `platform` | TEXT | No | None | CHECK in ('POWER_BI', 'TABLEAU', 'EXCEL', 'THOUGHTSPOT', 'MICROSTRATEGY') | Canonical | Originating Business Intelligence platform. | `'POWER_BI'` |
| `asset_type` | TEXT | No | None | None | Canonical | Asset category (e.g. `WORKBOOK`, `REPORT_PACKAGE`, `DOSSIER`). | `'PBIP_PROJECT'` |
| `asset_name` | TEXT | No | None | None | Canonical | Human-readable logical name of the asset. | `'Underwriting Performance'` |
| `asset_description` | TEXT | Yes | None | None | Canonical | Description extracted from source metadata or catalog. | `'Executive UW portfolio'` |
| `source_native_id` | TEXT | Yes | None | None | Source-Native | Platform-native internal unique ID if available. | `'uw_perf_v2_guid'` |
| `source_native_path`| TEXT | Yes | None | None | Source-Native | Original file or repository path at extraction time. | `'/finance/reports/uw.pbip'` |
| `source_version` | TEXT | Yes | None | None | Source-Native | Platform version string that generated the file. | `'2.128.751.0'` |
| `created_at_source` | TIMESTAMPTZ | Yes | None | None | Source-Native | Timestamp when asset was originally authored at source. | `'2024-03-01 10:00:00Z'` |
| `modified_at_source`| TIMESTAMPTZ | Yes | None | None | Source-Native | Timestamp of last modification recorded in source file. | `'2024-03-15 14:22:10Z'` |
| `first_ingested_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Timestamp when this asset was first loaded into platform. | `'2024-03-16 08:00:00Z'` |
| `last_ingested_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Timestamp of most recent ingestion attempt. | `'2024-03-20 09:30:00Z'` |
| `current_version_id`| UUID | Yes | None | FK -> `asset_versions` | Canonical | Pointer to active head version. | `v1a2b3c4-...` |
| `lifecycle_status` | TEXT | No | `'ACTIVE'` | CHECK in ('ACTIVE', 'ARCHIVED', 'DELETED', 'SUPERSEDED') | Governance | Lifecycle status of asset. | `'ACTIVE'` |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Database row creation timestamp. | `'2024-03-16 08:00:00Z'` |
| `updated_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Maintained by `set_updated_at()` trigger. | `'2024-03-20 09:30:00Z'` |

---

### 2. `asset_versions`
- **Purpose**: Immutable snapshot representing a specific content and metadata state of an asset.
- **Data Grain**: One record per distinct version/content hash of an asset within a tenant boundary.
- **Primary Key**: `asset_version_id` (UUID).
- **Foreign Keys**: `(asset_id, tenant_id)` references `assets(asset_id, tenant_id)` ON DELETE CASCADE.
- **Populating Platforms**: All.
- **Security / Redaction**: Row Level Security (RLS) enabled. Manifest stores file listings only; no file contents or credentials.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning | Example Values |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `asset_version_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Unique identifier for the immutable asset version. | `a01b02c0-...` |
| `asset_id` | UUID | No | None | FK -> `assets` | Canonical | Reference to parent logical asset. | `c1d2e3f4-...` |
| `tenant_id` | UUID | No | None | FK -> `assets(tenant_id)` | Governance | Tenant boundary identifier for multi-tenant isolation. | `11111111-...` |
| `version_number` | INTEGER | No | None | UNIQUE (asset_id, version_number) | Operational | Sequential version integer starting at 1. | `1` |
| `content_hash` | TEXT | No | None | None | Operational | Normalised package content SHA-256 hash. | `'e3b0c44298fc1c...'` |
| `raw_content_hash` | TEXT | No | None | None | Operational | Raw file binary SHA-256 hash. | `'8f434346648f6b...'` |
| `structure_hash` | TEXT | No | None | None | Operational | Normalised schema structure hash (ignoring cosmetics). | `'7a12b3c4d5e6f7...'` |
| `metadata_hash` | TEXT | No | None | None | Operational | Extracted metadata digest for cache invalidation. | `'1c2d3e4f5a6b7c...'` |
| `parser_version` | TEXT | No | None | None | Operational | Parser code version used to extract metadata. | `'1.4.0'` |
| `schema_version` | TEXT | No | None | None | Operational | Canonical schema DDL version. | `'1.0.0'` |
| `source_manifest` | JSONB | No | `'{}'::jsonb` | None | Operational | File listing and folder manifest within package. | `{"files": ["model.tmdl"]}` |
| `extraction_status` | TEXT | No | `'PENDING'` | CHECK in ('PENDING', 'SUCCESSFUL', 'PARTIAL', 'FAILED') | Operational | Extraction completion status. | `'SUCCESSFUL'` |
| `extraction_started_at` | TIMESTAMPTZ | Yes | None | None | Operational | Timestamp when extraction started. | `'2024-03-16 08:00:01Z'` |
| `extraction_completed_at` | TIMESTAMPTZ | Yes | None | None | Operational | Timestamp when extraction finished. | `'2024-03-16 08:00:15Z'` |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Database row creation timestamp. | `'2024-03-16 08:00:00Z'` |

---

### 3. `ingestion_events`
- **Purpose**: Physical upload attempt audit ledger, decoupling upload attempts from version creations.
- **Data Grain**: One record per physical file upload or batch ingestion trigger.
- **Primary Key**: `ingestion_id` (UUID).
- **Foreign Keys**: `asset_version_id` references `asset_versions(asset_version_id)` ON DELETE SET NULL.
- **Populating Platforms**: All.
- **Security / Redaction**: Error messages are sanitized to prevent credential/internal path leakage.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning | Example Values |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `ingestion_id` | UUID | No | `gen_random_uuid()` | PK | Operational | Unique identifier for the ingestion execution. | `b1c2d3e4-...` |
| `asset_version_id` | UUID | Yes | None | FK -> `asset_versions` | Operational | Resolved asset version (if upload was valid). | `a01b02c0-...` |
| `uploaded_by_user_id`| UUID | No | None | None | Governance | User ID who initiated the ingestion. | `u001-...` |
| `original_filename` | TEXT | No | None | None | Operational | Original filename uploaded via UI or batch. | `'claims_q4.pbip'` |
| `upload_size_bytes` | BIGINT | No | None | None | Operational | Physical byte count of uploaded payload. | `45120392` |
| `upload_source` | TEXT | No | None | None | Operational | Origin channel (`UI_UPLOAD`, `CLI_SYNC`, `S3_WATCHER`).| `'UI_UPLOAD'` |
| `ingestion_status` | TEXT | No | `'RECEIVED'` | CHECK in ('RECEIVED', 'VALIDATING', 'EXTRACTING', 'COMPLETED', 'FAILED') | Operational | Current status of ingestion event. | `'COMPLETED'` |
| `error_code` | TEXT | Yes | None | None | Operational | Standardized system error code if failed. | `'ERR_INVALID_PBIP'` |
| `error_message` | TEXT | Yes | None | None | Operational | Sanitized human-readable error description. | `'Missing definition.pbir'` |
| `started_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Ingestion initiation timestamp. | `'2024-03-16 07:59:59Z'` |
| `completed_at` | TIMESTAMPTZ | Yes | None | None | Operational | Ingestion termination timestamp. | `'2024-03-16 08:00:16Z'` |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Record creation timestamp. | `'2024-03-16 07:59:59Z'` |

---

### 4. `source_artifacts`
- **Purpose**: Granular tracking of individual files within a source package or multi-file directory.
- **Data Grain**: One record per individual file within an asset version package.
- **Primary Key**: `source_artifact_id` (UUID).
- **Foreign Keys**: `asset_version_id` references `asset_versions(asset_version_id)` ON DELETE CASCADE.
- **Populating Platforms**: All.
- **Security / Redaction**: Stores relative paths and hashes; no file byte contents are stored.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning | Example Values |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `source_artifact_id`| UUID | No | `gen_random_uuid()` | PK | Operational | Unique artifact record ID. | `d1e2f3a4-...` |
| `asset_version_id` | UUID | No | None | FK -> `asset_versions`, UNIQUE (asset_version_id, relative_path) | Operational | Containing asset version. | `a01b02c0-...` |
| `relative_path` | TEXT | No | None | Part of UNIQUE constraint | Source-Native | Path relative to package root. | `'definition/model.tmdl'`|
| `artifact_type` | TEXT | No | None | None | Canonical | Normalized file role (`TMDL`, `PBIR`, `XML`, `SHEET`).| `'TMDL'` |
| `source_native_id` | TEXT | Yes | None | None | Source-Native | Internal identifier embedded in file header. | `'model_001'` |
| `content_hash` | TEXT | No | None | None | Operational | SHA-256 hash of this specific sub-file. | `'a1b2c3d4...'` |
| `mime_type` | TEXT | Yes | None | None | Operational | MIME type detected. | `'text/plain'` |
| `size_bytes` | BIGINT | No | None | None | Operational | File size in bytes. | `15402` |
| `is_supported` | BOOLEAN | No | `true` | None | Operational | Whether parser supports this artifact type. | `true` |
| `extraction_status` | TEXT | No | `'PENDING'` | CHECK in ('PENDING', 'SUCCESSFUL', 'PARTIAL', 'SKIPPED', 'FAILED') | Operational | Extraction status of this specific file. | `'SUCCESSFUL'` |
| `extraction_notes` | JSONB | No | `'{}'::jsonb` | None | Operational | Extraction diagnostic metadata. | `{"lines_parsed": 450}` |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. | `'2024-03-16 08:00:02Z'` |

---

# Subsystem B: Universal Analytical Objects

### 5. `analytical_objects`
- **Purpose**: Universal polymorphic identity registry for every BI metadata entity across all platforms.
- **Data Grain**: One record per analytical object (report, visual, table, column, calculation, filter, etc.) within a tenant boundary.
- **Primary Key**: `object_id` (UUID).
- **Foreign Keys**:
  - `(asset_version_id, tenant_id)` references `asset_versions(asset_version_id, tenant_id)` ON DELETE CASCADE.
  - `parent_object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `source_artifact_id` references `source_artifacts(source_artifact_id)` ON DELETE SET NULL.
- **Populating Platforms**: All platforms.
- **Security / Redaction**: Row Level Security (RLS) enabled. `source_metadata` is sanitized to ensure no credentials or raw data rows are stored.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning | Example Values |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `object_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Universal surrogate key for the metadata object. | `f1e2d3c4-...` |
| `asset_version_id` | UUID | No | None | FK -> `asset_versions` | Canonical | Containing asset version snapshot. | `a01b02c0-...` |
| `tenant_id` | UUID | No | None | FK -> `asset_versions(tenant_id)` | Governance | Tenant boundary identifier for multi-tenant isolation. | `11111111-...` |
| `parent_object_id` | UUID | Yes | None | Self-FK -> `analytical_objects` | Canonical | Parent container (e.g. Page for Visual, Table for Col).| `p1a2b3c4-...` |
| `source_artifact_id`| UUID | Yes | None | FK -> `source_artifacts` | Operational | Originating source file artifact. | `d1e2f3a4-...` |
| `platform` | TEXT | No | None | CHECK in ('POWER_BI', 'TABLEAU', 'EXCEL', 'THOUGHTSPOT', 'MICROSTRATEGY') | Canonical | Originating platform. | `'POWER_BI'` |
| `object_type` | TEXT | No | None | None | Canonical | Object type (`REPORT`, `VISUAL`, `MEASURE`, `COLUMN`). | `'MEASURE'` |
| `source_native_id` | TEXT | Yes | None | None | Source-Native | Platform-native internal GUID or ID. | `'m_loss_ratio_01'` |
| `source_native_name`| TEXT | Yes | None | None | Source-Native | Original object name with native casing and symbols. | `'[Loss Ratio %]'` |
| `canonical_name` | TEXT | No | None | None | Canonical | Normalised, clean business name. | `'Loss Ratio'` |
| `display_name` | TEXT | Yes | None | None | Canonical | Formatted display name shown to report end-users. | `'Loss Ratio (%)'` |
| `description` | TEXT | Yes | None | None | Canonical | Object description extracted from source definitions. | `'Claims Incurred / EP'` |
| `source_path` | TEXT | Yes | None | None | Source-Native | Internal hierarchical path in source model. | `'Model/Measures/Loss'` |
| `source_locator` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Structural coordinates (page/visual/cell address). | `{"page_id": "p1"}` |
| `is_hidden` | BOOLEAN | No | `false` | None | Source-Native | Whether hidden from report consumers. | `false` |
| `is_active` | BOOLEAN | No | `true` | None | Operational | Active status flag. | `true` |
| `extraction_status` | TEXT | No | `'EXTRACTED'`| CHECK in ('EXTRACTED', 'PARTIAL', 'INFERRED', 'UNRESOLVED', 'FAILED') | Operational | Extraction completeness status. | `'EXTRACTED'` |
| `metadata_completeness`| NUMERIC(5,4) | Yes | None | CHECK between 0.0000 and 1.0000 | Inferred | Ratio of known attributes successfully populated. | `0.9500` |
| `source_metadata` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Native platform-specific property bag. | `{"format": "0.0%"}` |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Row creation timestamp. | `'2024-03-16 08:00:05Z'` |
| `updated_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Maintained by `set_updated_at()` trigger. | `'2024-03-16 08:00:05Z'` |

---

### 6. `reports`
- **Purpose**: Specialized analytical dashboard/report package header entity.
- **Data Grain**: One record per dashboard, workbook canvas, dossier, or liveboard.
- **Primary Key**: `report_id` (UUID).
- **Foreign Keys**:
  - `object_id` (UNIQUE) references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `default_page_object_id` references `analytical_objects(object_id)` ON DELETE SET NULL.
- **Populating Platforms**: All platforms.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `report_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Specialized report ID. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, UNIQUE | Canonical | Associated polymorphic analytical object. |
| `report_type` | TEXT | No | None | None | Canonical | Report category (`INTERACTIVE_DASHBOARD`, `PAGINATED`, `LIVEBOARD`). |
| `report_definition`| JSONB | No | `'{}'::jsonb` | None | Canonical | Normalized presentation definition tree. |
| `default_page_object_id`| UUID | Yes | None | FK -> `analytical_objects` | Canonical | Pointer to default landing page. |
| `page_count` | INTEGER | No | `0` | None | Inferred | Total page/tab count. |
| `visual_count` | INTEGER | No | `0` | None | Inferred | Total visual component count. |
| `report_configuration`| JSONB| No | `'{}'::jsonb` | None | Source-Native | Platform-specific canvas settings (theme, palette, canvas size). |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Row creation timestamp. |

---

### 7. `report_pages`
- **Purpose**: Individual pages, tabs, canvas sheets, or story points within a report.
- **Data Grain**: One record per page/sheet.
- **Primary Key**: `page_id` (UUID).
- **Foreign Keys**:
  - `report_id` references `reports(report_id)` ON DELETE CASCADE.
  - `object_id` (UNIQUE) references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Populating Platforms**: Power BI, Tableau, Excel (as worksheets), ThoughtSpot, MicroStrategy.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `page_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Specialized page ID. |
| `report_id` | UUID | No | None | FK -> `reports` | Canonical | Parent report ID. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, UNIQUE | Canonical | Associated polymorphic analytical object. |
| `source_native_id` | TEXT | Yes | None | None | Source-Native | Native page identifier. |
| `page_name` | TEXT | No | None | None | Canonical | Display name of the page/tab. |
| `page_order` | INTEGER | No | `0` | None | Source-Native | Tab sequence index (0-indexed). |
| `page_type` | TEXT | No | None | None | Canonical | Page classification (`CANVAS`, `TOOLTIP_PAGE`, `DRILLTHROUGH`). |
| `page_properties` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Layout, height, width, background settings. |
| `is_hidden` | BOOLEAN | No | `false` | None | Source-Native | Whether tab is hidden from report navigation. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

### 8. `visuals`
- **Purpose**: Visual charts, KPI cards, tables, maps, or containers placed on a report page.
- **Data Grain**: One record per visual container on a canvas.
- **Primary Key**: `visual_id` (UUID).
- **Foreign Keys**:
  - `page_id` references `report_pages(page_id)` ON DELETE CASCADE.
  - `object_id` (UNIQUE) references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Populating Platforms**: All platforms.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `visual_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Specialized visual ID. |
| `page_id` | UUID | No | None | FK -> `report_pages` | Canonical | Parent report page ID. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, UNIQUE | Canonical | Associated polymorphic analytical object. |
| `source_native_id` | TEXT | Yes | None | None | Source-Native | Native visual ID. |
| `visual_type` | TEXT | No | None | None | Canonical | Visual type (`KPI_CARD`, `BAR_CHART`, `TABLE`, `LINE_CHART`). |
| `visual_title` | TEXT | Yes | None | None | Source-Native | Rendered title of the visual. |
| `visual_description`| TEXT | Yes | None | None | Source-Native | Subtitle or accessibility description. |
| `position_x` | NUMERIC | Yes | None | None | Source-Native | Horizontal pixel coordinate. |
| `position_y` | NUMERIC | Yes | None | None | Source-Native | Vertical pixel coordinate. |
| `width` | NUMERIC | Yes | None | None | Source-Native | Visual width in pixels. |
| `height` | NUMERIC | Yes | None | None | Source-Native | Visual height in pixels. |
| `z_order` | INTEGER | No | `0` | None | Source-Native | Layering stacking order. |
| `visual_configuration`| JSONB| No | `'{}'::jsonb` | None | Source-Native | Platform-specific visual config (axes, legends, formatting). |
| `is_visible` | BOOLEAN | No | `true` | None | Source-Native | Visibility state. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

### 9. `visual_bindings`
- **Purpose**: Association of measures, columns, and dimensions to visual roles/axes.
- **Data Grain**: One record per bound field-to-visual role.
- **Primary Key**: `visual_binding_id` (UUID).
- **Foreign Keys**:
  - `visual_id` references `visuals(visual_id)` ON DELETE CASCADE.
  - `object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Populating Platforms**: All platforms.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `visual_binding_id`| UUID | No | `gen_random_uuid()` | PK | Canonical | Binding record ID. |
| `visual_id` | UUID | No | None | FK -> `visuals` | Canonical | Target visual receiving the data binding. |
| `object_id` | UUID | No | None | FK -> `analytical_objects` | Canonical | Bound measure, calculated column, or dimension. |
| `binding_role` | TEXT | No | None | None | Canonical | Role on visual (`X_AXIS`, `Y_AXIS`, `VALUE`, `LEGEND`, `TOOLTIP`). |
| `binding_order` | INTEGER | No | `0` | None | Source-Native | Sequence order within multi-field shelves. |
| `aggregation_override`| TEXT | Yes | None | None | Source-Native | Visual-level aggregation override (`SUM`, `AVG`, `COUNT`). |
| `format_override` | TEXT | Yes | None | None | Source-Native | Visual-level format string override. |
| `binding_properties`| JSONB | No | `'{}'::jsonb` | None | Source-Native | Sort direction, top-N settings, data color mapping. |

---

### 10. `visual_properties`
- **Purpose**: Granular visual-level format properties, conditional formats, and dynamic rules.
- **Data Grain**: One record per visual property path.
- **Primary Key**: `visual_property_id` (UUID).
- **Foreign Keys**: `visual_id` references `visuals(visual_id)` ON DELETE CASCADE.
- **Populating Platforms**: All platforms.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `visual_property_id`| UUID | No | `gen_random_uuid()` | PK | Canonical | Property record ID. |
| `visual_id` | UUID | No | None | FK -> `visuals`, UNIQUE (visual_id, property_path) | Canonical | Target visual. |
| `property_path` | TEXT | No | None | Part of UNIQUE constraint | Canonical | Dot-notated property locator (`legend.position`, `title.text`).|
| `property_value` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Structured value of property. |
| `expression_language`| TEXT | Yes | None | None | Source-Native | Expression language if dynamic (`DAX`, `EXCEL`). |
| `expression_text` | TEXT | Yes | None | None | Source-Native | Formula text driving dynamic property (e.g. conditional color). |
| `source_properties`| JSONB | No | `'{}'::jsonb` | None | Source-Native | Platform-native property attributes. |

---

### 11. `visual_interactions`
- **Purpose**: Cross-filtering, highlighting, and drilling interactions between visual pairs.
- **Data Grain**: One record per directed visual-to-visual interaction.
- **Primary Key**: `visual_interaction_id` (UUID).
- **Foreign Keys**:
  - `source_visual_id` references `visuals(visual_id)` ON DELETE CASCADE.
  - `target_visual_id` references `visuals(visual_id)` ON DELETE CASCADE.
- **Constraints**: CHECK (`source_visual_id <> target_visual_id`).
- **Populating Platforms**: Power BI, Tableau, ThoughtSpot, MicroStrategy.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `visual_interaction_id`| UUID | No | `gen_random_uuid()` | PK | Canonical | Interaction record ID. |
| `source_visual_id` | UUID | No | None | FK -> `visuals` | Canonical | Visual initiating the interaction (e.g. clicked slicer). |
| `target_visual_id` | UUID | No | None | FK -> `visuals` | Canonical | Visual affected by interaction. Must differ from source. |
| `interaction_type` | TEXT | No | None | None | Canonical | Interaction mode (`FILTER`, `HIGHLIGHT`, `NONE`, `DRILL`). |
| `interaction_properties`| JSONB| No | `'{}'::jsonb` | None | Source-Native | Field mapping and scope configuration. |

---

### 12. `visual_types`
- **Purpose**: Standard mapping taxonomy translating native visual strings to canonical types.
- **Data Grain**: One record per platform-native visual type identifier.
- **Primary Key**: `visual_type_id` (UUID).
- **Constraints**: UNIQUE (`platform`, `native_type`).
- **Populating Platforms**: Canonical reference table seeded across all 5 platforms.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `visual_type_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Type mapping ID. |
| `platform` | TEXT | No | None | Part of UNIQUE constraint | Canonical | BI Platform (`POWER_BI`, `TABLEAU`, etc.). |
| `native_type` | TEXT | No | None | Part of UNIQUE constraint | Source-Native | Native visual code (e.g. `pieChart`, `card`, `bar`). |
| `canonical_type` | TEXT | No | None | None | Canonical | Normalized taxonomy (`KPI_CARD`, `PIE_CHART`, `CLUSTERED_BAR`).|
| `description` | TEXT | Yes | None | None | Canonical | Canonical visual description. |
| `type_properties` | JSONB | No | `'{}'::jsonb` | None | Canonical | Supported binding roles and axis capabilities. |

---

### 13. `bookmarks`
- **Purpose**: Saved visual state snapshots, personal views, and visual filter configurations.
- **Data Grain**: One record per saved visual state or bookmark.
- **Primary Key**: `bookmark_id` (UUID).
- **Foreign Keys**: `object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Populating Platforms**: Power BI, Tableau (Custom Views), MicroStrategy.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `bookmark_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Bookmark ID. |
| `object_id` | UUID | No | None | FK -> `analytical_objects` | Canonical | Associated polymorphic object. |
| `source_native_id` | TEXT | Yes | None | None | Source-Native | Native bookmark GUID. |
| `bookmark_name` | TEXT | No | None | None | Source-Native | Bookmark name. |
| `bookmark_state` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Serialized state of visual visibility, filters, and spotlight.|
| `bookmark_properties`| JSONB| No | `'{}'::jsonb` | None | Source-Native | Target page, scope, and display options. |

---

### 14. `report_navigation`
- **Purpose**: Action links, drill-through targets, URL actions, and page-to-page navigation paths.
- **Data Grain**: One record per navigation or drill action link.
- **Primary Key**: `report_navigation_id` (UUID).
- **Foreign Keys**:
  - `source_object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `target_object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Populating Platforms**: Power BI, Tableau, ThoughtSpot, MicroStrategy.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `report_navigation_id`| UUID | No | `gen_random_uuid()` | PK | Canonical | Navigation record ID. |
| `source_object_id` | UUID | No | None | FK -> `analytical_objects` | Canonical | Initiating visual, button, or link. |
| `target_object_id` | UUID | No | None | FK -> `analytical_objects` | Canonical | Destination page, report, or visual. |
| `navigation_type` | TEXT | No | None | None | Canonical | Navigation mode (`DRILLTHROUGH`, `PAGE_NAV`, `URL_ACTION`). |
| `navigation_name` | TEXT | Yes | None | None | Source-Native | Display label of action. |
| `navigation_expression`| TEXT| Yes | None | None | Source-Native | Dynamic destination or parameter passing expression. |
| `expression_language`| TEXT | Yes | None | None | Source-Native | Expression language used. |
| `navigation_properties`| JSONB| No | `'{}'::jsonb` | None | Source-Native | Pass-through filter parameters and window behavior. |

---

# Subsystem C: Semantic Models and Calculations

### 15. `semantic_models`
- **Purpose**: Tabular models, cubes, datasets, or ThoughtSpot worksheets modeling business logic.
- **Data Grain**: One record per semantic data model package.
- **Primary Key**: `semantic_model_id` (UUID).
- **Foreign Keys**: `object_id` (UNIQUE) references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Populating Platforms**: All platforms.
- **Security / Redaction**: `source_connection_summary` is thoroughly sanitized to remove connection passwords/tokens.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `semantic_model_id`| UUID | No | `gen_random_uuid()` | PK | Canonical | Semantic model surrogate key. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, UNIQUE | Canonical | Associated polymorphic object. |
| `source_native_id` | TEXT | Yes | None | None | Source-Native | Native model identifier or GUID. |
| `model_name` | TEXT | No | None | None | Canonical | Semantic model name. |
| `model_type` | TEXT | No | None | None | Canonical | Model architecture (`TABULAR`, `LOGICAL_CUBE`, `EXCEL_DATAMODEL`).|
| `model_version` | TEXT | Yes | None | None | Source-Native | Model format version (e.g. Tabular 1500). |
| `compatibility_level`| TEXT | Yes | None | None | Source-Native | Compatibility level integer/string. |
| `model_definition` | JSONB | No | `'{}'::jsonb` | None | Canonical | Normalized model schema definition. |
| `source_connection_summary`| JSONB| No | `'{}'::jsonb`| None | Operational | Sanitized connection summary (host, DB name, auth type). |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

### 16. `data_tables`
- **Purpose**: Physical, logical, calculated, imported, or query tables within a semantic model.
- **Data Grain**: One record per table in a semantic model.
- **Primary Key**: `data_table_id` (UUID).
- **Foreign Keys**:
  - `object_id` (UNIQUE) references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `semantic_model_id` references `semantic_models(semantic_model_id)` ON DELETE CASCADE.
- **Populating Platforms**: All platforms.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `data_table_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Table surrogate key. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, UNIQUE | Canonical | Associated polymorphic analytical object. |
| `semantic_model_id`| UUID | No | None | FK -> `semantic_models` | Canonical | Parent semantic model. |
| `source_native_id` | TEXT | Yes | None | None | Source-Native | Native table identifier. |
| `table_name` | TEXT | No | None | None | Canonical | Table name. |
| `schema_name` | TEXT | Yes | None | None | Source-Native | Database schema name (e.g. `dbo`, `analytics`). |
| `table_type` | TEXT | No | None | None | Canonical | Table role (`PHYSICAL`, `CALCULATED`, `IMPORT`, `EXCEL_TABLE`). |
| `description` | TEXT | Yes | None | None | Canonical | Table documentation. |
| `is_hidden` | BOOLEAN | No | `false` | None | Source-Native | Whether hidden in model field lists. |
| `storage_mode` | TEXT | Yes | None | None | Source-Native | Storage mode (`IMPORT`, `DIRECT_QUERY`, `DUAL`). |
| `source_reference` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Source database and physical table reference. |
| `table_properties` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Platform-specific table configuration. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

### 17. `data_columns`
- **Purpose**: Columns belonging to data tables, including physical, calculated, and attribute fields.
- **Data Grain**: One record per column in a table.
- **Primary Key**: `data_column_id` (UUID).
- **Foreign Keys**:
  - `object_id` (UNIQUE) references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `data_table_id` references `data_tables(data_table_id)` ON DELETE CASCADE.
- **Populating Platforms**: All platforms.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `data_column_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Column surrogate key. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, UNIQUE | Canonical | Associated polymorphic analytical object. |
| `data_table_id` | UUID | No | None | FK -> `data_tables` | Canonical | Parent table ID. |
| `source_native_id` | TEXT | Yes | None | None | Source-Native | Native column ID. |
| `column_name` | TEXT | No | None | None | Canonical | Original column name. |
| `display_name` | TEXT | Yes | None | None | Canonical | Formatted display name. |
| `data_type` | TEXT | No | None | None | Canonical | Harmonized data type (`INTEGER`, `DECIMAL`, `TEXT`, `DATE`). |
| `source_data_type` | TEXT | Yes | None | None | Source-Native | Native source data type (e.g. `Int64`, `varchar(50)`). |
| `description` | TEXT | Yes | None | None | Canonical | Column documentation. |
| `semantic_role` | TEXT | Yes | None | None | Canonical | Role (`DIMENSION`, `MEASURE`, `ATTRIBUTE`, `PRIMARY_KEY`). |
| `is_nullable` | BOOLEAN | No | `true` | None | Source-Native | Whether column permits nulls. |
| `is_hidden` | BOOLEAN | No | `false` | None | Source-Native | Hidden state in field picker. |
| `is_calculated` | BOOLEAN | No | `false` | None | Canonical | Whether populated by an expression. |
| `default_aggregation`| TEXT | Yes | None | None | Source-Native | Default aggregation (`SUM`, `COUNT`, `NONE`). |
| `format_string` | TEXT | Yes | None | None | Source-Native | Display format mask (`$#,##0.00`). |
| `column_properties`| JSONB | No | `'{}'::jsonb` | None | Source-Native | Sorting columns, encoding, and data category. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

### 18. `calculations`
- **Purpose**: Explicit measures, calculated columns/tables, metrics, and formula expressions.
- **Data Grain**: One record per calculated expression.
- **Primary Key**: `calculation_id` (UUID).
- **Foreign Keys**:
  - `object_id` (UNIQUE) references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `semantic_model_id` references `semantic_models(semantic_model_id)` ON DELETE CASCADE.
  - `data_table_id` references `data_tables(data_table_id)` ON DELETE SET NULL.
  - `data_column_id` references `data_columns(data_column_id)` ON DELETE SET NULL.
- **Populating Platforms**: All platforms.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `calculation_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Calculation surrogate key. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, UNIQUE | Canonical | Associated polymorphic analytical object. |
| `semantic_model_id`| UUID | Yes | None | FK -> `semantic_models` | Canonical | Scoped semantic model. |
| `data_table_id` | UUID | Yes | None | FK -> `data_tables` | Canonical | Scoped data table (home table). |
| `data_column_id` | UUID | Yes | None | FK -> `data_columns` | Canonical | Associated physical column if calculated column. |
| `calculation_name` | TEXT | No | None | None | Canonical | Name of the measure/calculation. |
| `calculation_type` | TEXT | No | None | None | Canonical | Type (`MEASURE`, `CALCULATED_COLUMN`, `METRIC`, `CELL_FORMULA`).|
| `expression_language`| TEXT | No | None | None | Canonical | Language (`DAX`, `TABLEAU_CALC`, `EXCEL_FORMULA`, `M`, `SQL`).|
| `expression_text` | TEXT | No | None | None | Source-Native | Original verbatim source expression. |
| `normalised_expression`| TEXT| Yes | None | None | Inferred | Normalised expression with standard casing/spacing. |
| `return_data_type` | TEXT | Yes | None | None | Canonical | Inferred or declared return type. |
| `aggregation_type` | TEXT | Yes | None | None | Canonical | Aggregation type (`SUM`, `RATIO`, `COUNT`, `COMPOUND`). |
| `format_string` | TEXT | Yes | None | None | Source-Native | Display format mask. |
| `description` | TEXT | Yes | None | None | Canonical | Calculation documentation. |
| `evaluation_context`| TEXT | Yes | None | None | Canonical | Context (`ROW_CONTEXT`, `FILTER_CONTEXT`, `CELL_CONTEXT`). |
| `expression_parse_status`| TEXT| No| `'UNPARSED'`| CHECK in ('UNPARSED', 'PARSED', 'PARTIAL', 'UNSUPPORTED', 'FAILED') | Operational | AST parsing status. |
| `expression_ast` | JSONB | No | `'{}'::jsonb` | None | Inferred | Parsed Abstract Syntax Tree. |
| `expression_properties`| JSONB| No | `'{}'::jsonb` | None | Source-Native | Dynamic formatting expressions and display folders. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

### 19. `relationships`
- **Purpose**: Joins, relationships, and active cross-table filter navigation in semantic models.
- **Data Grain**: One record per model join or relationship.
- **Primary Key**: `relationship_id` (UUID).
- **Foreign Keys**:
  - `object_id` (UNIQUE) references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `from_table_id` references `data_tables(data_table_id)` ON DELETE CASCADE.
  - `to_table_id` references `data_tables(data_table_id)` ON DELETE CASCADE.
  - `from_object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `to_object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Constraints**: CHECK (`(from_table_id IS NOT NULL AND to_table_id IS NOT NULL) OR (from_object_id IS NOT NULL AND to_object_id IS NOT NULL)`).
- **Populating Platforms**: Power BI, Tableau, ThoughtSpot, MicroStrategy.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `relationship_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Relationship surrogate key. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, UNIQUE | Canonical | Associated polymorphic analytical object. |
| `relationship_type`| TEXT | No | None | None | Canonical | Type (`MODEL_RELATIONSHIP`, `PHYSICAL_JOIN`, `LOGICAL_LINK`). |
| `from_table_id` | UUID | Yes | None | FK -> `data_tables` | Canonical | Source table reference. |
| `to_table_id` | UUID | Yes | None | FK -> `data_tables` | Canonical | Target table reference. |
| `from_object_id` | UUID | Yes | None | FK -> `analytical_objects` | Canonical | Generalized source object endpoint. |
| `to_object_id` | UUID | Yes | None | FK -> `analytical_objects` | Canonical | Generalized target object endpoint. |
| `cardinality` | TEXT | No | None | None | Canonical | Cardinality (`ONE_TO_ONE`, `ONE_TO_MANY`, `MANY_TO_MANY`). |
| `join_type` | TEXT | Yes | None | None | Canonical | Join mode (`INNER`, `LEFT_OUTER`, `RIGHT_OUTER`, `FULL`). |
| `is_active` | BOOLEAN | No | `true` | None | Source-Native | Whether active for default filter propagation. |
| `cross_filter_direction`| TEXT| Yes| None | None | Source-Native | Filter direction (`SINGLE`, `BOTH`). |
| `relationship_expression`| TEXT| Yes| None | None | Source-Native | Join predicate expression. |
| `relationship_properties`| JSONB| No | `'{}'::jsonb`| None | Source-Native | Security filter propagation and referential integrity flags. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

### 20. `model_partitions`
- **Purpose**: Physical partitions, query partitions, or incremental load ranges.
- **Data Grain**: One record per partition in a semantic model table.
- **Primary Key**: `model_partition_id` (UUID).
- **Foreign Keys**: `semantic_model_id` references `semantic_models(semantic_model_id)` ON DELETE CASCADE.
- **Populating Platforms**: Power BI (TMDL partitions), MicroStrategy (Cubes).

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `model_partition_id`| UUID | No | `gen_random_uuid()` | PK | Canonical | Partition record ID. |
| `semantic_model_id`| UUID | No | None | FK -> `semantic_models` | Canonical | Parent semantic model ID. |
| `source_native_id` | TEXT | Yes | None | None | Source-Native | Native partition identifier. |
| `partition_name` | TEXT | No | None | None | Canonical | Partition name (e.g. `Partition_2023`). |
| `source_type` | TEXT | Yes | None | None | Source-Native | Partition source (`M_QUERY`, `SQL_QUERY`, `ENTITY`). |
| `expression_language`| TEXT | Yes | None | None | Source-Native | Language of partition expression. |
| `expression_text` | TEXT | Yes | None | None | Source-Native | Query text driving partition. |
| `partition_properties`| JSONB| No | `'{}'::jsonb` | None | Source-Native | Incremental refresh policies and range boundaries. |

---

### 21. `hierarchies`
- **Purpose**: Dimensional hierarchies defined within semantic models.
- **Data Grain**: One record per multi-level dimensional hierarchy.
- **Primary Key**: `hierarchy_id` (UUID).
- **Foreign Keys**:
  - `object_id` (UNIQUE) references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `semantic_model_id` references `semantic_models(semantic_model_id)` ON DELETE CASCADE.
- **Populating Platforms**: Power BI, Tableau, MicroStrategy, ThoughtSpot.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `hierarchy_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Hierarchy surrogate key. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, UNIQUE | Canonical | Associated polymorphic analytical object. |
| `semantic_model_id`| UUID | No | None | FK -> `semantic_models` | Canonical | Parent semantic model. |
| `hierarchy_name` | TEXT | No | None | None | Canonical | Hierarchy name (e.g. `Calendar Hierarchy`, `Geography`). |
| `hierarchy_type` | TEXT | No | None | None | Canonical | Category (`DATE`, `GEOGRAPHY`, `ORGANIZATIONAL`, `CUSTOM`). |
| `hierarchy_properties`| JSONB| No | `'{}'::jsonb` | None | Source-Native | Display folder and hide-members configuration. |

---

### 22. `hierarchy_levels`
- **Purpose**: Ordered levels within a dimensional hierarchy.
- **Data Grain**: One record per step/level in a hierarchy.
- **Primary Key**: `hierarchy_level_id` (UUID).
- **Foreign Keys**:
  - `hierarchy_id` references `hierarchies(hierarchy_id)` ON DELETE CASCADE.
  - `level_object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Constraints**: UNIQUE (`hierarchy_id`, `level_order`).
- **Populating Platforms**: Power BI, Tableau, MicroStrategy.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `hierarchy_level_id`| UUID | No | `gen_random_uuid()` | PK | Canonical | Level surrogate key. |
| `hierarchy_id` | UUID | No | None | FK -> `hierarchies`, UNIQUE (hierarchy_id, level_order) | Canonical | Parent hierarchy. |
| `level_object_id` | UUID | No | None | FK -> `analytical_objects` | Canonical | Associated column object representing this level. |
| `level_name` | TEXT | No | None | None | Canonical | Name of the level (e.g. `Year`, `Quarter`, `Month`). |
| `level_order` | INTEGER | No | None | Part of UNIQUE constraint | Canonical | Ordinal depth in hierarchy (1 = root). |
| `level_properties` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Sorting rules and level-specific formatting. |

---

### 23. `parameters`
- **Purpose**: What-if parameters, report parameters, or query variables.
- **Data Grain**: One record per parameter definition.
- **Primary Key**: `parameter_id` (UUID).
- **Foreign Keys**: `object_id` (UNIQUE) references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Populating Platforms**: Power BI, Tableau, ThoughtSpot, MicroStrategy.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `parameter_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Parameter surrogate key. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, UNIQUE | Canonical | Associated polymorphic analytical object. |
| `parameter_name` | TEXT | No | None | None | Canonical | Parameter identifier. |
| `data_type` | TEXT | No | None | None | Canonical | Parameter data type (`DECIMAL`, `TEXT`, `BOOLEAN`). |
| `default_value` | JSONB | Yes | None | None | Source-Native | Configured default value. |
| `allowed_values` | JSONB | Yes | None | None | Source-Native | List or range of valid parameter values. |
| `is_required` | BOOLEAN | No | `false` | None | Source-Native | Whether prompt requires input. |
| `parameter_properties`| JSONB| No | `'{}'::jsonb` | None | Source-Native | UI widget type (slider, dropdown) and step sizes. |

---

### 24. `named_expressions`
- **Purpose**: Power Query / M shared queries, named calculations, or semantic constants.
- **Data Grain**: One record per named expression.
- **Primary Key**: `named_expression_id` (UUID).
- **Foreign Keys**:
  - `object_id` (UNIQUE) references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `resolved_reference_object_id` references `analytical_objects(object_id)` ON DELETE SET NULL.
- **Populating Platforms**: Power BI, Excel, ThoughtSpot.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `named_expression_id`| UUID | No | `gen_random_uuid()` | PK | Canonical | Expression surrogate key. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, UNIQUE | Canonical | Associated polymorphic analytical object. |
| `expression_name` | TEXT | No | None | None | Canonical | Name of the shared query or parameter. |
| `scope` | TEXT | Yes | None | None | Canonical | Scope (`GLOBAL`, `MODEL`, `FOLDER`). |
| `expression_language`| TEXT | No | None | None | Canonical | Expression language (`M`, `DAX`, `SQL`). |
| `expression_text` | TEXT | No | None | None | Source-Native | Complete query definition text. |
| `resolved_reference_object_id`| UUID| Yes| None | FK -> `analytical_objects` | Canonical | Resolved target if this expression aliases another object.|
| `expression_properties`| JSONB| No | `'{}'::jsonb`| None | Source-Native | Query metadata, load-to-model flags, query groups. |

---

# Subsystem D: Filters, Security, Data Sources, and Lineage

### 25. `filters`
- **Purpose**: Standard report, page, visual, and model-level filtering predicates.
- **Data Grain**: One record per filter predicate.
- **Primary Key**: `filter_id` (UUID).
- **Foreign Keys**: `object_id` (UNIQUE) references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Populating Platforms**: All platforms.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `filter_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Filter surrogate key. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, UNIQUE | Canonical | Associated polymorphic analytical object. |
| `filter_name` | TEXT | No | None | None | Canonical | Filter identifier. |
| `filter_type` | TEXT | No | None | None | Canonical | Category (`BASIC`, `ADVANCED`, `TOP_N`, `RELATIVE_DATE`). |
| `filter_scope` | TEXT | No | None | None | Canonical | Scope (`REPORT_LEVEL`, `PAGE_LEVEL`, `VISUAL_LEVEL`, `SLICER`).|
| `expression_language`| TEXT | Yes | None | None | Source-Native | Filter predicate language. |
| `expression_text` | TEXT | Yes | None | None | Source-Native | Filter logic expression. |
| `filter_operator` | TEXT | Yes | None | None | Canonical | Operator (`IN`, `EQUALS`, `BETWEEN`, `GREATER_THAN`). |
| `filter_values` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Filter operand values. |
| `is_enabled` | BOOLEAN | No | `true` | None | Source-Native | Active toggle state. |
| `filter_properties` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Slicer style, multi-select, and locked states. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

### 26. `filter_assignments`
- **Purpose**: Association of filters to specific target objects and filtered fields.
- **Data Grain**: One record per target object filtered by a filter.
- **Primary Key**: `filter_assignment_id` (UUID).
- **Foreign Keys**:
  - `filter_id` references `filters(filter_id)` ON DELETE CASCADE.
  - `target_object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `field_object_id` references `analytical_objects(object_id)` ON DELETE SET NULL.
- **Populating Platforms**: All platforms.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `filter_assignment_id`| UUID | No | `gen_random_uuid()` | PK | Canonical | Assignment record ID. |
| `filter_id` | UUID | No | None | FK -> `filters` | Canonical | Associated filter definition. |
| `target_object_id` | UUID | No | None | FK -> `analytical_objects` | Canonical | Target object receiving the filter (e.g. Visual, Page). |
| `field_object_id` | UUID | Yes | None | FK -> `analytical_objects` | Canonical | Underlying column/field being evaluated. |
| `assignment_scope` | TEXT | No | None | None | Canonical | Scope of assignment (`APPLIED`, `EXCLUDED`, `SYNCED`). |
| `assignment_properties`| JSONB| No | `'{}'::jsonb` | None | Source-Native | Slicer synchronization group and cross-island settings. |

---

### 27. `security_roles`
- **Purpose**: Row-level security (RLS) or object-level security (OLS) role declarations.
- **Data Grain**: One record per security role.
- **Primary Key**: `security_role_id` (UUID).
- **Foreign Keys**: `object_id` (UNIQUE) references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Populating Platforms**: Power BI, Tableau, ThoughtSpot, MicroStrategy.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `security_role_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Role surrogate key. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, UNIQUE | Canonical | Associated polymorphic analytical object. |
| `role_name` | TEXT | No | None | None | Canonical | Security role name (e.g. `Underwriting_Region_North`). |
| `role_type` | TEXT | No | None | None | Canonical | Mode (`RLS`, `OLS`, `PLATFORM_SECURITY`). |
| `role_description` | TEXT | Yes | None | None | Canonical | Security policy documentation. |
| `role_properties` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Role membership settings and tenant mappings. |

---

### 28. `security_role_filters`
- **Purpose**: Security predicate expressions restricting table rows or columns for a role.
- **Data Grain**: One record per secured object rule under a role.
- **Primary Key**: `security_role_filter_id` (UUID).
- **Foreign Keys**:
  - `security_role_id` references `security_roles(security_role_id)` ON DELETE CASCADE.
  - `target_object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Populating Platforms**: Power BI, Tableau, ThoughtSpot, MicroStrategy.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `security_role_filter_id`| UUID| No| `gen_random_uuid()` | PK | Canonical | Security rule record ID. |
| `security_role_id` | UUID | No | None | FK -> `security_roles` | Canonical | Parent security role. |
| `target_object_id` | UUID | No | None | FK -> `analytical_objects` | Canonical | Secured table or column object. |
| `expression_language`| TEXT | No | None | None | Canonical | Expression language (`DAX`, `USER_FILTER`, `SQL`). |
| `expression_text` | TEXT | No | None | None | Source-Native | Exact security predicate formula. |
| `normalised_expression`| TEXT| Yes| None | None | Inferred | Normalised predicate. |
| `expression_parse_status`| TEXT| No| `'UNPARSED'`| CHECK in ('UNPARSED', 'PARSED', 'PARTIAL', 'UNSUPPORTED', 'FAILED') | Operational | AST parsing status. |
| `rule_properties` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Dynamic user function metadata (`USERNAME()`, `USERPRINCIPALNAME()`). |

---

### 29. `security_principals`
- **Purpose**: Users, groups, roles, or service principals referenced in security definitions.
- **Data Grain**: One record per principal identity within a tenant.
- **Primary Key**: `principal_id` (UUID).
- **Constraints**:
  - Partial Unique Index on `(tenant_id, platform, source_native_id)` WHERE `source_native_id IS NOT NULL`.
  - Partial Unique Index on `(tenant_id, platform, principal_name)` WHERE `source_native_id IS NULL`.
- **Populating Platforms**: All platforms.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `principal_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Principal surrogate key. |
| `tenant_id` | UUID | No | None | None | Governance | Tenant boundary identifier. |
| `platform` | TEXT | No | None | None | Canonical | Platform managing this principal. |
| `source_native_id` | TEXT | Yes | None | Partial UNIQUE | Source-Native | Platform-native user/group GUID. |
| `principal_name` | TEXT | No | None | Partial UNIQUE | Canonical | Username or group name (e.g. `Actuarial_Group`). |
| `principal_type` | TEXT | No | None | None | Canonical | Category (`USER`, `GROUP`, `ROLE`, `SERVICE_PRINCIPAL`). |
| `principal_properties`| JSONB| No | `'{}'::jsonb` | None | Source-Native | Email, domain, and external directory metadata. |

---

### 30. `security_object_permissions`
- **Purpose**: Explicit permissions granted on analytical objects to security principals.
- **Data Grain**: One record per permission grant.
- **Primary Key**: `permission_id` (UUID).
- **Foreign Keys**:
  - `target_object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `principal_id` references `security_principals(principal_id)` ON DELETE CASCADE.
- **Populating Platforms**: All platforms.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `permission_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Permission record ID. |
| `target_object_id` | UUID | No | None | FK -> `analytical_objects` | Canonical | Object being protected. |
| `principal_id` | UUID | Yes | None | FK -> `security_principals` | Canonical | Grantee principal. |
| `principal_name` | TEXT | Yes | None | None | Source-Native | Fallback principal name if unlinked. |
| `permission_type` | TEXT | No | None | None | Canonical | Grant mode (`READ`, `WRITE`, `EXECUTE`, `VIEW`, `ADMIN`). |
| `permission_source`| TEXT | No | None | None | Canonical | Origin of grant (`EXPLICIT_ACL`, `INHERITED`, `RLS_ROLE`). |
| `permission_properties`| JSONB| No | `'{}'::jsonb`| None | Source-Native | Permission flags and expiration metadata. |

---

### 31. `data_sources`
- **Purpose**: Underlying databases, data warehouses, files, or APIs feeding semantic models.
- **Data Grain**: One record per external data source connection.
- **Primary Key**: `data_source_id` (UUID).
- **Foreign Keys**: `object_id` (UNIQUE) references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Populating Platforms**: All platforms.
- **Security / Redaction**: Sensitive server hosts and queries are strictly redacted before persistence.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `data_source_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Data source surrogate key. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, UNIQUE | Canonical | Associated polymorphic analytical object. |
| `source_type` | TEXT | No | None | None | Canonical | Type (`POSTGRESQL`, `SNOWFLAKE`, `BIGQUERY`, `ORACLE`, `CSV`). |
| `source_name` | TEXT | No | None | None | Canonical | Friendly source connection name. |
| `server_reference` | TEXT | Yes | None | None | Operational | Redacted host/server connection reference. |
| `database_reference`| TEXT | Yes | None | None | Operational | Redacted target database name. |
| `schema_reference` | TEXT | Yes | None | None | Source-Native | Target database schema. |
| `connection_mode` | TEXT | Yes | None | None | Canonical | Ingestion mode (`IMPORT`, `DIRECT_QUERY`, `LIVE`, `EXTRACT`).|
| `query_language` | TEXT | Yes | None | None | Canonical | Query syntax (`SQL`, `M`, `REST`). |
| `query_text` | TEXT | Yes | None | None | Source-Native | Redacted source SQL/M query text. |
| `source_properties`| JSONB | No | `'{}'::jsonb` | None | Source-Native | Isolation levels, timeout settings, and driver metadata. |

---

### 32. `query_dependencies`
- **Purpose**: Query-to-query, view-to-table, or M-query reference dependencies.
- **Data Grain**: One record per directed query dependency.
- **Primary Key**: `query_dependency_id` (UUID).
- **Foreign Keys**:
  - `source_object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `target_object_id` references `analytical_objects(object_id)` ON DELETE SET NULL.
- **Populating Platforms**: Power BI (Power Query), Tableau (Custom SQL), ThoughtSpot.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `query_dependency_id`| UUID | No | `gen_random_uuid()` | PK | Canonical | Dependency record ID. |
| `source_object_id` | UUID | No | None | FK -> `analytical_objects` | Canonical | Query or calculation initiating the reference. |
| `target_object_id` | UUID | Yes | None | FK -> `analytical_objects` | Canonical | Resolved target object if present in canonical catalog. |
| `target_reference` | TEXT | Yes | None | None | Source-Native | Unresolved text reference (e.g. `raw_dw.claims_stg`). |
| `dependency_type` | TEXT | No | None | None | Canonical | Mode (`READS_TABLE`, `CALLS_VIEW`, `INVOKES_QUERY`). |
| `resolution_status`| TEXT | No | `'UNRESOLVED'`| CHECK in ('RESOLVED', 'INFERRED', 'UNRESOLVED') | Operational | Status of dependency resolution. |
| `dependency_properties`| JSONB| No | `'{}'::jsonb` | None | Source-Native | Column projection list and join conditions. |

---

### 33. `metadata_lineage_edges`
- **Purpose**: Directed graph of fine-grained metadata lineage across analytical objects.
- **Data Grain**: One record per directed lineage edge ($A \rightarrow B$).
- **Primary Key**: `lineage_edge_id` (UUID).
- **Foreign Keys**:
  - `asset_version_id` references `asset_versions(asset_version_id)` ON DELETE CASCADE.
  - `source_object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `target_object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Constraints**: CHECK (`source_object_id <> target_object_id`), CHECK (`confidence_score BETWEEN 0 AND 1`).
- **Populating Platforms**: All platforms.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `lineage_edge_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Lineage edge ID. |
| `asset_version_id` | UUID | No | None | FK -> `asset_versions` | Canonical | Containing asset version. |
| `source_object_id` | UUID | No | None | FK -> `analytical_objects` | Canonical | Upstream object (e.g. Table Column, Measure). |
| `target_object_id` | UUID | No | None | FK -> `analytical_objects` | Canonical | Downstream object (e.g. Visual, Derived Measure). |
| `edge_type` | TEXT | No | None | None | Canonical | Lineage role (`CALCULATES_FROM`, `BINDS_TO`, `FILTERS`). |
| `derivation_method`| TEXT | No | None | CHECK in ('PARSED', 'SOURCE_DECLARED', 'INFERRED', 'MANUAL') | Operational | How edge was discovered. |
| `confidence_score` | NUMERIC(5,4)| Yes| None | CHECK between 0.0000 and 1.0000 | Inferred | Confidence in edge accuracy. |
| `evidence` | JSONB | No | `'{}'::jsonb` | None | Inferred | Parsing token evidence or AST path supporting the edge. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

# Subsystem E: Excel-Specific Metadata

### 34. `spreadsheet_cells`
- **Purpose**: Granular cell coordinates, formulas, and cached evaluation snapshots in XLSX workbooks.
- **Data Grain**: One record per captured cell coordinate in a worksheet.
- **Primary Key**: `spreadsheet_cell_id` (UUID).
- **Foreign Keys**:
  - `asset_version_id` references `asset_versions(asset_version_id)` ON DELETE CASCADE.
  - `worksheet_object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Constraints**: UNIQUE (`worksheet_object_id`, `cell_address`).
- **Populating Platforms**: Excel (XLSX).

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `spreadsheet_cell_id`| UUID| No | `gen_random_uuid()` | PK | Canonical | Cell record ID. |
| `asset_version_id` | UUID | No | None | FK -> `asset_versions` | Canonical | Containing asset version. |
| `worksheet_object_id`| UUID| No | None | FK -> `analytical_objects`, UNIQUE (worksheet_object_id, cell_address) | Canonical | Worksheet analytical object. |
| `cell_address` | TEXT | No | None | Part of UNIQUE constraint | Source-Native | Coordinate string (e.g. `'D12'`). |
| `row_number` | INTEGER | No | None | None | Source-Native | 1-indexed row number. |
| `column_number` | INTEGER | No | None | None | Source-Native | 1-indexed column number. |
| `formula_text` | TEXT | Yes | None | None | Source-Native | Excel formula string (e.g. `'=SUM(C2:C10)/D1'`). |
| `cached_value` | JSONB | Yes | None | None | Source-Native | Cached precalculated result from file bytes. |
| `data_type` | TEXT | Yes | None | None | Canonical | Data type (`NUMBER`, `STRING`, `BOOLEAN`, `ERROR`). |
| `number_format` | TEXT | Yes | None | None | Source-Native | Cell format code (`$#,##0`). |
| `is_hidden` | BOOLEAN | No | `false` | None | Source-Native | Whether cell is in a hidden row/column. |
| `cell_properties` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Font styling, borders, fill colors. |

---

### 35. `pivot_caches`
- **Purpose**: PivotTable underlying data cache definitions and connection links in Excel.
- **Data Grain**: One record per pivot cache definition in a workbook.
- **Primary Key**: `pivot_cache_id` (UUID).
- **Foreign Keys**: `asset_version_id` references `asset_versions(asset_version_id)` ON DELETE CASCADE.
- **Populating Platforms**: Excel (XLSX).

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `pivot_cache_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Cache record ID. |
| `asset_version_id` | UUID | No | None | FK -> `asset_versions` | Canonical | Containing asset version. |
| `source_native_id` | TEXT | Yes | None | None | Source-Native | Cache record ID from OpenXML (`rId1`). |
| `source_type` | TEXT | No | None | None | Canonical | Cache source type (`WORKSHEET_RANGE`, `EXTERNAL`, `DATA_MODEL`).|
| `source_reference` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Sheet range reference (`'Sheet1!$A$1:$F$100'`). |
| `refresh_metadata` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Refresh-on-open settings and record counts. |
| `cache_properties` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Field definitions and OLAP cube settings. |

---

### 36. `pivot_tables`
- **Purpose**: PivotTable visual layouts and report views in Excel worksheets.
- **Data Grain**: One record per PivotTable in a workbook.
- **Primary Key**: `pivot_table_id` (UUID).
- **Foreign Keys**:
  - `object_id` (UNIQUE) references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `worksheet_object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `pivot_cache_id` references `pivot_caches(pivot_cache_id)` ON DELETE SET NULL.
- **Populating Platforms**: Excel (XLSX).

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `pivot_table_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | PivotTable surrogate key. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, UNIQUE | Canonical | Associated polymorphic analytical object. |
| `worksheet_object_id`| UUID| No | None | FK -> `analytical_objects` | Canonical | Host worksheet analytical object. |
| `pivot_cache_id` | UUID | Yes | None | FK -> `pivot_caches` | Canonical | Data cache supplying the pivot table. |
| `pivot_name` | TEXT | No | None | None | Canonical | Name of the PivotTable (e.g. `'PivotTable1'`). |
| `source_reference` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Target destination cell range on the sheet. |
| `pivot_properties` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Grand totals, subtotals, and compact/outline layout flags. |

---

### 37. `pivot_field_assignments`
- **Purpose**: Pivot field roles (Row, Column, Value, Filter, Page) and aggregations.
- **Data Grain**: One record per field assigned to a PivotTable axis.
- **Primary Key**: `pivot_field_assignment_id` (UUID).
- **Foreign Keys**:
  - `pivot_table_id` references `pivot_tables(pivot_table_id)` ON DELETE CASCADE.
  - `field_object_id` references `analytical_objects(object_id)` ON DELETE SET NULL.
- **Populating Platforms**: Excel (XLSX).

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `pivot_field_assignment_id`| UUID| No| `gen_random_uuid()` | PK | Canonical | Assignment record ID. |
| `pivot_table_id` | UUID | No | None | FK -> `pivot_tables` | Canonical | Host PivotTable ID. |
| `field_object_id` | UUID | Yes | None | FK -> `analytical_objects` | Canonical | Bound field/column analytical object if resolved. |
| `field_reference` | TEXT | No | None | None | Source-Native | Original field name in cache. |
| `assignment_role` | TEXT | No | None | CHECK in ('ROW', 'COLUMN', 'FILTER', 'VALUE', 'PAGE', 'OTHER') | Canonical | Placement axis in PivotTable. |
| `aggregation_type` | TEXT | Yes | None | None | Canonical | Aggregation function applied (`SUM`, `COUNT`, `AVERAGE`).|
| `field_order` | INTEGER | No | `0` | None | Source-Native | Order on shelf. |
| `assignment_properties`| JSONB| No | `'{}'::jsonb` | None | Source-Native | Custom subtotal, number format, and calculation as % of total.|

---

### 38. `spreadsheet_objects`
- **Purpose**: Named ranges, shapes, hyperlinks, and chart objects embedded in Excel sheets.
- **Data Grain**: One record per non-cell spreadsheet object.
- **Primary Key**: `spreadsheet_object_id` (UUID).
- **Foreign Keys**:
  - `object_id` (UNIQUE) references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `worksheet_object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Populating Platforms**: Excel (XLSX).

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `spreadsheet_object_id`| UUID| No | `gen_random_uuid()` | PK | Canonical | Spreadsheet object surrogate key. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, UNIQUE | Canonical | Associated polymorphic analytical object. |
| `worksheet_object_id`| UUID| No | None | FK -> `analytical_objects` | Canonical | Host worksheet object. |
| `object_subtype` | TEXT | No | None | None | Canonical | Subtype (`NAMED_RANGE`, `EMBEDDED_CHART`, `HYPERLINK`, `SHAPE`).|
| `range_reference` | TEXT | Yes | None | None | Source-Native | Range address (`'Sheet1!$B$5:$F$20'`). |
| `is_hidden` | BOOLEAN | No | `false` | None | Source-Native | Hidden status. |
| `object_properties` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Chart type, formula references, and hyperlink target URL. |

---

### 39. `spreadsheet_rules`
- **Purpose**: Conditional formatting rules, data validation rules, and cell constraints in Excel.
- **Data Grain**: One record per conditional formatting or validation rule.
- **Primary Key**: `spreadsheet_rule_id` (UUID).
- **Foreign Keys**:
  - `object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
  - `worksheet_object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Populating Platforms**: Excel (XLSX).

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `spreadsheet_rule_id`| UUID | No | `gen_random_uuid()` | PK | Canonical | Rule record ID. |
| `object_id` | UUID | Yes | None | FK -> `analytical_objects` | Canonical | Associated polymorphic analytical object. |
| `worksheet_object_id`| UUID | No | None | FK -> `analytical_objects` | Canonical | Host worksheet object. |
| `rule_type` | TEXT | No | None | None | Canonical | Category (`CONDITIONAL_FORMAT`, `DATA_VALIDATION`). |
| `range_reference` | TEXT | Yes | None | None | Source-Native | Evaluated range (`'A2:A100'`). |
| `formula_text` | TEXT | Yes | None | None | Source-Native | Rule evaluation formula (`'=A2>1000'`). |
| `expression_language`| TEXT | Yes | None | None | Source-Native | Formula syntax language. |
| `rule_properties` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Highlight formatting, color scale, or data validation alert.|

---

# Subsystem F: KPI Ontology and Domain Classification

### 40. `kpi_ontology_versions`
- **Purpose**: Version registry for the local 550+ KPI Ontology Bank.
- **Data Grain**: One record per loaded ontology bank release/version.
- **Primary Key**: `ontology_version_id` (UUID).
- **Constraints**:
  - `version_number` UNIQUE.
  - Partial Unique Index on `is_active` WHERE `is_active = true` (enforces exactly one active version).
- **Populating Platforms**: System Local Ontology Loader (local JSON only).

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `ontology_version_id`| UUID| No | `gen_random_uuid()` | PK | Canonical | Ontology version surrogate key. |
| `version_number` | TEXT | No | None | UNIQUE | Operational | Version label (e.g. `'2.1.0'`). |
| `content_hash` | TEXT | No | None | None | Operational | SHA-256 hash of entire local JSON ontology payload. |
| `schema_version` | TEXT | No | None | None | Operational | JSON Schema specification version. |
| `kpi_count` | INTEGER | No | `0` | None | Operational | Total count of validated KPIs in this version. |
| `created_by_user_id`| UUID | No | None | None | Governance | User or system process who published this version. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Version creation timestamp. |
| `change_summary` | TEXT | Yes | None | None | Governance | Release notes and change summary. |
| `is_active` | BOOLEAN | No | `false` | Partial UNIQUE | Governance | Active indicator. Enforced at most one true in system. |

---

### 41. `kpi_ontology_entries`
- **Purpose**: Canonical KPI definitions preserved from the local JSON ontology bank.
- **Data Grain**: One record per KPI definition within an ontology version.
- **Primary Key**: `ontology_entry_id` (UUID).
- **Foreign Keys**: `ontology_version_id` references `kpi_ontology_versions(ontology_version_id)` ON DELETE CASCADE.
- **Constraints**: UNIQUE (`ontology_version_id`, `kpi_code`).
- **Populating Platforms**: Local JSON Ontology Resource.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `ontology_entry_id`| UUID | No | `gen_random_uuid()` | PK | Canonical | Canonical KPI entry ID. |
| `ontology_version_id`| UUID| No | None | FK -> `kpi_ontology_versions`, UNIQUE (ontology_version_id, kpi_code) | Canonical | Containing ontology version. |
| `kpi_code` | TEXT | No | None | Part of UNIQUE constraint | Canonical | Stable business code (e.g. `'KPI_LOSS_RATIO'`). |
| `kpi_name` | TEXT | No | None | None | Canonical | Official corporate KPI name (e.g. `'Loss Ratio'`). |
| `kpi_description` | TEXT | Yes | None | None | Canonical | Concise definition and business purpose. |
| `business_domain` | TEXT | No | None | None | Canonical | Business domain code (e.g. `'CLAIMS_RISK'`). |
| `definition` | TEXT | No | None | None | Canonical | Complete formal business definition. |
| `formula` | TEXT | Yes | None | None | Canonical | Standard mathematical formula expression. |
| `unit` | TEXT | Yes | None | None | Canonical | Standard unit of measure (`PERCENTAGE`, `USD`, `DAYS`, `RATIO`).|
| `aggregation_method`| TEXT | Yes | None | None | Canonical | Standard aggregation (`RATIO`, `SUM`, `WEIGHTED_AVERAGE`). |
| `synonyms` | JSONB | No | `'[]'::jsonb` | None | Canonical | Array of accepted aliases and vernacular terms. |
| `ontology_payload` | JSONB | No | `'{}'::jsonb` | None | Canonical | Complete verbatim JSON entry from local schema (lossless preservation). |
| `source_kpi_id` | TEXT | Yes | None | None | Source-Native | Native identifier string from source JSON (e.g. `'INS-CLM-001'`). |
| `source_sector` | TEXT | Yes | None | None | Source-Native | Native industry sector taxonomy (e.g. `'Insurance'`). |
| `source_subdomain` | TEXT | Yes | None | None | Source-Native | Native sub-domain classification (e.g. `'Property & Casualty'`). |
| `source_line_of_business`| TEXT | Yes | None | None | Source-Native | Native LOB classification (e.g. `'Commercial Property'`). |
| `source_status` | TEXT | Yes | None | None | Source-Native | Native publication status string (e.g. `'Active'`, `'Deprecated'`). |
| `valid_dimensions` | JSONB | No | `'[]'::jsonb` | None | Canonical | Normalised list of valid analytical dimensions/breakdowns. |
| `enrichments` | JSONB | No | `'{}'::jsonb` | None | Canonical | Calculated metrics, benchmarks, tags, or operational metadata. |
| `source_created_at` | TIMESTAMPTZ | Yes | None | None | Source-Native | Native creation timestamp parsed to UTC ISO-8601. |
| `source_created_by` | TEXT | Yes | None | None | Source-Native | Native author or originating system identifier. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Database row creation timestamp. |

---

### 42. `business_domains`
- **Purpose**: Canonical business domain master catalog.
- **Data Grain**: One record per business domain.
- **Primary Key**: `domain_id` (UUID).
- **Constraints**: `domain_code` UNIQUE, `domain_name` UNIQUE.
- **Populating Platforms**: Seeded directly with the 6 mandatory enterprise domains.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `domain_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Domain surrogate key. |
| `domain_code` | TEXT | No | None | UNIQUE | Canonical | Stable code (`CLAIMS_RISK`, `LEGAL`, `UNDERWRITING`, etc.).|
| `domain_name` | TEXT | No | None | UNIQUE | Canonical | Display name (`Claims & Risk`, `Legal`, `Underwriting`). |
| `domain_description`| TEXT | Yes | None | None | Canonical | Domain scope and analytical boundaries. |
| `is_active` | BOOLEAN | No | `true` | None | Operational | Active status flag. |

---

### 43. `domain_classifications`
- **Purpose**: Classifications of assets, reports, pages, visuals, and KPI candidates into domains.
- **Data Grain**: One record per object-to-domain classification within a tenant boundary.
- **Primary Key**: `classification_id` (UUID).
- **Foreign Keys**:
  - `(target_object_id, asset_version_id)` references `analytical_objects(object_id, asset_version_id)` ON DELETE CASCADE.
  - `(asset_version_id, tenant_id)` references `asset_versions(asset_version_id, tenant_id)` ON DELETE CASCADE.
  - `domain_id` references `business_domains(domain_id)` ON DELETE CASCADE.
- **Constraints**:
  - Partial Unique Index on `(asset_version_id, target_object_id)` WHERE `(is_primary = true AND approval_status <> 'REJECTED')`.
- **Populating Platforms**: All platforms.
- **Security / Redaction**: Row Level Security (RLS) enabled.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `classification_id`| UUID | No | `gen_random_uuid()` | PK | Canonical | Classification record ID. |
| `asset_version_id` | UUID | No | None | FK -> `asset_versions` | Canonical | Version snapshot. |
| `tenant_id` | UUID | No | None | FK -> `asset_versions(tenant_id)` | Governance | Tenant boundary identifier for multi-tenant isolation. |
| `target_object_id` | UUID | No | None | FK -> `analytical_objects` | Canonical | Classified object (Report, Visual, Measure, Candidate). |
| `domain_id` | UUID | No | None | FK -> `business_domains` | Canonical | Assigned business domain. |
| `classification_method`| TEXT| No | None | CHECK in ('LLM', 'DETERMINISTIC', 'HUMAN', 'INHERITED') | Operational | Classification method used. |
| `confidence_score` | NUMERIC(5,4)| Yes| None | CHECK between 0.0000 and 1.0000 | Inferred | Confidence in domain assignment. |
| `rationale` | TEXT | Yes | None | None | Inferred | Explanation supporting domain classification. |
| `is_primary` | BOOLEAN | No | `false` | Partial UNIQUE | Governance | Primary domain flag (at most one effective primary). |
| `approval_status` | TEXT | No | `'PENDING'` | CHECK in ('PENDING', 'APPROVED', 'REJECTED', 'OVERRIDDEN') | Governance | Human approval status. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |
| `updated_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Maintained by `set_updated_at()` trigger. |

---

# Subsystem G: KPI Candidates and Mapping

### 44. `kpi_candidates`
- **Purpose**: Source calculations, measures, or visual cards discovered as potential corporate KPIs.
- **Data Grain**: One record per discovered KPI candidate within a tenant boundary.
- **Primary Key**: `kpi_candidate_id` (UUID).
- **Foreign Keys**:
  - `(asset_version_id, tenant_id)` references `asset_versions(asset_version_id, tenant_id)` ON DELETE CASCADE.
  - `(source_object_id, asset_version_id)` references `analytical_objects(object_id, asset_version_id)` ON DELETE CASCADE.
  - `business_domain_id` references `business_domains(domain_id)` ON DELETE SET NULL.
- **Populating Platforms**: All platforms.
- **Security / Redaction**: Row Level Security (RLS) enabled.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `kpi_candidate_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Candidate surrogate key. |
| `asset_version_id` | UUID | No | None | FK -> `asset_versions` | Canonical | Source asset version snapshot. |
| `tenant_id` | UUID | No | None | FK -> `asset_versions(tenant_id)` | Governance | Tenant boundary identifier for multi-tenant isolation. |
| `source_object_id` | UUID | No | None | FK -> `analytical_objects` | Canonical | Source calculation, visual, or cell object. |
| `candidate_name` | TEXT | No | None | None | Canonical | Discovered candidate name. |
| `candidate_description`| TEXT| Yes | None | None | Canonical | Candidate description or context. |
| `candidate_expression`| TEXT | Yes | None | None | Source-Native | Discovered formula or calculation expression. |
| `expression_language`| TEXT | Yes | None | None | Source-Native | Language (`DAX`, `EXCEL`, `M`, etc.). |
| `normalised_expression`| TEXT| Yes | None | None | Inferred | Normalised candidate expression. |
| `candidate_type` | TEXT | Yes | None | None | Canonical | Type (`RATIO`, `COUNT`, `RATE`, `SCORE`, `AMOUNT`). |
| `unit` | TEXT | Yes | None | None | Canonical | Inferred unit (`PERCENTAGE`, `CURRENCY`, `DAYS`). |
| `aggregation_type` | TEXT | Yes | None | None | Canonical | Inferred aggregation (`SUM`, `RATIO`, `AVG`). |
| `business_domain_id`| UUID | Yes | None | FK -> `business_domains` | Canonical | Inferred or assigned domain. |
| `candidate_evidence`| JSONB | No | `'{}'::jsonb` | None | Inferred | Discovery proof (visual prominence, usage, bindings). |
| `discovery_method` | TEXT | No | None | None | Operational | Method (`RULE_BASED`, `PARSER_DERIVED`, `LLM_ASSISTED`). |
| `discovery_version`| TEXT | No | None | None | Operational | Version of candidate discovery rule engine. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

### 45. `kpi_mapping_runs`
- **Purpose**: Batch execution record of ontology matching (LLM or deterministic fallback).
- **Data Grain**: One record per matching engine invocation run within a tenant boundary.
- **Primary Key**: `mapping_run_id` (UUID).
- **Foreign Keys**:
  - `(asset_version_id, tenant_id)` references `asset_versions(asset_version_id, tenant_id)` ON DELETE CASCADE.
  - `ontology_version_id` references `kpi_ontology_versions(ontology_version_id)` ON DELETE CASCADE.
- **Populating Platforms**: System Inference Engine.
- **Security / Redaction**: Row Level Security (RLS) enabled.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `mapping_run_id` | UUID | No | `gen_random_uuid()` | PK | Operational | Mapping run ID. |
| `asset_version_id` | UUID | No | None | FK -> `asset_versions` | Canonical | Source asset version being evaluated. |
| `tenant_id` | UUID | No | None | FK -> `asset_versions(tenant_id)` | Governance | Tenant boundary identifier for multi-tenant isolation. |
| `ontology_version_id`| UUID| No | None | FK -> `kpi_ontology_versions` | Canonical | Target KPI ontology version matched against. |
| `candidate_generation_version`| TEXT| No| None| None | Operational | Version of candidate generation engine. |
| `mapping_engine_version`| TEXT| No| None | None | Operational | Version of mapping matching pipeline. |
| `primary_engine` | TEXT | No | None | CHECK in ('LLM', 'DETERMINISTIC') | Operational | Primary engine selected for run. |
| `fallback_used` | BOOLEAN | No | `false` | None | Operational | Whether deterministic fallback was triggered. |
| `llm_provider` | TEXT | Yes | None | None | Operational | LLM provider name (e.g. `'Anthropic'`, `'VertexAI'`). |
| `llm_model` | TEXT | Yes | None | None | Operational | Specific LLM model identifier. |
| `prompt_version` | TEXT | Yes | None | None | Operational | Identifier of version-controlled prompt template. |
| `input_fingerprint`| TEXT | No | None | None | Operational | Hash of all candidate inputs, models, and prompts. |
| `run_status` | TEXT | No | `'PENDING'` | CHECK in ('PENDING', 'RUNNING', 'SUCCESSFUL', 'PARTIAL', 'FAILED', 'CANCELLED') | Operational | Execution status. |
| `started_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Run start timestamp. |
| `completed_at` | TIMESTAMPTZ | Yes | None | None | Operational | Run completion timestamp. |
| `error_summary` | TEXT | Yes | None | None | Operational | Sanitized error log if run failed. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

### 46. `kpi_mappings`
- **Purpose**: Current mapping relationship linking a source candidate to the ontology bank.
- **Data Grain**: One record per candidate mapping state within a tenant boundary.
- **Primary Key**: `kpi_mapping_id` (UUID).
- **Foreign Keys**:
  - `(kpi_candidate_id, asset_version_id)` references `kpi_candidates(kpi_candidate_id, asset_version_id)` ON DELETE CASCADE.
  - `(mapping_run_id, asset_version_id, ontology_version_id)` references `kpi_mapping_runs(mapping_run_id, asset_version_id, ontology_version_id)` ON DELETE CASCADE.
  - `(selected_ontology_entry_id, ontology_version_id)` references `kpi_ontology_entries(ontology_entry_id, ontology_version_id) ON DELETE SET NULL (selected_ontology_entry_id)`.
- **Constraints**: CHECK (`top_candidate_count BETWEEN 0 AND 3`).
- **Triggers**: `trg_protect_human_approval` (prohibits automated overwriting of approved human mappings, locks immutable candidate/version/ontology keys, and restricts status transitions to human SUPERSEDED/REVOKED/OVERRIDDEN).
- **Populating Platforms**: System Inference Engine & Human Governance.
- **Security / Redaction**: Row Level Security (RLS) enabled with FORCE ROW LEVEL SECURITY.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `kpi_mapping_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Mapping surrogate key. |
| `kpi_candidate_id` | UUID | No | None | FK -> `kpi_candidates` | Canonical | Target source KPI candidate. |
| `mapping_run_id` | UUID | No | None | FK -> `kpi_mapping_runs` | Operational | Executing mapping run. |
| `tenant_id` | UUID | No | None | FK -> `asset_versions(tenant_id)` | Governance | Tenant boundary identifier for multi-tenant isolation. |
| `asset_version_id` | UUID | No | None | FK -> `asset_versions` | Canonical | Asset version snapshot context. |
| `ontology_version_id`| UUID| No | None | FK -> `kpi_ontology_versions` | Canonical | Target ontology version. |
| `selected_ontology_entry_id`| UUID| Yes| None | FK -> `kpi_ontology_entries` | Canonical | Currently active/selected ontology match. |
| `mapping_status` | TEXT | No | `'PROPOSED'`| CHECK in ('PROPOSED', 'APPROVED', 'REJECTED', 'OVERRIDDEN', 'UNMAPPED', 'SUPERSEDED') | Governance | Current workflow status. |
| `decision_source` | TEXT | No | None | CHECK in ('LLM', 'DETERMINISTIC', 'HUMAN') | Governance | Authority that established current selection. |
| `top_candidate_count`| INTEGER| No| `0` | CHECK between 0 and 3 | Inferred | Number of ranked candidates generated (max 3). |
| `input_fingerprint`| TEXT | No | None | None | Operational | Input fingerprint for cache lookup. |
| `mapping_version` | INTEGER | No | `1` | None | Operational | Revision sequence integer. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |
| `updated_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Maintained by `set_updated_at()` trigger. |

---

### 47. `kpi_mapping_candidates`
- **Purpose**: Ranked match proposals (maximum top 3) from the matching engines.
- **Data Grain**: One record per proposed match candidate for a mapping.
- **Primary Key**: `mapping_candidate_id` (UUID).
- **Foreign Keys**:
  - `kpi_mapping_id` references `kpi_mappings(kpi_mapping_id)` ON DELETE CASCADE.
  - `ontology_entry_id` references `kpi_ontology_entries(ontology_entry_id)` ON DELETE CASCADE.
- **Constraints**:
  - UNIQUE (`kpi_mapping_id`, `ontology_entry_id`).
  - UNIQUE (`kpi_mapping_id`, `rank`).
  - CHECK (`rank BETWEEN 1 AND 3`).
  - CHECK (`confidence_score BETWEEN 0.0000 AND 1.0000`).
  - CHECK (`confidence_band IN ('HIGH', 'MEDIUM', 'LOW', 'UNCERTAIN')`).
- **Populating Platforms**: System Inference Engine (LLM or Deterministic).

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `mapping_candidate_id`| UUID| No| `gen_random_uuid()` | PK | Canonical | Proposed candidate record ID. |
| `kpi_mapping_id` | UUID | No | None | FK -> `kpi_mappings`, Part of UNIQUE constraints | Canonical | Parent mapping container. |
| `ontology_entry_id`| UUID | No | None | FK -> `kpi_ontology_entries`, Part of UNIQUE constraint | Canonical | Proposed canonical ontology KPI. |
| `rank` | INTEGER | No | None | Part of UNIQUE constraint, CHECK between 1 and 3 | Inferred | Proposal rank (1 = best, max 3). |
| `confidence_score` | NUMERIC(5,4)| No| None | CHECK between 0.0000 and 1.0000 | Inferred | Overall confidence score. |
| `confidence_band` | TEXT | No | None | CHECK in ('HIGH', 'MEDIUM', 'LOW', 'UNCERTAIN') | Inferred | Standardized confidence band. |
| `match_score` | NUMERIC | Yes| None | None | Inferred | Raw uncalibrated similarity score. |
| `name_similarity_score`| NUMERIC(5,4)| Yes| None| CHECK between 0 and 1 | Inferred | Trigram/token similarity on KPI names. |
| `definition_similarity_score`| NUMERIC(5,4)| Yes| None| CHECK between 0 and 1 | Inferred | Semantic similarity between definitions. |
| `formula_similarity_score`| NUMERIC(5,4)| Yes| None| CHECK between 0 and 1 | Inferred | AST/formula structural match score. |
| `context_similarity_score`| NUMERIC(5,4)| Yes| None| CHECK between 0 and 1 | Inferred | Visual and report context similarity. |
| `domain_compatibility_score`| NUMERIC(5,4)| Yes| None| CHECK between 0 and 1 | Inferred | Domain compatibility score. |
| `unit_compatibility_score`| NUMERIC(5,4)| Yes| None| CHECK between 0 and 1 | Inferred | Unit compatibility score. |
| `rationale` | TEXT | No | None | None | Inferred | Detailed reasoning explaining why this match was proposed. |
| `supporting_evidence`| JSONB| No | `'[]'::jsonb` | None | Inferred | Array of supporting evidence items. |
| `contradicting_evidence`| JSONB| No| `'[]'::jsonb`| None | Inferred | Array of contradicting evidence items. |
| `is_recommended` | BOOLEAN | No | `false` | None | Inferred | Recommended choice flag. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

### 48. `mapping_evidence`
- **Purpose**: Granular structured evidence supporting or contradicting a candidate match.
- **Data Grain**: One record per evidence item.
- **Primary Key**: `mapping_evidence_id` (UUID).
- **Foreign Keys**:
  - `mapping_candidate_id` references `kpi_mapping_candidates(mapping_candidate_id)` ON DELETE CASCADE.
  - `source_object_id` references `analytical_objects(object_id)` ON DELETE SET NULL.
- **Constraints**: CHECK (`polarity IN ('SUPPORTS', 'CONTRADICTS', 'NEUTRAL')`).
- **Populating Platforms**: System Inference Engine.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `mapping_evidence_id`| UUID| No | `gen_random_uuid()` | PK | Canonical | Evidence record ID. |
| `mapping_candidate_id`| UUID| No | None | FK -> `kpi_mapping_candidates` | Canonical | Target proposed candidate match. |
| `evidence_type` | TEXT | No | None | None | Canonical | Evidence type (`NAME_TOKEN`, `DAX_SYNTAX`, `VISUAL_ROLE`, `UNIT_MATCH`).|
| `source_object_id` | UUID | Yes | None | FK -> `analytical_objects` | Canonical | Supporting metadata object in catalog. |
| `evidence_text` | TEXT | No | None | None | Inferred | Natural language explanation of evidence. |
| `evidence_payload` | JSONB | No | `'{}'::jsonb` | None | Inferred | Structured diagnostic payload. |
| `polarity` | TEXT | No | `'SUPPORTS'` | CHECK in ('SUPPORTS', 'CONTRADICTS', 'NEUTRAL') | Inferred | Polarity of evidence. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

# Subsystem H: Human Review, Approval, Overrides

### 49. `mapping_reviews`
- **Purpose**: Review actions taken by human subject matter experts.
- **Data Grain**: One record per user review interaction.
- **Primary Key**: `mapping_review_id` (UUID).
- **Foreign Keys**:
  - `kpi_mapping_id` references `kpi_mappings(kpi_mapping_id)` ON DELETE CASCADE.
  - `(mapping_candidate_id, kpi_mapping_id)` references `kpi_mapping_candidates(mapping_candidate_id, kpi_mapping_id) ON DELETE SET NULL (mapping_candidate_id)`.
- **Populating Platforms**: Governance Web Application.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `mapping_review_id`| UUID | No | `gen_random_uuid()` | PK | Governance | Review record ID. |
| `kpi_mapping_id` | UUID | No | None | FK -> `kpi_mappings` | Governance | Reviewed mapping. |
| `mapping_candidate_id`| UUID| Yes| None | FK -> `kpi_mapping_candidates` | Governance | Candidate reviewed (composite foreign key guarantees mapping alignment). |
| `reviewer_user_id` | UUID | No | None | None | Governance | User ID of reviewer. |
| `review_action` | TEXT | No | None | CHECK in ('APPROVE', 'REJECT', 'CHOOSE_ANOTHER', 'ADD_KPI', 'REQUEST_REMAPPING', 'MARK_UNMAPPED') | Governance | Action taken. |
| `review_status` | TEXT | No | `'COMPLETED'`| CHECK in ('PENDING', 'COMPLETED', 'WITHDRAWN') | Governance | Status of review item. |
| `review_comment` | TEXT | Yes | None | None | Governance | Optional reviewer comments. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

### 50. `mapping_approvals`
- **Purpose**: Formal approval ledger; approved mappings become immutable ground truth.
- **Data Grain**: One record per formal approval event.
- **Primary Key**: `mapping_approval_id` (UUID).
- **Foreign Keys**:
  - `kpi_mapping_id` references `kpi_mappings(kpi_mapping_id)` ON DELETE CASCADE.
  - `(approved_mapping_candidate_id, kpi_mapping_id)` references `kpi_mapping_candidates(mapping_candidate_id, kpi_mapping_id) ON DELETE SET NULL (approved_mapping_candidate_id)`.
- **Constraints**:
  - Partial Unique Index on `kpi_mapping_id` WHERE `approval_status = 'APPROVED'` (strictly enforces one active approval per mapping).
- **Triggers**: Protected via `trg_protect_human_approval` ensuring immutable mapping binding.
- **Populating Platforms**: Governance Web Application.
- **Security / Redaction**: Row Level Security (RLS) enabled with FORCE ROW LEVEL SECURITY via parent mapping tenant join.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `mapping_approval_id`| UUID| No | `gen_random_uuid()` | PK | Governance | Approval ledger record ID. |
| `kpi_mapping_id` | UUID | No | None | FK -> `kpi_mappings`, Partial UNIQUE | Governance | Target mapping. Exactly one active approval permitted. |
| `approved_mapping_candidate_id`| UUID| Yes| None | FK -> `kpi_mapping_candidates` | Governance | The specific candidate match that was approved (composite FK). |
| `approved_by_user_id`| UUID| No | None | None | Governance | Authoritative approver user ID. |
| `approval_status` | TEXT | No | `'APPROVED'` | CHECK in ('APPROVED', 'REVOKED', 'SUPERSEDED') | Governance | Status of approval. |
| `approval_version` | INTEGER | No | `1` | None | Governance | Approval revision counter. |
| `approved_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Governance | Approval timestamp. |
| `revoked_at` | TIMESTAMPTZ | Yes | None | None | Governance | Revocation timestamp if superseded or revoked. |
| `revocation_reason`| TEXT | Yes | None | None | Governance | Reason for approval revocation. |

---

### 51. `mapping_overrides`
- **Purpose**: User overrides of engine proposals with mandatory rationale for continuous learning.
- **Data Grain**: One record per human override.
- **Primary Key**: `override_id` (UUID).
- **Foreign Keys**:
  - `kpi_mapping_id` references `kpi_mappings(kpi_mapping_id)` ON DELETE CASCADE.
  - `(mapping_candidate_id, kpi_mapping_id)` references `kpi_mapping_candidates(mapping_candidate_id, kpi_mapping_id) ON DELETE SET NULL (mapping_candidate_id)`.
  - `previous_ontology_entry_id` references `kpi_ontology_entries(ontology_entry_id)` ON DELETE SET NULL.
  - `replacement_ontology_entry_id` references `kpi_ontology_entries(ontology_entry_id)` ON DELETE SET NULL.
  - `supersedes_override_id` references `mapping_overrides(override_id)` ON DELETE SET NULL.
- **Constraints**: CHECK (`length(trim(override_justification)) > 0`).
- **Triggers**: `trg_prevent_override_cycle` (prohibits cyclic and self-referencing `supersedes_override_id` chains).
- **Populating Platforms**: Governance Web Application.
- **Security / Redaction**: Row Level Security (RLS) enabled with FORCE ROW LEVEL SECURITY via parent mapping tenant join.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `override_id` | UUID | No | `gen_random_uuid()` | PK | Governance | Override surrogate key. |
| `kpi_mapping_id` | UUID | No | None | FK -> `kpi_mappings` | Governance | Parent mapping. |
| `mapping_candidate_id`| UUID| Yes| None | FK -> `kpi_mapping_candidates` | Governance | Candidate rejected or replaced (composite FK). |
| `override_type` | TEXT | No | None | CHECK in ('REJECT', 'SELECT_ALTERNATIVE', 'ADD_KPI', 'FORCE_UNMAPPED', 'REMAP', 'OTHER') | Governance | Action type. |
| `previous_ontology_entry_id`| UUID| Yes| None| FK -> `kpi_ontology_entries` | Governance | Previously proposed KPI. |
| `replacement_ontology_entry_id`| UUID| Yes| None| FK -> `kpi_ontology_entries` | Governance | Selected replacement KPI. |
| `override_justification`| TEXT| No| None | CHECK length(trim) > 0 | Governance | Mandatory non-empty business justification text. |
| `normalised_justification`| TEXT| No| None| None | Governance | Cleaned text for trigram and FTS indexing. |
| `justification_hash`| TEXT | No | None | None | Operational | Hash of normalized justification for deduplication. |
| `created_by_user_id`| UUID | No | None | None | Governance | Author of override. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Override timestamp. |
| `is_active` | BOOLEAN | No | `true` | None | Governance | Active indicator. |
| `supersedes_override_id`| UUID| Yes| None | Self-FK -> `mapping_overrides` | Governance | Prior override superseded by this record (acyclic trigger-verified). |

---

### 52. `metadata_field_reviews`
- **Purpose**: Human overrides and reviews of specific extracted metadata attributes.
- **Data Grain**: One record per reviewed metadata attribute path within a tenant boundary.
- **Primary Key**: `field_review_id` (UUID).
- **Foreign Keys**:
  - `(target_object_id, asset_version_id)` references `analytical_objects(object_id, asset_version_id)` ON DELETE CASCADE.
  - `(asset_version_id, tenant_id)` references `asset_versions(asset_version_id, tenant_id)` ON DELETE CASCADE.
- **Populating Platforms**: Governance Web Application.
- **Security / Redaction**: Row Level Security (RLS) enabled.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `field_review_id` | UUID | No | `gen_random_uuid()` | PK | Governance | Field review ID. |
| `asset_version_id` | UUID | No | None | FK -> `asset_versions` | Canonical | Asset version snapshot. |
| `tenant_id` | UUID | No | None | FK -> `asset_versions(tenant_id)` | Governance | Tenant boundary identifier for multi-tenant isolation. |
| `target_object_id` | UUID | No | None | FK -> `analytical_objects` | Canonical | Target object whose metadata was corrected. |
| `field_path` | TEXT | No | None | None | Canonical | Dot-notated attribute path (`canonical_name`, `description`).|
| `source_value_hash`| TEXT | No | None | None | Operational | Hash of raw extracted value. |
| `proposed_value` | JSONB | No | None | None | Inferred | Suggested replacement value. |
| `approved_value` | JSONB | Yes | None | None | Governance | Final human-approved value. |
| `review_status` | TEXT | No | `'PENDING'` | CHECK in ('PENDING', 'APPROVED', 'REJECTED', 'OVERRIDDEN') | Governance | Status of field review. |
| `reviewed_by_user_id`| UUID| Yes| None | None | Governance | Reviewer user ID. |
| `reviewed_at` | TIMESTAMPTZ | Yes | None | None | Governance | Review timestamp. |
| `override_justification`| TEXT| Yes| None | None | Governance | Reason for correcting metadata attribute. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

# Subsystem I: KPI Rationalisation

### 53. `kpi_equivalence_candidates`
- **Purpose**: Discovered potential duplicates, redundant calculations, or equivalent metrics.
- **Data Grain**: One record per candidate equivalence pair ($A, B$).
- **Primary Key**: `equivalence_candidate_id` (UUID).
- **Foreign Keys**:
  - `source_kpi_candidate_id` references `kpi_candidates(kpi_candidate_id)` ON DELETE CASCADE.
  - `target_kpi_candidate_id` references `kpi_candidates(kpi_candidate_id)` ON DELETE CASCADE.
- **Constraints**:
  - CHECK (`source_kpi_candidate_id <> target_kpi_candidate_id`).
  - Symmetrical Unique Index on `(LEAST(source_kpi_candidate_id, target_kpi_candidate_id), GREATEST(source_kpi_candidate_id, target_kpi_candidate_id))` preventing duplicate inverted pairs.
  - CHECK (`equivalence_score BETWEEN 0.0000 AND 1.0000`).
- **Populating Platforms**: KPI Rationalisation Scanner.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `equivalence_candidate_id`| UUID| No| `gen_random_uuid()`| PK | Canonical | Equivalence candidate ID. |
| `source_kpi_candidate_id`| UUID| No| None | FK -> `kpi_candidates`, CHECK distinct | Canonical | First KPI candidate. |
| `target_kpi_candidate_id`| UUID| No| None | FK -> `kpi_candidates`, CHECK distinct | Canonical | Second KPI candidate. |
| `comparison_type` | TEXT | No | None | None | Canonical | Comparison mode (`EXACT_FORMULA`, `SEMANTIC_EQUIVALENT`, `NAME_SIMILARITY`).|
| `name_similarity_score`| NUMERIC(5,4)| Yes| None| CHECK between 0 and 1 | Inferred | Token similarity score between candidate names. |
| `definition_similarity_score`| NUMERIC(5,4)| Yes| None| CHECK between 0 and 1 | Inferred | Semantic similarity score. |
| `formula_similarity_score`| NUMERIC(5,4)| Yes| None| CHECK between 0 and 1 | Inferred | AST/formula logic equivalence score. |
| `unit_compatibility_score`| NUMERIC(5,4)| Yes| None| CHECK between 0 and 1 | Inferred | Unit compatibility. |
| `dependency_similarity_score`| NUMERIC(5,4)| Yes| None| CHECK between 0 and 1 | Inferred | Lineage input similarity. |
| `equivalence_score` | NUMERIC(5,4)| No | None | CHECK between 0.0000 and 1.0000 | Inferred | Composite equivalence score. |
| `evidence` | JSONB | No | `'{}'::jsonb` | None | Inferred | Structured evidence comparing the two candidates. |
| `review_status` | TEXT | No | `'PROPOSED'`| CHECK in ('PROPOSED', 'APPROVED', 'REJECTED', 'SUPERSEDED') | Governance | Review status of recommendation. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

### 54. `kpi_rationalisation_decisions`
- **Purpose**: Human-governed consolidation decisions across equivalent metrics.
- **Data Grain**: One record per governance rationalisation decision.
- **Primary Key**: `rationalisation_decision_id` (UUID).
- **Foreign Keys**:
  - `equivalence_candidate_id` references `kpi_equivalence_candidates(equivalence_candidate_id)` ON DELETE CASCADE.
  - `canonical_kpi_candidate_id` references `kpi_candidates(kpi_candidate_id)` ON DELETE SET NULL.
- **Populating Platforms**: Governance Web Application.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `rationalisation_decision_id`| UUID| No| `gen_random_uuid()`| PK | Governance | Decision surrogate key. |
| `equivalence_candidate_id`| UUID| No| None | FK -> `kpi_equivalence_candidates` | Governance | Equivalence candidate evaluated. |
| `decision_type` | TEXT | No | None | CHECK in ('MERGE', 'CONSOLIDATE', 'RETAIN_SEPARATELY', 'REJECT') | Governance | Action decided by committee. |
| `canonical_kpi_candidate_id`| UUID| Yes| None| FK -> `kpi_candidates` | Governance | The preferred canonical candidate retained. |
| `approved_by_user_id`| UUID | No | None | None | Governance | Authorizing steward user ID. |
| `decision_justification`| TEXT| No | None | None | Governance | Mandatory business justification for decision. |
| `decision_status` | TEXT | No | `'PROPOSED'`| CHECK in ('PROPOSED', 'APPROVED', 'REJECTED', 'EXECUTED', 'REVERSED') | Governance | Lifecycle status of decision. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |
| `updated_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Maintained by `set_updated_at()` trigger. |

---

### 55. `rationalisation_evidence`
- **Purpose**: Visual usage, dependency proof, and lineage supporting a rationalisation decision.
- **Data Grain**: One record per supporting evidence item for a decision.
- **Primary Key**: `rationalisation_evidence_id` (UUID).
- **Foreign Keys**: `rationalisation_decision_id` references `kpi_rationalisation_decisions(rationalisation_decision_id)` ON DELETE CASCADE.
- **Populating Platforms**: KPI Rationalisation Scanner & Governance App.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `rationalisation_evidence_id`| UUID| No| `gen_random_uuid()`| PK | Governance | Evidence record ID. |
| `rationalisation_decision_id`| UUID| No| None | FK -> `kpi_rationalisation_decisions`| Governance | Parent decision ID. |
| `evidence_type` | TEXT | No | None | None | Canonical | Category (`LINEAGE_OVERLAP`, `USAGE_FREQUENCY`, `FORMULA_MATCH`).|
| `evidence_text` | TEXT | No | None | None | Governance | Explanation of evidence. |
| `evidence_payload` | JSONB | No | `'{}'::jsonb` | None | Governance | Structured details (dashboards affected, consumer counts). |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

# Subsystem J: Operations and Audit

### 56. `platform_capabilities`
- **Purpose**: Metadata extraction capabilities and feature support matrix across platforms.
- **Data Grain**: One record per platform/artifact/metadata feature tuple.
- **Primary Key**: `platform_capability_id` (UUID).
- **Constraints**: UNIQUE (`platform`, `artifact_type`, `metadata_type`).
- **Populating Platforms**: System configuration matrix.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `platform_capability_id`| UUID| No| `gen_random_uuid()` | PK | Operational | Capability surrogate key. |
| `platform` | TEXT | No | None | CHECK in ('POWER_BI', 'TABLEAU', 'EXCEL', 'THOUGHTSPOT', 'MICROSTRATEGY'), Part of UNIQUE | Canonical | Source BI platform. |
| `artifact_type` | TEXT | No | None | Part of UNIQUE constraint | Canonical | Artifact category (`TMDL`, `PBIR`, `TWB`, `XLSX`). |
| `metadata_type` | TEXT | No | None | Part of UNIQUE constraint | Canonical | Metadata feature (`CALCULATIONS`, `LINEAGE`, `RLS`, `VISUALS`).|
| `capability_status`| TEXT | No | None | CHECK in ('SUPPORTED', 'PARTIAL', 'UNSUPPORTED', 'RUNTIME_DEPENDENT') | Operational | Support level. |
| `minimum_source_version`| TEXT| Yes| None | None | Operational | Earliest supported version. |
| `maximum_source_version`| TEXT| Yes| None | None | Operational | Latest verified version. |
| `notes` | TEXT | Yes | None | None | Operational | Technical adapter notes and caveats. |
| `capability_properties`| JSONB| No | `'{}'::jsonb` | None | Operational | Detailed parser flag matrix. |

---

### 57. `parser_runs`
- **Purpose**: Execution logs of platform-specific metadata parsing adapters.
- **Data Grain**: One record per parser execution on a version or artifact within a tenant boundary.
- **Primary Key**: `parser_run_id` (UUID).
- **Foreign Keys**:
  - `(asset_version_id, tenant_id)` references `asset_versions(asset_version_id, tenant_id)` ON DELETE CASCADE.
  - `source_artifact_id` references `source_artifacts(source_artifact_id)` ON DELETE SET NULL.
- **Populating Platforms**: Platform Metadata Adapters.
- **Security / Redaction**: Row Level Security (RLS) enabled.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `parser_run_id` | UUID | No | `gen_random_uuid()` | PK | Operational | Execution record ID. |
| `asset_version_id` | UUID | No | None | FK -> `asset_versions` | Canonical | Asset version parsed. |
| `tenant_id` | UUID | No | None | FK -> `asset_versions(tenant_id)` | Governance | Tenant boundary identifier for multi-tenant isolation. |
| `source_artifact_id`| UUID | Yes | None | FK -> `source_artifacts` | Operational | Sub-artifact parsed if file-scoped. |
| `platform` | TEXT | No | None | None | Canonical | Platform adapter executed. |
| `parser_name` | TEXT | No | None | None | Operational | Adapter class name (`PowerBiPbipAdapter`, `TableauXmlAdapter`).|
| `parser_version` | TEXT | No | None | None | Operational | Adapter semantic version. |
| `run_status` | TEXT | No | `'PENDING'` | CHECK in ('PENDING', 'RUNNING', 'SUCCESSFUL', 'PARTIAL', 'FAILED', 'SKIPPED') | Operational | Execution status. |
| `objects_extracted`| INTEGER | No | `0` | None | Operational | Total metadata entities extracted. |
| `warnings_count` | INTEGER | No | `0` | None | Operational | Count of non-fatal warnings logged. |
| `errors_count` | INTEGER | No | `0` | None | Operational | Count of errors encountered. |
| `started_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Execution start timestamp. |
| `completed_at` | TIMESTAMPTZ | Yes | None | None | Operational | Execution finish timestamp. |
| `run_metadata` | JSONB | No | `'{}'::jsonb` | None | Operational | Memory usage, CPU time, and thread telemetry. |

---

### 58. `extraction_errors`
- **Purpose**: Detailed parser warnings, partial failure diagnostics, and syntax errors.
- **Data Grain**: One record per diagnostic, warning, or error during parsing.
- **Primary Key**: `extraction_error_id` (UUID).
- **Foreign Keys**:
  - `parser_run_id` references `parser_runs(parser_run_id)` ON DELETE CASCADE.
  - `source_artifact_id` references `source_artifacts(source_artifact_id)` ON DELETE SET NULL.
- **Populating Platforms**: Platform Metadata Adapters.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `extraction_error_id`| UUID| No | `gen_random_uuid()` | PK | Operational | Error record ID. |
| `parser_run_id` | UUID | No | None | FK -> `parser_runs` | Operational | Associated parser run. |
| `source_artifact_id`| UUID | Yes | None | FK -> `source_artifacts` | Operational | File artifact where error occurred. |
| `object_locator` | JSONB | No | `'{}'::jsonb` | None | Source-Native | Precise coordinates (line number, column, XML XPath). |
| `severity` | TEXT | No | None | CHECK in ('INFO', 'WARNING', 'ERROR', 'FATAL') | Operational | Diagnostic severity. |
| `error_code` | TEXT | No | None | None | Operational | Standard system error identifier. |
| `error_message` | TEXT | No | None | None | Operational | Sanitized error diagnostic message. |
| `is_recoverable` | BOOLEAN | No | `false` | None | Operational | Whether parser recovered and continued extraction. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

### 59. `object_tags`
- **Purpose**: Multi-source taxonomy, business tags, and source metadata labels attached to objects.
- **Data Grain**: One record per tag-object association.
- **Primary Key**: `object_tag_id` (UUID).
- **Foreign Keys**: `object_id` references `analytical_objects(object_id)` ON DELETE CASCADE.
- **Constraints**:
  - Unique Index on `(object_id, tag_name, COALESCE(tag_value, ''))` handling null values uniformly.
- **Populating Platforms**: All platforms.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `object_tag_id` | UUID | No | `gen_random_uuid()` | PK | Canonical | Tag record ID. |
| `object_id` | UUID | No | None | FK -> `analytical_objects`, Part of UNIQUE index | Canonical | Tagged analytical object. |
| `tag_name` | TEXT | No | None | Part of UNIQUE index | Canonical | Tag label or category (e.g. `'Certified'`, `'Confidential'`).|
| `tag_value` | TEXT | Yes | None | Handled via COALESCE in UNIQUE index | Canonical | Optional tag value (e.g. `'Gold'`, `'Tier-1'`). |
| `tag_source` | TEXT | No | `'SOURCE'` | CHECK in ('SOURCE', 'CANONICAL', 'INFERRED', 'USER') | Governance | Origin of tag. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Creation timestamp. |

---

### 60. `mapping_audit_events`
- **Purpose**: Complete immutable audit trail of state transitions in the mapping lifecycle.
- **Data Grain**: One record per mapping state change event within a tenant boundary.
- **Primary Key**: `mapping_audit_event_id` (UUID).
- **Foreign Keys**: `kpi_mapping_id` references `kpi_mappings(kpi_mapping_id)` ON DELETE RESTRICT (prohibits parent cascade deletion).
- **Triggers**: Protected via `trg_mapping_audit_immutable` (strictly prohibits UPDATE and DELETE mutations).
- **Populating Platforms**: All Governance and Inference services.
- **Security / Redaction**: Row Level Security (RLS) enabled.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `mapping_audit_event_id`| UUID| No| `gen_random_uuid()` | PK | Governance | Audit event record ID. |
| `tenant_id` | UUID | No | None | None | Governance | Tenant boundary identifier for multi-tenant isolation. |
| `kpi_mapping_id` | UUID | Yes| None | FK -> `kpi_mappings` ON DELETE RESTRICT | Governance | Current mapping reference (nullable if parent archived). |
| `target_kpi_mapping_id`| UUID | No | None | None | Governance | Immutable mapping snapshot key (persists even if mapping row changes). |
| `actor_user_id` | UUID | No | None | None | Governance | User or system agent who initiated the state change. |
| `event_type` | TEXT | No | None | None | Governance | Transition type (`CREATED`, `PROPOSED`, `APPROVED`, `OVERRIDDEN`).|
| `previous_state` | JSONB | No | `'{}'::jsonb` | None | Governance | Complete serialized snapshot of prior mapping state. |
| `new_state` | JSONB | No | `'{}'::jsonb` | None | Governance | Serialized snapshot of new state. |
| `event_reason` | TEXT | Yes | None | None | Governance | Contextual reason for transition. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Event timestamp. |

---

### 61. `ontology_change_events`
- **Purpose**: Immutable audit log recording additions and modifications to the local ontology bank.
- **Data Grain**: One record per change applied to the local ontology.
- **Primary Key**: `ontology_change_event_id` (UUID).
- **Foreign Keys**:
  - `ontology_version_id` references `kpi_ontology_versions(ontology_version_id)` ON DELETE RESTRICT (prohibits cascade deletion).
  - `ontology_entry_id` references `kpi_ontology_entries(ontology_entry_id)` ON DELETE SET NULL.
- **Triggers**: Protected via `trg_ontology_audit_immutable` (strictly prohibits UPDATE and DELETE mutations).
- **Populating Platforms**: Local Ontology Management Service.

| Column | SQL Type | Nullable | Default | Constraints | Classification | Description & Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `ontology_change_event_id`| UUID| No| `gen_random_uuid()` | PK | Governance | Event surrogate key. |
| `ontology_version_id`| UUID| No | None | FK -> `kpi_ontology_versions` ON DELETE RESTRICT | Governance | Affected ontology version (protected against deletion). |
| `ontology_entry_id`| UUID | Yes | None | FK -> `kpi_ontology_entries` | Governance | Affected KPI entry if applicable. |
| `actor_user_id` | UUID | No | None | None | Governance | User who authored or authorized the change. |
| `change_type` | TEXT | No | None | CHECK in ('ADD', 'UPDATE', 'DEPRECATE', 'RESTORE', 'IMPORT') | Governance | Nature of change. |
| `previous_payload` | JSONB | Yes | None | None | Governance | JSON payload of entry prior to change. |
| `new_payload` | JSONB | Yes | None | None | Governance | JSON payload after change. |
| `change_justification`| TEXT| No | None | None | Governance | Mandatory justification for ontology modification. |
| `created_at` | TIMESTAMPTZ | No | `clock_timestamp()` | None | Operational | Event timestamp. |
