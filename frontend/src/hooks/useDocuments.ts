import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

export function useDocuments(offset = 0, limit = 20) {
  return useQuery({
    queryKey: ['documents', offset, limit],
    queryFn: () => api.documents.list(offset, limit),
  })
}

export function useDocument(id: string) {
  return useQuery({
    queryKey: ['document', id],
    queryFn: () => api.documents.get(id),
    enabled: !!id,
  })
}

export function useDeleteDocument() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.documents.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents'] }),
  })
}

export function useStats() {
  return useQuery({
    queryKey: ['stats'],
    queryFn: () => api.health.stats(),
    refetchInterval: 30_000,
  })
}
