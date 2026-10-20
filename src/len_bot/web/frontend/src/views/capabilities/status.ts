import type { Tone } from '../../ui/Badge.vue'

const mcpTones: Record<string, Tone> = {
  running: 'success',
  connecting: 'info',
  failed: 'error',
  disabled: 'neutral',
  stopped: 'neutral',
}
export const mcpTone = (status: string): Tone => mcpTones[status] ?? 'neutral'
