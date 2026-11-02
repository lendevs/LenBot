# 配置表单

在 `plugin.toml` 中用 `[config.<字段名>]` 声明参数，面板据此生成表单，宿主校验后放进 `ctx.config`。每个字段的 `type` 和 `description` 必填，写了 `default` 的字段可以留空，没写的为必填。

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

[config.subscriptions.fields.scenes]
type = "scene_list"
label = "推送到的群"
description = "开播时在这些群里提醒"
default = []
```

## 类型

| 类型 | 值 | 控件 | 宽度 |
|---|---|---|---|
| `string` | 文字 | 单行输入框；`multiline = true` 时为多行文本框 | 半行，多行时整行 |
| `secret` | 文字，面板不回显 | 密码框；已保存过的字段留空表示不修改 | 半行 |
| `integer`、`number` | 整数、数字 | 数字输入框，框内显示范围；上下限跨度不超过 100 的整数带加减按钮 | 半行 |
| `boolean` | 开关 | 名称在左、开关在右 | 半行 |
| `string_list` | 文字列表 | 标签输入框，回车添加一项，粘贴多行时每行一项 | 整行 |
| `scene` | 一个群 | 群选择器，从宿主已配置的群中选 | 半行 |
| `scene_list` | 多个群 | 群选择器，可以全选、清空和搜索 | 整行 |
| `path` | 绝对路径 | 等宽字体输入框 | 整行 |
| `url` | http 或 https 地址 | 输入框 | 整行 |
| `object_list` | 对象列表 | 每项收起为一行摘要，点开编辑子字段 | 整行 |

通用的可选属性：

- `label`：表单中显示的名称，建议写运营者看得懂的中文，单位写进去，例如 `超时（秒）`。
- `group`：分组卡片的标题，只用于顶层字段。
- `placeholder`：输入框中的示例文字。
- `options`：候选值，可以写成 `{ value = "auto", label = "自动" }`。不超过 3 个、每个标签不超过 8 个字时显示为分段按钮，否则为下拉框。
- `minimum`、`maximum`：数字范围，后端同样校验。
- `object_list.fields`：一层子字段，子字段不能是 `secret` 和 `object_list`，不能设 `group`。

`scene` 和 `scene_list` 保存和加载时都会核对群是否在宿主的配置中，所以 `scene` 不能写 `default`，`scene_list` 的 `default` 只能是 `[]`。`path` 和 `url` 写了 `default = ""` 时允许留空。

## 面板如何排布

- 每个 `group` 是一张卡片，按第一次出现的顺序排列；没有分组的普通字段合成一张不带标题的卡片排在最前。没有分组的 `object_list` 单独成一张卡片。
- 卡片内两列，半行字段按声明顺序两两并排，窄屏时改为一列。卡片有 4 张或更多时，宽屏左侧显示分组目录。
- `description` 收在字段名旁的提示图标里。必填字段的名称后有红色星号。
- `object_list` 每项收起时，第一个有值的 `string` 子字段作为标题，其余数字和文字子字段以名称加值排在下方。

## 声明建议

- `label` 写短，保证半行放得下；取值的含义和限制写进 `description`。
- `object_list` 中把能代表这一项的名称字段放在最前面。
- 字段超过 6 个时用 `group` 分组，很少修改的放进单独的一组。
- 几种互斥的方式用一个带 `options` 的字段，不要拆成几个 `boolean`。
- 半行字段尽量成对声明。

运行参数保存在实例的 `lenbot.config.json` 中。KV 只放插件运行中的业务数据，不放配置。

## 在聊天中修改配置

LenBot 0.2.1 起，声明 `configure` 权限后，插件可以用 `await ctx.update_config({"字段": 值})` 修改自己的配置，例如提供一个工具，让聊天模型按主人的要求增删订阅：

```python
@tool("room_follow", "按房间号订阅直播间；只有主人发起的请求能执行。", needs_source=True)
async def follow(self, ctx: Invocation, room_id: int) -> dict:
    ctx.require_owner()
    rooms = [*ctx.config["rooms"], {"room_id": room_id, "scenes": [ctx.scene]}]
    saved = await ctx.update_config({"rooms": rooms})
    return {"rooms": saved["rooms"]}
```

- 只写给出的字段，其余保持原值。宿主按 `[config]` 校验合并后的结果，不合法时抛出 `ValueError`，配置不变。
- 保存后立即生效，`ctx.config` 返回新值，面板也显示新值，插件不重新加载。插件在 `start()` 中保留的值由插件自己按返回值更新。
- 宿主不检查请求人，只允许主人修改时先调用 `ctx.require_owner()`。
- 测试中 `PluginTest.saved_config` 是插件最近一次保存的配置。
- 使用这项能力的插件把 `requires_lenbot` 写成 `">=0.2.1,<1"`。
