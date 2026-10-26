# KPI Intelligence Platform

Universal Metadata Extraction, KPI Ontology Mapping, Human Approval, and KPI Rationalisation Platform.

---

## Azure Cosmos DB for NoSQL Architecture (Production)

The production database is architected natively around **Azure Cosmos DB for NoSQL** as the sole production storage engine, featuring 4 optimized containers, partition keys, selective indexing policies, and document aggregates.

👉 **[Cosmos DB Architecture Blueprint](docs/cosmos_nosql_architecture.md)**

### Production Containers & Partitioning
- **`metadata_catalog`** (`/tenant_id`): Logical assets, asset versions, report document aggregates (embedded pages, visuals, bindings), semantic models (embedded tables, columns, measures, relationships), and lineage edges.
- **`kpi_governance`** (`/tenant_id`): Discovered KPI candidates, automated mappings with ranked LLM evidence, human approvals, manual overrides, and deduplication rationalisations.
- **`kpi_ontology`** (`/business_domain`): Curated standard KPI Bank entries, versions, and canonical business domains (`CLAIMS_RISK`, `UNDERWRITING`, `LEGAL`, `FINANCE`, `OPERATIONS`, `GENERAL`).
- **`operational_audit`** (`/tenant_id`): Extraction telemetry, parser diagnostics, and governance audit events (configured with 90-day automatic TTL).

---

## Local Developer Experience & Full Relational Mirror

The local developer experience provides a coordinated two-tier SQLite database (`local_data/kpi_intelligence.sqlite3`):
1. **Full Canonical Relational Mirror**: All 61 canonical relational tables containing all 636 columns, primary keys, active foreign key enforcement (`PRAGMA foreign_keys = ON;`), unique constraints, and deterministic synthetic fixtures. Visible and inspectable in SQLite tools (e.g. DB Browser for SQLite).
2. **Cosmos Document Store**: The `cosmos_documents` table emulating Cosmos DB point-reads, partition queries, continuation tokens, and ETags for offline adapter testing without cloud costs.

### Critical Production Safety Guard
To guarantee safety, setting `KPI_ENVIRONMENT=production` or `KPI_STORAGE_BACKEND=sqlite` in production or staging triggers a hard, fail-closed runtime exception on application startup.

### Developer CLI Tooling
```bash
# Initialize both relational (61 tables) and Cosmos stores with synthetic seed records
python3 -m backend.storage.cli init --all --seed

# Initialize only the 61 canonical relational tables with seed records
python3 -m backend.storage.cli init --relational --seed

# Validate relational schema completeness (61 tables, 636 columns) and foreign key integrity
python3 -m backend.storage.cli validate --relational

# Inspect database summary (relational subsystems breakdown + Cosmos documents)
python3 -m backend.storage.cli inspect --all

# Run cross-representation reconciliation across PostgreSQL, Cosmos, and SQLite
python3 scripts/validate_cross_representation.py

# Export relational tables to JSON bundle
python3 -m backend.storage.cli export --relational --output local_data/relational_export.json

# Reset / clear all local data
python3 -m backend.storage.cli reset --all --force
```

---

## Power BI PBIP Metadata Ingestion

```bash
# Ingest the reference Power BI project into the canonical repository
python3 scripts/ingest_powerbi.py --source reference

# Dry-run parsing without persistence
python3 scripts/ingest_powerbi.py --source reference --dry-run
```

---

## Azure Provisioning & PostgreSQL Migration

```bash
# Provision production Cosmos DB database and containers (dry-run)
python3 scripts/provision_cosmos.py --dry-run

# Replay relational data into Cosmos document format and verify reconciliation
python3 scripts/migrate_postgres_to_cosmos.py --dry-run
```

---

## Test Execution

```bash
# Run the complete test suite (79 passing tests across connectors, lifecycle, SQLite mirror, and Cosmos)
python3 -m unittest discover -s tests -p "test_*.py" -v

# Run SQLite relational mirror integration and foreign key tests
python3 -m unittest tests/test_sqlite_relational_mirror.py

# Run SQLite document repository integration & concurrency tests
python3 -m unittest tests/test_sqlite_repository.py

# Run Cosmos DB adapter unit & throttling retry tests
python3 -m unittest tests/test_cosmos_adapter.py

# Run Cosmos & domain model conformance tests
python3 -m unittest tests/test_cosmos_conformance.py
```

---

## Legacy Relational Documentation (PostgreSQL 61 Tables)

For historical reference and migration mapping, the legacy 61-table PostgreSQL documentation is preserved under:
👉 **[Legacy Relational Model Documentation](docs/kpi-intelligence-canonical-model/README.md)**


