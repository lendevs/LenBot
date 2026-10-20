import { useI18n } from 'vue-i18n'
import type { LogRecord } from '../../../api/logs'
import type { Tone } from '../../../ui/Badge.vue'

/** Correlation fields shown under a record, in this order. */
export const idFields = ['turn_id', 'tool', 'plugin', 'task_id', 'message_seq', 'job'] as const

export const severity = (item: LogRecord): Tone | null =>
  item.error || item.level === 'ERROR' || item.level === 'CRITICAL'
    ? 'error'
    : item.level === 'WARNING'
      ? 'warning'
      : null

export const seconds = (item: LogRecord) => Date.parse(item.ts) / 1000

export function useLogLabels() {
  const { t, te } = useI18n()
  return {
    /** Name of an event kind; records without one are grouped as other. */
    event: (value: string | undefined) =>
      value === undefined ? t('logs.events._other') : te(`logs.events.${value}`) ? t(`logs.events.${value}`) : value,
    title: (item: LogRecord) =>
      item.event && te(`logs.events.${item.event}`) ? t(`logs.events.${item.event}`) : (item.event ?? item.message),
  }
}
