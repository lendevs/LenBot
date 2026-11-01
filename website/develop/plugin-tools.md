# 模型工具

`@tool` 把插件的能力交给聊天模型，在一轮聊天中按需调用。模型先在简短的目录里发现工具，再加载完整定义；角色要同时允许 `tool_search` 和这个工具名。

```python
from typing import Annotated
from pydantic import Field
from len_bot.plugin import Invocation, Plugin, tool


class Example(Plugin):
    @tool("recent_count", "统计当前群指定时段的消息数量。", summary="查询本群最近几小时的消息数")
    async def count(self, ctx: Invocation,
                    hours: Annotated[int, Field(ge=1, le=72, description="向前回溯的小时数", examples=[12])] = 24) -> dict:
        before = ctx.now()
        after = before - hours * 3600
        count = 0
        while True:
            page = ctx.messages_between(after, before, offset=count, limit=500)
            count += len(page)
            if len(page) < 500:
                return {"hours": hours, "count": count}
```

## 说明分三层

- `summary`：发现目录和搜索结果里的简介。省略时用完整说明。
- `description`：实际调用时的完整说明。
- 参数的类型、默认值和 `Annotated[..., Field(...)]`：生成参数 schema，`Field` 的说明、示例、枚举和范围都会交给模型。

函数的 docstring 和 README 不会进入提示词。工具名只能用字母、数字、下划线和连字符，最长 64。当前群由宿主确定，不要让模型填写群号。

跨工具的流程（真实 ID 怎么传、怎么分页、结果的含义）写在共享指南中：

```toml
[model]
instructions = "prompts/tools.md"
```

当前角色发现了这个插件的工具后，指南进入系统提示；同一插件的多个工具只加载一份。

## 返回值

工具可以返回 `str` 或 JSON 值（dict、list、数字、布尔、None），宿主统一编码。查询类工具返回数据；发送类工具返回 `Sent` 的字段；在后台生成并自行发送的工具返回 `{"status": "started", "delivery": "plugin"}` 这类结果，并在说明里写明完成后由插件发送。

## 按能力组织工具

不要把每个外部接口都做成一个工具。列表、搜索和详情属于同一种查询能力时，用带 `action` 的请求区分：

```python
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


class Query(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

class Search(Query):
    action: Literal["search"]
    query: str = Field(description="关键词")

class Read(Query):
    action: Literal["read"]
    item_id: str = Field(description="来源列表返回的真实 ID")

Request = Annotated[Search | Read, Field(discriminator="action")]

@tool("content_query", "搜索或读取内容。", summary="查询内容")
async def query(self, ctx: Invocation, request: Annotated[Request, Field(description="搜索或详情请求")]) -> dict:
    if request.action == "search":
        return await self.search_source(request.query)
    return await self.read_source(request.item_id)
```

查询与发送分开，账号写入也单独一个工具。

## 真实请求来源

委派工作和账号操作类的工具写 `needs_source=True`。宿主为它增加一个必填参数 `source_message_id`，模型从本轮收到的消息中选出实际提出请求的那一条，宿主读取这条消息放进 `ctx.message`。函数参数里不要声明 `source_message_id`。

```python
@tool("owner_action", "按主人真实请求执行操作。", summary="主人操作", needs_source=True)
async def action(self, ctx: Invocation) -> dict:
    ctx.require_owner()
    return {"requester": ctx.message.sender.uid}
```

来源消息必须是当前群本轮收到的、没有撤回的、不是 Bot 自己或其他已知 Bot 发的、发送者不在黑名单中的消息。普通查询不需要来源。

## 按配置停用工具

```python
def unavailable_tools(self, scene: str) -> dict[str, str]:
    if not self.ctx.config["account_read_enabled"]:
        return {"account_read": "账号读取未开启"}
    return {}
```

返回的工具从发现目录和调用中去掉，面板预览里显示原因。这个方法只做同步的配置判断，请求人的权限在工具执行时检查。

面板角色详情的**工具与技能**页签和 `PluginTest.preview_tools()` 显示实际交给模型的简介、说明、schema 和共享指南。
