<script setup lang="ts">
import { computed, ref } from 'vue'
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
import { currentLocale, setLocale, type Locale } from '../i18n'
import Avatar from '../ui/Avatar.vue'
import Badge from '../ui/Badge.vue'
import Button from '../ui/Button.vue'
import Checkbox from '../ui/Checkbox.vue'
import CodeBlock from '../ui/CodeBlock.vue'
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

/** Development-only page listing every component in src/ui with its states (work.md M1.3). */
const themes = [
  { value: 'light', label: '浅色', icon: Sun },
  { value: 'dark', label: '深色', icon: Moon },
]
const theme = computed({
  get: () => (themeMode.value === 'dark' ? 'dark' : 'light'),
  set: (value: string) => setThemeMode(value),
})
const locales = [
  { value: 'zh-CN' as Locale, label: '中文' },
  { value: 'en' as Locale, label: 'English' },
]
const locale = computed({ get: () => currentLocale.value, set: (value: Locale) => void setLocale(value) })

const text = ref('LenBot')
const empty = ref('')
const secret = ref('sk-test')
const longText = ref('第一行\n第二行会随着内容自动变高，直到最大行数后出现滚动条。')
const number = ref<number | null>(30)
const select = ref<string | undefined>('ambient')
const selectEmpty = ref<string | undefined>()
const scene = ref<string | number | (string | number)[] | undefined>('onebot:group:1')
const scenes = ref<string | number | (string | number)[] | undefined>(['onebot:group:1', 'onebot:group:3'])
const tags = ref(['小莲', 'Len', 'lenbot'])
const on = ref(true)
const off = ref(false)
const savingSwitch = ref(true)
const checked = ref(true)
const unchecked = ref(false)
const indeterminate = ref<boolean | 'indeterminate'>('indeterminate')
const radio = ref('all')
const segment = ref('live')
const segmentSmall = ref('day')
const tab = ref('live')
const dialog = ref(false)
const sheet = ref(false)
const dirty = ref(true)
const saving = ref(false)

const modeOptions = [
  { value: 'ambient', label: '自由参与' },
  { value: 'direct', label: '只回应直接联系' },
  { value: 'off', label: '暂停', disabled: true },
]
const sceneOptions = [
  { value: 'onebot:group:1', label: '摸鱼研究所', meta: '702154' },
  { value: 'onebot:group:2', label: '周末桌游群', meta: '881203' },
  { value: 'onebot:group:3', label: 'LenBot 开发', meta: '554219' },
  { value: 'telegram:group:4', label: 'Weekend Club', meta: '-100223' },
]
const radioOptions = [
  { value: 'all', label: '所有群' },
  { value: 'some', label: '指定的群' },
  { value: 'none', label: '不启用', disabled: true },
]
const segments = [
  { value: 'live', label: '现场', icon: MessageSquare },
  { value: 'session', label: '会话', icon: BrainCircuit },
  { value: 'tasks', label: '任务', icon: Wrench },
]
const periods = [
  { value: 'day', label: '24 小时' },
  { value: 'week', label: '7 天' },
  { value: 'month', label: '30 天' },
]
const tabs = [
  { value: 'live', label: '现场', icon: MessageSquare },
  { value: 'session', label: '会话', icon: BrainCircuit },
  { value: 'memory', label: '记忆' },
  { value: 'tasks', label: '任务', count: 3 },
  { value: 'settings', label: '设置' },
  { value: 'locked', label: '学习', disabled: true },
]
const menu: MenuEntry[] = [
  { type: 'label', label: '摸鱼研究所' },
  { label: '安静一会', icon: Pause, shortcut: 'Q', select: () => toast.info('已安静 30 分钟') },
  { label: '开始新会话', icon: RotateCw, select: () => toast.success('已开始新会话') },
  { label: '复制群号', icon: Copy, select: () => toast.success('已复制') },
  { type: 'separator' },
  {
    label: '移除群聊',
    icon: Trash,
    danger: true,
    select: () => void ask(),
  },
  { label: '不可用的操作', disabled: true, select: () => undefined },
]

async function ask() {
  const confirmed = await confirm({
    title: '移除摸鱼研究所？',
    message: '移除后不再接收这个群的消息，历史记录保留。',
    confirmLabel: '移除',
  })
  toast[confirmed ? 'success' : 'info'](confirmed ? '已移除' : '已取消')
}

function failSave() {
  saving.value = true
  setTimeout(() => {
    saving.value = false
    toast.error('设置没有保存', { detail: 'HTTP 409：配置已被其他标签页修改，请重新读取后再保存。' })
  }, 900)
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
const retry = () => toast.info('重试')
function toastWithAction() {
  toast.info('已开始新会话', { action: { label: '撤销', run: () => toast.info('已撤销') } })
}
const trend = [3, 5, 4, 8, 12, 9, 14, 18, 15, 22, 19, 26, 24, 31, 28, 35]
const flat = [4, 4, 4, 4, 4]
const stat = ref(1284)
const json = {
  model: 'gemini-2.5-pro',
  input_tokens: 18342,
  output_tokens: 412,
  tool_calls: [{ name: 'send_message', arguments: { text: '晚上好呀', reply_to: 88123 } }],
}
const longLog = Array.from(
  { length: 30 },
  (_, index) => `[12:00:${String(index).padStart(2, '0')}] step ${index + 1}`,
).join('\n')

interface Row {
  id: number
  author: string
  text: string
}
const rows = ref<Row[]>(
  Array.from({ length: 5000 }, (_, index) => ({
    id: index,
    author: ['小莲', '阿冰', '路人甲', 'Len'][index % 4] as string,
    text:
      index % 7 === 0
        ? '这是一条比较长的消息，用来检查虚拟列表在行高不一致时能否正确测量和定位。'.repeat(2)
        : `第 ${index + 1} 条消息`,
  })),
)
let nextId = 5000
function prepend() {
  const older = Array.from({ length: 50 }, (_, index) => ({
    id: -(nextId + index),
    author: '更早',
    text: '更早的消息',
  }))
  nextId += 50
  rows.value = [...older, ...rows.value]
}
function append() {
  rows.value = [...rows.value, { id: nextId++, author: '小莲', text: '新消息' }]
}
</script>

<template>
  <TooltipProvider :delay-duration="300">
    <div class="min-h-dvh bg-page text-ink">
      <header
        class="sticky top-0 z-(--z-top) flex flex-wrap items-center gap-3 border-b border-line bg-page/90 px-4 py-3 backdrop-blur sm:px-8"
      >
        <h1 class="mr-auto text-lg font-semibold">UI</h1>
        <SegmentedControl v-model="theme" :options="themes" size="sm" label="Theme" />
        <SegmentedControl v-model="locale" :options="locales" size="sm" label="Language" />
      </header>

      <main class="mx-auto flex max-w-6xl flex-col gap-12 px-4 py-8 sm:px-8">
        <section id="buttons" class="flex flex-col gap-4">
          <h2 class="text-xl font-semibold">Button · IconButton · Tooltip · Kbd</h2>
          <div class="flex flex-wrap items-center gap-2">
            <Button variant="primary" :icon="Plus">新建角色</Button>
            <Button>次要按钮</Button>
            <Button variant="ghost" :icon="Pencil">编辑</Button>
            <Button variant="danger" :icon="Trash">删除</Button>
            <Button variant="danger-ghost">移除</Button>
            <Button variant="primary" loading>保存中</Button>
            <Button disabled>禁用</Button>
            <Button size="sm">小按钮</Button>
            <Button size="lg" variant="primary" :icon-right="Send">大按钮</Button>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <IconButton :icon="Search" label="搜索" shortcut="⌘K" />
            <IconButton :icon="Pause" label="暂停" :pressed="true" />
            <IconButton :icon="Pencil" label="编辑" variant="secondary" />
            <IconButton :icon="Plus" label="新建" variant="primary" />
            <IconButton :icon="Trash" label="删除" variant="danger-ghost" />
            <IconButton :icon="RotateCw" label="刷新" loading />
            <IconButton :icon="Copy" label="复制" disabled />
            <Tooltip text="悬停提示" shortcut="⌘S"><Button size="sm">悬停看提示</Button></Tooltip>
            <span class="inline-flex items-center gap-1 text-sm text-muted">
              <Kbd>⌘</Kbd>
              <Kbd>K</Kbd>
            </span>
          </div>
        </section>

        <section id="status" class="flex flex-col gap-4">
          <h2 class="text-xl font-semibold">Badge · StatusDot · Spinner · Avatar · Skeleton</h2>
          <div class="flex flex-wrap items-center gap-2">
            <Badge>默认</Badge>
            <Badge tone="brand">角色</Badge>
            <Badge tone="success" dot pulse>聊天中</Badge>
            <Badge tone="warning" dot>安静中</Badge>
            <Badge tone="error" dot>连接断开</Badge>
            <Badge tone="info">插件</Badge>
            <span class="ml-3 inline-flex items-center gap-3">
              <StatusDot tone="success" pulse label="聊天中" />
              <StatusDot tone="warning" label="安静中" />
              <StatusDot tone="error" label="出错" />
              <StatusDot tone="idle" label="已暂停" />
              <Spinner label="读取中" />
              <Spinner :size="20" class="text-primary" />
            </span>
          </div>
          <div class="flex flex-wrap items-center gap-3">
            <Avatar name="摸鱼研究所" shape="square" :size="40" />
            <Avatar name="周末桌游群" shape="square" :size="40" />
            <Avatar name="Weekend Club" shape="square" :size="40" />
            <Avatar name="小莲" :size="40" />
            <Avatar name="阿冰" :size="32" />
            <Avatar name="🍑 桃子" :size="32" />
            <Avatar name="Len" :size="24" />
            <Avatar name="坏图片" src="/missing.png" :size="32" />
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

        <section id="forms" class="flex flex-col gap-4">
          <h2 class="text-xl font-semibold">
            Field · Input · Textarea · NumberInput · Select · Combobox · TagInput
          </h2>
          <div class="max-w-3xl">
            <FormSection title="基本设置">
              <Field label="名字" required><Input v-model="text" clearable /></Field>
              <Field label="搜索"><Input v-model="empty" :icon="Search" placeholder="群名或群号" /></Field>
              <Field label="接口密钥"><Input v-model="secret" type="password" mono /></Field>
              <Field label="出错的输入" error="地址必须以 http:// 或 https:// 开头">
                <Input model-value="ftp://example" />
              </Field>
              <Field label="禁用" disabled><Input model-value="不能修改" /></Field>
              <Field label="回合超时"><NumberInput v-model="number" :min="5" :max="600" unit="秒" /></Field>
              <Field label="参与方式"><Select v-model="select" :options="modeOptions" /></Field>
              <Field label="未选择"><Select v-model="selectEmpty" :options="modeOptions" /></Field>
              <Field label="群聊"><Combobox v-model="scene" :options="sceneOptions" /></Field>
              <Field label="多个群聊"><Combobox v-model="scenes" :options="sceneOptions" multiple /></Field>
              <Field label="别名" wide><TagInput v-model="tags" /></Field>
              <Field label="额外要求" wide><Textarea v-model="longText" /></Field>
              <Field label="出错的数字" error="不能小于 5"><NumberInput :model-value="2" :min="5" /></Field>
              <Field label="出错的选择" error="请选择一个群"><Select :options="modeOptions" /></Field>
            </FormSection>
          </div>
        </section>

        <section id="choices" class="flex flex-col gap-4">
          <h2 class="text-xl font-semibold">Switch · Checkbox · RadioGroup · SegmentedControl</h2>
          <div class="grid max-w-3xl gap-6 sm:grid-cols-2">
            <div class="flex flex-col gap-3">
              <Switch v-model="on">开启</Switch>
              <Switch v-model="off">关闭</Switch>
              <Switch v-model="savingSwitch" loading>保存中</Switch>
              <Switch :model-value="true" disabled>禁用</Switch>
              <Switch v-model="on" size="sm">小开关</Switch>
              <Field label="在 Field 里" inline><Switch v-model="on" /></Field>
            </div>
            <div class="flex flex-col gap-3">
              <Checkbox v-model="checked">已勾选</Checkbox>
              <Checkbox v-model="unchecked">未勾选</Checkbox>
              <Checkbox v-model="indeterminate">部分勾选</Checkbox>
              <Checkbox :model-value="true" disabled>禁用</Checkbox>
              <RadioGroup v-model="radio" :options="radioOptions" class="mt-2" />
            </div>
          </div>
          <div class="flex flex-wrap items-center gap-3">
            <SegmentedControl v-model="segment" :options="segments" label="页签" />
            <SegmentedControl v-model="segmentSmall" :options="periods" size="sm" label="时间范围" />
          </div>
          <div class="max-w-sm">
            <SegmentedControl v-model="segmentSmall" :options="periods" block label="时间范围" />
          </div>
        </section>

        <section id="tabs" class="flex flex-col gap-4">
          <h2 class="text-xl font-semibold">Tabs</h2>
          <Tabs v-model="tab" :items="tabs" label="群聊工作台">
            <template #live><p class="text-muted">现场页签内容</p></template>
            <template #session><p class="text-muted">会话页签内容</p></template>
            <template #memory><p class="text-muted">记忆页签内容</p></template>
            <template #tasks><p class="text-muted">任务页签内容</p></template>
            <template #settings><p class="text-muted">设置页签内容</p></template>
          </Tabs>
        </section>

        <section id="overlays" class="flex flex-col gap-4">
          <h2 class="text-xl font-semibold">
            Dialog · Sheet · ConfirmDialog · Popover · DropdownMenu · Toast
          </h2>
          <div class="flex flex-wrap items-center gap-2">
            <Button @click="dialog = true">打开对话框</Button>
            <Button @click="sheet = true">打开侧边面板</Button>
            <Button variant="danger-ghost" @click="ask">确认删除</Button>
            <Popover>
              <template #trigger><Button>弹出层</Button></template>
              <div class="flex flex-col gap-3">
                <p class="text-sm font-semibold">安静一会</p>
                <SegmentedControl v-model="segmentSmall" :options="periods" size="sm" block label="时长" />
                <Button variant="primary" size="sm" block>确定</Button>
              </div>
            </Popover>
            <DropdownMenu :items="menu">
              <IconButton :icon="Ellipsis" label="更多操作" variant="secondary" />
            </DropdownMenu>
            <Button @click="toast.success('设置已保存')">成功提示</Button>
            <Button @click="toast.error('没有发出去', { detail: 'OneBot 返回 retcode 100：消息被风控拦截' })">
              错误提示
            </Button>
            <Button @click="toastWithAction">带操作</Button>
          </div>
          <Dialog v-model:open="dialog" title="新建角色">
            <div class="flex flex-col gap-4">
              <Field label="名字" required><Input v-model="text" /></Field>
              <Field label="说话方式"><Textarea v-model="longText" :rows="4" /></Field>
            </div>
            <template #footer>
              <Button @click="dialog = false">取消</Button>
              <Button variant="primary" @click="dialog = false">创建</Button>
            </template>
          </Dialog>
          <Sheet v-model:open="sheet" title="回合详情">
            <CodeBlock :code="json" />
          </Sheet>
        </section>

        <section id="feedback" class="flex flex-col gap-4">
          <h2 class="text-xl font-semibold">ErrorNote · EmptyState · SaveBar</h2>
          <div class="grid max-w-3xl gap-3">
            <ErrorNote title="设置没有保存" :error="apiError" :retry="retry" />
            <ErrorNote :error="networkError" />
            <ErrorNote title="插件没有启动" error="缺少依赖 bilibili-api-python" />
          </div>
          <div class="grid max-w-3xl gap-3 sm:grid-cols-2">
            <div class="rounded-lg border border-line">
              <EmptyState title="还没有接入群聊">
                <Button variant="primary" size="sm" :icon="Plus">接入群聊</Button>
              </EmptyState>
            </div>
            <div class="rounded-lg border border-line"><EmptyState compact :icon="Bot" /></div>
          </div>
          <div class="flex items-center gap-3">
            <Switch v-model="dirty">有未保存的修改</Switch>
          </div>
        </section>

        <section id="data" class="flex flex-col gap-4">
          <h2 class="text-xl font-semibold">StatTile · Sparkline · CodeBlock · Timeline</h2>
          <div class="grid max-w-4xl gap-6 sm:grid-cols-4">
            <StatTile label="今日消息" :value="stat" :delta="12" :trend="trend" />
            <StatTile
              label="token"
              :value="182340"
              :delta="-4.5"
              :trend="trend.slice().reverse()"
              tone="info"
            />
            <StatTile label="平均耗时" :value="3.42" unit="秒" :trend="flat" tone="neutral" />
            <StatTile label="读取中" :value="null" loading />
          </div>
          <div class="flex items-center gap-2">
            <Button size="sm" @click="stat += Math.round(Math.random() * 400)">数字增加</Button>
            <div class="w-32"><Sparkline :values="trend" tone="success" label="最近 16 小时" /></div>
          </div>
          <div class="grid max-w-4xl gap-4 sm:grid-cols-2">
            <CodeBlock :code="json" label="模型请求" />
            <CodeBlock :code="longLog" :max-lines="8" />
          </div>
          <div class="max-w-xl">
            <Timeline>
              <TimelineItem title="被点名唤醒" tone="brand" :icon="MessageSquare" meta="12:03:11" />
              <TimelineItem title="召回 2 条记忆" :icon="BrainCircuit" meta="0.3 秒">
                <span class="text-muted">people.md · events/2026-10.md</span>
              </TimelineItem>
              <TimelineItem title="模型 · 第 1 步" tone="info" :icon="Bot" meta="2.1 秒 · 18.3k → 412">
                想先确认对方说的是哪局桌游，再决定要不要接话。
              </TimelineItem>
              <TimelineItem title="send_message" tone="success" :icon="Send" meta="已发出" />
              <TimelineItem title="工具失败 · web_search" tone="error" :icon="Wrench" meta="0.8 秒">
                <span class="text-error">HTTP 503 Service Unavailable</span>
              </TimelineItem>
              <TimelineItem title="模型 · 第 2 步" tone="info" running last />
            </Timeline>
          </div>
        </section>

        <section id="virtual" class="flex flex-col gap-4">
          <h2 class="text-xl font-semibold">VirtualList（{{ rows.length }} 行）</h2>
          <div class="flex gap-2">
            <Button size="sm" @click="prepend">加载更早 50 条</Button>
            <Button size="sm" @click="append">追加一条</Button>
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
                  <span class="text-xs text-subtle">{{ item.author }} · #{{ item.id }}</span>
                  <p class="text-sm">{{ item.text }}</p>
                </div>
              </div>
            </template>
          </VirtualList>
        </section>

        <SaveBar :dirty="dirty" :saving="saving" @save="failSave" @discard="dirty = false" />
      </main>
    </div>
    <Toaster />
    <ConfirmHost />
  </TooltipProvider>
</template>
