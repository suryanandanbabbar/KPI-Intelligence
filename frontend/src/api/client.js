/**
 * KPI Intelligence — Centralized API Client Layer.
 * Connects the React application to the FastAPI backend over documented HTTP APIs.
 */

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/+$/, '');

class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

async function request(endpoint, options = {}, tenantId) {
  const url = `${API_BASE}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;
  const isFormData = options.body instanceof FormData;
  const headers = {
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}),
    ...(options.headers || {}),
  };

  const config = {
    ...options,
    headers,
  };

  if (config.body && typeof config.body === 'object' && !isFormData) {
    config.body = JSON.stringify(config.body);
  }

  try {
    const response = await fetch(url, config);
    const contentType = response.headers.get('content-type') || '';
    let data;

    if (contentType.includes('application/json')) {
      data = await response.json();
    } else {
      data = { text: await response.text() };
    }

    if (!response.ok) {
      const errorMessage = data?.error || data?.detail || `HTTP ${response.status}: ${response.statusText}`;
      throw new ApiError(errorMessage, response.status, data);
    }

    return data;
  } catch (err) {
    if (err instanceof ApiError) {
      throw err;
    }
    throw new ApiError(err.message || 'Network request failed', 0, null);
  }
}

export const api = {
  // Diagnostics
  async checkHealth() {
    const res = await fetch('/health');
    return res.json();
  },

  async getLLMStatus() {
    return request('/llm/status', { method: 'GET' });
  },

  // Workspace
  async getWorkspaceSummary(tenantId) {
    return request('/workspace/summary', { method: 'GET' }, tenantId);
  },

  // Domains
  async getDomains() {
    return request('/domains', { method: 'GET' });
  },

  async getDomainMetrics(domain, tenantId) {
    return request(`/domains/${encodeURIComponent(domain)}/metrics`, { method: 'GET' }, tenantId);
  },

  async updateFieldDomain(fieldId, domain, justification, tenantId) {
    return request(`/metadata/fields/${encodeURIComponent(fieldId)}/domain`, {
      method: 'POST',
      body: {
        target_object_id: fieldId,
        corrected_domain: domain,
        justification: justification || 'Human corrected domain via UI',
      },
    }, tenantId);
  },

  // Metadata Fields
  async getMetadataFields(params = {}, tenantId) {
    const query = new URLSearchParams();
    if (params.domain) query.set('domain', params.domain);
    if (params.status) query.set('status', params.status);
    if (params.entityType) query.set('entity_type', params.entityType);
    const qs = query.toString();
    return request(`/metadata/fields${qs ? `?${qs}` : ''}`, { method: 'GET' }, tenantId);
  },

  async getFieldCandidates(fieldId, tenantId) {
    return request(`/mapping/fields/${encodeURIComponent(fieldId)}/candidates`, { method: 'GET' }, tenantId);
  },

  // Mapping Execution
  async runMappingPipeline(options = {}, tenantId) {
    return request('/mapping/run', {
      method: 'POST',
      body: {
        user_id: options.userId || 'analyst',
        force_fallback: Boolean(options.forceFallback),
      },
    }, tenantId);
  },

  // Proposals
  async getProposals(params = {}, tenantId) {
    const query = new URLSearchParams();
    if (params.domain) query.set('domain', params.domain);
    const qs = query.toString();
    return request(`/mappings/proposals${qs ? `?${qs}` : ''}`, { method: 'GET' }, tenantId);
  },

  // Human Governance Decisions
  async approveMapping(mappingId, approvedKpiId, tenantId) {
    return request('/mapping/approve', {
      method: 'POST',
      body: {
        mapping_id: mappingId,
        approved_kpi_id: approvedKpiId,
        user_id: 'governance_analyst',
      },
    }, tenantId);
  },

  async rejectMapping(mappingId, reason, tenantId) {
    return request('/mapping/reject', {
      method: 'POST',
      body: {
        mapping_id: mappingId,
        reason: reason || 'Not a business-approved KPI',
        user_id: 'governance_analyst',
      },
    }, tenantId);
  },

  async overrideMapping(mappingId, replacementKpiId, justification, tenantId) {
    return request('/mapping/override', {
      method: 'POST',
      body: {
        mapping_id: mappingId,
        replacement_kpi_id: replacementKpiId,
        override_justification: justification,
        user_id: 'governance_analyst',
      },
    }, tenantId);
  },

  // KPI Bank
  async searchKPIBank(params = {}) {
    const query = new URLSearchParams();
    if (params.q) query.set('q', params.q);
    if (params.domain) query.set('domain', params.domain);
    if (params.status) query.set('status', params.status);
    const qs = query.toString();
    return request(`/kpi-bank/search${qs ? `?${qs}` : ''}`, { method: 'GET' });
  },

  async createKPI(kpiData, tenantId) {
    return request('/kpi-bank/create', {
      method: 'POST',
      body: kpiData,
    }, tenantId);
  },

  // Overrides & Learning
  async getOverrides(tenantId) {
    return request('/overrides', { method: 'GET' }, tenantId);
  },

  async invalidateOverride(overrideId, reason, tenantId) {
    return request('/overrides/invalidate', {
      method: 'POST',
      body: {
        override_id: overrideId,
        reason: reason || 'Manual invalidation via UI',
        user_id: 'governance_analyst',
      },
    }, tenantId);
  },

  // Audit
  async getAuditHistory(limit = 50, tenantId) {
    return request(`/audit/history?limit=${limit}`, { method: 'GET' }, tenantId);
  },

  // Ingestion & Sources
  async getSupportedFormats() {
    return request('/ingestion/supported-formats', { method: 'GET' });
  },

  async getIngestedSources(tenantId) {
    return request('/ingestion/sources', { method: 'GET' }, tenantId);
  },

  async uploadFiles(files, tenantId) {
    const formData = new FormData();
    for (const file of files) {
      formData.append('files', file);
    }
    return request('/ingestion/uploads', {
      method: 'POST',
      body: formData,
    }, tenantId);
  },

  async uploadFolder(filesWithPaths, tenantId) {
    const formData = new FormData();
    const relativePaths = [];
    for (const item of filesWithPaths) {
      formData.append('files', item.file);
      relativePaths.push(item.relativePath || item.file.name);
    }
    formData.append('relative_paths', JSON.stringify(relativePaths));
    return request('/ingestion/folder-uploads', {
      method: 'POST',
      body: formData,
    }, tenantId);
  },

  async getIngestionJob(jobId, tenantId) {
    return request(`/ingestion/jobs/${encodeURIComponent(jobId)}`, { method: 'GET' }, tenantId);
  },
};
