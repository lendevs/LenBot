# 更新与备份

本页说明源码、部署包与 Docker 实例的版本更新、完整备份、数据清理、隔离测试副本以及系统后台服务托管。

## 更新代码

### 从源码运行的实例

先在运行终端按 `Ctrl+C`（或通过 `systemctl stop lenbot`）正常停止实例，再依次拉取代码、同步依赖并执行带快照的升级检查：

```sh
git pull
./scripts/install.sh
uv run --no-sync python -m len_bot.next.maintenance.upgrade run --snapshot ../lenbot-backup-20261029
uv run --no-sync len-bot
```

`upgrade run` 会先将当前实例运行数据与配置中引用的外部目录完整备份到 `--snapshot` 指定的新目录（必须位于实例目录及外部数据目录之外），随后执行格式迁移、恢复已安装插件的 Python 依赖并运行 `doctor` 校验；任一环节报错都会自动从该快照回滚。

升级后如需手动回退到旧版本，先停止新进程，恢复升级前快照，再切回旧提交并同步环境：

```sh
uv run --no-sync python -m len_bot.next.maintenance.upgrade restore --snapshot ../lenbot-backup-20261029
```

仅需在重建虚拟环境后补齐已安装插件的第三方 Python 依赖时，可停机单独执行：

```sh
uv run --no-sync python -m len_bot.next.maintenance.plugin_dependencies
```

### 部署包与 Docker 实例

在面板**系统 → 设置 → 版本与更新**点击**更新到 <版本>**，页面依次显示下载、安装和重启，完成后自动刷新：

1. 运行中的 LenBot 下载新版本并校验：部署包下载对应平台的部署包，解压到 `releases/<版本>/`；Docker 下载新版本的 wheel 和锁定的依赖，安装到数据卷的 `/data/runtime/<版本>/`。这一步 Bot 照常工作。
2. LenBot 退出，启动器把实例保存到 `backups/<时间>-<编号>`，用新版本迁移数据并安装插件依赖，然后启动新版本。
3. 新版本在 2 分钟内就绪即完成；没有就绪时，启动器恢复快照、回到原来的版本，页面显示原因。
4. 开启**同时更新插件**时，新版本运行后把已安装的插件更新到插件目录中的最新兼容版本，结果显示在同一页。

部署目录保留当前和上一个版本，以及最近两份快照。**更新快照**中点击**恢复**，LenBot 重启并回到快照时的程序和数据。新版本每隔几小时自动检查一次，有新版本时顶栏和侧栏显示提醒；在根配置中把 `panel.update_check` 设为 `false` 关闭自动检查。

宿主进程与所有 `maintenance` 维护命令共用单实例文件锁 `.lenbot-instance.lock`，同一时刻只有一个进程读写数据库。

## 手动备份与数据保留

### 完整备份范围

在**已停止** LenBot 的状态下复制以下内容即可获得一致性完整备份：

- **实例运行文件**：`lenbot.config.json`、SQLite 主数据库及旁边的 `.memory.sqlite3`（若尚未完全合并还需连同 `-wal`、`-shm` 文件一并复制，正常停机后 WAL 已落盘）、`state/`、`personas/`、`plugins/` 和 `logs/`。
- **外部引用路径**：`lenbot.config.json` 中指向实例目录以外的角色目录、插件目录或后台任务的工作区、运行目录与交付目录。

`lenbot.config.json` 内含模型 API Key、OneBot 令牌和面板密码哈希，备份归档需按敏感凭据妥善保管。恢复备份时须使用生成该备份时的同版本（或兼容格式版本）代码启动。

### 自动清理过期记录

在**系统 → 设置 → 数据保留**中可配置自动清理旧数据的保留天数（修改后立即生效，也可点击**清理一批**立即执行）：

- **模型请求记录保留**：控制聊天、学习、记忆整理与后台任务的原始请求／响应快照保留天数，清理后不影响 `usage` 表中的历史 token 统计。
- **回复记录保留**：控制旧回合步骤记录的保留天数。
- **聊天原文保留**：可选**永久**或指定天数；清理过期聊天原文时会自动跳过后台记忆整理（或当前启用的记忆插件）尚未处理完的消息。

## 导出隔离测试副本

需要在不影响线上群聊的前提下用真实历史数据验证新设置、新角色或新插件时，先停止实例再执行 `test_copy`：

```sh
uv run --no-sync python -m len_bot.next.maintenance.test_copy . /tmp/lenbot-test --panel-port 8089
cd /tmp/lenbot-test && uv run --project /path/to/LenBot --no-sync len-bot
```

命令会将配置及其引用的数据库、记忆、资料、角色与任务目录复制到目标位置，自动将副本切换为**模拟发送**、断开 OneBot 连接（`onebot: null`）、绑定指定的面板端口，并把原实例内的绝对路径重写为副本路径。副本中的模型、插件和后台任务按原配置连接运行。

## 作为系统后台服务运行

`len-bot` 作为前台启动器运行，收到 `SIGINT`（`Ctrl+C`）或 `SIGTERM` 时优雅等待当前回合收尾后退出；面板内的**重启 LenBot** 由启动器进程自行拉起新子进程完成，因此外部服务管理器无需配置崩溃无限重启。部署包用目录中的 `service` 或 `service.ps1` 注册，见[部署包](../start/package#后台服务)；下面是从源码运行时的做法。

- **Linux（`systemd`）**：仓库提供 [`deploy/current/lenbot.service`](https://github.com/lendevs/LenBot/blob/master/deploy/current/lenbot.service) 单元模板（默认 `Restart=no` 并启用文件系统沙箱保护）。按机器实际路径修改 `User`、`Group`、`WorkingDirectory`、`ExecStart` 及 `ReadWritePaths`（必须覆盖实例目录及位于实例外的任务目录）后安装：
  ```sh
  sudo install -m 0644 deploy/current/lenbot.service /etc/systemd/system/lenbot.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now lenbot
  sudo journalctl -u lenbot -n 100 --no-pager
  ```
- **macOS**：可直接双击 [`deploy/current/start.command`](https://github.com/lendevs/LenBot/blob/master/deploy/current/start.command) 在终端窗口中启动。
