# 认识 LenBot

LenBot 是面向 QQ 群聊的自主决策 Agent 框架。何时开口、回复谁、先查什么、何时跟进，由 ReAct Loop 决定。

LenBot 通过已登录 QQ 的 OneBot v11 实现（例如 [SnowLuma](https://github.com/SnowLuma/SnowLuma)，推荐使用）收发消息。模型服务由部署者自行配置，只需准备一个聊天模型及其 API Key（例如 DeepSeek）。

日常对话无需输入命令前缀。群友 @ Bot、回复 Bot 或提到角色名字时，Bot 读取近期上下文并决定如何回应；开启**同时参与群内讨论**后，Bot 也会在群聊讨论活跃时自主判断是否接话。

## 核心能力

| 能力 | 说明 | 详见 |
|---|---|---|
| 群聊节奏 | 每个群保持连续对话，较早内容自动压缩为回想。支持合并连发消息、引用原消息、@ 群友、分多条发送、发送表情或贴表情回应 | [在群里聊天](../use/chatting) |
| 联网与工具 | 搜索网页、读取正文、查询历史聊天记录、查看图片、打开合并转发、登记提醒与持续关注，也可接入 MCP（Model Context Protocol，模型上下文协议）服务 | [联网与工具](../connect/web) |
| 角色包 | 名字、设定、说话方式、轮换风格、底线、样例、资料与表情独立存放在角色包中，各群可绑定不同角色并在线切换 | [角色管理](../use/personas) |
| 记忆与学习 | 记忆以本地 Markdown 文件按群保存。群内空闲时自动整理记忆，并学习群内的说法、黑话、表情和回复效果 | [记忆与学习](../use/memory) |
| 资料检索 | 上传 Markdown、纯文本或 PDF，或直接从 QQ 群文件中导入。Bot 回答时检索原文并标明文件名与小节或页码，各群资料相互隔离 | [资料检索](../use/reference) |
| 插件 | 用 Python 扩展命令、定时播报、模型工具或自定义长期记忆实现，支持同进程加载与独立进程隔离 | [插件管理](../use/plugins) |
| 后台任务 | 编写报告、处理数据或渲染页面等耗时工作委托给隔离 Docker 容器中的后台任务，完成后将文件发回群内 | [后台任务](../use/tasks) |
| 网页面板 | 首次配置、日常设置、隔离试聊、token 用量统计和逐回合诊断均在网页面板完成 | [面板一览](../use/panel) |

## 运行条件

- **运行主机**：支持 Linux、macOS 和 Windows。
- **OneBot v11 客户端**：例如 [SnowLuma](https://github.com/SnowLuma/SnowLuma)（推荐使用），已登录 Bot 的 QQ 号并启用 WebSocket。
- **聊天模型服务**：支持 OpenAI 兼容聊天（`openai-chat`）、OpenAI Responses（`openai-responses`）、Anthropic Messages（`anthropic`）和 Gemini GenerateContent（`gemini`）四种协议。

向量检索服务、语音转写服务、外部搜索服务与 Docker 均为按需选配项。

## 常用术语

**实例目录**
: 保存一个 Bot 全部运行配置与持久化数据的根目录。从源码运行时即仓库根目录。全部运行配置集中保存在 `lenbot.config.json` 一个文件中。

**场景（`scene`）**
: 一个群聊或一段私聊。场景与账号均带平台前缀：群聊写作 `onebot:group:80001`，私聊写作 `onebot:private:70001`，个人账号写作 `onebot:70001`。

**主人**
: 权限最高的操作者账号，可使用全部管理命令并在群内通过自然语言让 Bot 修改设置。首次配置时填写首个主人，后续可在面板中增补。

**模拟发送**
: Bot 照常接收平台消息并执行回合决策，但生成的回复、表情和文件只记录在面板中，不实际发往 QQ。

**回合**
: Bot 被唤醒后的一次完整决策循环，包含自动召回记忆、一至多步模型请求与工具调用，以及最终发出的发言或旁听结束。面板中每个回合渲染为一张可展开的步骤卡片。

**回想**
: 会话上下文接近压缩阈值时，由较早历史对话整理生成的摘要。回想始终保留在每轮上下文头部。

## 当前范围

- 平台接入支持 QQ（OneBot v11）。
- 配置语音转写模型后可理解群内语音消息，Bot 自身以文字、表情图片和文件形式回复。
- 内置框架提示词为中文，网页面板界面支持中文和英文。

## 按角色阅读

- **部署与日常运营**：按顺序阅读[快速开始](./quick-start)、[首次配置](./first-setup)、[对话测试](./playground)和[面板一览](../use/panel)。
- **编写角色包或插件**：阅读[写角色包](../develop/personas)或[写插件](../develop/plugins)。
- **参与核心开发**：阅读仓库中的 [CONTRIBUTING](https://github.com/lendevs/LenBot/blob/master/CONTRIBUTING.md) 与 [developer 目录](https://github.com/lendevs/LenBot/tree/master/developer)。
