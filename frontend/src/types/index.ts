export interface Document {
  id: string
  title: string
  filename: string
  author_email: string | null
  content_hash: string
  page_count: number
  chunk_count: number
  tags: string[]
  experts?: { name: string; email: string }[]
  created_at: string
  processed_at: string | null
  status: 'pending' | 'processing' | 'completed' | 'failed'
  error_message: string | null
  chunks?: DocumentChunk[]
}

export interface DocumentChunk {
  id: string
  // The document-detail endpoint's embedded chunks omit document_id.
  document_id?: string
  page_number: number
  chunk_index: number
  content: string
  token_count: number
}

export interface DocumentUploadResponse {
  id: string
  status: 'processing' | 'completed' | 'failed'
  message: string
}

export interface DocumentStatusEvent {
  id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  progress: number
  message: string | null
}

export interface DocumentExpert {
  name: string
  email: string
}

export interface Ticket {
  id: string
  subject: string
  preview: string
  status: string
  source: string
  source_system?: string
  ticket_type?: string | null
  inbox_name?: string | null
  created_at: string | null
  resolved_at: string | null
  tags: string[]
  agent_name: string | null
  agent_email: string | null
  assigned_to_name?: string | null
  assigned_to_email?: string | null
  client_name: string | null
  client_domain: string | null
  client_display_name: string | null
  content?: string | null
  request_content?: string | null
  request_preview?: string | null
  raw_content?: string | null
  // Routing match (from list query)
  routed_to_name?: string | null
  routed_to_email?: string | null
  is_mismatch?: boolean | null
  // Routing detail (from full ticket query)
  latest_routing_event_id?: string | null
  latest_routing_event_outcome?: string | null
  latest_aura_suggestion_email?: string | null
  latest_aura_suggestion_name?: string | null
  // Routing
  routing_status?: 'unrouted' | 'queued' | 'running' | 'suggested' | 'confirmed' | 'no_recommendation' | 'failed' | null
  aura_routing_error?: string | null
  teamwork_action_error?: string | null
  routing_suggestions?: RouteSuggestion[] | null
  routed_at?: string | null
  confirmed_expert_email?: string | null
  confirmed_expert_name?: string | null
  confirmed_at?: string | null
  is_override?: boolean | null
  aura_suggestion_email?: string | null
  aura_suggestion_confidence?: string | null
  // Ingestion quality gate
  ingest_status?: 'staged' | 'promoted' | null
  staged_reasons?: string[] | null
  gatekeeper_notes?: string | null
  gated_at?: string | null
}

export interface Client {
  // Backend allows a nameless client (display_name is the safe render field).
  name: string | null
  display_name: string
  domain: string
  ticket_count: number
  agents?: string[]
  tickets?: Array<{ id: string; subject: string; status: string; created_at: string | null; source_system: string }>
  parent_domain?: string | null
  parent_name?: string | null
}

export interface User {
  id: string
  email: string
  name: string
  title: string | null
  department: string | null
  manager_name: string | null
  manager_email: string | null
  certifications: string[]
  tickets_resolved?: number
  topics?: string[]
  skills?: string[]
}

export interface AuthoredDocument {
  id?: string | null
  title?: string | null
  status?: string | null
  created_at?: string | null
}

export type TeamworkRoutingMode = 'manual' | 'auto_comment' | 'auto_assign'

export interface TeamworkSyncState {
  source: string
  name: string
  cursor: string
  status?: string | null
  error?: string | null
  last_run_at?: string | null
  processed?: number | null
  imported?: number | null
  updated?: number | null
  protected_skipped?: number | null
  failed?: number | null
}

export interface TeamworkSyncResult {
  processed: number
  imported: number
  updated: number
  protected_skipped: number
  failed: number
  blocked: number
  needs_routing: number
  cursor: string
  status: string
}

export interface TeamworkAutoSyncSettings {
  enabled: boolean
  interval_seconds: 60 | 120 | 300 | 600
}

export interface SearchRequest {
  query: string
  limit?: number
  threshold?: number
}

export interface SearchResult {
  chunk_id: string
  document_id: string
  content: string
  score: number
  page_number: number | null
}

export interface SearchResponse {
  query: string
  results: SearchResult[]
  total: number
}

export interface RouteSuggestion {
  user_id: string
  name: string
  email: string
  tickets_matched: number
  avg_score: number
  topics: string[]
  sample_subjects: string[]
  client_tickets: number
  match_reason: string
}

export interface RouteTask {
  title: string
  skill_area: string
  description: string
  suggestions: RouteSuggestion[]
  similar_tickets_searched: number
}

export interface RouteResponse {
  text: string
  suggestions: RouteSuggestion[]
  tasks: RouteTask[]
  similar_tickets_searched: number
}

export interface ExpertComparison {
  expert_a: { id: string; name: string; email: string }
  expert_b: { id: string; name: string; email: string }
  shared_clients: { name: string | null; count_a: number; count_b: number }[]
  only_a_clients: { name: string | null; count: number }[]
  only_b_clients: { name: string | null; count: number }[]
  shared_skills: string[]
  only_a_skills: string[]
  only_b_skills: string[]
}

export interface AuraAgentToolParameter {
  name: string
  description?: string
  data_type?: string
}

export interface AuraAgentTool {
  name: string
  type: string
  description?: string
  enabled?: boolean
  config?: {
    parameters?: AuraAgentToolParameter[]
    template?: string
    dimension?: number
    index?: string
    model?: string
    provider?: string
    top_k?: number
    [key: string]: unknown
  }
}

export interface AuraAgent {
  id: string
  name: string
  description?: string
  project_id: string
  organization_id: string
  dbid?: string
  enabled?: boolean
  is_private?: boolean
  is_mcp_enabled?: boolean
  endpoint_link?: string
  mcp_endpoint_link?: string
  system_prompt?: string
  tools: AuraAgentTool[]
}

export interface Stats {
  documents: number
  users: number
  tickets: number
  clients: number
}

export interface AskSource {
  chunk_id: string
  document_id: string
  content: string
  score: number
}

export interface AskResponse {
  question: string
  answer: string
  sources: AskSource[]
}

export interface Notification {
  type: string
  message: string
  status: string
  created_at: string
}
