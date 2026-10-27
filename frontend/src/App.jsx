import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { api } from './api/client';

const TENANTS = [
  { id: '11111111-1111-1111-1111-111111111111', name: 'Tenant Alpha (Insurance)' },
  { id: '22222222-2222-2222-2222-222222222222', name: 'Tenant Beta (Underwriting)' },
];

const VIEWS = [
  { id: 'overview', label: 'Workspace Overview', icon: '📊', section: 'WORKFLOW' },
  { id: 'metadata', label: 'Ingestion & Metadata', icon: '🗂️', section: 'WORKFLOW' },
  { id: 'domains', label: 'Domain Segregation', icon: '🛡️', section: 'WORKFLOW' },
  { id: 'mapping', label: 'KPI Candidate Mapping', icon: '🎯', section: 'WORKFLOW' },
  { id: 'review', label: 'Human Review', icon: '⚖️', section: 'WORKFLOW', hasBadge: true },
  { id: 'kpibank', label: 'KPI Bank', icon: '🏛️', section: 'CATALOGUE & AUDIT' },
  { id: 'overrides', label: 'Overrides & Learning', icon: '🔄', section: 'CATALOGUE & AUDIT' },
  { id: 'audit', label: 'Audit History', icon: '📜', section: 'CATALOGUE & AUDIT' },
];

export default function App() {
  const [activeView, setActiveView] = useState('overview');
  const [tenantId, setTenantId] = useState(TENANTS[0].id);
  const [theme, setTheme] = useState('light');
  const [loading, setLoading] = useState(false);
  const [toasts, setToasts] = useState([]);

  // Operational State
  const [summary, setSummary] = useState(null);
  const [llmStatus, setLlmStatus] = useState(null);
  const [domains, setDomains] = useState([]);
  const [metadataFields, setMetadataFields] = useState([]);
  const [proposals, setProposals] = useState([]);
  const [kpiBankEntries, setKpiBankEntries] = useState([]);
  const [overrides, setOverrides] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [ingestedSources, setIngestedSources] = useState([]);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Modals & Drawer State
  const [selectedCandidateData, setSelectedCandidateData] = useState(null);
  const [drawerMode, setDrawerMode] = useState('technical'); // 'technical' | 'analyst'
  const [chooseKpiModal, setChooseKpiModal] = useState({ open: false, mappingId: null, fieldName: null, candidates: [] });
  const [addKpiModal, setAddKpiModal] = useState({ open: false, mappingId: null, defaultDomain: 'CLAIMS_RISK' });
  const [ingestModalOpen, setIngestModalOpen] = useState(false);

  // Filters
  const [metadataDomainFilter, setMetadataDomainFilter] = useState('');
  const [kpiBankSearchQuery, setKpiBankSearchQuery] = useState('');
  const [kpiBankDomainFilter, setKpiBankDomainFilter] = useState('');

  const addToast = (type, message) => {
    const id = Date.now() + Math.random();
    setToasts(prev => [...prev, { id, type, message }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 4000);
  };

  // ---------------------------------------------------------------------------
  // DATA FETCHING
  // ---------------------------------------------------------------------------

  const refreshAllData = useCallback(async (currentTenant = tenantId) => {
    setLoading(true);
    try {
      const [sumRes, domRes, fieldsRes, kpiRes, ovrRes, audRes, sourcesRes] = await Promise.allSettled([
        api.getWorkspaceSummary(currentTenant),
        api.getDomains(),
        api.getMetadataFields({}, currentTenant),
        api.searchKPIBank(),
        api.getOverrides(currentTenant),
        api.getAuditHistory(50, currentTenant),
        api.getIngestedSources(currentTenant),
      ]);

      if (sumRes.status === 'fulfilled' && sumRes.value.success) {
        setSummary(sumRes.value.data);
        if (sumRes.value.data.llm_status) {
          setLlmStatus(sumRes.value.data.llm_status);
        }
      }
      if (domRes.status === 'fulfilled' && domRes.value.success) {
        setDomains(domRes.value.data);
      }
      if (fieldsRes.status === 'fulfilled' && fieldsRes.value.success) {
        setMetadataFields(fieldsRes.value.data);
        const pending = fieldsRes.value.data.filter(f => f.mapping_status === 'PROPOSED');
        setProposals(pending);
      }
      if (kpiRes.status === 'fulfilled' && kpiRes.value.success) {
        setKpiBankEntries(kpiRes.value.data);
      }
      if (ovrRes.status === 'fulfilled' && ovrRes.value.success) {
        setOverrides(ovrRes.value.data);
      }
      if (audRes.status === 'fulfilled' && audRes.value.success) {
        setAuditLogs(audRes.value.data);
      }
      if (sourcesRes.status === 'fulfilled' && sourcesRes.value.success) {
        setIngestedSources(sourcesRes.value.data || []);
      }
    } catch (err) {
      addToast('error', `Failed to load workspace data: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    refreshAllData(tenantId);
  }, [tenantId, refreshAllData]);

  // Apply theme class
  useEffect(() => {
    document.body.className = `theme-${theme}`;
  }, [theme]);

  // ---------------------------------------------------------------------------
  // GOVERNANCE ACTIONS
  // ---------------------------------------------------------------------------

  const handleRunMapping = async (forceFallback = false) => {
    if (!metadataFields || metadataFields.length === 0) {
      addToast('warning', 'No canonical metadata fields found. Please ingest a Power BI project (.pbip) first.');
      setIngestModalOpen(true);
      return;
    }
    setLoading(true);
    try {
      const res = await api.runMappingPipeline({ forceFallback }, tenantId);
      if (res.success) {
        addToast('success', `Pipeline completed: ${res.data.total_fields_processed} fields mapped, ${res.data.auto_reused_from_learning} reused.`);
        await refreshAllData();
      }
    } catch (err) {
      addToast('error', `Mapping run failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async (mappingId, kpiId) => {
    try {
      const res = await api.approveMapping(mappingId, kpiId, tenantId);
      if (res.success) {
        addToast('success', `Candidate approved and locked into canonical model.`);
        await refreshAllData();
      }
    } catch (err) {
      addToast('error', `Approval failed: ${err.message}`);
    }
  };

  const handleReject = async (mappingId) => {
    const reason = window.prompt('Please enter the rejection reason:');
    if (!reason) return;
    try {
      const res = await api.rejectMapping(mappingId, reason, tenantId);
      if (res.success) {
        addToast('warning', `Mapping rejected and recorded in audit log.`);
        await refreshAllData();
      }
    } catch (err) {
      addToast('error', `Rejection failed: ${err.message}`);
    }
  };

  const handleInspectCandidates = async (fieldId) => {
    try {
      const res = await api.getFieldCandidates(fieldId, tenantId);
      if (res.success) {
        setSelectedCandidateData(res.data);
      }
    } catch (err) {
      addToast('error', `Failed to retrieve candidates: ${err.message}`);
    }
  };

  const handleDomainCorrection = async (fieldId, newDomain) => {
    const justification = window.prompt(`Correct domain to ${newDomain}. Enter justification:`);
    if (!justification) return;
    try {
      const res = await api.updateFieldDomain(fieldId, newDomain, justification, tenantId);
      if (res.success) {
        addToast('success', `Domain corrected to ${newDomain}. Audit event generated.`);
        await refreshAllData();
      }
    } catch (err) {
      addToast('error', `Domain correction failed: ${err.message}`);
    }
  };

  const handleInvalidateOverride = async (overrideId) => {
    if (!window.confirm('Are you sure you want to invalidate this learned override? Future mapping runs will re-evaluate candidate rankings.')) return;
    try {
      const res = await api.invalidateOverride(overrideId, 'Analyst manual override invalidation', tenantId);
      if (res.success) {
        addToast('warning', `Override rule invalidated.`);
        await refreshAllData();
      }
    } catch (err) {
      addToast('error', `Failed to invalidate override: ${err.message}`);
    }
  };

  // ---------------------------------------------------------------------------
  // FILTERED LISTS
  // ---------------------------------------------------------------------------

  const filteredMetadataFields = useMemo(() => {
    return metadataFields.filter(f => {
      if (metadataDomainFilter && f.domain !== metadataDomainFilter) return false;
      return true;
    });
  }, [metadataFields, metadataDomainFilter]);

  const filteredKpiBank = useMemo(() => {
    return kpiBankEntries.filter(k => {
      if (kpiBankDomainFilter && k.domain !== kpiBankDomainFilter) return false;
      if (kpiBankSearchQuery) {
        const q = kpiBankSearchQuery.toLowerCase();
        const matchesName = k.name?.toLowerCase().includes(q);
        const matchesDef = k.definition?.toLowerCase().includes(q);
        const matchesAlias = k.aliases?.some(a => a.toLowerCase().includes(q));
        if (!matchesName && !matchesDef && !matchesAlias) return false;
      }
      return true;
    });
  }, [kpiBankEntries, kpiBankDomainFilter, kpiBankSearchQuery]);

  // Pending count for sidebar badge
  const pendingReviewCount = proposals.length;

  return (
    <div id="app" className="app-container">
      {/* MOBILE BACKDROP */}
      {mobileMenuOpen && (
        <div
          className="sidebar-backdrop"
          onClick={() => setMobileMenuOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* PERSISTENT LEFT NAVIGATION SIDEBAR */}
      <aside className={`sidebar ${mobileMenuOpen ? 'mobile-open' : ''}`}>
        <div className="sidebar-header">
          <div className="app-brand">
            <div className="app-logo">KPI</div>
            <div className="app-title-group">
              <span className="app-title">KPI Intelligence</span>
              <span className="app-subtitle">FastAPI + React</span>
            </div>
          </div>
        </div>

        <nav className="sidebar-nav">
          {['WORKFLOW', 'CATALOGUE & AUDIT'].map(section => (
            <React.Fragment key={section}>
              <div className="nav-section-label">{section}</div>
              {VIEWS.filter(v => v.section === section).map(v => (
                <button
                  key={v.id}
                  className={`nav-item ${activeView === v.id ? 'active' : ''}`}
                  onClick={() => {
                    setActiveView(v.id);
                    setMobileMenuOpen(false);
                  }}
                >
                  <span className="nav-icon">{v.icon}</span>
                  <span className="nav-label">{v.label}</span>
                  {v.hasBadge && pendingReviewCount > 0 && (
                    <span className="nav-badge">{pendingReviewCount}</span>
                  )}
                </button>
              ))}
            </React.Fragment>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="tenant-selector">
            <label htmlFor="tenant-select" className="tenant-label">TENANT</label>
            <select
              id="tenant-select"
              className="tenant-dropdown"
              value={tenantId}
              onChange={e => setTenantId(e.target.value)}
            >
              {TENANTS.map(t => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>
          <div className="theme-toggle-row">
            <span className="theme-label">
              {theme === 'light' ? 'Light Appearance' : 'Dark Appearance'}
            </span>
            <button
              className="apple-button secondary small"
              onClick={() => setTheme(prev => prev === 'light' ? 'dark' : 'light')}
              title="Toggle Appearance"
            >
              🌓
            </button>
          </div>
        </div>
      </aside>

      {/* MAIN CONTENT VIEW AREA */}
      <main className="main-content">
        <header className="top-bar">
          <div className="top-bar-left">
            <button
              className="mobile-menu-btn"
              onClick={() => setMobileMenuOpen(prev => !prev)}
              aria-label="Toggle navigation menu"
            >
              ☰
            </button>
            <div className="top-bar-titles">
              <h1 className="page-header-title">
                {VIEWS.find(v => v.id === activeView)?.label || 'Workspace'}
              </h1>
              <span className="page-header-subtitle">
                Canonical model KPI mapping, domain classification, and human governance
              </span>
            </div>
          </div>
          <div className="top-bar-right">
            <div className="system-status-pill">
              <span className={`status-dot ${llmStatus?.llm_configured ? 'green' : 'orange'}`}></span>
              <span>
                {llmStatus?.llm_configured
                  ? `Azure Llama (${llmStatus.llm_deployment_label || 'Configured'})`
                  : 'Deterministic Fallback Active'}
              </span>
            </div>
            <button
              className="apple-button secondary"
              onClick={() => setIngestModalOpen(true)}
              title="Upload PBIP files or select a project folder"
            >
              <span>📥 Ingest Sources</span>
            </button>
            <button
              className="apple-button primary"
              onClick={() => handleRunMapping(false)}
              disabled={loading}
            >
              <span>{loading ? '⏳ Processing...' : '⚡ Run Mapping Pipeline'}</span>
            </button>
          </div>
        </header>

        <div className="view-scrollable">
          {/* VIEW 1: WORKSPACE OVERVIEW */}
          {activeView === 'overview' && (
            <section className="view-panel active">
              {/* Guidance / Ingestion Entry Point */}
              <div className="banner-guidance">
                <div className="banner-text">
                  <h4>Power BI Project Ingestion</h4>
                  <p>Upload a Power BI Project (.pbip) folder or zip archive to extract measures and semantic models into the canonical catalog.</p>
                </div>
                <button
                  className="apple-button primary small"
                  onClick={() => setIngestModalOpen(true)}
                >
                  📥 Ingest Power BI Source
                </button>
              </div>

              <div className="kpi-metrics-grid">
                <div className="metric-card">
                  <div className="metric-header">
                    <span className="metric-title">Canonical Entities</span>
                    <span className="metric-icon">📦</span>
                  </div>
                  <div className="metric-value">{summary?.total_canonical_entities ?? 0}</div>
                  <div className="metric-subtext">Persisted in canonical catalog</div>
                </div>

                <div className="metric-card warning">
                  <div className="metric-header">
                    <span className="metric-title">Human Review Queue</span>
                    <span className="metric-icon">⚖️</span>
                  </div>
                  <div className="metric-value">{summary?.proposals_awaiting_approval ?? 0}</div>
                  <div className="metric-subtext">Requires human approval (HIGH never auto-approves)</div>
                </div>

                <div className="metric-card success">
                  <div className="metric-header">
                    <span className="metric-title">Approved Mappings</span>
                    <span className="metric-icon">✅</span>
                  </div>
                  <div className="metric-value">{summary?.approved_mappings ?? 0}</div>
                  <div className="metric-subtext">Locked into canonical model</div>
                </div>

                <div className="metric-card accent">
                  <div className="metric-header">
                    <span className="metric-title">Active Overrides</span>
                    <span className="metric-icon">🔄</span>
                  </div>
                  <div className="metric-value">{summary?.active_overrides_learned ?? 0}</div>
                  <div className="metric-subtext">Reusable fingerprint rules</div>
                </div>
              </div>

              {/* Execution Pipeline Overview */}
              <div className="apple-card" style={{ marginTop: '20px' }}>
                <div className="apple-card-header">
                  <div className="apple-card-title-group">
                    <h3 className="apple-card-title">Intelligent Governance Pipeline</h3>
                    <span className="apple-card-subtitle">End-to-end extraction, domain segregation, LLM semantic ranking, and human sign-off</span>
                  </div>
                  <button className="apple-button secondary" onClick={() => handleRunMapping(true)}>
                    <span>Run Fallback Engine Only</span>
                  </button>
                </div>
                <div className="apple-card-body">
                  <div className="pipeline-flow-steps">
                    <div className="flow-step">
                      <div className="step-num">1</div>
                      <div className="step-info">
                        <strong>Canonical Read</strong>
                        <span>Read measures & tables from Report/Semantic documents.</span>
                      </div>
                    </div>
                    <div className="flow-step">
                      <div className="step-num">2</div>
                      <div className="step-info">
                        <strong>Domain Segregation</strong>
                        <span>Classify entity into 1 of 5 segregated domains.</span>
                      </div>
                    </div>
                    <div className="flow-step">
                      <div className="step-num">3</div>
                      <div className="step-info">
                        <strong>LLM Ranking</strong>
                        <span>Semantic evaluation against reference KPI Bank.</span>
                      </div>
                    </div>
                    <div className="flow-step">
                      <div className="step-num">4</div>
                      <div className="step-info">
                        <strong>Deterministic Fallback</strong>
                        <span>Triggered on hallucination, timeout, or malformed JSON.</span>
                      </div>
                    </div>
                    <div className="flow-step">
                      <div className="step-num">5</div>
                      <div className="step-info">
                        <strong>Human Governance</strong>
                        <span>Mandatory sign-off with permanent override learning.</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Domain Distribution */}
              <div className="apple-card" style={{ marginTop: '20px' }}>
                <div className="apple-card-header">
                  <h3 className="apple-card-title">Segregated Domain Distribution</h3>
                </div>
                <div className="apple-card-body">
                  <div className="domain-cards-row">
                    {domains.map(dom => {
                      const count = summary?.domain_distribution?.[dom.code] ?? 0;
                      return (
                        <div key={dom.code} className="domain-stat-pill">
                          <span className="domain-badge">{dom.code}</span>
                          <span className="domain-name">{dom.name}</span>
                          <span className="domain-count">{count}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* VIEW 2: INGESTION & METADATA */}
          {activeView === 'metadata' && (
            <section className="view-panel active">
              {/* Ingested Analytical Sources */}
              <div className="apple-card" style={{ marginBottom: '20px' }}>
                <div className="apple-card-header">
                  <div className="apple-card-title-group">
                    <h3 className="apple-card-title">Ingested Analytical Sources</h3>
                    <span className="apple-card-subtitle">
                      Power BI Projects (.pbip) and semantic models registered in canonical persistence
                    </span>
                  </div>
                  <button className="apple-button primary small" onClick={() => setIngestModalOpen(true)}>
                    📥 Ingest Sources
                  </button>
                </div>
                <div className="apple-card-body no-padding">
                  <table className="apple-table">
                    <thead>
                      <tr>
                        <th>Asset Name</th>
                        <th>Platform</th>
                        <th>Version</th>
                        <th>Status</th>
                        <th>Ingested At</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ingestedSources.length === 0 ? (
                        <tr>
                          <td colSpan="5" className="text-center empty-state">
                            No source assets registered yet. Click "Ingest Sources" to upload PBIP files or select a project directory.
                          </td>
                        </tr>
                      ) : (
                        ingestedSources.map(s => (
                          <tr key={s.asset_id}>
                            <td>
                              <strong>{s.asset_name}</strong>
                              <div className="code-hint">{s.asset_id}</div>
                            </td>
                            <td><span className="type-badge">{s.platform}</span></td>
                            <td>v{s.version_number}</td>
                            <td><span className="status-pill approved">{s.status}</span></td>
                            <td className="code-hint">{s.ingested_at || 'Recently'}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Canonical Analytical Metadata */}
              <div className="apple-card">
                <div className="apple-card-header">
                  <div className="apple-card-title-group">
                    <h3 className="apple-card-title">Canonical Analytical Metadata</h3>
                    <span className="apple-card-subtitle">
                      Extracted exclusively from canonical documents (ReportDocument, SemanticModelDocument, AnalyticalObjectDocument)
                    </span>
                  </div>
                  <div className="filter-group">
                    <select
                      className="apple-select"
                      value={metadataDomainFilter}
                      onChange={e => setMetadataDomainFilter(e.target.value)}
                    >
                      <option value="">All Domains</option>
                      {domains.map(d => (
                        <option key={d.code} value={d.code}>{d.name}</option>
                      ))}
                    </select>
                    <button className="apple-button secondary small" onClick={() => setIngestModalOpen(true)}>
                      + Upload More
                    </button>
                  </div>
                </div>
                <div className="apple-card-body no-padding">
                  <table className="apple-table">
                    <thead>
                      <tr>
                        <th>Field Name</th>
                        <th>Type</th>
                        <th>Source Asset</th>
                        <th>Segregated Domain</th>
                        <th>Mapping Status</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredMetadataFields.length === 0 ? (
                        <tr><td colSpan="6" className="text-center empty-state">No metadata fields found. Ingest a Power BI Project to begin.</td></tr>
                      ) : (
                        filteredMetadataFields.map(f => (
                          <tr key={f.field_id}>
                            <td>
                              <strong>{f.name}</strong>
                              {f.formula && <div className="code-hint">{f.formula}</div>}
                            </td>
                            <td><span className="type-badge">{f.entity_type}</span></td>
                            <td>{f.source_asset_id}</td>
                            <td>
                              <div className="table-domain-cell">
                                <span className="domain-badge">{f.domain}</span>
                                <button
                                  className="link-action-btn"
                                  onClick={() => handleDomainCorrection(f.field_id, f.domain === 'CLAIMS_RISK' ? 'UNDERWRITING' : 'CLAIMS_RISK')}
                                >
                                  Reclassify
                                </button>
                              </div>
                            </td>
                            <td>
                              <span className={`status-pill ${f.mapping_status?.toLowerCase()}`}>
                                {f.mapping_status}
                              </span>
                            </td>
                            <td>
                              <button
                                className="apple-button secondary small"
                                onClick={() => handleInspectCandidates(f.field_id)}
                              >
                                Candidates
                              </button>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}

          {/* VIEW 3: DOMAIN SEGREGATION */}
          {activeView === 'domains' && (
            <section className="view-panel active">
              <div className="apple-card">
                <div className="apple-card-header">
                  <div className="apple-card-title-group">
                    <h3 className="apple-card-title">Canonical Segregated Business Domains</h3>
                    <span className="apple-card-subtitle">
                      Strict domain boundaries: Legal and Underwriting are strictly separated.
                    </span>
                  </div>
                </div>
                <div className="apple-card-body">
                  <div className="domain-grid">
                    {domains.map(d => (
                      <div key={d.code} className="domain-card-box">
                        <div className="domain-card-top">
                          <span className="domain-badge large">{d.code}</span>
                          <span className="domain-entity-count">
                            {summary?.domain_distribution?.[d.code] ?? 0} fields
                          </span>
                        </div>
                        <h4 className="domain-title">{d.name}</h4>
                        <p className="domain-desc">{d.description}</p>
                        <div className="domain-subtypes">
                          <strong>Key Signals:</strong> {d.subtypes?.join(', ') || 'N/A'}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* VIEW 4: KPI CANDIDATE MAPPING */}
          {activeView === 'mapping' && (
            <section className="view-panel active">
              <div className="apple-card">
                <div className="apple-card-header">
                  <div className="apple-card-title-group">
                    <h3 className="apple-card-title">Discovered KPI Candidate Mappings</h3>
                    <span className="apple-card-subtitle">Top-3 ranked candidates produced by LLM semantic evaluation & deterministic fallback</span>
                  </div>
                </div>
                <div className="apple-card-body no-padding">
                  <table className="apple-table">
                    <thead>
                      <tr>
                        <th>Metadata Field</th>
                        <th>Domain</th>
                        <th>Top Candidate</th>
                        <th>Confidence</th>
                        <th>Engine / Source</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {metadataFields.length === 0 ? (
                        <tr><td colSpan="6" className="text-center empty-state">No mappings discovered. Click "Run Mapping Pipeline" to process fields.</td></tr>
                      ) : (
                        metadataFields.map(f => {
                          const topCand = f.top_candidate || f.top_candidates?.[0] || {};
                          return (
                            <tr key={f.field_id}>
                              <td>
                                <strong>{f.name}</strong>
                                <div className="code-hint">{f.source_asset_id}</div>
                              </td>
                              <td><span className="domain-badge">{f.domain}</span></td>
                              <td>
                                {topCand.kpi_name ? (
                                  <div>
                                    <strong>{topCand.kpi_name}</strong>
                                    <div className="code-hint">{topCand.kpi_id}</div>
                                  </div>
                                ) : (
                                  <span className="text-muted">No candidate</span>
                                )}
                              </td>
                              <td>
                                {topCand.confidence_code ? (
                                  <span className={`confidence-badge ${topCand.confidence_code.toLowerCase()}`}>
                                    {topCand.confidence_code} ({Math.round((topCand.confidence_score || 0) * 100)}%)
                                  </span>
                                ) : '—'}
                              </td>
                              <td>
                                <span className={`engine-pill ${topCand.ranking_method === 'DETERMINISTIC_FALLBACK' ? 'fallback' : 'llm'}`}>
                                  {topCand.ranking_method || 'PENDING'}
                                </span>
                              </td>
                              <td>
                                <button
                                  className="apple-button secondary small"
                                  onClick={() => handleInspectCandidates(f.field_id)}
                                >
                                  View Evidence
                                </button>
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}

          {/* VIEW 5: HUMAN REVIEW & GOVERNANCE QUEUE */}
          {activeView === 'review' && (
            <section className="view-panel active">
              <div className="apple-card">
                <div className="apple-card-header">
                  <div className="apple-card-title-group">
                    <h3 className="apple-card-title">Human Governance Review Queue</h3>
                    <span className="apple-card-subtitle">
                      Human approval is mandatory for all proposed mappings. HIGH confidence proposals NEVER auto-approve.
                    </span>
                  </div>
                  <span className="badge-count-pill">{proposals.length} Pending Review</span>
                </div>
                <div className="apple-card-body no-padding">
                  {proposals.length === 0 ? (
                    <div className="empty-state-box">
                      <div className="empty-icon">✅</div>
                      <h4>Review Queue Clear</h4>
                      <p>All discovered metadata fields have been reviewed, approved, or overridden.</p>
                    </div>
                  ) : (
                    proposals.map(prop => {
                      const topCand = prop.top_candidate || prop.top_candidates?.[0] || {};
                      const mappingId = prop.active_mapping_id || prop.mapping_id || `map_${prop.field_id}`;
                      return (
                        <div key={prop.field_id} className="review-item-card">
                          <div className="review-item-header">
                            <div>
                              <h4 className="review-field-title">{prop.name}</h4>
                              <span className="code-hint">{prop.source_asset_id} • {prop.entity_type}</span>
                            </div>
                            <span className="domain-badge">{prop.domain}</span>
                          </div>

                          <div className="review-candidate-box">
                            <div className="candidate-summary-line">
                              <span className="rank-tag">Top 1</span>
                              <strong>{topCand.kpi_name || 'No proposal'}</strong>
                              {topCand.confidence_code && (
                                <span className={`confidence-badge ${topCand.confidence_code.toLowerCase()}`}>
                                  {topCand.confidence_code} ({Math.round((topCand.confidence_score || 0) * 100)}%)
                                </span>
                              )}
                              <span className="engine-pill">{topCand.ranking_method || 'PENDING'}</span>
                            </div>

                            {topCand.evidence && (
                              <div className="evidence-preview-box">
                                <strong>Rationale:</strong> {topCand.evidence.ranking_rationale || 'N/A'}
                              </div>
                            )}

                            <div className="review-action-row">
                              <button
                                className="apple-button primary small"
                                onClick={() => handleApprove(mappingId, topCand.kpi_id)}
                                disabled={!topCand.kpi_id}
                              >
                                ✅ Approve Proposal
                              </button>
                              <button
                                className="apple-button secondary small danger"
                                onClick={() => handleReject(mappingId)}
                              >
                                ❌ Reject
                              </button>
                              <button
                                className="apple-button secondary small"
                                onClick={() => {
                                  setChooseKpiModal({
                                    open: true,
                                    mappingId,
                                    fieldName: prop.name,
                                    candidates: prop.all_candidates || [],
                                  });
                                }}
                              >
                                🔄 Choose Other KPI
                              </button>
                              <button
                                className="apple-button secondary small"
                                onClick={() => {
                                  setAddKpiModal({
                                    open: true,
                                    mappingId,
                                    defaultDomain: prop.domain || 'CLAIMS_RISK',
                                  });
                                }}
                              >
                                ➕ Add Standard KPI
                              </button>
                              <button
                                className="link-action-btn"
                                onClick={() => handleInspectCandidates(prop.field_id)}
                              >
                                Full Evidence Drawer
                              </button>
                            </div>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </section>
          )}

          {/* VIEW 6: KPI BANK */}
          {activeView === 'kpibank' && (
            <section className="view-panel active">
              <div className="apple-card">
                <div className="apple-card-header">
                  <div className="apple-card-title-group">
                    <h3 className="apple-card-title">Reference KPI Bank</h3>
                    <span className="apple-card-subtitle">Authoritative enterprise KPI definitions and calculation standards</span>
                  </div>
                  <div className="filter-group">
                    <input
                      type="text"
                      className="apple-input search"
                      placeholder="Search name, aliases, definition..."
                      value={kpiBankSearchQuery}
                      onChange={e => setKpiBankSearchQuery(e.target.value)}
                    />
                    <select
                      className="apple-select"
                      value={kpiBankDomainFilter}
                      onChange={e => setKpiBankDomainFilter(e.target.value)}
                    >
                      <option value="">All Domains</option>
                      {domains.map(d => (
                        <option key={d.code} value={d.code}>{d.name}</option>
                      ))}
                    </select>
                    <button
                      className="apple-button primary small"
                      onClick={() => setAddKpiModal({ open: true, mappingId: null, defaultDomain: 'CLAIMS_RISK' })}
                    >
                      + Add Standard KPI
                    </button>
                  </div>
                </div>
                <div className="apple-card-body no-padding">
                  <div className="kpi-bank-list">
                    {filteredKpiBank.length === 0 ? (
                      <div className="empty-state-box">No KPIs found matching filters.</div>
                    ) : (
                      filteredKpiBank.map(k => (
                        <div key={k.id} className="kpi-bank-card">
                          <div className="kpi-card-header">
                            <div>
                              <h4 className="kpi-title">{k.name}</h4>
                              <span className="code-hint">{k.id} • {k.category || 'General'}</span>
                            </div>
                            <span className="domain-badge">{k.domain}</span>
                          </div>
                          <p className="kpi-def">{k.definition}</p>
                          {k.formula && (
                            <div className="kpi-formula-box">
                              <span className="formula-label">FORMULA:</span>
                              <code>{k.formula}</code>
                            </div>
                          )}
                          {k.aliases?.length > 0 && (
                            <div className="kpi-aliases-row">
                              <span className="aliases-label">Aliases:</span>
                              {k.aliases.map(a => <span key={a} className="alias-pill">{a}</span>)}
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* VIEW 7: OVERRIDES & LEARNING */}
          {activeView === 'overrides' && (
            <section className="view-panel active">
              <div className="apple-card">
                <div className="apple-card-header">
                  <div className="apple-card-title-group">
                    <h3 className="apple-card-title">Learned Overrides & Re-ingestion Rules</h3>
                    <span className="apple-card-subtitle">
                      Human override decisions are permanently learned and re-applied across subsequent ingestion runs via layered fingerprints.
                    </span>
                  </div>
                </div>
                <div className="apple-card-body no-padding">
                  <table className="apple-table">
                    <thead>
                      <tr>
                        <th>Source Entity</th>
                        <th>Replacement KPI</th>
                        <th>Fingerprint Level</th>
                        <th>Reuse Count</th>
                        <th>Justification</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {overrides.length === 0 ? (
                        <tr><td colSpan="6" className="text-center empty-state">No overrides recorded yet. Manual overrides will appear here.</td></tr>
                      ) : (
                        overrides.map(ovr => (
                          <tr key={ovr.id}>
                            <td>
                              <strong>{ovr.canonical_entity_id || ovr.source_asset_id || 'Entity'}</strong>
                              <div className="code-hint">{ovr.source_platform}</div>
                            </td>
                            <td>
                              <strong>{ovr.replacement_kpi_name || ovr.replacement_ontology_entry_id}</strong>
                            </td>
                            <td>
                              <span className="type-badge">
                                {ovr.canonical_source_fingerprint ? 'Level 2: Source' : 'Level 1: Object ID'}
                              </span>
                            </td>
                            <td>
                              <span className="badge-count-pill">{ovr.reuse_count ?? 0}</span>
                            </td>
                            <td>
                              <span className="justification-text">{ovr.override_justification}</span>
                            </td>
                            <td>
                              <button
                                className="apple-button secondary small danger"
                                onClick={() => handleInvalidateOverride(ovr.id)}
                              >
                                Invalidate
                              </button>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}

          {/* VIEW 8: AUDIT HISTORY */}
          {activeView === 'audit' && (
            <section className="view-panel active">
              <div className="apple-card">
                <div className="apple-card-header">
                  <div className="apple-card-title-group">
                    <h3 className="apple-card-title">Immutable Compliance Audit History</h3>
                    <span className="apple-card-subtitle">Complete chronological record of all human approvals, rejections, overrides, and domain changes</span>
                  </div>
                </div>
                <div className="apple-card-body no-padding">
                  <table className="apple-table">
                    <thead>
                      <tr>
                        <th>Timestamp</th>
                        <th>Event Type</th>
                        <th>Actor</th>
                        <th>Target ID</th>
                        <th>Reason / Justification</th>
                      </tr>
                    </thead>
                    <tbody>
                      {auditLogs.length === 0 ? (
                        <tr><td colSpan="5" className="text-center empty-state">No audit logs available.</td></tr>
                      ) : (
                        auditLogs.map(log => (
                          <tr key={log.id}>
                            <td className="code-hint">{log.created_at || log.timestamp}</td>
                            <td><span className="type-badge">{log.event_type}</span></td>
                            <td>{log.actor_user_id || 'system'}</td>
                            <td className="code-hint">{log.kpi_mapping_id || log.target_kpi_mapping_id || log.id}</td>
                            <td>{log.event_reason || log.reason || JSON.stringify(log.new_state || {})}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}
        </div>
      </main>

      {/* SLIDE-OVER EVIDENCE DRAWER */}
      {selectedCandidateData && (
        <div className="drawer-overlay" onClick={() => setSelectedCandidateData(null)}>
          <div className="drawer-content" onClick={e => e.stopPropagation()}>
            <div className="drawer-header">
              <div>
                <h3 className="drawer-title">{selectedCandidateData.field?.name}</h3>
                <span className="code-hint">Domain: {selectedCandidateData.field?.domain}</span>
              </div>
              <button className="apple-button secondary small" onClick={() => setSelectedCandidateData(null)}>✕</button>
            </div>

            <div className="drawer-view-toggle">
              <button
                className={`toggle-tab ${drawerMode === 'technical' ? 'active' : ''}`}
                onClick={() => setDrawerMode('technical')}
              >
                Technical Evidence
              </button>
              <button
                className={`toggle-tab ${drawerMode === 'analyst' ? 'active' : ''}`}
                onClick={() => setDrawerMode('analyst')}
              >
                Plain Analyst Summary
              </button>
            </div>

            <div className="drawer-body">
              {(selectedCandidateData.candidates || selectedCandidateData.top_candidates || []).map((c, idx) => (
                <div key={c.kpi_id || idx} className="candidate-drawer-card">
                  <div className="candidate-drawer-header">
                    <span className="rank-pill">Candidate #{idx + 1}</span>
                    <h4>{c.kpi_name}</h4>
                    <span className={`confidence-badge ${c.confidence_code?.toLowerCase()}`}>
                      {c.confidence_code} ({Math.round((c.confidence_score || 0) * 100)}%)
                    </span>
                  </div>

                  {drawerMode === 'technical' ? (
                    <div className="technical-evidence-block">
                      <div className="evidence-field">
                        <strong>Ranking Method:</strong> <code>{c.ranking_method}</code>
                      </div>
                      <div className="evidence-field">
                        <strong>Observed Signals:</strong> {c.evidence?.observed_evidence?.join('; ') || 'None'}
                      </div>
                      <div className="evidence-field">
                        <strong>Missing Info:</strong> {c.evidence?.missing_information?.join('; ') || 'None'}
                      </div>
                      <div className="evidence-field">
                        <strong>Contradictions:</strong> {c.evidence?.contradictory_evidence?.join('; ') || 'None detected'}
                      </div>
                      <div className="evidence-field">
                        <strong>Formula Compatibility:</strong> {c.evidence?.formula_compatibility || 'Compatible'}
                      </div>
                    </div>
                  ) : (
                    <div className="analyst-summary-block">
                      <p><strong>Rationale:</strong> {c.evidence?.ranking_rationale || 'High semantic compatibility.'}</p>
                      <p><strong>Inferences:</strong> {c.evidence?.inferences_made?.join('; ') || 'Direct term match.'}</p>
                    </div>
                  )}

                  <div className="candidate-drawer-actions">
                    <button
                      className="apple-button primary small"
                      onClick={async () => {
                        await handleApprove(`map_${selectedCandidateData.field.field_id}`, c.kpi_id);
                        setSelectedCandidateData(null);
                      }}
                    >
                      Approve This Candidate
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* CHOOSE ALTERNATIVE KPI MODAL */}
      {chooseKpiModal.open && (
        <ChooseKpiModalComponent
          modal={chooseKpiModal}
          kpiBankEntries={kpiBankEntries}
          onClose={() => setChooseKpiModal({ open: false, mappingId: null, fieldName: null, candidates: [] })}
          onSubmit={async (mappingId, kpiId, justification) => {
            try {
              const res = await api.overrideMapping(mappingId, kpiId, justification, tenantId);
              if (res.success) {
                addToast('success', `Override recorded and learned for future runs.`);
                setChooseKpiModal({ open: false, mappingId: null, fieldName: null, candidates: [] });
                await refreshAllData();
              }
            } catch (err) {
              addToast('error', `Override failed: ${err.message}`);
            }
          }}
        />
      )}

      {/* ADD STANDARD KPI MODAL */}
      {addKpiModal.open && (
        <AddKpiModalComponent
          modal={addKpiModal}
          domains={domains}
          existingKpis={kpiBankEntries}
          onClose={() => setAddKpiModal({ open: false, mappingId: null, defaultDomain: 'CLAIMS_RISK' })}
          onSubmit={async (kpiData) => {
            try {
              const res = await api.createKPI({ ...kpiData, mapping_id: addKpiModal.mappingId }, tenantId);
              if (res.success) {
                addToast('success', `Standard KPI '${kpiData.name}' created and mapped.`);
                setAddKpiModal({ open: false, mappingId: null, defaultDomain: 'CLAIMS_RISK' });
                await refreshAllData();
              }
            } catch (err) {
              addToast('error', `Creation failed: ${err.message}`);
            }
          }}
        />
      )}

      {/* INGEST SOURCES MODAL */}
      {ingestModalOpen && (
        <IngestSourcesModalComponent
          open={ingestModalOpen}
          tenantId={tenantId}
          onClose={() => setIngestModalOpen(false)}
          onIngestionComplete={async () => {
            await refreshAllData();
          }}
          addToast={addToast}
        />
      )}

      {/* TOAST CONTAINER */}
      <div className="toast-container">
        {toasts.map(t => (
          <div key={t.id} className={`apple-toast ${t.type}`}>
            <span className="toast-icon">
              {t.type === 'success' ? '✅' : t.type === 'warning' ? '⚠️' : '❌'}
            </span>
            <span className="toast-text">{t.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------------
// SUB-COMPONENTS: CHOOSE KPI MODAL
// -----------------------------------------------------------------------------

function ChooseKpiModalComponent({ modal, kpiBankEntries, onClose, onSubmit }) {
  const [selectedKpiId, setSelectedKpiId] = useState('');
  const [justification, setJustification] = useState('');
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    if (!search) return kpiBankEntries;
    const q = search.toLowerCase();
    return kpiBankEntries.filter(k => k.name.toLowerCase().includes(q) || k.id.toLowerCase().includes(q));
  }, [kpiBankEntries, search]);

  const isValidJustification = justification.trim().length >= 10;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">Choose Alternative KPI</h3>
          <button className="apple-button secondary small" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <p className="modal-subtitle">
            Remap <strong>{modal.fieldName}</strong> to a different standard KPI. A mandatory justification of at least 10 non-whitespace characters is required.
          </p>

          <div className="form-group">
            <label className="form-label">Search KPI Bank</label>
            <input
              type="text"
              className="apple-input"
              placeholder="Search by name or code..."
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>

          <div className="kpi-select-list">
            {filtered.map(k => (
              <div
                key={k.id}
                className={`kpi-select-row ${selectedKpiId === k.id ? 'selected' : ''}`}
                onClick={() => setSelectedKpiId(k.id)}
              >
                <div>
                  <strong>{k.name}</strong>
                  <div className="code-hint">{k.id} • {k.domain}</div>
                </div>
                {selectedKpiId === k.id && <span>✓</span>}
              </div>
            ))}
          </div>

          <div className="form-group" style={{ marginTop: '16px' }}>
            <label className="form-label">
              Override Justification <span className="required-star">*</span>
              <span className={`char-counter ${isValidJustification ? 'valid' : 'invalid'}`}>
                {justification.trim().length} / 10 chars minimum
              </span>
            </label>
            <textarea
              className="apple-textarea"
              placeholder="Explain why this KPI is the appropriate canonical representation..."
              rows={3}
              value={justification}
              onChange={e => setJustification(e.target.value)}
            />
          </div>
        </div>
        <div className="modal-footer">
          <button className="apple-button secondary" onClick={onClose}>Cancel</button>
          <button
            className="apple-button primary"
            disabled={!selectedKpiId || !isValidJustification}
            onClick={() => onSubmit(modal.mappingId, selectedKpiId, justification)}
          >
            Apply & Learn Override
          </button>
        </div>
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------------
// SUB-COMPONENTS: ADD KPI MODAL
// -----------------------------------------------------------------------------

function AddKpiModalComponent({ modal, domains, existingKpis, onClose, onSubmit }) {
  const [name, setName] = useState('');
  const [definition, setDefinition] = useState('');
  const [domain, setDomain] = useState(modal.defaultDomain || 'CLAIMS_RISK');
  const [formula, setFormula] = useState('');
  const [unit, setUnit] = useState('PERCENTAGE');
  const [category, setCategory] = useState('Financial');
  const [aliases, setAliases] = useState('');

  const isDuplicate = useMemo(() => {
    if (!name.trim()) return false;
    const norm = name.trim().toLowerCase();
    return existingKpis.some(k => k.name?.toLowerCase() === norm);
  }, [name, existingKpis]);

  const isValid = name.trim().length > 0 && definition.trim().length > 0 && !isDuplicate;

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!isValid) return;
    const aliasList = aliases.split(',').map(a => a.trim()).filter(Boolean);
    onSubmit({
      name: name.trim(),
      definition: definition.trim(),
      domain,
      formula: formula.trim() || null,
      unit,
      category,
      aliases: aliasList,
    });
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content large" onClick={e => e.stopPropagation()}>
        <form onSubmit={handleSubmit}>
          <div className="modal-header">
            <h3 className="modal-title">Create Standard Governed KPI</h3>
            <button type="button" className="apple-button secondary small" onClick={onClose}>✕</button>
          </div>
          <div className="modal-body">
            {isDuplicate && (
              <div className="apple-alert warning">
                ⚠️ A KPI with this exact name already exists in the reference KPI Bank. Duplicate names are not permitted.
              </div>
            )}

            <div className="form-row">
              <div className="form-group flex-2">
                <label className="form-label">KPI Name <span className="required-star">*</span></label>
                <input
                  type="text"
                  className="apple-input"
                  placeholder="e.g. Incurred Loss Ratio"
                  required
                  value={name}
                  onChange={e => setName(e.target.value)}
                />
              </div>
              <div className="form-group flex-1">
                <label className="form-label">Business Domain</label>
                <select className="apple-select" value={domain} onChange={e => setDomain(e.target.value)}>
                  {domains.map(d => (
                    <option key={d.code} value={d.code}>{d.name}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Definition <span className="required-star">*</span></label>
              <textarea
                className="apple-textarea"
                placeholder="Authoritative business definition..."
                rows={2}
                required
                value={definition}
                onChange={e => setDefinition(e.target.value)}
              />
            </div>

            <div className="form-row">
              <div className="form-group flex-2">
                <label className="form-label">Standard Formula (DAX / SQL)</label>
                <input
                  type="text"
                  className="apple-input code"
                  placeholder="e.g. IncurredLosses / EarnedPremium"
                  value={formula}
                  onChange={e => setFormula(e.target.value)}
                />
              </div>
              <div className="form-group flex-1">
                <label className="form-label">Unit</label>
                <select className="apple-select" value={unit} onChange={e => setUnit(e.target.value)}>
                  <option value="PERCENTAGE">Percentage (%)</option>
                  <option value="CURRENCY">Currency ($)</option>
                  <option value="RATIO">Ratio</option>
                  <option value="COUNT">Count</option>
                  <option value="DAYS">Days</option>
                </select>
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Aliases (Comma-separated)</label>
              <input
                type="text"
                className="apple-input"
                placeholder="e.g. Loss Ratio, ILR, Claims Ratio"
                value={aliases}
                onChange={e => setAliases(e.target.value)}
              />
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="apple-button secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="apple-button primary" disabled={!isValid}>
              Create & Save to KPI Bank
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------------
// SUB-COMPONENTS: INGEST SOURCES MODAL
// -----------------------------------------------------------------------------

function IngestSourcesModalComponent({ open, onClose, tenantId, onIngestionComplete, addToast }) {
  const [activeTab, setActiveTab] = useState('files'); // 'files' | 'folder'
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [jobResult, setJobResult] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [supportedFormats, setSupportedFormats] = useState(null);

  useEffect(() => {
    api.getSupportedFormats().then(res => {
      if (res.success) {
        setSupportedFormats(res.data);
      }
    }).catch(() => {});
  }, []);

  const recognizeFile = (filename) => {
    const lower = filename.toLowerCase();
    if (lower.endsWith('.pbip')) return { status: 'SUPPORTED', label: 'PBIP Project Root', valid: true };
    if (lower.endsWith('.tmdl')) return { status: 'SUPPORTED', label: 'TMDL Measure/Table', valid: true };
    if (lower.endsWith('.json') || lower.endsWith('.pbir') || lower.endsWith('.pbism')) {
      return { status: 'SUPPORTED', label: 'PBIP Definition', valid: true };
    }
    if (lower.endsWith('.zip')) return { status: 'SUPPORTED', label: 'PBIP Zip Archive', valid: true };
    if (lower.endsWith('.pbix')) return { status: 'UNSUPPORTED', label: 'Legacy Binary (.pbix)', valid: false };
    if (lower.endsWith('.xlsx') || lower.endsWith('.xlsm')) return { status: 'PLANNED', label: 'Excel (Planned)', valid: false };
    if (lower.endsWith('.twbx') || lower.endsWith('.twb')) return { status: 'PLANNED', label: 'Tableau (Planned)', valid: false };
    return { status: 'OTHER', label: 'Other File', valid: true };
  };

  const handleFileSelect = (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    const mapped = files.map(f => {
      const rec = recognizeFile(f.name);
      return {
        file: f,
        relativePath: f.name,
        ...rec,
      };
    });
    setSelectedFiles(prev => [...prev, ...mapped]);
    e.target.value = '';
  };

  const handleFolderSelect = (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    const mapped = files.map(f => {
      const relPath = f.webkitRelativePath || f.name;
      const rec = recognizeFile(relPath);
      return {
        file: f,
        relativePath: relPath,
        ...rec,
      };
    });
    setSelectedFiles(mapped);
    e.target.value = '';
  };

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const files = Array.from(e.dataTransfer.files);
      const mapped = files.map(f => {
        const rec = recognizeFile(f.name);
        return {
          file: f,
          relativePath: f.name,
          ...rec,
        };
      });
      setSelectedFiles(prev => [...prev, ...mapped]);
    }
  };

  const removeFile = (idx) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== idx));
  };

  const clearFiles = () => {
    setSelectedFiles([]);
    setJobResult(null);
  };

  const hasPbipInFolder = useMemo(() => {
    return selectedFiles.some(f => f.relativePath.toLowerCase().endsWith('.pbip'));
  }, [selectedFiles]);

  const totalSizeFormatted = useMemo(() => {
    const totalBytes = selectedFiles.reduce((acc, f) => acc + (f.file?.size || 0), 0);
    if (totalBytes < 1024) return `${totalBytes} B`;
    if (totalBytes < 1024 * 1024) return `${(totalBytes / 1024).toFixed(1)} KB`;
    return `${(totalBytes / (1024 * 1024)).toFixed(2)} MB`;
  }, [selectedFiles]);

  const hasUnsupportedBinary = useMemo(() => {
    return selectedFiles.some(f => f.status === 'UNSUPPORTED' || f.status === 'PLANNED');
  }, [selectedFiles]);

  const handleStartIngestion = async () => {
    if (!selectedFiles.length) return;
    setUploading(true);
    setJobResult(null);

    try {
      let res;
      if (activeTab === 'files') {
        const fileObjects = selectedFiles.map(s => s.file);
        res = await api.uploadFiles(fileObjects, tenantId);
      } else {
        const items = selectedFiles.map(s => ({ file: s.file, relativePath: s.relativePath }));
        res = await api.uploadFolder(items, tenantId);
      }

      if (res.success) {
        setJobResult(res.data);
        addToast('success', `Ingestion completed: ${res.data.files_processed} files processed, ${res.data.stats?.measures_extracted ?? 0} measures extracted.`);
        onIngestionComplete();
      } else {
        addToast('error', res.error || 'Ingestion failed.');
        setJobResult(res.data || { status: 'FAILED', error_message: res.error });
      }
    } catch (err) {
      addToast('error', `Ingestion failed: ${err.message}`);
      setJobResult({ status: 'FAILED', error_message: err.message });
    } finally {
      setUploading(false);
    }
  };

  if (!open) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content large" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h3 className="modal-title">Ingest Analytical Sources</h3>
            <span className="page-header-subtitle" style={{ display: 'block', marginTop: '2px' }}>
              Power BI Project (.pbip) extraction and canonical model registration
            </span>
          </div>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            aria-label="Close modal"
          >
            ✕
          </button>
        </div>

        <div className="modal-body">
          {/* Format Support Callout */}
          <div className="format-info-box">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
              <span className="supported-badge supported">Supported</span>
              <strong>Power BI Project (.pbip)</strong>
            </div>
            <p style={{ margin: 0, fontSize: '13px', lineHeight: 1.5 }}>
              Accepts PBIP project folders or .zip archives with TMDL semantic models (<code>.pbip</code>, <code>.pbir</code>, <code>.pbism</code>, <code>.tmdl</code>, <code>.json</code>).
            </p>
            <div style={{ marginTop: '8px', padding: '8px 12px', background: 'rgba(255, 159, 10, 0.1)', borderRadius: 'var(--radius-sm)', border: '1px solid rgba(255, 159, 10, 0.25)', fontSize: '12px', color: 'var(--text-primary)' }}>
              <strong>Notice:</strong> Legacy binary files (<code>.pbix</code>), Excel, and Tableau are unsupported or planned. Save Power BI models as <strong>.pbip (Power BI Project)</strong> with TMDL to enable full semantic measure extraction.
            </div>
          </div>

          {/* Navigation Tabs */}
          <div className="ingest-tabs-header" role="tablist" aria-label="Ingestion Source Mode">
            <button
              className={`ingest-tab-btn ${activeTab === 'files' ? 'active' : ''}`}
              onClick={() => { setActiveTab('files'); clearFiles(); }}
              role="tab"
              aria-selected={activeTab === 'files'}
              type="button"
            >
              📄 Upload Files
            </button>
            <button
              className={`ingest-tab-btn ${activeTab === 'folder' ? 'active' : ''}`}
              onClick={() => { setActiveTab('folder'); clearFiles(); }}
              role="tab"
              aria-selected={activeTab === 'folder'}
              type="button"
            >
              📁 Select PBIP Folder
            </button>
          </div>

          {/* Tab 1: Upload Files */}
          {activeTab === 'files' && (
            <div>
              <div
                className={`ingest-dropzone ${dragActive ? 'drag-active' : ''}`}
                onDragEnter={handleDrag}
                onDragLeave={handleDrag}
                onDragOver={handleDrag}
                onDrop={handleDrop}
                onClick={() => document.getElementById('file-upload-input').click()}
                onKeyDown={e => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    document.getElementById('file-upload-input').click();
                  }
                }}
                role="button"
                tabIndex={0}
                aria-label="Upload files drop zone"
              >
                <div className="dropzone-icon">☁️</div>
                <div className="dropzone-title">Drag & drop PBIP project files or .zip archive</div>
                <div className="dropzone-subtitle">Supports .pbip, .tmdl, .json, .pbir, .pbism, and .zip archives (up to 50 MB)</div>
                <input
                  id="file-upload-input"
                  type="file"
                  multiple
                  style={{ display: 'none' }}
                  onChange={handleFileSelect}
                  accept=".pbip,.pbir,.pbism,.tmdl,.json,.zip,.pbix,.xlsx,.twbx"
                />
                <button
                  type="button"
                  className="apple-button secondary small"
                  onClick={e => { e.stopPropagation(); document.getElementById('file-upload-input').click(); }}
                >
                  Browse Files
                </button>
              </div>
            </div>
          )}

          {/* Tab 2: Select Folder */}
          {activeTab === 'folder' && (
            <div>
              <div
                className="ingest-dropzone"
                onClick={() => document.getElementById('folder-upload-input').click()}
                onKeyDown={e => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    document.getElementById('folder-upload-input').click();
                  }
                }}
                role="button"
                tabIndex={0}
                aria-label="Select directory drop zone"
              >
                <div className="dropzone-icon">📁</div>
                <div className="dropzone-title">Select PBIP Project Root Folder</div>
                <div className="dropzone-subtitle">
                  Select the folder containing your .pbip file and .SemanticModel/.Report subfolders
                </div>
                <input
                  id="folder-upload-input"
                  type="file"
                  webkitdirectory=""
                  directory=""
                  multiple
                  style={{ display: 'none' }}
                  onChange={handleFolderSelect}
                />
                <button
                  type="button"
                  className="apple-button secondary small"
                  onClick={e => { e.stopPropagation(); document.getElementById('folder-upload-input').click(); }}
                >
                  Select Directory
                </button>
              </div>

              {selectedFiles.length > 0 && (
                <div className="folder-tree-summary">
                  <div>
                    <strong>Selected Folder:</strong> {selectedFiles.length} files ({totalSizeFormatted})
                    <div style={{ marginTop: '2px' }}>
                      {hasPbipInFolder ? (
                        <span style={{ color: 'var(--apple-green)', fontWeight: 600 }}>
                          ✅ PBIP project root detected in folder
                        </span>
                      ) : (
                        <span style={{ color: 'var(--apple-amber)', fontWeight: 600 }}>
                          ⚠️ No .pbip file detected. Make sure to select the parent folder containing your .pbip project.
                        </span>
                      )}
                    </div>
                  </div>
                  <button type="button" className="link-action-btn" onClick={clearFiles}>
                    Clear
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Warning if unsupported files included */}
          {hasUnsupportedBinary && (
            <div className="apple-alert warning" style={{ marginTop: '12px' }}>
              ⚠️ One or more files are legacy binary (.pbix) or planned formats. They will be skipped during ingestion.
            </div>
          )}

          {/* Selected Files Preview Table */}
          {selectedFiles.length > 0 && (
            <div style={{ marginTop: '16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ fontSize: '13px', fontWeight: 600 }}>
                  Selected Files ({selectedFiles.length}) • Total: {totalSizeFormatted}
                </span>
                <button type="button" className="link-action-btn" onClick={clearFiles}>
                  Clear All
                </button>
              </div>

              <div className="file-preview-table-container">
                <table className="apple-table small" aria-label="Selected files preview">
                  <thead>
                    <tr>
                      <th>Relative Path / Name</th>
                      <th>Type</th>
                      <th>Size</th>
                      <th>Status</th>
                      <th style={{ textAlign: 'right' }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedFiles.slice(0, 100).map((f, idx) => (
                      <tr key={idx}>
                        <td className="file-path-cell" title={f.relativePath}>
                          {f.relativePath}
                        </td>
                        <td><span className="code-hint">{f.label}</span></td>
                        <td>{(f.file.size / 1024).toFixed(1)} KB</td>
                        <td>
                          <span className={`supported-badge ${f.status.toLowerCase()}`}>
                            {f.status}
                          </span>
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          <button
                            type="button"
                            className="link-action-btn"
                            style={{ color: 'var(--apple-red)' }}
                            onClick={() => removeFile(idx)}
                            aria-label={`Remove ${f.relativePath}`}
                          >
                            ✕
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {selectedFiles.length > 100 && (
                <div className="code-hint" style={{ marginTop: '4px' }}>
                  Showing first 100 of {selectedFiles.length} files.
                </div>
              )}
            </div>
          )}

          {/* Job Completion / Diagnostics Box */}
          {jobResult && (
            <div
              className={`apple-alert ${jobResult.status === 'COMPLETED' ? 'success' : 'error'}`}
              style={{ marginTop: '16px' }}
            >
              {jobResult.status === 'COMPLETED' ? (
                <div>
                  <h4 style={{ margin: '0 0 6px 0' }}>✅ Ingestion Successful</h4>
                  <div style={{ fontSize: '13px', lineHeight: 1.5 }}>
                    <div><strong>Asset:</strong> {jobResult.asset_name} (<code>{jobResult.asset_id}</code>)</div>
                    <div><strong>Files:</strong> {jobResult.files_processed} processed, {jobResult.files_skipped} skipped</div>
                    {jobResult.stats && (
                      <div>
                        <strong>Extracted:</strong> {jobResult.stats.measures_extracted ?? 0} measures, {jobResult.stats.tables_extracted ?? 0} tables
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div>
                  <h4 style={{ margin: '0 0 6px 0' }}>❌ Ingestion Failed</h4>
                  <p style={{ margin: 0, fontSize: '13px' }}>
                    {jobResult.error_message || 'Could not parse PBIP project. Verify project structure.'}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button type="button" className="apple-button secondary" onClick={onClose} disabled={uploading}>
            {jobResult?.status === 'COMPLETED' ? 'Done' : 'Cancel'}
          </button>
          <button
            type="button"
            className="apple-button primary"
            onClick={handleStartIngestion}
            disabled={uploading || selectedFiles.length === 0}
          >
            {uploading ? '⏳ Extracting & Ingesting...' : 'Start Ingestion'}
          </button>
        </div>
      </div>
    </div>
  );
}
