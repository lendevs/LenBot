# 模型协议与用途绑定

服务商只保存协议、接口地址、密钥和可选的网络代理。用途绑定保存模型、窗口、输出额度、超时和生成参数。聊天、视觉、记忆整理、学习、插件生成和任务都通过 `models.providers` 与 `models.roles` 解析，不各自维护密钥。

## 支持范围

| `api` | 地址示例 | 聊天与后台用途 | 续接方式 |
|---|---|---|---|
| `openai-chat` | 兼容服务的 API 根地址，一般以 `/v1` 结尾 | mind、vision、memory、learner、worker | 保留原生 assistant 字段和工具 ID |
| `openai-responses` | `https://api.openai.com/v1` | 同上 | `store=false`，携带 output 和加密 reasoning |
| `anthropic` | `https://api.anthropic.com/v1` | 同上 | 保留 Messages 内容块、thinking 和 signature |
| `gemini` | `https://generativelanguage.googleapis.com/v1beta` | 同上 | Gemini API GenerateContent，保留完整 model parts 与 thoughtSignature |
| `openai-audio` | 兼容服务的 API 根地址 | asr | audio/transcriptions |
| `deepseek-search` | `https://api.deepseek.com/v1` | 网页搜索 | 独立 Search JSON 接口 |
| `openai-embeddings` | 兼容服务的 API 根地址 | 本地记忆、场景学习的 embedding | embeddings |


暂不接入以下功能。

- Vertex
- Azure 专用鉴权
- 订阅 OAuth
- 服务商内置的搜索或图像生成

OpenAI 兼容服务也可以提供 ASR 和向量接口，按服务商文档配置。ASR 和向量使用各自的专用协议。

Gemini 的模型名填写短名称，带 `models/` 前缀的名称也能解析。宿主发送的图片使用内联 data URL。其他三种协议可以使用图片 URL 或内联图片，部分服务商限制 URL。

## 添加与测试

在面板的服务商页可以读取模型列表。读取失败时显示服务商返回的原始错误，仍然可以直接手动填写模型。列表中的窗口和输出额度只使用服务商明确返回的字段，其余的按服务商文档填写。用途页只显示支持该用途的协议。

连接测试使用尚未保存的草稿。旧密钥留空时由后端读取。

已有服务商可以改名。保存请求通过 `previous_alias` 指明原名称，一次保存更新用途、本地记忆、场景学习和搜索连接的引用；这个字段不写入根配置。只改名或补上地址末尾的斜杠可以保留旧密钥，修改协议、地址或代理需要重新填写密钥。模型列表显示名称和完整 ID，选择时写入 ID。

- 文本测试调用一次模型。
- 工具测试调用两次，确认工具请求和结果能够续接。
- 向量测试调用一次 embeddings 接口，验证返回的向量与维数，不写入业务索引。

测试发送一条文本或完成一次工具续接，结果附服务商报告的用量；测试用量不计入聊天预算。

在**模型 → 向量模型**中分别配置 `memory.local.embedding` 和 `scenes.*.learning.embedding`。两者只能绑定支持 embeddings 的协议，维数留空时使用服务商返回的维数。更换地址、模型或维数后，先重启应用保存的配置，再在记忆或学习页面点击**重建索引**。`pending-restart` 接口返回已有索引的维护项目。兼容性依据地址、模型和维数判断。

记忆查询遇到索引绑定不匹配、缺少待建向量或向量 HTTP 查询失败时，记录错误后使用现有全文索引。自动召回的全文分支只使用消息正文，向量分支继续使用带说话者的上下文。正常的混合检索也会合并自动全文召回结果。写入和离线重建要求选定模型返回合法向量。`memory/state` 的 `index` 字段返回已有绑定、运行配置、当前检索方式和重建状态。

### 生成参数

- `temperature: null` 表示不发送温度。
- `reasoning_effort` 按协议映射到 reasoning effort、adaptive thinking 的 effort 或 Gemini 的 thinkingLevel，必须填写该模型接受的值。
- `thinking_budget_tokens` 用于 Anthropic 的额度思考或 Gemini 的 thinkingBudget，与思考强度二选一。Anthropic 的思考模式下，温度必须留空，额度至少为 1024，并且小于输出额度。

兼容聊天接口可以明确把 `output_token_field` 选为 `max_completion_tokens` 或 `max_tokens`。原生协议必须使用 `history_policy: native`。`omit-reasoning` 只用于已经确认会自行保持签名续接的兼容路由。

### 代理

`proxy` 是服务商级别的 HTTP(S) 代理地址，留空时直接连接，不读取环境变量中的代理。同一服务商的所有请求共用这个代理，包括聊天、模型列表、测试、后台任务、ASR 和向量请求。代理地址中不包含用户名和密码。API 密钥只在宿主中使用，任务容器只会收到本次任务的令牌。

## 会话与工作代理

场景以统一的格式保存可读文本和工具调用，同时保留原生响应和绑定来源。

聊天模型、服务商地址与协议可以在面板中保存，重启后生效。切换到原生协议时，编辑器把兼容聊天专属的续接方式与输出字段恢复为原生默认值。

- 协议、地址和模型都相同时，续接原样使用签名数据。
- 更换绑定后，已完成的异源工具组会转为历史资料，旧的签名不会发给新模型。
- 未完成的异源工具组拒绝续接，需要先处理旧的轮次，或者在面板中开始新的上下文。
- 旧版兼容聊天中没有来源的历史，仍然按原有的兼容接口发送。服务商不接受旧字段时，按实际的错误处理，或者开始新的上下文。

工作代理为 Pi 配置相应的原生协议，把流式字节原样转发，并观察完成事件、工具参数和真实用量。生成参数、超时和额度由同一个用途绑定控制。出错或被截断的响应，以及没有完整读取的响应，都不能记为成功。宿主的聊天调用目前仍然是非流式的，思考内容不会进入群消息。

新增工作桥接路由后，现有的任务镜像需要从当前源码重新构建。

协议依据：[Responses 状态与加密续接](https://developers.openai.com/api/docs/guides/migrate-to-responses)，[Messages](https://platform.claude.com/docs/en/api/messages/create)，[Gemini GenerateContent](https://ai.google.dev/api/generate-content)，[Gemini 签名](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures)。

## 网页搜索和读取服务

`web_search.provider` 可选 `yahoo`、`bing_rss`、`deepseek`、`tavily`、`brave`、`bocha`；`web_read.provider` 可选 `local`（默认，本机抓取）、`deepseek`、`tavily`、`jina`。付费服务用 `connection` 引用 `models.providers` 中的连接，复用地址、Key 和代理；免费服务不设置 `connection`。可用的连接协议：

| 服务 | 连接协议 | 请求 |
|---|---|---|
| DeepSeek 搜索 | `openai-chat`、`openai-responses`、`deepseek-search` | `POST tools/search` |
| DeepSeek 读取 | 同上 | `POST tools/fetch`，`{"url"}`，返回 `title`、`content`（Markdown） |
| Tavily 搜索 | `tavily` | `POST search`，`{"query", "max_results"}` |
| Tavily 读取 | `tavily` | `POST extract`，`{"urls": [url], "format": "markdown"}` |
| Brave Search | `brave-search` | `GET web/search?q=&count=`，Key 放在 `X-Subscription-Token` |
| 博查 | `bocha` | `POST web-search`，`{"query", "count", "summary": true}` |
| Jina Reader | `jina-reader` | `GET <地址>/<网页地址>`，`Accept: application/json` |

除 Brave 外都用 `Authorization: Bearer`。读取服务返回的正文按 Markdown 存为场景网页文档，`web_read` 同样用 `document` 和 `offset` 续读。

```json
{"web_search": {"provider": "deepseek", "connection": "primary", "timeout_seconds": 15, "max_results": 5}}
```

连接地址以 `/v1` 结尾时请求其下的 `tools/search`，其他地址请求其下的 `v1/tools/search`；支持网关前缀，始终请求所选地址。搜索词最多 128 字符，接口请求携带 `need_content: true`。结果保留标题、URL、短摘要、长摘要、日期和正文开头；开启网页读取时完整正文存为场景网页文档，返回 `document` 和 `next_offset` 供 `web_read` 续读。搜索为空时返回空列表，服务报错原样交给工具调用方。

已有连接可即时切换搜索和读取设置；新增或修改服务商连接沿用模型连接的重启流程，重启前保持原设置。`connection` 默认为空，已有配置不用迁移。

协议依据：[DeepSeek Search 与 Fetch](https://api-docs.deepseek.com/zh-cn/guides/search/)，[Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search)，[Tavily Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract)，[Brave Web Search](https://api-dashboard.search.brave.com/api-reference/web/search/get)，[博查开放平台](https://open.bochaai.com/)，[Jina Reader](https://jina.ai/reader/)。Tavily、Brave、博查、Jina 没有用真实 Key 调用过。
