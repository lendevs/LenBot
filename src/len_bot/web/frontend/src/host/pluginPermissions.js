// Same wording as PERMISSION_TITLES in plugins/manifest.py; the market lists bare permission names.
const titles = {
  send: '在启用的群里发消息', events: '把插件事件交给 Bot 作背景', history: '读取启用的群的聊天记录',
  memory: '读写启用的群的长期记忆', generate: '调用模型做单次生成（计入用量）',
  delegate: '以请求人的名义发起后台任务', network: '从公网获取图片', schedule: '登记定点任务',
}
export const permissionTitle = name => titles[name] || name
/** One line for a declared list: null is an undeclared (legacy) plugin with every capability. */
export function permissionSummary(list) {
  if (list == null) return '未声明权限，可以使用全部宿主能力'
  if (!list.length) return '不需要额外权限'
  return `需要：${list.map(item => typeof item === 'string' ? permissionTitle(item) : item.title).join('、')}`
}
