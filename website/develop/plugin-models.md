# 模型调用与后台任务

插件处理一件事有三种做法，按需要选择：

```python
# 普通查询：直接用 Python 处理和发送。
await ctx.reply("今天的订阅内容")

# 单次模型生成：插件给出完整的提示，拿到文字后自己发送。
text = await ctx.generate("待处理的资料", role="mind", system="本次整理要求")
await ctx.reply(text)

# 长工作或文件：交给后台任务，以触发消息的发送者作为请求人。
await ctx.delegate("整理刚才的活动", "CSV 文件", context="实际活动记录")
```

## 单次生成

`ctx.generate(prompt, role="mind", system=None)` 做一次不带工具的模型生成，返回文字，不会唤醒聊天或自动发送。`role` 是 `mind` 或 `learner`，没有单独配置 `learner` 时用 `mind` 的绑定。调用计入实例的模型用量和每日上限，用量记录里标明来自哪个插件。需要 `generate` 权限；`self.ctx.generate(scene, ...)` 要先传入群。

## 委派后台任务

`ctx.delegate(goal, deliverable, context="", materials=())` 以触发这次调用的真实发送者为请求人，把工作交给后台任务，`materials` 是本群共享资料的文件名。返回值表示任务已接受，结果由宿主送回群里，不要轮询等待。

- 需要实例启用后台任务，请求人有任务权限，并且插件声明 `delegate` 权限。
- 只能在有真实触发消息的调用中使用：命令、规则和 `needs_source=True` 的工具。通知、定点任务和没有来源的工具不能委派。

## 定点任务

在 `start()` 中登记，处理器收到的 `ctx` 没有触发消息：

```python
async def start(self) -> None:
    for scene in self.ctx.scenes:
        self.ctx.cron("日报", "0 8 * * *", self.publish, scene=scene, timezone=self.ctx.timezone(scene))

async def publish(self, ctx: Invocation) -> None:
    await ctx.reply("早上好，这是今天的日报")
```

- 五段式 cron 和明确的 IANA 时区，同一插件同一群中任务名唯一。需要 `schedule` 权限。
- 登记只在本次运行中有效。重启后从当前时间算下一次，停机期间错过的次数不补。
- 单次执行失败时记录错误，下一次照常执行。

## 后台循环和自建任务

`@background(every="5m")` 标记的方法在上一轮执行完后等一个间隔再执行，最短 10 秒，适合轮询外部服务：

```python
@background(every="5m")
async def poll(self, ctx: PluginContext) -> None:
    for scene in ctx.scenes:
        ...
```

插件自己的长期协程用 `self.ctx.start_task(name, coroutine)` 登记，插件停止时宿主取消它们。不要在主循环里做阻塞的网络请求。

`self.ctx.scenes` 是启用了插件且聊天开着的群；管理员在面板关掉某个群的聊天后，插件的命令和通知不再分发到这个群，向它发送会报错。

## 生命周期

- `start()` 在平台连接就绪后调用一次，限时 60 秒；耗时的准备（等待网络、预热缓存）放进 `start_task`。
- `stop()` 在宿主停止或插件重新加载时调用，限时 30 秒，此前后台循环和自建任务已经取消。
- 超时会被取消并记为插件错误，宿主的其他部分照常运行。

## 插件技能

插件可以带 `skills/<技能名>/SKILL.md` 和相关资源。启用了这个插件的群里，后台任务可以按角色的技能许可使用这些技能，技能目录以只读方式挂载。
