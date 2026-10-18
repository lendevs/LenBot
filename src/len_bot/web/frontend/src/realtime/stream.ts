import { onScopeDispose, readonly, ref } from 'vue'
import { socketUrl } from '../api/client'
import { keys, queryClient } from '../api/query'

/** Envelope of /api/host/stream (protocol in work.md, server in runtime/events.py). */
export interface HostEvent {
  seq: number
  at: number
  type: string
  scene: string | null
  [field: string]: unknown
}

export type StreamStatus = 'idle' | 'connecting' | 'open' | 'closed'

type Handler = (event: HostEvent) => void

const status = ref<StreamStatus>('idle')
/** Seconds until the next reconnect attempt while closed. */
const retryIn = ref<number | null>(null)
const handlers = new Map<string, Set<Handler>>()
let socket: WebSocket | null = null
let wanted = false
let attempts = 0
let timer: ReturnType<typeof setTimeout> | undefined
let countdown: ReturnType<typeof setInterval> | undefined
let opened = false

export const streamStatus = readonly(status)
export const streamRetryIn = readonly(retryIn)

function dispatch(event: HostEvent) {
  for (const key of [event.type, '*']) handlers.get(key)?.forEach((handler) => handler(event))
}

function schedule() {
  // 1, 2, 4 … 30 seconds with jitter, so many tabs do not reconnect at the same instant.
  const delay = Math.min(30_000, 1000 * 2 ** attempts) * (0.8 + Math.random() * 0.4)
  attempts += 1
  retryIn.value = Math.ceil(delay / 1000)
  clearInterval(countdown)
  countdown = setInterval(() => {
    if (retryIn.value !== null && retryIn.value > 1) retryIn.value -= 1
  }, 1000)
  timer = setTimeout(connect, delay)
}

function connect() {
  clearTimeout(timer)
  clearInterval(countdown)
  retryIn.value = null
  if (!wanted) return
  const connection = new WebSocket(socketUrl('/api/host/stream'))
  socket = connection
  status.value = 'connecting'
  connection.onmessage = (message) => {
    if (socket !== connection) return
    let event: HostEvent
    try {
      event = JSON.parse(String(message.data)) as HostEvent
    } catch {
      return
    }
    if (event.type === 'hello') {
      status.value = 'open'
      attempts = 0
      // Events sent while disconnected are not replayed; after a reconnect everything is read again.
      if (opened) void queryClient.invalidateQueries()
      opened = true
    } else if (event.type === 'resync') {
      void queryClient.invalidateQueries()
    }
    dispatch(event)
  }
  connection.onclose = () => {
    if (socket !== connection) return
    socket = null
    status.value = 'closed'
    if (wanted) schedule()
  }
}

/** Open the single connection after login; calling it again is harmless. */
export function startStream(): void {
  if (wanted) return
  wanted = true
  opened = false
  attempts = 0
  connect()
}

export function stopStream(): void {
  wanted = false
  clearTimeout(timer)
  clearInterval(countdown)
  retryIn.value = null
  const connection = socket
  socket = null
  connection?.close()
  status.value = 'idle'
}

/** Reconnect now instead of waiting for the backoff. */
export function reconnectStream(): void {
  if (!wanted) return
  socket?.close()
  socket = null
  attempts = 0
  connect()
}

/** Listen to one event type, or '*' for all; removed with the calling component or effect scope. */
export function useHostEvent(type: string, handler: Handler): () => void {
  const set = handlers.get(type) ?? new Set<Handler>()
  handlers.set(type, set)
  set.add(handler)
  const remove = () => set.delete(handler)
  onScopeDispose(remove, true)
  return remove
}

function throttle(run: () => void, wait: number): () => void {
  let last = 0
  let pending: ReturnType<typeof setTimeout> | undefined
  return () => {
    const due = last + wait - Date.now()
    if (due <= 0) {
      last = Date.now()
      run()
    } else if (!pending) {
      pending = setTimeout(() => {
        pending = undefined
        last = Date.now()
        run()
      }, due)
    }
  }
}

const refreshState = throttle(() => void queryClient.invalidateQueries({ queryKey: keys.host.state() }), 250)
const refreshHost = throttle(() => void queryClient.invalidateQueries({ queryKey: keys.host.all() }), 1000)

/** Cache rules that hold on every page: which queries an event makes stale. */
function cacheRules(event: HostEvent) {
  if (event.type === 'host.state') refreshState()
  else if (event.type === 'host.changed') refreshHost()
  if (event.scene && /^(message\.|turn\.(started|ended)$)/.test(event.type)) {
    void queryClient.invalidateQueries({ queryKey: keys.scene.timeline(event.scene) })
  }
}
handlers.set('*', new Set([cacheRules]))
