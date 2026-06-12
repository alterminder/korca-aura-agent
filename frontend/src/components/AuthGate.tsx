import { FormEvent, useEffect, useState } from 'react'
import { api } from '../api/client'

type AuthState = 'loading' | 'authenticated' | 'unauthenticated'

interface AuthGateProps {
  children: (auth: { logout: () => Promise<void> }) => React.ReactNode
}

export function AuthGate({ children }: AuthGateProps) {
  const [state, setState] = useState<AuthState>('loading')

  useEffect(() => {
    let active = true
    api.auth.me()
      .then((result) => {
        if (active) setState(result.authenticated ? 'authenticated' : 'unauthenticated')
      })
      .catch(() => {
        if (active) setState('unauthenticated')
      })
    return () => {
      active = false
    }
  }, [])

  async function logout() {
    await api.auth.logout().catch(() => undefined)
    setState('unauthenticated')
  }

  if (state === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-app-bg">
        <div className="text-sm text-app-nav-text">Loading...</div>
      </div>
    )
  }

  if (state === 'unauthenticated') {
    return <LoginScreen onAuthenticated={() => setState('authenticated')} />
  }

  return <>{children({ logout })}</>
}

function LoginScreen({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      await api.auth.login(password)
      setPassword('')
      onAuthenticated()
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Login failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-app-bg px-4">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-[20px] border border-app-border bg-white px-8 py-8 shadow-sm"
      >
        <div className="mb-7 flex items-center gap-3">
          <img src="/favicon.png" alt="Korca" className="h-9 w-9 object-contain" />
          <div>
            <h1 className="text-xl font-bold tracking-wide text-app-accent">Korca</h1>
            <p className="text-sm text-app-nav-text">Sign in to continue</p>
          </div>
        </div>
        <label className="mb-2 block text-sm font-medium text-slate-800" htmlFor="korca-password">
          Password
        </label>
        <input
          id="korca-password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="h-10 w-full rounded-md border border-app-border px-3 text-sm text-slate-950 outline-none transition-colors focus:border-app-accent"
          autoComplete="current-password"
          autoFocus
        />
        {error && <div className="mt-3 text-sm text-red-600">{error}</div>}
        <button
          type="submit"
          disabled={submitting || !password}
          className="mt-5 h-10 w-full rounded-md bg-app-accent px-4 text-sm font-semibold text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
