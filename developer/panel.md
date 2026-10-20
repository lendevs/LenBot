# 面板前端

面向修改 `src/len_bot/web/frontend` 的开发者。读完这一篇，应该能按约定新增一个页面。后端接口、实时事件协议和时间线接口的说明在[架构](architecture.md#面板)。

## 技术栈

| 用途 | 选择 |
|---|---|
| 框架 | Vue 3（`<script setup lang="ts">`），TypeScript 严格模式 |
| 交互原语 | Reka UI：焦点管理、键盘操作、aria 属性都由它提供 |
| 样式 | Tailwind CSS v4，颜色等取值全部来自设计令牌 |
| 服务端状态 | TanStack Query（`@tanstack/vue-query`） |
| 长列表 | TanStack Virtual，经 `ui/VirtualList.vue` 使用 |
| 双语 | vue-i18n，中文是源语言 |
| 图标 | `@lucide/vue`，按需引入单个图标组件 |

检查命令在前端目录执行：`npm run typecheck`、`npm run lint`（ESLint 加 Prettier）、`npm run build`。CI 跑同样三项。构建产物写到 `src/len_bot/web/static/dist`，不进 Git。

迁移期间旧页面（`src/host/`、`src/components/`、部分 `src/views/`）仍使用 Vuetify 和纯 JS，ESLint 忽略这些目录。新代码不引用 Vuetify，不新写 `.js` 文件。Vuetify 存在期间 Tailwind 不加载预检样式（preflight），工具类不放进层里，原因写在 `styles/app.css` 开头。Vuetify 自带同名的颜色类（`bg-info`、`text-success` 等，带 `!important`），会盖过 Tailwind 的同名工具类，所以 `theme.js` 给 Vuetify 的每个状态色都取令牌里的同名颜色，两边算出来一致。

## 目录

```text
src/
  api/          client.ts（请求封装）、query.ts（QueryClient 与查询键）、每个领域一个模块
  realtime/     stream.ts：全页唯一的实时事件连接
  i18n/         index.ts、format.ts、locales/zh-CN.ts、locales/en.ts
  ui/           通用组件，页面只用这里的组件和 Tailwind 工具类
  layouts/      AppShell.vue（外壳）、nav.ts（侧栏结构）、shell/（侧栏、命令面板、账号菜单）
  router/       index.ts：路由表、登录守卫、旧地址重定向
  styles/       tokens.css（设计令牌）、app.css（Tailwind 主题、动效）、base.css 与 shell.css（旧页面）、
                theme.js（从 tokens.css 解析颜色，供 Vuetify 主题使用）
  dev/          UiGallery.vue：只在开发模式出现的组件展示页
  views/        新写的页面：登录页、群聊工作台（groups/）等
```

## 设计原则

- 分区靠留白和细线，不靠卡片边框堆叠。内容区白底，侧栏浅灰。
- 品牌粉 `brand`（#E2809F）只用于标志、图表、页签指示条和开关开启状态；按钮、链接使用加深的 `primary`；标签和状态小块用中性色或状态色，不用 `primary`；其余是中性灰。
- 背景不用渐变和毛玻璃。例外只有两处：浮层遮罩的轻微模糊，走势图下方的渐变填充。
- 不写字段说明小字、页面副标题和解释性段落。只保留占位文字里的格式提示、不可撤销操作的确认和错误信息。
- 文案写给运营者：说清操作对象和后果，不写开发细节。名称用日常说法，例如模型用途 `mind` 显示为聊天。会消耗 token、不会发到 QQ 这类提醒不在各处重复，真正影响操作的限制只在最相关的位置说一次。
- 凡显示群聊的地方先显示群名，群号作为次要信息。
- 保存、开关等操作要有即时反馈；失败时显示原因，并能展开错误原文。
- 支持深色、390 px 手机宽度和键盘操作。

## 设计令牌

颜色、字号、间距、圆角、阴影、层级、动效时长和曲线只在 `styles/tokens.css` 定义，`:root[data-theme='dark']` 是深色取值。`styles/app.css` 用 `@theme` 把它们映射成工具类：

| 类别 | 工具类示例 |
|---|---|
| 背景 | `bg-page`、`bg-sidebar`、`bg-surface`、`bg-surface-raised`、`bg-fill`、`bg-hover`、`bg-selected` |
| 文字 | `text-ink`、`text-ink-2`、`text-muted`、`text-subtle`、`text-primary` |
| 线 | `border-line`、`border-line-strong` |
| 状态 | `text-success` 与 `bg-success-bg`，`warning`、`error`、`info` 同理 |
| 字号 | `text-xs` 12、`text-sm` 13、`text-base` 14、`text-lg` 16、`text-xl` 20、`text-2xl` 24 px |
| 圆角 | `rounded-sm` 6（控件）、`rounded-md` 8（小块）、`rounded-lg` 12（大块）、`rounded-xl` 16 |
| 阴影 | `shadow-card`、`shadow-hover`、`shadow-float`（浮层）、`shadow-dialog` |
| 曲线 | `ease-out`、`ease-in-out`、`ease-spring` |

间距以 4 px 为一档（`p-3` = 12 px），不随根字号变化。`dark:` 变体跟随 `data-theme`，不直接读系统设置。辅助工具类：`focus-ring`（键盘焦点描边）、`scrollbar-thin`、`tabular`（等宽数字）、`link-plain`（做成按钮或导航项的链接去掉下划线）。

不要在组件里写颜色值或像素字号；需要新颜色时先在 `tokens.css` 的浅色和深色两段各加一个令牌，再在 `app.css` 加映射。旧页面的 Vuetify 主题由 `styles/theme.js` 在构建时解析 `tokens.css` 得到，不另写颜色值。

## 动效

- 只做淡入、小位移、展开收起和列表重排，曲线用 `ease-out`，时长用 `--dur-1` 到 `--dur-4`（120、180、240、360 ms）。
- Reka UI 的浮层在 `data-state` 变为 closed 后等动画结束才卸载，所以进出动画写成 CSS 即可：浮层加 `ui-pop`（从所在方向展开），对话框加 `ui-overlay` 与 `ui-dialog`，侧边面板加 `ui-sheet`，Toast 加 `ui-toast`。
- 小块文字的出现和消失用 `<Transition name="ui-rise">`；列表项进场用 `animate-rise` 或 `animate-fade`。
- 系统开启减少动态效果时，`app.css` 把所有动画和过渡缩短到 1 ms，只保留加载转圈。

## 组件

全部在 `src/ui/`，每个组件的 props 都有类型和注释。开发模式下打开 `/#/dev/ui` 可以看到每个组件的各种状态，并切换主题和语言。

| 分类 | 组件 | 要点 |
|---|---|---|
| 按钮 | `Button`、`IconButton` | `variant`：primary、secondary、ghost、danger、danger-ghost；`to` 渲染路由链接，`href` 渲染普通链接；`loading` 时禁用并显示转圈。`IconButton` 必须给 `label`，同时作为提示和读屏名称 |
| 表单 | `Field`、`Input`、`Textarea`、`NumberInput`、`Select`、`Combobox`、`TagInput`、`Switch`、`Checkbox`、`RadioGroup`、`SegmentedControl` | 控件放进 `Field` 后自动拿到 id、错误状态和 `aria-describedby`。`Combobox` 加 `multiple` 变成可搜索多选；`TagInput` 用中英文逗号和换行分隔；`Switch` 的 `loading` 表示正在保存 |
| 分区 | `FormSection`、`SaveBar`、`Tabs` | `FormSection` 两列网格，`Field` 加 `wide` 占满一行；`SaveBar` 在有修改时浮在底部，支持 Ctrl/⌘ S；`Tabs` 的面板写成以页签值命名的插槽，没有插槽时只切换值（路由驱动的页签） |
| 浮层 | `Dialog`、`Sheet`、`ConfirmDialog`、`Popover`、`DropdownMenu`、`Tooltip` | `Dialog` 的 `busy` 期间不能关闭；`Sheet` 可从右、左、下方滑出 |
| 反馈 | `toast`（`ui/toast.ts`）、`confirm()`（`ui/confirm.ts`）、`ErrorNote`、`EmptyState`、`Skeleton`、`Spinner` | `ErrorNote` 接受任何错误对象，显示可读原因并能展开错误原文 |
| 展示 | `Badge`、`StatusDot`、`Avatar`、`Kbd`、`CodeBlock`、`StatTile`、`Sparkline`、`Timeline` 与 `TimelineItem` | `Avatar` 没有图片时按名字生成颜色和首字；`CodeBlock` 传对象时显示缩进后的 JSON，过长自动折叠；`StatTile` 的数字变化有过渡 |
| 列表 | `VirtualList` | 行高可以不一致；加载更早内容时保持视口位置；`follow-end` 时停在底部会跟随新内容；`reach-start`、`reach-end` 事件用于分页 |

组件 class 合并的注意事项：外部传入的 class 与组件内部的同类工具类（例如都设置高度）冲突时，生效顺序由 Tailwind 生成的 CSS 决定，不由 class 书写顺序决定。需要不同尺寸时给组件加 prop（如 `Badge` 的 `size`），不要从外部覆盖。

`confirm()`、`toast` 依赖外壳里渲染的 `ConfirmHost` 和 `Toaster`，在外壳之外（如登录页）不要调用。

## 外壳与路由

`layouts/AppShell.vue` 提供侧栏、顶栏、命令面板、账号菜单、待重启横幅、Toast 和确认框，`TooltipProvider` 也在这里。侧栏结构写在 `layouts/nav.ts`：分组 → 区域 → 区域下的子页面（显示为外壳里的页签）。

新增一个侧栏区域：

1. 在 `router/index.ts` 的 `hostRoutes` 加路由，名字和路径按现有写法。
2. 在 `nav.ts` 对应分组下加区域，`label` 写词条键，图标从 `@lucide/vue` 引入。
3. 中英文词条各加一条。

针对单个群的内容不新增侧栏区域，放进群聊工作台（`views/groups/`）的页签。工作台地址是 `/groups/:scene/:tab`，页签名写在 `views/groups/route.ts` 的 `groupTabs`；链接用 `groupsTarget(scene, tab)` 生成，切群时保留当前页签，从别的页面回到群聊时回到上次的群和页签。群聊标识（如 `onebot:group:80001`）总带冒号、页签名不带，所以 `/groups/memory` 表示默认群的记忆页签。旧页面里还在用 `?scene=` 的页面（日志）把路由名放在 `nav.ts` 的 `scopedRoutes`。

文档标题由侧栏标签或路由的 `meta.titleKey` 生成。`/host/...` 是旧外壳的地址，只做重定向，不再新增；旧路由名 `host-scenes`、`host-memory`、`host-tasks`、`host-resources` 也是重定向，指向工作台对应页签，M2.11 清理旧页面时一并删除。

## 数据层

所有请求经过 `api/client.ts`：

- `http.get/post/put/patch/delete` 返回解析后的 JSON；`requestBlob` 用于下载。
- 失败时抛出 `ApiError`：`status`（没拿到响应时为 0，`code` 为 `network`）、`detail`（服务端原样的错误正文）、`message`（可读文字）。
- 401 统一跳转登录；登录状态变化后，之前发出的请求即使返回也会抛出 `SessionChangedError`，结果被丢弃。

每个领域一个模块（如 `api/host.ts`），类型写在同一文件，函数挂在一个对象上：

```ts
export const hostApi = {
  state: (signal?: AbortSignal) => http.get<HostState>('/api/host/state', undefined, signal),
}
```

页面用 TanStack Query 读取，查询键从 `api/query.ts` 的 `keys` 取：

```ts
const state = useQuery({ queryKey: keys.host.state(), queryFn: ({ signal }) => hostApi.state(signal) })
```

查询键第一项是领域，之后从概括到具体（`['scene', id, 'timeline']`），让对象失效时可以按前缀刷新下面的全部查询。默认 30 秒内视为新鲜，只对没拿到响应的请求重试一次，HTTP 错误不重试。保存用 `useMutation`，成功后让相关查询失效或直接写入缓存。

## 实时事件

`realtime/stream.ts` 在登录后建立唯一的 `/api/host/stream` 连接，退出登录时关闭；断线按 1、2、4…30 秒加抖动重连，重连后和收到 `resync` 时让全部查询失效。全局规则写在 `cacheRules`：`host.state` 让宿主状态失效，`host.changed` 让宿主类查询失效。群聊时间线不在全局规则里：现场页签打开时，自己在这个群的消息和回合事件后重新读取最新一页并合并进已读取的内容（`views/groups/live/useTimeline.ts`），不重新读取全部已加载的页；关闭后缓存丢弃，再打开从最新一页开始。

页面需要对某类事件做增量处理时：

```ts
useHostEvent('turn.step', (event) => {
  if (event.scene === scene.value) appendStep(event)
})
```

订阅随组件卸载自动取消。不要在页面里另开 WebSocket，也不要每收到一个事件就重新读取整页数据。事件类型和字段见[架构的实时事件](architecture.md#实时事件)。

## 双语

- 中文词条 `locales/zh-CN.ts` 是源，`en.ts` 用 `satisfies Messages` 约束，缺键或多键在类型检查时报错。
- 键名按 `区域.页面.条目`，通用词放 `common`，组件内置文字放 `ui`。
- 新代码不写裸中文文案；后端返回的错误正文原样显示。
- 词条里的 `@`、`{`、`}`、`|` 是 vue-i18n 的语法字符，要显示原字符时写成 `{'@'}`，否则整条词条在运行时编译失败。
- 语言保存在 localStorage，没有保存时按浏览器语言；切换时同步 `<html lang>`。英文词条按需加载。
- 数字、日期、相对时间、时长、字节用 `i18n/format.ts`，不手写拼接。

术语表（同一概念在两种语言里各只用一个词）：

| 中文 | English |
|---|---|
| 群聊 | Group |
| 角色 | Persona |
| 回合 | Turn |
| 唤醒 | Wake |
| 记忆 | Memory |
| 插件 | Plugin |
| 能力 | Capabilities |
| 对话测试 | Playground |
| 模拟发送 | Simulated sending |

## 页面骨架

```vue
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { hostApi } from '@/api/host'
import { keys } from '@/api/query'
import ErrorNote from '@/ui/ErrorNote.vue'
import Skeleton from '@/ui/Skeleton.vue'

const { t } = useI18n()
const state = useQuery({ queryKey: keys.host.state(), queryFn: ({ signal }) => hostApi.state(signal) })
</script>

<template>
  <section class="flex flex-col gap-6">
    <h1 class="text-2xl font-semibold">{{ t('example.title') }}</h1>
    <Skeleton v-if="state.isPending.value" :lines="3" />
    <ErrorNote v-else-if="state.isError.value" :error="state.error.value" :retry="state.refetch" />
    <div v-else><!-- 内容 --></div>
  </section>
</template>
```

页面内容放在外壳的 `<main>` 里，外壳已经提供内边距。读取中显示骨架屏而不是空白；错误用 `ErrorNote` 并提供重试；空列表用 `EmptyState`，有可执行的下一步时放一个按钮。

## 性能

参考值（可以调整，超出时在维护记录里写明原因）：入口 JS gzip 约 200 KB 以内，入口 CSS gzip 约 40 KB 以内；宿主状态变化 1 秒内反映到界面；5,000 条以上的列表必须用 `VirtualList`。外壳和页面都是异步分块，登录页只加载入口。

## 截图核对

界面改动要截图核对宽屏、390 px 手机宽度、深色，双语完成的页面再看英文：

1. 在仓库根目录启动演示实例：`uv run --no-sync python website/scripts/demo_instance.py <临时目录> --panel-port 18088`，账号 `demo`，密码 `demo-password`。演示实例是模拟发送，模型地址是不可达的占位地址。
2. 用 Playwright 无头浏览器登录后截图。主题和语言可以在打开页面前写入 localStorage 的 `lenbot.theme`、`lenbot.locale`；不写语言时按浏览器语言，Playwright 默认是英文。
3. 组件改动在 `npm run dev` 下打开 `/#/dev/ui` 截图。`npm run dev` 的代理不改 Origin，后端会拒绝写请求和 WebSocket，看真实效果用演示实例。

## 其他约定

- 插件参数表单由插件清单生成（目前在旧页面的 `host/components/SchemaForm.vue`），不为单个插件写专用表单。
- 首页的待处理事项在 `host/attention.js` 汇总，顶栏的计数和首页列表共用这一份数据。
