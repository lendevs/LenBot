# 数据与迁移

## KV 和数据目录

每个插件有独立的数据目录 `ctx.data_dir`（默认在实例的 `plugins/.data/<name>`）和存在其中的 KV：

```python
count = await ctx.get_kv(ctx.scene, 0)
await ctx.set_kv(ctx.scene, count + 1)
await ctx.delete_kv(ctx.scene)
```

- 值是 JSON 值。KV 只按插件隔离，按群区分时把 `scene` 放进键名。
- 较大的文件直接写在 `ctx.data_dir` 下。
- 停用、卸载和换版本都保留数据；删除数据是插件停止后在面板上的单独操作。

## 数据版本

改变数据目录或 KV 的结构时，提高清单中的 `data_version`，并实现 `migrate_data`：

```python
class Notes(Plugin):
    async def migrate_data(self, from_version: int) -> None:
        if from_version < 2:
            legacy = self.ctx.data_dir / "notes.txt"
            if legacy.exists():
                await self.ctx.set_kv("notes", legacy.read_text(encoding="utf-8").splitlines())
                legacy.unlink()
```

清单中的 `data_version` 高于已有数据的版本时，宿主在 `start()` 之前：

1. 把整个数据目录复制到 `plugins/.data/.backups/<name>-v<旧版本>-<时间>`。
2. 调用 `migrate_data(from_version)`。此时可以读写 `ctx.data_dir` 和 KV，还没有调用 `start()`。
3. 成功后记下新的版本号再启动插件；抛出异常时把数据目录恢复到迁移前，插件标记为失败。

一次迁移要能从任何支持的旧版本升到当前版本，按 `from_version` 依次处理。提高了 `data_version` 却没有实现 `migrate_data` 时直接失败。清单中的 `data_version` 低于已有数据时宿主拒绝启动，因为旧版插件不读新格式的数据；回退到旧版时需要同时从 `.backups` 恢复对应的数据。

新版本在加载、启动或迁移时失败，宿主自动回到上一版本的源码和参数；已经迁移过的数据恢复为迁移前的备份。

测试迁移的方法见[测试与发行](plugin-testing)。
