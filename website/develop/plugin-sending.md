# 发送消息

发送需要 `send` 权限。插件直接发出的内容不经过聊天模型，发送记录进入之后的对话。

## 回复与组合消息

```python
from len_bot.plugin import Image, Mention, Text

await ctx.reply("今天的订阅内容")                       # 命令触发时引用这条命令
await ctx.reply_image(png_bytes, "今日日程卡片")          # 图片和它的内容说明
await ctx.reply_parts([Mention("onebot:70001"), Text(" 轮到你了")])
```

- `Text(text)`、`Image(data, description)`、`Mention(user)` 按顺序组成一条消息。`Mention("all")` 提及全体成员。
- 图片必须给出非空的 `description`。聊天模型之后读到的是这段说明，看不到图片本身，所以写清图片里有什么。
- 文字超过群的单条字数上限时，宿主按顺序拆成多条发送；一条消息里有多张图片时，每张图片另起一条。
- `PluginContext` 上的 `self.ctx.send(scene, text)`、`send_parts(scene, parts)`、`send_image(scene, data, description)` 用于定点任务、后台循环等没有 `ctx` 的地方，`scene` 必须是启用了插件的群。

## 发送回执

发送返回 `Sent`：

| 字段 | 内容 |
|---|---|
| `status` | `sent`（平台已确认）、`failed`、`unconfirmed`（结果未知）、`simulated`（模拟发送）、`partial`（拆成多条时部分成功） |
| `report` | 结果说明 |
| `message_ids` | 平台消息 ID |

只有 `sent` 表示平台已确认。模型工具要返回发送结果时，把这几个字段原样放进返回值，见[模型工具](plugin-tools)。

## 唤醒聊天

`await ctx.emit_event(text)` 把一段文字作为插件事件交给这个群的聊天模型并唤醒它，由角色决定怎么说。它与直接发送不同：适合需要角色接话的场合，例如开播提醒交给角色用自己的口吻转述。需要 `events` 权限。

## 公网图片

`await ctx.fetch_image(url, timeout_seconds=15)` 按宿主的公网地址检查和重定向规则下载图片，校验格式和大小后返回原始字节，可以直接交给 `Image`。需要 `network` 权限。

## 卡片与图片

`len_bot.text_cards` 把文字排成图片卡片，自动换行和分页：

```python
import asyncio
from pathlib import Path
from len_bot.text_cards import CardSection, TextCards

cards = TextCards(Path(self.ctx.config["font_path"]))
pages = await asyncio.to_thread(cards.render, "今日日程", "11 月 1 日",
                                [CardSection("20:00", "直播")], source="示例日历")
for page in pages:
    await ctx.reply_image(page.data, page.text)
```

- `TextCards(font)` 需要字体文件的绝对路径，宿主不附带字体。插件可以把字体放进自己的 `assets/` 一起发行（注意字体许可），或者做成 `path` 类型的配置项。
- `render(title, subtitle, sections, source=...)` 返回 `CardPage` 列表，每页有 PNG 字节 `data` 和这一页的文字 `text`，超过 32 页时报错。`text` 正好作为图片说明。
- `len_bot.image_assets.inspect_image(data)` 校验图片字节，返回 `(MIME 类型, 宽, 高, 是否动图)`；只接受 PNG、JPEG、GIF、WebP，上限 10 MB、2500 万像素，不符合时抛出 `ValueError`。从外部服务取到的图片先校验再发送。
- 排版和绘图占用 CPU，用 `asyncio.to_thread` 调用，避免阻塞聊天。
