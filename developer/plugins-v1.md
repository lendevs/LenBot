# 插件接口 v1

## 最小插件

一个插件目录包含 `plugin.toml` 和 `__init__.py`，`__init__.py` 中必须恰好定义一个 `Plugin` 子类。可以从[插件模板](https://github.com/lendevs/lenbot-plugin-template)开始编写。插件通过公开的 `len_bot.plugin` 接口与宿主交互。

清单中必须填写以下字段。`name` 等于安装后的目录名，仓库根目录或 ZIP 根目录不要求事先使用这个目录名。

公共接口的代次为 **1**，从 0.2.0 起冻结。之后只做兼容的增加，例如新的可选参数、新方法和新的清单可选字段，不修改已有的签名和语义。确实需要破坏兼容时，提升代次。宿主加载当前代次的插件，旧代次的插件需要升级到当前接口。

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
```

- `version` 按 Python packaging 的版本规范解析和规范化，推荐使用 X.Y.Z 格式。
- 两个 requires 字段是明确的版本范围，分别与实际的宿主版本和解释器版本比较。
- `platforms` 使用 Python 的 `sys.platform` 名称：Linux（`linux`）、macOS（`darwin`）和 Windows（`win32`）。部署包覆盖 Linux 和 Windows，Docker 镜像是 Linux，从源码运行时三者都可能出现。
- `reload` 为 `plugin` 时允许单独更换这个插件的版本，为 `host` 时需要重启宿主。
- 可选的 `repository` 和 `homepage` 是 HTTP(S) 地址。
- 可选的 `chat_platforms` 列出支持的聊天平台（`onebot`、`telegram`、`feishu`），不写时为全部平台，见[多平台](#多平台)。
- 可选的 `data_version`（正整数，默认为 1）是插件数据目录和 KV 的格式编号。改变数据的结构时，需要提高这个编号并实现 `migrate_data`，见下文的[数据版本](#数据版本)。

`dependencies = ["包名>=版本"]` 声明 Python 依赖，由 uv 解析，安装到实例的 `.runtime/plugin-packages/<宿主版本>-py313` 目录，宿主更换版本后重新安装。当前环境中已有的版本会作为约束，冲突时原样报告。对系统软件、外部服务和凭据的要求，请写在插件的 README 中。

### 权限声明

可选的 `permissions` 列出插件需要的宿主能力。声明了这个字段，插件就只能通过宿主接口使用列出的能力，其余调用抛出 `PermissionError`，并说明缺少哪一项。

```toml
permissions = ["send", "history"]
```

| 名称 | 能力 |
|---|---|
| `send` | 在启用的群内发送消息，包括 `ctx.reply` 回复自己的命令 |
| `events` | `emit_event` 唤醒群聊 |
| `history` | `recent_messages`、`messages_between` 和 `wait_message` |
| `memory` | `ctx.memory` |
| `generate` | `ctx.generate` 单次模型调用 |
| `delegate` | `ctx.delegate` 以请求人的名义发起后台任务 |
| `network` | `fetch_image` 从公网获取图片 |
| `schedule` | `ctx.cron` 登记定点任务 |
| `configure` | `ctx.update_config` 修改本插件的配置 |

插件自己的 KV、数据目录、日志、命令、消息规则、工具和通知不需要权限。名称重复或未知时清单无效。没有这个字段的旧插件保留全部能力，面板显示为**未声明权限**。新插件和官方插件应明确声明实际调用的宿主能力；模板也按此编写。权限只约束宿主提供的能力，同进程插件仍然可以直接使用 Python，需要隔离时配合下面的 `isolation`。

### 进程隔离

`isolation = "process"` 让插件运行在自己的子进程中，默认值 `inline` 与宿主同进程。

- 宿主先在子进程中导入插件、读取入口，再按同样的标记登记命令、全文和正则规则、通知、`@background` 循环、`@recall` 和 `@compact`。每次调用通过标准输入输出上的 JSON 行转发。
- 插件中的 `ctx` 能力都回到宿主执行。宿主使用自己记录的插件名，并重新检查场景和 `permissions`，子进程无法冒充其他插件。`ctx.delegate` 的请求人由宿主按触发这次调用的真实消息确定，子进程传来的账号不被采用；后台循环和调用结束后不能委派。
- 子进程崩溃或退出时，未完成的调用以失败结束，`@background` 循环随之停止，插件标记为失败并记录退出码，宿主和其他插件不受影响。协议输出中出现无法解析的行时，宿主结束这个进程，按同样方式处理。在面板中重新加载插件会启动新的进程。
- 停止时先请求插件的 `stop()`，超时或被取消时结束进程。插件的 `print` 写入标准错误，不会混入协议。
- 暂不支持 `@tool`、`@memory_tool`、`ctx.cron` 和 `ctx.start_task`；含有这些入口的插件加载时会说明原因。跨进程传递的值需要能编码为 JSON，图片按 base64 传递。
- 子进程与宿主使用同一个 Python 环境，进程隔离用于故障隔离，插件拥有与宿主相同的权限。

公开给插件作者的入口包括以下几项。`len_bot.next` 下的内部模块不承诺兼容。

- `len_bot.plugin`，包括它导出的 `ChatMessage`、`Notice`、`Sender`、`Segment` 消息类型
- 下文介绍的 `len_bot.plugin_testing`
- 辅助模块 `len_bot.image_assets` 和 `len_bot.text_cards`

## 安装与维护

### 安装来源

- **Git**。在面板中手动填写完整的 HTTPS 或 `ssh://` Git URL，可以选择标签、分支或提交。仓库根目录需要包含清单和包入口。私有仓库使用本机的 Git 凭据，URL 中不要写密码。没有指定 ref 时记录默认分支，更新时沿用这个分支。指定了 ref 时，更新会重新获取同一个 ref。
- **ZIP**。清单可以放在 ZIP 的根目录，也可以把全部内容放在唯一的顶层目录中，并在这个目录中直接包含清单。必须有 `__init__.py`。以下情况都会报错，Finder 元数据会被忽略。
  - 路径越界
  - 重复的文件
  - 符号链接
  - Python 字节码
  - 超过 4096 项
  - 上传或解压后超过 200 MiB

  ZIP 源码可以离线准备，但安装依赖可能仍然需要网络。

两种来源都只**准备候选版本**。准备时会下载和解析插件，检查身份和兼容性，并保存来源信息。当前运行的版本继续运行。之后在面板中填写候选版本的配置并保存，再点击应用。新插件初始为停用状态，应用成功后可以启用并选择群。

### 文件位置

插件统一放在实例根目录的 `plugins/` 中。

| 内容 | 位置 |
|---|---|
| 已安装的源码 | `plugins/<name>` |
| 候选版本 | `plugins/.candidates/<name>` |
| 安装记录 | `plugins/.installations/<name>.json` |
| 候选参数 | `.installations/.candidate-values/` |
| 业务数据 | `plugins.data_directory/<name>`，默认为 `plugins/.data/<name>` |

安装记录保存 Git commit 或 ZIP 的 SHA-256、已安装版本和候选版本、生效方式、是否已经选择重启应用，以及最近的错误。

生效的参数和群选择保存在根目录的 `lenbot.config.json` 中。候选参数暂存在 `.installations/.candidate-values/`，应用对应的源码时才会发布。取消候选版本时，候选参数一并删除。

`plugins.paths` 默认为 `["plugins"]`，手动复制进 `plugins/` 的插件同样会被发现，但手动放入的目录不由安装器管理。

### 应用规则

- 受管理的 Git 源码有本地修改时（包括未跟踪的文件，宿主生成的 `__pycache__` 除外），应用会停止。
- ZIP 插件换版时重新导入。同名的包更换 Git 仓库，或者在 Git 和 ZIP 之间切换来源时，需要选择**替换同名插件的安装来源**，并沿用原插件的数据身份。
- 依赖没有变化，并且 `reload=plugin` 时，停止目标插件，切换源码，然后实际重新导入并调用 start。保存普通参数或群选择时，也只重新加载目标插件。重新加载会中断这个插件尚未完成的处理，其他插件和聊天继续运行。
- 依赖声明有变化，或者 `reload=host` 时，应用操作只选定候选版本，面板将其列为待重启。明确重启时，启动器等待旧宿主退出，然后由 `maintenance.apply_plugins` 持有实例锁，核对候选配置，一次性安装合并后的依赖，切换源码，最后启动新宿主。候选版本只在明确重启时应用。失败时本次启动器结束，候选版本和原始错误保留，修正问题后再次重启应用。

直接运行 host 的实例，停机后在实例根目录执行 `python -m len_bot.next.maintenance.apply_plugins`，然后明确启动。这条命令只处理面板中已经选择应用的候选版本。

重建环境后，用 `python -m len_bot.next.maintenance.plugin_dependencies` 恢复已安装插件声明的依赖。首次安装且尚未应用的候选版本不参与恢复，已有安装的插件按已安装的源码恢复。请使用目标环境的解释器和 uv。服务和容器的说明见[部署](../deploy/current/README.md)。

### 取消、停用和卸载

- **取消候选**保留已安装的源码。首次安装且尚未应用时，取消会移除这个插件的配置入口。
- 停用会保留参数、群选择和数据。
- 卸载会删除源码、候选版本和启用配置，保留插件的业务数据和共享的依赖包。删除数据是插件停止后的单独操作。

### 回退

应用新版本时，被替换的源码会移到 `plugins/.previous/<name>`，同时保留当时的参数，面板可以**回退到上一版本**一次。新版本在加载、启动或数据迁移时失败，宿主会回到上一版本的源码和参数。如果新版本已经迁移了数据，数据也会恢复为迁移前的备份。在面板上手动回退会换回上一版的源码和参数，数据的处理见下文。

应用新版本前，按候选配置表单补齐新增的必填项，并移除已删除的字段。

### 数据版本

插件数据存放在 `ctx.data_dir` 中，KV 文件也在这里。宿主在这个目录中写入 `.lenbot-data.json`，记录数据是按哪个 `data_version` 写入的。没有记录的已有数据视为版本 1，全新的空目录直接记为清单中的当前版本。

清单中的 `data_version` 高于记录值时，宿主在调用 `start()` 之前执行以下步骤。

1. 把整个数据目录复制到 `plugins.data_directory/.backups/<name>-v<旧版本>-<时间>`。
2. 调用 `await plugin.migrate_data(from_version)`。此时插件已经加载，可以读写 `ctx.data_dir` 和 KV，但还没有调用 `start()`。
3. 迁移成功后写入新的版本号，然后启动插件。迁移抛出异常时，把数据目录恢复到迁移前的状态，将插件标记为失败，并把原始错误写入日志。

一次迁移必须能从任何受支持的旧版本升级到当前版本，按 `from_version` 依次处理。提高了 `data_version` 却没有实现 `migrate_data` 时，会直接失败。清单中的 `data_version` 低于记录值时，宿主拒绝启动插件，因为旧版本插件不读取新格式的数据。回退版本时，需要同时从 `.backups` 恢复对应的数据。

[独立插件与示例](plugin-examples.md)涵盖命令接管、生成与委派，以及外部服务的接入。发现页仍然使用[静态目录](plugin-catalog.md)，首个版本没有插件市场后端。

## 入口

```python
from len_bot.plugin import Plugin, Invocation, command, fullmatch, regex, tool, background, on_notice
```

| 装饰器 | async 方法参数 | 行为 |
|---|---|---|
| `@command("查询", "说明")` | `self, ctx: Invocation, args: str` | `/查询` 后面剩余的文字作为 args |
| `@fullmatch("今日直播", "说明")` | `self, ctx: Invocation` | 去掉首尾空白后，全文与文本相同 |
| `@regex(r"查 (?P<name>.+)", "说明", priority=0)` | `self, ctx: Invocation, match` | 使用 Python 正则的 fullmatch，命名组从 match 中读取 |
| `@on_notice("group_increase")` | `self, ctx: Invocation, notice` | 通知类型，也支持 type.sub_type，见[通知](#通知) |
| `@tool("plugin_read", "完整说明", summary="发现简介", needs_source=False)` | `self, ctx: Invocation, ...` | 根据参数类型生成 schema，返回文本或 JSON 值 |
| `@background(every="5m")` | `self, ctx: PluginContext` | 本次执行完成后再等待一个周期，最短 10 秒。它按间隔执行，与定点的 cron 不同 |
| `@recall()` | `self, request: RecallRequest` | 群设置 `memory_plugin` 指向本插件时，每轮在第一次模型请求前调用一次，返回 `RecallBlock` 列表，见[自动召回](#自动召回) |
| `@memory_tool("说明")` | `self, ctx: Invocation, ...` | 群设置 `memory_plugin` 指向本插件时，作为这个群的 `memory` 工具，参数写法与 `@tool` 相同，见[自动召回](#自动召回) |
| `@compact()` | `self, request: CompactRequest` | 群设置 `recap_plugin` 指向本插件时，由它写压缩回想，返回文字，见[压缩回想](#压缩回想) |

每个方法只使用一个入口装饰器。匹配的优先级依次为命令、全文、正则，正则之间按 priority 降序匹配。同一条消息最多由一个处理器接管，并且不唤醒聊天模型。默认匹配只针对纯文本，开头的回复段和 @Bot 自己的部分可以去掉。命令可用 `@command("转发", "说明", allow_mentions=True)` 明确接收正文中的提及；提及保留在 `ctx.message.segments`，文字参数中的提及位置替换为一个空格，插件从真实消息读取目标账号。图片、语音等其他段仍不接管。全文和正则规则继续只匹配纯文本，不把提及或媒体悄悄拼接进去。

插件先于宿主命令匹配。插件显式注册 `/角色` 等同名命令时由插件处理；否则 `/角色` 交给宿主，只有主人和全局管理员可以切换角色。需要保留宿主命令时，不要给插件注册同名命令。

部署方可以只关掉插件的某几条规则，插件其余功能继续可用：在 `plugins.disabled_rules` 里按插件名列出，命令写 `/群日报`，全文写原文，正则写模式字符串，例如 `"disabled_rules": {"group_digest": ["/群日报"]}`。被关掉的文本当普通聊天处理。写了插件没有的规则时，日志里有一条警告。

处理结果会作为背景记录到之后的对话上下文中，等下一次唤醒时供模型参考。发送消息需要调用 `await ctx.reply("文字")`，处理器的返回值只作记录。聊天模型选择调用某个 tool，属于一轮聊天的一部分；插件的 tool 内部如果调用模型，要在插件说明中写清楚。

### 自动召回

群设置的 `memory_plugin` 写成一个已在该群启用的插件名后，这个群每轮的自动召回由该插件的 `@recall` 入口提供，原生记忆不再为这个群做自动召回和后台整理，已有的原生记忆文件原样保留。在面板保存 `memory_plugin` 或 `recap_plugin` 后，这个群在当前回合结束时切换；插件卸载时，用它的群回到原生实现。每个插件最多一个 `@recall` 入口。

插件用 `@memory_tool("说明")` 提供这个群的 `memory` 工具，参数按处理函数的类型标注生成，写法与 `@tool` 相同。聊天模型、其他插件的 `ctx.memory()` 和任务执行器在这个群调用 `memory` 时都交给它，角色仍需允许 `memory`。插件没有 `@memory_tool` 时这个群没有 `memory` 工具。原生记忆的说明和群资料不再写入这个群的提示词，改为一段说明记忆由该插件提供的文字。需要导入原生记忆时，用 `await self.ctx.native_memory(scene, arguments)` 读取，参数与原生 `memory` 工具相同，只允许 browse、read、search 和 history。

```python
from len_bot.plugin import Plugin, RecallBlock, RecallRequest, recall

class Notes(Plugin):
    @recall()
    async def remember(self, request: RecallRequest) -> list[RecallBlock]:
        hits = await self.search(request.scene, request.messages, limit=5)
        return [RecallBlock(hit.title, hit.text) for hit in hits]
```

| `RecallRequest` 字段 | 内容 |
|---|---|
| `scene`、`persona`、`turn_id` | 场景、当前角色 ID、本轮 ID |
| `observed_at` | 本轮开始时间，Unix 秒 |
| `messages` | 最近 8 条 Bot 已读或已送达的消息，从早到晚排列；未送达的 Bot 发言不在其中 |
| `recap` | 当前的压缩回想，没有时为 None |
| `tasks` | 未完成的工作，每项一行 |
| `budget_chars` | 字数预算，取根配置的 `memory.recall_budget_chars`；没有配置原生记忆时为 1500 |

宿主按返回顺序保留各块，跳过空白块，累计超出 `budget_chars` 的部分截掉。保留的块以 `plugin:<插件名>` 为来源、`title` 为路径写入本轮状态和面板的召回记录，一轮内的每次模型请求使用同一份结果。召回限时 10 秒；超时、抛出异常或返回值不是 `RecallBlock` 序列时，错误记到插件上，这一轮不带召回继续。

插件用 `ctx.messages_between` 读原消息做自己的整理时，处理完一段后调用 `await self.ctx.report_memory_progress(scene, message.id)`，表示到这条消息为止都已处理。只有该群的 `memory_plugin` 可以报告，位置只前进不后退。数据清理按 `retention.message_days` 删除过期原话时，只保留插件还没处理的部分；插件从未报告时不为它保留。原生记忆的整理位置在插件接管期间不参与判断。改回原生记忆后，原生整理从改回时的最新消息开始，插件接管期间的消息不补整理。

### 压缩回想

会话快要超过压缩阈值，或管理员在面板手动压缩时，宿主选出最早的若干完整对话段，连同当前回想一起换成一份新回想。群设置的 `recap_plugin` 写成一个已在该群启用的插件名后，这份新回想由该插件的 `@compact` 入口写。每个插件最多一个 `@compact` 入口。

```python
from len_bot.plugin import CompactRequest, Plugin, compact

class Notes(Plugin):
    @compact()
    async def fold(self, request: CompactRequest) -> str:
        return await self.ctx.generate(request.scene, "把下面的对话整理成回想：\n" + request.source)
```

| `CompactRequest` 字段 | 内容 |
|---|---|
| `scene`、`persona`、`turn_id` | 场景、当前角色 ID、本次压缩所属的回合 ID |
| `source` | 当前回想和待压缩的对话段，按原生回想使用的同一份文字 |
| `budget_tokens` | 新回想的长度上限，宿主按 UTF-8 字节数除以 3 估算 |

宿主按完整的工具调用及其结果选择压缩边界。插件返回的文字去掉首尾空白后，由宿主在同一个事务里写入回想、推进压缩位置并清空已发现的工具，原生回想走同一个提交。压缩限时 120 秒；超时、抛出异常、返回空白或超过 `budget_tokens` 时，错误记到插件和当前回合上，当前回合结束，已有回想、压缩位置和历史保持原样。切换角色时的交接回想始终由原生回想写。

## 配置表单

面板按 `[config.<字段名>]` 的声明生成表单，运营者不需要手写 JSON。每个字段的 `type` 和 `description` 必填。写了 `default` 的字段可以省略，否则为必填。宿主只解析一次，`ctx.config` 中是已经校验过的普通值。

| 类型 | 值 | 面板控件 | 宽度 |
| --- | --- | --- | --- |
| `string` | 文字 | 单行输入框。`multiline = true` 时为多行文本框 | 半行；多行时整行 |
| `secret` | 文字，面板不回显 | 密码框，可以临时显示明文。已保存过的字段标有已保存，留空表示不修改 | 半行 |
| `integer`、`number` | 整数、数字 | 数字输入框，框内右侧显示取值范围。上下限都写了且跨度不超过 100 的 integer 带加减按钮 | 半行 |
| `boolean` | 开关 | 一行开关，名称在左，开关在右 | 半行 |
| `string_list` | 文字列表 | 标签输入框，回车添加一项，粘贴多行文字时每行成为一项 | 整行 |
| `scene` | 一个群，例如 `onebot:group:123` | 群选择器，从宿主已配置的群中选，显示群头像和群名 | 半行 |
| `scene_list` | 多个群 | 群选择器，可以全选和清空，群超过 6 个时可以搜索，收起时显示前两个群名和总数 | 整行 |
| `path` | 绝对路径 | 等宽字体的输入框 | 整行 |
| `url` | http 或 https 地址 | 输入框 | 整行 |
| `object_list` | 对象列表 | 每一项收起为一行摘要，点开后编辑子字段 | 整行 |

通用的可选属性如下。

- `label` 是表单中显示的名称，不填时显示字段名。建议写成运营者能看懂的中文。
- `group` 是分组标题，只用于顶层字段。同组的字段放在一起，没有分组的字段排在最前面。
- `placeholder` 是输入框中的示例文字，用于 string、secret、integer、number、path 和 url。
- `options` 是 string／integer／number 的候选值。可以直接写值，也可以写成 `{ value = "auto", label = "自动" }`，保存 value，显示 label。候选值不超过 3 个、且每个 label 不超过 8 个字时，面板显示为分段按钮，其余情况显示为下拉框。
- `minimum` 和 `maximum` 是 integer／number 的范围，后端同样会校验。面板在输入框内显示范围；只写了下限且下限是 0 或 1 时不显示。
- `object_list.fields` 定义一层对象子字段。子字段可以使用除 secret 和 object_list 以外的类型，不能设置 `group`。没有声明子字段的对象列表只能按 JSON 编辑，面板会提示补充声明。

`path` 和 `url` 写了 `default = ""` 时允许留空，表示不填写。没有写默认值时，必须填写有效的值。

`scene` 和 `scene_list` 在保存和加载时，都会核对群是否在宿主的配置中。插件作者无法预知运营者有哪些群，因此 `scene` 不能写 `default`，`scene_list` 的 `default` 只能是 `[]`。如果某个群之后从配置中删除，但仍然留在插件参数中，插件加载会失败并报告这个群，需要在面板中修改。

下面以订阅条目为例。

```toml
[config.card_mode]
type = "string"
label = "卡片样式"
group = "显示"
description = "推送消息用哪种样式"
options = [{ value = "auto", label = "自动" }, { value = "image", label = "图片" }]
default = "auto"

[config.subscriptions]
type = "object_list"
label = "订阅的直播间"
description = "每个直播间单独选推送到哪些群"
default = []

[config.subscriptions.fields.room_id]
type = "integer"
label = "房间号"
description = "直播间页面地址里的数字"
minimum = 1

[config.subscriptions.fields.name]
type = "string"
label = "显示名称"
description = "推送消息里用的名字"
default = "直播间"

[config.subscriptions.fields.scenes]
type = "scene_list"
label = "推送到的群"
description = "开播时在这些群里提醒"
default = []
```

### 面板如何排布参数

插件详情页的设置页签按以下规则排布表单，插件作者无法另外指定位置或样式。

- 每个 `group` 是一张卡片，卡片标题就是 group 的值。各组按第一次出现的顺序排列。
- 没有 `group` 的普通字段合成一张不带标题的卡片，排在最前面。没有 `group` 的 `object_list` 单独成一张卡片，标题是它的 `label`，标题旁显示条数。
- 卡片内分两列，宽度见上表。半行的字段按声明顺序两两并排；窄屏时改为一列。
- 卡片有 4 张或更多时，宽屏左侧显示分组目录，点击后跳到对应的卡片。
- 字段名显示在控件上方。`description` 收在字段名旁的提示图标里，鼠标悬停或聚焦时显示。必填字段（没有写 `default`）的名称后有红色星号；必填的 secret 保存过一次后不再标星号。表单改动后，或点了启用时，没填的必填项、超出范围的数字和格式不对的 JSON 在字段下方显示原因；对象列表里有问题的一项收起时边框标红。
- `object_list` 的每一项收起时显示一行摘要。第一个有值的 `string` 子字段作为这一项的标题，没有时用第一个有值的数字字段，其余的数字和文字子字段以名称加值的形式排在标题下方，例如 `房间号 22637261`。`scene_list` 子字段显示为群数，值为 true 的 `boolean` 和选中的 `options` 显示为标签。点开后编辑全部子字段，删除按钮也在展开的区域里。
- 设置有改动时，页面底部出现保存栏。插件处于停用状态时，保存按钮写作保存并启用，因为宿主只在启用时保存参数。

### 声明建议

- `label` 写得短一些，保证在半行宽度内放得下。单位写进 `label`，例如 `超时（秒）`。
- 取值的含义和限制写进 `description`，例如 0 表示关闭、需要先填写 SESSDATA。
- `object_list` 中，把能代表这一项的 `string` 子字段（名称、备注名）放在最前面，摘要才能一眼认出是哪一项。不需要名称时，把最有辨识度的数字字段放在最前面。
- 字段超过 6 个时用 `group` 分组。同一组内常改的字段放前面，很少修改的放进单独的一组，例如 `高级`。
- 几种互斥的方式（例如 `文字`／`图片`）用一个带 `options` 的字段声明，不要拆成几个 `boolean`。候选值少且短时显示为分段按钮，全部选项一眼可见。
- 半行字段尽量成对声明，避免一行只放一个短字段、另一半空着。

运行参数保存在实例根目录的 `lenbot.config.json` 中，KV 仅用于插件运行期业务数据。

### 插件修改自己的配置

LenBot 0.2.1 起，声明了 `configure` 权限的插件可以用 `await ctx.update_config({"字段": 值})`（`PluginContext.update_config`）修改自己的配置，例如在聊天中按主人的要求增删订阅。

- 只写给出的字段，其余字段保持原值。宿主按清单的 `[config]` 校验合并后的结果，`scene`、`scene_list` 的值必须是已接入的群；未声明的字段和不合法的值抛出 `ValueError`，配置保持不变。
- 校验通过后写入 `lenbot.config.json`，立即生效：返回值和 `ctx.config` 都是新值，面板显示的也是新值，插件不重新加载。插件在 `start()` 中读取并保留的值（例如后台循环的订阅列表）由插件自己按返回值更新。
- 宿主不检查请求人。只允许主人修改时，先调用 `ctx.require_owner()`；修改他人可见的内容前，用工具结果或 `wait_message` 向请求人确认。
- 面板保存同一插件的配置会重新加载插件，以面板保存的值为准。
- 使用这项能力的插件把 `requires_lenbot` 写成 `">=0.2.1,<1"`。

## 工具说明如何交给聊天模型

工具有三层说明。

- `summary` 用于发现目录和搜索结果。
- `description` 是实际调用时的完整说明。
- 类型、默认值和 `Annotated[..., Field(...)]` 提供参数 schema。

`summary` 可以省略，此时完整的 description 原样作为简介，不按标点截断。Field 中的 description、examples、枚举和范围都会保留。函数的 docstring、README、清单介绍和后台任务技能，都不会自动进入聊天提示。

角色必须同时允许 `tool_search` 和实际的工具名。聊天模型先从简短的目录中选择能力，再按完整的工具名搜索。搜索按原词匹配。被搜索到的工具从下一次请求开始可用。目录、搜索结果和面板使用同一份发现简介和来源，实际的工具定义始终提供完整的说明和参数 schema。

跨工具的流程写在可选的共享指南中。

```toml
[model]
instructions = "prompts/tools.md"
```

文件路径必须位于插件目录内。当前角色允许并且已经发现了插件的工具时，指南会进入系统提示。同一个插件的多个工具只加载一份指南。定向重新加载时会刷新指南，停用、卸载或压缩清除了发现状态后，指南会被撤下。

指南中应该写明真实 ID 的传递方式、分页、参数的选择和结果的含义。不要复制整份 README，也不要写入凭据。

```python
from typing import Annotated
from pydantic import Field
from len_bot.plugin import Invocation, Plugin, tool

class Example(Plugin):
    @tool("recent_count", "统计当前群指定时段的消息数量。",
          summary="查询本群最近几小时的消息数")
    async def count(self, ctx: Invocation,
                    hours: Annotated[int, Field(ge=1, le=72,
                        description="向前回溯的小时数", examples=[12])] = 24) -> dict:
        before = ctx.now()
        after = before - hours * 3600
        count = 0
        while True:
            page = ctx.messages_between(after, before, offset=count, limit=500)
            count += len(page)
            if len(page) < 500:
                return {"hours": hours, "count": count}
```

工具可以直接返回 dict、list、int、float、bool、None 等 JSON 值，宿主在调用边界统一编码。返回 str 时保持原文，原有的返回 JSON 文本的工具可以继续使用。不支持任意的 Python 对象、键不是字符串的对象、tuple 或非有限的浮点数。当前群由宿主确定，不让模型填写群号。

推荐的返回方式如下。

- 查询类工具返回数据。
- 发送类工具返回实际的 Sent 字段。
- 后台生成类工具返回 `{"status": "started", "delivery": "plugin"}` 这类业务结果，并在说明中写明完成后由插件自行发送。

`sent` 表示平台已确认，结果未知和失败都按未确认处理。

## 工具按能力组织

不要把每个外部接口都做成一个工具。列表、搜索和详情属于同一种查询能力时，用严格的 action 请求区分分支。查询与发送分开，与账号写入也分开。

现有插件的工具划分如下。这些插件已经按用途拆分，不需要合并成一个万能工具。

| 插件 | 工具 |
|---|---|
| B 站 | 四项，即视频、搜索、监测和账号读取 |
| 群聊总结 | 两项 |
| GSUID | 一项 |
| 计数模板 | 两项 |

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
async def query(self, ctx: Invocation,
                request: Annotated[Request, Field(description="搜索或详情请求")]) -> dict:
    if request.action == "search":
        return await self.search_source(request.query)
    return await self.read_source(request.item_id)
```

模型传入 `{"request": {"action": "read", "item_id": "真实ID"}}`。read 不接受 query。未知字段、缺少 ID 或无效的 action 都会在参数边界报错。请保持每个可调用定义的作用范围明确，不要堆积几十个互斥的可选参数。

`PluginTest.preview_tools()` 和面板显示的参数与实际交给模型的定义相同，即去掉自动生成的 title，保留业务属性名、说明、示例、枚举和约束。减少工具数量后，也要检查目录、共享指南和加载的 schema 的体积，不能把工具数量本身当作上下文的节省。

## 工具的真实请求来源

委派工作和账号操作类的工具可以声明 `needs_source=True`。宿主只为这些工具增加一个必填的 `source_message_id`，插件作者不要在函数参数中声明它。模型从本轮收到的消息中选择实际发出请求的消息，宿主按当前场景的真实平台消息 ID 读取发送者，放入 `Invocation.message`。

```python
@tool("owner_action", "按主人真实请求执行操作。",
      summary="主人操作", needs_source=True)
async def action(self, ctx: Invocation) -> dict:
    ctx.require_owner()
    return {"requester": ctx.message.sender.uid}
```

来源消息必须满足以下条件。

- 已经保存在当前群中
- 没有被撤回
- 是接收到的消息，并且不是 Bot 自己发的
- 发送者不是已知的其他 Bot，也不在黑名单中

群里的请求归属由模型判断，宿主读取模型指明的来源消息的发送者作为请求人。普通的查询不需要这个字段。

## 配置可用性

插件可以按当前的配置，返回不可用的工具名和原因。

```python
def unavailable_tools(self, scene: str) -> dict[str, str]:
    if not self.ctx.config["account_read_enabled"]:
        return {"account_read": "账号读取未开启"}
    return {}
```

这些工具保留在面板的预览中，发现目录和执行都会跳过它们。保存配置后，定向重新加载会刷新工具的可用性。这个入口只做同步的配置判断，实际请求人的权限在工具执行时另行检查。原因和指南中不能包含凭据。

面板角色详情的**工具与技能**页签统一显示以下信息。

- 群是否启用
- 角色许可
- 配置原因
- 发现简介和完整说明
- schema 和共享指南

## 调用上下文

- 命令匹配和全文／正则匹配中，`Invocation.message` 是真实触发的消息。
- `needs_source=True` 的工具有宿主解析出的真实来源，普通工具没有 message。
- `ctx.scene` 是当前启用的场景，例如 `onebot:group:80001`。
- `ctx.message.sender.uid` 和 `ctx.bot_id` 是带平台前缀的账号，例如 `onebot:70001`。`ctx.bot_id` 是当前场景发言的 Bot 账号，`ctx.platform` 是场景的平台；`self.ctx.bot_for(scene)`、`self.ctx.platform(scene)` 按场景取，`self.ctx.bot_id` 是根配置的 Bot 账号。
- 提及使用 `Mention("onebot:70001")`。

| 能力 | 使用方式 |
|---|---|
| 回复 | `await ctx.reply(text)`，图片 `reply_image(data, description)`，组合 `reply_parts(parts)` |
| 组合消息 | `Text(text)`、`Image(bytes, description)`、`Mention(user)` 从公共入口导入 |
| KV | `get_kv(key, default=None)`、`set_kv(key, JSON值)`、`delete_kv(key)`，都需要 await |
| 原消息 | `ctx.recent_messages(limit=20)`，只读取当前场景，最多 100 条 |
| 时间段消息 | `ctx.messages_between(after, before, offset=0, limit=200)`，Unix 时间 `after <= time < before`，按时间从早到晚排列，每页最多 500 条，用 offset 翻页 |
| 记忆 | `await ctx.memory(arguments)`，调用当前场景的 `memory` 工具，原生记忆或该群的记忆插件，不直接连接后端数据库；`ctx.native_memory(scene, arguments)` 只读访问原生记忆文件 |
| 主动交给聊天模型 | `await ctx.emit_event(text)`，与直接发送不同，它会唤醒聊天模型 |
| 时间 | `ctx.now()` 和 `ctx.timezone()`，明确使用场景的时区 |
| 主人权限 | `ctx.require_owner()`，使用真实来源的发送者 |
| 公网原图 | `await ctx.fetch_image(url, timeout_seconds=15)`，返回已经校验的原始图片 bytes |
| 等下一条消息 | `await ctx.wait_message(timeout_seconds=60, sender="same")`，见[多轮对话](#多轮对话) |
| 消息文字 | `message_text(message, names=None)`，见[消息](#消息) |

`PluginContext` 用于 `self.ctx`、start／stop 和后台入口。发送消息、读取消息、记忆和事件相关的方法需要明确传入启用的场景，例如 `await self.ctx.send(scene, text)`。

`self.ctx.scenes` 列出启用了这个插件并且聊天开关打开的场景。管理员在面板中关闭某个群的聊天后，这个群不再出现在列表中，插件的指令和通知也不再分发到这个群，向这个群发送消息或事件会报错。

`data_dir` 是这个插件独立的数据目录。KV 只按插件隔离，需要按群区分时，请把 `scene` 放进 key 中。

发送后返回 `Sent`，状态分为 sent、failed、unconfirmed、simulated 和 partial。只有 sent 表示平台已确认，客户端上的实际效果仍需要观察。用原生 JSON 返回回执时，可以把 message_ids 转为 list。

`PluginContext.fetch_image` 和 `Invocation.fetch_image` 使用宿主的公网地址检查和重定向规则，以及实例的 fake-ip 配置和图片的字节数、像素上限。它们返回完整的、已经验证的图片。

外部业务的协议、签名和轮询仍然由插件负责。卡片和图片的辅助接口见[卡片与图片](#卡片与图片)。

### 多轮对话

`Invocation.wait_message` 等同一场景中的下一条消息，用于插件提问后等回答。

```python
@command("问卷", "逐题提问")
async def survey(self, ctx: Invocation, args: str) -> None:
    await ctx.reply("你喜欢什么颜色？")
    answer = await ctx.wait_message(timeout_seconds=60)
    if answer is None:
        await ctx.reply("超时了，下次再来")
        return
    await ctx.reply("记下了：" + message_text(answer))
```

- `sender` 为 `"same"`（默认）时等触发这次调用的人，写账号（如 `onebot:70001`）时等这个人，`None` 时等这个场景里的任何人。没有触发消息的调用（定点任务、通知、没有来源的工具）不能用 `"same"`。
- 等到的消息由插件接管：不唤醒聊天模型，处理记录作为背景进入之后的上下文，与命令相同。等待中的发送者发来的下一条消息无论内容是什么都交给插件，包括命令。
- `timeout_seconds` 大于 0、不超过 600，到时返回 `None`。同一场景中同一个发送者（或任何人）同时只能有一个等待，重复等待时报错。插件重新加载、停用时等待随调用一起取消。
- 需要 `history` 权限。进程隔离的插件同样可以使用。
- 插件用 `asyncio.timeout` 或任务取消结束等待时，宿主同步释放该等待，后续消息恢复正常分发；同进程和进程隔离模式行为一致。

## 消息与通知

### 消息

`ChatMessage` 是宿主保存的一条消息，`ctx.message`、`recent_messages`、`messages_between`、`wait_message` 和 `RecallRequest.messages` 都返回它。

| 字段 | 内容 |
|---|---|
| `id` | 宿主内部的消息 ID，`report_memory_progress` 使用它 |
| `platform`、`bot_id`、`scene` | 平台名、本场景的 Bot 账号、场景 |
| `platform_message_id` | 平台的消息 ID，回复、`needs_source` 和 `reply_to` 使用它；未发出的 Bot 消息为 None |
| `sender` | `uid`（带平台前缀的账号）、`nickname`、`card`（群名片）、`role`（协议端给出的群身份，OneBot 为 `owner`、`admin`、`member`，没有时为 None） |
| `time` | Unix 秒 |
| `segments` | 消息段列表，见下表 |
| `reply_to` | 被回复消息的平台 ID，没有时为 None |
| `mentions_bot`、`is_self` | 是否提及 Bot、是否 Bot 自己发的 |
| `send_status` | 收到的消息为 `received`；Bot 的消息为 `sent`、`failed`、`unconfirmed` 或 `simulated` |
| `recalled` | 是否已撤回 |

每个 `Segment` 有 `type` 和 `data`。宿主统一以下几种段，其余段沿用协议端的类型名和字段，`data` 原样保留。

| `type` | `data` |
|---|---|
| `text` | `text` |
| `mention` | `user`：带平台前缀的账号，提及全体成员时为 `all` |
| `reply` | `id`：被回复消息的平台 ID |
| `image` | 协议端的图片字段，OneBot 常见 `file`、`url`、`summary`；QQ 表情包的 `sub_type` 不为 0 |
| `audio` | 协议端的语音字段，OneBot 的 `record` 段统一为 `audio` |
| `face`、`json`、`forward`、`file`、`video` 等 | OneBot 的原始字段，例如 `face` 的 `id`、`json` 的 `data`（卡片 JSON 文本）、`forward` 的 `id` |

`message_text(message, names=None)` 返回消息的文字，媒体和提及按聊天上下文的写法变成占位：`[图片1]`、`[语音1]`、`[提及 onebot:70001]`、`[提及全体成员]`，卡片写成 `[卡片：…]`，其他段写成 `[类型：主要字段]` 或 `[类型]`，回复段不输出。`names` 把账号换成显示名，例如 `{"onebot:70001": "小明"}` 时写成 `[提及 小明]`。插件需要把消息交给模型或写进总结时用它，不必自己逐段拼接。

### 通知

`@on_notice` 收到的 `Notice` 字段如下。

| 字段 | 内容 |
|---|---|
| `scene` | 通知所在的场景 |
| `notice_type`、`sub_type` | 通知类型和子类型 |
| `user_id`、`operator_id` | 相关账号和操作者，带平台前缀；没有时为 None |
| `time` | Unix 秒 |
| `platform_message_id` | 撤回通知中被撤回消息的平台 ID |
| `duration` | 禁言通知的秒数 |
| `raw` | 协议端的原始事件 |

OneBot 的通知按原来的 `notice_type` 和 `sub_type` 转发，常见的有：

| 通知 | 写法 |
|---|---|
| 入群、退群 | `group_increase`（`approve`、`invite`）、`group_decrease`（`leave`、`kick`、`kick_me`） |
| 撤回 | `group_recall`、`friend_recall` |
| 禁言 | `group_ban`（`ban`、`lift_ban`），`duration` 为秒数 |
| 戳一戳 | `notify.poke` |
| 管理员变动、群文件上传 | `group_admin`（`set`、`unset`）、`group_upload` |

通知只送到启用了这个插件的场景，私聊通知的场景为 `onebot:private:<QQ>`。

## 多平台

宿主可以同时接入 OneBot、Telegram 和飞书，场景和账号都带平台前缀。

- **声明平台**：清单的 `chat_platforms` 不包含某个场景的平台时，配置在这个场景启用插件会让插件加载失败，并列出这些场景；面板的群选择只列出支持的平台的群。目录条目可以写同名字段，从目录安装时与仓库清单核对。
- **媒体**：图片段在 OneBot 有 `url`，Telegram 是 `file_id`，飞书是 `image_key` 加 `message_id`。`await ctx.fetch_media(segment, max_bytes=20_000_000)`（`PluginContext.fetch_media(scene, segment, ...)`）读取 `image`、`audio`、`file`、`video` 段的文件：平台引用经平台下载，带 `url` 的段按宿主的公网检查读取，超过 `max_bytes` 时报错。需要 `history` 权限。
- **段类型**：`face`、`json`、`forward`、`poke` 等只在 OneBot 出现；Telegram 另有 `sticker`（动态贴纸）、`poll`、`location` 等；飞书富文本里的表情转成文字 `[表情名]`。
- **命令**：Telegram 的 `/命令@Bot用户名` 去掉本 Bot 的后缀后匹配。Telegram 群默认开启隐私模式，Bot 收不到中文命令和全文规则，需要关闭隐私模式或设为管理员；飞书群默认只收到 @机器人的消息，`@Bot /命令` 照常由插件接管。
- **通知**：Telegram 只有 `group_increase`、`group_decrease`；飞书有这两项和 `group_recall`、`friend_recall`；其他通知只在 OneBot 出现。
- **提及**：`Mention` 的账号必须属于场景的平台，否则发送报错。`Mention("all")` 在 Telegram 被省略，其余内容照常发出，`Sent.report` 写明已省略。
- **文字长度**：Telegram 单条文字最多 4096 个字符，带图片时说明文字最多 1024 个，超过时发送失败；宿主先按群的单条字数上限拆分。
- **测试**：`PluginTest(..., bots={"telegram": "telegram:7001"})` 为其他平台的场景给出 Bot 账号，`add_media(reference, data)` 登记 `fetch_media` 返回的内容。

## 卡片与图片

`len_bot.text_cards` 把文字排成图片卡片，自动换行和分页，`len_bot.image_assets` 校验图片。两者都是稳定的公共接口。

```python
import asyncio
from pathlib import Path
from len_bot.text_cards import CardSection, TextCards

cards = TextCards(Path(self.ctx.config["font_path"]))
pages = await asyncio.to_thread(cards.render, "今日日程", "11 月 1 日",
                                [CardSection("20:00", "直播")], source="示例日历")
for page in pages:
    await ctx.reply_image(page.data, page.text)
```

- `TextCards(font)` 的字体必须是字体文件的绝对路径，宿主不附带字体。插件可以把字体放进自己的 `assets/`（打包时一起发行，注意字体许可），或者做成 `path` 类型的配置项。
- `render(title, subtitle, sections, source=...)` 返回 `CardPage` 列表，每页有 PNG 字节 `data` 和这一页的文字 `text`。超过 32 页时报错。`text` 适合作为图片说明交给 `reply_image`，聊天模型之后读到的是这段文字。
- `image_assets.inspect_image(data)` 校验图片字节，返回 `(MIME 类型, 宽, 高, 是否动图)`；只接受 PNG、JPEG、GIF、WebP，上限是 `MAX_IMAGE_BYTES`（10 MB）和 `MAX_IMAGE_PIXELS`（2500 万像素），不符合时抛出 `ValueError`。插件从外部服务取到图片后先校验再发送。
- 排版和绘图占用 CPU，用 `asyncio.to_thread` 调用，以免阻塞聊天主循环。

## 单次生成、工作与定点播报

以下三种路径需要分别选择，不要把所有命令都交给聊天模型。

```python
# 普通查询：直接 Python 处理与发送。
await ctx.reply("今天的订阅内容")

# 用指定用途执行一次模型生成。
text = await ctx.generate("待处理的资料", role="mind", system="本次整理要求")
await ctx.reply(text)

# 长工作或文件：ctx 必须来自真实消息，宿主使用该消息发送者。
task = await ctx.delegate("整理刚才的活动", "CSV 文件", context="实际活动记录")
```

### generate

`generate` 执行一次模型生成并返回文本，发送由插件自己调用 `reply`。role 只能是 `mind` 或 `learner`。没有单独配置 `learner` 时使用 `mind` 的绑定。请求发给这个用途绑定的服务商和模型。`PluginContext.generate` 需要先传入 scene。

调用使用 ModelSlots 和原有的预算，用量写入 `model_calls`，`plugin` 字段记录插件来源。完整的系统提示和输入都由插件提供。

### delegate

`Invocation.delegate` 的参数是 goal 和 deliverable，以及可选的 context 和 materials（本场景共享资料的文件名列表）。

- 通知、cron 和没有来源的普通工具，都不能委派任务。
- `needs_source=True` 的工具可以沿用真实消息的发送者委派任务，不要传入伪造的 requester。
- 任务按已有的场景、发送者权限和角色技能许可执行。

返回值表示任务已经被接受，结果事件由宿主送回群会话。不要用 `wait` 轮询而长时间占用聊天。

### 定点任务

在 `start()` 中登记定点任务，handler 收到的 Invocation 不带 message。

```python
async def start(self):
    for scene in self.ctx.scenes:
        self.ctx.cron("日报", "0 8 * * *", self.publish,
                      scene=scene, timezone=self.ctx.timezone(scene))

async def publish(self, ctx):
    await ctx.reply("定点播报")
```

- 同一个插件和场景中的任务名必须唯一。
- 使用明确的 IANA 时区和五段式 cron。时间计算使用宿主的实现，遇到夏令时导致的时刻缺失或重复时，原样报错。
- 登记只在本次生命周期内有效。重启后从当前时间计算下一次执行，离线期间的次数跳过。
- `background` 仍然用于完成后按间隔轮询。
- 单次执行失败时记录原始错误并结束本次执行。下一次执行按日程正常进行。

### 插件技能

插件可以带有 `skills/<技能名>/SKILL.md` 和相关的资源。宿主只为启用了这个插件的场景提供技能目录，并继续应用角色的 `skills` 许可，任务以只读方式挂载这些技能。名称遵循现有的技能命名规则，与其他来源的技能重名时报错。插件技能可以在面板中查看，但不能通过普通技能的移动或删除操作改写插件源码。

[插件模板](https://github.com/lendevs/lenbot-plugin-template)和[独立的群聊总结插件](https://github.com/lendevs/lenbot-plugin-group-digest)涵盖了不使用模型、单次模型生成和独立工作三种路径。

## 生命周期和错误

`start()` 建立资源，`stop()` 关闭资源。启动协程也由宿主管理。重新加载或停用插件时，宿主先取消并等待尚未完成的启动，再依次关闭这个实例的资源。

用 `self.ctx.start_task(name, coroutine)` 登记插件自己的后台协程，宿主停止时会取消这些协程。它与容器中的工作任务无关。不要在 asyncio 主循环中执行阻塞的网络请求。

`start()` 限时 60 秒，`stop()` 限时 30 秒。

- `start()` 超时后，宿主会取消它并把插件标记为失败，错误为 `TimeoutError: 插件 start() 超过 60 秒未返回，已取消`。宿主的其他部分继续启动。
- `stop()` 超时后同样会被取消，并报告同类错误，关闭流程继续进行。
- 等待网络或预热缓存这类耗时的准备工作，请放进 `start_task`，不要在 `start()` 中等待。
- `migrate_data` 不限时。

处理器的一次报错结束这一次调用，原始错误由宿主写入运行日志（`plugin_error`），插件继续处理后续事件。

插件自己的日志使用 `self.ctx.log`（标准的 `logging.Logger`），写入宿主的 `logs/lenbot.jsonl`，并自动带上插件名和当前的群，以及当前的回复轮次和工具调用 ID。面板的系统日志可以按插件筛选。需要特殊权限的入口可以使用 `ctx.require_owner()`，普通查询不需要加上主人限制。

默认的 `inline` 模式与宿主同进程运行并共享依赖环境；`isolation = "process"` 隔离工作进程崩溃，插件进程仍拥有与宿主相同的文件与网络访问权限。

每个插件的状态带有 `health`：`level` 为 `ok`、`degraded`（运行中，但最近一小时记录过错误，或有后台循环、定点任务最近一次失败）、`failed`、`stopped` 或 `starting`，另有 `errors_last_hour`、`failing` 和 `last_error_at`。面板可以轮询 `GET /api/host/plugins/health`，该接口直接读取内存状态。接口扩展随版本发布，安装和生效方式见[安装与维护](#安装与维护)。

## 本地测试与发布

宿主提供一个公共的测试入口，不需要启动 OneBot、面板或 worker。它使用真实的生命周期、配置、入口匹配、工具校验和磁盘上的 KV，发送的消息只以 simulated 状态记录。

```python
from pathlib import Path
from len_bot.plugin_testing import PluginTest

async def check():
    async with PluginTest(Path("counter"), config={"step": 2}) as bot:
        assert await bot.message("计数加一")
        assert bot.deliveries[-1].text == "本群计数：2"
        result = await bot.tool("counter_read", {})
        assert '2' in result
```

- `scenes` 和 `owners` 可以在构造时指定，`scene`／`scene_list` 参数按 `scenes` 校验。
- `message(text, scene=..., sender=..., parts=...)` 模拟身份和消息，返回是否被接管。`parts` 是追加在文字之后的公开 `Segment` 列表，可验证提及或媒体的接管边界。处理器停在 `wait_message` 时 `message` 立即返回，下一次 `message` 作为回答，并等处理器继续执行完。
- `notice(notice_type, sub_type=..., user=..., operator=..., scene=..., message_id=..., duration=..., raw=...)` 按宿主的分发调用 `@on_notice`，返回运行的处理器数，处理器出错时报错。
- `deliveries` 包含插件、场景、组合内容、reply_to 和 simulated 状态。
- `saved_config` 是插件最近一次用 `update_config` 保存的配置，与根配置中保存的内容相同；没有保存过时为 `None`。
- `events()` 用于查看实际记录的插件事件。
- `recall(scene=..., recap=None, tasks=(), budget_chars=1500)` 用最近 8 条 `add_message` 的消息调用 `@recall`，返回聊天实际收到的召回条目。
- `memory(arguments, scene=...)` 按聊天 `memory` 工具的校验调用 `@memory_tool`。
- `compact(source, scene=..., budget_tokens=4096)` 调用 `@compact` 并按宿主的规则检查，返回宿主会采用的回想。

处理器或启动失败时，本次测试会报错。退出上下文时会停止插件并删除临时实例。

当前官方业务插件和模板都有工具，部分还使用 cron 或 start_task，保持 inline；它们不能只改 isolation 就切到进程模式。进程模式的限制是当前接口的明确范围。

模型默认关闭。通过 `models=` 明确配置测试模型后，generate 会经过真实的宿主协议、预算和用量记录。记忆服务和工作服务仍然会明确报错。插件自己的网络访问在测试中照常执行。

测试数据迁移时，传入旧的数据目录，例如 `PluginTest(package, data=Path('tests/data-v1'), data_version=1)`。进入上下文时，会像真实升级一样先运行 `migrate_data`，再调用 `start()`。

- 固定时钟使用 `PluginTest(..., now=lambda: 1791298800)`。
- `add_message(text, sender=..., scene=..., message_id=..., timestamp=...)` 保存一条测试消息并返回 ChatMessage，可以用它的 platform_message_id 调用需要来源的工具。消息默认属于当前模拟轮次；`received=False` 保存一条尚未进入会话的消息，`new_turn(scene)` 开始下一轮，此前的消息不再是有效来源。
- `preview_tools(scene)` 返回发现简介、完整说明、共享指南、参数、needs_source、允许的群和配置原因。
- `tool()` 经过真实的调用边界，结果是模型实际收到的字符串。
- `wait_tasks(name_prefix)` 等待插件通过 `start_task` 登记且名称匹配前缀的一次性后台任务完成。

测试本机的模型协议时，可以传入完整的模型配置，例如：

```python
models = {
    "providers": {"test": {"api": "openai-chat", "base_url": local_server_url,
                           "api_key": "synthetic"}},
    "roles": {"mind": {"provider": "test", "model": "local",
                       "context_window_tokens": 8192}},
}
async with PluginTest(package, models=models, now=lambda: fixed_time) as bot:
    print(bot.preview_tools())
```

测试模型配置直接发起真实 HTTP 请求，协议测试可指向本机模拟服务。模板同时提供返回 JSON 的查询工具 `counter_read`，以及在后台生成并自行发送的 `counter_card`。三个业务插件和[回放场景](../examples/plugin-tools/README.md)用于核对真实 ID、时间范围和结果的含义。

在 GitHub 上打开[插件模板仓库](https://github.com/lendevs/lenbot-plugin-template)，点击 Use this template 生成自己的仓库。

- 模板的 CI 调用 LenBot 提供的可复用工作流 `plugin-ci.yml`，默认用宿主的 `master` 运行插件测试和打包检查，可以传入 `host_ref` 固定宿主版本。
- 推送 `v*` 标签时，发布工作流把完整的运行源码、prompts／skills／assets 资源和许可说明打包成可导入的 ZIP，附加到 Release 上。
- 发布前填写插件自己的 `name` 和 `authors`，并更新版本和兼容范围。

**许可证**。LenBot 宿主采用 AGPL-3.0-only，插件模板和计数示例采用 GPL-3.0-only。插件和宿主运行在同一个进程中，推荐插件使用 GPL-3.0；GPLv3 第 13 条允许 GPLv3 作品与 AGPLv3 作品组合使用。

[English](plugins-v1.en.md)

官方插件的 CI 跟随宿主的 `master`，宿主的 CI 也会按插件目录中固定的版本运行官方插件的测试，任何一方破坏兼容都会直接失败。补丁版本保持兼容，新接口要求的最低宿主版本写入 requires_lenbot，只有破坏接口时才提升代次。
