---
name: lenbot-plugin
description: 编写、测试和发布 LenBot 插件（Python，插件接口 1）。在创建或修改 LenBot 插件、编写 plugin.toml、命令和消息规则、模型工具、配置表单、PluginTest 测试，以及打包发行或提交到社区插件目录时使用。
---

# LenBot 插件开发

LenBot 插件是一个 Python 包：清单 `plugin.toml` 加入口 `__init__.py`，`__init__.py` 中恰好定义一个 `Plugin` 子类。插件接口的代次是 1，LenBot 0.2.0 起冻结，之后只做兼容的增加。

## 资料

动手前按任务读对应的文档。插件仓库旁边有 LenBot 克隆（`../LenBot`）时读本地文件，否则读 `https://raw.githubusercontent.com/lendevs/LenBot/master/` 加下表中的路径。

| 任务 | 文件 |
|---|---|
| 完整接口契约，有疑问时以它为准 | `developer/plugins-v1.md` |
| 清单字段、权限、依赖、进程隔离 | `website/develop/plugin-manifest.md` |
| 命令、全文、正则、通知、消息结构、多轮对话 | `website/develop/plugin-messages.md` |
| 回复、图片、提及、发送回执、卡片 | `website/develop/plugin-sending.md` |
| 让聊天模型调用插件 | `website/develop/plugin-tools.md` |
| 面板参数表单 | `website/develop/plugin-config.md` |
| KV、数据目录、数据版本 | `website/develop/plugin-data.md` |
| 单次生成、委派任务、定点任务、后台循环 | `website/develop/plugin-models.md` |
| 替换群的自动召回、记忆工具和压缩回想 | `website/develop/plugin-memory.md` |
| QQ、Telegram、飞书的差异 | `website/develop/plugin-platforms.md` |
| `PluginTest`、CI、打包、许可证 | `website/develop/plugin-testing.md` |
| 提交到社区插件目录 | `website/develop/plugin-catalog.md` |

## 工作流程

1. **确认需求**：插件由谁触发（命令、全文、正则、通知、模型工具、后台循环、定点任务），需要哪些配置项，用到哪些宿主能力，支持哪些聊天平台。需求不清楚时先问用户。
2. **建仓库**：新插件从模板开始，`gh repo create <仓库名> --template lendevs/lenbot-plugin-template --public --clone`，或在 GitHub 上打开 [lenbot-plugin-template](https://github.com/lendevs/lenbot-plugin-template) 点 **Use this template**。模板是按群计数的插件，带测试、CI、发行工作流、`catalog-entry.json` 和共享指南 `prompts/tools.md`。先改 `plugin.toml` 的 `name`、`version`、`authors`、`license`、`description`，`catalog-entry.json` 中的同名字段保持一致，再把命令和工具改成自己的名字。
3. **准备环境**：LenBot 与插件仓库克隆在同一个目录下。

   ```sh
   git clone https://github.com/lendevs/LenBot.git
   cd <插件仓库>
   uv venv --python 3.13
   uv pip install ../LenBot pytest pytest-asyncio
   uv run --no-project python -m pytest -q
   ```

   `plugin.toml` 的 `dependencies` 中声明的依赖也用 `uv pip install` 装进这个环境。
4. **编写**：按下文的规则写清单和处理器。
5. **测试**：用 `len_bot.plugin_testing.PluginTest` 覆盖每个命令、规则和工具，运行 pytest 全部通过。
6. **在实例中试用**：把插件目录复制到实例根目录的 `plugins/<name>`，在面板的插件详情中启用，在**使用的群**页签选择群；改了源码后点**重载**。工具在面板角色详情的**工具与技能**页签预览。
7. **发行**：提高 `plugin.toml` 和 `catalog-entry.json` 的 `version`，更新 `CHANGELOG.md`，推送 `v<version>` 标签，发行工作流把可导入的 ZIP 附加到 Release。收录到社区插件目录时，向 [lenbot-plugin-index](https://github.com/lendevs/lenbot-plugin-index) 提交条目，`ref` 写完整的 40 位提交号。

## 规则

### 导入与结构

- 只从公开模块导入：`len_bot.plugin`、`len_bot.plugin_testing`、`len_bot.text_cards`、`len_bot.image_assets`。`len_bot.next` 是宿主内部实现，不导入。
- 处理器都是 `async` 方法，每个方法只用一个入口装饰器。
- 不在事件循环中做阻塞的网络或文件操作。耗时的准备工作用 `self.ctx.start_task(name, coroutine)`，不放进 `start()`；`start()` 限时 60 秒，`stop()` 限时 30 秒。
- 日志用 `self.ctx.log`。处理器抛出的异常结束这一次调用并写进宿主日志，插件继续运行。

### 清单

必填字段：

```toml
name = "counter"            # 安装后的目录名：小写字母开头，小写字母、数字和下划线，最长 40 个字符
version = "1.0.0"
interface = 1
permissions = ["send"]
requires_lenbot = ">=0.2,<1"
requires_python = ">=3.13"
platforms = ["linux", "darwin", "win32"]
reload = "plugin"           # 单独更换插件版本；需要重启宿主时写 "host"
authors = ["维护者"]
license = "GPL-3.0-only"
description = "一句话说明"
```

- `permissions` 列出实际用到的宿主能力，未列出的能力调用时抛出 `PermissionError`：`send` 发送消息（含 `ctx.reply`），`events` 用 `emit_event` 唤醒聊天，`history` 读取消息记录和 `wait_message`，`memory` 调用 `ctx.memory`，`generate` 单次模型调用，`delegate` 委派后台任务，`network` 用 `fetch_image` 取公网图片，`schedule` 用 `ctx.cron` 登记定点任务。插件自己的 KV、数据目录、日志、命令、规则、工具和通知不需要权限。
- 只支持部分聊天平台时写 `chat_platforms`（`onebot`、`telegram`、`feishu`），不写为全部平台。
- Python 依赖写在 `dependencies`；系统软件、外部服务和凭据要求写在 README。
- 改变数据结构时提高 `data_version` 并实现 `migrate_data`。

### 入口

```python
from len_bot.plugin import Invocation, Plugin, PluginContext, background, command, fullmatch, on_notice, regex, tool
```

| 装饰器 | 方法参数 | 行为 |
|---|---|---|
| `@command("查询", "说明")` | `self, ctx: Invocation, args: str` | `/查询` 后面的文字作为 `args` |
| `@fullmatch("今日直播", "说明")` | `self, ctx: Invocation` | 去掉首尾空白后全文相同 |
| `@regex(r"查 (?P<name>.+)", "说明", priority=0)` | `self, ctx: Invocation, match` | 正则 fullmatch，命名组从 `match` 读取 |
| `@on_notice("group_increase")` | `self, ctx: Invocation, notice` | 进群、撤回等通知 |
| `@tool("plugin_read", "完整说明", summary="发现简介")` | `self, ctx: Invocation, ...` | 聊天模型调用的工具 |
| `@background(every="5m")` | `self, ctx: PluginContext` | 按间隔循环执行，最短 10 秒 |

- 匹配顺序是命令、全文、正则；同一条消息最多由一个处理器接管，接管后不唤醒聊天模型，处理结果作为背景进入之后的对话。
- 发送用 `await ctx.reply(text)`、`reply_image(data, description)`、`reply_parts([Text(...), Image(...), Mention(uid)])`；处理器的返回值只作记录。`self.ctx` 上的方法要明确传入场景，例如 `await self.ctx.send(scene, text)`。
- `ctx.scene` 是带平台前缀的场景（如 `onebot:group:80001`），账号同样带前缀（如 `telegram:501`）。
- KV 只按插件隔离：`await ctx.get_kv(key, default)`、`set_kv`、`delete_kv`。按群区分时把 `ctx.scene` 放进 key。
- 多轮对话用 `await ctx.wait_message(timeout_seconds=60)`，超时返回 `None`，需要 `history` 权限。
- 定点任务在 `start()` 中用 `self.ctx.cron(name, "0 8 * * *", handler, scene=scene, timezone=self.ctx.timezone(scene))` 登记，需要 `schedule` 权限。

### 模型工具

- `summary` 是发现目录中的简介，`description` 是调用时的完整说明，参数用类型注解和 `Annotated[..., Field(description=..., examples=...)]` 描述。docstring 和 README 不会交给模型。
- 返回 dict、list、数字、布尔、None 或 str；当前群由宿主确定，不让模型填写群号。
- 同一种查询能力的列表、搜索和详情合成一个工具，用 `action` 区分的严格 pydantic 联合类型；查询、发送和账号写入分开成不同工具。
- 委派工作和账号操作类工具声明 `needs_source=True`，宿主自动加上 `source_message_id` 参数并把请求人放进 `ctx.message`，函数里不声明这个参数；需要主人权限时调用 `ctx.require_owner()`。
- 按配置不可用的工具从 `unavailable_tools(self, scene)` 返回 `{工具名: 原因}`。
- 跨工具的用法写在共享指南（清单中 `[model] instructions = "prompts/tools.md"`），写明真实 ID 的传递、分页和结果含义。
- 角色要同时允许 `tool_search` 和这些工具名，在 README 中写明工具名。

### 配置表单

在清单中用 `[config.<键>]` 声明，`type` 为 `string`、`secret`、`integer`、`number`、`boolean`、`string_list`、`object_list`、`scene`、`scene_list`、`path` 或 `url`，配 `label`、`description` 和 `default`。处理器从 `ctx.config["<键>"]` 读取。字段写法见 `website/develop/plugin-config.md`。

## 测试

```python
from pathlib import Path
import pytest
from len_bot.plugin_testing import PluginTest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_increment():
    async with PluginTest(ROOT, config={"step": 2}) as bot:
        assert await bot.message("计数加一")
        assert bot.deliveries[-1].text == "本群计数：2"
        assert "2" in await bot.tool("counter_read", {})
```

- `message(text, scene=..., sender=...)` 返回是否被接管，`deliveries` 记录发送内容。
- `tool(name, arguments)` 经过真实的调用边界，返回模型实际收到的字符串；`preview_tools()` 返回交给模型的说明和参数。
- 需要来源的工具先用 `add_message(...)` 保存一条消息，再把它的 `platform_message_id` 作为 `source_message_id` 传入。
- 模型默认关闭，`models=` 传入测试模型配置时 `generate` 走真实协议；固定时钟用 `now=lambda: <Unix 秒>`。

## 许可证

LenBot 宿主采用 AGPL-3.0-only。插件与宿主运行在同一个进程中，推荐插件使用 GPL-3.0。
