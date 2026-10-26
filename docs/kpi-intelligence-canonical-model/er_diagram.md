# KPI Intelligence — Canonical Entity-Relationship (ER) Specifications

This document contains the structural data models and entity-relationship specifications for the KPI Intelligence canonical schema (`kpi_intel`). 

To preserve readability, diagrams are decomposed into modular subsystem blocks using standard Mermaid `erDiagram` syntax, followed by detailed cardinality rationales and an exhaustive table-coverage verification map.

---

## 1. High-Level Canonical Architecture Overview

```mermaid
erDiagram
    assets ||--o{ asset_versions : "has versions"
    asset_versions ||--o{ analytical_objects : "contains entities"
    analytical_objects ||--o{ calculations : "defines logic"
    analytical_objects ||--o{ visuals : "presents in UI"
    calculations ||--o{ kpi_candidates : "discovers"
    kpi_candidates ||--o{ kpi_mappings : "maps to ontology"
    kpi_ontology_entries ||--o{ kpi_mappings : "matches canonical"
    kpi_mappings ||--o{ mapping_approvals : "human approves"
    kpi_candidates ||--o{ kpi_equivalence_candidates : "evaluates overlap"
    kpi_equivalence_candidates ||--o{ kpi_rationalisation_decisions : "rationalises"
```

---

## 2. Subsystem ERDs

### ERD 1 — Asset Registry, Ingestion, and Ingestion Audit
Covers physical file intake, version snapshotting, source file tracking, parser execution telemetry, and extraction diagnostics.

```mermaid
erDiagram
    assets {
        uuid asset_id PK
        uuid tenant_id
        text platform
        text asset_name
        uuid current_version_id FK
    }
    asset_versions {
        uuid asset_version_id PK
        uuid asset_id FK
        integer version_number
        text content_hash
        text structure_hash
    }
    ingestion_events {
        uuid ingestion_id PK
        uuid asset_version_id FK
        uuid uploaded_by_user_id
        text original_filename
        text ingestion_status
    }
    source_artifacts {
        uuid source_artifact_id PK
        uuid asset_version_id FK
        text relative_path
        text artifact_type
    }
    analytical_objects {
        uuid object_id PK
        uuid asset_version_id FK
        uuid source_artifact_id FK
        text platform
        text canonical_name
    }
    parser_runs {
        uuid parser_run_id PK
        uuid asset_version_id FK
        uuid source_artifact_id FK
        text parser_name
        text run_status
    }
    extraction_errors {
        uuid extraction_error_id PK
        uuid parser_run_id FK
        uuid source_artifact_id FK
        text severity
        text error_code
    }

    assets ||--o{ asset_versions : "versioned as"
    assets ||--o| asset_versions : "points to current"
    asset_versions ||--o{ ingestion_events : "logged in"
    asset_versions ||--o{ source_artifacts : "unpacks into"
    asset_versions ||--o{ analytical_objects : "extracts"
    source_artifacts ||--o{ analytical_objects : "originates"
    asset_versions ||--o{ parser_runs : "parsed by"
    source_artifacts ||--o{ parser_runs : "targets"
    parser_runs ||--o{ extraction_errors : "logs errors"
    source_artifacts ||--o{ extraction_errors : "error location"
```

*Relationship Rationales*:
- `assets -> asset_versions` ($1:N$): A logical BI asset (e.g. "Underwriting Executive Dashboard") changes over time, producing immutable version records.
- `assets -> asset_versions (current_version_id)` ($1:0..1$): Fast resolution of the active canonical head version.
- `asset_versions -> ingestion_events` ($1:0..N$): A repeat upload of an identical byte stream creates a new upload event without duplicating version metadata.
- `asset_versions -> source_artifacts` ($1:1..N$): Package-based formats (.pbip, .twbx, .zip) unpack into distinct physical source files.
- `parser_runs -> extraction_errors` ($1:0..N$): Any extraction anomalies or syntax parsing failures are logged against the exact execution run.

---

### ERD 2A — Universal Presentation Layer (Reports, Pages, Visuals)
Models user-facing reporting layouts, canvas structures, visual types, field bindings, formatting properties, and visual interactions.

```mermaid
erDiagram
    analytical_objects {
        uuid object_id PK
        text canonical_name
        text object_type
    }
    reports {
        uuid report_id PK
        uuid object_id FK
        text report_type
        uuid default_page_object_id FK
    }
    report_pages {
        uuid page_id PK
        uuid report_id FK
        uuid object_id FK
        text page_name
        integer page_order
    }
    visuals {
        uuid visual_id PK
        uuid page_id FK
        uuid object_id FK
        text visual_type
        text visual_title
    }
    visual_bindings {
        uuid visual_binding_id PK
        uuid visual_id FK
        uuid object_id FK
        text binding_role
        integer binding_order
    }
    visual_properties {
        uuid visual_property_id PK
        uuid visual_id FK
        text property_path
        jsonb property_value
    }
    visual_interactions {
        uuid visual_interaction_id PK
        uuid source_visual_id FK
        uuid target_visual_id FK
        text interaction_type
    }
    visual_types {
        uuid visual_type_id PK
        text platform
        text native_type
        text canonical_type
    }
    bookmarks {
        uuid bookmark_id PK
        uuid object_id FK
        text bookmark_name
    }
    report_navigation {
        uuid report_navigation_id PK
        uuid source_object_id FK
        uuid target_object_id FK
        text navigation_type
    }

    analytical_objects ||--|| reports : "identifies"
    reports ||--o{ report_pages : "contains pages"
    analytical_objects ||--|| report_pages : "identifies"
    report_pages ||--o{ visuals : "contains visuals"
    analytical_objects ||--|| visuals : "identifies"
    visuals ||--o{ visual_bindings : "binds"
    analytical_objects ||--o{ visual_bindings : "bound to"
    visuals ||--o{ visual_properties : "configures"
    visuals ||--o{ visual_interactions : "initiates"
    visuals ||--o{ visual_interactions : "receives"
    analytical_objects ||--o{ bookmarks : "stores state"
    analytical_objects ||--o{ report_navigation : "navigates from"
    analytical_objects ||--o{ report_navigation : "navigates to"
```

*Relationship Rationales*:
- `analytical_objects -> reports / report_pages / visuals` ($1:1$): Polymorphous canonical identity pattern; every concrete BI entity inherits universal properties (`is_hidden`, `metadata_completeness`, `source_metadata`).
- `visuals -> visual_bindings` ($1:N$): Connects visual components to underlying measures/columns across chart roles (e.g. X-axis, Y-axis, Color, Tooltip).
- `visuals -> visual_interactions` ($1:N$): Cross-filtering and highlighting graph among visual pairs on a canvas.

---

### ERD 2B — Semantic Models, Tables, Columns, and Calculations
Models logical tabular models, entities, attributes, calculation expressions (DAX, M, Tableau, Excel formulas), hierarchies, and joins.

```mermaid
erDiagram
    analytical_objects {
        uuid object_id PK
        text canonical_name
    }
    semantic_models {
        uuid semantic_model_id PK
        uuid object_id FK
        text model_name
        text model_type
    }
    data_tables {
        uuid data_table_id PK
        uuid object_id FK
        uuid semantic_model_id FK
        text table_name
        text table_type
    }
    data_columns {
        uuid data_column_id PK
        uuid object_id FK
        uuid data_table_id FK
        text column_name
        text data_type
    }
    calculations {
        uuid calculation_id PK
        uuid object_id FK
        uuid semantic_model_id FK
        uuid data_table_id FK
        uuid data_column_id FK
        text calculation_name
        text expression_language
        text expression_text
    }
    relationships {
        uuid relationship_id PK
        uuid object_id FK
        uuid from_table_id FK
        uuid to_table_id FK
        text cardinality
        text join_type
    }
    model_partitions {
        uuid model_partition_id PK
        uuid semantic_model_id FK
        text partition_name
    }
    hierarchies {
        uuid hierarchy_id PK
        uuid object_id FK
        uuid semantic_model_id FK
        text hierarchy_name
    }
    hierarchy_levels {
        uuid hierarchy_level_id PK
        uuid hierarchy_id FK
        uuid level_object_id FK
        text level_name
        integer level_order
    }
    parameters {
        uuid parameter_id PK
        uuid object_id FK
        text parameter_name
        text data_type
    }
    named_expressions {
        uuid named_expression_id PK
        uuid object_id FK
        text expression_name
        text expression_language
    }

    analytical_objects ||--|| semantic_models : "identifies"
    semantic_models ||--o{ data_tables : "contains"
    analytical_objects ||--|| data_tables : "identifies"
    data_tables ||--o{ data_columns : "contains"
    analytical_objects ||--|| data_columns : "identifies"
    semantic_models ||--o{ calculations : "scoped to"
    data_tables ||--o{ calculations : "homes"
    data_columns ||--o| calculations : "backs calculated column"
    analytical_objects ||--|| calculations : "identifies"
    data_tables ||--o{ relationships : "from table"
    data_tables ||--o{ relationships : "to table"
    analytical_objects ||--|| relationships : "identifies"
    semantic_models ||--o{ model_partitions : "partitions"
    semantic_models ||--o{ hierarchies : "defines"
    analytical_objects ||--|| hierarchies : "identifies"
    hierarchies ||--o{ hierarchy_levels : "levels"
    analytical_objects ||--|| parameters : "identifies"
    analytical_objects ||--|| named_expressions : "identifies"
```

*Relationship Rationales*:
- `semantic_models -> data_tables -> data_columns` ($1:N:M$): Standard relational container hierarchy representing tabular or dimensional schemas.
- `calculations -> semantic_models / data_tables / data_columns`: Calculations may be model-level explicit measures, table-scoped measures, or calculated columns backed by physical column records.
- `relationships -> data_tables` ($N:2$): Captures joins and active model relationships between source and target tables with defined cardinalities (`1:N`, `N:1`, `1:1`, `N:M`).

---

### ERD 3 — Filters, Security, Data Sources, and Dependency Lineage
Captures presentation and model filters, RLS/OLS security roles, principals, data sources, and lineage edges.

```mermaid
erDiagram
    analytical_objects {
        uuid object_id PK
        text canonical_name
    }
    filters {
        uuid filter_id PK
        uuid object_id FK
        text filter_name
        text filter_scope
    }
    filter_assignments {
        uuid filter_assignment_id PK
        uuid filter_id FK
        uuid target_object_id FK
        uuid field_object_id FK
    }
    security_roles {
        uuid security_role_id PK
        uuid object_id FK
        text role_name
        text role_type
    }
    security_role_filters {
        uuid security_role_filter_id PK
        uuid security_role_id FK
        uuid target_object_id FK
        text expression_text
    }
    security_principals {
        uuid principal_id PK
        uuid tenant_id
        text platform
        text principal_name
    }
    security_object_permissions {
        uuid permission_id PK
        uuid target_object_id FK
        uuid principal_id FK
        text permission_type
    }
    data_sources {
        uuid data_source_id PK
        uuid object_id FK
        text source_type
        text source_name
    }
    query_dependencies {
        uuid query_dependency_id PK
        uuid source_object_id FK
        uuid target_object_id FK
        text dependency_type
    }
    metadata_lineage_edges {
        uuid lineage_edge_id PK
        uuid asset_version_id FK
        uuid source_object_id FK
        uuid target_object_id FK
        text edge_type
        text derivation_method
    }

    analytical_objects ||--|| filters : "identifies"
    filters ||--o{ filter_assignments : "assigned via"
    analytical_objects ||--o{ filter_assignments : "targets"
    analytical_objects ||--|| security_roles : "identifies"
    security_roles ||--o{ security_role_filters : "contains rules"
    analytical_objects ||--o{ security_role_filters : "secures object"
    security_principals ||--o{ security_object_permissions : "granted to"
    analytical_objects ||--o{ security_object_permissions : "governs"
    analytical_objects ||--|| data_sources : "identifies"
    analytical_objects ||--o{ query_dependencies : "depends"
    analytical_objects ||--o{ query_dependencies : "referenced"
    analytical_objects ||--o{ metadata_lineage_edges : "lineage source"
    analytical_objects ||--o{ metadata_lineage_edges : "lineage target"
```

*Relationship Rationales*:
- `security_roles -> security_role_filters` ($1:N$): Isolates RLS/OLS policy definitions from standard visual slicing filters.
- `metadata_lineage_edges -> analytical_objects` ($N:2$): Forms a directed metadata graph connecting source databases to tables, calculations, and visuals.

---

### ERD 4 — Excel-Specific Structures
Captures spreadsheet cell coordinates, formulas, cached values, PivotTables, and conditional formatting.

```mermaid
erDiagram
    analytical_objects {
        uuid object_id PK
    }
    asset_versions {
        uuid asset_version_id PK
    }
    spreadsheet_cells {
        uuid spreadsheet_cell_id PK
        uuid asset_version_id FK
        uuid worksheet_object_id FK
        text cell_address
        text formula_text
    }
    pivot_caches {
        uuid pivot_cache_id PK
        uuid asset_version_id FK
        text source_type
    }
    pivot_tables {
        uuid pivot_table_id PK
        uuid object_id FK
        uuid worksheet_object_id FK
        uuid pivot_cache_id FK
        text pivot_name
    }
    pivot_field_assignments {
        uuid pivot_field_assignment_id PK
        uuid pivot_table_id FK
        uuid field_object_id FK
        text assignment_role
    }
    spreadsheet_objects {
        uuid spreadsheet_object_id PK
        uuid object_id FK
        uuid worksheet_object_id FK
        text object_subtype
    }
    spreadsheet_rules {
        uuid spreadsheet_rule_id PK
        uuid object_id FK
        uuid worksheet_object_id FK
        text rule_type
    }

    asset_versions ||--o{ spreadsheet_cells : "contains cells"
    analytical_objects ||--o{ spreadsheet_cells : "worksheet container"
    asset_versions ||--o{ pivot_caches : "contains caches"
    analytical_objects ||--|| pivot_tables : "identifies"
    analytical_objects ||--o{ pivot_tables : "worksheet container"
    pivot_caches ||--o{ pivot_tables : "supplies data"
    pivot_tables ||--o{ pivot_field_assignments : "assigns fields"
    analytical_objects ||--|| spreadsheet_objects : "identifies"
    analytical_objects ||--o{ spreadsheet_objects : "worksheet container"
    analytical_objects ||--o{ spreadsheet_rules : "worksheet rules"
```

*Relationship Rationales*:
- `pivot_caches -> pivot_tables` ($1:N$): Multiple PivotTable layouts in Excel frequently share a single underlying memory cache or external query.
- `pivot_tables -> pivot_field_assignments` ($1:N$): Fields placed into Row, Column, Filter, or Value areas.

---

### ERD 5 — KPI Ontology and Mapping Engine
Models the local 550+ KPI bank, domain classification, discovery candidates, mapping runs, and ranked candidates.

```mermaid
erDiagram
    kpi_ontology_versions {
        uuid ontology_version_id PK
        text version_number
        text content_hash
        boolean is_active
    }
    kpi_ontology_entries {
        uuid ontology_entry_id PK
        uuid ontology_version_id FK
        text kpi_code
        text kpi_name
        text business_domain
    }
    business_domains {
        uuid domain_id PK
        text domain_code
        text domain_name
    }
    domain_classifications {
        uuid classification_id PK
        uuid asset_version_id FK
        uuid target_object_id FK
        uuid domain_id FK
        boolean is_primary
    }
    kpi_candidates {
        uuid kpi_candidate_id PK
        uuid asset_version_id FK
        uuid source_object_id FK
        text candidate_name
        uuid business_domain_id FK
    }
    kpi_mapping_runs {
        uuid mapping_run_id PK
        uuid asset_version_id FK
        uuid ontology_version_id FK
        text primary_engine
        boolean fallback_used
    }
    kpi_mappings {
        uuid kpi_mapping_id PK
        uuid kpi_candidate_id FK
        uuid mapping_run_id FK
        uuid ontology_version_id FK
        uuid selected_ontology_entry_id FK
        text mapping_status
    }
    kpi_mapping_candidates {
        uuid mapping_candidate_id PK
        uuid kpi_mapping_id FK
        uuid ontology_entry_id FK
        integer rank
        numeric confidence_score
    }
    mapping_evidence {
        uuid mapping_evidence_id PK
        uuid mapping_candidate_id FK
        text evidence_type
        text polarity
    }

    kpi_ontology_versions ||--o{ kpi_ontology_entries : "contains"
    business_domains ||--o{ domain_classifications : "categorizes"
    analytical_objects ||--o{ domain_classifications : "classified"
    analytical_objects ||--o{ kpi_candidates : "originates candidate"
    business_domains ||--o{ kpi_candidates : "tagged domain"
    kpi_ontology_versions ||--o{ kpi_mapping_runs : "runs against"
    kpi_candidates ||--o{ kpi_mappings : "mapped"
    kpi_mapping_runs ||--o{ kpi_mappings : "produces"
    kpi_mappings ||--o{ kpi_mapping_candidates : "proposes (max 3)"
    kpi_ontology_entries ||--o{ kpi_mapping_candidates : "matched entry"
    kpi_mapping_candidates ||--o{ mapping_evidence : "justified by"
```

*Relationship Rationales*:
- `kpi_ontology_versions -> kpi_ontology_entries` ($1:N$): Full versioning of the local JSON ontology bank.
- `kpi_mappings -> kpi_mapping_candidates` ($1:1..3$): Database check constraints strictly limit ranked proposals to at most 3 items (ranks 1, 2, 3).
- `kpi_mapping_candidates -> mapping_evidence` ($1:0..N$): Granular evidence items with explicit polarity (`SUPPORTS`, `CONTRADICTS`, `NEUTRAL`).

---

### ERD 6 — Human Review, Governance Approvals, and Overrides
Models SME reviews, immutable approvals, required override justifications, and audit ledgers.

```mermaid
erDiagram
    kpi_mappings {
        uuid kpi_mapping_id PK
        text mapping_status
    }
    mapping_reviews {
        uuid mapping_review_id PK
        uuid kpi_mapping_id FK
        uuid mapping_candidate_id FK
        text review_action
    }
    mapping_approvals {
        uuid mapping_approval_id PK
        uuid kpi_mapping_id FK
        uuid approved_mapping_candidate_id FK
        text approval_status
    }
    mapping_overrides {
        uuid override_id PK
        uuid kpi_mapping_id FK
        text override_justification
        boolean is_active
    }
    metadata_field_reviews {
        uuid field_review_id PK
        uuid target_object_id FK
        text field_path
        text review_status
    }
    mapping_audit_events {
        uuid mapping_audit_event_id PK
        uuid kpi_mapping_id FK
        text event_type
    }
    ontology_change_events {
        uuid ontology_change_event_id PK
        uuid ontology_version_id FK
        text change_type
    }

    kpi_mappings ||--o{ mapping_reviews : "reviewed in"
    kpi_mappings ||--o{ mapping_approvals : "approved in"
    kpi_mappings ||--o{ mapping_overrides : "overridden in"
    analytical_objects ||--o{ metadata_field_reviews : "field reviews"
    kpi_mappings ||--o{ mapping_audit_events : "audits"
    kpi_ontology_versions ||--o{ ontology_change_events : "tracks changes"
```

*Relationship Rationales*:
- `kpi_mappings -> mapping_approvals` ($1:0..N$ with Unique Partial Index): Exactly one active approval is permitted per mapping (`WHERE approval_status = 'APPROVED'`).
- `mapping_overrides -> mapping_overrides (supersedes_override_id)` ($1:0..1$): Forms a self-referencing lineage chain of human override adjustments.

---

### ERD 7 — KPI Rationalisation and Platform Operations
Models cross-asset duplication discovery, human consolidation decisions, and platform capabilities.

```mermaid
erDiagram
    kpi_candidates {
        uuid kpi_candidate_id PK
        text candidate_name
    }
    kpi_equivalence_candidates {
        uuid equivalence_candidate_id PK
        uuid source_kpi_candidate_id FK
        uuid target_kpi_candidate_id FK
        text comparison_type
        numeric equivalence_score
    }
    kpi_rationalisation_decisions {
        uuid rationalisation_decision_id PK
        uuid equivalence_candidate_id FK
        uuid canonical_kpi_candidate_id FK
        text decision_type
    }
    rationalisation_evidence {
        uuid rationalisation_evidence_id PK
        uuid rationalisation_decision_id FK
        text evidence_text
    }
    platform_capabilities {
        uuid platform_capability_id PK
        text platform
        text artifact_type
        text capability_status
    }
    object_tags {
        uuid object_tag_id PK
        uuid object_id FK
        text tag_name
        text tag_value
    }

    kpi_candidates ||--o{ kpi_equivalence_candidates : "source candidate"
    kpi_candidates ||--o{ kpi_equivalence_candidates : "target candidate"
    kpi_equivalence_candidates ||--o{ kpi_rationalisation_decisions : "decision"
    kpi_candidates ||--o{ kpi_rationalisation_decisions : "canonical target"
    kpi_rationalisation_decisions ||--o{ rationalisation_evidence : "evidence"
    analytical_objects ||--o{ object_tags : "tagged"
```

---

## 3. Supplementary 61-Table Coverage Verification Map

Every single table in the `kpi_intel` schema appears in the ER diagrams as verified below:

| # | Table Name | Subsystem | Appearing Diagram |
| :--- | :--- | :--- | :--- |
| 1 | `assets` | Subsystem A | High-Level, ERD 1 |
| 2 | `asset_versions` | Subsystem A | High-Level, ERD 1, ERD 4 |
| 3 | `ingestion_events` | Subsystem A | ERD 1 |
| 4 | `source_artifacts` | Subsystem A | ERD 1 |
| 5 | `analytical_objects` | Subsystem B | High-Level, ERD 1, ERD 2A, ERD 2B, ERD 3, ERD 4, ERD 5, ERD 6, ERD 7 |
| 6 | `reports` | Subsystem B | ERD 2A |
| 7 | `report_pages` | Subsystem B | ERD 2A |
| 8 | `visuals` | Subsystem B | High-Level, ERD 2A |
| 9 | `visual_bindings` | Subsystem B | ERD 2A |
| 10 | `visual_properties` | Subsystem B | ERD 2A |
| 11 | `visual_interactions` | Subsystem B | ERD 2A |
| 12 | `visual_types` | Subsystem B | ERD 2A |
| 13 | `bookmarks` | Subsystem B | ERD 2A |
| 14 | `report_navigation` | Subsystem B | ERD 2A |
| 15 | `semantic_models` | Subsystem C | ERD 2B |
| 16 | `data_tables` | Subsystem C | ERD 2B |
| 17 | `data_columns` | Subsystem C | ERD 2B |
| 18 | `calculations` | Subsystem C | High-Level, ERD 2B |
| 19 | `relationships` | Subsystem C | ERD 2B |
| 20 | `model_partitions` | Subsystem C | ERD 2B |
| 21 | `hierarchies` | Subsystem C | ERD 2B |
| 22 | `hierarchy_levels` | Subsystem C | ERD 2B |
| 23 | `parameters` | Subsystem C | ERD 2B |
| 24 | `named_expressions` | Subsystem C | ERD 2B |
| 25 | `filters` | Subsystem D | ERD 3 |
| 26 | `filter_assignments` | Subsystem D | ERD 3 |
| 27 | `security_roles` | Subsystem D | ERD 3 |
| 28 | `security_role_filters` | Subsystem D | ERD 3 |
| 29 | `security_principals` | Subsystem D | ERD 3 |
| 30 | `security_object_permissions` | Subsystem D | ERD 3 |
| 31 | `data_sources` | Subsystem D | ERD 3 |
| 32 | `query_dependencies` | Subsystem D | ERD 3 |
| 33 | `metadata_lineage_edges` | Subsystem D | ERD 3 |
| 34 | `spreadsheet_cells` | Subsystem E | ERD 4 |
| 35 | `pivot_caches` | Subsystem E | ERD 4 |
| 36 | `pivot_tables` | Subsystem E | ERD 4 |
| 37 | `pivot_field_assignments` | Subsystem E | ERD 4 |
| 38 | `spreadsheet_objects` | Subsystem E | ERD 4 |
| 39 | `spreadsheet_rules` | Subsystem E | ERD 4 |
| 40 | `kpi_ontology_versions` | Subsystem F | ERD 5, ERD 6 |
| 41 | `kpi_ontology_entries` | Subsystem F | High-Level, ERD 5 |
| 42 | `business_domains` | Subsystem F | ERD 5 |
| 43 | `domain_classifications` | Subsystem F | ERD 5 |
| 44 | `kpi_candidates` | Subsystem G | High-Level, ERD 5, ERD 7 |
| 45 | `kpi_mapping_runs` | Subsystem G | ERD 5 |
| 46 | `kpi_mappings` | Subsystem G | High-Level, ERD 5, ERD 6 |
| 47 | `kpi_mapping_candidates` | Subsystem G | ERD 5 |
| 48 | `mapping_evidence` | Subsystem G | ERD 5 |
| 49 | `mapping_reviews` | Subsystem H | ERD 6 |
| 50 | `mapping_approvals` | Subsystem H | High-Level, ERD 6 |
| 51 | `mapping_overrides` | Subsystem H | ERD 6 |
| 52 | `metadata_field_reviews` | Subsystem H | ERD 6 |
| 53 | `kpi_equivalence_candidates` | Subsystem I | High-Level, ERD 7 |
| 54 | `kpi_rationalisation_decisions`| Subsystem I | High-Level, ERD 7 |
| 55 | `rationalisation_evidence` | Subsystem I | ERD 7 |
| 56 | `platform_capabilities` | Subsystem J | ERD 7 |
| 57 | `parser_runs` | Subsystem J | ERD 1 |
| 58 | `extraction_errors` | Subsystem J | ERD 1 |
| 59 | `object_tags` | Subsystem J | ERD 7 |
| 60 | `mapping_audit_events` | Subsystem J | ERD 6 |
| 61 | `ontology_change_events` | Subsystem J | ERD 6 |
