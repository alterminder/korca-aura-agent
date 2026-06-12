import { Link } from 'react-router-dom'

export function Integrations() {
  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-950 mb-2">Integrations</h1>
      <p className="text-app-nav-text mb-8">Connect external sources to build your knowledge graph.</p>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <Link
          to="/integrations/teamwork"
          className="bg-app-panel rounded-lg border border-app-border p-6 flex flex-col items-center gap-4 hover:border-app-accent/50 transition-colors"
        >
          <img
            src="/teamwork-desk.svg"
            alt="Teamwork Desk"
            className="object-contain"
          />
          <span className="text-sm font-medium text-slate-600">Teamwork Desk</span>
        </Link>
      </div>
    </div>
  )
}
