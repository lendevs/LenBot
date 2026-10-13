import { sceneName } from '../../../api.js'
import { permissionSummary } from '../../pluginPermissions.js'

// Read-only views over the plugins snapshot, shared by the list and the detail page.

export function manifestOf(snapshot, name) {
  const entries = snapshot.available[name] || []
  return entries.length === 1 && !entries[0].error ? entries[0] : null
}
export const runningOf = (snapshot, name) => snapshot.running.plugins.find(item => item.name === name) || null
export const enabledIn = (snapshot, name) => Boolean(snapshot.saved.plugins[name]) && !snapshot.saved.disabled.includes(name)
export const scenesUsing = (snapshot, name) => Object.keys(snapshot.scenes).filter(scene => (snapshot.scenes[scene].saved || []).includes(name))
export const versionOf = (snapshot, name) => runningOf(snapshot, name)?.version
  || manifestOf(snapshot, name)?.source?.installed?.version || manifestOf(snapshot, name)?.version || ''

export function statusIn(snapshot, name) {
  if (snapshot.saved.disabled.includes(name)) return { text: '已停用', tone: 'neutral' }
  const running = runningOf(snapshot, name)
  if (running) return { kind: 'plugin', value: running.status }
  return { kind: 'plugin', value: snapshot.saved.plugins[name] ? 'pending' : 'unloaded' }
}

export function factsOf(snapshot, name) {
  const manifest = manifestOf(snapshot, name), source = manifest?.source, running = runningOf(snapshot, name)
  return [
    ['源码版本', source?.installed ? `v${source.installed.version}` : source ? '尚未应用' : manifest ? `v${manifest.version}` : ''],
    ['候选版本', source?.candidate ? `v${source.candidate.version}` : ''],
    ['生效方式', source?.candidate ? source.application === 'host' ? (source.requested ? '已选择，下次明确重启时应用' : '应用后需要重启') : '应用时重载这个插件' : ''],
    ['运行版本', running?.version ? `v${running.version}` : '未加载'],
    ['在用的群', running?.scenes.map(sceneName).join('、') || '没有'],
    ['安装来源', source?.installed ? `${source.installed.kind} · ${source.installed.location} · ${source.installed.ref || source.installed.branch || source.installed.revision}` : ''],
    ['候选来源', source?.candidate ? `${source.candidate.kind} · ${source.candidate.location} · ${source.candidate.revision}` : ''],
    ['兼容范围', manifest ? `宿主 ${manifest.requires_lenbot} · Python ${manifest.requires_python} · ${manifest.platforms.join('、')}` : ''],
    ['依赖', manifest?.dependencies.join('、') || ''],
    ['目录', (snapshot.available[name] || []).map(entry => entry.directory).join('、')],
  ]
}

export const featureCount = running => running ? running.commands.length + running.rules.length + running.tools.length : 0

export const permissionsOf = (snapshot, name) => runningOf(snapshot, name)?.permissions ?? manifestOf(snapshot, name)?.permissions ?? null
export const isolationOf = (snapshot, name) => runningOf(snapshot, name)?.isolation || manifestOf(snapshot, name)?.isolation || 'inline'
export function healthNote(health) {
  if (!health || health.level !== 'degraded') return ''
  return health.errors_last_hour ? `近 1 小时报错 ${health.errors_last_hour} 次` : `${health.failing.join('、')} 失败`
}
// A candidate that is not applied yet may ask for different permissions or isolation than the running one.
export function candidateChange(snapshot, name) {
  const now = runningOf(snapshot, name), next = manifestOf(snapshot, name)
  if (!now || !next || !('permissions' in next)) return ''
  const names = list => list == null ? null : list.map(item => item.name).sort().join(',')
  const parts = []
  if (names(now.permissions) !== names(next.permissions)) parts.push(permissionSummary(next.permissions))
  if ((now.isolation || 'inline') !== (next.isolation || 'inline')) parts.push(next.isolation === 'process' ? '改为独立进程' : '改为和主程序同进程')
  return parts.join('；')
}
