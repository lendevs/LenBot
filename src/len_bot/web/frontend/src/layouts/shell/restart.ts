import { reactive } from 'vue'
import { http, resetSession } from '../../api/client'
import { i18n } from '../../i18n'

/** The explicit host restart: preview what it applies and interrupts, request it, wait for the new process. */

interface HostProcess {
  pid: number
  started_at: number
}

interface PanelAddress {
  host: string
  port: number
}

/** GET and POST /api/host/restart */
export interface RestartPreview {
  process: HostProcess
  restartable: boolean
  intent: string
  pending: {
    sections: string[]
    scenes: string[]
    personas: { name: string; path: string }[]
    plugins: { name: string; candidate: { version: string }; error: string | null }[]
  }
  panel: { running: PanelAddress; saved: PanelAddress | null }
  chats: string[]
  tasks: { id: number; scene: string; goal: string; status: string; account_browser: boolean }[]
  queued_tasks: number
  browsers: { id: number; scene: string; session: string | null }[]
  trials: { id: string; scene: string }[]
}

type Phase = 'preview' | 'waiting' | 'ready' | 'address-changed' | 'unavailable'

export const restartFlow = reactive({
  open: false,
  busy: false,
  /** A restart was requested; the page waits for the new process and shows nothing else. */
  waiting: false,
  preview: null as RestartPreview | null,
  error: null as unknown,
  phase: 'preview' as Phase,
  lastConnectionError: null as unknown,
})

/** Login sessions belong to the old process; only the public readiness is read while waiting. */
async function ready(): Promise<HostProcess> {
  const response = await fetch('/api/host/ready', {
    cache: 'no-store',
    credentials: 'omit',
    signal: AbortSignal.timeout(3000),
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const value = (await response.json()) as Partial<HostProcess>
  if (typeof value.pid !== 'number' || typeof value.started_at !== 'number') {
    throw new Error(`${i18n.global.t('shell.restart.dialog.badReady')}: ${JSON.stringify(value)}`)
  }
  return value as HostProcess
}

export async function openRestart(): Promise<void> {
  Object.assign(restartFlow, { open: true, busy: true, phase: 'preview', preview: null, error: null })
  try {
    restartFlow.preview = await http.get<RestartPreview>('/api/host/restart')
  } catch (error) {
    restartFlow.error = error
  } finally {
    restartFlow.busy = false
  }
}

export function panelChanged(preview: RestartPreview): boolean {
  const { running, saved } = preview.panel
  return saved === null || running.host !== saved.host || running.port !== saved.port
}

/** Where the panel answers after the restart; null when only the startup log can tell. */
export function newPanelUrl(preview: RestartPreview): string | null {
  const panel = preview.panel.saved
  if (panel === null || panel.port === 0) return null
  // Behind HTTPS or a forwarded port the address the browser uses stays the same.
  if (location.protocol === 'https:' || Number(location.port || 80) !== preview.panel.running.port) {
    return `${location.origin}/#/overview`
  }
  const hostname = ['0.0.0.0', '::'].includes(panel.host) ? location.hostname : panel.host
  const host = hostname.includes(':') && !hostname.startsWith('[') ? `[${hostname}]` : hostname
  return `${location.protocol}//${host}:${panel.port}/#/overview`
}

export async function waitForRestart(): Promise<void> {
  const old = restartFlow.preview!.process
  Object.assign(restartFlow, { phase: 'waiting', error: null, lastConnectionError: null })
  const deadline = Date.now() + 180_000
  while (Date.now() < deadline) {
    try {
      const current = await ready()
      restartFlow.lastConnectionError = null
      if (current.pid !== old.pid || current.started_at !== old.started_at) {
        restartFlow.phase = 'ready'
        location.reload()
        return
      }
    } catch (error) {
      restartFlow.lastConnectionError = error
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  restartFlow.phase = 'unavailable'
  restartFlow.error = new Error(i18n.global.t('shell.restart.dialog.unavailable'))
}

export async function confirmRestart(): Promise<void> {
  restartFlow.busy = true
  restartFlow.error = null
  try {
    const preview = await http.post<RestartPreview>('/api/host/restart')
    restartFlow.preview = preview
    restartFlow.waiting = true
    // Answers to requests still in flight belong to the old process.
    resetSession()
    if (panelChanged(preview)) restartFlow.phase = 'address-changed'
    else await waitForRestart()
  } catch (error) {
    restartFlow.error = error
  } finally {
    restartFlow.busy = false
  }
}
