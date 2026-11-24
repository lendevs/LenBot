<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { TooltipProvider } from 'reka-ui'
import {
  Bot,
  BrainCircuit,
  Copy,
  Ellipsis,
  MessageSquare,
  Moon,
  Pause,
  Pencil,
  Plus,
  RotateCw,
  Search,
  Send,
  Sun,
  Trash,
  Wrench,
} from '@lucide/vue'
import { setThemeMode, themeMode } from '../composables/useThemeMode'
import { currentLocale, localeOptions, setLocale, type Locale } from '../i18n'
import Avatar from '../ui/Avatar.vue'
import Badge from '../ui/Badge.vue'
import Button from '../ui/Button.vue'
import Checkbox from '../ui/Checkbox.vue'
import CodeBlock from '../ui/CodeBlock.vue'
import Collapsible from '../ui/Collapsible.vue'
import Combobox from '../ui/Combobox.vue'
import ConfirmHost from '../ui/ConfirmHost.vue'
import Dialog from '../ui/Dialog.vue'
import DropdownMenu, { type MenuEntry } from '../ui/DropdownMenu.vue'
import EmptyState from '../ui/EmptyState.vue'
import ErrorNote from '../ui/ErrorNote.vue'
import Field from '../ui/Field.vue'
import FormSection from '../ui/FormSection.vue'
import IconButton from '../ui/IconButton.vue'
import Input from '../ui/Input.vue'
import Kbd from '../ui/Kbd.vue'
import MarkdownText from '../ui/MarkdownText.vue'
import NumberInput from '../ui/NumberInput.vue'
import Popover from '../ui/Popover.vue'
import RadioGroup from '../ui/RadioGroup.vue'
import SaveBar from '../ui/SaveBar.vue'
import SegmentedControl from '../ui/SegmentedControl.vue'
import Select from '../ui/Select.vue'
import Sheet from '../ui/Sheet.vue'
import Skeleton from '../ui/Skeleton.vue'
import Sparkline from '../ui/Sparkline.vue'
import Spinner from '../ui/Spinner.vue'
import StatTile from '../ui/StatTile.vue'
import StatusDot from '../ui/StatusDot.vue'
import Switch from '../ui/Switch.vue'
import Tabs from '../ui/Tabs.vue'
import TagInput from '../ui/TagInput.vue'
import Textarea from '../ui/Textarea.vue'
import Timeline from '../ui/Timeline.vue'
import TimelineItem from '../ui/TimelineItem.vue'
import Toaster from '../ui/Toaster.vue'
import Tooltip from '../ui/Tooltip.vue'
import VirtualList from '../ui/VirtualList.vue'
import { confirm } from '../ui/confirm'
import { toast } from '../ui/toast'

const { t } = useI18n()

const themes = computed(() => [
  { value: 'light', label: t('shell.account.themes.light'), icon: Sun },
  { value: 'dark', label: t('shell.account.themes.dark'), icon: Moon },
])
const theme = computed({
  get: () => (themeMode.value === 'dark' ? 'dark' : 'light'),
  set: (value: string) => setThemeMode(value),
})
const locale = computed({ get: () => currentLocale.value, set: (value: Locale) => void setLocale(value) })

const text = ref('LenBot')
const empty = ref('')
const secret = ref('sk-demo-key')
const fixedSecret = ref('sk-hidden-only')
const longText = ref('Line 1\nLine 2 grows automatically with content up to maxRows.')
const number = ref<number | null>(30)
const select = ref<string | undefined>('join')
const selectEmpty = ref<string | undefined>()
const scene = ref<string | number | (string | number)[] | undefined>('onebot:group:1')
const scenes = ref<string | number | (string | number)[] | undefined>(['onebot:group:1', 'onebot:group:3'])
const tags = ref(['Len', 'Momo', 'lenbot'])
const on = ref(true)
const off = ref(false)
const savingSwitch = ref(true)
const checked = ref(true)
const unchecked = ref(false)
const indeterminate = ref<boolean | 'indeterminate'>('indeterminate')
const radio = ref('active')
const segment = ref('live')
const segmentSmall = ref('active')
const tab = ref('live')
const verticalTab = ref('live')
const sectionOpen = ref(true)
const alertOpen = ref(false)
const inlineOpen = ref(false)
const dialog = ref(false)
const sheet = ref(false)
const sheetBottom = ref(false)
const dirty = ref(false)
const saveError = ref<string | null>(null)
const saving = ref(false)

const modeOptions = computed(() => [
  { value: 'join', label: t('participation.modes.join'), meta: 'default' },
  { value: 'direct', label: t('participation.modes.direct'), meta: '@bot' },
  { value: 'off', label: t('groups.status.paused'), disabled: true },
])
const sceneOptions = computed(() => [
  { value: 'onebot:group:1', label: `${t('shell.pages.groups')} A`, meta: '702154' },
  { value: 'onebot:group:2', label: `${t('shell.pages.groups')} B`, meta: '881203' },
  { value: 'onebot:group:3', label: `${t('shell.pages.groups')} C`, meta: '554219' },
])
const radioOptions = computed(() => [
  { value: 'active', label: t('participation.levels.active') },
  { value: 'moderate', label: t('participation.levels.moderate') },
  { value: 'quiet', label: t('participation.levels.quiet'), disabled: true },
])
const segments = computed(() => [
  { value: 'live', label: t('groups.tabs.live'), icon: MessageSquare },
  { value: 'session', label: t('groups.tabs.session'), icon: BrainCircuit },
  { value: 'tasks', label: t('groups.tabs.tasks'), icon: Wrench },
])
const levels = computed(() => [
  { value: 'active', label: t('participation.levels.active') },
  { value: 'moderate', label: t('participation.levels.moderate') },
  { value: 'quiet', label: t('participation.levels.quiet') },
])
const tabs = computed(() => [
  { value: 'live', label: t('groups.tabs.live'), icon: MessageSquare },
  { value: 'session', label: t('groups.tabs.session'), icon: BrainCircuit, dot: 'warning' as const },
  { value: 'memory', label: t('groups.tabs.memory'), dot: 'error' as const },
  { value: 'tasks', label: t('groups.tabs.tasks'), count: 3 },
  { value: 'settings', label: t('groups.tabs.settings') },
  { value: 'learning', label: t('groups.tabs.learning'), disabled: true },
])
const verticalTabs = computed(() => [
  { value: 'live', label: t('groups.tabs.live'), icon: MessageSquare },
  { value: 'memory', label: t('groups.tabs.memory'), dot: 'warning' as const },
  { value: 'tasks', label: t('groups.tabs.tasks'), count: 3 },
  { value: 'settings', label: t('groups.tabs.settings'), dot: 'error' as const },
])
const menu = computed<MenuEntry[]>(() => [
  { type: 'label', label: `${t('shell.pages.groups')} · 702154` },
  {
    label: t('groups.status.quiet'),
    icon: Pause,
    shortcut: 'Q',
    select: () => toast.info(t('groups.status.quiet')),
  },
  {
    label: t('common.reload'),
    icon: RotateCw,
    select: () => toast.success(t('common.saved')),
  },
  {
    label: t('common.copy'),
    icon: Copy,
    select: () => toast.success(t('common.copied')),
  },
  { type: 'separator' },
  {
    label: t('common.delete'),
    icon: Trash,
    danger: true,
    select: () => void ask(),
  },
  { label: t('common.unknown'), disabled: true, select: () => undefined },
])

async function ask() {
  const confirmed = await confirm({
    title: t('ui.unsaved.title'),
    message: t('ui.unsaved.message'),
    confirmLabel: t('common.confirm'),
  })
  toast[confirmed ? 'success' : 'info'](confirmed ? t('common.saved') : t('common.cancel'))
}

function failSave() {
  saving.value = true
  saveError.value = null
  setTimeout(() => {
    saving.value = false
    saveError.value = 'HTTP 409: Conflict'
    toast.error(t('ui.error.title'), { detail: 'HTTP 409: Conflict' })
  }, 700)
}

const apiError = {
  status: 422,
  message: 'HTTP 422',
  detail: [
    { loc: ['body', 'attention', 'threshold'], msg: 'Input should be less than or equal to 1' },
    { loc: ['body', 'quiet', 'start'], msg: 'Invalid time format' },
  ],
}
const networkError = new TypeError('Failed to fetch')
const retry = () => toast.info(t('common.retry'))
function toastWithAction() {
  toast.info(t('common.saved'), {
    action: { label: t('common.retry'), run: () => toast.info(t('common.saved')) },
  })
}
const trend = [3, 5, 4, 8, 12, 9, 14, 18, 15, 22, 19, 26, 24, 31, 28, 35]
const flat = [4, 4, 4, 4, 4]
const stat = ref(1284)
const json = {
  model: 'chat-default',
  input_tokens: 18342,
  output_tokens: 412,
  tool_calls: [{ name: 'send_message', arguments: { text: 'Hello!', reply_to: 88123 } }],
}
const longLog = Array.from(
  { length: 30 },
  (_, index) => `[12:00:${String(index).padStart(2, '0')}] step ${index + 1}`,
).join('\n')
const markdownSample = [
  '### Release 0.3.0',
  '- Crisp **hairlines** and `tabular` metrics across all views',
  '- Documentation at [LenBot Docs](https://example.com)',
  '',
  '| Metric | Value |',
  '| --- | --- |',
  '| Latency | `42 ms` |',
  '| Status | **OK** |',
].join('\n')

interface Row {
  id: number
  author: string
  text: string
}
const rows = ref<Row[]>(
  Array.from({ length: 5000 }, (_, index) => ({
    id: index,
    author: ['Len', 'Momo', 'Kira', 'Ren'][index % 4] as string,
    text:
      index % 7 === 0
        ? 'Variable-height row sample to verify dynamic measurement and scroll anchoring across 5,000 virtualized items. '.repeat(
            2,
          )
        : `Message #${index + 1}`,
  })),
)
let nextId = 5000
function prepend() {
  const older = Array.from({ length: 50 }, (_, index) => ({
    id: -(nextId + index),
    author: 'Archive',
    text: `History #${nextId + index}`,
  }))
  nextId += 50
  rows.value = [...older, ...rows.value]
}
function append() {
  rows.value = [...rows.value, { id: nextId++, author: 'Len', text: `Message #${nextId}` }]
}
</script>

<template>
  <TooltipProvider :delay-duration="300">
    <div class="min-h-dvh bg-page text-ink">
      <header
        class="sticky top-0 z-(--z-top) flex flex-wrap items-center gap-2 border-b border-line bg-page px-4 py-3 sm:px-8"
      >
        <h1 class="mr-auto text-lg font-semibold tracking-tight">UI</h1>
        <SegmentedControl v-model="theme" :options="themes" size="sm" :label="t('shell.account.theme')" />
        <SegmentedControl
          v-model="locale"
          :options="localeOptions"
          size="sm"
          :label="t('shell.account.language')"
        />
      </header>

      <main class="mx-auto flex max-w-6xl flex-col gap-10 px-4 py-8 sm:px-8" :class="dirty && 'pb-24'">
        <section id="buttons" class="flex flex-col gap-4">
          <h2 class="text-xl font-semibold">Button · IconButton · Tooltip · Kbd</h2>
          <div class="flex flex-wrap items-center gap-2">
            <Button variant="primary" :icon="Plus">{{ t('personas.create.createTitle') }}</Button>
            <Button>{{ t('common.cancel') }}</Button>
            <Button variant="ghost" :icon="Pencil">{{ t('common.edit') }}</Button>
            <Button variant="danger" :icon="Trash">{{ t('common.delete') }}</Button>
            <Button variant="danger-ghost">{{ t('common.discard') }}</Button>
            <Button variant="primary" loading>{{ t('common.saving') }}</Button>
            <Button variant="primary" disabled>{{ t('common.confirm') }}</Button>
            <Button disabled>{{ t('common.close') }}</Button>
            <Button size="xs">XS</Button>
            <Button size="sm">SM</Button>
            <Button size="lg" variant="primary" :icon-right="Send">LG</Button>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <IconButton :icon="Search" :label="t('common.search')" shortcut="⌘K" />
            <IconButton :icon="Pause" :label="t('groups.status.paused')" :pressed="true" />
            <IconButton :icon="Pencil" :label="t('common.edit')" variant="secondary" />
            <IconButton :icon="Plus" :label="t('personas.create.create')" variant="primary" />
            <IconButton :icon="Trash" :label="t('common.delete')" variant="danger-ghost" />
            <IconButton :icon="RotateCw" :label="t('common.reload')" loading />
            <IconButton :icon="Copy" :label="t('common.copy')" disabled />
            <Tooltip :text="t('common.save')" shortcut="⌘S">
              <Button size="sm">{{ t('common.save') }}</Button>
            </Tooltip>
            <span class="inline-flex items-center gap-1 text-sm text-muted">
              <Kbd>⌘</Kbd>
              <Kbd>K</Kbd>
            </span>
          </div>
        </section>

        <section id="status" class="flex flex-col gap-4 border-t border-line pt-8">
          <h2 class="text-xl font-semibold">Badge · StatusDot · Spinner · Avatar · Skeleton</h2>
          <div class="flex flex-wrap items-center gap-2">
            <Badge>{{ t('common.unknown') }}</Badge>
            <Badge tone="brand">{{ t('shell.pages.personas') }}</Badge>
            <Badge tone="success" dot pulse>{{ t('groups.status.chatting') }}</Badge>
            <Badge tone="warning" dot>{{ t('groups.status.quiet') }}</Badge>
            <Badge tone="error" dot>{{ t('shell.status.platformOffline') }}</Badge>
            <Badge tone="info">{{ t('shell.pages.plugins') }}</Badge>
            <span class="ml-2 inline-flex items-center gap-3">
              <StatusDot tone="success" pulse :label="t('groups.status.chatting')" />
              <StatusDot tone="warning" :label="t('groups.status.quiet')" />
              <StatusDot tone="error" :label="t('ui.error.title')" />
              <StatusDot tone="idle" :label="t('groups.status.paused')" />
              <Spinner :label="t('common.loading')" />
              <Spinner :size="20" class="text-primary" />
            </span>
          </div>
          <div class="flex flex-wrap items-center gap-3">
            <Avatar name="Group A" shape="square" :size="40" />
            <Avatar name="Board Club" shape="square" :size="40" />
            <Avatar name="Weekend" shape="square" :size="40" />
            <Avatar name="Len" :size="40" />
            <Avatar name="Momo" :size="32" />
            <Avatar name="🍑" :size="32" />
            <Avatar name="Kira" :size="24" />
            <Avatar name="Broken" src="/missing.png" :size="32" />
          </div>
          <div class="grid max-w-md gap-3">
            <Skeleton width="40%" height="20px" />
            <Skeleton :lines="3" />
            <div class="flex items-center gap-3">
              <Skeleton width="36px" height="36px" rounded="rounded-full" />
              <Skeleton :lines="2" class="flex-1" />
            </div>
          </div>
        </section>

        <section id="forms" class="flex flex-col gap-4 border-t border-line pt-8">
          <h2 class="text-xl font-semibold">
            Field · Input · Textarea · NumberInput · Select · Combobox · TagInput
          </h2>
          <div class="max-w-3xl">
            <FormSection :title="t('personas.detail.profile.who')">
              <Field :label="t('personas.detail.profile.name')" required>
                <Input v-model="text" clearable />
              </Field>
              <Field :label="t('common.search')">
                <Input v-model="empty" :icon="Search" :placeholder="t('groups.search')" />
              </Field>
              <Field label="API Key" :info="t('ui.secret.show')">
                <Input v-model="secret" type="password" clearable mono />
              </Field>
              <Field label="Password (fixed)">
                <Input v-model="fixedSecret" type="password" :revealable="false" mono />
              </Field>
              <Field label="URL" error="https:// required">
                <Input model-value="ftp://example" />
              </Field>
              <Field :label="t('groups.status.closed')" disabled><Input model-value="readonly" /></Field>
              <Field label="Timeout"><NumberInput v-model="number" :min="5" :max="600" unit="s" /></Field>
              <Field :label="t('participation.mode')">
                <Select v-model="select" :options="modeOptions" />
              </Field>
              <Field :label="t('groups.pick')">
                <Select v-model="selectEmpty" :options="modeOptions" />
              </Field>
              <Field :label="t('shell.pages.groups')">
                <Combobox v-model="scene" :options="sceneOptions" />
              </Field>
              <Field :label="t('groups.list')">
                <Combobox v-model="scenes" :options="sceneOptions" multiple />
              </Field>
              <Field :label="t('personas.detail.profile.aliases')" wide><TagInput v-model="tags" /></Field>
              <Field :label="t('personas.detail.profile.brief')" wide><Textarea v-model="longText" /></Field>
              <Field label="Min 5" error=">= 5"><NumberInput :model-value="2" :min="5" /></Field>
              <Field :label="t('common.required')" :error="t('ui.select.placeholder')">
                <Select :options="modeOptions" />
              </Field>
            </FormSection>
          </div>
        </section>

        <section id="choices" class="flex flex-col gap-4 border-t border-line pt-8">
          <h2 class="text-xl font-semibold">Switch · Checkbox · RadioGroup · SegmentedControl</h2>
          <div class="grid max-w-3xl gap-6 sm:grid-cols-2">
            <div class="flex flex-col gap-3">
              <Switch v-model="on">{{ t('groups.open') }}</Switch>
              <Switch v-model="off">{{ t('groups.status.closed') }}</Switch>
              <Switch v-model="savingSwitch" loading>{{ t('common.saving') }}</Switch>
              <Switch :model-value="true" disabled>{{ t('groups.status.paused') }}</Switch>
              <Switch v-model="on" size="sm">SM</Switch>
              <Field :label="t('participation.chatMode')" inline><Switch v-model="on" /></Field>
            </div>
            <div class="flex flex-col gap-3">
              <Checkbox v-model="checked">{{ t('personas.detail.scenes.selectAll') }}</Checkbox>
              <Checkbox v-model="unchecked">{{ t('common.none') }}</Checkbox>
              <Checkbox v-model="indeterminate">{{ t('participation.custom') }}</Checkbox>
              <Checkbox :model-value="true" disabled>{{ t('groups.status.paused') }}</Checkbox>
              <RadioGroup v-model="radio" :options="radioOptions" class="mt-2" />
            </div>
          </div>
          <div class="flex flex-wrap items-center gap-3">
            <SegmentedControl v-model="segment" :options="segments" :label="t('shell.pages.groups')" />
            <SegmentedControl
              v-model="segmentSmall"
              :options="levels"
              size="sm"
              :label="t('participation.frequency')"
            />
          </div>
          <div class="max-w-sm">
            <SegmentedControl
              v-model="segmentSmall"
              :options="levels"
              block
              :label="t('participation.frequency')"
            />
          </div>
        </section>

        <section id="tabs" class="flex flex-col gap-4 border-t border-line pt-8">
          <h2 class="text-xl font-semibold">Tabs · Collapsible</h2>
          <Tabs v-model="tab" :items="tabs" :label="t('shell.pages.groups')">
            <template #live>
              <p class="text-sm text-muted">{{ t('groups.tabs.live') }}</p>
            </template>
            <template #session>
              <p class="text-sm text-muted">{{ t('groups.tabs.session') }}</p>
            </template>
            <template #memory>
              <p class="text-sm text-muted">{{ t('groups.tabs.memory') }}</p>
            </template>
            <template #tasks>
              <p class="text-sm text-muted">{{ t('groups.tabs.tasks') }}</p>
            </template>
            <template #settings>
              <p class="text-sm text-muted">{{ t('groups.tabs.settings') }}</p>
            </template>
          </Tabs>
          <div class="max-w-2xl border-t border-line pt-4">
            <Tabs
              v-model="verticalTab"
              :items="verticalTabs"
              orientation="vertical"
              :label="t('shell.pages.groups')"
            >
              <template #live>
                <p class="text-sm text-muted">{{ t('groups.tabs.live') }}</p>
              </template>
              <template #memory>
                <p class="text-sm text-muted">{{ t('groups.tabs.memory') }}</p>
              </template>
              <template #tasks>
                <p class="text-sm text-muted">{{ t('groups.tabs.tasks') }}</p>
              </template>
              <template #settings>
                <p class="text-sm text-muted">{{ t('groups.tabs.settings') }}</p>
              </template>
            </Tabs>
          </div>
          <div class="flex max-w-2xl flex-col gap-4 pt-2">
            <Collapsible
              v-model:open="sectionOpen"
              :title="t('groups.tabs.settings')"
              :count="3"
              dot="warning"
            >
              <p class="text-sm text-muted">{{ t('personas.detail.profile.brief') }}</p>
            </Collapsible>
            <Collapsible v-model:open="alertOpen" :title="t('ui.error.title')" dot="error">
              <p class="text-sm text-muted">{{ t('ui.error.network') }}</p>
            </Collapsible>
            <Collapsible v-model:open="inlineOpen" variant="inline" :title="t('common.more')" :count="2">
              <p class="text-sm text-muted">{{ t('groups.tabs.memory') }}</p>
            </Collapsible>
          </div>
        </section>

        <section id="overlays" class="flex flex-col gap-4 border-t border-line pt-8">
          <h2 class="text-xl font-semibold">
            Dialog · Sheet · ConfirmDialog · Popover · DropdownMenu · Toast
          </h2>
          <div class="flex flex-wrap items-center gap-2">
            <Button @click="dialog = true">Dialog</Button>
            <Button @click="sheet = true">Sheet</Button>
            <Button @click="sheetBottom = true">Sheet Bottom</Button>
            <Button variant="danger-ghost" @click="ask">Confirm</Button>
            <Popover>
              <template #trigger><Button>Popover</Button></template>
              <div class="flex flex-col gap-3">
                <p class="text-sm font-semibold">{{ t('groups.status.quiet') }}</p>
                <SegmentedControl
                  v-model="segmentSmall"
                  :options="levels"
                  size="sm"
                  block
                  :label="t('participation.frequency')"
                />
                <Button variant="primary" size="sm" block>{{ t('common.confirm') }}</Button>
              </div>
            </Popover>
            <DropdownMenu :items="menu">
              <IconButton :icon="Ellipsis" :label="t('groups.actions')" variant="secondary" />
            </DropdownMenu>
            <Button @click="toast.success(t('common.saved'))">Toast OK</Button>
            <Button @click="toast.error(t('ui.error.title'), { detail: 'retcode 100' })">Toast Error</Button>
            <Button @click="toastWithAction">Toast Action</Button>
          </div>
          <Dialog v-model:open="dialog" :title="t('personas.create.createTitle')">
            <div class="flex flex-col gap-4">
              <Field :label="t('personas.detail.profile.name')" required><Input v-model="text" /></Field>
              <Field :label="t('personas.detail.speech.voice')">
                <Textarea v-model="longText" :rows="4" />
              </Field>
            </div>
            <template #footer>
              <Button @click="dialog = false">{{ t('common.cancel') }}</Button>
              <Button variant="primary" @click="dialog = false">{{ t('personas.create.create') }}</Button>
            </template>
          </Dialog>
          <Sheet v-model:open="sheet" title="JSON">
            <CodeBlock :code="json" />
          </Sheet>
          <Sheet v-model:open="sheetBottom" side="bottom" title="JSON">
            <CodeBlock :code="json" />
          </Sheet>
        </section>

        <section id="feedback" class="flex flex-col gap-4 border-t border-line pt-8">
          <h2 class="text-xl font-semibold">ErrorNote · EmptyState · SaveBar</h2>
          <div class="grid max-w-3xl gap-3">
            <ErrorNote :title="t('ui.error.title')" :error="apiError" :retry="retry" />
            <ErrorNote :error="networkError" />
            <ErrorNote :title="t('shell.pages.plugins')" error="Missing dependency: httpx" />
          </div>
          <div class="grid max-w-3xl gap-3 sm:grid-cols-2">
            <div class="rounded-lg border border-line">
              <EmptyState :title="t('groups.empty')">
                <Button variant="primary" size="sm" :icon="Plus">{{ t('groups.add') }}</Button>
              </EmptyState>
            </div>
            <div class="rounded-lg border border-line"><EmptyState compact :icon="Bot" /></div>
          </div>
          <div class="flex items-center gap-3">
            <Switch
              :model-value="dirty"
              @update:model-value="
                (val) => {
                  dirty = val
                  if (!val) saveError = null
                }
              "
            >
              {{ t('common.unsaved') }}
            </Switch>
          </div>
        </section>

        <section id="data" class="flex flex-col gap-4 border-t border-line pt-8">
          <h2 class="text-xl font-semibold">StatTile · Sparkline · CodeBlock · MarkdownText · Timeline</h2>
          <div class="grid max-w-4xl gap-6 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Messages" :value="stat" :delta="12" :trend="trend" />
            <StatTile
              label="Tokens"
              :value="182340"
              :delta="-4.5"
              :trend="trend.slice().reverse()"
              tone="info"
            />
            <StatTile label="Latency" :value="3.42" unit="s" :trend="flat" tone="neutral" />
            <StatTile :label="t('common.loading')" :value="null" loading />
          </div>
          <div class="flex flex-wrap items-center gap-3">
            <Button size="sm" @click="stat += Math.round(Math.random() * 400)">+ Stat</Button>
            <div class="w-32"><Sparkline :values="trend" tone="success" label="Trend" /></div>
          </div>
          <div class="grid max-w-4xl gap-4 sm:grid-cols-2">
            <CodeBlock :code="json" label="payload.json" />
            <CodeBlock :code="longLog" :max-lines="8" />
          </div>
          <div class="max-w-xl border-t border-line pt-4">
            <MarkdownText :text="markdownSample" />
          </div>
          <div class="max-w-xl border-t border-line pt-4">
            <Timeline>
              <TimelineItem title="Wake" tone="neutral" :icon="MessageSquare" meta="12:03:11" />
              <TimelineItem title="Recall · 2 items" :icon="BrainCircuit" meta="0.3s">
                <span class="text-muted">people.md · events/2026-10.md</span>
              </TimelineItem>
              <TimelineItem title="Step 1" tone="info" :icon="Bot" meta="2.1s · 18.3k -> 412">
                Checking recent context before replying.
              </TimelineItem>
              <TimelineItem title="send_message" tone="success" :icon="Send" meta="OK" />
              <TimelineItem title="web_search" tone="error" :icon="Wrench" meta="0.8s">
                <span class="text-error">HTTP 503 Service Unavailable</span>
              </TimelineItem>
              <TimelineItem title="Step 2" tone="info" running last />
            </Timeline>
          </div>
        </section>

        <section id="virtual" class="flex flex-col gap-4 border-t border-line pt-8">
          <h2 class="text-xl font-semibold">VirtualList ({{ rows.length }})</h2>
          <div class="flex flex-wrap gap-2">
            <Button size="sm" @click="prepend">+50 Older</Button>
            <Button size="sm" @click="append">+1 New</Button>
          </div>
          <VirtualList
            :items="rows"
            :get-key="(row) => row.id"
            :estimate-size="44"
            follow-end
            class="h-80 max-w-xl rounded-lg border border-line"
          >
            <template #default="{ item }">
              <div class="flex gap-2.5 border-b border-line px-3 py-2.5">
                <Avatar :name="item.author" :size="24" />
                <div class="min-w-0">
                  <span class="text-xs text-subtle tabular">{{ item.author }} · #{{ item.id }}</span>
                  <p class="text-sm break-words">{{ item.text }}</p>
                </div>
              </div>
            </template>
          </VirtualList>
        </section>

        <SaveBar
          :dirty="dirty"
          :saving="saving"
          :error="saveError"
          @save="failSave"
          @discard="
            () => {
              dirty = false
              saveError = null
            }
          "
        />
      </main>
    </div>
    <Toaster />
    <ConfirmHost />
  </TooltipProvider>
</template>
