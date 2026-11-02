<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { ChevronDown, PlugZap } from '@lucide/vue'
import type { SettingsSnapshot } from '../../api/settings'
import {
  systemApi,
  systemOf,
  type ChatPlatform,
  type Connection,
  type FeishuLink,
  type OneBot,
  type OneBotCommon,
  type TelegramLink,
} from '../../api/system'
import { host } from '../../api/hostStore'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
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
import Switch from '../../ui/Switch.vue'
import TestResult from '../setup/TestResult.vue'
import { useSettingsDraft } from './draft'

type Draft = Omit<Connection, 'owners' | 'bot_id' | 'delivery' | 'onebot' | 'telegram'> & {
  onebot: OneBot | null
  telegram: TelegramLink | null
  /** The QQ account typed when the root account belongs to another platform. */
  qq: string
}

const TELEGRAM_TOKEN = /^[1-9][0-9]*:[A-Za-z0-9_-]{20,}$/
const TELEGRAM_DEFAULTS: TelegramLink = {
  api_url: 'https://api.telegram.org',
  proxy: null,
  poll_timeout_seconds: 30,
  request_timeout_seconds: 15,
}
const FEISHU_DEFAULTS: FeishuLink = { bot_id: '', app_id: '', domain: 'feishu', request_timeout_seconds: 15 }

const { t } = useI18n()
const token = ref('')
const telegramToken = ref('')
const feishuSecret = ref('')
const pick = (snapshot: SettingsSnapshot): Draft => {
  const { owners: _owners, bot_id: _bot, onebot, telegram, ...rest } = systemOf(snapshot).connection
  const { bot_id: _telegramBot, ...telegramLink } = telegram ?? { bot_id: '' }
  const base = { ...rest, telegram: telegram ? (telegramLink as TelegramLink) : null, qq: '' }
  if (onebot === null) return { ...base, onebot: null }
  const { access_token_configured: _configured, ...link } = onebot
  return { ...base, onebot: link }
}
const form = useSettingsDraft<Draft>({
  pick,
  section: 'connection',
  extra: () => Boolean(token.value || telegramToken.value || feishuSecret.value),
  reset: () => {
    token.value = ''
    telegramToken.value = ''
    feishuSecret.value = ''
    telegramTest.reset()
    feishuTest.reset()
  },
  save: (value): Promise<SettingsSnapshot> => {
    const { qq, ...rest } = value
    return systemApi.saveConnection({
      ...rest,
      onebot: value.onebot && {
        ...value.onebot,
        http_url: value.onebot.action_transport === 'http' ? value.onebot.http_url : null,
      },
      ...(value.onebot && needsQq.value ? { bot_id: `onebot:${qq.trim()}` } : {}),
      telegram: value.telegram && { ...value.telegram, proxy: value.telegram.proxy?.trim() || null },
      owners: connection.value!.owners,
      access_token: token.value || null,
      telegram_token: telegramToken.value.trim() || null,
      feishu_secret: feishuSecret.value || null,
    })
  },
})
const { settings, draft } = form
const connection = computed<Connection | undefined>(() =>
  settings.data.value ? systemOf(settings.data.value).connection : undefined,
)
const value = computed(() => draft.value!)
const link = computed(() => draft.value?.onebot ?? null)
const forward = computed(() => (link.value?.mode === 'forward_ws' ? link.value : null))
const reverse = computed(() => (link.value?.mode === 'reverse_ws' ? link.value : null))
/** OneBot logs in as the root account, so an instance set up on another platform names its QQ account here. */
const needsQq = computed(() => Boolean(connection.value && !connection.value.bot_id.startsWith('onebot:')))

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
        }
      : {
          action_transport: 'websocket',
          http_url: null,
          request_timeout_seconds: 10,
          ping_interval_seconds: 20,
          ping_timeout_seconds: 20,
          max_frame_bytes: 1048576,
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

const telegramOn = computed({
  get: () => Boolean(draft.value?.telegram),
  set: (on: boolean) => {
    if (!draft.value) return
    const saved = connection.value?.telegram
    draft.value.telegram = on ? { ...TELEGRAM_DEFAULTS, ...(saved ? withoutBot(saved) : {}) } : null
    if (!on) telegramToken.value = ''
  },
})
const feishuOn = computed({
  get: () => Boolean(draft.value?.feishu),
  set: (on: boolean) => {
    if (!draft.value) return
    draft.value.feishu = on ? { ...FEISHU_DEFAULTS, ...(connection.value?.feishu ?? {}) } : null
    if (!on) feishuSecret.value = ''
  },
})
function withoutBot(saved: TelegramLink & { bot_id: string }): TelegramLink {
  const { bot_id: _bot, ...rest } = saved
  return rest
}
const telegram = computed(() => draft.value?.telegram ?? null)
const feishu = computed(() => draft.value?.feishu ?? null)
const domains = computed(() => [
  { value: 'feishu', label: t('chatPlatforms.feishu') },
  { value: 'lark', label: 'Lark' },
])
/** Another app or domain has another bot, found again by the test. */
watch(
  () => [feishu.value?.app_id, feishu.value?.domain],
  () => {
    const saved = connection.value?.feishu
    const current = feishu.value
    if (!current) return
    const same = saved && saved.app_id === current.app_id && saved.domain === current.domain
    if (!same && current.bot_id === saved?.bot_id) current.bot_id = ''
    if (same && !current.bot_id) current.bot_id = saved.bot_id
  },
)

const telegramTest = useMutation({
  mutationFn: () =>
    systemApi.testConnection({
      platform: 'telegram',
      telegram: { ...telegram.value!, proxy: telegram.value!.proxy?.trim() || null },
      telegram_token: telegramToken.value.trim() || null,
    }),
})
const feishuTest = useMutation({
  mutationFn: () =>
    systemApi.testConnection({
      platform: 'feishu',
      feishu: feishu.value!,
      feishu_secret: feishuSecret.value || null,
    }),
  onSuccess: (result) => {
    if (feishu.value) feishu.value.bot_id = result.bot_id
  },
})
watch([telegram, telegramToken], () => telegramTest.reset(), { deep: true })
watch(
  () => [feishu.value?.app_id, feishu.value?.domain, feishuSecret.value],
  () => feishuTest.reset(),
)

/** The running host's own connection for each platform it runs. */
function status(name: ChatPlatform): { tone: 'success' | 'warning' | 'neutral'; label: string } | null {
  const on = name === 'onebot' ? Boolean(link.value) : name === 'telegram' ? telegramOn.value : feishuOn.value
  if (!on) return { tone: 'neutral', label: t('system.connection.status.off') }
  const running = host.state?.connection.platforms
  if (!running || !(name in running)) return null
  return running[name]
    ? { tone: 'success', label: t('system.connection.status.connected') }
    : { tone: 'warning', label: t('system.connection.status.disconnected') }
}

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
const telegramSaved = computed(() => connection.value?.telegram ?? null)
const telegramMoved = computed(
  () =>
    Boolean(telegramSaved.value && telegram.value) &&
    telegramSaved.value!.api_url.replace(/\/+$/, '') !== telegram.value!.api_url.trim().replace(/\/+$/, ''),
)
const feishuSaved = computed(() => connection.value?.feishu ?? null)
const feishuMoved = computed(
  () =>
    Boolean(feishuSaved.value && feishu.value) &&
    (feishuSaved.value!.app_id !== feishu.value!.app_id ||
      feishuSaved.value!.domain !== feishu.value!.domain),
)

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

const httpUrl = (text: string) => /^https?:\/\/[^/]+/.test(text.trim())
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
    if (link.action_transport === 'http' && !httpUrl(link.http_url ?? ''))
      result.http_url = t('system.connection.httpRule')
    if (addressChanged.value && tokenConfigured.value && !token.value)
      result.token = t('system.connection.tokenAgain')
    if (needsQq.value && !/^[1-9][0-9]*$/.test(current.qq.trim())) result.qq = t('system.connection.qqRule')
  }
  const telegram = current.telegram
  if (telegram) {
    const typed = telegramToken.value.trim()
    if (typed && !TELEGRAM_TOKEN.test(typed)) result.telegramToken = t('system.connection.telegram.tokenRule')
    else if (!typed && !telegramSaved.value) result.telegramToken = required
    else if (!typed && telegramMoved.value) result.telegramToken = t('system.connection.telegram.tokenAgain')
    if (!httpUrl(telegram.api_url)) result.telegramApi = t('system.connection.httpRule')
    if (telegram.proxy?.trim() && !httpUrl(telegram.proxy))
      result.telegramProxy = t('system.connection.httpRule')
    if (telegram.request_timeout_seconds === null) result.telegramTimeout = required
    if (telegram.poll_timeout_seconds === null) result.telegramPoll = required
  }
  const feishu = current.feishu
  if (feishu) {
    if (!/^cli_[A-Za-z0-9]+$/.test(feishu.app_id.trim()))
      result.feishuApp = t('system.connection.feishu.appRule')
    if (!feishuSecret.value && (!feishuSaved.value || feishuMoved.value))
      result.feishuSecret = feishuSaved.value ? t('system.connection.feishu.secretAgain') : required
    if (!result.feishuApp && !result.feishuSecret && !feishu.bot_id)
      result.feishuBot = t('system.connection.feishu.testFirst')
    if (feishu.request_timeout_seconds === null) result.feishuTimeout = required
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
  'telegramApi',
  'telegramTimeout',
  'telegramPoll',
  'feishuTimeout',
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
      <FormSection :title="t('system.connection.qq')">
        <template #actions>
          <Badge v-if="status('onebot')" :tone="status('onebot')!.tone" dot>
            {{ status('onebot')!.label }}
          </Badge>
        </template>
        <Field v-if="!needsQq" :label="t('system.connection.bot')">
          <Input :model-value="connection.bot_id" mono readonly />
        </Field>
        <Field :label="t('system.connection.mode')">
          <Select v-model="mode" :options="modes" />
        </Field>
        <template v-if="link">
          <Field v-if="needsQq" :label="t('system.connection.qqAccount')" :error="errors.qq" required>
            <Input v-model="value.qq" mono inputmode="numeric" placeholder="10001" />
          </Field>
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
      </FormSection>

      <FormSection :title="t('chatPlatforms.telegram')">
        <template #actions>
          <Badge v-if="status('telegram')" :tone="status('telegram')!.tone" dot>
            {{ status('telegram')!.label }}
          </Badge>
          <Switch v-model="telegramOn" :aria-label="t('chatPlatforms.telegram')" />
        </template>
        <template v-if="telegram">
          <Field v-if="telegramSaved" :label="t('system.connection.bot')">
            <Input :model-value="telegramSaved.bot_id" mono readonly />
          </Field>
          <Field :label="t('system.connection.telegram.token')" :error="errors.telegramToken" required wide>
            <Input
              v-model="telegramToken"
              type="password"
              autocomplete="new-password"
              mono
              :placeholder="telegramSaved ? t('system.connection.tokenKept') : undefined"
            />
          </Field>
          <Field :label="t('system.connection.telegram.proxy')" :error="errors.telegramProxy" wide>
            <Input
              :model-value="telegram!.proxy ?? ''"
              type="url"
              mono
              placeholder="http://127.0.0.1:7890"
              @update:model-value="(text: string) => (telegram!.proxy = text.trim() ? text : null)"
            />
          </Field>
          <div class="flex flex-col gap-3 sm:col-span-2">
            <div>
              <Button
                :icon="PlugZap"
                :loading="telegramTest.isPending.value"
                :disabled="Boolean(errors.telegramToken || errors.telegramApi || errors.telegramProxy)"
                @click="telegramTest.mutate()"
              >
                {{ t('system.connection.test') }}
              </Button>
            </div>
            <TestResult
              :passed="
                telegramTest.data.value
                  ? t('system.connection.testPassed', { name: telegramTest.data.value.name })
                  : null
              "
              :error="telegramTest.error.value"
              :failed-title="t('system.connection.testFailed')"
            />
          </div>
        </template>
      </FormSection>

      <FormSection :title="t('chatPlatforms.feishu')">
        <template #actions>
          <Badge v-if="status('feishu')" :tone="status('feishu')!.tone" dot>
            {{ status('feishu')!.label }}
          </Badge>
          <Switch v-model="feishuOn" :aria-label="t('chatPlatforms.feishu')" />
        </template>
        <template v-if="feishu">
          <Field :label="t('system.connection.feishu.appId')" :error="errors.feishuApp" required>
            <Input v-model="feishu.app_id" mono placeholder="cli_" />
          </Field>
          <Field :label="t('system.connection.feishu.secret')" :error="errors.feishuSecret" required>
            <Input
              v-model="feishuSecret"
              type="password"
              autocomplete="new-password"
              mono
              :placeholder="feishuSaved && !feishuMoved ? t('system.connection.tokenKept') : undefined"
            />
          </Field>
          <Field :label="t('system.connection.feishu.domain')">
            <Select v-model="feishu.domain" :options="domains" />
          </Field>
          <Field :label="t('system.connection.bot')" :error="errors.feishuBot">
            <Input :model-value="feishu.bot_id" mono readonly />
          </Field>
          <div class="flex flex-col gap-3 sm:col-span-2">
            <div>
              <Button
                :icon="PlugZap"
                :loading="feishuTest.isPending.value"
                :disabled="Boolean(errors.feishuApp || errors.feishuSecret)"
                @click="feishuTest.mutate()"
              >
                {{ t('system.connection.test') }}
              </Button>
            </div>
            <TestResult
              :passed="
                feishuTest.data.value
                  ? t('system.connection.testPassed', { name: feishuTest.data.value.name })
                  : null
              "
              :error="feishuTest.error.value"
              :failed-title="t('system.connection.testFailed')"
            />
          </div>
        </template>
      </FormSection>

      <FormSection :title="t('system.connection.general')">
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
          </div>
          <div v-if="telegram" class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
            <Field :label="t('system.connection.telegram.apiUrl')" :error="errors.telegramApi" required wide>
              <Input
                :model-value="telegram!.api_url"
                mono
                placeholder="https://api.telegram.org"
                @update:model-value="(text: string) => (telegram!.api_url = text)"
              />
            </Field>
            <Field :label="t('system.connection.telegram.poll')" :error="errors.telegramPoll">
              <NumberInput
                :model-value="telegram!.poll_timeout_seconds"
                :min="1"
                :max="50"
                snap
                :steppers="false"
                :unit="t('system.seconds')"
                @update:model-value="(number: number | null) => (telegram!.poll_timeout_seconds = number)"
              />
            </Field>
            <Field :label="t('system.connection.telegram.timeout')" :error="errors.telegramTimeout">
              <NumberInput
                :model-value="telegram!.request_timeout_seconds"
                :min="0.1"
                :steppers="false"
                :unit="t('system.seconds')"
                @update:model-value="(number: number | null) => (telegram!.request_timeout_seconds = number)"
              />
            </Field>
          </div>
          <div v-if="feishu" class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
            <Field :label="t('system.connection.feishu.timeout')" :error="errors.feishuTimeout">
              <NumberInput
                v-model="feishu.request_timeout_seconds"
                :min="0.1"
                :steppers="false"
                :unit="t('system.seconds')"
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
