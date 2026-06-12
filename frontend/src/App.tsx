import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import { AuthGate } from './components/AuthGate'
import { Layout } from './components/Layout'
import { Dashboard } from './pages/Dashboard'
import { Documents } from './pages/Documents'
import { DocumentView } from './pages/DocumentView'
import { Experts } from './pages/Experts'
import { Clients } from './pages/Clients'
import { Integrations } from './pages/Integrations'
import { AuraAgent } from './pages/AuraAgent'
import { ImportTeamwork } from './pages/ImportTeamwork'
import { RoutingPlayground } from './pages/RoutingPlayground'
import { ReviewQueue } from './pages/ReviewQueue'
import { ActivityLog } from './pages/ActivityLog'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthGate>
          {({ logout }) => (
            <Layout onLogout={async () => {
              queryClient.clear()
              await logout()
            }}>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/upload" element={<Navigate to="/documents" replace />} />
                <Route path="/documents" element={<Documents />} />
                <Route path="/documents/:id" element={<DocumentView />} />
                <Route path="/search" element={<Navigate to="/documents" replace />} />
                <Route path="/experts" element={<Experts />} />
                <Route path="/clients" element={<Clients />} />
                <Route path="/integrations" element={<Integrations />} />
                <Route path="/aura-agent" element={<AuraAgent />} />
                <Route path="/integrations/teamwork" element={<ImportTeamwork />} />
                <Route path="/routing" element={<RoutingPlayground />} />
                <Route path="/review-queue" element={<ReviewQueue />} />
                <Route path="/activity-log" element={<ActivityLog />} />
              </Routes>
            </Layout>
          )}
        </AuthGate>
      </BrowserRouter>
      <Toaster position="bottom-right" />
    </QueryClientProvider>
  )
}
