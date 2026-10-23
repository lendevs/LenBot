# 更新与备份

## 更新代码

更新代码后，按以下步骤执行迁移。

```sh
# 先按 Ctrl-C 停止 LenBot
git pull
./scripts/install.sh
uv run --no-sync python -m len_bot.next.maintenance.migrate_config
uv run --no-sync python -m len_bot.next.maintenance.migrate
uv run --no-sync python -m len_bot.next.maintenance.migrate_memory_jobs
uv run --no-sync python -m len_bot.next.maintenance.migrate_local_memory
uv run --no-sync python -m len_bot.next.maintenance.plugin_dependencies
uv run --no-sync python -m len_bot.next.maintenance.doctor
uv run --no-sync len-bot
```

| 命令 | 作用 |
|---|---|
| `migrate_config` | 升级根配置。必须在数据库升级之前执行 |
| `migrate` | 升级业务数据库 |
| `migrate_memory_jobs` | 升级记忆处理库 |
| `migrate_local_memory` | 升级本地记忆索引 |
| `plugin_dependencies` | 恢复已安装插件的依赖 |
| `doctor` | 检查升级结果，全部为 `ok` 或 `disabled` 后再启动 |

升级前请先[备份](#备份)。

- 数据库迁移在数据库旁边保留一份升级前的副本，例如 `state.db.v2.bak`。确认运行正常后可以删除。同名副本已存在时命令拒绝执行。
- 每一步升级在一个事务中完成，中途失败时数据停留在上一个完整的格式。
- 跳过 `migrate_config` 直接启动时，LenBot 停止运行并报告配置格式过旧，同时给出需要执行的命令。

所有命令和程序运行共用实例锁 `.lenbot-instance.lock`，同一时间只能运行一个。不要手动删除锁文件。

## 备份

停止 LenBot 后备份以下内容：

- **实例目录**：从源码运行时是仓库根目录中被 `.gitignore` 排除的运行文件，包括 `lenbot.config.json`、数据库、`state/`、`personas/`、`plugins/` 和 `logs/`。
- **实例以外的目录**：配置中指向实例以外的角色目录、插件目录，以及后台任务的工作目录、运行目录和交付目录。

数据库旁边的 `-wal` 和 `-shm` 文件也属于数据，需要一起备份。LenBot 运行期间复制的数据库可能前后不一致，因此必须先停止。

`lenbot.config.json` 中有模型服务、OneBot 和面板的密钥，备份文件需要按密钥的标准保管。

恢复时把备份放回原位置，使用备份时的同一个代码版本启动。旧版本的程序不能读取新版本的数据。

## 测试副本

不希望改动正在使用的数据时，停止 LenBot 后复制一份测试实例：

```sh
uv run --no-sync python -m len_bot.next.maintenance.test_copy . /tmp/lenbot-test --panel-port 8089
cd /tmp/lenbot-test && uv run --project /path/to/LenBot --no-sync len-bot
```

命令复制配置和配置中引用到的实例文件。副本改为模拟发送，不连接 OneBot 或 Telegram，面板使用指定的端口，指向原实例内部的绝对路径改为指向副本。模型、插件和后台任务在副本中正常运行，模型调用同样消耗 token。

## 作为系统服务运行

`len-bot` 是前台进程，按 Ctrl-C 停止。面板中的重启由进程自身完成，服务管理器只需要启动它，不需要在退出后自动重启。

Linux 上可以使用仓库中的 [systemd 模板](https://github.com/lendevs/LenBot/blob/master/deploy/current/lenbot.service)。使用前按实际情况修改 `User`、`Group`、`WorkingDirectory`、`ExecStart` 和 `ReadWritePaths`。`ReadWritePaths` 必须包含实例目录，以及配置中位于实例以外的任务目录。

```sh
sudo install -m 0644 deploy/current/lenbot.service /etc/systemd/system/lenbot.service
sudo systemctl daemon-reload
sudo systemctl start lenbot
sudo journalctl -u lenbot -n 100 --no-pager
```

模板设置了 `Restart=no`。需要开机自启时执行 `systemctl enable lenbot`。

macOS 上可以双击 `deploy/current/start.command` 启动。
