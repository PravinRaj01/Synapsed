import type { components } from '@/api/schema'
import { api, unwrap } from './api'

export type IngestResponse = components['schemas']['IngestResponse']

export type UploadOptions = {
  campaignId: string
  segmentId?: string | null
  textColumn?: string
  segmentColumn?: string
  /** Relabel a text, JSON or spreadsheet file (the API checks it is allowed for that file). */
  sourceType?: string | null
}

type XhrLike = {
  open(method: string, url: string): void
  send(body: Blob): void
  abort(): void
  upload: { onprogress: ((e: { loaded: number; total: number; lengthComputable: boolean }) => void) | null }
  onload: (() => void) | null
  onerror: (() => void) | null
  onabort: (() => void) | null
  status: number
}

/** PUT the raw file bytes to a presigned URL, reporting progress (fetch cannot report upload progress). */
export function putFile(url: string, file: Blob, onProgress: (fraction: number) => void, signal?: AbortSignal, Xhr: new () => XhrLike = XMLHttpRequest as never): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new Xhr()
    xhr.open('PUT', url)
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? (onProgress(1), resolve()) : reject(new Error('The file store refused the upload. Please try again.')))
    xhr.onerror = () => reject(new Error('The upload did not finish. Check your connection and try again.'))
    xhr.onabort = () => reject(new Error('The upload was cancelled.'))
    signal?.addEventListener('abort', () => xhr.abort())
    xhr.send(file)
  })
}

type Deps = {
  ticket: (body: { campaign_id: string; filename: string; size: number }) => Promise<{ key: string; url: string }>
  stage: (body: Record<string, unknown>) => Promise<IngestResponse>
  put: typeof putFile
}

const real: Deps = {
  ticket: (body) => unwrap(api.POST('/api/v1/uploads', { body })),
  stage: (body) => unwrap(api.POST('/api/v1/ingest/stored', { body: body as never })),
  put: putFile,
}

/**
 * Add one file to a campaign: ask for a presigned URL, send the bytes straight to storage, then ask the API to
 * read, scrub and stage them. Progress is 0-0.9 while uploading and 1 once the API has staged the file.
 */
export async function uploadSource(file: File, opts: UploadOptions, onProgress: (fraction: number) => void = () => {}, signal?: AbortSignal, deps: Deps = real): Promise<IngestResponse> {
  const ticket = await deps.ticket({ campaign_id: opts.campaignId, filename: file.name, size: file.size })
  await deps.put(ticket.url, file, (f) => onProgress(f * 0.9), signal)
  onProgress(0.9)
  const result = await deps.stage({
    campaign_id: opts.campaignId,
    key: ticket.key,
    segment_id: opts.segmentId || null,
    source_type: opts.sourceType || null,
    text_column: opts.textColumn?.trim() || null,
    segment_column: opts.segmentColumn?.trim() || null,
  })
  onProgress(1)
  return result
}

/** A pasted note as a file, so it goes through the same pipeline as everything else. */
export function noteFile(text: string, title: string): File {
  const safe = title.trim().replace(/[\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80).trim() || 'Pasted note'
  return new File([text], `${safe}.txt`, { type: 'text/plain' })
}
