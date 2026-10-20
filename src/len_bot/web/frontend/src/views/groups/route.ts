import { ref } from 'vue'
import type { RouteLocationRaw } from 'vue-router'

export const groupTabs = ['live', 'session', 'memory', 'tasks', 'learning', 'settings'] as const
export type GroupTab = (typeof groupTabs)[number]

export function isGroupTab(value: unknown): value is GroupTab {
  return typeof value === 'string' && (groupTabs as readonly string[]).includes(value)
}

/** The tab last open in the workbench, so returning from another page lands on it again. */
export const lastGroupTab = ref<GroupTab>('live')

/**
 * Address of a group in the workbench. Scene ids always contain a colon and tab names never do, so
 * `/groups/memory` (no group chosen yet) still means the memory tab of the default group.
 */
export function groupsTarget(scene?: string, tab: GroupTab = lastGroupTab.value, query = {}): RouteLocationRaw {
  return scene
    ? { name: 'groups', params: { scene, tab }, query }
    : { name: 'groups', params: { scene: tab }, query }
}
