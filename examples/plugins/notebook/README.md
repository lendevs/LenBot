# notebook：示例记忆插件

演示插件如何接管一个群的长期记忆。笔记保存在插件数据目录的 `notes.sqlite3` 中，按群隔离。

| 入口 | 作用 |
|---|---|
| `@recall` | 每轮把与最近对话用词重合最多的几条笔记交给聊天模型 |
| `@memory_tool` | 提供本群的 `memory` 工具：`search`、`write`、`delete`、`list` |
| `@background("10m")` | 攒够设定数量的新消息后调用模型整理成笔记，并上报已处理到的消息位置 |

## 安装

1. 把本目录复制到实例的 `plugins/notebook`（`plugins.paths` 默认包含 `plugins`）。
2. 在面板的**插件**页启用 `notebook`，按需修改参数后保存。
3. 在**群聊 → 设置 → 本群启用的插件**中开启 `notebook`，再将**长期记忆**选为 `notebook`；插件已在该群运行时，保存后在当前回合结束时切换生效。

当前群绑定的角色需要允许 `memory` 工具，聊天模型才能调用该工具读写笔记。

## 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `min_messages` | `30` | 新消息达到该数量后触发一次后台整理 |
| `model_role` | `learner` | 整理使用的模型用途；未单独配置 `learner` 时使用聊天模型 |
| `recall_limit` | `5` | 每轮自动召回最多带上的笔记条数 |

## 行为

- 插件首次为某个群执行自动召回时记录起点，后台整理从该时刻起算，不补处理此前消息；宿主重启后同样在该群下一轮召回后继续整理，进度保存在插件键值存储中。
- 每次整理完成后通过 `report_memory_progress` 上报最新消息 ID，宿主按数据保留期清理旧消息时保留尚未整理的区段。
- 原生记忆文件原样保留；需要迁移旧资料的插件可通过 `ctx.native_memory(scene, arguments)` 只读查询。
- 切回原生记忆后，原生后台整理从切回时刻开始；插件已有笔记保留在 `notes.sqlite3` 中。

## 测试

```sh
uv run --no-sync pytest tests/test_example_notebook.py
```
