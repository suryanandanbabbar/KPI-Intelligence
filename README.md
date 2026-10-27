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
# Run the complete test suite (162 passing tests across FastAPI, React E2E, governance, SQLite, and Cosmos)
python3 -m unittest discover -s tests -p "test_*.py" -v

# Run FastAPI backend integration tests
python3 -m unittest tests/test_fastapi_api.py

# Run End-to-End FastAPI + React smoke tests
python3 -m unittest tests/test_e2e_fastapi_react.py

# Run KPI mapping, domain segregation, and human governance workflow tests
python3 -m unittest tests/test_kpi_mapping_workflow.py

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

## FastAPI Backend & React Frontend

### 1. FastAPI Backend Server
The REST API is implemented with **FastAPI**, exposing OpenAPI documentation, Pydantic request/response validation, dependency-injected services, tenant authorization guards, and CORS configuration.

```bash
# Install backend dependencies in virtual environment
pip install fastapi uvicorn pydantic httpx

# Start the FastAPI ASGI server (default: port 8080)
uvicorn backend.api.app:app --host 127.0.0.1 --port 8080 --reload

# Interactive Swagger / OpenAPI Documentation
open http://127.0.0.1:8080/docs
```

### 2. React Frontend Application
The user interface is a real **React 19** single-page application built with **Vite**, adhering to Apple Human Interface Guidelines with an 8-view persistent workflow navigation, responsive typography, slide-over candidate drawers, and accessible theme controls.

```bash
# Navigate to frontend directory
cd frontend

# Install frontend dependencies
npm install

# Start Vite React development server (proxies /api to http://127.0.0.1:8080)
npm run dev

# Build for production (outputs optimized static bundle to frontend/dist)
npm run build
```

### 3. Canonical API Contract
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Diagnostic service health check |
| `GET` | `/ready` | Readiness check |
| `GET` | `/api/v1/workspace/summary` | Aggregated metrics & domain distributions |
| `GET` | `/api/v1/domains` | 5 canonical segregated domains + legacy operations |
| `GET` | `/api/v1/domains/{domain}/metrics` | Domain-specific proposal counts |
| `GET` | `/api/v1/metadata/fields` | Extracted canonical metadata fields |
| `GET` | `/api/v1/metadata/fields/{field_id}` | Detailed metadata field profile |
| `POST` | `/api/v1/metadata/fields/{field_id}/domain` | Human domain correction with audit logging |
| `POST` | `/api/v1/mapping/run` | Execute mapping pipeline (LLM + deterministic fallback) |
| `GET` | `/api/v1/mapping/fields/{field_id}/candidates` | Top-3 ranked KPI candidates with structured evidence |
| `GET` | `/api/v1/mappings/proposals` | Proposals awaiting human review queue |
| `POST` | `/api/v1/mapping/approve` | Human approval (HIGH confidence never auto-approves) |
| `POST` | `/api/v1/mapping/reject` | Human rejection with reason tracking |
| `POST` | `/api/v1/mapping/override` | Manual override (strictly validates $\ge 10$ chars justification) |
| `GET` | `/api/v1/kpi-bank/search` | Search reference KPI Bank definitions & formulas |
| `POST` | `/api/v1/kpi-bank/create` | Create governed schema-compliant KPI in KPI Bank |
| `GET` | `/api/v1/overrides` | Learned override rules & fingerprint reuse counts |
| `POST` | `/api/v1/overrides/invalidate` | Invalidate learned override rule |
| `GET` | `/api/v1/audit/history` | Chronological immutable governance audit trail |
| `GET` | `/api/v1/llm/status` | Non-sensitive operational status of Azure Llama integration |

---

## Azure AI Foundry Llama Integration

The semantic matching engine integrates with Llama models hosted on **Azure AI Foundry** (or Azure OpenAI Service), configured through 5 exact environment variables.

### 1. Configuration & Semantics
Configure through process environment variables or local `.env` (copied from `.env.example`):

```dotenv
# Exact 5 Environment Variables:
AZURE_DEPLOYMENT=llama-3.3-70b-instruct
AZURE_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_LLAMAKEY=your-secret-api-key
AZURE_DEPLOYMENT_NAME=llama-33-deployment
AZURE_OPENAI_API_VERSION=2024-06-01
```

#### Established Variable Semantics:
- **`AZURE_DEPLOYMENT`**: The model identifier / deployment slug passed in the request body as the `"model"` property (e.g. `llama-3.3-70b-instruct`).
- **`AZURE_DEPLOYMENT_NAME`**: The Azure deployment resource name used in URL route paths (`/openai/deployments/{AZURE_DEPLOYMENT_NAME}/chat/completions`).
- **`AZURE_ENDPOINT`**: The base resource URI (e.g. `https://<resource>.openai.azure.com/` or `https://<model>.eastus2.models.ai.azure.com/`).
- **`AZURE_LLAMAKEY`**: Secret authentication token passed via `api-key` and `Authorization: Bearer` headers (server-side ONLY; never logged or returned to clients).
- **`AZURE_OPENAI_API_VERSION`**: Azure API version query parameter (e.g. `2024-06-01` or `2024-05-01-preview`).

### 2. Operational Safety & Fallback Behavior
- **Zero-Secret Diagnostics**: Verify configuration status via `GET /api/v1/llm/status` or the workspace summary without making billable calls or exposing secrets.
- **Deterministic Fallback**: If configuration is absent, the client encounters transient throttling (HTTP 429), timeouts, invalid JSON, or unknown KPI IDs, the pipeline automatically fails over to the deterministic matching engine with non-secret category codes (`MISSING_CONFIGURATION`, `THROTTLED`, `TIMEOUT`, `UNKNOWN_KPI_ID`, `INVALID_RESPONSE`).
- **Human Invariant**: A `HIGH` confidence proposal is **never auto-approved**. Human review is strictly mandatory.

### 3. Testing Azure Llama Integration
```bash
# Run mocked Azure AI Foundry Llama integration tests
python3 -m unittest tests/test_azure_llama_integration.py

# Run complete test suite (includes deterministic fallback and FastAPI routes)
python3 -m unittest discover -s tests -p "test_*.py" -v
```

---

---

## Local Database & Cloud Disclaimer

- **Preserved Database**: The local developer SQLite mirror at `local_data/kpi_intelligence.sqlite3` is preserved and must never be mutated or reset during testing. Automated test suites run exclusively against isolated temporary test databases.
- **Mandatory Cloud Disclaimer**: *Live Azure Cosmos DB verification remains out of scope. No live Cosmos DB connectivity, read/write, migration, or roundtrip claims are made by this task.*

---

## Legacy Relational Documentation (PostgreSQL 61 Tables)

For historical reference and migration mapping, the legacy 61-table PostgreSQL documentation is preserved under:
👉 **[Legacy Relational Model Documentation](docs/kpi-intelligence-canonical-model/README.md)**


