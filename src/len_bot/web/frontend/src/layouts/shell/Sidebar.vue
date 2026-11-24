<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import markUrl from '../../assets/lenbot-mark.svg'
import Tooltip from '../../ui/Tooltip.vue'
import { areaOf, areaTarget, navGroups } from '../nav'

const props = defineProps<{
  collapsed: boolean
  /** Group currently selected on group pages; kept when moving between them. */
  scene: string
  /** Areas that show a small warning dot. */
  flagged: Set<string>
  /** Areas with updates waiting, and how many. */
  updates?: Record<string, number>
}>()
const emit = defineEmits<{ navigate: [] }>()

const { t } = useI18n()
const route = useRoute()
</script>

<template>
  <div class="flex h-full flex-col overflow-x-hidden">
    <div
      class="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-line transition-[padding] duration-250 ease-out"
      :class="collapsed ? 'px-4.5' : 'px-4'"
    >
      <RouterLink
        :to="{ name: 'host-overview' }"
        class="group flex min-w-0 items-center rounded-md text-ink link-plain focus-visible:focus-ring"
        @click="emit('navigate')"
      >
        <img
          :src="markUrl"
          alt=""
          class="size-7 shrink-0 transition-transform duration-300 ease-out group-hover:-rotate-8"
        />
        <span
          class="min-w-0 overflow-hidden leading-tight whitespace-nowrap transition-[opacity,width,margin] duration-200 ease-out"
          :class="collapsed ? 'pointer-events-none ml-0 w-0 opacity-0' : 'ml-2.5 w-32 opacity-100'"
          :aria-hidden="collapsed || undefined"
        >
          <strong class="block truncate text-base font-semibold tracking-tight">LenBot</strong>
          <span class="block truncate text-xs text-muted">{{ t('shell.console') }}</span>
        </span>
      </RouterLink>
      <slot v-if="!collapsed" name="header-end" />
    </div>
    <nav
      :aria-label="t('shell.nav.label')"
      class="flex flex-1 flex-col gap-4 overflow-x-hidden overflow-y-auto px-2.5 py-3 scrollbar-thin"
    >
      <div v-for="(group, groupIndex) in navGroups" :key="group.id" class="flex flex-col gap-0.5">
        <div class="relative flex h-5 items-center overflow-hidden px-2.5">
          <span
            class="truncate text-xs font-medium whitespace-nowrap text-muted transition-[opacity,width] duration-200 ease-out"
            :class="collapsed ? 'pointer-events-none w-0 opacity-0' : 'w-full opacity-100'"
            :aria-hidden="collapsed || undefined"
          >
            {{ t(group.label) }}
          </span>
          <span
            v-if="groupIndex > 0"
            class="pointer-events-none absolute inset-x-0 mx-auto h-px w-6 bg-line transition-opacity duration-200 ease-out"
            :class="collapsed ? 'opacity-100' : 'opacity-0'"
            aria-hidden="true"
          />
        </div>
        <Tooltip
          v-for="area in group.areas"
          :key="area.id"
          :text="t(area.label)"
          side="right"
          :disabled="!collapsed"
        >
          <RouterLink
            :to="areaTarget(area, props.scene)"
            :aria-current="areaOf(route.name) === area ? 'page' : undefined"
            :aria-label="collapsed ? t(area.label) : undefined"
            class="group/nav link-plain relative flex h-9 items-center rounded-md text-sm font-medium text-ink-2 transition-[background-color,color,box-shadow,padding] duration-200 ease-out hover:bg-hover hover:text-ink focus-visible:focus-ring aria-[current=page]:bg-surface-raised aria-[current=page]:font-semibold aria-[current=page]:text-ink aria-[current=page]:shadow-card aria-[current=page]:ring-1 aria-[current=page]:ring-line pointer-coarse:h-11"
            :class="collapsed ? 'px-[13px]' : 'px-2.5'"
            @click="emit('navigate')"
          >
            <component
              :is="area.icon"
              :size="17"
              class="shrink-0 transition-colors"
              :class="areaOf(route.name) === area ? 'text-primary' : 'text-muted group-hover/nav:text-ink-2'"
              aria-hidden="true"
            />
            <span
              class="min-w-0 truncate whitespace-nowrap transition-[opacity,width,margin] duration-200 ease-out"
              :class="
                collapsed ? 'pointer-events-none ml-0 w-0 flex-none opacity-0' : 'ml-2.5 flex-1 opacity-100'
              "
              :aria-hidden="collapsed || undefined"
            >
              {{ t(area.label) }}
            </span>
            <span
              v-if="updates?.[area.id] && !collapsed"
              class="ml-1.5 inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-info-bg px-1.5 text-xs leading-none font-semibold text-info tabular"
              :aria-label="t('shell.updatesWaiting', { n: updates[area.id] }, updates[area.id])"
            >
              {{ updates[area.id] }}
            </span>
            <span
              v-else-if="updates?.[area.id] && !flagged.has(area.id)"
              class="absolute top-1.5 right-1.5 size-2 shrink-0 rounded-full bg-info ring-2 ring-sidebar"
              aria-hidden="true"
            />
            <span
              v-if="flagged.has(area.id)"
              class="size-2 shrink-0 rounded-full bg-warning"
              :class="collapsed ? 'absolute top-1.5 right-1.5 ring-2 ring-sidebar' : 'ml-1.5'"
              aria-hidden="true"
            />
          </RouterLink>
        </Tooltip>
      </div>
    </nav>
    <slot name="footer" />
  </div>
</template>
