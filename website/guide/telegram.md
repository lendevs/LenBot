# 接入 Telegram

LenBot 也可以作为 Telegram Bot 运行。它通过 Bot API 的长轮询收消息，不需要公网地址，也不需要额外的转发程序。同一个实例只能接一个平台：填写了 `telegram` 就不能再填写 `onebot`。

面板的首次配置向导目前只支持 QQ，接入 Telegram 需要手动编辑 `lenbot.config.json`。

## 准备 Bot

1. 在 Telegram 中找到 @BotFather，发送 `/newbot` 创建 Bot，得到形如 `123456789:AA…` 的令牌。冒号前面的数字就是 Bot 的账号。
2. 要让 Bot 看到群里的普通消息，在 @BotFather 中用 `/setprivacy` 把隐私模式设为 Disable，然后把 Bot 拉进群。隐私模式开启时，Bot 只能收到命令、提及和对它的回复。
3. 群的 ID 是负数，例如 `-1001234567890`。还没有写进 `scenes` 的群，LenBot 只记一条日志，不会回复，`/id` 在这时也不会回答。可以先按下面的配置启动，把 Bot 拉进群发一条 `/id`（隐私模式开启时 Bot 只能收到命令），然后在面板的**系统 → 日志 → 系统日志**中找事件名为 `receipt`、`status` 为 `ignored` 的记录，其中的 `scene` 就是这个群的写法。写进 `scenes` 并重启后，`/id` 会直接回复场景和账号。

## 配置

```json
{
  "bot_id": "telegram:123456789",
  "delivery": "telegram",
  "owners": ["telegram:10001"],
  "telegram": {"bot_token": "123456789:AA…"},
  "scenes": {"telegram:group:-1001234567890": {"persona": "personas/default"}}
}
```

- `bot_id` 写成 `telegram:` 加 Bot 的数字账号。启动时 LenBot 会用令牌读取 Bot 信息，账号不一致时拒绝启动。
- 账号写成 `telegram:用户数字ID`，场景写成 `telegram:group:群ID` 或 `telegram:private:用户ID`。
- `delivery` 为 `telegram` 时才会真正发送；改为 `simulated` 可以只收不发，用来观察。
- 可选项：`api_base` 指向自建的 Bot API 服务或反向代理，`poll_timeout_seconds`（默认 25，最大 50）是每次长轮询在服务端等待的秒数，`request_timeout_seconds`（默认 15）是其他请求的超时。

令牌和 QQ 的访问令牌一样不会写进日志。

## 与 QQ 的差别

- 文字、提及和回复引用可以收发，Bot 可以发送图片（每条一张）。收到的图片、表情、语音、视频和文件以 `[图片]` 这类占位文字进入上下文，模型看不到内容。
- 不能上传群文件，相关工具会报告不支持。
- Telegram 的消息里没有群主和群管理员身份。按群角色开放的群命令（`/status`、`/quiet`、`/resume`，以及打开 `commands.group_managers_chat_reset` 后的 `/chat` 和 `/reset`）在 Telegram 上只有主人和全局管理员可以使用；需要时把群管理员的账号加进全局管理员，或者在**群聊 → 设置 → 权限**的「谁可以让 Bot 暂时安静」中加上白名单，再把账号加进白名单（只管 `/status`、`/quiet` 和 `/resume`）。`/model` 和 `/limit` 本来就只给主人和全局管理员。
- 群里有多个 Bot 时，命令可以写成 `/status@你的Bot用户名`，与 `/status` 相同，并算作 @ 了 Bot。写给其他 Bot 的命令（`@` 后面是别的用户名）不由 LenBot 处理，照常作为普通消息。
- 第一次收取消息成功后才算连上。连接断开后自动重试，间隔从 1 秒开始逐步加长，最长 30 秒。令牌失效（401），或者这个 Bot 设置了 webhook、另有程序在收取消息（409）时不再重试，LenBot 记录原始错误后停止，处理好再重启。
