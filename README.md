# KPI Intelligence Platform

Enterprise Universal Metadata Extraction, KPI Ontology Mapping, Human Governance, and Rationalisation Platform.

---

## Table of Contents

- [1. Project Overview](#1-project-overview)
  - [Business Problem & Objective](#business-problem--objective)
  - [Key Capabilities](#key-capabilities)
  - [Supported Analytical Platforms & Formats](#supported-analytical-platforms--formats)
  - [Implementation Status Summary](#implementation-status-summary)
- [2. System Architecture](#2-system-architecture)
  - [Architecture Flow Diagram](#architecture-flow-diagram)
  - [Frontend-to-Backend Request Flow](#frontend-to-backend-request-flow)
  - [Analytical Ingestion & Staging Pipeline](#analytical-ingestion--staging-pipeline)
  - [Matching Engine & Deterministic Fallback](#matching-engine--deterministic-fallback)
  - [Human Governance Invariants](#human-governance-invariants)
  - [Multi-Tenant Isolation Architecture](#multi-tenant-isolation-architecture)
- [3. Technology Stack](#3-technology-stack)
- [4. Repository Structure](#4-repository-structure)
- [5. Prerequisites](#5-prerequisites)
- [6. Local Development Setup](#6-local-development-setup)
  - [Step 1: Clone Repository](#step-1-clone-repository)
  - [Step 2: Python Backend Setup](#step-2-python-backend-setup)
  - [Step 3: Environment Configuration](#step-3-environment-configuration)
  - [Step 4: Frontend Setup](#step-4-frontend-setup)
  - [Step 5: Storage Verification](#step-5-storage-verification)
  - [Step 6: Start Services](#step-6-start-services)
  - [Step 7: Verify Running Application](#step-7-verify-running-application)
- [7. Environment Configuration Reference](#7-environment-configuration-reference)
- [8. Dependency Management](#8-dependency-management)
- [9. Database & Storage Architecture](#9-database--storage-architecture)
  - [Local Developer Experience (SQLite Two-Tier Mirror)](#local-developer-experience-sqlite-two-tier-mirror)
  - [Developer Storage CLI](#developer-storage-cli)
  - [Production Persistence (Azure Cosmos DB for NoSQL)](#production-persistence-azure-cosmos-db-for-nosql)
  - [Production Safety Guard](#production-safety-guard)
- [10. Testing & Quality Assurance](#10-testing--quality-assurance)
  - [Automated Test Execution](#automated-test-execution)
  - [Canonical Model & Cross-Representation Validation](#canonical-model--cross-representation-validation)
  - [Frontend Production Build](#frontend-production-build)
- [11. Canonical REST API Contract](#11-canonical-rest-api-contract)
- [12. Troubleshooting Guide](#12-troubleshooting-guide)
- [13. Security & Development Practices](#13-security--development-practices)
- [14. Known Limitations & Roadmap](#14-known-limitations--roadmap)
- [15. Boundary & Disclaimer](#15-boundary--disclaimer)

---

## 1. Project Overview

### Business Problem & Objective
Modern enterprise analytics environments often contain hundreds of fragmented reports, dashboards, and semantic models across tools such as Microsoft Power BI. This leads to duplicate business metrics, inconsistent calculation formulas, ambiguous definitions, and uncoordinated metric proliferation across departments.

**KPI Intelligence** provides a unified, governed metadata platform that ingests analytical assets, normalizes them into a canonical relational and document schema, maps analytical fields to an authoritative corporate KPI Bank using LLM semantic matching (with deterministic offline fallback), enforces human review and governance workflows, tracks persistent learning rules, and maintains an immutable audit trail.

### Key Capabilities
- **Analytical Metadata Ingestion**: Ingests Power BI Project (`.pbip`) directories, report definitions (`report.json`), semantic model metadata (`model.bim` / TMDL), tables, columns, calculated measures, and DAX expressions.
- **Canonical Object Registration**: Maps raw platform assets into universal analytical objects isolated by tenant.
- **Intelligent KPI Mapping**: Generates Top-3 ranked candidate recommendations with confidence scores (`HIGH`, `MEDIUM`, `LOW`) and multi-factor evidence (lexical overlap, DAX formula similarity, domain alignment).
- **Domain Segregation**: Segregates assets across 6 corporate business domains: `CLAIMS_RISK`, `UNDERWRITING`, `LEGAL`, `SALES_DISTRIBUTION`, `SERVICE_OPERATIONS`, and `ACTUARIAL`.
- **Strict Human Governance**: Enforces mandatory human approval before any KPI mapping can be promoted to production. `HIGH` confidence proposals are **never** auto-approved.
- **Manual Overrides & Persistent Learning**: Captures analyst overrides with mandatory justification ($\ge 10$ characters), computes deterministic semantic fingerprints, and suggests learned rules for future recurring fields.
- **KPI Bank Catalogue Management**: Searchable directory of corporate reference KPIs; enables governed, schema-compliant creation of new KPIs when no existing candidate matches.
- **Immutable Audit Logging**: Captures all domain corrections, mapping approvals, rejections, overrides, and invalidations in a queryable audit trail.
- **Multi-Tenant Isolation**: Enforces tenant authorization via `TenantContext.assert_authorized` at the repository and service layers.

### Supported Analytical Platforms & Formats
| Platform / Format | Support Level | Implementation Notes |
| :--- | :--- | :--- |
| **Power BI Project (`.pbip`)** | **Fully Implemented** | Full extraction of `.Report/report.json`, `.SemanticModel/model.bim`, TMDL measures, DAX expressions, and visual bindings. |
| **Power BI PBIP Archives (`.zip`)** | **Fully Implemented** | Upload PBIP zipped archives; automatically unpacks with path traversal validation. |
| **Legacy Power BI (`.pbix`)** | *Roadmap* | Detected with guidance to export as modern `.pbip` format. |
| **Excel (`.xlsx` / Power Pivot)** | *Roadmap* | Canonical relational schema supports Subsystem E; parser scheduled for subsequent phase. |
| **Tableau (`.twbx` / `.twb`)** | *Roadmap* | Architectural hooks designed; connector scheduled for subsequent phase. |

### Implementation Status Summary
- **Backend API**: Complete (FastAPI, 31 endpoints, OpenAPI/Swagger at `/docs`).
- **Frontend SPA**: Complete (React 19, Vite, responsive Apple HIG design, 8 navigation views).
- **LLM Matching**: Complete (Azure AI Foundry Llama 3.3 70B Instruct with zero-secret diagnostics, exponential backoff, and deterministic fallback).
- **Storage Subsystem**: Complete (Local SQLite 61-table relational mirror + `cosmos_documents` table; Azure Cosmos DB for NoSQL 4-container production adapter).
- **Test Suite**: 184 passing automated tests across unit, integration, security, and end-to-end suites.

---

## 2. System Architecture

### Architecture Flow Diagram

```mermaid
flowchart TD
    subgraph Client["Frontend Client (React 19 / Vite)"]
        UI["React SPA (Port 5173)"]
        Nav["Workspace Overview | Ingest | Review | KPI Bank | Domains | Overrides | Audit"]
    end

    subgraph API["FastAPI Backend (Port 8080)"]
        Router["FastAPI ASGI Router (/api/v1)"]
        Auth["Tenant Context Guard (X-Tenant-ID)"]
        IngestMgr["Ingestion Manager (PBIP Parser & Staging)"]
        GovSvc["Governance Service"]
        DomainSvc["Domain Classification Service"]
    end

    subgraph Intelligence["Matching Orchestrator"]
        Matcher["Matching Orchestrator"]
        Llama["Azure AI Foundry Client (Llama 3.3 70B)"]
        Fallback["Deterministic Matching Engine"]
    end

    subgraph Storage["Storage Layer (StorageBackendType)"]
        Repo["IRepository Abstract Contract"]
        SQLiteRepo["SQLite Two-Tier Repository"]
        CosmosRepo["Azure Cosmos DB Repository"]
    end

    subgraph Persistence["Persistence Engines"]
        SQLiteDB[("SQLite Mirror\nlocal_data/kpi_intelligence.sqlite3\n61 Canonical Tables + cosmos_documents")]
        CosmosDB[("Azure Cosmos DB for NoSQL\n4 Containers (/tenant_id & /business_domain)")]
    end

    UI -->|HTTP / JSON (Vite Proxy)| Router
    Router --> Auth
    Auth --> GovSvc
    Auth --> IngestMgr
    GovSvc --> DomainSvc
    GovSvc --> Matcher
    Matcher -->|Configured & Available| Llama
    Matcher -->|Missing Config / 429 / Timeout| Fallback
    GovSvc --> Repo
    IngestMgr --> Repo
    Repo -->|KPI_STORAGE_BACKEND=sqlite| SQLiteRepo
    Repo -->|KPI_STORAGE_BACKEND=cosmos| CosmosRepo
    SQLiteRepo --> SQLiteDB
    CosmosRepo --> CosmosDB
```

### Frontend-to-Backend Request Flow
1. During development, Vite serves the React application at `http://127.0.0.1:5173`.
2. Requests matching `/api/*` are reverse-proxied by Vite to the FastAPI backend at `http://127.0.0.1:8080`.
3. In production, FastAPI optionally mounts the built static assets from `frontend/dist` at `/`, serving the SPA and API from a unified origin.
4. All client HTTP requests pass the active tenant ID using the `X-Tenant-ID` header (defaulting to `tenant_alpha` when omitted).
5. Responses follow standard JSON envelopes (`{"success": true, "data": ...}`).

### Analytical Ingestion & Staging Pipeline
1. Users upload PBIP files or folders via `POST /api/v1/ingestion/uploads` or `POST /api/v1/ingestion/folder-uploads`.
2. The `IngestionManager` validates file signatures, enforces path-traversal defenses on zip members (`..` prevention), and stages files into `local_data/ingestion_staging/{job_id}/`.
3. The parser extracts semantic model metadata (`model.bim` / TMDL) and report visuals (`report.json`).
4. Extracted fields and measures are registered as canonical analytical objects into the active repository and assigned an initial domain classification.
5. Staged temporary files are cleaned up following parsing.

### Matching Engine & Deterministic Fallback
1. Triggering mapping (`POST /api/v1/mapping/run`) queries all unmapped analytical fields for the active tenant.
2. The `MatchingOrchestrator` checks configuration for the Azure AI Foundry Llama deployment.
3. If valid credentials and endpoints exist, the request is dispatched to Llama 3.3 70B Instruct with exponential backoff on HTTP 429 throttling.
4. If credentials are unset, the Azure service times out, throttling retries exhaust, or the model produces invalid JSON, the orchestrator triggers immediate **deterministic fallback**.
5. The deterministic engine computes token-overlap Jaccard similarity, DAX expression lexical matching, and domain affinity, ensuring mapping execution succeeds offline without billable API calls.

### Human Governance Invariants
- **Non-Negotiable Review Invariant**: A `HIGH` confidence candidate is **never** auto-approved. Every proposal requires explicit human approval via `POST /api/v1/mapping/approve`.
- **Mandatory Override Justification**: Overriding a proposal to a different KPI requires non-whitespace justification of at least 10 characters.
- **Single Active Approval**: The repository enforces that each analytical object has at most one active approved mapping at any point in time.

### Multi-Tenant Isolation Architecture
- All analytical metadata, proposals, decisions, and audit events are scoped by `tenant_id`.
- The `TenantContext.assert_authorized(document_tenant_id)` method validates every read, write, and query operation.
- In Azure Cosmos DB, containers use `/tenant_id` as the physical partition key (except `/business_domain` for the shared global ontology).

---

## 3. Technology Stack

Authoritative versions obtained from repository manifests (`requirements.txt`, `frontend/package.json`):

| Layer | Technology | Version | Purpose |
| :--- | :--- | :--- | :--- |
| **Backend Runtime** | Python | 3.10+ (3.11 verified) | Application backend runtime |
| **Backend Framework** | FastAPI | `0.162.0` (`>=0.110.0,<1.0.0`) | REST API with OpenAPI documentation |
| **ASGI Web Server** | Uvicorn | `0.54.0` (`>=0.30.0,<1.0.0`) | High-performance ASGI HTTP server |
| **Schema Validation** | Pydantic | `2.14.1` (`>=2.7.0,<3.0.0`) | Request/response data validation |
| **HTTP Client** | HTTPX | `0.28.1` (`>=0.27.0,<1.0.0`) | Client for Azure Llama & test suites |
| **Cloud Storage** | Azure Cosmos DB SDK | `4.17.1` (`>=4.7.0,<5.0.0`) | Production NoSQL document store |
| **Cloud Identity** | Azure Identity | `1.26.0` (`>=1.16.0,<2.0.0`) | Managed Identity credential provider |
| **Relational Storage** | SQLite | 3.x (bundled with Python) | Local development & offline mirror |
| **Relational Adapter** | Psycopg2-binary | `>=2.9.9,<3.0.0` (optional) | Canonical PostgreSQL live migrations |
| **Frontend Runtime** | Node.js / npm | Node 18+ (22 verified), npm 10+ | Frontend package ecosystem |
| **Frontend Framework** | React | `^19.3.1` | User interface component architecture |
| **Frontend DOM** | React DOM | `^19.3.1` | React DOM renderer |
| **Build Tooling** | Vite | `^5.4.11` | Dev server with HMR and production bundler |
| **Vite React Plugin** | `@vitejs/plugin-react` | `^4.3.4` | Fast Refresh Babel/Babel-JSX plugin |
| **LLM Deployment** | Azure AI Foundry | Llama 3.3 70B Instruct | Semantic KPI candidate matching |

---

## 4. Repository Structure

```text
kpi-intelligence/
├── README.md                           # Authoritative enterprise project documentation
├── requirements.txt                    # Core Python backend dependencies
├── requirements-dev.txt                # Development & optional database dependencies
├── .env.example                        # Template environment configuration (no real secrets)
├── .gitignore                          # Git exclusions for venv, node_modules, temp files
│
├── backend/                            # Python Backend Application
│   ├── api/                            # FastAPI REST API
│   │   └── app.py                      # FastAPI application, OpenAPI schemas, and routes
│   ├── domain/                         # Business domain classification service
│   │   └── service.py                  # Domain catalog and alias classification rules
│   ├── governance/                     # Human review, proposal, and override service
│   │   └── service.py                  # Governance state transitions & audit trail
│   ├── ingestion/                      # Analytical asset ingestion pipeline
│   │   ├── manager.py                  # Ingestion manager, file staging & zip security
│   │   └── pbip_parser.py              # Power BI PBIP / model.bim / report.json parser
│   ├── matching/                       # AI & Deterministic KPI candidate matching
│   │   ├── config.py                   # Azure AI Foundry Llama config loader
│   │   ├── azure_llama_client.py       # Azure Llama HTTP client with retry/backoff
│   │   ├── deterministic.py            # Offline deterministic matching engine
│   │   ├── llm.py                      # LLM matching service adapter
│   │   └── orchestrator.py             # Matching orchestrator with automatic fallback
│   ├── models/                         # Domain models & document contracts
│   │   └── contracts.py                # 25 Cosmos DB DocumentType contracts
│   ├── repository/                     # Repository interfaces & context
│   │   ├── context.py                  # TenantContext & TenantAccessDeniedError
│   │   └── interfaces.py               # IRepository abstract interface
│   └── storage/                        # Persistence adapters & CLI
│       ├── cli.py                      # Developer storage CLI (init, inspect, validate)
│       ├── config.py                   # StorageConfig, fail-closed safety guards
│       ├── fixtures.py                 # Deterministic synthetic test fixtures
│       ├── cosmos/                     # Azure Cosmos DB for NoSQL adapter
│       └── sqlite/                     # Local SQLite two-tier relational mirror
│
├── frontend/                           # React 19 Frontend Application
│   ├── package.json                    # Frontend dependencies & npm scripts
│   ├── package-lock.json               # Deterministic npm dependency lockfile
│   ├── vite.config.js                  # Vite configuration (port 5173, /api proxy)
│   ├── index.html                      # Single-page application HTML entrypoint
│   ├── styles.css                      # Apple HIG design system tokens & layout
│   ├── dist/                           # Production build output directory (gitignored)
│   └── src/                            # React Source Code
│       ├── main.jsx                    # React root mount entrypoint
│       ├── App.jsx                     # Core application layout, views & modals
│       └── api/                        # HTTP client modules
│           └── client.js               # API service methods & FormData handlers
│
├── local_data/                         # Local storage data directory
│   ├── kpi_intelligence.sqlite3        # Preserved SQLite database (61 tables mirror)
│   └── ingestion_staging/              # Temporary file staging directory (gitignored)
│
├── tests/                              # Automated Test Suites (184 Tests)
│   ├── test_fastapi_api.py             # FastAPI REST endpoint integration tests
│   ├── test_ingestion_api.py           # Ingestion API, staging & security tests
│   ├── test_e2e_fastapi_react.py       # End-to-end FastAPI + React mount test
│   ├── test_azure_llama_integration.py # Mocked Azure AI Foundry Llama client tests
│   ├── test_kpi_mapping_workflow.py    # Governance & proposal state transition tests
│   ├── test_sqlite_relational_mirror.py# SQLite 61-table relational schema tests
│   ├── test_sqlite_repository.py       # SQLite document repository tests
│   ├── test_cosmos_adapter.py          # Cosmos DB adapter & throttling retry tests
│   └── test_cosmos_conformance.py      # Cosmos document contract conformance tests
│
├── scripts/                            # Validation & Migration Utilities
│   ├── validate_canonical_model.py     # Canonical PostgreSQL 61-table model validator
│   ├── validate_cross_representation.py# PostgreSQL/Cosmos/SQLite cross-reconciler
│   ├── ingest_powerbi.py               # CLI runner for PBIP metadata ingestion
│   ├── provision_cosmos.py             # Azure Cosmos DB provisioning utility
│   └── migrate_postgres_to_cosmos.py   # Registry-driven relational-to-Cosmos migrator
│
├── docs/                               # Architecture Documentation
│   ├── cosmos_nosql_architecture.md    # Production Cosmos DB NoSQL blueprint
│   └── kpi-intelligence-canonical-model/# Legacy PostgreSQL 61-table specification
│       ├── canonical_schema.sql        # Authoritative 61-table PostgreSQL DDL
│       ├── data_dictionary.md          # 636-column canonical data dictionary
│       ├── er_diagram.md               # Entity-relationship diagrams
│       └── table_inventory.csv         # Complete table inventory & disposition
│
└── reference/                          # Reference analytical source projects
    └── Insurance_Claims_Report/        # Sample Power BI Project (.pbip)
```

---

## 5. Prerequisites

### Mandatory Prerequisites
- **Operating System**: macOS, Linux, or Windows (WSL2 recommended for Windows).
- **Python**: Version `3.10` or higher (`3.11` recommended).
- **Node.js**: Version `18.0.0` or higher (`22.0.0` verified).
- **npm**: Version `9.0.0` or higher (`10.5.1` verified).
- **Git**: Version `2.30+`.

### Optional Prerequisites
- **Azure AI Foundry / Azure OpenAI Service**: Required only if executing live LLM matching with Llama models. When absent, the application automatically uses offline deterministic matching.
- **Azure Cosmos DB for NoSQL**: Required only for live cloud deployment in staging or production. Local development runs on the built-in SQLite mirror without Azure accounts.
- **PostgreSQL 15+**: Required only if running live database execution of `validate_canonical_model.py` or relational data replication scripts.

---

## 6. Local Development Setup

Follow these exact sequential steps to configure the environment and run both backend and frontend locally.

### Step 1: Clone Repository
```bash
git clone <repository-url> kpi-intelligence
cd kpi-intelligence
```

### Step 2: Python Backend Setup
Create and activate an isolated Python virtual environment, then install direct dependencies:

```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
# On macOS / Linux:
source .venv/bin/activate
# On Windows (cmd):
# .venv\Scripts\activate.bat
# On Windows (PowerShell):
# .venv\Scripts\Activate.ps1

# Upgrade pip and install core backend dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3: Environment Configuration
Initialize your local `.env` configuration file from the template:

```bash
cp .env.example .env
```

The default values in `.env.example` configure the application to use the local SQLite mirror (`KPI_STORAGE_BACKEND=sqlite`) and offline deterministic fallback. If you have an Azure AI Foundry Llama deployment, edit `.env` to populate the 5 Azure variables:

```dotenv
AZURE_DEPLOYMENT=llama-3.3-70b-instruct
AZURE_ENDPOINT=https://<your-resource>.services.ai.azure.com/
AZURE_LLAMAKEY=<your-api-key>
AZURE_DEPLOYMENT_NAME=llama-33-70b-deployment
AZURE_OPENAI_API_VERSION=2024-06-01
```

### Step 4: Frontend Setup
Navigate into the `frontend` directory and install JavaScript dependencies:

```bash
cd frontend
npm install
cd ..
```

### Step 5: Storage Verification
Verify that the local SQLite database is populated and contains all 61 canonical relational tables:

```bash
python3 -m backend.storage.cli inspect --all
```

*Expected output: Reports 61 relational tables across 10 subsystems and registered Cosmos document counts.*

### Step 6: Start Services

Open two terminal sessions (with `.venv` activated in both):

#### Terminal 1 — Start FastAPI Backend Server
```bash
uvicorn backend.api.app:app --host 127.0.0.1 --port 8080 --reload
```
*The ASGI server will start on `http://127.0.0.1:8080`.*

#### Terminal 2 — Start Vite React Frontend Development Server
```bash
cd frontend
npm run dev
```
*The Vite development server will start on `http://127.0.0.1:5173`.*

### Step 7: Verify Running Application
Verify that both services are healthy:

1. **Backend Health Check**:
   ```bash
   curl http://127.0.0.1:8080/health
   # Returns: {"status":"healthy","service":"kpi-intelligence-api","version":"1.0.0",...}
   ```
2. **Interactive OpenAPI / Swagger Documentation**:
   Open [http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs) in your browser.
3. **React Frontend Application**:
   Open [http://127.0.0.1:5173](http://127.0.0.1:5173) in your browser.

---

## 7. Environment Configuration Reference

All settings can be configured via environment variables or a local `.env` file located in the repository root.

| Variable Name | Required? | Default Value | Description / Allowed Values |
| :--- | :--- | :--- | :--- |
| `KPI_ENVIRONMENT` | Optional | `development` | Environment mode: `development`, `test`, `staging`, `production`. |
| `KPI_STORAGE_BACKEND` | Optional | `sqlite` | Persistence engine: `sqlite` (dev/test only) or `cosmos` (staging/prod). |
| `KPI_SQLITE_PATH` | Optional | `local_data/kpi_intelligence.sqlite3` | Relative or absolute path to local SQLite database. |
| `KPI_TEMP_DIR` | Optional | `C:\kpi_tmp` (Win) / `local_data/temp_ingestion` (Unix) | Temporary workspace for PBIP uploads. Prevents Windows WinError 206. |
| `COSMOS_ENDPOINT` | Prod Only | *None* | Cosmos DB account URI (`https://<account>.documents.azure.com:443/`). |
| `COSMOS_DATABASE` | Prod Only | `kpi_intelligence` | Target database name in Cosmos DB. |
| `COSMOS_USE_MANAGED_IDENTITY` | Optional | `true` | Use Azure Managed Identity (`true` / `false`). |
| `COSMOS_KEY` | Optional | *None* | Master secret key (used only when Managed Identity is disabled). |
| `COSMOS_MAX_RETRIES` | Optional | `5` | Maximum retry attempts upon encountering HTTP 429 throttling. |
| `COSMOS_RETRY_DELAY_SECONDS`| Optional | `0.5` | Initial backoff delay for Cosmos throttling retries. |
| `COSMOS_CONNECTION_TIMEOUT` | Optional | `10` | HTTP connection timeout in seconds for Cosmos requests. |
| `AZURE_DEPLOYMENT` | Optional | *None* | Model identifier passed in JSON body (e.g. `llama-3.3-70b-instruct`). |
| `AZURE_ENDPOINT` | Optional | *None* | Azure AI Foundry / Azure OpenAI endpoint URI. |
| `AZURE_LLAMAKEY` | Optional | *None* | Secret API key for Azure AI Foundry. Never exposed in responses or logs. |
| `AZURE_DEPLOYMENT_NAME` | Optional | *None* | Azure deployment resource name for URL routing paths. |
| `AZURE_OPENAI_API_VERSION` | Optional | `2024-06-01` | Azure API version query parameter. |
| `KPI_LLM_TIMEOUT_SECONDS` | Optional | `30.0` | Client timeout in seconds for LLM inference calls. |
| `KPI_LLM_MAX_RETRIES` | Optional | `2` | Retry attempts for LLM inference on rate-limiting or network errors. |
| `KPI_CORS_ORIGINS` | Optional | `http://localhost:3000,http://localhost:5173,...` | Comma-separated allowed CORS origins. |

> [!WARNING]
> Never commit real secrets to source control. The `.gitignore` configuration explicitly excludes all `.env` files while preserving the template `.env.example`.

---

## 8. Dependency Management

### Python Backend (`requirements.txt`)
The backend uses standard `pip` dependency resolution with pinned minimum and bounded maximum versions to prevent breaking upstream upgrades.

- **`requirements.txt`**: Direct runtime dependencies required for the FastAPI server, SQLite mirror, Cosmos DB SDK, Azure Identity, and test suites.
- **`requirements-dev.txt`**: Development dependencies, including optional database adapters like `psycopg2-binary`.

To verify dependency resolution without modifying the environment:
```bash
pip check
```

### React Frontend (`frontend/package.json`)
The frontend uses `npm` with a locked dependency tree in `frontend/package-lock.json`.
- Install dependencies: `npm install` (or `npm ci` for deterministic clean installs).
- Run dev server: `npm run dev`
- Production build: `npm run build`

---

## 9. Database & Storage Architecture

### Local Developer Experience (SQLite Two-Tier Mirror)
The local SQLite database at `local_data/kpi_intelligence.sqlite3` implements two coordinated storage layers:

1. **Full Relational Mirror (61 Tables)**:
   Contains all 61 canonical tables across 10 subsystems (Asset Registry, Analytical Objects, Calculations, Filters & Lineage, Excel Metadata, KPI Ontology, Candidates, Governance, Rationalisation, and Operations). Foreign key constraints are enforced (`PRAGMA foreign_keys = ON;`).
2. **Cosmos Document Store Mirror (`cosmos_documents` Table)**:
   Emulates Cosmos DB partition queries (`SELECT * FROM c WHERE c.tenant_id = @tenant_id`), point-reads by ID, continuation tokens, and ETags for offline development.

### Developer Storage CLI
Manage the local SQLite database using `backend.storage.cli`:

```bash
# Inspect relational subsystems and Cosmos document counts
python3 -m backend.storage.cli inspect --all

# Validate relational schema completeness (61 tables, 636 columns) and foreign key integrity
python3 -m backend.storage.cli validate --relational

# Export relational tables to JSON bundle
python3 -m backend.storage.cli export --relational --output local_data/relational_export.json

# (Safe Development Only) Re-initialize both stores with synthetic test fixtures
python3 -m backend.storage.cli init --all --seed
```

> [!IMPORTANT]
> The database file at `local_data/kpi_intelligence.sqlite3` is a pre-populated baseline. Avoid resetting it unless intentionally regenerating synthetic test records.

### Production Persistence (Azure Cosmos DB for NoSQL)
In production, data is stored across 4 Cosmos DB for NoSQL containers:

| Container Name | Partition Key | Purpose | TTL Policy |
| :--- | :--- | :--- | :--- |
| **`metadata_catalog`** | `/tenant_id` | Logical assets, reports (with embedded pages/visuals), semantic models (tables/measures), and lineage edges. | Permanent (`-1`) |
| **`kpi_governance`** | `/tenant_id` | Discovered KPI candidates, mappings, approvals, manual overrides, and rationalisations. | Permanent (`-1`) |
| **`kpi_ontology`** | `/business_domain` | Authoritative corporate KPI definitions, formulas, aliases, and versions. | Permanent (`-1`) |
| **`operational_audit`** | `/tenant_id` | Ingestion telemetry, parser logs, and immutable governance audit events. | 90 Days (`7776000s`) |

### Production Safety Guard
To prevent accidental connection to local SQLite in enterprise environments, `StorageConfig.from_env()` enforces a strict runtime guard:
Setting `KPI_ENVIRONMENT=production` or `KPI_ENVIRONMENT=staging` while `KPI_STORAGE_BACKEND=sqlite` throws a fatal `RuntimeError` on startup.

---

## 10. Testing & Quality Assurance

### Automated Test Execution
Run the complete automated test suite using Python's standard `unittest` framework:

```bash
# Execute all 184 test cases
python3 -m unittest discover -s tests -p "test_*.py" -v
```

*Current Suite Status: 184 tests ran in ~2.7s; 183 passed, 1 skipped (live Cosmos DB cloud test safely skipped by default).*

#### Targeted Test Suites
```bash
# 1. FastAPI REST endpoints & HTTP responses (13 tests)
python3 -m unittest tests/test_fastapi_api.py

# 2. Ingestion API, PBIP staging, path traversal defenses (7 tests)
python3 -m unittest tests/test_ingestion_api.py

# 3. End-to-end FastAPI + React mount smoke test (1 test)
python3 -m unittest tests/test_e2e_fastapi_react.py

# 4. Azure AI Foundry Llama integration & deterministic fallback (11 tests)
python3 -m unittest tests/test_azure_llama_integration.py

# 5. KPI mapping, domain segregation, and human governance (25 tests)
python3 -m unittest tests/test_kpi_mapping_workflow.py

# 6. SQLite relational mirror & foreign key integrity (27 tests)
python3 -m unittest tests/test_sqlite_relational_mirror.py

# 7. SQLite document repository integration (30 tests)
python3 -m unittest tests/test_sqlite_repository.py

# 8. Cosmos DB adapter & throttling retry logic (46 tests)
python3 -m unittest tests/test_cosmos_adapter.py

# 9. Cosmos DB document contract conformance (24 tests)
python3 -m unittest tests/test_cosmos_conformance.py
```

### Canonical Model & Cross-Representation Validation
Two specialized verification scripts ensure 100% schema alignment across relational, document, and SQLite representations:

```bash
# 1. Verify PostgreSQL 61-table canonical schema, foreign keys, and inventory
python3 scripts/validate_canonical_model.py
# Result: 36 / 36 checks passed.

# 2. Verify cross-representation reconciliation (636 columns, contracts, handlers)
python3 scripts/validate_cross_representation.py
# Result: 636 / 636 columns resolved, 25/25 contracts verified, 61/61 handlers valid.
```

### Frontend Production Build
Validate that the React frontend compiles into optimized production assets without syntax or bundle errors:

```bash
cd frontend
npm run build
cd ..
```
*Output: Production bundle generated in `frontend/dist` (~32 kB CSS, ~275 kB JS gzip-optimized).*

---

## 11. Canonical REST API Contract

The FastAPI backend provides 31 documented endpoints organized by operational domain:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Service health status check. |
| `GET` | `/ready` | Service readiness probe. |
| `GET` | `/api/v1/workspace/summary` | Aggregated metrics, unreviewed proposal counts, and domain distributions. |
| `GET` | `/api/v1/llm/status` | Non-sensitive operational status of Azure AI Foundry Llama integration. |
| `GET` | `/api/v1/domains` | List canonical business domains with definitions and counts. |
| `GET` | `/api/v1/domains/{domain}/metrics` | Domain-specific proposal and approval metrics. |
| `GET` | `/api/v1/metadata/fields` | Query extracted analytical fields for the active tenant. |
| `GET` | `/api/v1/metadata/fields/{field_id}` | Detailed field metadata (table, source expression, current domain). |
| `POST` | `/api/v1/metadata/fields/{field_id}/domain` | Reclassify field domain with justification and audit trail. |
| `POST` | `/api/v1/domain/classify` | Test domain classification for arbitrary text aliases. |
| `POST` | `/api/v1/mapping/run` | Execute mapping pipeline (Azure Llama with deterministic fallback). |
| `GET` | `/api/v1/mapping/fields/{field_id}/candidates` | Retrieve Top-3 ranked KPI candidates with multi-factor evidence. |
| `GET` | `/api/v1/mapping/proposals` | List proposals awaiting human review. |
| `GET` | `/api/v1/mappings/proposals/{proposal_id}` | Detailed proposal inspection with evidence breakdown. |
| `POST` | `/api/v1/mapping/approve` | Approve a candidate proposal (enforces single active approval). |
| `POST` | `/api/v1/mapping/reject` | Reject proposal with reason tracking. |
| `POST` | `/api/v1/mapping/override` | Override mapping (requires $\ge 10$ characters justification). |
| `GET` | `/api/v1/kpi-bank/search` | Search authoritative reference KPI Bank entries. |
| `POST` | `/api/v1/kpi-bank/create` | Create a new schema-compliant governed KPI in the KPI Bank. |
| `GET` | `/api/v1/overrides` | List persistent learned override rules and reuse statistics. |
| `POST` | `/api/v1/overrides/invalidate` | Invalidate a previously learned override rule. |
| `GET` | `/api/v1/audit/history` | Chronological immutable audit history log. |
| `GET` | `/api/v1/ingestion/supported-formats`| Query supported analytical file extensions and documentation. |
| `GET` | `/api/v1/ingestion/sources` | List previously ingested analytical assets. |
| `POST` | `/api/v1/ingestion/uploads` | Multipart file upload for analytical assets (PBIP, JSON, BIM, ZIP). |
| `POST` | `/api/v1/ingestion/folder-uploads` | Multipart folder upload preserving nested relative paths. |
| `GET` | `/api/v1/ingestion/jobs/{job_id}` | Poll asynchronous ingestion job status and error reporting. |

---

## 12. Troubleshooting Guide

### 1. Port Conflict (`Address already in use`)
- **Symptom**: `ERROR: [Errno 48] error while attempting to bind on address ('127.0.0.1', 8080): address already in use`
- **Diagnostic**: Identify the process occupying port 8080 or 5173:
  ```bash
  lsof -i :8080
  lsof -i :5173
  ```
- **Resolution**: Terminate the lingering process or specify an alternative port:
  ```bash
  kill -9 <PID>
  # Or start backend on a different port:
  uvicorn backend.api.app:app --port 8081
  ```

### 2. Frontend Proxy Connection Failure (`ECONNREFUSED`)
- **Symptom**: Frontend shows `NetworkError when attempting to fetch resource` or browser console logs `POST http://localhost:5173/api/v1/... 502 (Bad Gateway)`.
- **Diagnostic**: Verify whether the FastAPI backend is running:
  ```bash
  curl -I http://127.0.0.1:8080/health
  ```
- **Resolution**: Start the FastAPI backend first using `uvicorn backend.api.app:app --port 8080`.

### 3. Production Safety Guard Triggered on Startup
- **Symptom**: Backend startup crashes with: `RuntimeError: FATAL CONFIGURATION ERROR: KPI_STORAGE_BACKEND is set to 'sqlite' in production environment.`
- **Diagnostic**: Inspect `.env` or process environment for `KPI_ENVIRONMENT` and `KPI_STORAGE_BACKEND`.
- **Resolution**: For local development, set `KPI_ENVIRONMENT=development` and `KPI_STORAGE_BACKEND=sqlite`. For production, configure `KPI_STORAGE_BACKEND=cosmos` with valid `COSMOS_ENDPOINT` credentials.

### 4. Tenant Access Forbidden (`403 Forbidden`)
- **Symptom**: API returns `{"success": false, "error": "Access denied for tenant 'tenant_beta'. Current context: 'tenant_alpha'"}`.
- **Diagnostic**: The requested document or operation belongs to a different tenant than the authenticated request header.
- **Resolution**: Ensure requests provide a matching `X-Tenant-ID` header corresponding to the target resource.

### 5. Azure Llama Rate Limiting / Offline Fallback
- **Symptom**: Backend logs display `Azure Llama client failed [THROTTLED]: Rate limit. Falling back to deterministic matching.`
- **Diagnostic**: Check `GET /api/v1/llm/status` to inspect configuration status.
- **Resolution**: This is normal resilience behavior. The application automatically falls back to deterministic matching to prevent pipeline failures. If unexpected, check your Azure AI Foundry quota or adjust `KPI_LLM_TIMEOUT_SECONDS` and `KPI_LLM_MAX_RETRIES` in `.env`.

### 6. Windows Path Limit (`[WinError 206] The filename or extension is too long`)
- **Symptom**: Ingestion of deeply nested Power BI PBIP/PBIR folders fails on Windows with `[WinError 206] The filename or extension is too long`.
- **Diagnostic**: Occurs when staging deep report structures (e.g. `definition\pages\...\visuals\...\visual.json`) within deeply nested workspace directories (e.g. `C:\Users\...\OneDrive - ...\Documents\...`), exceeding the 260-character Win32 MAX_PATH limit.
- **Resolution**:
  1. The application automatically defaults to `C:\kpi_tmp` on Windows and prefixes file paths with Windows extended syntax (`\\?\`).
  2. To customize the temporary workspace, set `KPI_TEMP_DIR` in `.env` to a short local directory, e.g. `KPI_TEMP_DIR=C:\kpi_tmp`.
  3. Ensure the current user has write permissions to create `C:\kpi_tmp` or specify an accessible short path.

---

## 13. Security & Development Practices

1. **Zero Secret Exposure**:
   - The API status endpoint (`GET /api/v1/llm/status`) and `__repr__` methods redact `AZURE_LLAMAKEY` and hostnames.
   - Logs never print raw authorization keys, bearer tokens, or connection strings.
2. **Multi-Tenant Boundaries**:
   - Every database query and point-read is partitioned and authorized using `TenantContext.assert_authorized`.
   - Never remove or bypass tenant checks when implementing new endpoints.
3. **Zip Slip / Path Traversal Defenses**:
   - The file staging manager (`IngestionManager`) inspects all zip entries before extraction to block malicious archive members containing `..` or leading slashes.
4. **Git Hygiene**:
   - Keep `.env` outside source control.
   - Do not commit temporary test databases or staged files in `local_data/ingestion_staging/`.
5. **CORS Restrictions**:
   - Wildcards (`*`) are disallowed when credentials or headers are exchanged. Allowed origins must be explicitly listed in `KPI_CORS_ORIGINS`.

---

## 14. Known Limitations & Roadmap

### Implemented & Verified Capabilities
- Power BI Project (`.pbip`) semantic model extraction (tables, columns, measures, DAX).
- Automated KPI candidate discovery and ranking with multi-factor evidence.
- Human review and approval workflow with persistent audit history.
- Manual overrides with mandatory rationale ($\ge 10$ characters) and learned rule reuse.
- Azure AI Foundry Llama integration with exponential backoff and deterministic offline fallback.
- Dual-tier SQLite local relational mirror matching the canonical 61-table PostgreSQL schema.
- Responsive React 19 frontend adhering to Apple HIG across 1440px, 1280px, 1024px, 768px, and 390px viewports.

### Current Limitations
- **Background Tasks**: Long-running ingestion jobs execute in-process rather than via a distributed task broker (e.g. Celery or Azure Service Bus).
- **Authentication**: Tenant identification is currently passed via `X-Tenant-ID` request headers. Integration with Azure Active Directory (MSAL / JWT verification) is designed into the architecture but not yet wired to an external identity provider.

### Development Roadmap
- **Phase 2**: Native Excel workbook (`.xlsx`) and Power Pivot Data Model extraction.
- **Phase 3**: Tableau Workbook (`.twb` / `.twbx`) XML and hyper metadata extraction.
- **Phase 4**: Automated semantic reconciliation with Microsoft Purview and enterprise data catalogues.

---

## 15. Boundary & Disclaimer

> [!NOTE]
> **Live Azure Cosmos DB Verification Boundary**:
> Live Azure Cosmos DB verification remains out of scope. No live Cosmos DB cloud connectivity, live cloud read/write, cloud migration execution, or cloud roundtrip claims are made by this repository. All verification is performed against the authoritative 61-table PostgreSQL canonical schema, the local SQLite two-tier relational mirror, registered Cosmos DB document contracts, and synthetic serialization reconciliation suites.
