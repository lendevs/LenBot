import { currentLocale } from './index'

/** Number, date and relative-time formatting in the current panel language. */
export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(currentLocale.value, options).format(value)
}

/** Token counts and similar: 18342 → 18.3K (en) or 1.8万 (zh). */
export function formatCompact(value: number): string {
  return new Intl.NumberFormat(currentLocale.value, { notation: 'compact', maximumFractionDigits: 1 }).format(
    value,
  )
}

/**
 * Unix seconds → date and time; today shows only the time. `timeZone` (IANA name) shows the clock of a group
 * whose quiet hours and reminders follow its own time zone; without it the browser's zone is used.
 */
export function formatDateTime(
  seconds: number,
  { withSeconds = false, timeZone }: { withSeconds?: boolean; timeZone?: string } = {},
): string {
  const date = new Date(seconds * 1000)
  // en-CA gives YYYY-MM-DD, which compares day and year in the chosen zone.
  const day = (value: Date) =>
    new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(
      value,
    )
  const [shown, now] = [day(date), day(new Date())]
  return new Intl.DateTimeFormat(currentLocale.value, {
    timeZone,
    ...(shown === now ? {} : { month: 'numeric', day: 'numeric' }),
    ...(shown.slice(0, 4) !== now.slice(0, 4) ? { year: 'numeric' } : {}),
    hour: '2-digit',
    minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}),
    hour12: false,
  }).format(date)
}

const units: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 86400],
  ['month', 30 * 86400],
  ['week', 7 * 86400],
  ['day', 86400],
  ['hour', 3600],
  ['minute', 60],
  ['second', 1],
]

/** Unix seconds → 3 分钟前 / in 2 hours. */
export function formatRelative(seconds: number, now = Date.now() / 1000): string {
  const delta = seconds - now
  const format = new Intl.RelativeTimeFormat(currentLocale.value, { numeric: 'auto' })
  for (const [unit, size] of units) {
    if (Math.abs(delta) >= size || unit === 'second') return format.format(Math.round(delta / size), unit)
  }
  return format.format(0, 'second')
}

/** Milliseconds → 850 ms, 2.4 s, 3 min 12 s. */
export function formatDuration(ms: number): string {
  const locale = currentLocale.value
  if (ms < 1000)
    return new Intl.NumberFormat(locale, { style: 'unit', unit: 'millisecond' }).format(Math.round(ms))
  if (ms < 60_000) {
    return new Intl.NumberFormat(locale, { style: 'unit', unit: 'second', maximumFractionDigits: 1 }).format(
      ms / 1000,
    )
  }
  const minutes = Math.floor(ms / 60_000)
  const rest = Math.round((ms % 60_000) / 1000)
  const unit = (value: number, name: 'minute' | 'second') =>
    new Intl.NumberFormat(locale, { style: 'unit', unit: name, unitDisplay: 'short' }).format(value)
  return rest ? `${unit(minutes, 'minute')} ${unit(rest, 'second')}` : unit(minutes, 'minute')
}

export function formatBytes(bytes: number): string {
  const steps = ['byte', 'kilobyte', 'megabyte', 'gigabyte', 'terabyte'] as const
  let value = bytes
  let index = 0
  while (value >= 1024 && index < steps.length - 1) {
    value /= 1024
    index += 1
  }
  return new Intl.NumberFormat(currentLocale.value, {
    style: 'unit',
    unit: steps[index],
    unitDisplay: 'short',
    maximumFractionDigits: index ? 1 : 0,
  }).format(value)
}
