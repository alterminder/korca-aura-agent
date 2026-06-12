import { useMemo, useState } from 'react'

type AuraStreamEvent = {
  type: string
  text?: string
  thinking?: string
  name?: string
  input?: unknown
  output?: unknown
  tool_use_id?: string
  error?: { message?: string; type?: string; status_code?: number }
  status?: string
  usage?: {
    request_tokens?: number
    response_tokens?: number
    total_tokens?: number
  }
}

function parseSseFrame(frame: string): AuraStreamEvent | null {
  const data = frame
    .split('\n')
    .filter(line => line.startsWith('data:'))
    .map(line => line.slice(5).trimStart())
    .join('\n')
    .trim()

  if (!data || data === '[DONE]') return null
  return JSON.parse(data) as AuraStreamEvent
}

function EventPanel({ event }: { event: AuraStreamEvent }) {
  if (event.type === 'text') {
    return (
      <div className="rounded-lg border border-app-border bg-app-panel p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-app-accent mb-2">Answer</p>
        <p className="text-sm text-slate-800 whitespace-pre-wrap">{event.text}</p>
      </div>
    )
  }

  if (event.type === 'thinking') {
    return (
      <div className="rounded-lg border border-teal-500/30 bg-teal-500/10 p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-teal-300 mb-2">Thinking</p>
        <p className="text-sm text-slate-800 whitespace-pre-wrap">{event.thinking}</p>
      </div>
    )
  }

  if (event.type === 'done') {
    return (
      <div className="rounded-lg border border-green-500/30 bg-green-500/10 p-4">
        <p className="text-sm font-medium text-green-300">Completed</p>
        {event.usage && (
          <p className="mt-1 text-xs text-app-nav-text">
            Tokens: {event.usage.total_tokens ?? '—'} total
          </p>
        )}
      </div>
    )
  }

  if (event.type === 'error') {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4">
        <p className="text-sm font-medium text-red-300">{event.error?.message ?? 'Aura error'}</p>
      </div>
    )
  }

  const title = event.name ? `${event.type}: ${event.name}` : event.type
  return (
    <details className="rounded-lg border border-app-border bg-app-panel p-4" open>
      <summary className="cursor-pointer text-sm font-medium text-slate-950">{title}</summary>
      <pre className="mt-3 max-h-80 overflow-auto rounded-md bg-slate-50 border border-app-border p-3 text-xs leading-5 text-slate-700 whitespace-pre-wrap">
        {JSON.stringify(event, null, 2)}
      </pre>
    </details>
  )
}

export function RoutingPlayground() {
  const [text, setText] = useState('')
  const [clientName, setClientName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [events, setEvents] = useState<AuraStreamEvent[]>([])

  const answerText = useMemo(
    () => events.filter(event => event.type === 'text').map(event => event.text ?? '').join(''),
    [events],
  )

  async function handleRoute() {
    if (!text.trim()) return
    setLoading(true)
    setError(null)
    setEvents([])

    try {
      // Raw fetch (not the api client / react-query): this is an SSE stream read
      // via the body reader below — react-query doesn't model streaming responses.
      const res = await fetch('/api/aura/invoke-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text.trim(), client_name: clientName.trim() }),
      })

      if (!res.ok || !res.body) {
        const body = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error((body as { detail?: string }).detail ?? 'Aura streaming failed')
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let done = false

      while (!done) {
        const result = await reader.read()
        done = result.done
        const value = result.value
        buffer += decoder.decode(value, { stream: !done })
        const frames = buffer.split('\n\n')
        buffer = frames.pop() ?? ''

        for (const frame of frames) {
          const event = parseSseFrame(frame)
          if (!event) continue
          setEvents(current => [...current, event])
          if (event.type === 'error') {
            throw new Error(event.error?.message ?? 'Aura streaming failed')
          }
        }

      }

      const finalEvent = parseSseFrame(buffer)
      if (finalEvent) setEvents(current => [...current, finalEvent])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Aura streaming failed')
    } finally {
      setLoading(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleRoute()
  }

  const inputCls = "rounded border border-app-border bg-app-panel text-slate-950 placeholder-app-nav-text px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-app-accent"

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h1 className="text-2xl font-bold text-slate-950">Routing Sandbox</h1>
        <p className="text-sm text-app-nav-text mt-1">
          Stream the ticket through the Neo4j Aura Agent and inspect its live reasoning trace.
        </p>
      </div>

      <div className="space-y-3">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={7}
          placeholder={`Paste ticket content here.\n\nExample:\nSubject: Elementor Pro contact form not sending emails\nDescription: The contact form on the homepage stopped sending email notifications after the last plugin update. Tested with multiple browsers. No errors in console.`}
          className="w-full rounded-lg border border-app-border bg-app-panel px-4 py-3 text-sm text-slate-950 placeholder-app-nav-text focus:outline-none focus:ring-2 focus:ring-app-accent resize-none"
        />

        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2 text-sm text-app-nav-text">
            <label htmlFor="client">Client</label>
            <input
              id="client"
              type="text"
              placeholder="e.g. Acme Corp (optional)"
              value={clientName}
              onChange={(e) => setClientName(e.target.value)}
              className={`w-56 ${inputCls}`}
            />
          </div>
          <button
            onClick={handleRoute}
            disabled={loading || !text.trim()}
            className="ml-auto px-5 py-2 rounded-lg bg-app-accent text-app-bg text-sm font-medium hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
          >
            {loading ? 'Streaming...' : 'Run Agent'}
          </button>
        </div>
        <p className="text-xs text-app-nav-text">Tip: Cmd/Ctrl+Enter to run</p>
      </div>

      {error && (
        <div className="rounded-lg bg-red-900/20 border border-red-900/50 px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {(loading || events.length > 0) && (
        <div className="space-y-4">
          {answerText && (
            <div className="rounded-lg border border-app-accent/30 bg-app-accent-bg p-4">
              <p className="text-xs font-medium uppercase tracking-wide text-app-accent mb-2">Live Answer</p>
              <p className="text-sm text-slate-800 whitespace-pre-wrap">{answerText}</p>
            </div>
          )}

          <div className="space-y-3">
            <h2 className="text-sm font-semibold text-slate-950">Stream Events</h2>
            {events.map((event, index) => (
              <EventPanel key={index} event={event} />
            ))}
            {loading && events.length === 0 && (
              <div className="bg-app-panel rounded-lg border border-app-border p-4 animate-pulse">
                <div className="h-4 bg-app-nav-hover rounded w-1/3" />
                <div className="mt-3 h-3 bg-app-nav-hover rounded w-2/3" />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
