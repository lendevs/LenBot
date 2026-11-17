import { sceneTitles } from '../../api/scenes'

/** Group name when known, otherwise the group number; the platform prefix is never shown. */
export function groupLabel(scene: string): string {
  const titles = sceneTitles as Record<string, string>
  return titles[scene] || scene.split(':').slice(2).join(':') || scene
}

/** Secondary group ID when a distinct group title is known; empty when `groupLabel` already shows the ID. */
export function groupSecondaryId(scene: string): string {
  const titles = sceneTitles as Record<string, string>
  if (!titles[scene]) return ''
  const id = scene.split(':').slice(2).join(':')
  return id && id !== titles[scene] ? id : ''
}
