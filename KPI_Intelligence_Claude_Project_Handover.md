# KPI Intelligence — Project Handover for Claude and Claude Code

**Purpose:** This is the project-context baseline for Claude. Use it to understand the business goal, architecture, algorithms, governance, current known defects, and implementation constraints. Claude should inspect the current repository before treating any historical implementation claim as verified.

**Evidence convention:** Some items below are architectural requirements; some are implementation details reported by Antigravity; some are defects observed in screenshots. A historical report saying a test passed is not proof that the current branch still passes it. Do not invent missing facts. Inspect code, tests, configuration, and runtime behavior.

---

## 1. Executive Summary

KPI Intelligence is an enterprise, multi-tenant platform for extracting analytical metadata from BI/reporting assets, normalizing it into a canonical model, classifying it into business domains, mapping it to a reference KPI Bank, and governing those mappings through mandatory human review.

The intended outcome is a production-grade, explainable and auditable KPI metadata governance platform—not a static dashboard or demo. Users should be able to ingest supported sources, inspect extracted metadata, see business-domain classifications, run semantic KPI matching, compare ranked candidates and evidence, approve/reject/override proposals, create governed KPI definitions, and review audit/override history. Approved human overrides should be reused when equivalent metadata is re-ingested.

**Required stack and boundaries**
- Backend: **FastAPI (Python)**.
- Frontend: **React**.
- LLM: **Llama hosted in Azure AI Foundry**, configured through server-side environment variables.
- Canonical data: an existing 61-table PostgreSQL relational schema with 636 columns; Cosmos DB NoSQL document contracts/repository abstractions; SQLite local development/validation mirror.
- Governance: tenant isolation, explicit human approval, immutable audit history, justification-enforced overrides, and persistent override learning.
- Matching: LLM-first semantic ranking plus deterministic fallback.
- UI: Apple-inspired enterprise styling, persistent left navigation, eight views, clear hierarchy and spacing. Usability and accessibility matter more than decorative styling.

Do not rewrite the application from scratch. Inspect the actual repository and extend existing components, services, contracts, and tests. Preserve invariants unless a change is explicitly justified and tested.

---

## 2. Business Problem and Desired Outcome

Organizations have many dashboards, reports, semantic models, measures, columns, formulas, calculated fields, filters, and analytical objects. Different assets may describe the same KPI with different names, aliases, formulas, definitions, aggregation rules, or domain context. This creates duplicate measures, inconsistent business definitions, weak lineage, and difficult governance.

KPI Intelligence aims to:
1. Inventory analytical metadata from supported platforms.
2. Persist extracted metadata in a canonical platform-independent representation.
3. Classify relevant entities/fields into business domains.
4. Retrieve and rank candidate enterprise KPIs from a reference KPI Bank.
5. Explain each candidate with structured, inspectable evidence.
6. Require an authorized human to approve, reject, or override each proposal.
7. Persist decisions, justifications, provenance, and audit events.
8. Reuse valid prior human overrides on re-ingestion.
9. Enable future KPI rationalization and discovery of redundant/inconsistent definitions.
10. Maintain tenant isolation and useful behavior when the LLM is unavailable.

Success means an analyst can select supported source files, ingest them, inspect canonical metadata, see domain classification, run KPI mapping, compare up to three candidates with evidence, make a governance decision, and later retrieve that decision and its audit trail. On re-ingestion, valid human overrides should be reused rather than asking the LLM to rediscover the same decision.

The UI must distinguish “not processed,” `UNCLASSIFIED`, “no candidates found,” “LLM unavailable,” “fallback used,” “awaiting review,” approved/rejected/overridden, ingestion failure, API failure, and authorization failure. Never collapse these into one generic empty state.

---

## 3. Project Background and Existing Architecture

### 3.1 Canonical data model and repository abstraction

The canonical model was designed as a PostgreSQL schema with **61 tables and 636 columns**. It was also represented through Cosmos DB NoSQL document contracts, grouped into four containers, with a SQLite adapter/database for local development and validation.

Known container design:
1. `metadata_catalog` — partition key `/tenant_id`; assets, asset versions, reports, semantic models, lineage edges, and catalog metadata.
2. `kpi_governance` — `/tenant_id`; KPI candidates, mappings, approvals, overrides, and governance/rationalization records.
3. `kpi_ontology` — `/business_domain`; global reference KPI ontology.
4. `operational_audit` — `/tenant_id`; parser runs, extraction errors, audit events, and ingestion events. The plan mentions a 90-day TTL for applicable operational records.

Repository abstraction:
- `IRepository`
- `CosmosRepository`
- `SQLiteRepository`
- `CatalogServiceRepository`
- `GovernanceServiceRepository`
- `OntologyServiceRepository`
- `AuditServiceRepository`

`TenantContext` is intended to enforce tenant authorization on every tenant-scoped read/write. `TenantContext.system_context()` is intended for authorized global ontology queries. `TenantContext.assert_authorized` and all related isolation invariants are non-negotiable.

**Cloud validation caveat:** A previous implementation report explicitly stated that live Azure Cosmos DB connectivity, reads/writes, migrations, and round-trip verification were out of scope. Do not claim Cosmos DB was live-tested unless an authorized test is actually performed.

### 3.2 Existing contracts and governance models

The implementation plan identifies:
- `OntologyEntryDocument` in `backend/contracts/ontology.py`: canonical KPI Bank entry.
- `KpiCandidateDocument`: candidate discovered from measures, calculations, or visual summaries.
- `KpiMappingDocument`: mapping aggregate, selected ontology entry, status, decision source, confidence band, and candidate list.
- `MappingApprovalDocument`: immutable sign-off with approved ontology entry, actor, timestamp, and approval version.
- `MappingOverrideDocument`: human override, replacement KPI, required justification, and learning metadata.
- `MappingAuditEventDocument`: permanent audit/compliance event.

Reported mapping statuses: `PROPOSED`, `APPROVED`, `REJECTED`, `OVERRIDDEN`.
Reported decision sources: `LLM_INFERENCE`, `DETERMINISTIC_FALLBACK`, `HUMAN_OVERRIDE`.
Confidence bands: `HIGH`, `MEDIUM`, `LOW`, `UNCLASSIFIED`.

The authoritative KPI entry schema includes:
- `kpi_id`, `kpi_code`, `name`, `definition`
- `domain`, `business_domain`, `sector`, `subdomain`, `line_of_business`
- `aliases`, `aggregation_type`, `valid_dimensions`
- `status`, `is_active_sector`, `kpi_type`
- `enrichments`: `calculation`, `fields_required`, `applicability`, `business_meaning`, `metric_description`, `category`, `lob`, `team`, `source`
- `ontology_payload` for complete lossless JSON representation.

The actual contract files in the repository are authoritative. Do not simplify or replace the existing schema with a competing one.

### 3.3 KPI Bank

The KPI Bank is the reference ontology/catalogue. The plan references:
- `scripts/kpi_bank_parser.py`
- `fixtures/kpi_bank_representative_fixture.json`
- `OntologyEntryDocument`

The reported service searches normalized names, aliases, definitions, formulas/calculations, required fields, enrichments, and domain; it should support lifecycle status (active/draft/deprecated), duplicate/equivalence detection, and governed creation.

A representative fixture is a test/development fixture, not proof that the full enterprise KPI catalogue is loaded. Never present fixture data as the complete production KPI Bank unless the configured source confirms that.

New KPI creation must use the complete authoritative schema. Creating a KPI and approving a mapping are separate actions. A new KPI may need to remain draft depending on existing lifecycle rules.

---

## 4. Mandatory Application Architecture

### 4.1 FastAPI backend

FastAPI is mandatory. A prior Antigravity report described `backend/api/app.py` as implemented with Python's standard-library `http.server`, which does not satisfy the requirement. A corrective prompt was created to migrate it.

Claude must inspect current code to verify whether the migration has actually happened. A UI label saying “FastAPI + React” is not proof.

Expected:
- Real FastAPI app and routers.
- Pydantic request/response schemas.
- Dependency injection for services, repositories, tenant context, and actor identity.
- Centralized safe error handling and appropriate HTTP status codes.
- OpenAPI schema.
- CORS limited to configured frontend origins.
- Thin route handlers delegating to services.
- Bounded LLM timeouts/retries and appropriate handling of long-running work.

### 4.2 React frontend

React is mandatory. Verify that `frontend/` is a real React app with `package.json`, React entry point/components, and a successful production build. A directory named `frontend` is not proof.

React communicates with FastAPI through a single documented API client. It must not connect directly to PostgreSQL, Cosmos DB, or SQLite and must never receive Azure API keys.

### 4.3 Azure AI Foundry Llama

The required backend environment variable names are exactly:

```dotenv
AZURE_DEPLOYMENT=
AZURE_ENDPOINT=
AZURE_LLAMAKEY=
AZURE_DEPLOYMENT_NAME=
AZURE_OPENAI_API_VERSION=
```

Use local `.env` or an approved deployment secret store. `.env` must be ignored by Git; `.env.example` should contain placeholders only. Never commit, log, prompt, or return actual keys/endpoints containing secrets. Never expose secrets through React or frontend build variables.

A prompt was created to integrate Llama into the existing mapping pipeline. Important requirements:
- Inspect the actual endpoint and API contract before selecting an SDK or constructing endpoint paths.
- The variable names alone do not prove which Azure inference protocol the deployment supports.
- Do not assume `AZURE_DEPLOYMENT` and `AZURE_DEPLOYMENT_NAME` are interchangeable. Establish their meaning from current configuration and the endpoint contract; ask the user if repository evidence cannot resolve the ambiguity.
- Call the configured Azure endpoint, not the public OpenAI API.
- Hide SDK-specific request/response formats behind an adapter.
- Mock Azure calls in automated tests; do not make billable inference calls in normal tests.
- Distinguish “configured” from “reachable”; settings being present does not prove the endpoint is available.
- Deterministic fallback must work when LLM configuration or connectivity is unavailable.

---

## 5. Source Ingestion and Metadata Extraction

### 5.1 Intended workflow

Screenshots revealed no obvious file upload or folder selection path. The required ingestion experience is:

1. **Upload Files:** drag/drop and browse; multiple files if supported.
2. **Select Folder:** browser-supported directory selection, preview selected files, preserve relative path metadata when available.
3. Optional **server-side folder/cloud location** only if a genuinely supported and authorized backend connector or mounted location exists.
4. Validate supported formats, size/count limits, duplicates, and invalid files before ingestion.
5. Require an explicit **Start Ingestion** action.
6. Show per-file/job progress and validation/processing errors.
7. Provide an ingested-source inventory: name, type, timestamp, status, metadata count, and errors.
8. Run mapping only after ingestion has produced canonical metadata and the user explicitly triggers the pipeline, unless existing product behavior explicitly requires a different sequence.

Browser folder selection provides access only to the files selected by the user; it does not provide arbitrary local filesystem access. A server-side folder path is a different capability and must be constrained to configured allowed roots with authorization.

### 5.2 Existing ingestion components

The implementation plan identifies:
- `PowerBIConnector`
- `PbipDiscovery`
- `BundleToDocumentsConverter`
- Canonical ingestion services
- `ReportDocument`
- `SemanticModelDocument`
- `AnalyticalObjectDocument`

Mapping must read persisted canonical metadata from the repository. It must not reopen raw PBIP/TMDL/PBIX/Excel files during LLM ranking.

The project aims to support Power BI, Excel, Tableau, ThoughtSpot, MicroStrategy, and other sources through connectors, but this does not prove every connector has been implemented. Inspect actual code and tests before advertising support.

Possible ingestion routes from a previous corrective plan (reuse equivalent existing endpoints rather than creating duplicates):
- `POST /api/v1/ingestion/uploads`
- `POST /api/v1/ingestion/folder-uploads`
- `GET /api/v1/ingestion/jobs/{job_id}`
- `GET /api/v1/ingestion/supported-formats`
- `GET /api/v1/ingestion/sources`
- `POST /api/v1/ingestion/jobs/{job_id}/retry`

Security/engineering requirements:
- Validate extension, content type where reliable, signatures where appropriate, size and count.
- Stream/spool safely; avoid unbounded in-memory uploads.
- Sanitize display names; never use user filenames as paths.
- Prevent path traversal and unsafe archive extraction.
- Apply tenant authorization to uploads, jobs, and source inventory.
- Persist job state through existing services/repositories where supported.
- Do not report success until backend processing confirms it.
- Do not silently treat unsupported files as ingested.
- Do not write arbitrary source blobs into canonical metadata documents.
- Do not create cloud resources or perform cloud writes without explicit authorization.

---

## 6. Business Domains

Primary domains:
1. `CLAIMS_RISK` — Claims & Risk
2. `LEGAL` — Legal
3. `UNDERWRITING` — Underwriting
4. `SALES_DISTRIBUTION` — Sales & Distribution
5. `ACTUARIAL` — Actuarial

Legacy `SERVICE_OPERATIONS` — Service & Operations — must remain supported where existing contracts/data require it. The original plan calls these five primary domains plus legacy Service & Operations.

**Legal and Underwriting must remain strictly separate. Never merge them.**

Reported classification signals:
- **Claims & Risk:** claims processing, indemnity loss, reserves, recovery, subrogation, litigation reserves, claim frequency/severity, fraud mitigation.
- **Legal:** compliance, regulatory fines, litigation defense spend, disputes, policyholder suits, legal counsel billing, statutory filings.
- **Underwriting:** policy issuance, risk selection, capacity allocation, rating guidelines, written premium, rate adequacy, exposure; ratios should be classified based on actual KPI meaning/ontology, not string alone.
- **Sales & Distribution:** broker commissions/production, agency management, conversion rates, submissions, written premium, renewals, new-business pipeline.
- **Actuarial:** IBNR, loss development, reserving triangles, statistical modeling, pricing adequacy, capital reserving, solvency, rate making.
- **Service & Operations:** policyholder servicing, call center operations, SLA compliance, document processing, customer service call times.

Classification must provide confidence/result state, supporting evidence, and `UNCLASSIFIED` when evidence is insufficient. Human domain corrections must persist and be audited. Display human-readable names; internal codes may appear as secondary labels.

---

## 7. KPI Mapping Algorithm and Workflow

### 7.1 End-to-end algorithm

For each relevant canonical metadata field/entity:
1. Read persisted canonical metadata through the repository.
2. Retrieve or classify its business domain.
3. Look for a valid reusable approved override/prior human decision.
4. Retrieve plausible candidates from the authoritative KPI Bank.
5. Rank candidates using Azure Llama as the primary semantic engine.
6. Validate structured output and every KPI ID.
7. If the LLM is unavailable or output invalid, run deterministic ranking.
8. Persist candidate rankings, evidence, provenance, and mapping state.
9. Display up to three candidates for human review.
10. Human approves, rejects, chooses an alternative with justification, or creates a new KPI.
11. Persist the governance decision and audit event.
12. Reuse valid approved overrides during future re-ingestion.

The LLM's top-ranked candidate is a proposal, never an approval.

### 7.2 Stage A — Candidate retrieval

Retrieve a plausible set using the existing services and fields:
- Normalized KPI/field names.
- Alias match.
- Definition/description overlap.
- Formula/calculation overlap.
- Required-field overlap.
- Domain compatibility.
- Aggregation type, data type, units, and valid dimensions where available.
- Approved mapping/override history.
- Semantic retrieval only if a real mechanism is implemented and configured.

Search KPI name, aliases, definition, formula/calculation, required fields, enrichments, and domain. Retrieval should avoid missing good candidates without blindly sending the entire ontology to the LLM. Never invent candidate IDs.

### 7.3 Stage B — LLM ranking

Llama evaluates only retrieved candidates against relevant canonical metadata. Consider business meaning, formula semantics and numerator/denominator, aggregation compatibility, required fields/dimensions, data type/units, domain, missing evidence, contradictions, and KPI lifecycle status.

Send bounded, purpose-specific metadata only. Never send full source files, secrets, unrelated tenant data, or unnecessary personal/customer data. Treat source metadata as untrusted data, not instructions. Require the model to rank only supplied KPI IDs.

Validate output against a strict schema; reject malformed JSON, unknown IDs, duplicate IDs, unsupported fields, invalid confidence values, or invented KPIs. Return up to three candidates, fewer if fewer credible candidates exist.

### 7.4 Explainability

Candidate evidence fields should include:
- `observed_evidence`
- `inferences_made`
- `missing_information`
- `contradictory_evidence`
- `ranking_rationale`

Evidence should explain relevant name/alias matches, formula compatibility, required fields, aggregation, dimensions, domain and ranking. Never expose raw hidden chain-of-thought or internal prompts.

Confidence bands: `HIGH`, `MEDIUM`, `LOW`, `UNCLASSIFIED`. Neither LLM nor deterministic scores should be presented as calibrated probabilities unless a real calibration method exists. Keep source/provenance explicit.

### 7.5 Deterministic fallback

A prior report states that the deterministic engine uses:
- Name match: 0.30
- Alias match: 0.20
- Formula match: 0.25
- Definition Jaccard similarity: 0.15
- Domain compatibility: 0.10

Reported contradiction penalties:
- `-0.25` for formula-semantic mismatch (e.g. count vs average).
- `-0.15` for cross-domain mismatch.

The current code is authoritative; verify actual weights before changing them. These are ranking heuristics, not calibrated probabilities. Structured evidence should explain the result.

Fallback triggers include missing config, client initialization failure, timeout, HTTP error/throttling, malformed JSON, schema validation failure, or unknown KPI ID. Record `fallback_used` and a safe `fallback_reason`. If both LLM and deterministic processing fail, show an explicit error; do not fabricate results.

### 7.6 Mandatory human governance

- HIGH confidence never auto-approves.
- Approve a selected candidate explicitly.
- Reject with reason where required.
- Choose an alternative from the full searchable KPI Bank.
- Manual override justification must contain at least **10 non-whitespace characters** (reported current rule); validate on the server as well as the frontend.
- Validate chosen KPI against the authoritative KPI Bank.
- Record actor, tenant, timestamp, prior proposal, chosen KPI, justification, provenance, and source/fingerprint details supported by the model.
- KPI creation and mapping approval are separate actions.
- The LLM must never silently overwrite an approved human decision.

---

## 8. Override Learning and Re-ingestion

Overrides are durable business decisions, not merely prompt feedback.

Reported layered fingerprint strategy:
1. **Level 1 — Exact identity:** stable canonical entity/target ID.
2. **Level 2 — Stable source fingerprint:** platform, asset identity, entity type/name or equivalent source identity.
3. **Level 3 — Semantic field fingerprint:** normalized domain, entity type, tokens/name, formula signature/hash and stable semantic context.
4. **Level 4 — Similarity fallback:** token/similarity matching only with explicit thresholds and conflict checks.

The reported `MappingOverrideDocument` learning fields are:
- `source_platform`
- `source_asset_id`
- `canonical_entity_type`
- `canonical_entity_id`
- `canonical_source_fingerprint`
- `semantic_field_fingerprint`
- `domain_context`
- `original_candidates`
- `reuse_count`
- `last_reused_at`
- `match_method`

Verify actual contract definitions. Prior reports described these as additive/backward-compatible fields; do not assume no migration is needed without inspecting current code.

Rules:
- Reuse a valid approved override before rerunning the LLM when identity confidence is sufficient.
- Skip reuse if the replacement KPI is deleted/deprecated or otherwise invalid.
- Detect conflicting overrides and route them to human review; never pick arbitrarily.
- Update reuse count, time, and match method.
- Similarity reuse needs explicit thresholds and domain/formula conflict checks.
- Preserve tenant boundaries.
- Preserve decision history; corrections should supersede old decisions rather than erase history where supported.

---

## 9. Governance and Security Invariants

1. Human approval is mandatory for proposed KPI mappings.
2. HIGH confidence never auto-approves.
3. Overrides require justification and server-side validation.
4. Actions persist through existing service/repository layers.
5. Every tenant-scoped read/write is authorized.
6. Tenant ID from the browser is not proof of authorization.
7. Global ontology queries use the established authorized system-context mechanism.
8. Audit records are immutable/append-only according to the existing model.
9. Mapping reads canonical persisted metadata and does not reopen source files.
10. LLM output is validated and cannot invent KPI IDs or silently create KPI entries.
11. KPI creation uses authoritative schema and duplicate/equivalence checks.
12. Secrets never reach React, logs, prompts, audit payloads, or client responses.
13. The UI never shows fake success states or fabricated operational data.
14. Tests must not mutate `local_data/kpi_intelligence.sqlite3`.
15. Do not claim live Azure Cosmos DB or Azure AI Foundry connectivity unless it was actually tested and authorized.

---

## 10. Current Frontend and Known Defects

The screenshots show eight views with a persistent left navigation, light Apple-inspired styling, blue active states, and top-level status/actions. However, the current UI has substantial usability defects:

- Text and labels run together; spacing and hierarchy are inconsistent.
- Internal domain codes, display names, counts, descriptions, and buttons concatenate.
- Pipeline steps appear as unstructured inline text.
- Domain distribution looks like raw lines such as `CLAIMS_RISKClaims & Risk4`.
- No obvious Upload Files or Select Folder workflow.
- Domain reclassification button is attached to the `UNCLASSIFIED` text.
- Candidate table shows “No candidate” without clearly distinguishing not-run, no-match, and failure.
- Human Review contains “No proposal” items and unclear/disabled actions; a `100 Pending Review` badge may be hard-coded and must be checked against real backend data.
- KPI Bank entries appear as dense continuous text instead of a table/cards.
- Empty states for Overrides and Audit do not clearly distinguish no data from request failure.
- “Deterministic Fallback Active” must reflect actual backend status, not a static badge.

Required correction:
- Fix CSS/layout root causes, not by inserting arbitrary spaces into strings.
- Establish typography/spacing tokens and reusable grid/card/table/button/badge patterns.
- Use human-readable domain names; codes may be muted secondary labels.
- Render a proper stepper for pipeline stages.
- Use readable tables/cards, filters, pagination, detail drawers, and loading/empty/error states.
- Disable approval if no valid candidate is selected.
- Ensure every action's success state comes from a real FastAPI response.
- Support keyboard navigation, visible focus, contrast, reduced motion, and responsive layout.
- Keep Apple-inspired styling restrained; clarity first.

A detailed earlier prompt was created at `Antigravity_KPI_Intelligence_UI_Upload_Folder_Fix_Prompt.md`. It may or may not have been applied. Inspect the actual branch before relying on it.

---

## 11. Intended API Capabilities

Previous plan and report use inconsistent route names (singular `/api/v1/mapping/...` vs plural `/api/v1/mappings/...`). Inspect the current FastAPI app/OpenAPI schema and standardize on one API contract. Do not create duplicate routes unnecessarily.

Required capabilities:
- Workspace summary and safe LLM/fallback status.
- Domain list/metrics.
- Canonical metadata list/detail.
- Human domain correction.
- Mapping run.
- Candidate retrieval/proposal details.
- Approve, reject, override.
- KPI Bank search/list/create.
- Override/learning list and metrics.
- Audit history.
- Ingestion upload, folder upload, supported formats, ingestion job status, source inventory.

A previous implementation report listed routes such as:
- `GET /api/v1/workspace/summary`
- `GET /api/v1/domains`
- `GET /api/v1/metadata/fields`
- `POST /api/v1/mappings/run`
- `GET /api/v1/mappings/proposals`
- Approval/rejection/override routes
- KPI Bank and audit routes

The written plan also lists singular `/api/v1/mapping/...` routes. Select one canonical design and align backend, frontend, tests, OpenAPI and README. If compatibility aliases are necessary, document and test them.

---

## 12. Historical Test/Validation Report

Antigravity previously reported:
- 22 mapping/governance tests passed.
- Full Python suite: 149 tests discovered; 148 passed, 1 skipped.
- `scripts/validate_canonical_model.py`: 36/36 checks passed.
- `scripts/validate_cross_representation.py`: 636/636 columns passed static/runtime reconciliation; SQLite integrity `ok`.
- PostgreSQL schema: 61 tables, 636 columns, 109 foreign keys.
- Cross-representation validator reported 25 document types and 61 migration handlers.

These are historical reported results only. Re-run checks against the current branch. Do not change tests solely to make them green.

Required validation categories:
- Mapping/governance tests and full Python suite.
- Canonical and cross-representation validators.
- FastAPI route tests with test client.
- Tenant isolation tests.
- Mocked Azure Llama structured-output and fallback tests.
- Override fingerprint/re-ingestion/conflict tests.
- KPI Bank schema and duplicate tests.
- React tests and production build.
- Ingestion validation and job-state tests.
- End-to-end flow: select/upload supported source → ingest through FastAPI → canonical metadata visible → explicit mapping run → candidates shown → human decision persisted.
- Confirm the local SQLite database was not modified.

Do not run live Cosmos/Azure model calls in normal tests. Use mocks unless a separately authorized live diagnostic is required.

---

## 13. Working Instructions for Claude and Claude Code

Claude is expected to become the ongoing project-context owner and produce future Claude Code prompts.

### Before any implementation prompt or code change
1. Inspect the current repository tree, README, dependencies, branch/diff, relevant services/contracts/tests, and OpenAPI schema.
2. Determine what is actually implemented, partially implemented, or missing.
3. Use code and tests as the source of truth; this document is context, not proof of current completion.
4. If a specific archive/repository snapshot is supplied, inspect that exact version.

### Preserve architecture/data
- Do not rewrite from scratch.
- Do not bypass canonical repositories, tenant context, governance services, or audit.
- Do not mutate `local_data/kpi_intelligence.sqlite3` during UI tests or speculative work.
- Do not modify the 61-table/636-column schema or contracts unnecessarily.
- Schema changes must be additive/backward-compatible unless a migration is explicitly designed and approved.
- Do not create cloud resources or perform cloud writes without authorization.
- Do not claim live Azure/Cosmos validation unless actually performed.

### When creating Claude Code prompts
Include:
1. Objective and observed problem.
2. Repository inspection and baseline tests.
3. Files/components to inspect without assuming they exist.
4. Desired behavior and architectural boundaries.
5. Non-negotiable invariants.
6. Acceptance criteria and tests.
7. Verified commands where possible.
8. Required final report: files changed, tests/results, unresolved risks, migrations, and explicit statement about database/cloud operations.

Prompts should direct Claude Code to implement and verify unless the user asks for planning only. Keep changes focused; avoid speculative refactors.

### Be precise about uncertainty
- Separate historical claims from verified facts.
- Do not invent routes, dependencies, format support, or cloud capability.
- Ask for clarification only when repository inspection cannot resolve a material ambiguity.
- Explain conflicts and choose the smallest safe correction.
- Never claim a build/test passed if it was not run.

### Security and governance
- No secrets in prompts, code, logs, frontend bundles, or reports.
- Authorize every tenant-scoped operation.
- No automatic approval, even for HIGH confidence.
- Every override needs justification and auditability.
- No invented KPI IDs or silent LLM-created KPI Bank entries.
- No raw hidden chain-of-thought in UI/logs.
- Uploaded files must be validated and processed through existing ingestion services.

---

## 14. Unresolved Items to Verify from the Current Repository

Do not assume these are complete:
1. Whether `http.server` was fully replaced by FastAPI.
2. Whether the frontend is genuinely React and builds successfully.
3. Whether Azure AI Foundry Llama integration is implemented and tested against the actual endpoint/API protocol.
4. The exact meanings of `AZURE_DEPLOYMENT` and `AZURE_DEPLOYMENT_NAME`.
5. Which source formats are actually supported.
6. Whether file upload and folder selection work end to end.
7. Whether screenshot UI defects have been fixed.
8. Whether API route names are consistent between backend and frontend.
9. Whether production authentication exists or the tenant selector is only a development control.
10. Whether override/mapping data persists to live Cosmos DB.
11. Whether the historical test results still reproduce.

Resolve these through repository inspection and tests, not guesswork.

---

## 15. Desired End-to-End User Workflow

1. **Workspace:** Show real metrics, actual LLM/fallback status, source inventory, and next action.
2. **Add sources:** Upload supported files, select a folder, or use a separately supported authorized storage connector.
3. **Validate/ingest:** Preview files, identify unsupported items, start ingestion explicitly, track progress.
4. **Inspect metadata:** Review extracted reports, semantic models, measures, columns, calculations, source assets, and context.
5. **Classify domains:** Review five primary domains plus legacy Service & Operations where applicable; correct classifications with audit history.
6. **Run mapping:** Explicitly trigger matching. Reuse valid overrides first; otherwise retrieve candidates.
7. **Rank candidates:** Llama ranks retrieved candidates when configured/available; deterministic fallback handles unavailable or invalid LLM output.
8. **Review evidence:** Compare up to three candidates with domain, formula, aggregation, required fields, dimensions, missing information, contradictions, and ranking rationale.
9. **Governance decision:** Approve, reject, choose another KPI with mandatory justification, or create a new KPI using the authoritative schema.
10. **Persist/audit:** Store decision, actor, timestamp, justification, provenance, and audit event.
11. **Learn on re-ingestion:** Reuse valid fingerprints/overrides and route conflicts to human review.
12. **Monitor:** Inspect audit history, override reuse, mapping outcomes, ingestion failures, and LLM/fallback status.

The final product must be secure, explainable, multi-tenant, testable, and usable by business analysts.

---

## Final instruction to Claude

Treat this as the persistent high-level project handover. Before recommending changes or creating Claude Code prompts, inspect the current repository and reconcile this document with the actual implementation. Preserve all invariants. Explicitly distinguish verified facts, historical reports, and unresolved items. Update the project context when verified architecture or behavior changes.
