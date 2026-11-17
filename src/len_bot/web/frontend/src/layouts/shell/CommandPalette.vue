<script setup lang="ts">
import { computed, nextTick, ref, watch, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter, type RouteLocationRaw } from 'vue-router'
import { useEventListener } from '@vueuse/core'
import { DialogContent, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui'
import {
  CornerDownLeft,
  Languages,
  MessagesSquare,
  Palette,
  Pause,
  Play,
  RotateCw,
  Search,
  UserRound,
} from '@lucide/vue'
import { setThemeMode } from '../../composables/useThemeMode'
import { host } from '../../api/hostStore'
import { openRestart } from './restart'
import { hostApi } from '../../api/host'
import { localeOptions, setLocale } from '../../i18n'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'
import Kbd from '../../ui/Kbd.vue'
import { areaTarget, navAreas } from '../nav'
import { groupsTarget } from '../../views/groups/route'
import { roleLabel, useRoleSwitch, useRoles } from '../../views/groups/roleSwitch'
import { groupLabel, groupSecondaryId } from './scenes'

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

const { usable } = useRoles()
const { switchRole } = useRoleSwitch()

const commands = computed<Command[]>(() => {
  const pages = navAreas.flatMap((area) => {
    const entries = area.pages.length ? area.pages : [{ route: area.route, label: area.label }]
    return entries.map((page) => ({
      id: `page:${page.route}`,
      kind: 'page' as const,
      title: area.pages.length ? `${t(area.label)} · ${t(page.label)}` : t(page.label),
      keywords: `${page.route} ${area.id}`,
      icon: area.icon,
      to: area.pages.length ? { name: page.route } : areaTarget(area, props.scene),
    }))
  })
  const scenes = (host.state?.scenes ?? []) as {
    scene: string
    persona?: { name: string }
    persona_path: string
    persona_switch: { key: string } | null
    chat_enabled: boolean
  }[]
  const groups = scenes.map((item) => ({
    id: `group:${item.scene}`,
    kind: 'group' as const,
    title: groupLabel(item.scene),
    detail: [groupSecondaryId(item.scene), item.persona?.name].filter(Boolean).join(' · ') || undefined,
    keywords: item.scene,
    icon: MessagesSquare,
    to: groupsTarget(item.scene),
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
  // Only offered when searching, like the other actions; a group waiting for a switch is left alone.
  const roles = scenes
    .filter((item) => !item.persona_switch)
    .flatMap((item) =>
      usable.value
        .filter((role) => role.path !== item.persona_path)
        .map((role) => ({
          id: `role:${item.scene}:${role.key}`,
          kind: 'action' as const,
          title: t('palette.actions.role', { group: groupLabel(item.scene), name: roleLabel(role) }),
          keywords: `${item.scene} ${role.key} role persona`,
          icon: UserRound,
          run: () => switchRole(item.scene, role),
        })),
    )
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
  return [...pages, ...groups, ...switches, ...roles, ...themes, ...languages, restart]
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
  } else if (event.key === 'Home' && count) {
    event.preventDefault()
    cursor.value = 0
  } else if (event.key === 'End' && count) {
    event.preventDefault()
    cursor.value = count - 1
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
      <DialogOverlay class="ui-overlay fixed inset-0 z-(--z-dialog) bg-overlay backdrop-blur-[2px]" />
      <DialogContent
        :aria-describedby="undefined"
        class="ui-dialog fixed top-[10vh] left-1/2 z-(--z-dialog) flex max-h-[72dvh] w-[calc(100vw-24px)] max-w-xl -translate-x-1/2 flex-col overflow-hidden rounded-xl border border-line bg-surface-raised text-ink shadow-dialog outline-none sm:top-[12vh]"
      >
        <DialogTitle class="sr-only">{{ t('palette.label') }}</DialogTitle>
        <label class="flex shrink-0 items-center gap-3 border-b border-line px-4">
          <Search :size="17" class="shrink-0 text-subtle" aria-hidden="true" />
          <input
            ref="input"
            v-model="query"
            :placeholder="t('palette.placeholder')"
            :aria-label="t('palette.label')"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            :aria-activedescendant="results[cursor] ? `palette-${cursor}` : undefined"
            class="h-12 min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-subtle focus-visible:outline-none max-sm:text-lg"
            @keydown="onKey"
          />
          <span class="max-sm:hidden"><Kbd>Esc</Kbd></span>
        </label>
        <ul
          id="palette-list"
          ref="list"
          role="listbox"
          class="min-h-0 flex-1 overflow-y-auto p-1.5 scrollbar-thin"
        >
          <template v-for="(item, index) in results" :key="item.id">
            <li
              v-if="!query.trim() && (index === 0 || results[index - 1]?.kind !== item.kind)"
              role="presentation"
              aria-hidden="true"
              class="px-2.5 pt-2 pb-1 text-xs font-medium text-subtle select-none first:pt-1"
            >
              {{ t(`palette.kinds.${item.kind}`) }}
            </li>
            <li
              :id="`palette-${index}`"
              :data-index="index"
              role="option"
              :aria-selected="index === cursor"
              class="flex min-h-9.5 cursor-pointer items-center gap-3 rounded-md px-2.5 py-1.5 text-sm text-ink-2 transition-colors aria-selected:bg-hover aria-selected:text-ink"
              @mousemove="cursor = index"
              @click="choose(item)"
            >
              <component
                :is="item.icon"
                :size="16"
                class="shrink-0 transition-colors"
                :class="index === cursor ? 'text-primary' : 'text-muted'"
                aria-hidden="true"
              />
              <span class="min-w-0 truncate font-medium">{{ item.title }}</span>
              <span v-if="item.detail" class="min-w-0 truncate text-xs text-muted tabular">
                {{ item.detail }}
              </span>
              <span v-if="query.trim()" class="ml-auto shrink-0 text-xs text-subtle">
                {{ t(`palette.kinds.${item.kind}`) }}
              </span>
              <CornerDownLeft
                v-if="index === cursor"
                :size="14"
                class="shrink-0 text-subtle"
                :class="!query.trim() && 'ml-auto'"
                aria-hidden="true"
              />
            </li>
          </template>
          <li v-if="!results.length" class="px-3 py-8 text-center text-sm text-muted">
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
