import { groupLabel } from '../../layouts/shell/scenes'
import type { Tone } from '../../ui/Badge.vue'

const mcpTones: Record<string, Tone> = {
  running: 'success',
  connecting: 'info',
  failed: 'error',
  disabled: 'neutral',
  stopped: 'neutral',
}
export const mcpTone = (status: string): Tone => mcpTones[status] ?? 'neutral'

/** Group ID without the platform prefix, omitted when `groupLabel` already falls back to it. */
export function sceneSecondaryId(scene: string): string {
  const id = scene.split(':').slice(2).join(':') || scene
  return groupLabel(scene) === id ? '' : id
}
