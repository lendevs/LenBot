import { computed, onBeforeUnmount } from 'vue'
import { reconnectStream, streamStatus, useHostEvent } from './stream'

const statuses = {
  idle: 'connecting',
  connecting: 'connecting',
  open: 'connected',
  closed: 'disconnected',
} as const

/**
 * Run `read` after host events, one read at a time, on the shared /api/host/stream connection. `types` limits
 * which events count (default: all except per-step turn progress); `minInterval` spaces reads out in
 * milliseconds. The first read happens at once.
 */
export function useHostEvents(
  read: () => unknown,
  { types = null, minInterval = 0 }: { types?: string[] | null; minInterval?: number } = {},
) {
  let reading = false
  let again = false
  let active = true
  let last = 0
  let timer: ReturnType<typeof setTimeout> | null = null

  async function run() {
    if (reading) {
      again = true
      return
    }
    reading = true
    try {
      do {
        again = false
        last = Date.now()
        await read()
      } while (again && active)
    } finally {
      reading = false
    }
  }
  function changed() {
    if (!active || timer) return
    const wait = last + minInterval - Date.now()
    if (wait <= 0) void run()
    else
      timer = setTimeout(() => {
        timer = null
        void run()
      }, wait)
  }
  useHostEvent('*', (event) => {
    if (event.type === 'hello' || (types ? types.includes(event.type) : event.type !== 'turn.step')) changed()
  })
  onBeforeUnmount(() => {
    active = false
    if (timer) clearTimeout(timer)
  })
  changed()
  return {
    status: computed(() => statuses[streamStatus.value]),
    reconnect() {
      reconnectStream()
      void run()
    },
  }
}
