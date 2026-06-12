import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ImportTeamwork } from '../pages/ImportTeamwork'
import { api } from '../api/client'

vi.mock('../api/client', () => ({
  api: {
    users: {
      list: vi.fn(),
    },
    import: {
      aiAccuracy: vi.fn(),
      countTickets: vi.fn(),
      listTickets: vi.fn(),
      startTeamworkImport: vi.fn(),
      teamworkAutoSync: vi.fn(),
      teamworkFilterOptions: vi.fn(),
      teamworkStatus: vi.fn(),
      teamworkSyncState: vi.fn(),
      setTeamworkAutoSync: vi.fn(),
      syncTeamworkNow: vi.fn(),
      purgeBlockedTickets: vi.fn(),
      clearTeamworkTickets: vi.fn(),
    },
  },
}))

class FakeEventSource {
  static readonly instances: FakeEventSource[] = []

  readonly url: string
  readonly withCredentials: boolean
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  closed = false

  constructor(url: string, options?: EventSourceInit) {
    this.url = url
    this.withCredentials = Boolean(options?.withCredentials)
    FakeEventSource.instances.push(this)
  }

  close() {
    this.closed = true
  }
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <ImportTeamwork />
    </QueryClientProvider>,
  )
}

function mockDefaultApi(statusOverride = {}) {
  vi.mocked(api.users.list).mockResolvedValue([])
  vi.mocked(api.import.aiAccuracy).mockResolvedValue({ evaluated: 0, correct: 0, accuracy_pct: null })
  vi.mocked(api.import.countTickets).mockResolvedValue({ count: 0 })
  vi.mocked(api.import.listTickets).mockResolvedValue([])
  vi.mocked(api.import.teamworkAutoSync).mockResolvedValue({ enabled: false, interval_seconds: 60 })
  vi.mocked(api.import.teamworkFilterOptions).mockResolvedValue({ clients: [], agents: [], inboxes: [] })
  vi.mocked(api.import.teamworkStatus).mockResolvedValue({
    tickets_in_graph: 0,
    import_running: false,
    last_imported_at: null,
    ...statusOverride,
  })
  vi.mocked(api.import.teamworkSyncState).mockResolvedValue({ initialized: false, state: null })
  vi.mocked(api.import.startTeamworkImport).mockResolvedValue({ status: 'started' })
}

describe('ImportTeamwork durable import progress', () => {
  beforeEach(() => {
    FakeEventSource.instances.length = 0
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.stubGlobal('alert', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('resumes the progress stream on load when an import is already running', async () => {
    mockDefaultApi({
      import_running: true,
      progress: {
        status: 'running',
        message: 'Processed 5/10',
        processed: 5,
        imported: 4,
        skipped: 1,
        failed: 0,
        total: 10,
      },
    })

    renderPage()

    await waitFor(() => {
      expect(FakeEventSource.instances.some(es => es.url === '/api/import/teamwork/progress')).toBe(true)
    })
  })

  it('closes the progress stream on terminal events and ignores later stream errors', async () => {
    mockDefaultApi()
    const user = userEvent.setup()

    renderPage()
    await user.click(await screen.findByRole('button', { name: 'Import tickets' }))

    await waitFor(() => {
      expect(FakeEventSource.instances.some(es => es.url === '/api/import/teamwork/progress')).toBe(true)
    })

    const progressStream = FakeEventSource.instances.find(
      es => es.url === '/api/import/teamwork/progress',
    )
    expect(progressStream).toBeDefined()

    act(() => {
      progressStream?.onmessage?.({
        data: JSON.stringify({
          status: 'completed',
          message: 'Import finished; skill generation queued.',
          processed: 3,
          imported: 3,
          skipped: 0,
          failed: 0,
          total: 3,
        }),
      } as MessageEvent)
      progressStream?.onerror?.(new Event('error'))
    })

    expect(progressStream?.closed).toBe(true)
    expect(screen.queryByText('Connection lost')).not.toBeInTheDocument()
  })
})
