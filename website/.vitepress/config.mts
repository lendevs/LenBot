import { readFileSync } from 'node:fs'
import { defineConfigWithTheme, type DefaultTheme } from 'vitepress'

const repo = 'https://github.com/lendevs/LenBot'
// The release the deployment commands on the site refer to.
const version = readFileSync(new URL('../../pyproject.toml', import.meta.url), 'utf8').match(/^version = "(.+)"$/m)![1]

export default defineConfigWithTheme<DefaultTheme.Config & { version: string }>({
  lang: 'zh-CN',
  title: 'LenBot',
  description: '自主决策的群聊 Agent，接入 QQ（OneBot v11），通过网页面板配置与管理',
  base: '/LenBot/',
  cleanUrls: true,
  lastUpdated: true,
  head: [
    ['link', { rel: 'icon', href: '/LenBot/lenbot-favicon.svg', type: 'image/svg+xml' }],
    ['meta', { name: 'theme-color', content: '#b4476a' }],
    ['meta', { property: 'og:image', content: 'https://lendevs.github.io/LenBot/brand/lenbot-social-preview.png' }],
  ],
  themeConfig: {
    version,
    logo: '/lenbot-mark.svg',
    nav: [
      { text: '开始', link: '/start/introduction', activeMatch: '^/start/' },
      { text: '接入', link: '/connect/onebot', activeMatch: '^/connect/' },
      { text: '使用', link: '/use/panel', activeMatch: '^/use/' },
      { text: '开发', link: '/develop/personas', activeMatch: '^/develop/' },
    ],
    sidebar: [
      { text: '开始', collapsed: false, items: [
        { text: '认识 LenBot', link: '/start/introduction' },
        { text: '快速开始', link: '/start/quick-start' },
        { text: 'Docker 部署', link: '/start/docker' },
        { text: '部署包', link: '/start/package' },
        { text: '源码运行', link: '/start/source' },
        { text: '首次配置', link: '/start/first-setup' },
        { text: '对话测试', link: '/start/playground' },
      ] },
      { text: '接入', collapsed: false, items: [
        { text: 'QQ（OneBot）', link: '/connect/onebot' },
        { text: '模型与用量', link: '/connect/models' },
        { text: '联网与工具', link: '/connect/web' },
      ] },
      { text: '使用', collapsed: false, items: [
        { text: '面板一览', link: '/use/panel' },
        { text: '在群里聊天', link: '/use/chatting' },
        { text: '角色管理', link: '/use/personas' },
        { text: '群内命令与权限', link: '/use/commands' },
        { text: '记忆与学习', link: '/use/memory' },
        { text: '资料检索', link: '/use/reference' },
        { text: '插件管理', link: '/use/plugins' },
        { text: '后台任务', link: '/use/tasks' },
      ] },
      { text: '维护', collapsed: false, items: [
        { text: '更新与备份', link: '/use/maintenance' },
        { text: '日志与排查', link: '/use/logs' },
        { text: '常见问题', link: '/use/faq' },
      ] },
      { text: '开发', collapsed: false, items: [
        { text: '写角色包', link: '/develop/personas' },
        { text: '写插件', link: '/develop/plugins' },
        { text: '参与开发', link: '/develop/contributing' },
      ] },
    ],
    socialLinks: [{ icon: 'github', link: repo }],
    editLink: { pattern: `${repo}/edit/master/website/:path`, text: '在 GitHub 上修改这一页' },
    search: {
      provider: 'local',
      options: { translations: { button: { buttonText: '搜索', buttonAriaLabel: '搜索' },
        modal: { noResultsText: '没有找到', resetButtonTitle: '清除', footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' } } } },
    },
    outline: { level: [2, 3], label: '本页内容' },
    docFooter: { prev: '上一页', next: '下一页' },
    lastUpdated: { text: '最后更新' },
    returnToTopLabel: '回到顶部',
    sidebarMenuLabel: '目录',
    darkModeSwitchLabel: '外观',
    lightModeSwitchTitle: '切换到浅色',
    darkModeSwitchTitle: '切换到深色',
    notFound: { title: '页面不存在', quote: '链接已变更，可搜索或返回首页。', linkText: '回到首页' },
    footer: { message: '以 AGPL-3.0-only 发布', copyright: 'LenBot' },
  },
})
