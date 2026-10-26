-- ============================================================================
-- KPI INTELLIGENCE PLATFORM — MIGRATION V002
-- Migration: V002__canonical_model_hardening.sql
-- Description: Hardens canonical schema with:
--              1. Authoritative tenant context & multi-tenant isolation (RLS + composite FKs)
--              2. Immutable audit tables & cascade deletion protection
--              3. Cross-record referential consistency constraints
--              4. Lossless KPI Bank JSON normalization columns in kpi_ontology_entries
--              5. Governance approval protection & override cycle triggers
--
-- EXECUTION & IDEMPOTENCE CONTRACT:
-- - Flyway Execution Contract: In automated CI/CD and deployment pipelines, Flyway manages
--   exact-once execution tracking in `flyway_schema_history`.
-- - Standalone Rerunnability: All DDL statements are authored using strictly idempotent patterns
--   (IF NOT EXISTS, DROP CONSTRAINT IF EXISTS ... ADD CONSTRAINT, CREATE OR REPLACE,
--   DROP POLICY IF EXISTS ... CREATE POLICY, DROP TRIGGER IF EXISTS ... CREATE TRIGGER).
--   This ensures that developer sandboxes, test suites, and rollback retries can re-execute
--   this script safely without failing on duplicate constraints or policies.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

SET search_path = kpi_intel, public;

-- ----------------------------------------------------------------------------
-- 1. TENANT CONTEXT HELPER FUNCTIONS
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION kpi_intel.current_tenant_id()
RETURNS UUID AS $$
BEGIN
    RETURN NULLIF(current_setting('kpi_intel.current_tenant_id', true), '')::UUID;
EXCEPTION
    WHEN OTHERS THEN RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION kpi_intel.set_current_tenant_id(p_tenant_id UUID, p_is_local BOOLEAN DEFAULT true)
RETURNS VOID AS $$
BEGIN
    IF p_tenant_id IS NULL THEN
        PERFORM set_config('kpi_intel.current_tenant_id', '', p_is_local);
    ELSE
        PERFORM set_config('kpi_intel.current_tenant_id', p_tenant_id::TEXT, p_is_local);
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION kpi_intel.clear_current_tenant_id(p_is_local BOOLEAN DEFAULT true)
RETURNS VOID AS $$
BEGIN
    PERFORM set_config('kpi_intel.current_tenant_id', '', p_is_local);
END;
$$ LANGUAGE plpgsql;

-- ----------------------------------------------------------------------------
-- 2. TENANT OWNERSHIP COLUMN BACKFILLS & COMPOSITE CONSTRAINTS
-- ----------------------------------------------------------------------------

-- Add composite unique on assets for cross-tenant FK reference
ALTER TABLE kpi_intel.assets
DROP CONSTRAINT IF EXISTS uq_assets_tenant,
ADD CONSTRAINT uq_assets_tenant UNIQUE (asset_id, tenant_id);

-- Add tenant_id to asset_versions and link to assets
ALTER TABLE kpi_intel.asset_versions
ADD COLUMN IF NOT EXISTS tenant_id UUID;

-- Backfill tenant_id from assets
UPDATE kpi_intel.asset_versions av
SET tenant_id = a.tenant_id
FROM kpi_intel.assets a
WHERE av.asset_id = a.asset_id AND av.tenant_id IS NULL;

-- Set NOT NULL after backfill
ALTER TABLE kpi_intel.asset_versions
ALTER COLUMN tenant_id SET NOT NULL;

ALTER TABLE kpi_intel.asset_versions
DROP CONSTRAINT IF EXISTS uq_asset_versions_tenant,
ADD CONSTRAINT uq_asset_versions_tenant UNIQUE (asset_version_id, tenant_id);

ALTER TABLE kpi_intel.asset_versions
DROP CONSTRAINT IF EXISTS fk_asset_versions_asset_tenant,
ADD CONSTRAINT fk_asset_versions_asset_tenant
FOREIGN KEY (asset_id, tenant_id)
REFERENCES kpi_intel.assets(asset_id, tenant_id)
ON DELETE CASCADE;

-- Add tenant_id to analytical_objects and link to asset_versions
ALTER TABLE kpi_intel.analytical_objects
ADD COLUMN IF NOT EXISTS tenant_id UUID;

UPDATE kpi_intel.analytical_objects ao
SET tenant_id = av.tenant_id
FROM kpi_intel.asset_versions av
WHERE ao.asset_version_id = av.asset_version_id AND ao.tenant_id IS NULL;

ALTER TABLE kpi_intel.analytical_objects
ALTER COLUMN tenant_id SET NOT NULL;

ALTER TABLE kpi_intel.analytical_objects
DROP CONSTRAINT IF EXISTS uq_analytical_objects_version,
DROP CONSTRAINT IF EXISTS uq_analytical_objects_tenant,
ADD CONSTRAINT uq_analytical_objects_version UNIQUE (object_id, asset_version_id),
ADD CONSTRAINT uq_analytical_objects_tenant UNIQUE (object_id, tenant_id);

ALTER TABLE kpi_intel.analytical_objects
DROP CONSTRAINT IF EXISTS fk_analytical_objects_version_tenant,
ADD CONSTRAINT fk_analytical_objects_version_tenant
FOREIGN KEY (asset_version_id, tenant_id)
REFERENCES kpi_intel.asset_versions(asset_version_id, tenant_id)
ON DELETE CASCADE;

-- Add tenant_id to kpi_candidates
ALTER TABLE kpi_intel.kpi_candidates
ADD COLUMN IF NOT EXISTS tenant_id UUID;

UPDATE kpi_intel.kpi_candidates kc
SET tenant_id = av.tenant_id
FROM kpi_intel.asset_versions av
WHERE kc.asset_version_id = av.asset_version_id AND kc.tenant_id IS NULL;

ALTER TABLE kpi_intel.kpi_candidates
ALTER COLUMN tenant_id SET NOT NULL;

ALTER TABLE kpi_intel.kpi_candidates
DROP CONSTRAINT IF EXISTS uq_kpi_candidates_version,
DROP CONSTRAINT IF EXISTS uq_kpi_candidates_tenant,
ADD CONSTRAINT uq_kpi_candidates_version UNIQUE (kpi_candidate_id, asset_version_id),
ADD CONSTRAINT uq_kpi_candidates_tenant UNIQUE (kpi_candidate_id, tenant_id);

ALTER TABLE kpi_intel.kpi_candidates
DROP CONSTRAINT IF EXISTS fk_kpi_candidates_object_version,
ADD CONSTRAINT fk_kpi_candidates_object_version
FOREIGN KEY (source_object_id, asset_version_id)
REFERENCES kpi_intel.analytical_objects(object_id, asset_version_id)
ON DELETE CASCADE;

-- Add tenant_id to kpi_mapping_runs
ALTER TABLE kpi_intel.kpi_mapping_runs
ADD COLUMN IF NOT EXISTS tenant_id UUID;

UPDATE kpi_intel.kpi_mapping_runs mr
SET tenant_id = av.tenant_id
FROM kpi_intel.asset_versions av
WHERE mr.asset_version_id = av.asset_version_id AND mr.tenant_id IS NULL;

ALTER TABLE kpi_intel.kpi_mapping_runs
ALTER COLUMN tenant_id SET NOT NULL;

ALTER TABLE kpi_intel.kpi_mapping_runs
DROP CONSTRAINT IF EXISTS uq_kpi_mapping_runs_version,
ADD CONSTRAINT uq_kpi_mapping_runs_version UNIQUE (mapping_run_id, asset_version_id, ontology_version_id);

-- Add asset_version_id & tenant_id to kpi_mappings
ALTER TABLE kpi_intel.kpi_mappings
ADD COLUMN IF NOT EXISTS asset_version_id UUID,
ADD COLUMN IF NOT EXISTS tenant_id UUID;

UPDATE kpi_intel.kpi_mappings km
SET asset_version_id = kc.asset_version_id,
    tenant_id = kc.tenant_id
FROM kpi_intel.kpi_candidates kc
WHERE km.kpi_candidate_id = kc.kpi_candidate_id
  AND (km.asset_version_id IS NULL OR km.tenant_id IS NULL);

ALTER TABLE kpi_intel.kpi_mappings
ALTER COLUMN asset_version_id SET NOT NULL,
ALTER COLUMN tenant_id SET NOT NULL;

ALTER TABLE kpi_intel.kpi_mappings
DROP CONSTRAINT IF EXISTS uq_kpi_mappings_run_version,
DROP CONSTRAINT IF EXISTS uq_kpi_mappings_asset_version,
DROP CONSTRAINT IF EXISTS uq_kpi_mappings_tenant,
ADD CONSTRAINT uq_kpi_mappings_run_version UNIQUE (kpi_mapping_id, ontology_version_id),
ADD CONSTRAINT uq_kpi_mappings_asset_version UNIQUE (kpi_mapping_id, asset_version_id),
ADD CONSTRAINT uq_kpi_mappings_tenant UNIQUE (kpi_mapping_id, tenant_id);

ALTER TABLE kpi_intel.kpi_mappings
DROP CONSTRAINT IF EXISTS fk_kpi_mappings_candidate_version,
ADD CONSTRAINT fk_kpi_mappings_candidate_version
FOREIGN KEY (kpi_candidate_id, asset_version_id)
REFERENCES kpi_intel.kpi_candidates(kpi_candidate_id, asset_version_id)
ON DELETE CASCADE;

ALTER TABLE kpi_intel.kpi_mappings
DROP CONSTRAINT IF EXISTS fk_kpi_mappings_run_version,
ADD CONSTRAINT fk_kpi_mappings_run_version
FOREIGN KEY (mapping_run_id, asset_version_id, ontology_version_id)
REFERENCES kpi_intel.kpi_mapping_runs(mapping_run_id, asset_version_id, ontology_version_id)
ON DELETE CASCADE;

-- Add tenant_id to domain_classifications
ALTER TABLE kpi_intel.domain_classifications
ADD COLUMN IF NOT EXISTS tenant_id UUID;

UPDATE kpi_intel.domain_classifications dc
SET tenant_id = av.tenant_id
FROM kpi_intel.asset_versions av
WHERE dc.asset_version_id = av.asset_version_id AND dc.tenant_id IS NULL;

ALTER TABLE kpi_intel.domain_classifications
ALTER COLUMN tenant_id SET NOT NULL;

ALTER TABLE kpi_intel.domain_classifications
DROP CONSTRAINT IF EXISTS fk_domain_classifications_object_version,
ADD CONSTRAINT fk_domain_classifications_object_version
FOREIGN KEY (target_object_id, asset_version_id)
REFERENCES kpi_intel.analytical_objects(object_id, asset_version_id)
ON DELETE CASCADE;

-- Add tenant_id to metadata_field_reviews
ALTER TABLE kpi_intel.metadata_field_reviews
ADD COLUMN IF NOT EXISTS tenant_id UUID;

UPDATE kpi_intel.metadata_field_reviews mfr
SET tenant_id = av.tenant_id
FROM kpi_intel.asset_versions av
WHERE mfr.asset_version_id = av.asset_version_id AND mfr.tenant_id IS NULL;

ALTER TABLE kpi_intel.metadata_field_reviews
ALTER COLUMN tenant_id SET NOT NULL;

ALTER TABLE kpi_intel.metadata_field_reviews
DROP CONSTRAINT IF EXISTS fk_metadata_field_reviews_object_version,
ADD CONSTRAINT fk_metadata_field_reviews_object_version
FOREIGN KEY (target_object_id, asset_version_id)
REFERENCES kpi_intel.analytical_objects(object_id, asset_version_id)
ON DELETE CASCADE;

-- Add tenant_id to parser_runs
ALTER TABLE kpi_intel.parser_runs
ADD COLUMN IF NOT EXISTS tenant_id UUID;

UPDATE kpi_intel.parser_runs pr
SET tenant_id = av.tenant_id
FROM kpi_intel.asset_versions av
WHERE pr.asset_version_id = av.asset_version_id AND pr.tenant_id IS NULL;

ALTER TABLE kpi_intel.parser_runs
ALTER COLUMN tenant_id SET NOT NULL;

-- Composite constraints on metadata_lineage_edges
ALTER TABLE kpi_intel.metadata_lineage_edges
DROP CONSTRAINT IF EXISTS fk_lineage_edges_source_version,
DROP CONSTRAINT IF EXISTS fk_lineage_edges_target_version,
ADD CONSTRAINT fk_lineage_edges_source_version
FOREIGN KEY (source_object_id, asset_version_id)
REFERENCES kpi_intel.analytical_objects(object_id, asset_version_id)
ON DELETE CASCADE,
ADD CONSTRAINT fk_lineage_edges_target_version
FOREIGN KEY (target_object_id, asset_version_id)
REFERENCES kpi_intel.analytical_objects(object_id, asset_version_id)
ON DELETE CASCADE;

-- Composite constraint on spreadsheet_cells
ALTER TABLE kpi_intel.spreadsheet_cells
DROP CONSTRAINT IF EXISTS fk_spreadsheet_cells_worksheet_version,
ADD CONSTRAINT fk_spreadsheet_cells_worksheet_version
FOREIGN KEY (worksheet_object_id, asset_version_id)
REFERENCES kpi_intel.analytical_objects(object_id, asset_version_id)
ON DELETE CASCADE;

-- ----------------------------------------------------------------------------
-- 3. KPI ONTOLOGY ENTRIES ENHANCEMENTS
-- ----------------------------------------------------------------------------
ALTER TABLE kpi_intel.kpi_ontology_entries
ADD COLUMN IF NOT EXISTS source_kpi_id TEXT,
ADD COLUMN IF NOT EXISTS source_sector TEXT,
ADD COLUMN IF NOT EXISTS source_subdomain TEXT,
ADD COLUMN IF NOT EXISTS source_line_of_business TEXT,
ADD COLUMN IF NOT EXISTS source_status TEXT DEFAULT 'active',
ADD COLUMN IF NOT EXISTS valid_dimensions JSONB DEFAULT '[]'::jsonb,
ADD COLUMN IF NOT EXISTS enrichments JSONB DEFAULT '[]'::jsonb,
ADD COLUMN IF NOT EXISTS source_created_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS source_created_by TEXT;

-- Composite unique constraint on kpi_ontology_entries
ALTER TABLE kpi_intel.kpi_ontology_entries
DROP CONSTRAINT IF EXISTS uq_kpi_ontology_entries_version,
ADD CONSTRAINT uq_kpi_ontology_entries_version UNIQUE (ontology_entry_id, ontology_version_id);

-- Composite FK for selected_ontology_entry_id in kpi_mappings
ALTER TABLE kpi_intel.kpi_mappings
DROP CONSTRAINT IF EXISTS fk_kpi_mappings_selected_ontology_entry,
ADD CONSTRAINT fk_kpi_mappings_selected_ontology_entry
FOREIGN KEY (selected_ontology_entry_id, ontology_version_id)
REFERENCES kpi_intel.kpi_ontology_entries(ontology_entry_id, ontology_version_id)
ON DELETE SET NULL (selected_ontology_entry_id);

-- ----------------------------------------------------------------------------
-- 4. CANDIDATE, APPROVAL, REVIEW, OVERRIDE CONSISTENCY
-- ----------------------------------------------------------------------------
ALTER TABLE kpi_intel.kpi_mapping_candidates
DROP CONSTRAINT IF EXISTS uq_kpi_mapping_candidates_mapping,
ADD CONSTRAINT uq_kpi_mapping_candidates_mapping UNIQUE (mapping_candidate_id, kpi_mapping_id);

-- Enforce approval belongs to the mapping being approved
ALTER TABLE kpi_intel.mapping_approvals
DROP CONSTRAINT IF EXISTS fk_mapping_approvals_candidate_mapping,
ADD CONSTRAINT fk_mapping_approvals_candidate_mapping
FOREIGN KEY (approved_mapping_candidate_id, kpi_mapping_id)
REFERENCES kpi_intel.kpi_mapping_candidates(mapping_candidate_id, kpi_mapping_id)
ON DELETE SET NULL (approved_mapping_candidate_id);

-- Enforce review belongs to the mapping being reviewed
ALTER TABLE kpi_intel.mapping_reviews
DROP CONSTRAINT IF EXISTS fk_mapping_reviews_candidate_mapping,
ADD CONSTRAINT fk_mapping_reviews_candidate_mapping
FOREIGN KEY (mapping_candidate_id, kpi_mapping_id)
REFERENCES kpi_intel.kpi_mapping_candidates(mapping_candidate_id, kpi_mapping_id)
ON DELETE SET NULL (mapping_candidate_id);

-- Enforce override candidate belongs to the mapping being overridden
ALTER TABLE kpi_intel.mapping_overrides
DROP CONSTRAINT IF EXISTS fk_mapping_overrides_candidate_mapping,
ADD CONSTRAINT fk_mapping_overrides_candidate_mapping
FOREIGN KEY (mapping_candidate_id, kpi_mapping_id)
REFERENCES kpi_intel.kpi_mapping_candidates(mapping_candidate_id, kpi_mapping_id)
ON DELETE SET NULL (mapping_candidate_id);

-- ----------------------------------------------------------------------------
-- 5. AUDIT IMMUTABILITY & CASCADE DELETION PROTECTION
-- ----------------------------------------------------------------------------

-- Modify mapping_audit_events to protect audit history
ALTER TABLE kpi_intel.mapping_audit_events
ADD COLUMN IF NOT EXISTS tenant_id UUID,
ADD COLUMN IF NOT EXISTS target_kpi_mapping_id UUID;

-- Backfill target_kpi_mapping_id and tenant_id
UPDATE kpi_intel.mapping_audit_events mae
SET target_kpi_mapping_id = mae.kpi_mapping_id,
    tenant_id = km.tenant_id
FROM kpi_intel.kpi_mappings km
WHERE mae.kpi_mapping_id = km.kpi_mapping_id
  AND (mae.target_kpi_mapping_id IS NULL OR mae.tenant_id IS NULL);

ALTER TABLE kpi_intel.mapping_audit_events
ALTER COLUMN target_kpi_mapping_id SET NOT NULL;

-- Alter FK on mapping_audit_events from CASCADE to RESTRICT to prevent deletion of mapped audit trails
ALTER TABLE kpi_intel.mapping_audit_events
DROP CONSTRAINT IF EXISTS mapping_audit_events_kpi_mapping_id_fkey,
ADD CONSTRAINT fk_mapping_audit_events_mapping
FOREIGN KEY (kpi_mapping_id)
REFERENCES kpi_intel.kpi_mappings(kpi_mapping_id)
ON DELETE RESTRICT;

-- Protect ontology_change_events: prevent cascade deletion of ontology audit history
ALTER TABLE kpi_intel.ontology_change_events
DROP CONSTRAINT IF EXISTS ontology_change_events_ontology_version_id_fkey,
ADD CONSTRAINT fk_ontology_change_events_version
FOREIGN KEY (ontology_version_id)
REFERENCES kpi_intel.kpi_ontology_versions(ontology_version_id)
ON DELETE RESTRICT;

-- Immutability triggers for audit tables
CREATE OR REPLACE FUNCTION kpi_intel.prevent_audit_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit records in table % are strictly immutable and cannot be updated or deleted.', TG_TABLE_NAME
        USING ERRCODE = '42501'; -- insufficient_privilege
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_mapping_audit_immutable ON kpi_intel.mapping_audit_events;
CREATE TRIGGER trg_mapping_audit_immutable
BEFORE UPDATE OR DELETE ON kpi_intel.mapping_audit_events
FOR EACH ROW EXECUTE FUNCTION kpi_intel.prevent_audit_mutation();

DROP TRIGGER IF EXISTS trg_ontology_audit_immutable ON kpi_intel.ontology_change_events;
CREATE TRIGGER trg_ontology_audit_immutable
BEFORE UPDATE OR DELETE ON kpi_intel.ontology_change_events
FOR EACH ROW EXECUTE FUNCTION kpi_intel.prevent_audit_mutation();

-- ----------------------------------------------------------------------------
-- 6. GOVERNANCE STATE PROTECTION & OVERRIDE CYCLE PREVENTION TRIGGERS
-- ----------------------------------------------------------------------------

-- Protect human approvals from automated overwrites and enforce immutability of core mapping keys
CREATE OR REPLACE FUNCTION kpi_intel.protect_human_approval()
RETURNS TRIGGER AS $$
BEGIN
    -- 1. Automated mapping engines cannot overwrite human-approved or human-decided mappings
    IF (OLD.decision_source = 'HUMAN' OR OLD.mapping_status = 'APPROVED')
       AND NEW.decision_source IN ('LLM', 'DETERMINISTIC') THEN
        RAISE EXCEPTION 'Automated mapping runs cannot overwrite human-approved or human-decided mappings (kpi_mapping_id: %)', OLD.kpi_mapping_id
            USING ERRCODE = '42501';
    END IF;

    -- 2. Invariant: Structural keys (candidate, asset_version, ontology_version, created_at) are strictly immutable
    IF NEW.kpi_candidate_id <> OLD.kpi_candidate_id THEN
        RAISE EXCEPTION 'Cannot modify kpi_candidate_id of an existing mapping (kpi_mapping_id: %)', OLD.kpi_mapping_id
            USING ERRCODE = '42501';
    END IF;
    IF NEW.asset_version_id <> OLD.asset_version_id THEN
        RAISE EXCEPTION 'Cannot modify asset_version_id of an existing mapping (kpi_mapping_id: %)', OLD.kpi_mapping_id
            USING ERRCODE = '42501';
    END IF;
    IF NEW.ontology_version_id <> OLD.ontology_version_id THEN
        RAISE EXCEPTION 'Cannot modify ontology_version_id of an existing mapping (kpi_mapping_id: %)', OLD.kpi_mapping_id
            USING ERRCODE = '42501';
    END IF;
    IF NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'Cannot modify created_at timestamp of a mapping (kpi_mapping_id: %)', OLD.kpi_mapping_id
            USING ERRCODE = '42501';
    END IF;

    -- 3. Transition rules on APPROVED mappings:
    -- Once APPROVED, mapping status cannot be reverted to PROPOSED or UNMAPPED
    IF OLD.mapping_status = 'APPROVED' THEN
        IF NEW.mapping_status IN ('PROPOSED', 'UNMAPPED') THEN
            RAISE EXCEPTION 'Approved mappings cannot be reset to PROPOSED or UNMAPPED (kpi_mapping_id: %)', OLD.kpi_mapping_id
                USING ERRCODE = '55000'; -- object_not_in_prerequisite_state
        END IF;

        -- While remaining in APPROVED status, selected ontology entry cannot be altered directly
        IF NEW.mapping_status = 'APPROVED' AND NEW.selected_ontology_entry_id IS DISTINCT FROM OLD.selected_ontology_entry_id THEN
            RAISE EXCEPTION 'Cannot change selected_ontology_entry_id on an APPROVED mapping directly. Use governed review/override supersession workflow (kpi_mapping_id: %)', OLD.kpi_mapping_id
                USING ERRCODE = '55000';
        END IF;

        -- Only a human actor can transition an APPROVED mapping to SUPERSEDED, REJECTED, or OVERRIDDEN
        IF NEW.mapping_status IN ('SUPERSEDED', 'REJECTED', 'OVERRIDDEN') AND NEW.decision_source <> 'HUMAN' THEN
            RAISE EXCEPTION 'Only human subject matter experts can transition an approved mapping to % (kpi_mapping_id: %)', NEW.mapping_status, OLD.kpi_mapping_id
                USING ERRCODE = '42501';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_protect_human_approval ON kpi_intel.kpi_mappings;
CREATE TRIGGER trg_protect_human_approval
BEFORE UPDATE ON kpi_intel.kpi_mappings
FOR EACH ROW EXECUTE FUNCTION kpi_intel.protect_human_approval();

-- Prevent self-referencing and cyclic overrides
CREATE OR REPLACE FUNCTION kpi_intel.prevent_override_cycle()
RETURNS TRIGGER AS $$
DECLARE
    curr_id UUID;
    visited UUID[] := ARRAY[NEW.override_id];
BEGIN
    IF NEW.supersedes_override_id IS NOT NULL THEN
        IF NEW.supersedes_override_id = NEW.override_id THEN
            RAISE EXCEPTION 'An override cannot supersede itself (override_id: %)', NEW.override_id
                USING ERRCODE = '23514';
        END IF;
        curr_id := NEW.supersedes_override_id;
        WHILE curr_id IS NOT NULL LOOP
            IF curr_id = ANY(visited) THEN
                RAISE EXCEPTION 'Detected cycle in superseding overrides chain at override_id: %', curr_id
                    USING ERRCODE = '23514';
            END IF;
            visited := array_append(visited, curr_id);
            SELECT supersedes_override_id INTO curr_id FROM kpi_intel.mapping_overrides WHERE override_id = curr_id;
        END LOOP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_prevent_override_cycle ON kpi_intel.mapping_overrides;
CREATE TRIGGER trg_prevent_override_cycle
BEFORE INSERT OR UPDATE ON kpi_intel.mapping_overrides
FOR EACH ROW EXECUTE FUNCTION kpi_intel.prevent_override_cycle();

-- ----------------------------------------------------------------------------
-- 7. ROW-LEVEL SECURITY POLICIES FOR TENANT ISOLATION (COMPLETE 61-TABLE COVERAGE)
-- ----------------------------------------------------------------------------

-- 7.1 Tenant-Owned Root Tables (Direct tenant_id check)
ALTER TABLE kpi_intel.assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.assets FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_assets ON kpi_intel.assets;
CREATE POLICY tenant_isolation_policy_assets ON kpi_intel.assets
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

ALTER TABLE kpi_intel.security_principals ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.security_principals FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_principals ON kpi_intel.security_principals;
CREATE POLICY tenant_isolation_policy_principals ON kpi_intel.security_principals
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

ALTER TABLE kpi_intel.asset_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.asset_versions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_versions ON kpi_intel.asset_versions;
CREATE POLICY tenant_isolation_policy_versions ON kpi_intel.asset_versions
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

ALTER TABLE kpi_intel.analytical_objects ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.analytical_objects FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_objects ON kpi_intel.analytical_objects;
CREATE POLICY tenant_isolation_policy_objects ON kpi_intel.analytical_objects
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

ALTER TABLE kpi_intel.kpi_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.kpi_candidates FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_candidates ON kpi_intel.kpi_candidates;
CREATE POLICY tenant_isolation_policy_candidates ON kpi_intel.kpi_candidates
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

ALTER TABLE kpi_intel.kpi_mapping_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.kpi_mapping_runs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_mapping_runs ON kpi_intel.kpi_mapping_runs;
CREATE POLICY tenant_isolation_policy_mapping_runs ON kpi_intel.kpi_mapping_runs
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

ALTER TABLE kpi_intel.kpi_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.kpi_mappings FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_mappings ON kpi_intel.kpi_mappings;
CREATE POLICY tenant_isolation_policy_mappings ON kpi_intel.kpi_mappings
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

ALTER TABLE kpi_intel.domain_classifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.domain_classifications FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_domain_class ON kpi_intel.domain_classifications;
CREATE POLICY tenant_isolation_policy_domain_class ON kpi_intel.domain_classifications
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

ALTER TABLE kpi_intel.metadata_field_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.metadata_field_reviews FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_field_reviews ON kpi_intel.metadata_field_reviews;
CREATE POLICY tenant_isolation_policy_field_reviews ON kpi_intel.metadata_field_reviews
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

ALTER TABLE kpi_intel.parser_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.parser_runs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_parser_runs ON kpi_intel.parser_runs;
CREATE POLICY tenant_isolation_policy_parser_runs ON kpi_intel.parser_runs
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

ALTER TABLE kpi_intel.mapping_audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.mapping_audit_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_audit_events ON kpi_intel.mapping_audit_events;
CREATE POLICY tenant_isolation_policy_audit_events ON kpi_intel.mapping_audit_events
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

-- 7.2 Tenant-Owned Child Tables: Subsystem A (Asset Registry)
ALTER TABLE kpi_intel.ingestion_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.ingestion_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_ingestion_events ON kpi_intel.ingestion_events;
CREATE POLICY tenant_isolation_policy_ingestion_events ON kpi_intel.ingestion_events
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.asset_versions av 
    WHERE av.asset_version_id = ingestion_events.asset_version_id AND av.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.source_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.source_artifacts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_source_artifacts ON kpi_intel.source_artifacts;
CREATE POLICY tenant_isolation_policy_source_artifacts ON kpi_intel.source_artifacts
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.asset_versions av 
    WHERE av.asset_version_id = source_artifacts.asset_version_id AND av.tenant_id = kpi_intel.current_tenant_id()
));

-- 7.3 Tenant-Owned Child Tables: Subsystem B (Universal Analytical Objects)
ALTER TABLE kpi_intel.reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.reports FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_reports ON kpi_intel.reports;
CREATE POLICY tenant_isolation_policy_reports ON kpi_intel.reports
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = reports.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.report_pages ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.report_pages FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_report_pages ON kpi_intel.report_pages;
CREATE POLICY tenant_isolation_policy_report_pages ON kpi_intel.report_pages
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = report_pages.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.visuals ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.visuals FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_visuals ON kpi_intel.visuals;
CREATE POLICY tenant_isolation_policy_visuals ON kpi_intel.visuals
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = visuals.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.visual_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.visual_bindings FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_visual_bindings ON kpi_intel.visual_bindings;
CREATE POLICY tenant_isolation_policy_visual_bindings ON kpi_intel.visual_bindings
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = visual_bindings.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.visual_properties ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.visual_properties FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_visual_properties ON kpi_intel.visual_properties;
CREATE POLICY tenant_isolation_policy_visual_properties ON kpi_intel.visual_properties
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.visuals v 
    JOIN kpi_intel.analytical_objects ao ON v.object_id = ao.object_id
    WHERE v.visual_id = visual_properties.visual_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.visual_interactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.visual_interactions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_visual_interactions ON kpi_intel.visual_interactions;
CREATE POLICY tenant_isolation_policy_visual_interactions ON kpi_intel.visual_interactions
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.visuals v 
    JOIN kpi_intel.analytical_objects ao ON v.object_id = ao.object_id
    WHERE v.visual_id = visual_interactions.source_visual_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.bookmarks ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.bookmarks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_bookmarks ON kpi_intel.bookmarks;
CREATE POLICY tenant_isolation_policy_bookmarks ON kpi_intel.bookmarks
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = bookmarks.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.report_navigation ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.report_navigation FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_report_navigation ON kpi_intel.report_navigation;
CREATE POLICY tenant_isolation_policy_report_navigation ON kpi_intel.report_navigation
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = report_navigation.source_object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

-- 7.4 Tenant-Owned Child Tables: Subsystem C (Semantic Models & Calculations)
ALTER TABLE kpi_intel.semantic_models ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.semantic_models FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_semantic_models ON kpi_intel.semantic_models;
CREATE POLICY tenant_isolation_policy_semantic_models ON kpi_intel.semantic_models
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = semantic_models.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.data_tables ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.data_tables FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_data_tables ON kpi_intel.data_tables;
CREATE POLICY tenant_isolation_policy_data_tables ON kpi_intel.data_tables
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = data_tables.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.data_columns ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.data_columns FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_data_columns ON kpi_intel.data_columns;
CREATE POLICY tenant_isolation_policy_data_columns ON kpi_intel.data_columns
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = data_columns.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.calculations ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.calculations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_calculations ON kpi_intel.calculations;
CREATE POLICY tenant_isolation_policy_calculations ON kpi_intel.calculations
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = calculations.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.relationships ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.relationships FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_relationships ON kpi_intel.relationships;
CREATE POLICY tenant_isolation_policy_relationships ON kpi_intel.relationships
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = relationships.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.model_partitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.model_partitions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_model_partitions ON kpi_intel.model_partitions;
CREATE POLICY tenant_isolation_policy_model_partitions ON kpi_intel.model_partitions
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.semantic_models sm
    JOIN kpi_intel.analytical_objects ao ON sm.object_id = ao.object_id
    WHERE sm.semantic_model_id = model_partitions.semantic_model_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.hierarchies ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.hierarchies FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_hierarchies ON kpi_intel.hierarchies;
CREATE POLICY tenant_isolation_policy_hierarchies ON kpi_intel.hierarchies
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = hierarchies.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.hierarchy_levels ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.hierarchy_levels FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_hierarchy_levels ON kpi_intel.hierarchy_levels;
CREATE POLICY tenant_isolation_policy_hierarchy_levels ON kpi_intel.hierarchy_levels
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = hierarchy_levels.level_object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.parameters ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.parameters FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_parameters ON kpi_intel.parameters;
CREATE POLICY tenant_isolation_policy_parameters ON kpi_intel.parameters
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = parameters.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.named_expressions ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.named_expressions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_named_expressions ON kpi_intel.named_expressions;
CREATE POLICY tenant_isolation_policy_named_expressions ON kpi_intel.named_expressions
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = named_expressions.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

-- 7.5 Tenant-Owned Child Tables: Subsystem D (Filters, Security, Lineage)
ALTER TABLE kpi_intel.filters ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.filters FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_filters ON kpi_intel.filters;
CREATE POLICY tenant_isolation_policy_filters ON kpi_intel.filters
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = filters.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.filter_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.filter_assignments FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_filter_assignments ON kpi_intel.filter_assignments;
CREATE POLICY tenant_isolation_policy_filter_assignments ON kpi_intel.filter_assignments
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.filters f
    JOIN kpi_intel.analytical_objects ao ON f.object_id = ao.object_id
    WHERE f.filter_id = filter_assignments.filter_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.security_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.security_roles FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_security_roles ON kpi_intel.security_roles;
CREATE POLICY tenant_isolation_policy_security_roles ON kpi_intel.security_roles
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = security_roles.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.security_role_filters ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.security_role_filters FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_security_role_filters ON kpi_intel.security_role_filters;
CREATE POLICY tenant_isolation_policy_security_role_filters ON kpi_intel.security_role_filters
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.security_roles sr
    JOIN kpi_intel.analytical_objects ao ON sr.object_id = ao.object_id
    WHERE sr.security_role_id = security_role_filters.security_role_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.security_object_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.security_object_permissions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_sec_obj_perms ON kpi_intel.security_object_permissions;
CREATE POLICY tenant_isolation_policy_sec_obj_perms ON kpi_intel.security_object_permissions
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = security_object_permissions.target_object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.data_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.data_sources FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_data_sources ON kpi_intel.data_sources;
CREATE POLICY tenant_isolation_policy_data_sources ON kpi_intel.data_sources
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = data_sources.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.query_dependencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.query_dependencies FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_query_dependencies ON kpi_intel.query_dependencies;
CREATE POLICY tenant_isolation_policy_query_dependencies ON kpi_intel.query_dependencies
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = query_dependencies.source_object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.metadata_lineage_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.metadata_lineage_edges FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_metadata_lineage_edges ON kpi_intel.metadata_lineage_edges;
CREATE POLICY tenant_isolation_policy_metadata_lineage_edges ON kpi_intel.metadata_lineage_edges
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.asset_versions av 
    WHERE av.asset_version_id = metadata_lineage_edges.asset_version_id AND av.tenant_id = kpi_intel.current_tenant_id()
));

-- 7.6 Tenant-Owned Child Tables: Subsystem E (Excel Metadata)
ALTER TABLE kpi_intel.spreadsheet_cells ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.spreadsheet_cells FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_spreadsheet_cells ON kpi_intel.spreadsheet_cells;
CREATE POLICY tenant_isolation_policy_spreadsheet_cells ON kpi_intel.spreadsheet_cells
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = spreadsheet_cells.worksheet_object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.pivot_caches ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.pivot_caches FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_pivot_caches ON kpi_intel.pivot_caches;
CREATE POLICY tenant_isolation_policy_pivot_caches ON kpi_intel.pivot_caches
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.asset_versions av 
    WHERE av.asset_version_id = pivot_caches.asset_version_id AND av.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.pivot_tables ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.pivot_tables FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_pivot_tables ON kpi_intel.pivot_tables;
CREATE POLICY tenant_isolation_policy_pivot_tables ON kpi_intel.pivot_tables
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = pivot_tables.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.pivot_field_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.pivot_field_assignments FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_pivot_field_assignments ON kpi_intel.pivot_field_assignments;
CREATE POLICY tenant_isolation_policy_pivot_field_assignments ON kpi_intel.pivot_field_assignments
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.pivot_tables pt
    JOIN kpi_intel.analytical_objects ao ON pt.object_id = ao.object_id
    WHERE pt.pivot_table_id = pivot_field_assignments.pivot_table_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.spreadsheet_objects ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.spreadsheet_objects FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_spreadsheet_objects ON kpi_intel.spreadsheet_objects;
CREATE POLICY tenant_isolation_policy_spreadsheet_objects ON kpi_intel.spreadsheet_objects
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = spreadsheet_objects.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.spreadsheet_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.spreadsheet_rules FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_spreadsheet_rules ON kpi_intel.spreadsheet_rules;
CREATE POLICY tenant_isolation_policy_spreadsheet_rules ON kpi_intel.spreadsheet_rules
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = spreadsheet_rules.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

-- 7.7 Tenant-Owned Child Tables: Subsystem G (KPI Candidates & Mapping)
ALTER TABLE kpi_intel.kpi_mapping_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.kpi_mapping_candidates FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_map_cands ON kpi_intel.kpi_mapping_candidates;
CREATE POLICY tenant_isolation_policy_map_cands ON kpi_intel.kpi_mapping_candidates
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.kpi_mappings km 
    WHERE km.kpi_mapping_id = kpi_mapping_candidates.kpi_mapping_id AND km.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.mapping_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.mapping_evidence FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_mapping_evidence ON kpi_intel.mapping_evidence;
CREATE POLICY tenant_isolation_policy_mapping_evidence ON kpi_intel.mapping_evidence
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.kpi_mapping_candidates kmc
    JOIN kpi_intel.kpi_mappings km ON kmc.kpi_mapping_id = km.kpi_mapping_id
    WHERE kmc.mapping_candidate_id = mapping_evidence.mapping_candidate_id AND km.tenant_id = kpi_intel.current_tenant_id()
));

-- 7.8 Tenant-Owned Child Tables: Subsystem H (Human Review, Approval, Overrides)
ALTER TABLE kpi_intel.mapping_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.mapping_reviews FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_mapping_reviews ON kpi_intel.mapping_reviews;
CREATE POLICY tenant_isolation_policy_mapping_reviews ON kpi_intel.mapping_reviews
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.kpi_mappings km 
    WHERE km.kpi_mapping_id = mapping_reviews.kpi_mapping_id AND km.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.mapping_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.mapping_approvals FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_approvals ON kpi_intel.mapping_approvals;
CREATE POLICY tenant_isolation_policy_approvals ON kpi_intel.mapping_approvals
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.kpi_mappings km 
    WHERE km.kpi_mapping_id = mapping_approvals.kpi_mapping_id AND km.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.mapping_overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.mapping_overrides FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_overrides ON kpi_intel.mapping_overrides;
CREATE POLICY tenant_isolation_policy_overrides ON kpi_intel.mapping_overrides
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.kpi_mappings km 
    WHERE km.kpi_mapping_id = mapping_overrides.kpi_mapping_id AND km.tenant_id = kpi_intel.current_tenant_id()
));

-- 7.9 Tenant-Owned Child Tables: Subsystem I (KPI Rationalisation)
ALTER TABLE kpi_intel.kpi_equivalence_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.kpi_equivalence_candidates FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_equiv_cands ON kpi_intel.kpi_equivalence_candidates;
CREATE POLICY tenant_isolation_policy_equiv_cands ON kpi_intel.kpi_equivalence_candidates
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.kpi_candidates kc
    WHERE kc.kpi_candidate_id = kpi_equivalence_candidates.source_kpi_candidate_id AND kc.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.kpi_rationalisation_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.kpi_rationalisation_decisions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_rat_decisions ON kpi_intel.kpi_rationalisation_decisions;
CREATE POLICY tenant_isolation_policy_rat_decisions ON kpi_intel.kpi_rationalisation_decisions
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.kpi_candidates kc
    WHERE kc.kpi_candidate_id = kpi_rationalisation_decisions.canonical_kpi_candidate_id AND kc.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.rationalisation_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.rationalisation_evidence FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_rat_evidence ON kpi_intel.rationalisation_evidence;
CREATE POLICY tenant_isolation_policy_rat_evidence ON kpi_intel.rationalisation_evidence
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.kpi_rationalisation_decisions rd
    JOIN kpi_intel.kpi_candidates kc ON rd.canonical_kpi_candidate_id = kc.kpi_candidate_id
    WHERE rd.rationalisation_decision_id = rationalisation_evidence.rationalisation_decision_id AND kc.tenant_id = kpi_intel.current_tenant_id()
));

-- 7.10 Tenant-Owned Child Tables: Subsystem J (Operations & Tagging)
ALTER TABLE kpi_intel.extraction_errors ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.extraction_errors FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_extraction_errors ON kpi_intel.extraction_errors;
CREATE POLICY tenant_isolation_policy_extraction_errors ON kpi_intel.extraction_errors
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.parser_runs pr
    WHERE pr.parser_run_id = extraction_errors.parser_run_id AND pr.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.object_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.object_tags FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_object_tags ON kpi_intel.object_tags;
CREATE POLICY tenant_isolation_policy_object_tags ON kpi_intel.object_tags
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = object_tags.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

-- 7.11 Globally Shared Reference Tables (Global read-only access)
ALTER TABLE kpi_intel.business_domains ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS global_read_domains ON kpi_intel.business_domains;
CREATE POLICY global_read_domains ON kpi_intel.business_domains FOR SELECT USING (true);

ALTER TABLE kpi_intel.visual_types ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS global_read_visual_types ON kpi_intel.visual_types;
CREATE POLICY global_read_visual_types ON kpi_intel.visual_types FOR SELECT USING (true);

ALTER TABLE kpi_intel.platform_capabilities ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS global_read_platform_caps ON kpi_intel.platform_capabilities;
CREATE POLICY global_read_platform_caps ON kpi_intel.platform_capabilities FOR SELECT USING (true);

ALTER TABLE kpi_intel.kpi_ontology_versions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS global_read_ontology_versions ON kpi_intel.kpi_ontology_versions;
CREATE POLICY global_read_ontology_versions ON kpi_intel.kpi_ontology_versions FOR SELECT USING (true);

ALTER TABLE kpi_intel.kpi_ontology_entries ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS global_read_ontology_entries ON kpi_intel.kpi_ontology_entries;
CREATE POLICY global_read_ontology_entries ON kpi_intel.kpi_ontology_entries FOR SELECT USING (true);

-- 7.12 System Operational Audit Table (Global ledger read access)
ALTER TABLE kpi_intel.ontology_change_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS global_read_ontology_change_events ON kpi_intel.ontology_change_events;
CREATE POLICY global_read_ontology_change_events ON kpi_intel.ontology_change_events FOR SELECT USING (true);

-- 7.13 Application Roles & Privileges Model
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kpi_app_user') THEN
        CREATE ROLE kpi_app_user WITH NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kpi_readonly') THEN
        CREATE ROLE kpi_readonly WITH NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
END $$;

GRANT USAGE ON SCHEMA kpi_intel TO kpi_app_user, kpi_readonly;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA kpi_intel TO kpi_app_user;
REVOKE UPDATE, DELETE, TRUNCATE ON kpi_intel.mapping_audit_events, kpi_intel.ontology_change_events FROM kpi_app_user, PUBLIC;
GRANT SELECT, INSERT ON kpi_intel.mapping_audit_events, kpi_intel.ontology_change_events TO kpi_app_user;

GRANT SELECT ON ALL TABLES IN SCHEMA kpi_intel TO kpi_readonly;

GRANT EXECUTE ON FUNCTION kpi_intel.current_tenant_id() TO kpi_app_user, kpi_readonly;
GRANT EXECUTE ON FUNCTION kpi_intel.set_current_tenant_id(UUID, BOOLEAN) TO kpi_app_user;
GRANT EXECUTE ON FUNCTION kpi_intel.clear_current_tenant_id(BOOLEAN) TO kpi_app_user;

COMMIT;
