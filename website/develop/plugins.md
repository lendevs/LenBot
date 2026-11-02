# 写插件

插件是一个 Python 包：清单 `plugin.toml` 加入口 `__init__.py`，`__init__.py` 中恰好定义一个 `Plugin` 子类。插件只从公开模块导入：`len_bot.plugin`、`len_bot.plugin_testing`、`len_bot.text_cards` 和 `len_bot.image_assets`；`len_bot.next` 下是宿主内部实现，不承诺兼容。

插件接口的代次是 1，0.2.0 起冻结：之后只做兼容的增加，已有的签名和语义不变。完整的接口契约见仓库中的[插件接口 v1](https://github.com/lendevs/LenBot/blob/master/developer/plugins-v1.md)，本组页面按开发任务介绍常用部分。

| 页面 | 内容 |
|---|---|
| [清单与权限](plugin-manifest) | `plugin.toml` 的字段、权限声明、依赖和进程隔离 |
| [接收消息](plugin-messages) | 命令、全文、正则、通知、消息结构和多轮对话 |
| [发送消息](plugin-sending) | 回复、图片、提及、发送回执，卡片与图片 |
| [模型工具](plugin-tools) | 让聊天模型调用插件的能力 |
| [配置表单](plugin-config) | 面板为插件生成的参数表单 |
| [数据与迁移](plugin-data) | KV、数据目录和数据版本 |
| [模型调用与后台任务](plugin-models) | 单次生成、委派任务、定点任务和后台循环 |
| [记忆插件](plugin-memory) | 替换某个群的自动召回、记忆工具和压缩回想 |
| [多平台](plugin-platforms) | QQ、Telegram、飞书之间的差异和 `chat_platforms` |
| [测试与发行](plugin-testing) | `PluginTest`、CI、打包和许可证 |
| [发布到插件目录](plugin-catalog) | 把插件加入社区插件目录 |

## 用 Agent 写插件

仓库提供插件开发 skill [`skills/lenbot-plugin`](https://github.com/lendevs/LenBot/tree/master/skills/lenbot-plugin)，内容包括开发流程、清单与入口规则、工具写法和 `PluginTest` 测试，并按任务指向本组页面。把这段发给你的 Agent 安装它：

```text
请把 https://github.com/lendevs/LenBot/tree/master/skills/lenbot-plugin 安装为你的技能：下载这个目录到你的技能目录，之后帮我写 LenBot 插件时按其中的步骤和规则进行。
```

## 从模板开始

在 GitHub 打开[插件模板](https://github.com/lendevs/lenbot-plugin-template)，点 **Use this template** 生成自己的仓库。模板是一个按群计数的插件，带测试、CI 和发行工作流。生成后先改 `plugin.toml` 的 `name`、`authors`、`version` 和 `license`，再把命令和工具改成自己的名字。

## 本机开发环境

插件的测试使用宿主提供的 `PluginTest`，需要一个装有 LenBot 的 Python 3.13 环境。把 LenBot 和插件仓库克隆到同一个目录下：

```sh
git clone https://github.com/lendevs/LenBot.git
git clone https://github.com/<你的账号>/<插件仓库>.git
cd <插件仓库>
uv venv --python 3.13
uv pip install ../LenBot pytest pytest-asyncio
uv run --no-project python -m pytest -q
```

插件在 `plugin.toml` 的 `dependencies` 中声明了依赖时，用 `uv pip install` 一并装进这个环境。插件仓库的 CI 按同样的步骤安装宿主的 `master` 并运行测试。

## 最小插件

```text
counter/
  plugin.toml
  __init__.py
```

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

[config.step]
type = "integer"
label = "每次增加"
description = "发送 计数加一 时增加的数值"
minimum = 1
default = 1
```

```python
from len_bot.plugin import Invocation, Plugin, command, fullmatch


class Counter(Plugin):
    @command("计数", "查看本群当前计数")
    async def count(self, ctx: Invocation, args: str) -> None:
        await ctx.reply(f"本群计数：{await ctx.get_kv(ctx.scene, 0)}")

    @fullmatch("计数加一", "按配置的步长增加本群计数")
    async def increment(self, ctx: Invocation) -> None:
        value = await ctx.get_kv(ctx.scene, 0) + ctx.config["step"]
        await ctx.set_kv(ctx.scene, value)
        await ctx.reply(f"本群计数：{value}")
```

`/计数` 和 `计数加一` 由插件直接处理，不经过聊天模型。处理结果作为背景记录进入之后的对话，聊天模型下次被唤醒时能看到。

## 在实例中运行

开发中的插件可以直接复制到实例根目录的 `plugins/<name>`，宿主启动时会发现它；在面板的插件详情中启用，再在**使用的群**页签选择群。手动放入的目录不由安装器管理，改了源码后在插件详情点**重载**。

发布后的插件由用户在**插件 → 发现插件**中填写 Git 仓库地址安装，或导入 Release 中的 ZIP，见[插件管理](../use/plugins)。

## 日志与报错

`self.ctx.log` 是标准的 `logging.Logger`，记录写进宿主的 `logs/lenbot.jsonl`，自动带上插件名、群和当前回合，可以在面板**系统 → 日志**中按插件筛选。处理器抛出的异常结束这一次调用，原始错误写入日志并显示在插件详情中，插件继续处理之后的事件。
