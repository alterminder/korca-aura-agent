import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { TrashIcon, XMarkIcon } from '@heroicons/react/24/outline'
import { api } from '../../api/client'
import type { TeamworkAutoSyncSettings, TeamworkRoutingMode, TeamworkSyncState } from '../../types'

interface BackupEntry {
  filename: string
  created_at: string | null
  size_kb: number
  stats: Record<string, unknown>
}

export interface SettingsDrawerProps {
  onClose: () => void
  importing: boolean
  syncing: boolean
  syncState: TeamworkSyncState | null | undefined
  autoSync: TeamworkAutoSyncSettings | undefined
  onSaveAutoSync: (settings: TeamworkAutoSyncSettings) => void
  savingAutoSync: boolean
  onPurgeBlocked: (prefix?: string, block?: boolean) => void
  onClear: () => void
}

const ROUTING_MODE_OPTIONS: Array<{ mode: TeamworkRoutingMode; label: string; description: string }> = [
  { mode: 'manual', label: 'Manual', description: 'Store Aura suggestion in Korca.' },
  { mode: 'auto_comment', label: 'Private note', description: 'Post an internal Teamwork note.' },
  { mode: 'auto_assign', label: 'Auto assign', description: 'Assign Aura expert in Teamwork.' },
]

const AUTO_SYNC_INTERVALS: Array<{ label: string; value: TeamworkAutoSyncSettings['interval_seconds'] }> = [
  { label: '1 min', value: 60 },
  { label: '2 min', value: 120 },
  { label: '5 min', value: 300 },
  { label: '10 min', value: 600 },
]

function parseSseStream(body: ReadableStream<Uint8Array>, onEvent: (ev: Record<string, unknown>) => void): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  async function pump(): Promise<void> {
    const { done, value } = await reader.read()
    if (done) return
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try { onEvent(JSON.parse(line.slice(6))) } catch { /* skip */ }
      }
    }
    return pump()
  }
  return pump()
}

function PurgePreviewModal({
  preview,
  prefix,
  onConfirm,
  onConfirmAndBlock,
  onClose,
}: {
  preview: { count: number; samples: string[]; filter: string }
  prefix: string
  onConfirm: () => void
  onConfirmAndBlock: () => void
  onClose: () => void
}) {
  return (
    <>
      <button type="button" aria-label="Close drawer" className="fixed inset-0 bg-black/70 z-60 cursor-default" onClick={onClose} />
      <div className="fixed inset-0 flex items-center justify-center z-60 p-[10vh_10vw]" style={{ pointerEvents: 'none' }}>
        <div className="w-[80vw] h-[80vh] bg-app-drawer border border-app-border rounded-xl shadow-2xl flex flex-col" style={{ pointerEvents: 'auto' }}>
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-app-border shrink-0">
            <div>
              <h2 className="text-base font-semibold text-slate-950">
                {preview.count === 0 ? 'Nothing to purge' : `${preview.count} ticket${preview.count !== 1 ? 's' : ''} will be permanently deleted`}
              </h2>
              <p className="text-xs text-app-nav-text mt-0.5">Filter: {preview.filter}</p>
            </div>
            <button onClick={onClose} className="text-app-nav-text hover:text-slate-950 shrink-0">
              <XMarkIcon className="w-5 h-5" />
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto px-6 py-4">
            {preview.count === 0 ? (
              <div className="flex items-center justify-center h-full">
                <p className="text-app-nav-text text-sm">No tickets match the prefix <span className="text-slate-950 font-mono">"{prefix}"</span>.</p>
              </div>
            ) : (
              <ul className="space-y-1">
                {preview.samples.map((s, i) => (
                  <li key={i} className="flex items-start gap-3 py-1.5 border-b border-app-border/50 last:border-0">
                    <span className="text-app-nav-text/40 text-xs shrink-0 mt-0.5 w-8 text-right">{i + 1}</span>
                    <span className="text-sm text-slate-600">{s}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-app-border shrink-0 space-y-3">
            {preview.count > 0 && (
              <p className="text-xs text-app-nav-text">
                <span className="font-medium text-slate-950">Delete</span> removes tickets from Korca, they will be re-synced from Teamwork on the next sync.{' '}
                <span className="font-medium text-slate-950">Delete & Block</span> removes them permanently, prevents re-import.
              </p>
            )}
            <div className="flex items-center justify-between">
              <button onClick={onClose} className="px-4 py-1.5 text-sm font-normal border border-slate-950/30 text-slate-950 bg-transparent rounded-full hover:bg-slate-950/5 transition-colors">
                Cancel
              </button>
              {preview.count > 0 && (
                <div className="flex gap-2">
                  <button
                    onClick={onConfirm}
                    className="px-4 py-1.5 text-sm font-normal border border-slate-950/30 text-slate-950 bg-transparent rounded-full hover:bg-slate-950/5 transition-colors"
                  >
                    Delete {preview.count} ticket{preview.count !== 1 ? 's' : ''}
                  </button>
                  <button
                    onClick={onConfirmAndBlock}
                    className="px-4 py-1.5 text-sm font-normal bg-neutral-950 text-white rounded-full hover:bg-neutral-800 transition-colors"
                  >
                    Delete & Block
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

export function SettingsDrawer({
  onClose,
  importing,
  syncing,
  syncState,
  autoSync,
  onSaveAutoSync,
  savingAutoSync,
  onPurgeBlocked,
  onClear,
}: SettingsDrawerProps) {
  const queryClient = useQueryClient()
  const [purgePrefix, setPurgePrefix] = useState('job: ')
  const [purgePreview, setPurgePreview] = useState<{ count: number; samples: string[]; filter: string } | null>(null)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [clearConfirmText, setClearConfirmText] = useState('')

  // Backup state
  const [backups, setBackups] = useState<BackupEntry[] | null>(null)
  const [backupsLoading, setBackupsLoading] = useState(false)
  const [backingUp, setBackingUp] = useState(false)
  const [backupMessage, setBackupMessage] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [restoreTarget, setRestoreTarget] = useState<string | null>(null)
  const [restoreConfirmText, setRestoreConfirmText] = useState('')
  const [restoreMessage, setRestoreMessage] = useState<string | null>(null)
  const uploadInputRef = useRef<HTMLInputElement>(null)

  const { data: routingMode } = useQuery({
    queryKey: ['teamwork-routing-mode'],
    queryFn: api.import.teamworkRoutingMode,
  })

  const saveRoutingMode = useMutation({
    mutationFn: api.import.setTeamworkRoutingMode,
    onSuccess: (data) => {
      queryClient.setQueryData(['teamwork-routing-mode'], data)
    },
  })

  async function loadBackups() {
    setBackupsLoading(true)
    try {
      const list = await api.backup.list()
      setBackups(list)
    } finally {
      setBackupsLoading(false)
    }
  }

  async function handleCreateBackup() {
    if (backingUp) return
    setBackingUp(true)
    setBackupMessage('Starting backup…')
    try {
      const res = await api.backup.createStream()
      if (!res.ok || !res.body) throw new Error('Request failed')
      await parseSseStream(res.body, (ev) => {
        if (ev.event === 'progress') setBackupMessage(ev.message as string)
        if (ev.event === 'done') {
          setBackupMessage(`Saved: ${(ev.stats as Record<string, unknown>)?.tickets ?? 0} tickets, ${ev.size_kb} KB`)
          loadBackups()
        }
        if (ev.event === 'error') setBackupMessage(`Error: ${ev.message}`)
      })
    } catch (err) {
      setBackupMessage(`Failed: ${String(err)}`)
    } finally {
      setBackingUp(false)
    }
  }

  async function handleRestoreConfirm() {
    if (!restoreTarget || restoring) return
    setRestoring(true)
    setRestoreMessage('Starting restore…')
    try {
      const res = await api.backup.restoreStream(restoreTarget)
      if (!res.ok || !res.body) throw new Error('Request failed')
      await parseSseStream(res.body, (ev) => {
        if (ev.event === 'progress') setRestoreMessage(ev.message as string)
        if (ev.event === 'done') setRestoreMessage('Restore complete.')
        if (ev.event === 'error') setRestoreMessage(`Error: ${ev.message}`)
      })
    } catch (err) {
      setRestoreMessage(`Failed: ${String(err)}`)
    } finally {
      setRestoring(false)
      setRestoreTarget(null)
      setRestoreConfirmText('')
    }
  }

  async function handleDeleteBackup(filename: string) {
    if (!confirm(`Delete backup ${filename}?`)) return
    await api.backup.deleteBackup(filename)
    loadBackups()
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    setUploading(true)
    setBackupMessage(`Uploading ${file.name}…`)
    try {
      await api.backup.upload(file)
      setBackupMessage(`Uploaded ${file.name}`)
      loadBackups()
    } catch (err) {
      setBackupMessage(`Upload failed: ${String(err)}`)
    } finally {
      setUploading(false)
    }
  }

  async function loadPurgePreview() {
    setLoadingPreview(true)
    setPurgePreview(null)
    try {
      const res = await api.import.purgeBlockedPreview(purgePrefix.trim() || undefined)
      setPurgePreview(res)
    } finally {
      setLoadingPreview(false)
    }
  }

  function handlePurgeConfirm(block = false) {
    setPurgePreview(null)
    onPurgeBlocked(purgePrefix.trim() || undefined, block)
  }

  return (
    <>
      {purgePreview && (
        <PurgePreviewModal
          preview={purgePreview}
          prefix={purgePrefix}
          onConfirm={() => handlePurgeConfirm(false)}
          onConfirmAndBlock={() => handlePurgeConfirm(true)}
          onClose={() => setPurgePreview(null)}
        />
      )}
      <button type="button" aria-label="Close drawer" className="fixed inset-0 bg-black/50 z-40 cursor-default" onClick={onClose} />
      <div className="fixed top-0 right-0 h-full w-full max-w-md bg-app-drawer border-l border-app-border shadow-2xl z-50 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-app-border shrink-0">
          <h2 className="text-sm font-semibold text-slate-950">Teamwork Settings</h2>
          <button onClick={onClose} className="text-app-nav-text hover:text-slate-950">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          {/* Routing mode */}
          <section className="space-y-3">
            <div>
              <p className="text-xs font-semibold text-app-nav-text uppercase tracking-wider">Routing Mode</p>
            </div>
            <div className="grid grid-cols-3 gap-1 rounded-lg border border-app-border bg-app-nav-hover p-1">
              {ROUTING_MODE_OPTIONS.map(option => {
                const active = (routingMode?.mode ?? 'manual') === option.mode
                return (
                  <button
                    key={option.mode}
                    type="button"
                    onClick={() => saveRoutingMode.mutate(option.mode)}
                    disabled={importing || syncing || saveRoutingMode.isPending}
                    className={`min-h-16 rounded-md px-2 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
                      active ? 'bg-app-panel text-slate-950 shadow-sm' : 'text-app-nav-text hover:text-slate-950'
                    }`}
                    title={option.description}
                  >
                    <span className="block text-xs font-semibold">{option.label}</span>
                    <span className="mt-1 block text-[11px] leading-tight opacity-75">{option.description}</span>
                  </button>
                )
              })}
            </div>
            {saveRoutingMode.isError && (
              <p className="text-xs text-red-400">Could not save routing mode.</p>
            )}
          </section>

          {/* Update sync */}
          <section className="space-y-3">
            <div>
              <p className="text-xs font-semibold text-app-nav-text uppercase tracking-wider">Update Sync</p>
            </div>
            <div className="rounded-lg border border-app-border p-3 space-y-2">
              {syncState?.last_run_at && (
                <p className="text-xs text-app-nav-text">
                  Last sync {new Date(syncState.last_run_at).toLocaleString()}
                </p>
              )}
              {syncState?.error && (
                <p className="text-xs text-red-400">{syncState.error}</p>
              )}
              <div className="flex items-center justify-between gap-3">
                <label className="flex items-center gap-2 text-sm text-slate-950">
                  <input
                    type="checkbox"
                    checked={autoSync?.enabled ?? false}
                    onChange={e => onSaveAutoSync({
                      enabled: e.target.checked,
                      interval_seconds: autoSync?.interval_seconds ?? 60,
                    })}
                    disabled={importing || syncing || savingAutoSync}
                    className="h-4 w-4 rounded border-app-border text-app-accent focus:ring-app-accent"
                  />
                  Auto sync
                </label>
                <select
                  value={autoSync?.interval_seconds ?? 60}
                  onChange={e => onSaveAutoSync({
                    enabled: autoSync?.enabled ?? false,
                    interval_seconds: Number(e.target.value) as TeamworkAutoSyncSettings['interval_seconds'],
                  })}
                  disabled={importing || syncing || savingAutoSync}
                  className="text-sm px-2 py-1.5 border border-app-border rounded-lg bg-app-bg text-slate-950 focus:outline-none focus:ring-2 focus:ring-app-accent"
                >
                  {AUTO_SYNC_INTERVALS.map(option => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </div>
            </div>
          </section>

          {/* Backups */}
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold text-app-nav-text uppercase tracking-wider">Backups</p>
                <p className="text-xs text-app-nav-text mt-0.5">Export a full graph snapshot. Restore uses MERGE — never deletes existing data.</p>
              </div>
              {backups === null && !backupsLoading && (
                <button onClick={loadBackups} className="text-xs text-app-accent hover:underline shrink-0">Load</button>
              )}
            </div>

            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-950">Create backup</p>
                <p className="text-xs text-app-nav-text mt-0.5">Exports tickets, users, clients, and relationships to a backup archive on the server.</p>
                {backupMessage && <p className="text-xs text-app-accent mt-1">{backupMessage}</p>}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <input
                  ref={uploadInputRef}
                  type="file"
                  accept=".tar.gz,application/gzip,application/x-gzip"
                  className="hidden"
                  onChange={handleUpload}
                />
                <button
                  onClick={() => uploadInputRef.current?.click()}
                  disabled={backingUp || restoring || uploading}
                  className="px-4 py-1.5 text-sm font-normal border border-slate-950/30 text-slate-950 bg-transparent rounded-full hover:bg-slate-950/5 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {uploading ? 'Uploading…' : 'Upload'}
                </button>
                <button
                  onClick={handleCreateBackup}
                  disabled={backingUp || restoring || uploading}
                  className="px-4 py-1.5 text-sm font-normal bg-neutral-950 text-white rounded-full hover:bg-neutral-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {backingUp ? 'Saving…' : 'Create'}
                </button>
              </div>
            </div>

            {backupsLoading && <p className="text-xs text-app-nav-text">Loading…</p>}

            {backups !== null && backups.length === 0 && (
              <p className="text-xs text-app-nav-text">No backups yet.</p>
            )}

            {backups !== null && backups.length > 0 && (
              <div className="space-y-2">
                {backups.map(b => (
                  <div key={b.filename} className="rounded-lg border border-app-border p-3 space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-xs text-slate-950 font-mono truncate">{b.filename}</p>
                        <p className="text-xs text-app-nav-text mt-0.5">
                          {(b.stats?.tickets as number) ?? '?'} tickets · {b.size_kb} KB
                          {b.created_at ? ` · ${new Date(b.created_at).toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })}` : ''}
                        </p>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <a
                          href={api.backup.downloadUrl(b.filename)}
                          download
                          className="px-3 py-1 text-xs font-normal border border-slate-950/30 text-slate-950 bg-transparent rounded-full hover:bg-slate-950/5 transition-colors"
                        >
                          Download
                        </a>
                        <button
                          onClick={() => { setRestoreTarget(b.filename); setRestoreConfirmText(''); setRestoreMessage(null) }}
                          disabled={backingUp || restoring}
                          className="px-3 py-1 text-xs font-normal bg-neutral-950 text-white rounded-full hover:bg-neutral-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                          Restore
                        </button>
                        <button
                          onClick={() => handleDeleteBackup(b.filename)}
                          disabled={backingUp || restoring}
                          className="text-slate-950 bg-transparent rounded-full p-1 hover:bg-slate-950/5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                          title="Delete backup file"
                        >
                          <TrashIcon className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>

                    {restoreTarget === b.filename && (
                      <div className="pt-2 border-t border-app-border space-y-2">
                        <p className="text-xs text-amber-400">
                          Replays backup using MERGE — will not delete existing data. Type <span className="font-mono font-bold">RESTORE</span> to confirm:
                        </p>
                        <input
                          type="text"
                          value={restoreConfirmText}
                          onChange={e => setRestoreConfirmText(e.target.value)}
                          placeholder="RESTORE"
                          className="w-full text-sm px-2 py-1.5 border border-amber-800/50 rounded-lg bg-app-bg text-slate-950 placeholder-app-nav-text focus:outline-none focus:ring-2 focus:ring-amber-500 font-mono"
                          autoFocus
                        />
                        {restoreMessage && <p className="text-xs text-amber-400">{restoreMessage}</p>}
                        <div className="flex gap-2">
                          <button
                            onClick={handleRestoreConfirm}
                            disabled={restoreConfirmText !== 'RESTORE' || restoring}
                            className="px-3 py-1.5 text-xs font-medium text-amber-400 border border-amber-800/50 rounded-lg hover:bg-amber-900/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                          >
                            {restoring ? 'Restoring…' : 'Confirm restore'}
                          </button>
                          <button
                            onClick={() => { setRestoreTarget(null); setRestoreConfirmText(''); setRestoreMessage(null) }}
                            className="text-xs text-app-nav-text hover:text-slate-950"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          <div className="border-t border-app-border" />

          {/* Maintenance — danger zone */}
          <section className="space-y-3">
            <div>
              <p className="text-xs font-semibold text-red-400/70 uppercase tracking-wider">Maintenance</p>
              <p className="text-xs text-app-nav-text mt-0.5">Destructive operations. Review carefully before running.</p>
            </div>
            <div className="space-y-3">

              {/* Purge blocked */}
              <div className="rounded-lg border border-app-border p-3 space-y-3">
                <div>
                  <p className="text-sm font-medium text-slate-950">Purge tickets by subject prefix</p>
                  <p className="text-xs text-app-nav-text mt-0.5">Permanently deletes all tickets whose subject starts with the given prefix. Preview first to see exactly what will be removed.</p>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={purgePrefix}
                    onChange={e => { setPurgePrefix(e.target.value); setPurgePreview(null) }}
                    placeholder='e.g. "job: "'
                    className="flex-1 text-sm px-2 py-1.5 border border-app-border rounded-lg bg-app-bg text-slate-950 placeholder-app-nav-text focus:outline-none focus:ring-2 focus:ring-app-accent font-mono"
                  />
                  <button
                    onClick={loadPurgePreview}
                    disabled={loadingPreview || importing || !purgePrefix.trim()}
                    className="shrink-0 px-4 py-1.5 text-sm font-normal border border-slate-950/30 text-slate-950 bg-transparent rounded-full hover:bg-slate-950/5 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    {loadingPreview ? 'Loading…' : 'Preview'}
                  </button>
                </div>

              </div>

              {/* Clear tickets */}
              <div className="rounded-lg border border-red-900/30 bg-red-900/5 p-3 space-y-3">
                <p className="text-sm font-medium text-slate-950">Clear tickets</p>
                <p className="text-xs text-app-nav-text">
                  Drops all tickets from the knowledge graph. All routing history will be permanently lost. You can re-import from the tickets page afterwards.
                </p>
                {!showClearConfirm ? (
                  <button
                    onClick={() => { setShowClearConfirm(true); setClearConfirmText('') }}
                    disabled={importing}
                    className="px-5 py-2 text-sm font-normal bg-neutral-950 text-white rounded-full hover:bg-neutral-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    Clear all tickets
                  </button>
                ) : (
                  <div className="space-y-2 pt-1 border-t border-red-900/30">
                    <p className="text-xs text-red-400">Type <span className="font-mono font-bold">CLEAR</span> to confirm:</p>
                    <input
                      type="text"
                      value={clearConfirmText}
                      onChange={e => setClearConfirmText(e.target.value)}
                      placeholder="CLEAR"
                      className="w-full text-sm px-2 py-1.5 border border-red-900/50 rounded-lg bg-app-bg text-slate-950 placeholder-app-nav-text focus:outline-none focus:ring-2 focus:ring-red-500 font-mono"
                      autoFocus
                    />
                    <div className="flex gap-2">
                      <button
                        onClick={() => { setShowClearConfirm(false); setClearConfirmText(''); onClear() }}
                        disabled={clearConfirmText !== 'CLEAR' || importing}
                        className="px-3 py-1.5 text-xs font-normal bg-neutral-950 text-white rounded-full hover:bg-neutral-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        Confirm — clear all tickets
                      </button>
                      <button
                        onClick={() => { setShowClearConfirm(false); setClearConfirmText('') }}
                        className="text-xs text-app-nav-text hover:text-slate-950"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>

            </div>
          </section>
        </div>
      </div>
    </>
  )
}
