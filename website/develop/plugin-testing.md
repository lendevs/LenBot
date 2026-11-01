# 测试与发行

## PluginTest

`len_bot.plugin_testing.PluginTest` 把插件复制到临时实例里运行，使用真实的生命周期、配置校验、规则匹配、工具校验和磁盘上的 KV，不需要 OneBot、面板或任务环境。发送只记录为 `simulated`。

```python
from pathlib import Path
import pytest
from len_bot.plugin_testing import PluginTest


@pytest.mark.asyncio
async def test_increment():
    async with PluginTest(Path(__file__).parents[1], config={"step": 2}) as bot:
        assert await bot.message("计数加一")
        assert bot.deliveries[-1].text == "本群计数：2"
        assert "2" in await bot.tool("counter_read", {})
```

| 方法 | 用途 |
|---|---|
| `PluginTest(package, config=..., scenes=..., owners=..., now=...)` | 构造临时实例；`scenes` 默认 `("onebot:group:80001",)`，`now` 固定时钟 |
| `message(text, scene=..., sender=..., parts=...)` | 发一条消息，返回是否被插件接管；`parts` 追加 `Segment`，用于测试提及和媒体 |
| `notice(notice_type, sub_type=..., user=..., scene=...)` | 发一条通知，返回运行的处理器数 |
| `tool(name, arguments, scene=...)` | 经真实的调用边界调用工具，返回模型收到的字符串 |
| `preview_tools(scene)` | 模型看到的简介、说明、schema、共享指南和不可用原因 |
| `add_message(...)`、`new_turn(scene)` | 存一条消息（返回带 `platform_message_id` 的消息，用于 `needs_source` 工具）、开始下一轮 |
| `recall(...)`、`memory(...)`、`compact(...)` | 调用记忆插件的三个入口 |
| `wait_tasks(name_prefix)` | 等 `start_task` 登记的一次性任务完成 |
| `deliveries`、`events()` | 插件发出的内容、记录的插件事件 |

- 处理器停在 `wait_message` 时 `message` 立即返回，下一次 `message` 作为回答，并等处理器继续执行完。
- 处理器或启动出错时测试报错。
- 模型默认关闭，`ctx.generate` 会报错。传 `models={...}` 指向本机的模拟服务时，生成走真实的宿主协议和用量记录。记忆服务和任务服务在测试中不可用。
- 插件自己的网络访问照常执行。
- 测试数据迁移：`PluginTest(package, data=Path("tests/data-v1"), data_version=1)` 进入时先运行 `migrate_data` 再调用 `start()`。

## CI 与发行

模板仓库的两个工作流调用 LenBot 提供的可复用工作流：

- `plugin-ci.yml`：安装宿主的 `master`（或用 `host_ref` 指定的版本）和插件的依赖，运行插件测试，并检查发行 ZIP 能否打包。测试需要系统软件时用 `apt_packages` 传入。
- `plugin-release.yml`：推送 `v<版本>` 标签时，核对标签与 `plugin.toml` 的版本一致，把运行源码、`prompts/`、`skills/`、`assets/` 和许可文件打包成可导入的 ZIP 附在 Release 上，发行说明取自 `CHANGELOG.md` 中 `# X.Y.Z` 一节。

打包只取 Git 已跟踪的文件，新增的文件先加入 Git。本机打包：

```sh
uv run --no-project --python 3.13 python ../LenBot/scripts/package_plugin.py . /tmp/plugin.zip
```

每次发行前更新 `version`、`requires_lenbot` 和 `CHANGELOG.md`。使用了新接口时，把 `requires_lenbot` 的下限提高到提供这个接口的宿主版本。

## 许可证

LenBot 宿主采用 AGPL-3.0-only，插件模板采用 GPL-3.0-only。插件和宿主运行在同一个进程中，推荐插件使用 GPL-3.0；GPLv3 第 13 条允许 GPLv3 作品与 AGPLv3 作品组合使用。改用其他许可证前确认它与 GPLv3、AGPLv3 兼容。
