import { CircleStackIcon } from '@heroicons/react/24/outline'
import type { AuraAgent } from '../../types'

interface AgentSidebarProps {
  agents: AuraAgent[]
  selectedAgentId: string | null
  onSelect: (agentId: string) => void
}

export function AgentSidebar({ agents, selectedAgentId, onSelect }: AgentSidebarProps) {
  return (
    <aside className="space-y-2">
      {agents.map(agent => {
        const isSelected = agent.id === selectedAgentId
        return (
          <button
            key={agent.id}
            type="button"
            onClick={() => onSelect(agent.id)}
            className={`w-full text-left rounded-lg border px-4 py-3 transition-colors ${
              isSelected
                ? 'border-app-accent bg-app-accent-bg'
                : 'border-app-border bg-app-panel hover:border-app-accent/50'
            }`}
          >
            <div className="flex items-center gap-2">
              <CircleStackIcon className="w-4 h-4 text-app-accent shrink-0" />
              <span className="text-sm font-semibold text-slate-950 truncate">{agent.name}</span>
            </div>
            {agent.description && (
              <p className="mt-1 text-xs text-app-nav-text line-clamp-2">
                {agent.description}
              </p>
            )}
            <div className="mt-3 flex items-center gap-2 text-xs text-app-nav-text">
              <span>{agent.tools.length} tools</span>
              {agent.is_mcp_enabled && <span>MCP</span>}
              {agent.enabled === false && <span>Disabled</span>}
            </div>
          </button>
        )
      })}
    </aside>
  )
}
