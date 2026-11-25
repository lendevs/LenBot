<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { developerDetails } from '../../../composables/useDeveloperMode'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Select from '../../../ui/Select.vue'

/** Builds the `when` of a reminder: an ISO time with the group's offset, `every <n><unit>`, or a cron line. */
const props = defineProps<{ timezone: string }>()
const model = defineModel<string>({ default: '' })
const emit = defineEmits<{ dirty: [value: boolean] }>()

type Mode = 'once' | 'weekly' | 'every' | 'custom'
const { t } = useI18n()
const unitId = useId()

function localParts(instant: number): Record<string, number> {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-US', {
      timeZone: props.timezone,
      hourCycle: 'h23',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
      .formatToParts(instant)
      .map((part) => [part.type, Number(part.value)]),
  )
  return parts
}

/** Minutes the zone is ahead of UTC at an instant. */
function offsetAt(instant: number): number {
  const parts = localParts(instant)
  const local = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second)
  return Math.round((local - instant) / 60000)
}

/** The local time as ISO with its offset; empty when the zone skips that time. */
function withOffset(day: string, clock: string): string {
  const [y, m, d] = day.split('-').map(Number)
  const [h, mi] = clock.split(':').map(Number)
  const guess = Date.UTC(y, m - 1, d, h, mi)
  const offset = offsetAt(guess - offsetAt(guess) * 60000)
  if (offsetAt(guess - offset * 60000) !== offset) return ''
  const pad = (value: number) => String(value).padStart(2, '0')
  const sign = offset < 0 ? '-' : '+'
  const abs = Math.abs(offset)
  return `${day}T${clock}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`
}

/** Next whole hour in the group's timezone, at least +1 hour ahead (or skipping a DST gap). */
function initialDateTime(): { date: string; time: string } {
  const pad = (value: number) => String(value).padStart(2, '0')
  const now = Date.now()
  const parts = localParts(now)
  // Round forward to the next whole hour +1h when past the half hour, ensuring a comfortable future default.
  const minutesToNextHour = 60 - parts.minute
  let candidate = now + (minutesToNextHour + (parts.minute >= 30 ? 60 : 0)) * 60_000 - parts.second * 1000
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const next = localParts(candidate)
    const day = `${next.year}-${pad(next.month)}-${pad(next.day)}`
    const clock = `${pad(next.hour)}:00`
    if (withOffset(day, clock)) return { date: day, time: clock }
    candidate += 3600_000
  }
  const fallback = localParts(now + 3600_000)
  return {
    date: `${fallback.year}-${pad(fallback.month)}-${pad(fallback.day)}`,
    time: `${pad(fallback.hour)}:${pad(fallback.minute)}`,
  }
}

const initial = initialDateTime()
const mode = ref<Mode>('once')
const date = ref(initial.date)
const time = ref(initial.time)
const days = ref<number[]>([1, 2, 3, 4, 5, 6, 0])
const every = ref<number | null>(1)
const unit = ref<'m' | 'h' | 'd'>('h')
const custom = ref('')

const snapshot = () =>
  JSON.stringify({
    mode: mode.value,
    date: date.value,
    time: time.value,
    days: [...days.value].sort(),
    every: every.value,
    unit: unit.value,
    custom: custom.value,
  })
const initialSnapshot = snapshot()
const dirty = computed(() => snapshot() !== initialSnapshot)
watch(dirty, (value) => emit('dirty', value), { immediate: true })

const modes = computed(() =>
  (['once', 'weekly', 'every', 'custom'] as const).map((value) => ({
    value,
    label: t(`groups.tasks.schedules.dialog.modes.${value}`),
  })),
)
const units = computed(() =>
  (['m', 'h', 'd'] as const).map((value) => ({
    value,
    label: t(`groups.tasks.schedules.dialog.units.${value}`),
  })),
)
/** Monday first, as people read a week. */
const weekdays = [1, 2, 3, 4, 5, 6, 0]
const presets = [
  { key: 'daily', days: [1, 2, 3, 4, 5, 6, 0] },
  { key: 'weekdays', days: [1, 2, 3, 4, 5] },
  { key: 'weekend', days: [6, 0] },
] as const

function sameDays(a: readonly number[], b: readonly number[]): boolean {
  return a.length === b.length && a.every((day) => b.includes(day))
}
function toggleDay(day: number) {
  days.value = days.value.includes(day) ? days.value.filter((item) => item !== day) : [...days.value, day]
}

const clock = computed(() => (/^\d{2}:\d{2}/.test(time.value) ? time.value.slice(0, 5) : ''))
const once = computed(() =>
  /^\d{4}-\d{2}-\d{2}$/.test(date.value) && clock.value ? withOffset(date.value, clock.value) : null,
)
const isPast = computed(() => {
  if (mode.value !== 'once' || !once.value) return false
  const ms = Date.parse(once.value)
  return Number.isFinite(ms) && ms <= Date.now()
})

const value = computed(() => {
  if (mode.value === 'custom') return custom.value.trim()
  if (mode.value === 'every') return every.value && every.value > 0 ? `every ${every.value}${unit.value}` : ''
  if (!clock.value) return ''
  if (mode.value === 'once') return !once.value || isPast.value ? '' : once.value
  if (!days.value.length) return ''
  const [h, mi] = clock.value.split(':').map(Number)
  const week = days.value.length === 7 ? '*' : [...days.value].sort().join(',')
  return `cron:${mi} ${h} * * ${week}`
})
watch(value, (text) => (model.value = text), { immediate: true })
</script>

<template>
  <div class="flex flex-col gap-3">
    <SegmentedControl
      v-model="mode"
      :options="modes"
      size="sm"
      :label="t('groups.tasks.schedules.dialog.repeat')"
      class="self-start"
    />
    <div v-if="mode === 'once'" class="grid gap-3 sm:grid-cols-2">
      <Field :label="t('groups.tasks.schedules.dialog.date')"><Input v-model="date" type="date" /></Field>
      <Field :label="t('groups.tasks.schedules.dialog.time')"><Input v-model="time" type="time" /></Field>
    </div>
    <template v-else-if="mode === 'weekly'">
      <div class="max-w-48">
        <Field :label="t('groups.tasks.schedules.dialog.time')">
          <Input v-model="time" type="time" />
        </Field>
      </div>
      <fieldset class="m-0 flex min-w-0 flex-col gap-2 border-0 p-0">
        <div class="flex flex-wrap items-center gap-2">
          <legend class="text-sm font-medium text-ink">
            {{ t('groups.tasks.schedules.dialog.days') }}
          </legend>
          <div class="ml-auto flex flex-wrap items-center gap-1">
            <button
              v-for="preset in presets"
              :key="preset.key"
              type="button"
              class="cursor-pointer rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors focus-visible:focus-ring"
              :class="
                sameDays(days, preset.days)
                  ? 'bg-selected text-primary'
                  : 'bg-fill text-muted hover:bg-hover hover:text-ink'
              "
              :aria-pressed="sameDays(days, preset.days)"
              @click="days = [...preset.days]"
            >
              {{ t(`groups.tasks.schedules.dialog.presets.${preset.key}`) }}
            </button>
          </div>
        </div>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="day in weekdays"
            :key="day"
            type="button"
            class="inline-flex h-8 min-w-10 cursor-pointer items-center justify-center rounded-full border px-2.5 text-xs font-medium transition-colors focus-visible:focus-ring pointer-coarse:min-h-9"
            :class="
              days.includes(day)
                ? 'border-primary bg-primary text-on-primary'
                : 'border-line-strong bg-surface text-ink-2 hover:bg-hover hover:text-ink'
            "
            :aria-pressed="days.includes(day)"
            @click="toggleDay(day)"
          >
            {{ t(`groups.tasks.schedules.weekdays.${day}`) }}
          </button>
        </div>
      </fieldset>
    </template>
    <Field v-else-if="mode === 'every'" :label="t('groups.tasks.schedules.dialog.every')">
      <div class="flex flex-wrap gap-2">
        <div class="w-36"><NumberInput v-model="every" :min="1" /></div>
        <div class="w-28">
          <Select
            :id="unitId"
            v-model="unit"
            :options="units"
            :aria-label="t('groups.tasks.schedules.dialog.unit')"
          />
        </div>
      </div>
    </Field>
    <Field v-else :label="t('groups.tasks.schedules.dialog.custom')">
      <Input v-model="custom" mono :placeholder="t('groups.tasks.schedules.dialog.customPlaceholder')" />
    </Field>
    <p v-if="mode === 'once' && once === ''" role="alert" class="text-xs text-error">
      {{ t('groups.tasks.schedules.dialog.skipped', { timezone }) }}
    </p>
    <p v-else-if="isPast" role="alert" class="text-xs text-error">
      {{ t('groups.tasks.schedules.dialog.inPast') }}
    </p>
    <p class="text-xs text-muted">
      {{ t('groups.tasks.schedules.dialog.timezone', { timezone }) }}
      <template v-if="developerDetails && value">
        ·
        <span class="font-mono">{{ t('groups.tasks.schedules.dialog.saved', { value }) }}</span>
      </template>
    </p>
  </div>
</template>
