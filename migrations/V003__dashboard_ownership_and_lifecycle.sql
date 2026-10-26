-- ============================================================================
-- KPI INTELLIGENCE PLATFORM — MIGRATION V003
-- Migration: V003__dashboard_ownership_and_lifecycle.sql
-- Description: Extends canonical dashboard/report entity (kpi_intel.reports) with:
--              1. Dashboard ownership metadata (owner_id referencing security_principals, owner_name)
--              2. Last verified access timestamp (last_accessed_at)
--              3. Canonical lifecycle status (lifecycle_status: ACTIVE, DORMANT, ORPHANED, UNCLASSIFIED)
--              4. Calendar-arithmetic classification function (classify_report_lifecycle)
--              5. Automatic synchronization trigger (trg_reports_lifecycle_status)
--              6. Batch refresh procedure (refresh_report_lifecycle_status)
--              7. Downstream dashboard view (v_dashboard_lifecycle) with inherited RLS
--
-- EXECUTION & IDEMPOTENCE CONTRACT:
-- - Standalone rerunnability via IF NOT EXISTS, CREATE OR REPLACE, DROP CONSTRAINT IF EXISTS
-- - Zero data loss: Preserves all existing records, identifiers, and tenant isolation policies
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

SET search_path = kpi_intel, public;

-- ----------------------------------------------------------------------------
-- 1. EXTEND kpi_intel.reports WITH OWNERSHIP AND ACCESS ATTRIBUTES
-- ----------------------------------------------------------------------------

-- Add owner_id referencing security_principals
ALTER TABLE kpi_intel.reports
ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES kpi_intel.security_principals(principal_id) ON DELETE SET NULL;

-- Add owner display name
ALTER TABLE kpi_intel.reports
ADD COLUMN IF NOT EXISTS owner_name TEXT;

-- Add last_accessed_at timestamp
ALTER TABLE kpi_intel.reports
ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ;

-- Add lifecycle_status with default 'ORPHANED'
ALTER TABLE kpi_intel.reports
ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'ORPHANED';

-- Add check constraint for lifecycle status
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'ck_reports_lifecycle_status' 
          AND conrelid = 'kpi_intel.reports'::regclass
    ) THEN
        ALTER TABLE kpi_intel.reports
        ADD CONSTRAINT ck_reports_lifecycle_status
        CHECK (lifecycle_status IN ('ACTIVE', 'DORMANT', 'ORPHANED', 'UNCLASSIFIED'));
    END IF;
END $$;

-- ----------------------------------------------------------------------------
-- 2. INDEXES SUPPORTING DASHBOARD FILTERING AND GROUPING
-- ----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_reports_lifecycle_status
ON kpi_intel.reports (lifecycle_status);

CREATE INDEX IF NOT EXISTS idx_reports_owner_id
ON kpi_intel.reports (owner_id)
WHERE owner_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_reports_last_accessed_at
ON kpi_intel.reports (last_accessed_at)
WHERE last_accessed_at IS NOT NULL;

-- ----------------------------------------------------------------------------
-- 3. CANONICAL CLASSIFICATION FUNCTION
-- ----------------------------------------------------------------------------
-- Precedence:
-- 1. ORPHANED: owner_id IS NULL
-- 2. UNCLASSIFIED: owner_id IS NOT NULL AND last_accessed_at IS NULL
-- 3. DORMANT: owner_id IS NOT NULL AND last_accessed_at <= (p_classification_timestamp - INTERVAL '6 months')
-- 4. ACTIVE: owner_id IS NOT NULL AND last_accessed_at > (p_classification_timestamp - INTERVAL '6 months')
-- Uses native PostgreSQL calendar arithmetic (INTERVAL '6 months') rather than fixed 180-day approximations.

CREATE OR REPLACE FUNCTION kpi_intel.classify_report_lifecycle(
    p_owner_id UUID,
    p_last_accessed_at TIMESTAMPTZ,
    p_classification_timestamp TIMESTAMPTZ DEFAULT clock_timestamp()
)
RETURNS TEXT AS $$
BEGIN
    IF p_owner_id IS NULL THEN
        RETURN 'ORPHANED';
    ELSIF p_last_accessed_at IS NULL THEN
        RETURN 'UNCLASSIFIED';
    ELSIF p_last_accessed_at <= (p_classification_timestamp - INTERVAL '6 months') THEN
        RETURN 'DORMANT';
    ELSE
        RETURN 'ACTIVE';
    END IF;
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE SECURITY INVOKER SET search_path = pg_catalog, kpi_intel;

COMMENT ON FUNCTION kpi_intel.classify_report_lifecycle(UUID, TIMESTAMPTZ, TIMESTAMPTZ)
IS 'Derives canonical dashboard lifecycle status (ACTIVE, DORMANT, ORPHANED, UNCLASSIFIED) using PostgreSQL calendar arithmetic.';

-- ----------------------------------------------------------------------------
-- 4. SYNCHRONIZATION TRIGGER FUNCTION AND TRIGGER
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION kpi_intel.sync_report_lifecycle_status()
RETURNS TRIGGER AS $$
BEGIN
    -- Synchronize lifecycle_status based on owner_id and last_accessed_at
    -- If caller did not provide an explicit lifecycle_status or updated owner/access attributes:
    IF NEW.lifecycle_status IS NULL OR TG_OP = 'INSERT' OR 
       (OLD.owner_id IS DISTINCT FROM NEW.owner_id) OR 
       (OLD.last_accessed_at IS DISTINCT FROM NEW.last_accessed_at) THEN
        NEW.lifecycle_status := kpi_intel.classify_report_lifecycle(
            NEW.owner_id,
            NEW.last_accessed_at,
            clock_timestamp()
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, kpi_intel;

DROP TRIGGER IF EXISTS trg_reports_lifecycle_status ON kpi_intel.reports;
CREATE TRIGGER trg_reports_lifecycle_status
BEFORE INSERT OR UPDATE ON kpi_intel.reports
FOR EACH ROW EXECUTE FUNCTION kpi_intel.sync_report_lifecycle_status();

-- ----------------------------------------------------------------------------
-- 5. BATCH REFRESH PROCEDURE FOR TEMPORAL RECLASSIFICATION
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION kpi_intel.refresh_report_lifecycle_status(
    p_as_of TIMESTAMPTZ DEFAULT clock_timestamp()
)
RETURNS INTEGER AS $$
DECLARE
    v_updated_count INTEGER := 0;
BEGIN
    -- Reclassifies reports where time advancement alters active/dormant status
    UPDATE kpi_intel.reports r
    SET lifecycle_status = kpi_intel.classify_report_lifecycle(r.owner_id, r.last_accessed_at, p_as_of)
    WHERE r.lifecycle_status IS DISTINCT FROM kpi_intel.classify_report_lifecycle(r.owner_id, r.last_accessed_at, p_as_of);

    GET DIAGNOSTICS v_updated_count = ROW_COUNT;
    RETURN v_updated_count;
END;
$$ LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, kpi_intel;

COMMENT ON FUNCTION kpi_intel.refresh_report_lifecycle_status(TIMESTAMPTZ)
IS 'Batch refreshes stored lifecycle_status on kpi_intel.reports as time advances.';

-- ----------------------------------------------------------------------------
-- 6. CANONICAL DOWNSTREAM DASHBOARD VIEW (WITH ROW-LEVEL SECURITY)
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW kpi_intel.v_dashboard_lifecycle AS
SELECT
    r.report_id,
    r.object_id,
    ao.asset_version_id,
    ao.tenant_id,
    av.asset_id,
    a.asset_name,
    ao.canonical_name AS report_name,
    ao.display_name AS report_display_name,
    ao.platform,
    r.report_type,
    r.owner_id,
    COALESCE(r.owner_name, sp.principal_name) AS owner_name,
    r.last_accessed_at,
    clock_timestamp() AS classification_timestamp,
    kpi_intel.classify_report_lifecycle(r.owner_id, r.last_accessed_at, clock_timestamp()) AS lifecycle_status,
    r.page_count,
    r.visual_count,
    r.created_at
FROM kpi_intel.reports r
JOIN kpi_intel.analytical_objects ao ON ao.object_id = r.object_id
JOIN kpi_intel.asset_versions av ON av.asset_version_id = ao.asset_version_id
JOIN kpi_intel.assets a ON a.asset_id = av.asset_id
LEFT JOIN kpi_intel.security_principals sp ON sp.principal_id = r.owner_id;

COMMENT ON VIEW kpi_intel.v_dashboard_lifecycle
IS 'Dashboard-facing view exposing reports with owner, last access, classification timestamp, and lifecycle status under active tenant isolation.';

-- ----------------------------------------------------------------------------
-- 7. ROLE PERMISSIONS
-- ----------------------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kpi_app_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON kpi_intel.reports TO kpi_app_user;
        GRANT SELECT ON kpi_intel.v_dashboard_lifecycle TO kpi_app_user;
        GRANT EXECUTE ON FUNCTION kpi_intel.classify_report_lifecycle(UUID, TIMESTAMPTZ, TIMESTAMPTZ) TO kpi_app_user;
        GRANT EXECUTE ON FUNCTION kpi_intel.refresh_report_lifecycle_status(TIMESTAMPTZ) TO kpi_app_user;
    END IF;
END $$;

-- ----------------------------------------------------------------------------
-- 8. INITIAL BACKFILL OF EXISTING RECORDS
-- ----------------------------------------------------------------------------
UPDATE kpi_intel.reports
SET lifecycle_status = kpi_intel.classify_report_lifecycle(owner_id, last_accessed_at, clock_timestamp())
WHERE lifecycle_status IS NULL OR lifecycle_status = 'ORPHANED';

COMMIT;

/*
--------------------------------------------------------------------------------
ROLLBACK INSTRUCTIONS (V003 Undo Script)
--------------------------------------------------------------------------------
To revert migration V003:

BEGIN;

DROP VIEW IF EXISTS kpi_intel.v_dashboard_lifecycle;
DROP TRIGGER IF EXISTS trg_reports_lifecycle_status ON kpi_intel.reports;
DROP FUNCTION IF EXISTS kpi_intel.sync_report_lifecycle_status();
DROP FUNCTION IF EXISTS kpi_intel.refresh_report_lifecycle_status(TIMESTAMPTZ);
DROP FUNCTION IF EXISTS kpi_intel.classify_report_lifecycle(UUID, TIMESTAMPTZ, TIMESTAMPTZ);

DROP INDEX IF EXISTS kpi_intel.idx_reports_last_accessed_at;
DROP INDEX IF EXISTS kpi_intel.idx_reports_owner_id;
DROP INDEX IF EXISTS kpi_intel.idx_reports_lifecycle_status;

ALTER TABLE kpi_intel.reports DROP CONSTRAINT IF EXISTS ck_reports_lifecycle_status;
ALTER TABLE kpi_intel.reports DROP CONSTRAINT IF EXISTS fk_reports_owner;

ALTER TABLE kpi_intel.reports DROP COLUMN IF EXISTS lifecycle_status;
ALTER TABLE kpi_intel.reports DROP COLUMN IF EXISTS last_accessed_at;
ALTER TABLE kpi_intel.reports DROP COLUMN IF EXISTS owner_name;
ALTER TABLE kpi_intel.reports DROP COLUMN IF EXISTS owner_id;

COMMIT;
--------------------------------------------------------------------------------
*/

