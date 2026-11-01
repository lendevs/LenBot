# 接收消息

插件用装饰器标记入口方法，每个方法只用一个装饰器。

```python
from len_bot.plugin import Invocation, Notice, Plugin, command, fullmatch, on_notice, regex
```

## 命令、全文和正则

| 装饰器 | 方法参数 | 匹配 |
|---|---|---|
| `@command("查询", "说明")` | `self, ctx: Invocation, args: str` | `/查询 参数`，`/查询` 后面的文字作为 `args` |
| `@fullmatch("今日直播", "说明")` | `self, ctx: Invocation` | 去掉首尾空白后与文本完全相同 |
| `@regex(r"查 (?P<name>.+)", "说明", priority=0)` | `self, ctx: Invocation, match` | 整条文字完整匹配，命名组从 `match` 读取 |

- 匹配顺序是命令、全文、正则，正则之间按 `priority` 从高到低。同一条消息最多由一个处理器接管，被接管的消息不唤醒聊天模型，处理结果作为背景进入之后的对话。
- 默认只匹配纯文字：开头的回复段和 @Bot 会被去掉，带图片、语音的消息不匹配。
- 命令可以写 `allow_mentions=True` 接收正文中的提及，例如 `/转发 @某人`。文字参数中提及的位置换成一个空格，被提及的账号从 `ctx.message.segments` 的 `mention` 段读取。全文和正则不接收提及。
- 插件的命令先于宿主命令匹配。注册了 `/角色` 这类与宿主同名的命令时由插件处理。
- 处理器的返回值只作记录。发消息要调用 `ctx.reply`，见[发送消息](plugin-sending)。

部署方可以在根配置的 `plugins.disabled_rules` 里关掉插件的某几条规则，例如 `{"group_digest": ["/群日报"]}`，被关掉的文字按普通聊天处理。

## 通知

```python
@on_notice("group_increase")
async def welcome(self, ctx: Invocation, notice: Notice) -> None:
    await ctx.reply(f"欢迎 {notice.user_id}")
```

`@on_notice` 写通知类型，或类型加子类型（`notify.poke`）。通知只送到启用了这个插件的群。

| 通知 | 写法 |
|---|---|
| 入群、退群 | `group_increase`（`approve`、`invite`）、`group_decrease`（`leave`、`kick`、`kick_me`） |
| 撤回 | `group_recall`、`friend_recall`，`notice.platform_message_id` 是被撤回的消息 |
| 禁言 | `group_ban`（`ban`、`lift_ban`），`notice.duration` 是秒数 |
| 戳一戳 | `notify.poke` |
| 管理员变动、群文件上传 | `group_admin`（`set`、`unset`）、`group_upload` |

OneBot 的通知按原来的 `notice_type` 和 `sub_type` 转发，表中之外的通知同样可以订阅。`Notice` 的 `user_id`、`operator_id` 是带平台前缀的账号，`raw` 是协议端的原始事件。

## 消息结构

`ctx.message` 是触发这次调用的消息（命令和规则一定有，通知和定点任务没有）。

| 字段 | 内容 |
|---|---|
| `scene` | 场景，例如 `onebot:group:80001` |
| `sender` | `uid`（带平台前缀的账号，如 `onebot:70001`）、`nickname`、`card`（群名片）、`role` |
| `platform_message_id` | 平台的消息 ID，回复和引用用它 |
| `time` | Unix 秒 |
| `segments` | 消息段列表 |
| `reply_to` | 被回复消息的平台 ID |
| `mentions_bot`、`is_self` | 是否提及 Bot、是否 Bot 自己发的 |
| `recalled` | 是否已撤回 |

每个消息段有 `type` 和 `data`：

| `type` | `data` |
|---|---|
| `text` | `text` |
| `mention` | `user`：账号，提及全体成员时为 `all` |
| `reply` | `id`：被回复消息的平台 ID |
| `image` | 协议端的图片字段，OneBot 常见 `file`、`url`、`summary` |
| `audio` | 语音字段 |
| `face`、`json`、`forward`、`file`、`video` 等 | 协议端的原始字段 |

要把消息交给模型或写进总结时，用 `message_text` 得到与聊天上下文相同写法的文字，不必逐段拼接：

```python
from len_bot.plugin import message_text

text = message_text(ctx.message, names={"onebot:70002": "小明"})
# 例如：看这个[图片1][提及 小明]
```

图片、语音写成 `[图片1]`、`[语音1]`，提及写成 `[提及 账号]`，`names` 给出的账号换成名字。

读取群里更早的消息用 `ctx.recent_messages(limit=20)`（最多 100 条）和 `ctx.messages_between(after, before, offset=0, limit=200)`（按时间段，每页最多 500 条），需要 `history` 权限。

## 多轮对话

插件提问后，用 `ctx.wait_message` 等同一个人的下一条消息：

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

- `sender` 默认为 `"same"`，等触发这次调用的人；写账号时等这个人，写 `None` 时等群里的任何人。
- 等到的消息由插件接管，不唤醒聊天模型，处理记录进入之后的对话。等待期间这个人发来的下一条消息无论内容都交给插件。
- 超时返回 `None`，`timeout_seconds` 最长 600。同一个群里同一个人同时只能有一个等待。
- 需要 `history` 权限。
