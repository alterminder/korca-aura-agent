import type { Ticket } from '../../types'

type ContentView = 'summary' | 'request' | 'raw'

interface TicketContentViewerProps {
  ticket: Ticket
  contentView: ContentView
  onContentViewChange: (view: ContentView) => void
}

export function TicketContentViewer({ ticket, contentView, onContentViewChange }: TicketContentViewerProps) {
  if (!ticket.content && !ticket.request_content && !ticket.raw_content) return null

  return (
    <div>
      <div className="flex items-center gap-2 mb-1.5">
        {(['summary', 'request', 'raw'] as const).map((view) => {
          const available = view === 'summary'
            ? !!ticket.content
            : view === 'request'
            ? !!ticket.request_content
            : !!ticket.raw_content
          if (!available) return null
          return (
            <button
              key={view}
              onClick={() => onContentViewChange(view)}
              className={`text-xs px-2 py-0.5 rounded transition-colors ${
                contentView === view
                  ? 'bg-app-nav-hover text-app-nav-text font-medium'
                  : 'text-app-nav-text hover:text-slate-950'
              }`}
            >
              {view.charAt(0).toUpperCase() + view.slice(1)}
            </button>
          )
        })}
      </div>
      <div className="bg-app-nav-hover rounded-lg p-4 text-xs text-slate-600 whitespace-pre-wrap leading-relaxed">
        {contentView === 'summary' ? ticket.content : contentView === 'request' ? ticket.request_content : ticket.raw_content}
      </div>
    </div>
  )
}
