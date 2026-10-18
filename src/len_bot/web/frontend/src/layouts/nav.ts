import type { Component } from 'vue'
import {
  Blocks,
  Cpu,
  LayoutDashboard,
  MessagesSquare,
  MessageSquareText,
  Settings,
  UserRound,
  Wrench,
} from '@lucide/vue'

/** One entry of the sidebar. `pages` are route names shown as tabs under it while old pages are migrated. */
export interface NavArea {
  id: string
  label: string
  icon: Component
  route: string
  pages: { route: string; label: string }[]
  /** Pages that work on one group keep the selected group when switching. */
  scoped?: boolean
}

export interface NavGroup {
  id: string
  label: string
  areas: NavArea[]
}

export const navGroups: NavGroup[] = [
  {
    id: 'run',
    label: 'shell.groups.run',
    areas: [
      {
        id: 'overview',
        label: 'shell.pages.overview',
        icon: LayoutDashboard,
        route: 'host-overview',
        pages: [],
      },
      {
        id: 'playground',
        label: 'shell.pages.playground',
        icon: MessageSquareText,
        route: 'host-trials',
        pages: [],
      },
    ],
  },
  {
    id: 'chats',
    label: 'shell.groups.chats',
    areas: [
      {
        id: 'groups',
        label: 'shell.pages.groups',
        icon: MessagesSquare,
        route: 'host-scenes',
        scoped: true,
        pages: [
          { route: 'host-scenes', label: 'shell.pages.groupMessages' },
          { route: 'host-memory', label: 'shell.pages.groupMemory' },
          { route: 'host-tasks', label: 'shell.pages.groupTasks' },
          { route: 'host-resources', label: 'shell.pages.groupResources' },
        ],
      },
      { id: 'personas', label: 'shell.pages.personas', icon: UserRound, route: 'host-persona', pages: [] },
    ],
  },
  {
    id: 'extend',
    label: 'shell.groups.extend',
    areas: [
      { id: 'plugins', label: 'shell.pages.plugins', icon: Blocks, route: 'host-plugins', pages: [] },
      {
        id: 'capabilities',
        label: 'shell.pages.capabilities',
        icon: Wrench,
        route: 'host-capabilities',
        pages: [],
      },
    ],
  },
  {
    id: 'config',
    label: 'shell.groups.config',
    areas: [
      { id: 'models', label: 'shell.pages.models', icon: Cpu, route: 'host-models', pages: [] },
      {
        id: 'system',
        label: 'shell.pages.system',
        icon: Settings,
        route: 'host-system',
        pages: [
          { route: 'host-system', label: 'shell.pages.systemSettings' },
          { route: 'host-logs', label: 'shell.pages.systemLogs' },
        ],
      },
    ],
  },
]

export const navAreas = navGroups.flatMap((group) => group.areas)

export function areaOf(route: unknown): NavArea | undefined {
  return navAreas.find((area) => area.route === route || area.pages.some((page) => page.route === route))
}

export function groupOf(area: NavArea | undefined): NavGroup | undefined {
  return navGroups.find((group) => area !== undefined && group.areas.includes(area))
}

/** Route names that keep `?scene=` when reached from another page. */
export const scopedRoutes = new Set([
  'host-scenes',
  'host-memory',
  'host-tasks',
  'host-resources',
  'host-logs',
])

/** Root config sections → the restart banner label key (shell.restart.sections.*). */
const sectionKeys: Record<string, string> = {
  bot_id: 'connection',
  owners: 'connection',
  timezone: 'connection',
  onebot: 'connection',
  telegram: 'connection',
  delivery: 'connection',
  max_steps: 'connection',
  turn_timeout_seconds: 'connection',
  text_delivery: 'connection',
  max_model_requests: 'connection',
  panel: 'panel',
  permissions: 'permissions',
  models: 'models',
  limits: 'limits',
  retention: 'retention',
  compaction: 'context',
  images: 'context',
  audio: 'context',
  logging: 'context',
  web_read: 'web_read',
  web_search: 'web_search',
  network: 'network',
  memory: 'memory',
  worker: 'worker',
  commands: 'commands',
  account_browser: 'account_browser',
  plugins: 'plugins',
  mcp: 'mcp',
  prompts: 'prompts',
}

export function sectionKey(section: string): string {
  return `shell.restart.sections.${sectionKeys[section] ?? 'other'}`
}
