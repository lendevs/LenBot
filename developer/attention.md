# 持续关注与局部收尾

维护者使用本文配置和核对实验性的时间注意力。它在 `feat/speech-limit` 的规则上增加主脑声明，尚未经过真实群聊效果验证。

## 消息合批

直接联系默认空闲 1.5 秒后开始、最多等 4 秒，点名为 3 秒和 8 秒，聚焦为 4 秒和 12 秒。本批里已经发过言的人再发消息时，空闲计时从这条消息重新算，中间夹着别人的消息也一样；本批第一次出现的人发消息不重新计时。末条只有图片，并且发图的人本批已经发过言或这张图就是唤醒消息时，空闲等待加倍，仍不超过该渠道的上限，给随后补的文字留出时间。

持续关注与探索使用聚焦的等待参数，环境插话使用自己的间隔。

## 回复效果系数

环境插话和随机探索的参与分乘一个系数。系数取本群最近 3 天内、由环境插话或随机探索唤醒的回合里最多 10 条已判定的回复效果：`agree` 和 `continue` 记 1，`unrelated` 和 `negative` 记 -1，其余记 0，每条按 24 小时半衰加权。加权平均（分母另加 2，避免一两条判定就大幅变化）小于 0 时，系数为 1 加上它的一半，最低 0.5；不小于 0 时为 1。直接联系、点名、对话继续和持续关注不乘系数。系数随唤醒判定保存为 `effect_factor`，写进 `attention_ambient` 日志，现场的唤醒详情在系数小于 1 时显示。

`uv run --no-sync python scripts/first_reply_latency.py batches` 用固定 OneBot 到达序列核对图片后补文字、同一人续发、换人、隔着别人续发、旁人发图和上限；`report <数据库>` 读取实际回合的首句等待与合批、模型、工具、发送耗时。

## 配置

在群的 `attention` 中配置，或在隔离实例根配置的 `attention` 中配置：

```json
{
  "declarations": {"mode": "enforce"},
  "disposition": {"mode": "enforce"}
}
```

不配置即关闭。配置在场景重新装配时生效。面板的群设置会保留这些字段，目前没有专用编辑控件。

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
- `resolve`：主脑认为已经完成。
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

候选由主脑判断后 keep 或 resolve，例如指定账号的一条闲聊也会匹配 person。定时条件触发一次后不再自动重复，意图仍保留；再次定时需要修改意图。

## 局部收尾

可在最后一次 say、react、message_reaction 或 attention 调用上附加：

```json
{"disposition": {"state": "closed", "minutes": 5}}
```

没有表达时可直接调用 `end_turn`，参数同上。`open` 可以带 `people`，限制 focus 续接的账号；不填则不限。open 只放行原规则会产生的 focus，不扩展基线关注窗口。`minutes` 是局部状态的有效期；等待稍后补充或跨话题的结果应使用 `attention.intend`。

`closed` 在有效期内抑制 focus 和 ambient；直接联系、点名和持续意图照样唤醒，已有意图继续保留。正常结束回合的最后一次收尾替换旧值，省略则回到基线。异常回合不采用新的局部状态。

## 调度、持久化与限制

- 优先级：direct、named、attention、focus、ambient。
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

记录模式仍会改变工具与提示，可能影响模型回复。

事件使用既有运行日志：`attention_intent`、`attention_candidate`、`attention_local`、`attention_disposition`。模型请求与用量沿用原日志和 model_calls。

## 核对

```sh
uv run --no-sync pytest -q tests/test_attention_protocol.py
uv run --no-sync pytest -q
```

协议测试使用本机 HTTP 固定响应和隔离数据库，覆盖跨无关回合、重启、候选与完成、定时、批量、过期、配置与权限边界。

研究方案、旧补丁、数据与模型实验只保留在 Git 忽略的根目录 `research/`。旧 v1/v2 bundle 使用不同配置及状态，复现旧结果应使用旧 bundle 的独立副本。
