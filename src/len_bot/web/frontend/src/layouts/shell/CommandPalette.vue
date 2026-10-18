<script setup lang="ts">
import { computed, nextTick, ref, watch, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter, type RouteLocationRaw } from 'vue-router'
import { useEventListener } from '@vueuse/core'
import { DialogContent, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui'
import {
  CornerDownLeft,
  FileText,
  Languages,
  MessagesSquare,
  Palette,
  Pause,
  Play,
  RotateCw,
  Search,
} from '@lucide/vue'
import { setThemeMode } from '../../composables/useThemeMode.js'
import { host } from '../../host/store.js'
import { openRestart } from '../../host/restart.js'
import { hostApi } from '../../api/host'
import { localeOptions, setLocale } from '../../i18n'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'
import Kbd from '../../ui/Kbd.vue'
import { navAreas } from '../nav'
import { groupLabel } from './scenes'

interface Command {
  id: string
  kind: 'page' | 'group' | 'action'
  title: string
  detail?: string
  keywords: string
  icon: Component
  to?: RouteLocationRaw
  run?: () => unknown
}

const open = defineModel<boolean>('open', { default: false })
const props = defineProps<{ scene: string }>()

const { t } = useI18n()
const router = useRouter()
const query = ref('')
const cursor = ref(0)
const input = ref<HTMLInputElement>()
const list = ref<HTMLElement>()

async function setChat(scene: string, enabled: boolean) {
  const name = groupLabel(scene)
  try {
    await hostApi.setChat(scene, enabled)
    toast.success(t(enabled ? 'palette.actions.resumed' : 'palette.actions.paused', { name }))
  } catch (error) {
    toast.error(t('palette.actions.failed'), { detail: describeError(error, t('ui.error.network')).message })
  }
}

const commands = computed<Command[]>(() => {
  const pages = navAreas.flatMap((area) => {
    const entries = area.pages.length ? area.pages : [{ route: area.route, label: area.label }]
    return entries.map((page) => ({
      id: `page:${page.route}`,
      kind: 'page' as const,
      title: area.pages.length ? `${t(area.label)} · ${t(page.label)}` : t(page.label),
      keywords: `${page.route} ${area.id}`,
      icon: FileText,
      to: { name: page.route, query: area.scoped && props.scene ? { scene: props.scene } : {} },
    }))
  })
  const scenes = (host.state?.scenes ?? []) as {
    scene: string
    persona?: { name: string }
    chat_enabled: boolean
  }[]
  const groups = scenes.map((item) => ({
    id: `group:${item.scene}`,
    kind: 'group' as const,
    title: groupLabel(item.scene),
    detail: item.persona?.name,
    keywords: item.scene,
    icon: MessagesSquare,
    to: { name: 'host-scenes', query: { scene: item.scene } },
  }))
  const switches = scenes.map((item) => ({
    id: `chat:${item.scene}`,
    kind: 'action' as const,
    title: t(item.chat_enabled ? 'palette.actions.pause' : 'palette.actions.resume', {
      name: groupLabel(item.scene),
    }),
    keywords: `${item.scene} pause resume`,
    icon: item.chat_enabled ? Pause : Play,
    run: () => setChat(item.scene, !item.chat_enabled),
  }))
  const themes = (['system', 'light', 'dark'] as const).map((mode) => ({
    id: `theme:${mode}`,
    kind: 'action' as const,
    title: t('palette.actions.theme', { mode: t(`shell.account.themes.${mode}`) }),
    keywords: `theme ${mode}`,
    icon: Palette,
    run: () => setThemeMode(mode),
  }))
  const languages = localeOptions.map((option) => ({
    id: `locale:${option.value}`,
    kind: 'action' as const,
    title: t('palette.actions.language', { name: option.label }),
    keywords: `language locale ${option.value}`,
    icon: Languages,
    run: () => setLocale(option.value),
  }))
  const restart = {
    id: 'restart',
    kind: 'action' as const,
    title: t('palette.actions.restart'),
    keywords: 'restart',
    icon: RotateCw,
    run: openRestart,
  }
  return [...pages, ...groups, ...switches, ...themes, ...languages, restart]
})

const results = computed(() => {
  const words = query.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return commands.value.filter((item) => item.kind !== 'action' || item.id === 'restart')
  return commands.value.filter((item) => {
    const text = `${item.title} ${item.detail ?? ''} ${item.keywords}`.toLowerCase()
    return words.every((word) => text.includes(word))
  })
})

watch(results, () => (cursor.value = 0))
watch(open, (value) => {
  if (!value) return
  query.value = ''
  nextTick(() => input.value?.focus())
})
watch(cursor, (index) => {
  nextTick(() => list.value?.querySelector(`[data-index="${index}"]`)?.scrollIntoView({ block: 'nearest' }))
})

function choose(item: Command | undefined) {
  if (!item) return
  open.value = false
  if (item.run) void item.run()
  else if (item.to) void router.push(item.to)
}

function onKey(event: KeyboardEvent) {
  const count = results.value.length
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    cursor.value = count ? (cursor.value + 1) % count : 0
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    cursor.value = count ? (cursor.value - 1 + count) % count : 0
  } else if (event.key === 'Enter' && !event.isComposing) {
    event.preventDefault()
    choose(results.value[cursor.value])
  }
}

useEventListener(window, 'keydown', (event: KeyboardEvent) => {
  if (
    (event.ctrlKey || event.metaKey) &&
    !event.shiftKey &&
    !event.altKey &&
    event.key.toLowerCase() === 'k'
  ) {
    event.preventDefault()
    open.value = !open.value
  }
})
</script>

<template>
  <DialogRoot v-model:open="open">
    <DialogPortal>
      <DialogOverlay class="ui-overlay fixed inset-0 z-(--z-dialog) bg-overlay" />
      <DialogContent
        :aria-describedby="undefined"
        class="ui-dialog fixed top-[12vh] left-1/2 z-(--z-dialog) flex max-h-[70dvh] w-[calc(100vw-24px)] max-w-xl -translate-x-1/2 flex-col overflow-hidden rounded-xl border border-line bg-surface-raised text-ink shadow-dialog outline-none"
      >
        <DialogTitle class="sr-only">{{ t('palette.label') }}</DialogTitle>
        <label class="flex shrink-0 items-center gap-3 border-b border-line px-4">
          <Search :size="18" class="shrink-0 text-subtle" aria-hidden="true" />
          <input
            ref="input"
            v-model="query"
            :placeholder="t('palette.placeholder')"
            :aria-label="t('palette.label')"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            :aria-activedescendant="results[cursor] ? `palette-${cursor}` : undefined"
            class="h-13 min-w-0 flex-1 bg-transparent text-lg outline-none placeholder:text-subtle focus-visible:outline-none"
            @keydown="onKey"
          />
          <Kbd class="max-sm:hidden">Esc</Kbd>
        </label>
        <ul
          id="palette-list"
          ref="list"
          role="listbox"
          class="min-h-0 flex-1 overflow-y-auto p-1.5 scrollbar-thin"
        >
          <li
            v-for="(item, index) in results"
            :id="`palette-${index}`"
            :key="item.id"
            :data-index="index"
            role="option"
            :aria-selected="index === cursor"
            class="flex h-10 cursor-pointer items-center gap-3 rounded-md px-3 text-base text-ink-2 aria-selected:bg-hover aria-selected:text-ink"
            @mousemove="cursor = index"
            @click="choose(item)"
          >
            <component :is="item.icon" :size="16" class="shrink-0 text-muted" aria-hidden="true" />
            <span class="truncate">{{ item.title }}</span>
            <span v-if="item.detail" class="min-w-0 truncate text-sm text-subtle">{{ item.detail }}</span>
            <span class="ml-auto shrink-0 text-xs text-subtle">{{ t(`palette.kinds.${item.kind}`) }}</span>
            <CornerDownLeft
              v-if="index === cursor"
              :size="14"
              class="shrink-0 text-subtle"
              aria-hidden="true"
            />
          </li>
          <li v-if="!results.length" class="px-3 py-8 text-center text-sm text-subtle">
            {{ t('palette.empty') }}
          </li>
        </ul>
        <footer
          class="flex shrink-0 items-center gap-4 border-t border-line px-4 py-2 text-xs text-subtle max-sm:hidden"
        >
          <span class="inline-flex items-center gap-1">
            <Kbd>↑</Kbd>
            <Kbd>↓</Kbd>
            {{ t('palette.keys.select') }}
          </span>
          <span class="inline-flex items-center gap-1">
            <Kbd>Enter</Kbd>
            {{ t('palette.keys.open') }}
          </span>
          <span class="inline-flex items-center gap-1">
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd>
            {{ t('palette.keys.toggle') }}
          </span>
        </footer>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
