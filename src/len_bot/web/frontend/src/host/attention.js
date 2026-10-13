import { sceneName } from '../api.js'
import { runtimeLabel, turnFailed } from './labels.js'
import { formatAgo, formatTime } from './time.js'

export const connectionLabel = connection => connection.status === 'running' ? 'QQ 未连接' : runtimeLabel(connection.status)

export function attentionItems(state, day) {
  const items = []
  if (state && !(state.connection.connected && state.connection.accepting)) {
    items.push({ key: 'connection', text: connectionLabel(state.connection),
      to: { name: 'host-system', query: { tab: 'connection' } }, action: '连接设置' })
  }
  const places = { 插件: name => ({ name: 'host-plugins', query: { item: name } }),
    'MCP 服务': name => ({ name: 'host-capabilities', query: { tab: 'mcp', item: name } }) }
  for (const [kind, list] of [['插件', state?.plugins || []], ['MCP 服务', state?.mcp || []]]) {
    for (const item of list) {
      if (item.status === 'failed') items.push({ key: `${kind}:${item.name}`, text: `${kind} ${item.name} 没有启动成功`,
        error: item.error, to: places[kind](item.name), action: '查看' })
      else if (item.latest_error) items.push({ key: `${kind}:${item.name}`, text: `${kind} ${item.name} ${formatAgo(item.latest_error.at)}报错`,
        error: item.latest_error.error, to: places[kind](item.name), action: '查看' })
    }
  }
  if (!day) return items
  perScene(items, 'send', Object.entries(day.undelivered), (scene, total) => ({ text: `${sceneName(scene)} 今天有 ${total} 条消息没发出去`,
    count: total, to: { name: 'host-scenes', query: { scene } }, action: '查看' }), (groups, total) => `${groups} 个群今天有 ${total} 条消息没发出去`)
  const failures = {}
  for (const turn of day.recent_errors) {
    if (turn.started >= day.since && turnFailed(turn.status)) failures[turn.scene] = (failures[turn.scene] || 0) + 1
  }
  perScene(items, 'turn', Object.entries(failures), (scene, total) => ({ text: `${sceneName(scene)} 今天有 ${total} 次回复出错`,
    count: total, to: { name: 'host-logs', query: { scene } }, action: '查看' }), (groups, total) => `${groups} 个群今天共有 ${total} 次回复出错`)
  perScene(items, 'task', Object.entries(day.failed_tasks), (scene, total) => ({ text: `${sceneName(scene)} 今天有 ${total} 个任务失败`,
    count: total, to: { name: 'host-tasks', query: { scene } }, action: '查看' }), (groups, total) => `${groups} 个群今天共有 ${total} 个任务失败`)
  if (day.memory_stuck.length) {
    const rows = day.memory_stuck.map(job => ({ key: `memory:${job.scene}`, error: job.error, action: '去重试',
      text: `${sceneName(job.scene)} 的记忆整理${job.status === 'failed' ? '失败' : '被中断'}，停在这里等你重试`,
      to: { name: 'host-memory', query: { scene: job.scene, tab: 'ingest' } } }))
    items.push(rows.length === 1 ? rows[0] : { key: 'memory', text: `${rows.length} 个群的记忆整理停住了，需要逐个重试`, children: rows })
  }
  for (const [scene, until] of Object.entries(day.speech_held || {})) {
    items.push({ key: `speech:${scene}`, text: `${sceneName(scene)} 本小时发言已到上限，${formatTime(until, null, { date: false })} 恢复`,
      to: { name: 'host-scenes', query: { scene, tab: 'settings' } }, action: '查看' })
  }
  perScene(items, 'review', Object.entries(day.pending_reviews), (scene, reviews) => {
    const parts = [['expressions', '条表达'], ['stickers', '张表情']]
      .filter(([key]) => reviews[key]).map(([key, unit]) => `${reviews[key]} ${unit}`)
    return { text: `${sceneName(scene)} 新学到 ${parts.join('、')}，等你审核`, count: 1,
      to: { name: 'host-scenes', query: { scene, tab: 'learning' } }, action: '去审核' }
  }, groups => `${groups} 个群新学到的表达或表情等你审核`)
  return items
}

// The same kind of trouble in many groups reads as one item; each group stays one click away inside it.
function perScene(items, kind, entries, describe, summary) {
  const rows = entries.map(([scene, value]) => ({ key: `${kind}:${scene}`, ...describe(scene, value) }))
  if (rows.length < 3) {
    items.push(...rows)
    return
  }
  items.push({ key: kind, text: summary(rows.length, rows.reduce((sum, row) => sum + row.count, 0)), children: rows })
}
