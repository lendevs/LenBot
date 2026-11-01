# 多平台

LenBot 可以同时接入 QQ（OneBot）、Telegram 和飞书。插件看到的场景和账号都带平台前缀，例如 `onebot:group:80001`、`telegram:group:-1001234`、`feishu:group:oc_xxx`，大多数插件不需要为平台单独处理。

## 平台和 Bot 账号

| 写法 | 内容 |
|---|---|
| `ctx.platform` | 当前场景的平台：`onebot`、`telegram`、`feishu` |
| `ctx.bot_id` | 当前场景里发言的 Bot 账号，例如 Telegram 群中是 `telegram:7001` |
| `self.ctx.bot_for(scene)`、`self.ctx.platform(scene)` | 定点任务、后台循环里按群取 |
| `self.ctx.bot_id` | 根配置的 Bot 账号，只接一个平台时与各群相同 |

判断消息是不是 Bot 自己发的，用 `message.is_self` 或 `message.bot_id`，不要和 `self.ctx.bot_id` 比较。

## 声明支持的平台

只适用于部分平台的插件，在清单中写 `chat_platforms`：

```toml
chat_platforms = ["onebot"]
```

- 值是 `onebot`、`telegram`、`feishu` 中的一个或几个；不写时为全部平台。
- 配置里在其他平台的群启用这个插件时，插件加载失败并说明是哪些群。面板的**使用的群**页签只列出支持的平台的群。
- 插件目录的条目可以写同名字段，在安装前展示；从目录安装时与仓库清单核对，不一致就不准备候选版本。

## 收到的消息

`text`、`mention`、`reply`、`image`、`audio`、`file`、`video` 段在三个平台上都会出现，媒体段的字段各平台不同：

| 平台 | 图片段的 `data` | 其他 |
|---|---|---|
| OneBot | `file`、`url`、`summary`，QQ 表情包的 `sub_type` 不为 0 | `face`、`json`、`forward`、`poke` 等只在 QQ 出现 |
| Telegram | `file_id`、`file_unique_id`；贴纸带 `summary`（对应的 emoji） | 动态贴纸为 `sticker` 段，另有 `poll`、`location` 等 |
| 飞书 | `image_key`、`message_id` | 富文本里的表情转成文字 `[表情名]` |

读取媒体段的文件用 `fetch_media`，平台引用（`file_id`、`image_key`）经平台下载，带 `url` 的段按宿主的公网检查读取：

```python
data = await ctx.fetch_media(segment, max_bytes=10_000_000)
```

只接受 `image`、`audio`、`file`、`video` 段，超过 `max_bytes`（默认 20 MB）时报错。需要 `history` 权限。

把消息交给模型时用 `message_text`，三个平台得到同样写法的文字，见[接收消息](plugin-messages#消息结构)。

## 命令

命令写法在各平台相同。几处平台差异：

- Telegram 群默认开启隐私模式，Bot 只收到命令和回复它的消息，而 Telegram 只把拉丁字母、数字和下划线组成的 `/start` 一类当作命令，`/日程` 这样的中文命令和全文规则都收不到。部署时要在 BotFather 关闭隐私模式（`/setprivacy`）或把 Bot 设为管理员。
- Telegram 的 `/命令@Bot用户名` 写法会去掉后缀再匹配，发给其他 Bot 的命令不匹配。
- 飞书群默认只收到 @机器人的消息，要申请获取群组中所有消息的权限。没有这个权限时，用户要写成 `@Bot /命令`，插件照常接管。

## 通知

| 通知 | OneBot | Telegram | 飞书 |
|---|---|---|---|
| `group_increase`、`group_decrease` | 有 | 有（一次加入多人时只给出第一位，`raw` 保留全部） | 有 |
| `group_recall`、`friend_recall` | 有 | 没有（Bot API 不推送删除） | 有 |
| `group_ban`、`notify.poke` 等其他通知 | 有 | 没有 | 没有 |

## 发送

- `Mention` 的账号必须属于当前场景的平台，例如 Telegram 群里写 `Mention("telegram:502")`，写成其他平台的账号时发送报错。
- `Mention("all")` 在 QQ 和飞书提及全体成员（飞书需要群设置允许）。Telegram 没有全员提醒，这个提及会被省略，其余内容照常发出，`Sent.report` 写明已省略。
- Telegram 单条文字最多 4096 个字符，带图片时说明文字最多 1024 个。更长的内容由适配器拆成多条依次发送，在换行处断开，只有第一条带回复和图片。

## 测试

`PluginTest` 的 `bots` 参数为其他平台的群给出 Bot 账号，`add_media` 登记 `fetch_media` 返回的内容：

```python
scenes = ("onebot:group:80001", "telegram:group:-1001234")
async with PluginTest(package, scenes=scenes, bots={"telegram": "telegram:7001"}) as bot:
    assert await bot.message("/在哪", scene="telegram:group:-1001234", sender="telegram:501")
    bot.add_media("AgACAgQ", photo_bytes)
```
