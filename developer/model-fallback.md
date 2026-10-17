# 模型故障转移配置

默认每个角色只用一个服务商和模型，请求失败时这一轮直接失败。只有在 `lenbot.config.json` 中为角色写了
`fallbacks`，宿主才会在失败时换用备用模型。设计说明见 `docs/design/robustness-upgrade.md`。

## 配置

```json
{
  "models": {
    "providers": {
      "main":  {"api": "openai-chat", "base_url": "https://main.example/v1",  "api_key": "…"},
      "spare": {"api": "openai-chat", "base_url": "https://spare.example/v1", "api_key": "…"}
    },
    "roles": {
      "mind": {
        "provider": "main", "model": "model-a", "context_window_tokens": 128000,
        "fallbacks": [
          {"provider": "spare", "model": "model-b"},
          {"provider": "main",  "model": "model-c", "timeout_seconds": 30}
        ]
      }
    },
    "failover": {"failure_threshold": 3, "cooldown_seconds": 60}
  }
}
```

### `models.roles.<role>.fallbacks`

适用于 `mind`、`vision`、`memory`、`worker`、`learner`（`asr` 没有这一项）。按列表顺序尝试，主绑定优先级最高。最多 8 项。

| 字段 | 类型 | 说明 |
|---|---|---|
| `provider` | string，必填 | `models.providers` 中的名称，协议（`api`）必须与主绑定的服务商相同 |
| `model` | string，必填 | 模型名；同一服务商加同一模型不能与主绑定或前面的备用重复 |
| `temperature` | number 0–2，可选 | 不写则沿用主绑定 |
| `timeout_seconds` | number > 0，可选 | 不写则沿用主绑定 |
| `reasoning_effort` | string，可选 | 写了这一项或 `thinking_budget_tokens` 时，另一项不再沿用主绑定 |
| `thinking_budget_tokens` | integer ≥ 0，可选 | 同上 |
| `output_token_field` | `max_completion_tokens` / `max_tokens`，可选 | 仅 OpenAI 兼容聊天 |
| `retry_delays_seconds` | number 数组，可选 | 换下一个之前，对这个候选重发同一请求的等待时间 |

`context_window_tokens`、`max_output_tokens`、`history_policy` 不能单独设置，始终沿用主绑定：
它们决定场景历史的长度和续接方式，主备模型续接的是同一份历史。

为什么必须同一协议：LenBot 保存并续接原生助手消息（Anthropic 思考签名、Gemini thoughtSignature、
Responses 加密推理）。换到另一种协议后这些内容无法续接，配置校验会拒绝。

### `models.failover`

| 字段 | 默认 | 说明 |
|---|---|---|
| `failure_threshold` | 3 | 同一候选连续失败多少次后打开断路器（1–100） |
| `cooldown_seconds` | 60 | 断路器打开后跳过这个候选的时间（秒，≤ 86400） |

## 何时切换

- 切换：网络错误、超时、HTTP 401、403、408、409、425、429 和 5xx。
- 不切换、直接报错：其他 4xx（请求本身不被接受）、回复无法解析、上下文超出窗口、额度限制。

断路器按“角色 + 服务商 + 模型”分别计数。冷却结束后放行一次试探：成功则恢复，失败则重新冷却。
所有候选都在冷却时，仍按最早结束冷却的顺序尝试，不直接拒绝这一轮。

## 记录

- 每个失败的候选记一条 `model_failover` 日志事件（角色、服务商、模型、优先级、断路器状态、错误）。
- `model_call` 事件的 `provider`、`model` 仍是配置的主绑定；有备用时另记 `served_provider`、
  `served_model`、`served_priority` 和 `failed_before`。
- 面板接口 `GET /api/host/model-providers/health` 返回当前断路器状态。

## 适用范围

宿主的主脑、识图、学习、记忆整理和记忆抽取使用故障转移。试聊、后台任务容器和插件的单次生成
仍只用主绑定。
