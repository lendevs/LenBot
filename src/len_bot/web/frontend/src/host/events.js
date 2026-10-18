import { computed, onBeforeUnmount } from 'vue'
import { reconnectStream, streamStatus, useHostEvent } from '../realtime/stream'

const statuses = { idle: 'connecting', connecting: 'connecting', open: 'connected', closed: 'disconnected' }

/**
 * Old pages: run `read` after host events, one read at a time. Shares the single /api/host/stream
 * connection. `types` limits which events count (default: all except per-step turn progress);
 * `minInterval` spaces reads out in milliseconds.
 */
export function useHostEvents(read, { types = null, minInterval = 0 } = {}) {
  let reading = false, again = false, active = true, last = 0, timer = null

  async function run() {
    if (reading) { again = true; return }
    reading = true
    try {
      do { again = false; last = Date.now(); await read() } while (again && active)
    } finally {
      reading = false
    }
  }
  function changed() {
    if (!active || timer) return
    const wait = last + minInterval - Date.now()
    if (wait <= 0) run()
    else timer = setTimeout(() => { timer = null; run() }, wait)
  }
  useHostEvent('*', event => {
    if (event.type === 'hello' || (types ? types.includes(event.type) : event.type !== 'turn.step')) changed()
  })
  onBeforeUnmount(() => { active = false; clearTimeout(timer) })
  // The old socket announced a change on connect; with one shared connection the first read happens here.
  changed()
  return {
    status: computed(() => statuses[streamStatus.value]),
    reconnect() { reconnectStream(); run() },
  }
}
