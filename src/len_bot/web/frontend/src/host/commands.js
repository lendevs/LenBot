import { hostGroups } from '../router/hostNavigation.js'

// Sub-pages reachable by `?tab=`; kept beside the pages' own tab lists so the palette can jump straight there.
const pageTabs = {
  'host-system': [['connection', '连接'], ['chat', '群聊发言'], ['account', '面板账号'], ['retention', '数据保留'], ['updates', '版本与更新'], ['advanced', '高级']],
  'host-models': [['providers', '服务商'], ['roles', '用途'], ['vectors', '向量模型'], ['usage', '用量与上限']],
  'host-scenes': [['messages', '消息'], ['settings', '设置'], ['permissions', '权限'], ['brain', '会话'], ['learning', '学习']],
  'host-persona': [['profile', '设定'], ['knowledge', '资料'], ['stickers', '表情'], ['package', '导入导出']],
  'host-capabilities': [['tools', '工具与技能'], ['mcp', 'MCP 服务'], ['web', '网页'], ['tasks', '独立任务']],
  'host-logs': [['turns', '回复记录'], ['system', '系统日志']],
  'host-tasks': [['tasks', '独立任务'], ['schedules', '提醒']],
}

// Pinyin (full and initials) so the palette works without switching the input method.
const spell = {
  首页: 'shouye sy home', 对话测试: 'duihuaceshi dhcs trial', 日志: 'rizhi rz logs', 群聊: 'qunliao ql scenes', 角色: 'juese js persona',
  记忆: 'jiyi jy memory', 任务: 'renwu rw tasks', 资源: 'ziyuan zy resources', 插件: 'chajian cj plugins', 能力: 'nengli nl capabilities',
  模型: 'moxing mx models', 设置: 'shezhi sz settings', 连接: 'lianjie lj', 群聊发言: 'qunliaofayan qlfy', 面板账号: 'mianbanzhanghao mbzh',
  数据保留: 'shujubaoliu sjbl', 版本与更新: 'banbenyugengxin bbygx gengxin gx', 高级: 'gaoji gj', 服务商: 'fuwushang fws', 用途: 'yongtu yt',
  向量模型: 'xiangliangmoxing xlmx', 用量与上限: 'yongliangyushangxian ylysx', 消息: 'xiaoxi xx', 权限: 'quanxian qx', 会话: 'huihua hh',
  学习: 'xuexi xx', 设定: 'sheding sd', 资料: 'ziliao zl', 表情: 'biaoqing bq', 导入导出: 'daorudaochu drdc', 工具与技能: 'gongjuyujineng gjyjn',
  网页: 'wangye wy', 独立任务: 'dulirenwu dlrw', 回复记录: 'huifujilu hfjl', 系统日志: 'xitongrizhi xtrz', 提醒: 'tixing tx',
}

export function pageCommands() {
  const out = []
  for (const group of hostGroups) for (const area of group.areas) {
    out.push({ id: `page:${area.id}`, kind: '页面', title: area.title, hint: group.title, area: area.id,
      keywords: spell[area.title] || '', to: { name: area.name } })
    for (const [tab, label] of pageTabs[area.name] || []) {
      out.push({ id: `tab:${area.id}:${tab}`, kind: '页面', title: `${area.title} · ${label}`, hint: group.title, area: area.id,
        keywords: `${tab} ${spell[area.title] || ''} ${spell[label] || ''}`, to: { name: area.name, query: { tab } } })
    }
  }
  return out
}

// Whole words beat word prefixes, which beat substrings, which beat loose subsequences; lower is better.
export function matchScore(text, query) {
  const hay = text.toLowerCase(), needle = query.trim().toLowerCase()
  if (!needle) return 0
  const words = hay.split(/[\s·]+/)
  if (words.includes(needle)) return 0
  if (words.some(word => word.startsWith(needle))) return 1
  const at = hay.indexOf(needle)
  if (at >= 0) return 10 + at
  let pos = -1, gaps = 0
  for (const ch of needle.replace(/\s+/g, '')) {
    const next = hay.indexOf(ch, pos + 1)
    if (next < 0) return null
    gaps += next - pos - 1
    pos = next
  }
  return 1000 + gaps
}

export function filterCommands(items, query, limit = 12) {
  if (!query.trim()) return items.slice(0, limit)
  return items.map(item => ({ item, score: matchScore(`${item.title} ${item.hint || ''} ${item.keywords || ''}`, query) }))
    .filter(entry => entry.score !== null).sort((a, b) => a.score - b.score)
    // Loose matches are only a fallback; once something matches properly they are just noise.
    .filter((entry, _, all) => entry.score < 1000 || all[0].score >= 1000).slice(0, limit).map(entry => entry.item)
}
