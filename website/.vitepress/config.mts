import { defineConfig } from 'vitepress'

const repo = 'https://github.com/lendevs/LenBot'

export default defineConfig({
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
    logo: '/lenbot-mark.svg',
    nav: [
      { text: '指南', link: '/guide/introduction', activeMatch: '^/guide/' },
      { text: '扩展开发', link: '/develop/personas', activeMatch: '^/develop/' },
    ],
    sidebar: {
      '/guide/': [
        { text: '开始使用', items: [
          { text: '认识 LenBot', link: '/guide/introduction' },
          { text: '快速开始', link: '/guide/quick-start' },
          { text: '首次配置', link: '/guide/first-setup' },
          { text: '接入 QQ（OneBot）', link: '/guide/onebot' },
        ] },
        { text: '面板与日常运营', items: [
          { text: '面板一览', link: '/guide/panel' },
          { text: '在群里聊天', link: '/guide/chatting' },
          { text: '角色管理', link: '/guide/personas' },
          { text: '群内命令与权限', link: '/guide/commands' },
        ] },
        { text: '记忆、资料与能力', items: [
          { text: '记忆与学习', link: '/guide/memory' },
          { text: '资料检索', link: '/guide/reference' },
          { text: '模型与用量', link: '/guide/models' },
          { text: '联网与工具', link: '/guide/web' },
          { text: '插件管理', link: '/guide/plugins' },
          { text: '后台任务', link: '/guide/tasks' },
        ] },
        { text: '维护与排错', items: [
          { text: '更新与备份', link: '/guide/maintenance' },
          { text: '日志与排查', link: '/guide/logs' },
          { text: '常见问题', link: '/guide/faq' },
        ] },
      ],
      '/develop/': [
        { text: '角色与插件', items: [
          { text: '写角色包', link: '/develop/personas' },
          { text: '写插件', link: '/develop/plugins' },
        ] },
        { text: '核心贡献', items: [
          { text: '参与开发', link: '/develop/contributing' },
        ] },
      ],
    },
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
