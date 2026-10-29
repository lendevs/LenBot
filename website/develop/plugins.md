# 写插件

LenBot 插件是一个包含清单文件 `plugin.toml` 与入口模块 `__init__.py` 的标准 Python 包，`__init__.py` 中恰好定义一个继承自 `Plugin` 的子类。插件仅从公开模块 `len_bot.plugin`（及配套辅助模块 `len_bot.plugin_testing`、`len_bot.image_assets`、`len_bot.text_cards`）导入接口，不依赖 `len_bot.next` 内部实现。

本页通过一个按群独立计数的示例插件展示从编写、配置表单、数据迁移到自动化测试与发布的完整流程。你可以直接在 GitHub 上使用[官方插件模板仓库](https://github.com/lendevs/lenbot-plugin-template)创建新项目，模板已内置该示例插件及完整的 CI 与发版工作流。完整的 v1 接口契约见仓库中的[插件接口 v1](https://github.com/lendevs/LenBot/blob/master/developer/plugins-v1.md)。

```text
counter/
  plugin.toml
  __init__.py
```

## 1. 编写插件清单（`plugin.toml`）

```toml
name = "counter"
version = "1.0.0"
interface = 1
permissions = ["send"]
requires_lenbot = ">=0.2,<1"
requires_python = ">=3.13"
platforms = ["linux", "darwin", "win32"]
reload = "plugin"
authors = ["插件维护者"]
license = "GPL-3.0-only"
description = "每群独立计数"

[config.label]
type = "string"
label = "显示名称"
description = "回复计数时使用的前缀名称"
default = "本群计数"

[config.step]
type = "integer"
label = "单次步长"
description = "发送 计数加一 时增加的数值"
minimum = 1
default = 1
```

核心字段说明：

- `name`：插件唯一标识，安装后的目录名必须与 `name` 一致。
- `interface`：插件接口代次，当前固定为 `1`，同一代次内保持向后兼容。
- `permissions`：按最小权限原则声明插件需要调用的宿主能力（如 `send`、`events`、`history`、`memory`、`generate`、`delegate`、`network`、`schedule`）；只使用自身命令、工具和键值存储时可填 `[]`。
- `requires_lenbot` 与 `requires_python`：遵循 PEP 440 的显式版本范围（例如 `>=0.2,<1` 与 `>=3.13`）。
- `reload`：填 `"plugin"` 支持在线热重载；填 `"host"` 表示更新版本必须重启宿主进程。
- 可选字段：`isolation`（`"inline"` 或 `"process"`）、`dependencies`（第三方 PyPI 依赖列表）、`data_version`（持久化数据格式版本号，默认 `1`）、`repository`、`homepage` 以及 `[model] instructions`（模型工具共享使用指南路径）。

## 2. 注册处理入口（`__init__.py`）

```python
from len_bot.plugin import Invocation, Plugin, command, fullmatch


class Counter(Plugin):
    @command('计数', '查看本群当前计数')
    async def count(self, ctx: Invocation, args: str) -> None:
        current = await ctx.get_kv(ctx.scene, 0)
        await ctx.reply(f"{ctx.config['label']}：{current}")

    @fullmatch('计数加一', '按配置步长增加本群计数')
    async def increment(self, ctx: Invocation) -> None:
        value = await ctx.get_kv(ctx.scene, 0) + ctx.config['step']
        await ctx.set_kv(ctx.scene, value)
        await ctx.reply(f"{ctx.config['label']}：{value}")
```

`len_bot.plugin` 提供九种方法装饰器（每个异步方法绑定一个装饰器）：

| 装饰器 | 触发时机与职责 |
|---|---|
| `@command(name, description, allow_mentions=False)` | 匹配 `/命令 参数`，不经过聊天模型直接执行 |
| `@fullmatch(text, description)` | 消息首尾去空白后与指定文本完全相等时触发 |
| `@regex(pattern, description, priority=0)` | 整条纯文本消息完整匹配正则表达式时触发，按 `priority` 降序排列 |
| `@on_notice(type)` | 处理平台通知事件（如群成员增减、消息撤回） |
| `@tool(name, description, summary=..., needs_source=False)` | 注册为供聊天模型在回合中按需发现和调用的工具 |
| `@background(every="5m")` | 上一轮执行完毕后按间隔循环运行的后台协程（最短间隔 10 秒） |
| `@recall()` | 当某群将 `memory_plugin` 设为本插件时，在每轮开始前提供自动记忆召回 |
| `@memory_tool(description)` | 当某群将 `memory_plugin` 设为本插件时，提供该群的 `memory` 工具实现 |
| `@compact()` | 当某群将 `recap_plugin` 设为本插件时，负责将旧对话压缩为新回想 |

记忆与回想三类扩展入口的请求结构、字符预算与完整实现范例见仓库中的 [`examples/plugins/notebook`](https://github.com/lendevs/LenBot/tree/master/examples/plugins/notebook) 与[插件接口 v1](https://github.com/lendevs/LenBot/blob/master/developer/plugins-v1.md#自动召回)。

## 3. 配置表单、生命周期与日志

- **配置表单**：在 `plugin.toml` 中通过 `[config.<字段名>]` 声明参数，面板据此自动渲染双列卡片表单，校验后的结果由 `ctx.config` 读取。支持 `string`（可设 `multiline = true`）、`secret`、`integer`、`number`、`boolean`、`string_list`、`scene`、`scene_list`、`path`、`url` 和 `object_list`（单层子字段结构列表），并支持通过 `group` 分组、`options` 生成分段控件或下拉框。
- **启动与停止**：初始化资源重写 `async def start(self)`（限时 60 秒），释放资源重写 `async def stop(self)`（限时 30 秒）。联网预热或长连接监听请通过 `self.ctx.start_task(name, coroutine)` 放入受宿主托管的后台任务，避免阻塞 `start()`。
- **结构化日志**：使用标准 `self.ctx.log` 记录日志，输出自动进入宿主 `logs/lenbot.jsonl` 并附带插件名、场景、回合与工具调用编号，可在面板**系统 → 日志**中按插件筛选。

## 4. 数据存储与版本迁移

每个插件拥有隔离的数据目录 `ctx.data_dir` 及内置 JSON 键值库（`ctx.get_kv`、`set_kv`、`delete_kv`，按群隔离的数据请将 `ctx.scene` 拼入键名）。

当新版本插件修改了磁盘文件或键值结构时，递增 `plugin.toml` 中的 `data_version` 并实现 `migrate_data(self, from_version: int)`：

```python
class Notes(Plugin):
    async def migrate_data(self, from_version: int) -> None:
        if from_version < 2:
            legacy = self.ctx.data_dir / 'notes.txt'
            if legacy.exists():
                await self.ctx.set_kv('notes', legacy.read_text(encoding='utf-8').splitlines())
                legacy.unlink()
```

宿主在 `start()` 前检测到 `data_version` 升高时，会先将整个数据目录备份至 `plugins/.data/.backups/`，再调用 `migrate_data`；迁移成功才更新版本标记，若抛出异常则自动还原备份并将插件回退或标为失败。

## 5. 本地测试与发布

使用 `len_bot.plugin_testing.PluginTest` 可在临时隔离目录中直接测试完整生命周期、命令匹配、工具 Schema 校验、记忆钩子与数据迁移，无需启动完整 LenBot 实例：

```python
from pathlib import Path
import pytest
from len_bot.plugin_testing import PluginTest


@pytest.mark.asyncio
async def test_increment():
    async with PluginTest(Path(__file__).parents[1], config={'step': 2}) as bot:
        assert await bot.message('计数加一')
        assert bot.deliveries[-1].text == '本群计数：2'
```

传入 `data=Path(...)` 与 `data_version=1` 可直接验证升级迁移逻辑；调用 `bot.preview_tools()` 可检查暴露给聊天模型的工具摘要、参数 JSON Schema 与共享指南。

基于[插件模板](https://github.com/lendevs/lenbot-plugin-template)创建的仓库可直接复用 LenBot 提供的两个 GitHub Actions 工作流：

- `lendevs/LenBot/.github/workflows/plugin-ci.yml@master`：自动针对宿主最新 `master`（或通过 `host_ref` 指定的版本，以及可选的 `apt_packages`）运行插件 `pytest` 与打包校验。
- `lendevs/LenBot/.github/workflows/plugin-release.yml@master`：推送 `v*` 标签时校验标签与 `plugin.toml` 版本一致，提取 `CHANGELOG.md` 说明并构建可直接导入面板的发行 ZIP 附件。

更多关于模型工具分组设计、`needs_source=True` 真实消息溯源、进程隔离边界与许可证兼容要求（推荐 GPL-3.0）的完整规范，请阅读[插件接口 v1](https://github.com/lendevs/LenBot/blob/master/developer/plugins-v1.md)。
