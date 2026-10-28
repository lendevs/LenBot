# 表达回放用例

这是一组通用的群聊情境，用来对比修改提示词或角色包前后的回复。人物、账号和对话都是虚构的，角色使用[示例角色小然](../personas/companion/)。

在每个用例中，只有 @ Bot 的消息会触发回复，之前没有 @ 的消息作为上下文。`expect` 写的是期待的回应方式，由人工对照判断。

## 运行

回放会真实调用模型，按模型服务的标准计费。在本目录中执行以下命令。

```sh
cp lenbot.config.example.json lenbot.config.json
# 填写 models 里的接口地址、密钥和模型名
uv run --no-sync lenbot-eval plan expression --profile current   # 检查用例和配置
uv run --no-sync lenbot-eval run expression --profile current    # 确认后输入 run 开始
uv run --no-sync lenbot-eval report <run 目录名>
```

结果写入 `runs/`，每个用例的运行日志放在该用例自己的 `logs/` 中。改动前后各运行一次，再用 `lenbot-eval compare <旧> <新>` 对比。`lenbot.config.json`、`runs/` 和 `chat.sqlite3` 已经被 `.gitignore` 排除。

## 用例

| ID | 情境 | 观察重点 |
|---|---|---|
| several-calls-at-once | 三个人几秒内先后 @ | 用一句话一起回应，不逐条回复 |
| upset-after-bad-luck | 抽卡歪了，让 Bot 别笑 | 站在对方那边，不继续逗 |
| concrete-bad-luck | 交卷时平板没电 | 回应具体的事情，不空喊加油 |
| answer-a-fact | 问角色生日 | 直接给日期 |
| teasing | 被调侃偷吃宵夜 | 斗嘴有分寸 |
| good-news-sticker | 收到 offer | 表情承担情绪，文字不重复强调 |
| follow-the-topic | 聊完海报再问 Bot 今天干嘛 | 与前面的话题衔接 |
| spicy-hotpot | 被叫去吃重庆火锅 | 结合不吃辣自然回应 |
| are-you-a-bot | 群里聊谁是机器人 | 回答自然，不生硬声明 |
| ordinary-update | 分享一顿普通的午饭 | 允许平常反应，不强行抖包袱或安排下一步 |
| mixed-result | 有进展但仍为一个细节烦恼 | 理解具体烦恼，不保证未来一定成功 |
| unknown-arrangement | 询问未知的活动库存安排 | 区分推测和已知安排，不凭安慰保证有货 |
| corrected-by-a-friend | 说错面馆休息日后被群友纠正 | 大方认下，顺着新信息接着聊 |
| capability-without-posturing | 询问当前是否能发语音 | 如实回答能力，不追加人设表演 |

新增用例时沿用 `cases.json` 的格式。

- `message` 步骤放入原始的 OneBot 事件。
- `await_turn` 等待指定的轮次结束。
- `observe` 继续观察指定的秒数。

## 社交对照

`social.json` 固定了旁听、插话、事实回答、表达、表情选择和人物偏好六类虚构情境。
在仓库根目录执行：

```sh
uv run --no-sync python scripts/compare_social.py --instance . --label baseline
```

命令读取实例的聊天模型连接，在 `state/experiments/social-日期/baseline/` 下建立独立模拟实例，
每例默认运行三次。`social-stickers.yaml` 沿用示例角色的图片，为微笑和赞同提供共同的开心标签、中性描述和编号文件名，
检查同一情绪下的语气选择；实际采用的图片目录随每次回放归档。

每例 `result.json` 的 `social` 保存是否开口、误插话、漏接、事实匹配、人机味短语计数、
发出的表情、模型请求数、首句等待和 token。事实匹配按用例中的正则检查；完整回复也保留下来供人工复核。
人机味短语计数记录明确的说法，复述点评和安慰是否合适由人工判断。
在运行目录的 `annotations.json` 中填写 `verdict`、`reason` 和表情用例的 `sticker_fit`，
`report.json` 汇总逐例指标与人工判定。修改前后使用同一份用例和重复次数。

```sh
uv run --no-sync python scripts/compare_social.py --report <时间戳运行目录>
```

记忆对照增加了自嘲、称呼偏好和过期状态三例，可单独运行：

```sh
uv run --no-sync python scripts/compare_memory_retrieval.py --instance . --answer \
  --case self-deprecation preferred-name expired-status
uv run --no-sync python scripts/first_reply_latency.py batches
```

`batches` 为直接联系、点名、聚焦三个渠道各固定七组到达序列，覆盖图片后补文字、同一人续发、
换人、纯图片和等待上限。它从已存在的唤醒机会开始，按逻辑时钟输入 OneBot 事件，读取实际合批截止时间，
输出切断批次数和各渠道等待中位数。这一项按默认等待设置量合批，完整首句延迟仍由 `report` 读取回合记录。

`jargon.json` 固定了十个虚构群内用法和十个普通词。黑话模式执行一遍固定候选，含义任务按现有的五词一批使用实际整理工作者，输出结果、自动拒绝计数及完整请求响应：

```sh
uv run --no-sync python scripts/compare_social.py --instance . --label jargon-baseline --jargon
```

专项对照可用 `--cases <文件>` 指向 set 为 `social` 的固定用例或子集，用 `--repetitions <次数>` 指定重复次数；`--persona <目录>` 选择试验角色。每次运行保存实际用例和角色快照。
