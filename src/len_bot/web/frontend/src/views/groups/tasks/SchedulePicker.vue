<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { developerDetails } from '../../../composables/useDeveloperMode'
import Checkbox from '../../../ui/Checkbox.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Select from '../../../ui/Select.vue'

/** Builds the `when` of a reminder: an ISO time with the group's offset, `every <n><unit>`, or a cron line. */
const props = defineProps<{ timezone: string }>()
const model = defineModel<string>({ default: '' })

type Mode = 'once' | 'weekly' | 'every' | 'custom'
const { t } = useI18n()
const mode = ref<Mode>('once')
const date = ref(new Date().toLocaleDateString('sv-SE', { timeZone: props.timezone }))
const time = ref('09:00')
const days = ref<number[]>([1, 2, 3, 4, 5, 6, 0])
const every = ref<number | null>(1)
const unit = ref<'m' | 'h' | 'd'>('h')
const custom = ref('')

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

/** Minutes the zone is ahead of UTC at an instant. */
function offsetAt(instant: number): number {
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
      .map((part) => [part.type, part.value]),
  )
  const local = Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour, +parts.minute, +parts.second)
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
const clock = computed(() => (/^\d{2}:\d{2}/.test(time.value) ? time.value.slice(0, 5) : ''))
const once = computed(() =>
  /^\d{4}-\d{2}-\d{2}$/.test(date.value) && clock.value ? withOffset(date.value, clock.value) : null,
)
const value = computed(() => {
  if (mode.value === 'custom') return custom.value.trim()
  if (mode.value === 'every') return every.value && every.value > 0 ? `every ${every.value}${unit.value}` : ''
  if (!clock.value) return ''
  if (mode.value === 'once') return once.value ?? ''
  if (!days.value.length) return ''
  const [h, mi] = clock.value.split(':').map(Number)
  const week = days.value.length === 7 ? '*' : [...days.value].sort().join(',')
  return `cron:${mi} ${h} * * ${week}`
})
watch(value, (text) => (model.value = text), { immediate: true })

function toggle(day: number, on: boolean) {
  days.value = on ? [...days.value, day] : days.value.filter((item) => item !== day)
}
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
    <div v-if="mode === 'once'" class="grid grid-cols-2 gap-3">
      <Field :label="t('groups.tasks.schedules.dialog.date')"><Input v-model="date" type="date" /></Field>
      <Field :label="t('groups.tasks.schedules.dialog.time')"><Input v-model="time" type="time" /></Field>
    </div>
    <template v-else-if="mode === 'weekly'">
      <Field :label="t('groups.tasks.schedules.dialog.time')" class="max-w-48">
        <Input v-model="time" type="time" />
      </Field>
      <fieldset class="m-0 flex min-w-0 flex-col gap-1.5 border-0 p-0">
        <legend class="mb-1.5 text-sm font-medium text-ink">
          {{ t('groups.tasks.schedules.dialog.days') }}
        </legend>
        <div class="flex flex-wrap gap-x-4 gap-y-2">
          <label v-for="day in weekdays" :key="day" class="flex cursor-pointer items-center gap-1.5 text-sm">
            <Checkbox
              :model-value="days.includes(day)"
              @update:model-value="(on) => toggle(day, on === true)"
            />
            {{ t(`groups.tasks.schedules.weekdays.${day}`) }}
          </label>
        </div>
      </fieldset>
    </template>
    <Field v-else-if="mode === 'every'" :label="t('groups.tasks.schedules.dialog.every')">
      <div class="flex gap-2">
        <NumberInput v-model="every" :min="1" class="w-36" />
        <div class="w-28"><Select v-model="unit" :options="units" /></div>
      </div>
    </Field>
    <Field v-else :label="t('groups.tasks.schedules.dialog.custom')">
      <Input v-model="custom" mono :placeholder="t('groups.tasks.schedules.dialog.customPlaceholder')" />
    </Field>
    <p v-if="mode === 'once' && once === ''" role="alert" class="text-xs text-error">
      {{ t('groups.tasks.schedules.dialog.skipped', { timezone }) }}
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
