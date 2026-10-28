# notebook：示例记忆插件

演示插件如何接管一个群的长期记忆。笔记保存在插件数据目录的 `notes.sqlite3` 中，按群分开。

| 入口 | 作用 |
|---|---|
| `@recall` | 每轮把与最近对话用词重合最多的几条笔记交给聊天模型 |
| `@memory_tool` | 本群的 `memory` 工具：`search`、`write`、`delete`、`list` |
| `@background("10m")` | 攒够设定数量的新消息后，用模型把它们整理成笔记，并报告处理到哪条消息 |

## 安装

1. 把本目录复制到实例的 `plugins/notebook`。`plugins.paths` 默认包含实例的 `plugins` 目录。
2. 在面板的**插件**页启用 notebook，按需修改参数后应用。
3. 在**群聊 → 设置 → 插件**中打开 notebook，再把**长期记忆**选为 notebook，保存后重启。

角色需要允许 `memory` 工具，聊天模型才能读写笔记。

## 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `min_messages` | 30 | 新消息达到这个数量才整理 |
| `model_role` | `learner` | 整理用的模型用途；没有单独配置 learner 时使用聊天模型 |
| `recall_limit` | 5 | 每轮自动召回最多带上的笔记条数 |

## 行为

- 插件第一次为某个群召回时开始服务这个群，整理从那一刻起算，之前的消息不整理。插件重启后，同样等到这个群的下一轮召回再继续整理，处理位置保存在插件的 KV 中。
- 每次整理后插件报告处理到的消息，数据清理只保留还没整理的原话。
- 原生记忆文件原样保留。需要导入时可以用 `ctx.native_memory(scene, arguments)` 读取，本示例不导入。
- 切回原生记忆后，原生整理从切回时开始；笔记文件不删除，再选回 notebook 时继续使用。

## 测试

```bash
uv run pytest tests/test_example_notebook.py
```
