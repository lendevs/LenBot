# 持续关注与局部收尾

本文说明对话继续、插话间隔、发言节奏、消息合批、回复效果系数，以及实验性的跨回合关注声明与局部收尾配置。

## 对话继续

Bot 的每次发言（`expression_entry_seq` 非空的自身消息）打开一次对话继续，键为账号或 `*`：

- 引用回复了某条群友消息时，打开给这条消息的作者。
- 否则打开给唤醒本回合的人（直接联系、点名或对话继续的发送者）。
- 主动插话没有回复具体的人时，打开给 `*`，即任何人。

`focus_seconds`（默认 120）内，该账号（或任何人）的下一条消息按 focus 唤醒一次并消耗这次对话继续；其他人的消息仍需直接联系、点名或命中持续意图。Bot 自己的发言只打开新的对话继续，不延长已有的。被直接联系或点名时，发送者的对话继续随之取消。`focus_seconds=0` 关闭对话继续。

发言在回合结束、回合中追加消息、检查续接和固定提示语发出时读入，按 `spoke_through` 记录读到的位置。读入前已经到达的消息在读入后补判一次。回合进行中，只有本次唤醒的人、打开了对话继续的人或直接联系能让回合续接；发言节奏未放行时不续接。

## 插话间隔

`ambient` 的截止时间从 Bot 上次发言或上次主动看群（`spoke_at` 与 `ambient_last_at` 的较晚者）起算，间隔为：

```text
min(ambient_max_interval_seconds, ambient_min_interval_seconds × 2^silence_level / effect_factor)
```

`silence_level` 达到 `log2(max / min)` 向上取整后直接取最大间隔。

- 主动插话后，`focus_seconds` 内没有人接话（没有消耗 `*` 的对话继续），`silence_level` 加 1。
- 对话继续、点名或环境插话回合以沉默正常结束、本回合没有直接联系时，`silence_level` 加 1。
- 回合里发言并且来自直接联系、点名或对话继续，或者被直接联系、点名时，`silence_level` 归零。
- 群聊重新开启或暂停后恢复时，`ambient_last_at` 设为当时，插话间隔从这时起算。
- 关闭聊天或关闭群立即生效，不等正在执行的回合：回合在所处步骤结束，记为 `cancelled`；回合结束时从当前状态复制，保留开关。
- 插件用 `hold_quiet` 设置临时安静，`requester` 为 `plugin:<名称>`。续期替换自己的、已结束的或更早结束的临时安静，保留别人设置的更晚结束的；解除只清除自己的。

可以接的话指非自身、非其他 Bot、没有回复或 `@` 别人、去掉标点后不只是 `哈哈`、`草`、`6` 一类单独反应的消息。其余消息只在开启 `explore_probability` 时参与随机探索。

## 发言节奏

聊天唤醒（直接联系、点名、持续意图、对话继续、环境插话和随机探索）发言前按令牌桶等待：桶容量为 `speech_burst`，每 `speech_interval_seconds` 补一个，发言记录来自 `speech` 表。非直接联系的唤醒同时等待每小时发言上限。提醒和后台任务结果不受节奏限制。`speech_interval_seconds=0` 关闭节奏。

面板的三个唤醒档位只设定插话间隔和发言节奏：

| 档位 | `ambient_min_interval_seconds` | `ambient_max_interval_seconds` | `speech_burst` | `speech_interval_seconds` |
|---|---|---|---|---|
| `active` | 600 | 2400 | 3 | 120 |
| `moderate` | 1800 | 7200 | 3 | 180 |
| `quiet` | 5400 | 21600 | 2 | 300 |

当前关注参考里列出等待接话的账号及截止时间，群聊还列出最近 10 分钟 Bot 的发言条数和其他人的消息条数。

## 消息合批

直接联系默认空闲 1.5 秒后开始、最多等 4 秒，点名为 3 秒和 8 秒，对话继续为 4 秒和 12 秒。本批里已经发过言的人再发消息时，空闲计时从这条消息重新算，中间夹着别人的消息也一样；本批第一次出现的人发消息不重新计时。末条只有图片，并且发图的人本批已经发过言或这张图就是唤醒消息时，空闲等待加倍，仍不超过该渠道的上限，给随后补的文字留出时间。

持续关注与探索使用对话继续的等待参数，环境插话使用插话间隔。

## 回复效果系数

插话间隔除以一个系数。系数取本群最近 3 天内、由环境插话或随机探索唤醒的回合里最多 10 条已判定的回复效果：`agree` 和 `continue` 记 1，`unrelated` 和 `negative` 记 -1，其余记 0，每条按 24 小时半衰加权。加权平均（分母另加 2，避免一两条判定就大幅变化）小于 0 时，系数为 1 加上它的一半，最低 0.5，插话间隔最多延长到 2 倍；大于 0 时，系数为 1 加上它的四分之一，最高 1.25，插话间隔最多缩短到 0.8 倍。同样多的判定，收紧比放宽快。直接联系、点名、对话继续和持续关注不受系数影响。系数随唤醒判定保存为 `effect_factor`，写进 `attention_ambient` 日志，现场的唤醒详情在系数不为 1 时显示。

`uv run --no-sync python scripts/first_reply_latency.py batches` 用固定 OneBot 到达序列核对图片后补文字、同一人续发、换人、隔着别人续发、旁人发图和上限；`report <数据库>` 读取实际回合的首句等待与合批、模型、工具、发送耗时。

## 恢复后的追赶

宿主启动时还有上一个进程留下的未读消息，或一个回合因聊天模型的服务商错误失败后，场景进入追赶状态，直到某个回合拿到模型回复。追赶期间：

- 环境插话和随机探索只在最近 5 分钟（`CATCH_UP_SECONDS`）内有可以接的话时开轮；只有旧消息时撤下这次唤醒，消息留给下一轮，日志 `attention_catch_up`。
- 开轮时 5 分钟以前的消息单独成段，标题写明追赶开始时间、这些消息当时没有回应、按原时间理解且不逐条补回；@ Bot 的旧消息照常唤醒，按原时间交给模型。失败回合已经读入会话的批次不再重发，恢复回合的批次标题同样带这段说明。
- 恢复未结束对话（`resume`）的回合不受影响。

## 模型故障提醒

`runtime/model_alerts.py` 按聊天绑定（服务商和模型）统计所有场景连续以服务商错误结束的回合（`ModelHTTPError` 或 `ModelConnectionError`，回合结果的 `model_failure`）。连续 3 个时私聊每位主人一次：错误类别、最早失败时间、涉及场景数和最近一次错误；之后第一个拿到模型回复的回合（`model_replies` 大于 0）再发一次恢复。主人的私聊场景已接入时经该场景的发送出口并入库，否则直接经平台发送；非真实发送时只写 `model_alert` 日志。宿主不切换模型，不重试。

一段失败结束时（不论是否已提醒），`SessionUpkeep.model_recovered()` 让因服务商错误用完 3 次自动重试的后台整理清零一次失败次数，积压的整理不必等面板重试；它不增加请求，也不对其他原因的失败生效。

## 唤醒判定记录

每条收到的消息在 `messages.wake_verdict` 里保存一次判定：`woke`、`channel`、`reason` 和 `effect_factor`。`effect_factor` 只在消息可以接话时计算，其余为 `null`。

## 配置

在群的 `attention` 中配置，或在隔离实例根配置的 `attention` 中配置：

```json
{
  "declarations": {"mode": "enforce"},
  "disposition": {"mode": "enforce"}
}
```

`declarations` 默认开启（`enforce` 与下文的默认限制），写 `null` 关闭；`disposition` 不配置即关闭。根配置格式 5 及更早的文件里 `declarations: null` 是面板保存的旧默认值，升级到格式 6 时去掉，按新默认开启；格式 6 起 `null` 表示主动关闭。配置在场景重新装配时生效。面板群设置的持续关注与对话收尾一节提供两个开关，运行模式和上限在高级设置中。

面板读取与取消：

- `GET /api/host/scenes/{scene}/focus`：配置的两种模式、角色是否允许 `attention`、生效中的意图（条件、创建与到期时间）和当前局部状态。
- `DELETE /api/host/scenes/{scene}/focus/intents/{id}`：等当前回合结束后移除该意图及其待处理候选，效果与模型调用 `drop` 相同，日志 `attention_intent` 带 `source=panel`。

工具可用时系统提示词附加 `next_attention.md`，说明对话继续的范围和何时登记意图。

`declarations` 默认限制：最多 5 个意图、每个 4 个条件，每个条件最多 5 个账号或关键词，有效期最长 240 分钟。参数名为 `max_intents`、`max_conditions`、`max_people`、`max_keywords`、`max_minutes`。

`disposition` 默认最长 30 分钟、最多 5 个账号，参数为 `max_minutes`、`max_people`。

## 持续意图

角色须允许 `attention` 工具。未配置或角色不允许时不提供此工具，也不执行旧意图。

```json
{
  "action": "intend",
  "when": [{"type": "person", "people": ["onebot:70001"]}],
  "match": "any",
  "minutes": 60,
  "reason": "等待对方补充报错日志",
  "end_turn": true
}
```

工具返回意图 ID。`intend` 带 `id` 时替换该意图的条件和有效期；其他动作只需要 `action` 和 `id`：

- `keep`：继续等待，不重置有效期；未调用 keep 也会保留。
- `resolve`：聊天模型判定已经完成。
- `drop`：放弃关注。

`end_turn=true` 可以在操作后结束当前回合。工具输入不合法时沿用现有工具错误返回。

条件定义：

| type | 字段 | 匹配 |
|---|---|---|
| person | people | 指定账号发消息 |
| thread | message_id | 对该消息的回复链 |
| open_question | message_id、可选 keywords | 回复链或任一关键词 |
| topic | keywords | 文本包含任一关键词 |
| at | minutes | 从声明时起，指定分钟后检查一次 |

`match=any` 表示任一条件满足，`all` 表示全部消息条件满足。at 必须早于意图的有效期；可以独立使用或放在 any 中，不支持与其他条件作 all 组合。关键词只做大小写折叠后的包含匹配，不推测语义。

候选由聊天模型判断后执行 `keep` 或 `resolve`，例如指定账号的一条闲聊也会匹配 `person`。定时条件触发一次后不再自动重复，意图仍保留；再次定时需要修改意图。

### 由模型决定关注什么

持续意图是插话的主要来源：模型在回合里声明接下来要跟的人、话题和时长，命中时宿主按声明唤醒。插话间隔退为兜底，没有声明或声明没命中时才按它偶尔看一眼群：

- 意图唤醒的回合开始时和环境插话一样记一次 `ambient_last_at`，插话间隔从这时重新起算，意图唤醒替代而不是叠加在插话之上。
- 同一个意图由消息命中开轮后，`REWAKE_SECONDS`（120 秒）内再命中的消息只记为候选，下一轮在当前关注参考里一起列出，日志 `attention_candidate_held`；计时条件不受限制。
- 不增加模型调用：意图命中直接开一个普通回合，没有额外的判断请求。

### 话题新鲜度

环境插话、随机探索和意图唤醒的批次末尾附 `<话题新鲜度>`（`chat/freshness.py`、`next_topic_freshness.md`），只写事实：叫醒这次的那条消息的时间和距今多久，之后又有几条、几个人在说，其中几条和它有相同的字词（汉字两字组或两个以上字母数字），最后一条距今多久，中间停了 5 分钟以上的次数和最长一次。提示词说明隔得久、后面在聊别的就不回头接，模型判断值得回头时再接。直接联系、点名和对话继续不附这一段。追赶期间仍按上文只看最近 5 分钟开轮，新鲜度按实际开轮的批次计算。

## 局部收尾

可在最后一次 say、react、message_reaction 或 attention 调用上附加：

```json
{"disposition": {"state": "closed", "minutes": 5}}
```

没有表达时可直接调用 `end_turn`，参数同上。`open` 可以带 `people`，限制 focus 续接的账号；不填则不限。open 只放行原规则会产生的 focus，不扩展基线关注窗口。`minutes` 是局部状态的有效期；等待稍后补充或跨话题的结果应使用 `attention.intend`。

`closed` 在有效期内抑制 focus 和 ambient；直接联系、点名和持续意图照样唤醒，已有意图继续保留。正常结束回合的最后一次收尾替换旧值，省略则回到基线。异常回合不采用新的局部状态。

## 调度、持久化与限制

- 优先级：direct、named、attention、focus、ambient、explore。
- attention 使用 focus 的 idle/max 时间合并消息；同批多个意图只开一轮，在当前关注参考中展示各意图的候选消息 ID。
- 被直接联系时仍记录同批意图候选；下一批新消息可以再次触发。意图随已有唤醒批次参与判断，使用当前回合的预算。
- at 没有新消息也可以叫醒。静默结束后仅处理仍在有效期内的计时条件。意图先过期则不补触发。
- 黑名单、其他机器人过滤、only_direct、静默、暂停和既有资源/发言限制继续生效。
- 更新、完成、撤销或过期时移除对应待处理候选。其他意图和直接联系仍保留。
- 状态保存在原有 `mind_sessions.attention_state` JSON 的可选 declared/disposition 字段中，支持重启恢复；未开启时不写入这些字段。无新表或数据库格式变更。

## 实验模式

`declarations.mode`：

- enforce：维护和执行意图。
- record：维护、匹配并记录候选，但不因意图增加唤醒。
- context：维护工具 ID 和生命周期以支持后续调用，模型从历史工具交换读取意图。

`disposition.mode=record` 记录局部状态但不抑制基线唤醒。

记录模式下模型仍会看到意图工具和相应提示。

事件使用既有运行日志：`attention_intent`、`attention_candidate`、`attention_local`、`attention_disposition`。模型请求与用量沿用原日志和 model_calls。

## 核对

```sh
uv run --no-sync pytest -q tests/test_attention_protocol.py
uv run --no-sync pytest -q
```

协议测试使用本机 HTTP 固定响应和隔离数据库，覆盖跨无关回合、重启、候选与完成、定时、批量、过期、配置与权限边界。

研究方案、旧补丁、数据与模型实验只保留在 Git 忽略的根目录 `research/`。旧 v1/v2 bundle 使用不同配置及状态，复现旧结果应使用旧 bundle 的独立副本。
