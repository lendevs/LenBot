# 记忆插件

群设置的 `memory_plugin` 写成一个已在这个群启用的插件名后，这个群的自动召回和 `memory` 工具由这个插件提供；`recap_plugin` 指向插件时，压缩回想由它写。原生记忆的文件原样保留，改回原生实现时继续使用。完整示例见仓库中的 [`examples/plugins/notebook`](https://github.com/lendevs/LenBot/tree/master/examples/plugins/notebook)。

每个插件最多各有一个 `@recall`、`@memory_tool` 和 `@compact`。`@memory_tool` 只能在同进程模式下运行。

## 自动召回

```python
from len_bot.plugin import Plugin, RecallBlock, RecallRequest, recall


class Notes(Plugin):
    @recall()
    async def remember(self, request: RecallRequest) -> list[RecallBlock]:
        hits = await self.search(request.scene, request.messages, limit=5)
        return [RecallBlock(hit.title, hit.text) for hit in hits]
```

每轮第一次请求模型之前调用一次，限时 10 秒。

| `RecallRequest` 字段 | 内容 |
|---|---|
| `scene`、`persona`、`turn_id` | 群、当前角色 ID、本轮 ID |
| `observed_at` | 本轮开始时间，Unix 秒 |
| `messages` | 最近 8 条 Bot 已读或已送达的消息，从早到晚 |
| `recap` | 当前的压缩回想 |
| `tasks` | 未完成的工作，每项一行 |
| `budget_chars` | 字数预算 |

宿主按返回顺序保留各块，超出 `budget_chars` 的部分截掉。超时、出错或返回值不对时，错误记到插件上，这一轮不带召回继续。

## 记忆工具

`@memory_tool("说明")` 提供这个群的 `memory` 工具，参数写法与 `@tool` 相同。聊天模型、其他插件的 `ctx.memory()` 和后台任务在这个群调用 `memory` 时都交给它。没有 `@memory_tool` 时这个群没有 `memory` 工具。

需要导入原生记忆时，用 `await self.ctx.native_memory(scene, arguments)` 只读访问，`action` 可以是 `browse`、`read`、`search`、`history`。

插件用 `messages_between` 读原消息做整理时，处理完一段调用 `await self.ctx.report_memory_progress(scene, message.id)`。数据清理删除过期原话时，只保留插件还没处理的部分。

## 压缩回想

```python
from len_bot.plugin import CompactRequest, Plugin, compact


class Notes(Plugin):
    @compact()
    async def fold(self, request: CompactRequest) -> str:
        return await self.ctx.generate(request.scene, "把下面的对话整理成回想：\n" + request.source)
```

`request.source` 是当前回想加上最早的若干完整对话段，返回的文字替换它们，长度不能超过 `request.budget_tokens`（按 UTF-8 字节数除以 3 估算）。限时 120 秒；失败时当前回合结束，已有回想和历史保持原样。
