import type {
  AskResponse,
  AuthoredDocument,
  AuraAgent,
  Client,
  Document,
  DocumentUploadResponse,
  DocumentExpert,
  ExpertComparison,
  Notification,
  SearchRequest,
  SearchResponse,
  Stats,
  TeamworkAutoSyncSettings,
  TeamworkRoutingMode,
  TeamworkSyncResult,
  TeamworkSyncState,
  Ticket,
  User,
} from '../types'

const BASE = '/api'

export interface TicketFilters {
  client?: string
  agent?: string
  inbox?: string
  search?: string
  mismatch_only?: boolean
  unrouted_only?: boolean
  sort_by_status?: boolean
  imported_after?: string
}

export interface TeamworkImportProgress {
  status: 'idle' | 'queued' | 'running' | 'completed' | 'error'
  message: string
  processed?: number
  imported?: number
  skipped?: number
  failed?: number
  total?: number | null
  started_at?: string | null
  updated_at?: string | null
  finished_at?: string | null
  error?: string | null
}

export interface TeamworkImportStatus {
  tickets_in_graph: number
  import_running: boolean
  last_imported_at: string | null
  progress?: TeamworkImportProgress | null
}

export interface TeamworkImportStartResponse {
  status: 'started' | 'already_running'
}

function ticketFilterParams(filters?: TicketFilters, base?: Record<string, string>): URLSearchParams {
  const params = new URLSearchParams(base)
  if (filters?.client) params.set('client', filters.client)
  if (filters?.agent) params.set('agent', filters.agent)
  if (filters?.inbox) params.set('inbox', filters.inbox)
  if (filters?.search) params.set('search', filters.search)
  if (filters?.mismatch_only) params.set('mismatch_only', 'true')
  if (filters?.unrouted_only) params.set('unrouted_only', 'true')
  if (filters?.sort_by_status) params.set('sort_by_status', 'true')
  if (filters?.imported_after) params.set('imported_after', filters.imported_after)
  return params
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { credentials: 'same-origin', ...init })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error((err as { detail?: string }).detail ?? 'Request failed')
  }
  return res.json() as Promise<T>
}

// For no-content responses (e.g. 204 DELETE): throws on failure but doesn't parse
// a body, so callers (incl. react-query mutations) reject on HTTP 4xx/5xx.
async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  const res = await fetch(`${BASE}${path}`, { credentials: 'same-origin', ...init })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error((err as { detail?: string }).detail ?? 'Request failed')
  }
}

export const api = {
  auth: {
    me: () => request<{ authenticated: boolean }>('/auth/me'),
    login: (password: string) =>
      request<{ authenticated: boolean }>('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      }),
    logout: () => request<{ authenticated: boolean }>('/auth/logout', { method: 'POST' }),
  },

  health: {
    get: () => request<{ status: string }>('/health'),
    stats: () => request<Stats>('/stats'),
    expertLoad: () => request<{ name: string; email: string; ticket_count: number }[]>('/stats/expert-load'),
    clientLoad: () => request<{ name: string | null; domain: string | null; ticket_count: number }[]>('/stats/client-load'),
    recentActivity: () => request<{
      subject: string | null
      ticket_id: string | number
      expert_name: string | null
      expert_email: string | null
      routed_at: string | null
      client_name: string | null
      outcome: string | null
      confirmed: boolean
    }[]>('/stats/recent-activity'),
    needsReview: () => request<{ staged: number }>('/stats/needs-review'),
  },

  aura: {
    listAgents: () => request<AuraAgent[]>('/aura/agents'),
    getAgent: (id: string) => request<AuraAgent>(`/aura/agents/${encodeURIComponent(id)}`),
    updateAgent: (
      id: string,
      body: {
        system_prompt?: string
        tools?: AuraAgent['tools']
        is_private?: boolean
        is_mcp_enabled?: boolean
      },
    ) =>
      request<AuraAgent>(`/aura/agents/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
  },

  documents: {
    list: (offset = 0, limit = 20) =>
      request<Document[]>(`/documents?offset=${offset}&limit=${limit}`),
    get: (id: string) => request<Document>(`/documents/${id}`),
    delete: (id: string) => fetch(`${BASE}/documents/${id}`, { method: 'DELETE', credentials: 'same-origin' }),
    experts: (id: string) => request<DocumentExpert[]>(`/documents/${id}/experts`),
    addExpert: (id: string, email: string) =>
      request<DocumentExpert>(`/documents/${id}/experts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      }),
    removeExpert: (id: string, email: string) =>
      requestVoid(`/documents/${id}/experts?email=${encodeURIComponent(email)}`, {
        method: 'DELETE',
      }),
    upload: (file: File, authorEmail?: string, tags?: string): Promise<DocumentUploadResponse> => {
      const form = new FormData()
      form.append('file', file)
      if (authorEmail) form.append('author_email', authorEmail)
      if (tags) form.append('tags', tags)
      return request<DocumentUploadResponse>('/documents/upload', { method: 'POST', body: form })
    },
  },

  notifications: {
    list: (limit?: number) => {
      const suffix = limit ? `?limit=${limit}` : ''
      return request<Notification[]>(`/notifications/${suffix}`)
    },
  },

  search: {
    query: (body: SearchRequest) =>
      request<SearchResponse>('/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    ask: (question: string, threshold = 0.7, max_chunks = 8) =>
      request<AskResponse>('/search/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, threshold, max_chunks }),
      }),
  },

  users: {
    list: () => request<User[]>('/users'),
    get: (id: string) => request<User & { authored_documents: AuthoredDocument[] }>(`/users/${id}`),
    updateProfile: (id: string, body: { department?: string; title?: string; manager_email?: string; skills?: string[] }) =>
      request<User>(`/users/${id}/profile`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    create: (body: { name: string; email: string; title?: string; department?: string; skills?: string[] }) =>
      request<User>('/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    delete: (id: string) =>
      fetch(`${BASE}/users/${id}`, { method: 'DELETE', credentials: 'same-origin' }).then(r => {
        if (!r.ok && r.status !== 204) throw new Error('Delete failed')
      }),
    generateSkills: (id: string) =>
      request<{ skills: string[] }>(`/users/${id}/generate-skills`, { method: 'POST' }),
    compare: (idA: string, idB: string) =>
      request<ExpertComparison>(`/users/compare?a=${encodeURIComponent(idA)}&b=${encodeURIComponent(idB)}`),
  },

  clients: {
    list: (offset = 0, limit = 50, search?: string) => {
      const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
      if (search) params.set('search', search)
      return request<Client[]>(`/clients?${params}`)
    },
    get: (domain: string) => request<Client>(`/clients/${encodeURIComponent(domain)}`),
    link: (domain: string, parentDomain: string) =>
      request(`/clients/${encodeURIComponent(domain)}/link`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parent_domain: parentDomain }),
      }),
    unlink: (domain: string) =>
      fetch(`${BASE}/clients/${encodeURIComponent(domain)}/link`, { method: 'DELETE', credentials: 'same-origin' }),
  },

  import: {
    startTeamworkImport: () =>
      request<TeamworkImportStartResponse>('/import/teamwork', { method: 'POST' }),
    teamworkStatus: () => request<TeamworkImportStatus>('/import/teamwork/status'),
    teamworkRoutingMode: () => request<{ mode: TeamworkRoutingMode; staging_expert_configured: boolean }>('/import/teamwork/routing-mode'),
    teamworkSyncState: () => request<{ initialized: boolean; state: TeamworkSyncState | null }>('/import/teamwork/sync-state'),
    teamworkAutoSync: () => request<TeamworkAutoSyncSettings>('/import/teamwork/auto-sync'),
    setTeamworkAutoSync: (settings: TeamworkAutoSyncSettings) =>
      request<TeamworkAutoSyncSettings>('/import/teamwork/auto-sync', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      }),
    bootstrapTeamworkSync: () =>
      request<TeamworkSyncState>('/import/teamwork/sync/bootstrap', { method: 'POST' }),
    syncTeamworkNow: () =>
      request<TeamworkSyncResult>('/import/teamwork/sync-now', { method: 'POST' }),
    setTeamworkRoutingMode: (mode: TeamworkRoutingMode) =>
      request<{ mode: TeamworkRoutingMode; staging_expert_configured: boolean }>('/import/teamwork/routing-mode', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
      }),
    purgeBlockedPreview: (prefix?: string) => request<{ count: number; samples: string[]; filter: string }>(`/import/teamwork/purge-blocked/preview${prefix ? `?prefix=${encodeURIComponent(prefix)}` : ''}`),
    teamworkFilterOptions: () => request<{ clients: string[]; agents: string[]; inboxes: string[] }>('/import/teamwork/filters'),
    countTickets: (filters?: TicketFilters) =>
      request<{ count: number }>(
        `/import/teamwork/tickets/count?${ticketFilterParams(filters)}`,
      ),
    listTickets: (offset = 0, limit = 20, filters?: TicketFilters) =>
      request<Ticket[]>(
        `/import/teamwork/tickets?${ticketFilterParams(filters, { offset: String(offset), limit: String(limit) })}`,
      ),
    clearTeamworkTickets: () =>
      request<{ deleted: number }>('/import/teamwork/tickets', { method: 'DELETE' }),
    purgeBlockedTickets: (prefix?: string, block = false) => {
      const params = new URLSearchParams()
      if (prefix) params.set('prefix', prefix)
      if (block) params.set('block', 'true')
      const qs = params.toString()
      const url = qs ? `/import/teamwork/purge-blocked?${qs}` : '/import/teamwork/purge-blocked'
      return request<{ deleted: number }>(url, { method: 'POST' })
    },
    listAllTickets: (offset = 0, limit = 20) =>
      request<Ticket[]>(`/import/tickets?offset=${offset}&limit=${limit}`),
    getTicket: (id: string) => request<Ticket>(`/import/tickets/${encodeURIComponent(id)}`),
    routeTicketAura: (id: string) =>
      request<{ ticket_id: string; expert_email: string | null; expert_name: string | null; routing_event?: Record<string, unknown> }>(
        `/import/tickets/${encodeURIComponent(id)}/route-aura`,
        { method: 'POST' },
      ),
    postAuraSuggestion: (id: string) =>
      request<{ ticket_id: string; action: string }>(
        `/import/tickets/${encodeURIComponent(id)}/post-aura-suggestion`,
        { method: 'POST' },
      ),
    assignAuraSuggestion: (id: string) =>
      request<{ ticket_id: string; action: string }>(
        `/import/tickets/${encodeURIComponent(id)}/assign-aura-suggestion`,
        { method: 'POST' },
      ),
    postStagingExpert: (id: string) =>
      request<{ ticket_id: string; action: string }>(
        `/import/tickets/${encodeURIComponent(id)}/post-staging-expert`,
        { method: 'POST' },
      ),
    assignStagingExpert: (id: string) =>
      request<{ ticket_id: string; action: string }>(
        `/import/tickets/${encodeURIComponent(id)}/assign-staging-expert`,
        { method: 'POST' },
      ),
    confirmRouting: (id: string, expert_email: string, expert_name: string, is_override: boolean) =>
      request(`/import/tickets/${encodeURIComponent(id)}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expert_email, expert_name, is_override }),
      }),
    deleteTicket: (id: string) =>
      fetch(`${BASE}/import/tickets/${encodeURIComponent(id)}`, { method: 'DELETE', credentials: 'same-origin' }),
    spamTicket: (id: string) =>
      fetch(`${BASE}/import/tickets/${encodeURIComponent(id)}/spam`, { method: 'POST', credentials: 'same-origin' }),
    bulkDeleteTickets: (ids: string[]) =>
      request<{ deleted: number }>('/import/tickets/bulk-delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticket_ids: ids }),
      }),
    reassignResolver: (id: string, expert_email: string, expert_name: string) =>
      request(`/import/tickets/${encodeURIComponent(id)}/reassign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expert_email, expert_name }),
      }),
    aiAccuracy: () => request<{ evaluated: number; correct: number; accuracy_pct: number | null }>('/import/routing/ai-accuracy'),
    reimportTeamworkTicket: (id: string) =>
      request<{ status: string; ticket_id: number; subject: string }>(
        `/import/teamwork/tickets/${encodeURIComponent(id)}/reimport`,
        { method: 'POST' },
      ),
    syncTicket: (id: string) =>
      request<{ status: string }>(
        `/import/teamwork/tickets/${encodeURIComponent(id)}/sync`,
        { method: 'POST' },
      ),
    listStaged: (offset = 0, limit = 50) =>
      request<{ tickets: Ticket[]; total: number }>(`/import/staged?offset=${offset}&limit=${limit}`),
    promoteTicket: (id: string) =>
      request<{ ticket_id: string; ingest_status: string }>(
        `/import/tickets/${encodeURIComponent(id)}/promote`,
        { method: 'POST' },
      ),
  },

  backup: {
    list: () => request<{ filename: string; created_at: string | null; size_kb: number; stats: Record<string, unknown> }[]>('/backup/list'),
    deleteBackup: (filename: string) =>
      fetch(`${BASE}/backup/${encodeURIComponent(filename)}`, { method: 'DELETE' }).then(r => {
        if (!r.ok) throw new Error('Delete failed')
      }),
    downloadUrl: (filename: string) => `${BASE}/backup/download/${encodeURIComponent(filename)}`,
    upload: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return request<{ filename: string; size_kb: number; stats: Record<string, unknown>; created_at: string | null }>('/backup/upload', { method: 'POST', body: form })
    },
    // create and restore use raw fetch (SSE over POST)
    createStream: () => fetch(`${BASE}/backup/create`, { method: 'POST' }),
    restoreStream: (filename: string) => fetch(`${BASE}/backup/restore/${encodeURIComponent(filename)}`, { method: 'POST' }),
  },
}
