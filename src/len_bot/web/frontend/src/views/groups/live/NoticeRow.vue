<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { TimelineNotice } from '../../../api/timeline'
import { developerDetails } from '../../../composables/useDeveloperMode.js'
import { formatDateTime } from '../../../i18n/format'
import RawRecord from '../tasks/RawRecord.vue'

const props = defineProps<{
  notice: TimelineNotice
  timeZone: string
  nameOf: (uid: string) => string
}>()

const { t, te } = useI18n()
const prefix = 'groups.live.notices'
const person = (uid: string | null, known: string | null) => known ?? (uid ? props.nameOf(uid) : t(`${prefix}.someone`))
/** Platform fields this sentence uses; OneBot sends them as they are named here. */
const field = (key: string) => {
  const value = props.notice.raw[key]
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}
const text = computed(() => {
  const { kind, sub_type: sub, user_id, user_name, operator_id, operator_name, duration } = props.notice
  const values = {
    name: person(user_id, user_name),
    operator: person(operator_id, operator_name),
    duration: t(`${prefix}.minutes`, { n: Math.max(1, Math.round((duration ?? 0) / 60)) }),
    card: field('card_new'),
    file: (props.notice.raw.file as { name?: string } | undefined)?.name ?? '',
    sub: sub ?? '',
    kind,
  }
  const operated = operator_id !== null && operator_id !== user_id && !operator_id.endsWith(':0')
  if (kind === 'group_decrease' && (sub === 'kick' || sub === 'kick_me')) return t(`${prefix}.kicked`, values)
  if (kind === 'group_recall' && operated) return t(`${prefix}.recalledBy`, values)
  if (kind === 'group_ban') return t(sub === 'lift_ban' ? `${prefix}.liftBan` : `${prefix}.group_ban`, values)
  if (kind === 'group_card' && !values.card) return t(`${prefix}.cardCleared`, values)
  return te(`${prefix}.${kind}`) ? t(`${prefix}.${kind}`, values) : t(`${prefix}.other`, values)
})
</script>

<template>
  <div class="flex flex-col items-center gap-1 px-4 py-1.5 text-center">
    <p class="max-w-full rounded-full bg-fill px-3 py-1 text-xs break-words text-muted">
      {{ text }} · <span class="tabular">{{ formatDateTime(notice.time, { timeZone }) }}</span>
    </p>
    <RawRecord v-if="developerDetails" :label="t(`${prefix}.raw`)" :code="notice.raw" class="w-full max-w-lg text-left" />
  </div>
</template>
