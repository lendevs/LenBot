import type { ComputedRef } from 'vue'
import type { RouteLocationNormalized } from 'vue-router'
import type { HostScene } from '../api/host'

export function resolveScene(value: unknown): string
export function useCurrentScene(): { scene: ComputedRef<string>; current: ComputedRef<HostScene | null> }
export function sceneTarget(route: RouteLocationNormalized, scene: string): unknown
export function showsScene(route: RouteLocationNormalized): boolean
