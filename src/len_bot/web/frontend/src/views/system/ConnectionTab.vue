<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown } from '@lucide/vue'
import type { SettingsSnapshot } from '../../api/settings'
import { systemApi, systemOf, type Connection, type OneBot, type OneBotCommon } from '../../api/system'
import ErrorNote from '../../ui/ErrorNote.vue'
import Combobox from '../../ui/Combobox.vue'
import Field from '../../ui/Field.vue'
import FormSection from '../../ui/FormSection.vue'
import Input from '../../ui/Input.vue'
import NumberInput from '../../ui/NumberInput.vue'
import SaveBar from '../../ui/SaveBar.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import Select from '../../ui/Select.vue'
import Skeleton from '../../ui/Skeleton.vue'
import { confirm } from '../../ui/confirm'
import { useSettingsDraft } from './draft'

type Draft = Omit<Connection, 'owners' | 'bot_id' | 'telegram' | 'onebot'> & { onebot: OneBot | null }

const { t } = useI18n()
const token = ref('')
const pick = (snapshot: SettingsSnapshot): Draft => {
  const {
    owners: _owners,
    bot_id: _bot,
    telegram: _telegram,
    onebot,
    ...rest
  } = systemOf(snapshot).connection
  if (onebot === null) return { ...rest, onebot: null }
  const { access_token_configured: _configured, ...link } = onebot
  return { ...rest, onebot: link }
}
const form = useSettingsDraft<Draft>({
  pick,
  section: 'connection',
  extra: () => token.value !== '',
  reset: () => (token.value = ''),
  save: (value): Promise<SettingsSnapshot> =>
    systemApi.saveConnection({
      ...value,
      onebot: value.onebot && {
        ...value.onebot,
        http_url: value.onebot.action_transport === 'http' ? value.onebot.http_url : null,
      },
      owners: connection.value!.owners,
      access_token: token.value || null,
    }),
  confirm: async (value): Promise<boolean> => {
    if (value.delivery === 'simulated' || connection.value?.delivery !== 'simulated') return true
    return confirm({
      title: t('system.connection.realTitle'),
      message: t('system.connection.realMessage', { platform: telegram.value ? 'Telegram' : 'QQ' }),
      confirmLabel: t('common.save'),
      tone: 'danger',
    })
  },
})
const { settings, draft } = form
const connection = computed<Connection | undefined>(() =>
  settings.data.value ? systemOf(settings.data.value).connection : undefined,
)
/** A Telegram host keeps its transport in the config file; only delivery and the shared fields change here. */
const telegram = computed<boolean>(() => Boolean(connection.value?.telegram))
const value = computed(() => draft.value!)
const link = computed(() => draft.value?.onebot ?? null)
const forward = computed(() => (link.value?.mode === 'forward_ws' ? link.value : null))
const reverse = computed(() => (link.value?.mode === 'reverse_ws' ? link.value : null))

const modes = computed(() => [
  { value: 'none', label: t('system.connection.modes.none') },
  { value: 'forward_ws', label: t('system.connection.modes.forward_ws') },
  { value: 'reverse_ws', label: t('system.connection.modes.reverse_ws') },
])
const mode = computed({
  get: () => draft.value?.onebot?.mode ?? 'none',
  set: (next: string) => {
    const current = draft.value
    if (!current) return
    if (next === 'none') {
      current.onebot = null
      current.delivery = 'simulated'
      token.value = ''
      return
    }
    const base = current.onebot
    const common: OneBotCommon = base
      ? {
          action_transport: base.action_transport,
          http_url: base.http_url,
          request_timeout_seconds: base.request_timeout_seconds,
          ping_interval_seconds: base.ping_interval_seconds,
          ping_timeout_seconds: base.ping_timeout_seconds,
          max_frame_bytes: base.max_frame_bytes,
          upload_visible_root: base.upload_visible_root,
        }
      : {
          action_transport: 'websocket',
          http_url: null,
          request_timeout_seconds: 10,
          ping_interval_seconds: 20,
          ping_timeout_seconds: 20,
          max_frame_bytes: 1048576,
          upload_visible_root: null,
        }
    current.onebot =
      next === 'forward_ws'
        ? {
            ...common,
            mode: 'forward_ws',
            ws_url: base?.mode === 'forward_ws' ? base.ws_url : 'ws://127.0.0.1:3001',
          }
        : {
            ...common,
            mode: 'reverse_ws',
            listen_host: base?.mode === 'reverse_ws' ? base.listen_host : '127.0.0.1',
            listen_port: base?.mode === 'reverse_ws' ? base.listen_port : 8080,
          }
  },
})
const deliveries = computed(() => [
  {
    value: telegram.value ? 'telegram' : 'onebot',
    label: t('system.connection.real', { platform: telegram.value ? 'Telegram' : 'QQ' }),
  },
  { value: 'simulated', label: t('system.connection.simulated') },
])
const transports = [
  { value: 'websocket', label: 'WebSocket' },
  { value: 'http', label: 'HTTP' },
]
const zones = (() => {
  try {
    return Intl.supportedValuesOf('timeZone').map((zone) => ({ value: zone, label: zone }))
  } catch {
    return []
  }
})()
const zoneOptions = computed(() =>
  draft.value && !zones.some((zone) => zone.value === draft.value!.timezone)
    ? [{ value: draft.value.timezone, label: draft.value.timezone }, ...zones]
    : zones,
)

const tokenConfigured = computed(() => Boolean(connection.value?.onebot?.access_token_configured))
/** Changing where LenBot connects needs the token typed again, so an old token is not sent to a new address. */
const addressChanged = computed(() => {
  const before = connection.value?.onebot
  const after = draft.value?.onebot
  if (!before || !after) return false
  const at = (link: OneBot) => [
    link.mode,
    link.mode === 'forward_ws' ? link.ws_url : null,
    link.action_transport === 'http' ? link.http_url : null,
  ]
  return JSON.stringify(at(before)) !== JSON.stringify(at(after))
})

const numbers = [
  ['max_steps', 1, false],
  ['turn_timeout_seconds', 1, true],
  ['max_model_requests', 1, false],
] as const
const deliveryNumbers = [
  ['max_chars', 1, false],
  ['chars_per_second', 0.1, true],
  ['min_interval_seconds', 0, true],
  ['max_interval_seconds', 0, true],
] as const
const linkNumbers = [
  ['request_timeout_seconds', 0.1, true],
  ['ping_interval_seconds', 0.1, true],
  ['ping_timeout_seconds', 0.1, true],
  ['max_frame_bytes', 1024, false],
] as const

const errors = computed(() => {
  const result: Record<string, string> = {}
  const current = draft.value
  if (!current) return result
  const required = t('system.required')
  if (!current.timezone.trim()) result.timezone = required
  for (const [key] of numbers) if (current[key] === null) result[key] = required
  for (const [key] of deliveryNumbers) if (current.text_delivery[key] === null) result[key] = required
  const { min_interval_seconds: min, max_interval_seconds: max } = current.text_delivery
  if (min !== null && max !== null && min > max)
    result.max_interval_seconds = t('system.connection.intervalOrder')
  const link = current.onebot
  if (link) {
    for (const [key] of linkNumbers) if (link[key] === null) result[key] = required
    if (link.mode === 'forward_ws' && !/^wss?:\/\/[^/]+/.test(link.ws_url.trim()))
      result.ws_url = t('system.connection.wsRule')
    if (link.mode === 'reverse_ws') {
      if (!link.listen_host.trim()) result.listen_host = required
      if (link.listen_port === null) result.listen_port = required
    }
    if (link.action_transport === 'http' && !/^https?:\/\/[^/]+/.test((link.http_url ?? '').trim()))
      result.http_url = t('system.connection.httpRule')
    if (addressChanged.value && tokenConfigured.value && !token.value)
      result.token = t('system.connection.tokenAgain')
  }
  return result
})
const invalid = computed(() => Object.keys(errors.value).length > 0)
const advanced = ref(false)
const advancedKeys = new Set<string>([
  ...numbers.map(([key]) => key),
  ...deliveryNumbers.map(([key]) => key),
  ...linkNumbers.map(([key]) => key),
  'http_url',
])
watch(invalid, () => {
  if (Object.keys(errors.value).some((key) => advancedKeys.has(key))) advanced.value = true
})
</script>

<template>
  <Skeleton v-if="settings.isPending.value" :lines="8" />
  <ErrorNote
    v-else-if="settings.isError.value"
    :title="t('system.readFailed')"
    :error="settings.error.value"
    :retry="settings.refetch"
  />
  <div v-else-if="draft && connection" class="flex min-w-0 flex-col gap-4">
    <div class="flex min-w-0 flex-col gap-6 rounded-xl border border-line bg-surface p-5">
      <FormSection :title="telegram ? t('system.connection.telegram') : t('system.connection.qq')">
        <Field :label="t('system.connection.bot')">
          <Input :model-value="connection.bot_id" mono readonly />
        </Field>
        <Field v-if="!telegram" :label="t('system.connection.mode')">
          <Select v-model="mode" :options="modes" />
        </Field>
        <template v-if="link">
          <Field v-if="forward" :label="t('system.connection.wsUrl')" :error="errors.ws_url" required wide>
            <Input
              :model-value="forward!.ws_url"
              mono
              placeholder="ws://127.0.0.1:3001"
              @update:model-value="(text: string) => (forward!.ws_url = text)"
            />
          </Field>
          <template v-if="reverse">
            <Field :label="t('system.connection.listenHost')" :error="errors.listen_host" required>
              <Input v-model="reverse.listen_host" mono placeholder="127.0.0.1" />
            </Field>
            <Field :label="t('system.connection.listenPort')" :error="errors.listen_port" required>
              <NumberInput
                v-model="reverse.listen_port"
                :min="1"
                :max="65535"
                :steppers="false"
                :format-options="{ useGrouping: false }"
              />
            </Field>
          </template>
          <Field :label="t('system.connection.token')" :error="errors.token" wide>
            <Input
              v-model="token"
              type="password"
              autocomplete="new-password"
              :placeholder="
                tokenConfigured ? t('system.connection.tokenKept') : t('system.connection.tokenNone')
              "
            />
          </Field>
        </template>
        <Field :label="t('system.connection.delivery')" wide>
          <div>
            <SegmentedControl
              v-model="value.delivery"
              :options="deliveries"
              :disabled="!telegram && link === null"
              :label="t('system.connection.delivery')"
            />
          </div>
        </Field>
        <Field :label="t('system.connection.timezone')" :error="errors.timezone">
          <Combobox v-model="value.timezone" :options="zoneOptions" placeholder="Asia/Shanghai" />
        </Field>
      </FormSection>

      <section class="border-t border-line pt-6">
        <button
          type="button"
          class="flex w-full cursor-pointer items-center justify-between gap-3 rounded-sm text-left focus-visible:focus-ring"
          :aria-expanded="advanced"
          @click="advanced = !advanced"
        >
          <h3 class="text-base font-semibold text-ink">{{ t('system.connection.advanced') }}</h3>
          <ChevronDown
            :size="18"
            class="text-subtle transition-transform"
            :class="advanced && 'rotate-180'"
            aria-hidden="true"
          />
        </button>
        <div v-if="advanced" class="mt-4 flex flex-col gap-6">
          <div v-if="link" class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
            <Field :label="t('system.connection.transport')">
              <div>
                <SegmentedControl
                  v-model="link.action_transport"
                  :options="transports"
                  :label="t('system.connection.transport')"
                />
              </div>
            </Field>
            <Field
              v-if="link.action_transport === 'http'"
              :label="t('system.connection.httpUrl')"
              :error="errors.http_url"
              required
            >
              <Input
                :model-value="link.http_url ?? ''"
                mono
                placeholder="http://127.0.0.1:3000"
                @update:model-value="(text: string) => (link!.http_url = text.trim() ? text : null)"
              />
            </Field>
            <Field
              v-for="[key, min, decimals] in linkNumbers"
              :key="key"
              :label="t(`system.connection.fields.${key}`)"
              :error="errors[key]"
            >
              <NumberInput
                :model-value="link![key]"
                :min="min"
                :snap="!decimals"
                :steppers="false"
                :unit="key === 'max_frame_bytes' ? 'B' : t('system.seconds')"
                @update:model-value="(number: number | null) => (link![key] = number)"
              />
            </Field>
            <Field :label="t('system.connection.fields.upload_visible_root')">
              <Input
                :model-value="link!.upload_visible_root ?? ''"
                mono
                @update:model-value="
                  (text: string) => (link!.upload_visible_root = text.trim() ? text : null)
                "
              />
            </Field>
          </div>
          <div class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
            <Field
              v-for="[key, min, decimals] in numbers"
              :key="key"
              :label="t(`system.connection.fields.${key}`)"
              :error="errors[key]"
            >
              <NumberInput
                v-model="value[key]"
                :min="min"
                :snap="!decimals"
                :steppers="false"
                :unit="key === 'turn_timeout_seconds' ? t('system.seconds') : undefined"
              />
            </Field>
            <Field
              v-for="[key, min, decimals] in deliveryNumbers"
              :key="key"
              :label="t(`system.connection.fields.${key}`)"
              :error="errors[key]"
            >
              <NumberInput
                v-model="value.text_delivery[key]"
                :min="min"
                :snap="!decimals"
                :steppers="false"
                :unit="
                  key === 'max_chars'
                    ? undefined
                    : key === 'chars_per_second'
                      ? t('system.connection.perSecond')
                      : t('system.seconds')
                "
              />
            </Field>
          </div>
        </div>
      </section>
    </div>
    <SaveBar
      :dirty="form.dirty.value"
      :saving="form.saving.value"
      :error="form.saveError.value"
      :invalid="invalid"
      @save="form.submit"
      @discard="form.discard"
    />
  </div>
</template>
