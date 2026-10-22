import { sceneTitles } from '../../api/scenes'

/** Group name when known, otherwise the group number; the platform prefix is never shown. */
export function groupLabel(scene: string): string {
  const titles = sceneTitles as Record<string, string>
  return titles[scene] || scene.split(':').slice(2).join(':') || scene
}
