import type { Tone } from '../../../ui/Badge.vue'
import type { TaskStatus } from '../../../api/tasks'

export const statusTone: Record<TaskStatus, Tone> = {
  queued: 'neutral',
  running: 'info',
  waiting_input: 'warning',
  done: 'success',
  failed: 'error',
  cancelled: 'neutral',
}

export const uploadTone: Record<string, Tone> = { uploaded: 'success', failed: 'error', unconfirmed: 'warning' }

export const finished = (status: TaskStatus | undefined) =>
  status === 'done' || status === 'failed' || status === 'cancelled'
