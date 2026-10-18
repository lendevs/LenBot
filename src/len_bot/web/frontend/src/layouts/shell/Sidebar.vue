<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import markUrl from '../../assets/lenbot-mark.svg'
import Tooltip from '../../ui/Tooltip.vue'
import { areaOf, navGroups, type NavArea } from '../nav'

const props = defineProps<{
  collapsed: boolean
  /** Group currently selected on group pages; kept when moving between them. */
  scene: string
  /** Areas that show a small warning dot. */
  flagged: Set<string>
}>()

const { t } = useI18n()
const route = useRoute()

function target(area: NavArea) {
  return { name: area.route, query: area.scoped && props.scene ? { scene: props.scene } : {} }
}
</script>

<template>
  <div class="flex h-full flex-col">
    <RouterLink
      :to="{ name: 'host-overview' }"
      class="group flex h-14 shrink-0 items-center gap-3 px-4 text-ink link-plain"
      :class="collapsed && 'justify-center px-0'"
    >
      <img
        :src="markUrl"
        alt=""
        class="size-7 shrink-0 transition-transform duration-300 ease-out group-hover:-rotate-8"
      />
      <span v-if="!collapsed" class="min-w-0 leading-tight">
        <strong class="block text-lg font-semibold">LenBot</strong>
        <span class="block text-xs text-muted">{{ t('shell.console') }}</span>
      </span>
    </RouterLink>
    <nav :aria-label="t('shell.nav.label')" class="flex-1 overflow-y-auto px-3 pt-1 pb-4 scrollbar-thin">
      <div v-for="group in navGroups" :key="group.id" class="mb-4 flex flex-col gap-0.5">
        <div v-if="!collapsed" class="px-2.5 pb-1 text-xs font-semibold tracking-wide text-subtle">
          {{ t(group.label) }}
        </div>
        <div v-else class="mx-auto mb-1 h-px w-6 bg-line" aria-hidden="true" />
        <Tooltip
          v-for="area in group.areas"
          :key="area.id"
          :text="t(area.label)"
          side="right"
          :disabled="!collapsed"
        >
          <RouterLink
            :to="target(area)"
            :aria-current="areaOf(route.name) === area ? 'page' : undefined"
            :aria-label="collapsed ? t(area.label) : undefined"
            class="link-plain relative flex h-9 items-center gap-3 rounded-md px-2.5 text-base text-ink-2 transition-[background-color,color,box-shadow] duration-150 hover:bg-hover hover:text-ink focus-visible:focus-ring aria-[current=page]:bg-surface aria-[current=page]:font-semibold aria-[current=page]:text-ink aria-[current=page]:shadow-card pointer-coarse:h-11"
            :class="collapsed && 'justify-center px-0'"
          >
            <component
              :is="area.icon"
              :size="18"
              class="shrink-0 transition-colors"
              :class="areaOf(route.name) === area ? 'text-primary' : 'text-muted'"
              aria-hidden="true"
            />
            <span v-if="!collapsed" class="truncate">{{ t(area.label) }}</span>
            <span
              v-if="flagged.has(area.id)"
              class="size-1.5 shrink-0 rounded-full bg-warning"
              :class="collapsed ? 'absolute top-1.5 right-2' : 'ml-auto'"
              aria-hidden="true"
            />
          </RouterLink>
        </Tooltip>
      </div>
    </nav>
    <slot name="footer" />
  </div>
</template>
