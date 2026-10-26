-- ============================================================================
-- KPI INTELLIGENCE PLATFORM — MIGRATION V002
-- Migration: V002__canonical_model_hardening.sql
-- Description: Hardens canonical schema with:
--              1. Authoritative tenant context & multi-tenant isolation (RLS + composite FKs)
--              2. Immutable audit tables & cascade deletion protection
--              3. Cross-record referential consistency constraints
--              4. Lossless KPI Bank JSON normalization columns in kpi_ontology_entries
--              5. Governance approval protection & override cycle triggers
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

CREATE OR REPLACE FUNCTION kpi_intel.set_current_tenant_id(p_tenant_id UUID)
RETURNS VOID AS $$
BEGIN
    PERFORM set_config('kpi_intel.current_tenant_id', p_tenant_id::TEXT, false);
END;
$$ LANGUAGE plpgsql;

-- ----------------------------------------------------------------------------
-- 2. TENANT OWNERSHIP COLUMN BACKFILLS & COMPOSITE CONSTRAINTS
-- ----------------------------------------------------------------------------

-- Add composite unique on assets for cross-tenant FK reference
ALTER TABLE kpi_intel.assets
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
ADD CONSTRAINT uq_kpi_ontology_entries_version UNIQUE (ontology_entry_id, ontology_version_id);

-- Composite FK for selected_ontology_entry_id in kpi_mappings
ALTER TABLE kpi_intel.kpi_mappings
DROP CONSTRAINT IF EXISTS fk_kpi_mappings_selected_ontology_entry,
ADD CONSTRAINT fk_kpi_mappings_selected_ontology_entry
FOREIGN KEY (selected_ontology_entry_id, ontology_version_id)
REFERENCES kpi_intel.kpi_ontology_entries(ontology_entry_id, ontology_version_id)
ON DELETE SET NULL;

-- ----------------------------------------------------------------------------
-- 4. CANDIDATE, APPROVAL, REVIEW, OVERRIDE CONSISTENCY
-- ----------------------------------------------------------------------------
ALTER TABLE kpi_intel.kpi_mapping_candidates
ADD CONSTRAINT uq_kpi_mapping_candidates_mapping UNIQUE (mapping_candidate_id, kpi_mapping_id);

-- Enforce approval belongs to the mapping being approved
ALTER TABLE kpi_intel.mapping_approvals
DROP CONSTRAINT IF EXISTS fk_mapping_approvals_candidate_mapping,
ADD CONSTRAINT fk_mapping_approvals_candidate_mapping
FOREIGN KEY (approved_mapping_candidate_id, kpi_mapping_id)
REFERENCES kpi_intel.kpi_mapping_candidates(mapping_candidate_id, kpi_mapping_id)
ON DELETE SET NULL;

-- Enforce review belongs to the mapping being reviewed
ALTER TABLE kpi_intel.mapping_reviews
DROP CONSTRAINT IF EXISTS fk_mapping_reviews_candidate_mapping,
ADD CONSTRAINT fk_mapping_reviews_candidate_mapping
FOREIGN KEY (mapping_candidate_id, kpi_mapping_id)
REFERENCES kpi_intel.kpi_mapping_candidates(mapping_candidate_id, kpi_mapping_id)
ON DELETE SET NULL;

-- Enforce override candidate belongs to the mapping being overridden
ALTER TABLE kpi_intel.mapping_overrides
DROP CONSTRAINT IF EXISTS fk_mapping_overrides_candidate_mapping,
ADD CONSTRAINT fk_mapping_overrides_candidate_mapping
FOREIGN KEY (mapping_candidate_id, kpi_mapping_id)
REFERENCES kpi_intel.kpi_mapping_candidates(mapping_candidate_id, kpi_mapping_id)
ON DELETE SET NULL;

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
        USING ERRCODE = '23505';
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

-- Protect human approvals from automated overwrites
CREATE OR REPLACE FUNCTION kpi_intel.protect_human_approval()
RETURNS TRIGGER AS $$
BEGIN
    IF (OLD.mapping_status = 'APPROVED' OR OLD.decision_source = 'HUMAN')
       AND NEW.decision_source IN ('LLM', 'DETERMINISTIC') THEN
        RAISE EXCEPTION 'Automated mapping runs cannot overwrite human-approved or human-decided mappings (kpi_mapping_id: %)', OLD.kpi_mapping_id
            USING ERRCODE = '23514';
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
-- 7. ROW-LEVEL SECURITY POLICIES FOR TENANT ISOLATION
-- ----------------------------------------------------------------------------

-- Enable RLS on all tenant-owned root tables
ALTER TABLE kpi_intel.assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.security_principals ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.asset_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.analytical_objects ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.kpi_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.kpi_mapping_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.kpi_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.domain_classifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.metadata_field_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.parser_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_intel.mapping_audit_events ENABLE ROW LEVEL SECURITY;

-- Root table tenant policies
DROP POLICY IF EXISTS tenant_isolation_policy_assets ON kpi_intel.assets;
CREATE POLICY tenant_isolation_policy_assets ON kpi_intel.assets
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation_policy_principals ON kpi_intel.security_principals;
CREATE POLICY tenant_isolation_policy_principals ON kpi_intel.security_principals
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation_policy_versions ON kpi_intel.asset_versions;
CREATE POLICY tenant_isolation_policy_versions ON kpi_intel.asset_versions
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation_policy_objects ON kpi_intel.analytical_objects;
CREATE POLICY tenant_isolation_policy_objects ON kpi_intel.analytical_objects
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation_policy_candidates ON kpi_intel.kpi_candidates;
CREATE POLICY tenant_isolation_policy_candidates ON kpi_intel.kpi_candidates
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation_policy_mapping_runs ON kpi_intel.kpi_mapping_runs;
CREATE POLICY tenant_isolation_policy_mapping_runs ON kpi_intel.kpi_mapping_runs
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation_policy_mappings ON kpi_intel.kpi_mappings;
CREATE POLICY tenant_isolation_policy_mappings ON kpi_intel.kpi_mappings
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation_policy_domain_class ON kpi_intel.domain_classifications;
CREATE POLICY tenant_isolation_policy_domain_class ON kpi_intel.domain_classifications
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation_policy_field_reviews ON kpi_intel.metadata_field_reviews;
CREATE POLICY tenant_isolation_policy_field_reviews ON kpi_intel.metadata_field_reviews
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation_policy_parser_runs ON kpi_intel.parser_runs;
CREATE POLICY tenant_isolation_policy_parser_runs ON kpi_intel.parser_runs
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation_policy_audit_events ON kpi_intel.mapping_audit_events;
CREATE POLICY tenant_isolation_policy_audit_events ON kpi_intel.mapping_audit_events
FOR ALL USING (tenant_id = kpi_intel.current_tenant_id());

-- Enable RLS on child tables to prevent direct bypass queries
ALTER TABLE kpi_intel.reports ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_reports ON kpi_intel.reports;
CREATE POLICY tenant_isolation_policy_reports ON kpi_intel.reports
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = reports.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.calculations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_calculations ON kpi_intel.calculations;
CREATE POLICY tenant_isolation_policy_calculations ON kpi_intel.calculations
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = calculations.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.data_tables ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_data_tables ON kpi_intel.data_tables;
CREATE POLICY tenant_isolation_policy_data_tables ON kpi_intel.data_tables
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.analytical_objects ao 
    WHERE ao.object_id = data_tables.object_id AND ao.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.kpi_mapping_candidates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_map_cands ON kpi_intel.kpi_mapping_candidates;
CREATE POLICY tenant_isolation_policy_map_cands ON kpi_intel.kpi_mapping_candidates
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.kpi_mappings km 
    WHERE km.kpi_mapping_id = kpi_mapping_candidates.kpi_mapping_id AND km.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.mapping_approvals ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_approvals ON kpi_intel.mapping_approvals;
CREATE POLICY tenant_isolation_policy_approvals ON kpi_intel.mapping_approvals
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.kpi_mappings km 
    WHERE km.kpi_mapping_id = mapping_approvals.kpi_mapping_id AND km.tenant_id = kpi_intel.current_tenant_id()
));

ALTER TABLE kpi_intel.mapping_overrides ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy_overrides ON kpi_intel.mapping_overrides;
CREATE POLICY tenant_isolation_policy_overrides ON kpi_intel.mapping_overrides
FOR ALL USING (EXISTS (
    SELECT 1 FROM kpi_intel.kpi_mappings km 
    WHERE km.kpi_mapping_id = mapping_overrides.kpi_mapping_id AND km.tenant_id = kpi_intel.current_tenant_id()
));

-- Global reference tables have public/authenticated read-only policy
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

COMMIT;
