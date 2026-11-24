import { useI18n } from 'vue-i18n'
import type { ChatStatus } from '../../api/host'
import { currentLocale } from '../../i18n'
import { formatDateTime } from '../../i18n/format'

export const statusTones = {
  chatting: 'success',
  paused: 'idle',
  quiet: 'info',
  limited: 'warning',
  closed: 'idle',
} as const satisfies Record<ChatStatus['status'], string>

/** 聊天中, or 安静中，到 23:00 when the state ends by itself in the future. */
export function useStatusLabel() {
  const { t } = useI18n()
  return (value: ChatStatus, timeZone?: string, nowMs = Date.now()) => {
    const status = t(`groups.status.${value.status}`)
    const ends = value.status === 'quiet' || value.status === 'limited'
    return ends && value.changes_at && value.changes_at * 1000 > nowMs
      ? t('groups.until', { status, time: formatDateTime(value.changes_at, { timeZone }) })
      : status
  }
}

/** Compact remaining duration until a Unix-second deadline: 2 hr 15 min, 28 min, 40 sec. */
export function formatQuietRemaining(untilSeconds: number, nowMs: number): string {
  const remaining = Math.max(0, Math.ceil((untilSeconds * 1000 - nowMs) / 1000))
  const locale = currentLocale.value
  const unit = (value: number, name: 'hour' | 'minute' | 'second') =>
    new Intl.NumberFormat(locale, { style: 'unit', unit: name, unitDisplay: 'short' }).format(value)
  if (remaining >= 3600) {
    let hours = Math.floor(remaining / 3600)
    let minutes = Math.ceil((remaining % 3600) / 60)
    if (minutes === 60) {
      hours += 1
      minutes = 0
    }
    return minutes ? `${unit(hours, 'hour')} ${unit(minutes, 'minute')}` : unit(hours, 'hour')
  }
  if (remaining >= 60) return unit(Math.ceil(remaining / 60), 'minute')
  return unit(Math.max(1, remaining), 'second')
}
