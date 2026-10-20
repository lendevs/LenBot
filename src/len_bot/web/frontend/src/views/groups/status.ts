import { useI18n } from 'vue-i18n'
import type { ChatStatus } from '../../api/host'
import { formatDateTime } from '../../i18n/format'

export const statusTones = {
  chatting: 'success',
  paused: 'idle',
  quiet: 'info',
  limited: 'warning',
} as const satisfies Record<ChatStatus['status'], string>

/** 聊天中, or 安静中，到 23:00 when the state ends by itself. */
export function useStatusLabel() {
  const { t } = useI18n()
  return (value: ChatStatus, timeZone?: string) => {
    const status = t(`groups.status.${value.status}`)
    const ends = value.status === 'quiet' || value.status === 'limited'
    return ends && value.changes_at ? t('groups.until', { status, time: formatDateTime(value.changes_at, { timeZone }) }) : status
  }
}
