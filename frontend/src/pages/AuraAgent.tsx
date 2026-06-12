import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { ChevronDownIcon } from '@heroicons/react/24/outline'
import { api } from '../api/client'
import { AgentPromptEditor } from '../components/aura-agent/AgentPromptEditor'
import { AgentSidebar } from '../components/aura-agent/AgentSidebar'
import type { AuraAgent as AuraAgentType, AuraAgentTool } from '../types'

function AgentSwitch({
  checked,
  disabled,
  label,
  description,
  onChange,
}: {
  checked: boolean
  disabled?: boolean
  label: string
  description: string
  onChange: (checked: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-md border border-app-border px-3 py-3">
      <div className="min-w-0">
        <p className="text-sm font-medium text-slate-950">{label}</p>
        <p className="mt-1 text-xs text-app-nav-text">{description}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        disabled={disabled}
        className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${
          checked ? 'bg-app-accent' : 'bg-app-nav-hover'
        } ${disabled ? 'opacity-60 cursor-not-allowed' : ''}`}
      >
        <span
          className={`inline-block h-5 w-5 rounded-full bg-white transition-transform ${
            checked ? 'translate-x-5' : 'translate-x-0.5'
          }`}
        />
      </button>
    </div>
  )
}

function formatToolType(type: string) {
  return type
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/^./, char => char.toUpperCase())
}

function renderConfigValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  return JSON.stringify(value, null, 2)
}

function ToolPanel({
  tool,
  isOpen,
  onToggle,
  onSave,
  isSaving,
}: {
  tool: AuraAgentTool
  isOpen: boolean
  onToggle: () => void
  onSave: (tool: AuraAgentTool) => void
  isSaving: boolean
}) {
  const config = tool.config ?? {}
  const parameters = config.parameters ?? []
  const configEntries = Object.entries(config).filter(
    ([key]) => key !== 'parameters' && key !== 'template' && key !== 'top_k',
  )
  const [topKDraft, setTopKDraft] = useState(String(config.top_k ?? ''))
  const [templateDraft, setTemplateDraft] = useState(
    typeof config.template === 'string' ? config.template : '',
  )
  const topKValue = Number(topKDraft)
  const canEditTopK = tool.type === 'similaritySearch' && typeof config.top_k === 'number'
  const canEditTemplate = tool.type === 'cypherTemplate' && typeof config.template === 'string'
  const isTopKDirty = canEditTopK && topKValue !== config.top_k
  const isTopKValid = Number.isInteger(topKValue) && topKValue > 0
  const canSaveTopK = isTopKDirty && isTopKValid && !isSaving
  const isTemplateDirty = canEditTemplate && templateDraft !== config.template
  const canSaveTemplate = isTemplateDirty && templateDraft.trim().length > 0 && !isSaving

  useEffect(() => {
    setTopKDraft(String(config.top_k ?? ''))
    setTemplateDraft(typeof config.template === 'string' ? config.template : '')
  }, [config.template, config.top_k])

  function saveTopK() {
    if (!canSaveTopK) return
    onSave({
      ...tool,
      config: {
        ...config,
        top_k: topKValue,
      },
    })
  }

  function saveTemplate() {
    if (!canSaveTemplate) return
    onSave({
      ...tool,
      config: {
        ...config,
        template: templateDraft,
      },
    })
  }

  function toggleEnabled() {
    if (isSaving) return
    onSave({
      ...tool,
      enabled: tool.enabled === false,
    })
  }

  return (
    <section className="bg-app-panel border border-app-border rounded-lg p-5">
      <div className="flex items-start justify-between gap-4">
        <button
          type="button"
          onClick={onToggle}
          className="min-w-0 flex-1 text-left"
          aria-expanded={isOpen}
        >
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-base font-semibold text-slate-950">{tool.name}</h3>
            <span className="px-2 py-0.5 rounded text-xs font-medium bg-app-accent-bg text-app-accent">
              {formatToolType(tool.type)}
            </span>
            {tool.enabled === false && (
              <span className="px-2 py-0.5 rounded text-xs font-medium bg-red-500/10 text-red-300">
                Disabled
              </span>
            )}
          </div>
          {tool.description && (
            <p className="mt-2 text-sm text-app-nav-text">{tool.description}</p>
          )}
        </button>
        <div className="flex items-center gap-3 shrink-0">
          <button
            type="button"
            role="switch"
            aria-checked={tool.enabled !== false}
            onClick={toggleEnabled}
            disabled={isSaving}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              tool.enabled !== false ? 'bg-app-accent' : 'bg-app-nav-hover'
            } ${isSaving ? 'opacity-60 cursor-wait' : ''}`}
            title={tool.enabled === false ? 'Enable tool' : 'Disable tool'}
          >
            <span
              className={`inline-block h-5 w-5 rounded-full bg-white transition-transform ${
                tool.enabled !== false ? 'translate-x-5' : 'translate-x-0.5'
              }`}
            />
          </button>
          <button
            type="button"
            onClick={onToggle}
            className="p-1 text-app-nav-text hover:text-slate-950"
            aria-label={isOpen ? 'Collapse tool' : 'Expand tool'}
          >
            <ChevronDownIcon
              className={`w-5 h-5 transition-transform ${isOpen ? 'rotate-180' : ''}`}
            />
          </button>
        </div>
      </div>

      {isOpen && configEntries.length > 0 && (
        <dl className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
          {configEntries.map(([key, value]) => (
            <div key={key} className="border border-app-border rounded-md px-3 py-2">
              <dt className="text-xs uppercase tracking-wide text-app-nav-text">{key}</dt>
              <dd className="mt-1 text-sm text-slate-700 whitespace-pre-wrap break-words">
                {renderConfigValue(value)}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {isOpen && canEditTopK && (
        <div className="mt-4 border border-app-border rounded-md px-3 py-3">
          <label htmlFor={`${tool.name}-top-k`} className="block text-sm font-semibold text-slate-700">
            top_k
          </label>
          <div className="mt-2 flex items-center gap-3">
            <input
              id={`${tool.name}-top-k`}
              type="number"
              min={1}
              step={1}
              value={topKDraft}
              onChange={event => setTopKDraft(event.target.value)}
              className="w-28 rounded-md bg-slate-50 border border-app-border px-3 py-2 text-sm text-slate-700 outline-none focus:border-app-accent"
            />
            <button
              type="button"
              onClick={saveTopK}
              disabled={!canSaveTopK}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                canSaveTopK
                  ? 'bg-app-accent text-white hover:bg-app-accent/90'
                  : 'bg-app-nav-hover text-app-nav-text cursor-not-allowed'
              }`}
            >
              {isSaving ? 'Saving...' : 'Save'}
            </button>
          </div>
          {!isTopKValid && (
            <p className="mt-2 text-xs text-red-300">top_k must be a positive whole number.</p>
          )}
        </div>
      )}

      {isOpen && parameters.length > 0 && (
        <div className="mt-4">
          <h4 className="text-sm font-semibold text-slate-700 mb-2">Parameters</h4>
          <div className="space-y-2">
            {parameters.map(parameter => (
              <div
                key={parameter.name}
                className="border border-app-border rounded-md px-3 py-2"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium text-slate-950">{parameter.name}</span>
                  {parameter.data_type && (
                    <span className="text-xs text-app-nav-text">{parameter.data_type}</span>
                  )}
                </div>
                {parameter.description && (
                  <p className="mt-1 text-sm text-app-nav-text">{parameter.description}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {isOpen && canEditTemplate && (
        <div className="mt-4">
          <h4 className="text-sm font-semibold text-slate-700 mb-2">Cypher Template</h4>
          <textarea
            value={templateDraft}
            onChange={event => setTemplateDraft(event.target.value)}
            className="w-full min-h-80 resize-y rounded-md bg-slate-50 border border-app-border p-4 text-xs leading-5 text-slate-700 whitespace-pre-wrap outline-none focus:border-app-accent"
            spellCheck={false}
          />
          <div className="mt-4 flex justify-end">
            <button
              type="button"
              onClick={saveTemplate}
              disabled={!canSaveTemplate}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                canSaveTemplate
                  ? 'bg-app-accent text-white hover:bg-app-accent/90'
                  : 'bg-app-nav-hover text-app-nav-text cursor-not-allowed'
              }`}
            >
              {isSaving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}

export function AuraAgent() {
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null)
  const [openToolKey, setOpenToolKey] = useState<string | null>(null)
  const [promptDraft, setPromptDraft] = useState('')
  const queryClient = useQueryClient()

  function updateCachedAgent(updatedAgent: AuraAgentType) {
    queryClient.setQueryData(['aura-agent', updatedAgent.id], updatedAgent)
    queryClient.setQueryData<AuraAgentType[]>(['aura-agents'], current =>
      current?.map(agent => (agent.id === updatedAgent.id ? { ...agent, ...updatedAgent } : agent)),
    )
  }

  const agentsQuery = useQuery({
    queryKey: ['aura-agents'],
    queryFn: api.aura.listAgents,
  })

  useEffect(() => {
    if (!selectedAgentId && agentsQuery.data?.length) {
      setSelectedAgentId(agentsQuery.data[0].id)
    }
  }, [agentsQuery.data, selectedAgentId])

  const agentQuery = useQuery({
    queryKey: ['aura-agent', selectedAgentId],
    queryFn: () => api.aura.getAgent(selectedAgentId as string),
    enabled: Boolean(selectedAgentId),
  })

  const selectedAgent = useMemo<AuraAgentType | undefined>(() => {
    return agentQuery.data ?? agentsQuery.data?.find(agent => agent.id === selectedAgentId)
  }, [agentQuery.data, agentsQuery.data, selectedAgentId])

  useEffect(() => {
    setOpenToolKey(null)
  }, [selectedAgentId])

  useEffect(() => {
    setPromptDraft(selectedAgent?.system_prompt ?? '')
  }, [selectedAgent?.id, selectedAgent?.system_prompt])

  const updatePromptMutation = useMutation({
    mutationFn: ({ agentId, systemPrompt }: { agentId: string; systemPrompt: string }) =>
      api.aura.updateAgent(agentId, { system_prompt: systemPrompt }),
    onSuccess: updatedAgent => {
      updateCachedAgent(updatedAgent)
      setPromptDraft(updatedAgent.system_prompt ?? '')
      toast.success('Aura agent prompt saved')
    },
    onError: error => {
      toast.error(error instanceof Error ? error.message : 'Failed to save Aura agent prompt')
    },
  })

  const updateToolsMutation = useMutation({
    mutationFn: ({ agentId, tools }: { agentId: string; tools: AuraAgentTool[] }) =>
      api.aura.updateAgent(agentId, { tools }),
    onSuccess: updatedAgent => {
      updateCachedAgent(updatedAgent)
      toast.success('Aura agent tool saved')
    },
    onError: error => {
      toast.error(error instanceof Error ? error.message : 'Failed to save Aura agent tool')
    },
  })

  const updateAccessMutation = useMutation({
    mutationFn: ({
      agentId,
      isPrivate,
      isMcpEnabled,
    }: {
      agentId: string
      isPrivate?: boolean
      isMcpEnabled?: boolean
    }) => api.aura.updateAgent(agentId, { is_private: isPrivate, is_mcp_enabled: isMcpEnabled }),
    onSuccess: updatedAgent => {
      updateCachedAgent(updatedAgent)
      toast.success('Aura agent access updated')
    },
    onError: error => {
      toast.error(error instanceof Error ? error.message : 'Failed to update Aura agent access')
    },
  })

  const savedPrompt = selectedAgent?.system_prompt ?? ''
  const isPromptDirty = promptDraft !== savedPrompt
  const canSavePrompt =
    Boolean(selectedAgentId) && isPromptDirty && promptDraft.trim().length > 0 && !updatePromptMutation.isPending

  function handleSavePrompt() {
    if (!selectedAgentId || !canSavePrompt) return
    updatePromptMutation.mutate({ agentId: selectedAgentId, systemPrompt: promptDraft })
  }

  function handleSaveTool(toolIndex: number, updatedTool: AuraAgentTool) {
    if (!selectedAgentId || !selectedAgent) return
    const tools = selectedAgent.tools.map((tool, index) =>
      index === toolIndex ? updatedTool : tool,
    )
    updateToolsMutation.mutate({ agentId: selectedAgentId, tools })
  }

  function handlePrivateChange(isPrivate: boolean) {
    if (!selectedAgentId || updateAccessMutation.isPending) return
    updateAccessMutation.mutate({
      agentId: selectedAgentId,
      isPrivate,
      isMcpEnabled: isPrivate ? false : selectedAgent?.is_mcp_enabled,
    })
  }

  function handleMcpChange(isMcpEnabled: boolean) {
    if (!selectedAgentId || selectedAgent?.is_private || updateAccessMutation.isPending) return
    updateAccessMutation.mutate({ agentId: selectedAgentId, isMcpEnabled })
  }

  return (
    <div>
<div className="flex items-start justify-between gap-6 mb-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-950 mb-2">Aura Agent</h1>
          <p className="text-app-nav-text">Neo4j Aura-hosted agents and their retrieval tools.</p>
        </div>
      </div>

      {agentsQuery.isLoading && (
        <div className="bg-app-panel border border-app-border rounded-lg p-6 text-app-nav-text">
          Loading agents…
        </div>
      )}

      {agentsQuery.error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-200">
          {(agentsQuery.error as Error).message}
        </div>
      )}

      {agentsQuery.data && agentsQuery.data.length === 0 && (
        <div className="bg-app-panel border border-app-border rounded-lg p-6 text-app-nav-text">
          No Aura agents found.
        </div>
      )}

      {agentsQuery.data && agentsQuery.data.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6">
          <AgentSidebar
            agents={agentsQuery.data}
            selectedAgentId={selectedAgentId}
            onSelect={setSelectedAgentId}
          />

          <div className="min-w-0 space-y-5">
            {agentQuery.isFetching && !agentQuery.data && (
              <div className="bg-app-panel border border-app-border rounded-lg p-6 text-app-nav-text">
                Loading agent details…
              </div>
            )}

            {agentQuery.error && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-200">
                {(agentQuery.error as Error).message}
              </div>
            )}

            {selectedAgent && (
              <>
                <section className="bg-app-panel border border-app-border rounded-lg p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <h2 className="text-xl font-semibold text-slate-950">{selectedAgent.name}</h2>
                      {selectedAgent.description && (
                        <p className="mt-1 text-sm text-app-nav-text">{selectedAgent.description}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-app-nav-text shrink-0">
                      {selectedAgent.enabled !== false && <span>Enabled</span>}
                      <span>{selectedAgent.is_private === false ? 'Public' : 'Private'}</span>
                      {selectedAgent.is_mcp_enabled && <span>MCP</span>}
                    </div>
                  </div>

                  <dl className="mt-5 grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div className="border border-app-border rounded-md px-3 py-2">
                      <dt className="text-xs uppercase tracking-wide text-app-nav-text">Agent ID</dt>
                      <dd className="mt-1 text-sm text-slate-700 break-all">{selectedAgent.id}</dd>
                    </div>
                    <div className="border border-app-border rounded-md px-3 py-2">
                      <dt className="text-xs uppercase tracking-wide text-app-nav-text">Database</dt>
                      <dd className="mt-1 text-sm text-slate-700">{selectedAgent.dbid ?? '—'}</dd>
                    </div>
                  </dl>

                  <div className="mt-5 grid grid-cols-1 md:grid-cols-2 gap-3">
                    <AgentSwitch
                      checked={selectedAgent.is_private === false}
                      disabled={updateAccessMutation.isPending}
                      label="Public"
                      description="Expose the agent externally. REST and MCP links are accessible."
                      onChange={(isPublic) => handlePrivateChange(!isPublic)}
                    />
                    <AgentSwitch
                      checked={selectedAgent.is_mcp_enabled === true}
                      disabled={selectedAgent.is_private === true || updateAccessMutation.isPending}
                      label="MCP"
                      description={
                        selectedAgent.is_private === true
                          ? 'MCP is only available when the agent is public.'
                          : 'Expose the agent through the Aura MCP endpoint.'
                      }
                      onChange={handleMcpChange}
                    />
                  </div>
                </section>

                <AgentPromptEditor
                  value={promptDraft}
                  onChange={setPromptDraft}
                  canSave={canSavePrompt}
                  isSaving={updatePromptMutation.isPending}
                  onSave={handleSavePrompt}
                />

                <div className="space-y-4">
                  <h3 className="text-base font-semibold text-slate-950">
                    Tools ({selectedAgent.tools.length})
                  </h3>
                  {selectedAgent.tools.map((tool, index) => {
                    const toolKey = `${tool.name}-${tool.type}`
                    return (
                      <ToolPanel
                        key={toolKey}
                        tool={tool}
                        isOpen={openToolKey === toolKey}
                        onToggle={() =>
                          setOpenToolKey(current => (current === toolKey ? null : toolKey))
                        }
                        onSave={updatedTool => handleSaveTool(index, updatedTool)}
                        isSaving={updateToolsMutation.isPending}
                      />
                    )
                  })}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
