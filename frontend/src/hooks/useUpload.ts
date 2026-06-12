import { useCallback, useState } from 'react'
import { api } from '../api/client'
import type { DocumentStatusEvent } from '../types'

export interface UploadState {
  status: 'idle' | 'uploading' | 'processing' | 'completed' | 'failed'
  progress: number
  message: string | null
  documentId: string | null
}

export function useUpload() {
  const [state, setState] = useState<UploadState>({
    status: 'idle',
    progress: 0,
    message: null,
    documentId: null,
  })

  const upload = useCallback(async (file: File, authorEmail?: string, tags?: string) => {
    setState({ status: 'uploading', progress: 5, message: 'Uploading...', documentId: null })
    try {
      const data = await api.documents.upload(file, authorEmail, tags)
      setState((s) => ({ ...s, status: 'processing', progress: 10, documentId: data.id }))

      const rawId = data.id.includes(':') ? data.id.split(':')[1] : data.id
      const es = new EventSource(`/api/documents/${rawId}/status`)

      es.onmessage = (e: MessageEvent<string>) => {
        const evt: DocumentStatusEvent = JSON.parse(e.data)
        setState({
          status: evt.status === 'pending' ? 'processing' : evt.status,
          progress: evt.progress,
          message: evt.message,
          documentId: data.id,
        })
        if (evt.status === 'completed' || evt.status === 'failed') es.close()
      }

      es.onerror = () => {
        es.close()
        setState((s) => ({ ...s, status: 'failed', message: 'Connection lost' }))
      }
    } catch (err) {
      setState({
        status: 'failed',
        progress: 0,
        message: err instanceof Error ? err.message : 'Upload failed',
        documentId: null,
      })
    }
  }, [])

  const reset = useCallback(() => {
    setState({ status: 'idle', progress: 0, message: null, documentId: null })
  }, [])

  return { state, upload, reset }
}
