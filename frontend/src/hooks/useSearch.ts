import { useCallback, useState } from 'react'
import { api } from '../api/client'
import type { AskResponse, SearchResponse } from '../types'

export function useSearch() {
  const [results, setResults] = useState<SearchResponse | null>(null)
  const [answer, setAnswer] = useState<AskResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [answerLoading, setAnswerLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const search = useCallback(async (query: string, limit = 10) => {
    if (!query.trim()) return
    setLoading(true)
    setAnswerLoading(true)
    setError(null)
    setAnswer(null)

    // Fire both in parallel — chunks load fast, answer takes longer
    const [searchResult] = await Promise.allSettled([
      api.search.query({ query, limit }).then((data) => {
        setResults(data)
        setLoading(false)
      }),
      api.search.ask(query).then((data) => {
        setAnswer(data)
        setAnswerLoading(false)
      }).catch(() => {
        setAnswerLoading(false)
      }),
    ])

    if (searchResult.status === 'rejected') {
      setError(searchResult.reason instanceof Error ? searchResult.reason.message : 'Search failed')
      setLoading(false)
    }
  }, [])

  return { results, answer, loading, answerLoading, error, search }
}
