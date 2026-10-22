# 联网与工具

模型在回合中可以调用工具查询资料。本页说明搜索和读网页的服务选择、MCP 服务，以及其他内置工具。

## 搜索网页

在**能力 → 网页**中选择搜索服务，首次配置时也可以选择。

| 搜索服务 | 费用 | 连接 |
|---|---|---|
| Yahoo | 免费 | 不需要 Key |
| Bing RSS | 免费 | 不需要 Key |
| DeepSeek | 按次收费 | 可以复用 DeepSeek 聊天连接，也可以单独填写 |
| Tavily | 按次收费 | Tavily 的 Key |
| Brave Search | 按次收费 | Brave 的 Key |
| 博查 | 按次收费 | 博查的 Key |

可以设置每次最多返回几条结果（默认 5，最多 20）和超时时间。

## 读网页

| 读取方式 | 费用 | 说明 |
|---|---|---|
| 本机直接读取 | 免费 | 默认。由 LenBot 抓取网页并提取正文 |
| DeepSeek | 按次收费 | 复用 DeepSeek 搜索或聊天的连接 |
| Tavily | 按次收费 | 与 Tavily 搜索共用一个 Key |
| Jina Reader | 按用量收费 | Jina 的 Key |

搜索和读取选择同一家服务时共用一个连接，选择不同服务时分别填写。连接在**模型 → 服务商**中管理。DeepSeek 搜索和读取的价格见[官方说明](https://api-docs.deepseek.com/zh-cn/guides/search/)。

对应的配置：

```json
"web_search": { "provider": "tavily", "connection": "search", "max_results": 5, "timeout_seconds": 15 },
"web_read": { "provider": "local", "timeout_seconds": 20 }
```

`web_search` 或 `web_read` 设为 `null` 时关闭对应工具。

## 其他内置工具

| 工具 | 作用 |
|---|---|
| `recall_chat` | 按关键词、发言人和时间查询本群历史消息，查看前后文 |
| `memory` | 搜索、读取和写入本群记忆，见[记忆与学习](./memory) |
| `persona_knowledge` | 检索角色包中的资料 |
| `look` | 查看消息中的图片 |
| `open_forward` | 读取合并转发的聊天记录（QQ） |
| `member_info` | 查询群成员名单和群友资料（QQ 群） |
| `transcribe` | 转写语音消息，需要配置语音转写 |
| `schedule` | 设置提醒，可以提醒群友，也可以提醒 Bot 自己之后跟进 |
| `delegate`、`task` | 委托和管理后台任务，见[后台任务](./tasks) |

角色的工具许可决定可以使用哪些工具，见[写角色包](../develop/personas#persona-yaml)。不常用的工具不常驻在模型的工具表中，模型需要时先用 `tool_search` 找出。

## MCP 服务

在**能力 → MCP 服务**中添加 MCP 服务，模型可以调用其中的工具。支持两种连接方式：

- **stdio**：LenBot 启动一个本机命令，填写命令、参数、工作目录和环境变量。
- **HTTP**：填写服务地址，凭据写在请求头中。

每个 MCP 服务需要选择在哪些群启用。可以设置超时时间（默认 30 秒）和单次响应的大小上限（默认 1 MiB）。

## 代理软件的 fake-ip 模式

Clash、Surge 等代理软件开启 fake-ip 后，所有域名都解析为 `198.18.x.x` 这类保留地址。LenBot 读取网页和获取图片时会拒绝保留地址，后台任务访问外网时也一样，报错中出现 `私有或保留地址`。

解决方法：在**能力 → 网页**的**代理的假 IP 网段**中填写代理实际使用的网段。对应的配置：

```json
"network": {
  "fake_ip_networks": ["198.18.0.0/15"],
  "public_dns_url": "https://dns.google/resolve"
}
```

按域名连接时，如果解析结果落在该网段内，LenBot 通过 `public_dns_url` 查询真实的 A／AAAA 记录，确认是公网地址后直接连接。

- `public_dns_url` 必须是 DNS JSON 接口，接受 `name` 和 `type` 参数，返回 `Status` 和 `Answer`。
- 查询失败，或真实地址是内网地址时，请求直接报错。
- 直接写成保留 IP 的地址仍然会被拒绝。
- 网段不能覆盖 `10.0.0.0/8`、`192.168.0.0/16` 这类真实局域网，也不能是公网网段。
