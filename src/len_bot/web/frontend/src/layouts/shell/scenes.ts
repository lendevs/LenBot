import { sceneTitles } from '../../api/scenes'

/** Group name when known, otherwise the group number; the platform prefix is never shown. */
export function groupLabel(scene: string): string {
  return sceneTitles[scene] || scene.split(':').slice(2).join(':') || scene
}

/** Secondary group ID when a distinct group title is known; empty when `groupLabel` already shows the ID. */
export function groupSecondaryId(scene: string): string {
  if (!sceneTitles[scene]) return ''
  const id = scene.split(':').slice(2).join(':')
  return id && id !== sceneTitles[scene] ? id : ''
}

export const sceneSecondaryId = groupSecondaryId

/** Platform prefix of a scene id (e.g. `onebot`, `telegram`, `feishu`), or empty when absent. */
export function scenePlatform(scene: string): string {
  const colon = scene.indexOf(':')
  return colon > 0 ? scene.slice(0, colon) : ''
}

/** Whether a scene id refers to a private chat rather than a group. */
export function isPrivateScene(scene: string): boolean {
  return scene.split(':')[1] === 'private'
}
