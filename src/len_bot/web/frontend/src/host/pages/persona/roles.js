import { api, sceneName } from '../../../api.js'

export const roleBase = key => `/api/host/personas/${encodeURIComponent(key)}`

export const roleAvatarUrl = (role, version = 0) =>
  `${roleBase(role.key)}/avatar/image?directory=${encodeURIComponent(role.path)}&v=${version}`

export const roleLabel = role => role.name || role.key

export function roleUsage(role) {
  const names = role.scenes.map(sceneName)
  if (!names.length) return '没有群在用'
  return names.length > 2 ? `用在 ${names.slice(0, 2).join('、')} 等 ${names.length} 个群` : `用在 ${names.join('、')}`
}

// A new role's folder is also its id: lowercase letters, digits and single hyphens.
export const folderProblem = value => !value ? '' : /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value) && value.length <= 64 ? ''
  : '只能用小写英文字母、数字和 -，不能以 - 开头或结尾'

// Switch scenes to the role; a scene busy with a reply switches when that turn ends.
export async function applyRole(role, scenes) {
  const { results } = await api(`${roleBase(role.key)}/scenes`, { method: 'POST', body: JSON.stringify({ scenes }) })
  const failed = results.filter(item => item.status === 'failed')
  const pending = results.filter(item => item.status === 'pending')
  const handover = results.filter(item => item.handover === 'failed')
  if (failed.length && failed.length === results.length) throw new Error(failed.map(item => `${sceneName(item.scene)}：${item.error}`).join('\n'))
  const parts = [pending.length ? `${pending.map(item => sceneName(item.scene)).join('、')} 等这一轮回复结束后换成 ${roleLabel(role)}`
    : `已换成 ${roleLabel(role)}`]
  if (failed.length) parts.push(`${failed.map(item => sceneName(item.scene)).join('、')} 没换成`)
  if (handover.length) parts.push('聊天交接没写成，已提醒新角色之前的话不是它说的')
  return { results, message: parts.join('；') }
}

export async function downloadRole(role) {
  const blob = await api(`${roleBase(role.key)}/package`, {}, 'blob')
  const url = URL.createObjectURL(blob), link = document.createElement('a')
  link.href = url
  link.download = `persona-${role.key}.zip`
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// What a save response says about the scenes running the role.
export const savedNotice = result => result.apply_error ? result.apply_error
  : result.applied === false ? '已保存，正在回复的群这一轮结束后用上' : '已保存'
