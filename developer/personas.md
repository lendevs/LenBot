# 角色包装配

角色包的完整目录结构、`persona.yaml` 字段含义与材料编写方法见文档站[编写角色包](https://lendevs.github.io/LenBot/develop/personas)，可运行的完整示例见 [examples/personas/companion/](../examples/personas/companion/)。本文说明宿主在 `persona/`、`runtime/personas.py` 和 `chat/context.py` 中对角色包的校验、原子读写、提示词拼装与运行期切换机制。

## 目录校验与原子读写

`persona/profile.py` 负责角色包的读取、校验与保存。

- 必选文件只有 `persona.yaml`。`voice.md`、`boundaries.md`、`examples.yaml` 不存在时按空内容读取；面板保存一次角色资料后会写入这四个文件。
- `Persona` 模型启用 `extra="forbid"` 和 `strict=True`。`persona.yaml` 中不能内联填写 `voice`、`boundaries`、`examples`、`knowledge`、`stickers` 或 `avatar`，这些内容必须放在各自的文件或子目录中。
- `name`、`aliases` 元素、`example_tags` 元素和 `styles[].name` 均不可为空白字符串。`example_tags` 列出的每个标签都必须在 `examples.yaml` 的样例标签中出现过。
- `styles` 非空时，每项 `weight` 取值范围为 `0` 到 `1`，各项权重之和必须等于 `1`（浮点容差 `1e-12`）。
- 保存角色核心四文件时，`save_persona_files` 先把旧内容写入同目录的 `.persona-pending.json`，再逐个原子替换目标文件，最后删除 `.persona-pending.json` 并同步目录。写入中途中断时，下次 `read_persona_files` 发现 `.persona-pending.json` 会自动还原上一版完整文件。

## ZIP 导入导出与删除

`persona/packages.py` 处理原生角色包 ZIP 归档：

- 上传与导出的 ZIP 体积上限为 64 MiB，解压后总字节数上限为 128 MiB，条目上限为 2048 项。
- 仅允许根目录白名单文件（四个核心文件、三份表达规则覆盖文件、`avatar.png`、`README.md`、`LICENSE`、`NOTICE`）以及 `knowledge/`、`stickers/` 两个子目录；拒绝符号链接、特殊文件、隐藏路径、路径越界和加密条目。
- 导入时先在 `personas/` 下的临时目录展开并通过 `load_persona` 完整校验，校验通过后重命名发布。若包内 `id` 已被实例中其他角色占用，`runtime/personas.py` 的 `import_role` 会将包内 `id` 改写为新目录名。
- 面板删除角色时，仅允许删除位于实例 `personas/` 下且当前没有任何群绑定的角色目录。原目录移动到 `.runtime/deleted-personas/<目录名>-<时间戳>`，`memory/` 下属于该角色 ID 的长期记忆保留。

## 提示词拼装与每轮抽样

`chat/context.py` 在构造系统消息和每轮参考材料时消费 `Persona` 对象：

1. `character_material` 读取 `next_character.md`，填入 `brief`、`self_reference`、`aliases`、`behavior`、`voice`、`boundaries` 以及 `select_examples` 选出的最多 8 条样例（未填 `example_tags` 时取前 8 条，否则按标签交集按原顺序取前 8 条）。若当前群配置了 `persona_aliases`、`relationships` 或 `behavior_addendum`，再由 `next_scene_persona.md` 渲染为本群补充段落拼入 `$scene_material`。
2. `build_system` 读取 `next_mind.md`，填入 `$name`、`$scene`、`$bot_id`、`$character`、`$response_choice`、`$expression_principles` 和发送出口说明，随后追加 `chat_examples.md` 以及当前场景已开放工具对应的能力说明段落。
3. `styles` 非空时，每轮开始由 `select_style` 按权重随机抽取一条正权重风格，经 `next_style.md` 渲染后放入当轮宿主参考材料，不进入稳定系统前缀，也不写入会话历史。

## 替换框架的表达规则

`EXPRESSION_FILES` 定义了角色包可单独覆盖的三份表达提示词：

| 角色包文件 | 替换的框架提示词 | 用途 |
|---|---|---|
| `response_choice.md` | `next_response_choice.md` | 开口前的回应判断 |
| `expression_principles.md` | `next_expression_principles.md` | 群聊默认表达做法 |
| `chat_examples.md` | `next_chat_examples.md` | 情境判断与工具选择示范 |

角色包内对应文件存在且去掉空白后非空时，该角色使用自己的文件，并通过 `Template.safe_substitute(name=persona.name)` 替换 `$name`，其余 `$` 原样保留。文件不存在或为空白时，回退到框架提示词（包括实例 `state/prompts/` 中保存的全局覆盖版本）。框架与角色材料的职责边界见[群聊表达](expression-materials.md#框架和角色的分工)。

## 运行期切换与回退

`runtime/personas.py` 的 `PersonaService` 管理运行中场景的角色切换与热重载：

- 角色库同时汇总实例 `personas/` 下的非符号链接角色目录和 `scenes.*.persona` 直接引用的外部目录。库中存在重复角色 `id` 时，拒绝切换到该 `id`。
- 切换角色（`switch`）和保存角色后热重载（`reload`）都会获取目标群的回合执行锁 `runner.execution`。若当前回合正在执行，面板请求最多同步等待 3 秒；超时未完成时转入后台继续等待，同时在 `switching` 中公布待切换目标供面板展示。热重载不允许直接修改运行中角色的 `id`。
- 切换到不同 `id` 的角色时，`_bind` 将当前群配置的 `persona_aliases`、`relationships`、`behavior_addendum` 存入该群配置的 `inactive_personas[<旧ID>]`；若新角色 `id` 此前在 `inactive_personas` 中存有记录，则自动恢复到当前群配置。
- 保存根配置后，若新旧角色 `id` 不同，宿主先调用 `chat.hand_over` 生成一份角色交接回想，再由 `_apply` 同步更新运行态场景配置、任务技能许可、外部工具目录和记忆服务的活动角色。
- 交接模型调用失败时，记录 `persona_handover` 警告日志并按既有会话继续切换，同时在本轮 `host_state` 注入提示，标明当前会话中此前 `assistant` 的发言和承诺归属上一角色；交接成功时则标明较早群聊回想中的发言和承诺归属上一角色。
- 若 `_apply` 装配阶段抛出异常，运行态配置立即还原，并重新获取配置写锁将 `lenbot.config.json` 恢复为切换前的角色绑定。
