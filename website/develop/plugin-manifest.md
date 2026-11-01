# 清单与权限

`plugin.toml` 描述插件的身份、兼容范围、需要的宿主能力和配置表单。宿主在安装、应用和启动时读取它，未知字段和格式错误都会让清单无效。

## 必填字段

| 字段 | 内容 |
|---|---|
| `name` | 插件名，等于安装后的目录名；仓库根目录或 ZIP 根目录不要求使用这个名字 |
| `version` | 插件版本，按 Python packaging 的规范解析，推荐 `X.Y.Z` |
| `interface` | 插件接口代次，目前为 `1` |
| `requires_lenbot`、`requires_python` | 明确的版本范围，例如 `">=0.2,<1"`、`">=3.13"`，分别与实际的宿主和解释器版本比较 |
| `platforms` | 支持的操作系统，用 `sys.platform` 的名称：`linux`、`darwin`、`win32` |
| `reload` | `plugin` 表示可以单独换版本；`host` 表示换版本需要重启宿主 |
| `authors`、`license`、`description` | 作者列表、许可证和一句话介绍 |

部署包覆盖 Linux 和 Windows，Docker 镜像是 Linux，从源码运行时三者都可能出现。

## 可选字段

| 字段 | 内容 |
|---|---|
| `permissions` | 需要的宿主能力，见下文 |
| `dependencies` | Python 依赖，例如 `["httpx>=0.28"]`，由 uv 解析安装 |
| `isolation` | `inline`（默认，与宿主同进程）或 `process` |
| `chat_platforms` | 支持的聊天平台，例如 `["onebot"]`，不写时为全部平台，见[多平台](plugin-platforms) |
| `data_version` | 数据格式编号，默认 1，见[数据与迁移](plugin-data) |
| `repository`、`homepage` | HTTP(S) 地址 |
| `[model] instructions` | 模型工具的共享指南文件，见[模型工具](plugin-tools) |
| `[config.<字段名>]` | 配置表单，见[配置表单](plugin-config) |

依赖安装到实例的 `.runtime/plugin-packages/<宿主版本>-py313`，宿主换版本后重新安装；当前环境里已有的包作为约束，冲突时原样报告。依赖有变化时，应用新版本需要重启宿主。系统软件、外部服务和凭据的要求写在插件的 README 中。

## 权限

`permissions` 列出插件通过宿主使用的能力。声明了这个字段，未列出的能力调用时抛出 `PermissionError` 并说明缺少哪一项。

| 名称 | 能力 |
|---|---|
| `send` | 在启用的群内发送消息，包括 `ctx.reply` |
| `events` | `emit_event` 唤醒群聊 |
| `history` | `recent_messages`、`messages_between`、`wait_message` |
| `memory` | `ctx.memory` |
| `generate` | `ctx.generate` 单次模型调用 |
| `delegate` | `ctx.delegate` 以请求人的名义发起后台任务 |
| `network` | `fetch_image` 从公网获取图片 |
| `schedule` | `ctx.cron` 登记定点任务 |

插件自己的 KV、数据目录、日志、命令、消息规则、工具和通知不需要权限。只用这些时写 `permissions = []`。没有这个字段的插件保留全部能力，面板显示为**未声明权限**。

权限约束的是宿主提供的能力。同进程的插件仍然可以直接使用 Python 的文件和网络访问，面板展示的权限清单让用户在安装前知道插件会用到哪些宿主能力。

## 进程隔离

`isolation = "process"` 让插件在自己的子进程中运行。子进程崩溃时未完成的调用以失败结束，插件标记为失败，宿主和其他插件不受影响；在面板点**重载**会启动新的进程。

- `ctx` 的能力都回到宿主执行，宿主按自己记录的插件名重新检查场景和权限。
- 跨进程传递的值需要能编码为 JSON，图片按 base64 传递。插件的 `print` 写入标准错误。
- 暂不支持 `@tool`、`@memory_tool`、`ctx.cron` 和 `ctx.start_task`，含有这些入口的插件加载时说明原因。
- 子进程与宿主使用同一个 Python 环境和系统账号，进程隔离用于故障隔离。
