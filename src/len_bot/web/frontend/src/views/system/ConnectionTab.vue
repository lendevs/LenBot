<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { PlugZap } from '@lucide/vue'
import type { SettingsSnapshot } from '../../api/settings'
import {
  runningSystemOf,
  systemApi,
  systemOf,
  type ChatPlatform,
  type Connection,
  type FeishuLink,
  type OneBot,
  type OneBotCommon,
  type SavedOneBot,
  type SavedTelegram,
  type TelegramLink,
} from '../../api/system'
import { host } from '../../api/hostStore'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import Collapsible from '../../ui/Collapsible.vue'
import Combobox from '../../ui/Combobox.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
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
import { same, useSettingsDraft } from './draft'

const emit = defineEmits<{ dirty: [value: boolean] }>()

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

function normalizedOnebot(item: OneBot): OneBot {
  const http_url = item.action_transport === 'http' ? item.http_url?.trim() || null : null
  return item.mode === 'forward_ws'
    ? { ...item, ws_url: item.ws_url.trim(), http_url }
    : { ...item, listen_host: item.listen_host.trim(), http_url }
}

function stripOnebot(item: SavedOneBot | OneBot | null | undefined): OneBot | null {
  if (!item) return null
  const { access_token_configured: _configured, ...rest } = item as SavedOneBot
  return normalizedOnebot(rest as OneBot)
}

function normalizedTelegram(item: SavedTelegram | TelegramLink | null | undefined): TelegramLink | null {
  if (!item) return null
  const { bot_id: _bot, ...rest } = item as SavedTelegram
  return {
    ...rest,
    api_url: rest.api_url.trim().replace(/\/+$/, ''),
    proxy: rest.proxy?.trim() || null,
  }
}

function normalizedFeishu(item: FeishuLink | null | undefined): FeishuLink | null {
  if (!item) return null
  return { ...item, app_id: item.app_id.trim() }
}

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
    onebotTest.reset()
    telegramTest.reset()
    feishuTest.reset()
  },
  save: (value): Promise<SettingsSnapshot> => {
    const { qq, ...rest } = value
    return systemApi.saveConnection({
      ...rest,
      onebot: value.onebot && normalizedOnebot(value.onebot),
      ...(value.onebot && needsQq.value ? { bot_id: `onebot:${qq.trim()}` } : {}),
      telegram: value.telegram && {
        ...value.telegram,
        api_url: value.telegram.api_url.trim(),
        proxy: value.telegram.proxy?.trim() || null,
      },
      feishu: value.feishu && normalizedFeishu(value.feishu),
      owners: connection.value!.owners,
      access_token: token.value || null,
      telegram_token: telegramToken.value.trim() || null,
      feishu_secret: feishuSecret.value || null,
    })
  },
})
const { settings, draft } = form
watch(form.dirty, (dirty) => emit('dirty', dirty), { immediate: true })
watch([token, telegramToken, feishuSecret], () => form.clearError())

const connection = computed<Connection | undefined>(() =>
  settings.data.value ? systemOf(settings.data.value).connection : undefined,
)
const runningConnection = computed<Connection | undefined>(() =>
  settings.data.value ? runningSystemOf(settings.data.value)?.connection : undefined,
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
    const matches = saved && saved.app_id === current.app_id && saved.domain === current.domain
    if (!matches && current.bot_id === saved?.bot_id) current.bot_id = ''
    if (matches && !current.bot_id) current.bot_id = saved.bot_id
  },
)

const onebotTest = useMutation({
  mutationFn: () =>
    systemApi.testConnection({
      platform: 'onebot',
      onebot: normalizedOnebot(link.value!),
      access_token: token.value || null,
    }),
  onSuccess: (result) => {
    if (needsQq.value && draft.value && !draft.value.qq.trim()) draft.value.qq = result.name
  },
})
const telegramTest = useMutation({
  mutationFn: () =>
    systemApi.testConnection({
      platform: 'telegram',
      telegram: {
        ...telegram.value!,
        api_url: telegram.value!.api_url.trim(),
        proxy: telegram.value!.proxy?.trim() || null,
      },
      telegram_token: telegramToken.value.trim() || null,
    }),
})
const feishuTest = useMutation({
  mutationFn: () =>
    systemApi.testConnection({
      platform: 'feishu',
      feishu: normalizedFeishu(feishu.value!)!,
      feishu_secret: feishuSecret.value || null,
    }),
  onSuccess: (result) => {
    if (feishu.value) feishu.value.bot_id = result.bot_id
  },
})
watch([link, token], () => onebotTest.reset(), { deep: true })
watch([telegram, telegramToken], () => telegramTest.reset(), { deep: true })
watch(
  () => [
    feishu.value?.app_id,
    feishu.value?.domain,
    feishu.value?.request_timeout_seconds,
    feishuSecret.value,
  ],
  () => feishuTest.reset(),
)

function runningActive(name: ChatPlatform): boolean | null {
  const state = host.state?.connection
  if (!state) return null
  if (state.platforms) return name in state.platforms
  return name === 'onebot' ? state.mode !== 'simulated' : false
}

/** The running host's real connection state for each platform, independent of unsaved draft toggles. */
function status(name: ChatPlatform): { tone: 'success' | 'warning' | 'neutral'; label: string } | null {
  const state = host.state?.connection
  if (!state) return null
  if (state.platforms) {
    if (!(name in state.platforms)) return { tone: 'neutral', label: t('system.connection.status.off') }
    return state.platforms[name]
      ? { tone: 'success', label: t('system.connection.status.connected') }
      : { tone: 'warning', label: t('system.connection.status.disconnected') }
  }
  if (name !== 'onebot' || state.mode === 'simulated')
    return { tone: 'neutral', label: t('system.connection.status.off') }
  return state.connected
    ? { tone: 'success', label: t('system.connection.status.connected') }
    : { tone: 'warning', label: t('system.connection.status.disconnected') }
}

/** Whether saved settings or the current draft for this platform differ from the running host. */
function pendingRestart(name: ChatPlatform): boolean {
  const active = runningActive(name)
  const run = runningConnection.value
  const saved = connection.value
  if (name === 'onebot') {
    if (active !== null && (active !== Boolean(saved?.onebot) || active !== Boolean(link.value))) return true
    if (token.value) return true
    if (!run) return false
    const runningVal = stripOnebot(run.onebot)
    return !same(runningVal, stripOnebot(saved?.onebot)) || !same(runningVal, stripOnebot(link.value))
  }
  if (name === 'telegram') {
    if (active !== null && (active !== Boolean(saved?.telegram) || active !== Boolean(telegram.value)))
      return true
    if (telegramToken.value.trim()) return true
    if (!run) return false
    const runningVal = normalizedTelegram(run.telegram)
    return (
      !same(runningVal, normalizedTelegram(saved?.telegram)) ||
      !same(runningVal, normalizedTelegram(telegram.value))
    )
  }
  if (active !== null && (active !== Boolean(saved?.feishu) || active !== Boolean(feishu.value))) return true
  if (feishuSecret.value) return true
  if (!run) return false
  const runningVal = normalizedFeishu(run.feishu)
  return (
    !same(runningVal, normalizedFeishu(saved?.feishu)) || !same(runningVal, normalizedFeishu(feishu.value))
  )
}

const transports = [
  { value: 'websocket' as const, label: 'WebSocket' },
  { value: 'http' as const, label: 'HTTP' },
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
  const at = (item: OneBot) => [
    item.mode,
    item.mode === 'forward_ws' ? item.ws_url.trim() : null,
    item.action_transport === 'http' ? item.http_url?.trim() || null : null,
  ]
  return JSON.stringify(at(before)) !== JSON.stringify(at(after))
})
const telegramSaved = computed(() => connection.value?.telegram ?? null)
const telegramMoved = computed(
  () =>
    Boolean(telegramSaved.value && telegram.value) &&
    telegramSaved.value!.api_url.trim().replace(/\/+$/, '') !==
      telegram.value!.api_url.trim().replace(/\/+$/, ''),
)
const feishuSaved = computed(() => connection.value?.feishu ?? null)
const feishuMoved = computed(
  () =>
    Boolean(feishuSaved.value && feishu.value) &&
    (feishuSaved.value!.app_id.trim() !== feishu.value!.app_id.trim() ||
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
  const onebot = current.onebot
  if (onebot) {
    for (const [key] of linkNumbers) if (onebot[key] === null) result[key] = required
    if (onebot.mode === 'forward_ws' && !/^wss?:\/\/[^/]+/.test(onebot.ws_url.trim()))
      result.ws_url = t('system.connection.wsRule')
    if (onebot.mode === 'reverse_ws') {
      if (!onebot.listen_host.trim()) result.listen_host = required
      if (onebot.listen_port === null) result.listen_port = required
    }
    if (onebot.action_transport === 'http' && !httpUrl(onebot.http_url ?? ''))
      result.http_url = t('system.connection.httpRule')
    if (addressChanged.value && tokenConfigured.value && !token.value)
      result.token = t('system.connection.tokenAgain')
    if (needsQq.value && !/^[1-9][0-9]*$/.test(current.qq.trim())) result.qq = t('system.connection.qqRule')
  }
  const tg = current.telegram
  if (tg) {
    const typed = telegramToken.value.trim()
    if (typed && !TELEGRAM_TOKEN.test(typed)) result.telegramToken = t('system.connection.telegram.tokenRule')
    else if (!typed && !telegramSaved.value) result.telegramToken = required
    else if (!typed && telegramMoved.value) result.telegramToken = t('system.connection.telegram.tokenAgain')
    if (!httpUrl(tg.api_url)) result.telegramApi = t('system.connection.httpRule')
    if (tg.proxy?.trim() && !httpUrl(tg.proxy)) result.telegramProxy = t('system.connection.httpRule')
    if (tg.request_timeout_seconds === null) result.telegramTimeout = required
    if (tg.poll_timeout_seconds === null) result.telegramPoll = required
  }
  const fs = current.feishu
  if (fs) {
    if (!/^cli_[A-Za-z0-9]+$/.test(fs.app_id.trim())) result.feishuApp = t('system.connection.feishu.appRule')
    if (!feishuSecret.value && (!feishuSaved.value || feishuMoved.value))
      result.feishuSecret = feishuSaved.value ? t('system.connection.feishu.secretAgain') : required
    if (!result.feishuApp && !result.feishuSecret && !fs.bot_id)
      result.feishuBot = t('system.connection.feishu.testFirst')
    if (fs.request_timeout_seconds === null) result.feishuTimeout = required
  }
  return result
})
const invalid = computed(() => Object.keys(errors.value).length > 0)

const onebotAdvancedKeys = ['http_url', ...linkNumbers.map(([key]) => key)]
const telegramAdvancedKeys = ['telegramApi', 'telegramTimeout', 'telegramPoll']
const feishuAdvancedKeys = ['feishuTimeout']
const generalAdvancedKeys = [...numbers.map(([key]) => key), ...deliveryNumbers.map(([key]) => key)]

const onebotAdvanced = ref(false)
const telegramAdvanced = ref(false)
const feishuAdvanced = ref(false)
const generalAdvanced = ref(false)

const onebotAdvancedError = computed(() => onebotAdvancedKeys.some((key) => Boolean(errors.value[key])))
const telegramAdvancedError = computed(() => telegramAdvancedKeys.some((key) => Boolean(errors.value[key])))
const feishuAdvancedError = computed(() => feishuAdvancedKeys.some((key) => Boolean(errors.value[key])))
const generalAdvancedError = computed(() => generalAdvancedKeys.some((key) => Boolean(errors.value[key])))

watch(onebotAdvancedError, (has) => has && (onebotAdvanced.value = true))
watch(telegramAdvancedError, (has) => has && (telegramAdvanced.value = true))
watch(feishuAdvancedError, (has) => has && (feishuAdvanced.value = true))
watch(generalAdvancedError, (has) => has && (generalAdvanced.value = true))

const onebotTestDisabled = computed(() =>
  Boolean(
    errors.value.ws_url ||
    errors.value.listen_host ||
    errors.value.listen_port ||
    errors.value.token ||
    onebotAdvancedError.value,
  ),
)
</script>

<template>
  <Skeleton v-if="settings.isPending.value" :lines="8" />
  <ErrorNote
    v-else-if="settings.isError.value"
    :title="t('system.readFailed')"
    :error="settings.error.value"
    :retry="settings.refetch"
  />
  <div v-else-if="draft && connection" class="flex min-w-0 max-w-3xl flex-col gap-4">
    <div class="flex min-w-0 flex-col gap-6">
      <FormSection :title="t('system.connection.qq')">
        <template #actions>
          <Badge v-if="status('onebot')" :tone="status('onebot')!.tone" dot>
            {{ status('onebot')!.label }}
          </Badge>
          <Badge v-if="pendingRestart('onebot')" tone="warning">
            {{ t('system.connection.status.pendingRestart') }}
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
          <div class="flex flex-col gap-3 sm:col-span-2">
            <div>
              <Button
                :icon="PlugZap"
                :loading="onebotTest.isPending.value"
                :disabled="onebotTestDisabled"
                @click="onebotTest.mutate()"
              >
                {{ t('system.connection.test') }}
              </Button>
            </div>
            <TestResult
              :passed="
                onebotTest.data.value
                  ? t('system.connection.testPassed', { name: onebotTest.data.value.name })
                  : null
              "
              :error="onebotTest.error.value"
              :failed-title="t('system.connection.testFailed')"
            />
          </div>
          <Collapsible
            v-model:open="onebotAdvanced"
            :title="t('system.connection.advanced')"
            :dot="onebotAdvancedError ? 'error' : false"
            class="sm:col-span-2"
            content-class="grid gap-x-5 gap-y-5 sm:grid-cols-2"
          >
            <Field :label="t('system.connection.transport')">
              <div>
                <SegmentedControl
                  :model-value="link!.action_transport"
                  :options="transports"
                  :label="t('system.connection.transport')"
                  @update:model-value="(next) => (link!.action_transport = next)"
                />
              </div>
            </Field>
            <Field
              v-if="link!.action_transport === 'http'"
              :label="t('system.connection.httpUrl')"
              :error="errors.http_url"
              required
            >
              <Input
                :model-value="link!.http_url ?? ''"
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
          </Collapsible>
        </template>
      </FormSection>

      <FormSection :title="t('chatPlatforms.telegram')">
        <template #actions>
          <Badge v-if="status('telegram')" :tone="status('telegram')!.tone" dot>
            {{ status('telegram')!.label }}
          </Badge>
          <Badge v-if="pendingRestart('telegram')" tone="warning">
            {{ t('system.connection.status.pendingRestart') }}
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
                :disabled="
                  Boolean(
                    errors.telegramToken ||
                    errors.telegramApi ||
                    errors.telegramProxy ||
                    errors.telegramTimeout,
                  )
                "
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
          <Collapsible
            v-model:open="telegramAdvanced"
            :title="t('system.connection.advanced')"
            :dot="telegramAdvancedError ? 'error' : false"
            class="sm:col-span-2"
            content-class="grid gap-x-5 gap-y-5 sm:grid-cols-2"
          >
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
          </Collapsible>
        </template>
      </FormSection>

      <FormSection :title="t('chatPlatforms.feishu')">
        <template #actions>
          <Badge v-if="status('feishu')" :tone="status('feishu')!.tone" dot>
            {{ status('feishu')!.label }}
          </Badge>
          <Badge v-if="pendingRestart('feishu')" tone="warning">
            {{ t('system.connection.status.pendingRestart') }}
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
                :disabled="Boolean(errors.feishuApp || errors.feishuSecret || errors.feishuTimeout)"
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
          <Collapsible
            v-model:open="feishuAdvanced"
            :title="t('system.connection.advanced')"
            :dot="feishuAdvancedError ? 'error' : false"
            class="sm:col-span-2"
            content-class="grid gap-x-5 gap-y-5 sm:grid-cols-2"
          >
            <Field :label="t('system.connection.feishu.timeout')" :error="errors.feishuTimeout">
              <NumberInput
                :model-value="feishu!.request_timeout_seconds"
                :min="0.1"
                :steppers="false"
                :unit="t('system.seconds')"
                @update:model-value="(number: number | null) => (feishu!.request_timeout_seconds = number)"
              />
            </Field>
          </Collapsible>
        </template>
      </FormSection>

      <FormSection :title="t('system.connection.general')">
        <Field :label="t('system.connection.timezone')" :error="errors.timezone">
          <Combobox v-model="value.timezone" :options="zoneOptions" placeholder="Asia/Shanghai" />
        </Field>
        <Collapsible
          v-model:open="generalAdvanced"
          :title="t('system.connection.advanced')"
          :dot="generalAdvancedError ? 'error' : false"
          class="sm:col-span-2"
          content-class="grid gap-x-5 gap-y-5 sm:grid-cols-2"
        >
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
        </Collapsible>
      </FormSection>
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
