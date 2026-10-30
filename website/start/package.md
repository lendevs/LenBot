# 部署包

部署包内含 Python 3.13、锁定的依赖和预构建的网页面板，解压后直接启动，本机不需要另外安装 Python 或 uv。Linux 部署包还带有后台任务的本机沙箱运行时。macOS 使用 [Docker 部署](./docker)。

从 [Releases](https://github.com/lendevs/LenBot/releases/tag/v0.2.0rc1) 下载与系统对应的文件，下文以 `0.2.0rc1` 为例：

| 系统 | 文件 |
|---|---|
| Linux x64 | `lenbot-0.2.0rc1-linux-x64.tar.gz` |
| Linux arm64 | `lenbot-0.2.0rc1-linux-arm64.tar.gz` |
| Windows x64 | `lenbot-0.2.0rc1-windows-x64.zip` |

解压出的目录就是部署目录，配置和数据都写在里面，可以先改名或移到常用位置再启动。

## Linux

```sh
tar -xzf lenbot-0.2.0rc1-linux-x64.tar.gz
mv lenbot-0.2.0rc1-linux-x64 ~/lenbot
~/lenbot/run
```

arm64 换成对应的文件名。部署包适用于 glibc 2.28 及以上的发行版，例如 Debian 10、Ubuntu 20.04、RHEL 8 及更新版本。

## Windows

解压 `lenbot-0.2.0rc1-windows-x64.zip`，双击目录中的 `run.cmd`，或在 PowerShell 中执行：

```powershell
.\run.cmd
```

部署包没有代码签名。解压前在 zip 文件上右键 → **属性**，勾选**解除锁定**，解压出的文件就不再触发下载文件的安全提示；直接解压时，SmartScreen 显示**已保护你的电脑**后点击**更多信息 → 仍要运行**。

## 首次配置

首次启动时，终端输出一次性配置链接：

```text
尚无根配置。请打开 http://127.0.0.1:52811/#token=...
```

在本机桌面终端启动时浏览器自动打开该链接。按[首次配置](./first-setup)填写向导，保存后进入面板，面板默认地址为 `http://127.0.0.1:8088`。

## 目录

| 目录或入口 | 用途 |
|---|---|
| `instance/` | 配置、数据库、角色、插件和运行数据 |
| `releases/<版本>/` | 该版本的 Python、程序、更新器和任务运行时 |
| `backups/` | 更换版本前的快照 |
| `updates/` | 更新器日志 |
| `current.json` | 当前使用的版本 |
| `run`、`run.cmd` | 启动更新器和 Bot |
| `service`、`service.ps1` | 注册为登录后自动启动的后台服务 |

## 后台任务

Linux 部署包默认用本机沙箱（bubblewrap）运行后台任务，需要系统安装 `bwrap`，例如 Debian 和 Ubuntu 上执行 `sudo apt install bubblewrap`。Windows 部署包用 Docker 任务容器，需要 Docker Desktop。启用步骤和联网方式见[后台任务](../use/tasks)。

## 后台服务

Linux 注册为 systemd 用户服务：

```sh
~/lenbot/service install
~/lenbot/service start
~/lenbot/service status
```

服务在登录后启动；需要开机即运行、不依赖登录时，执行一次 `sudo loginctl enable-linger $USER`。`service stop` 停止，`service uninstall` 移除。

Windows 注册为登录后运行的计划任务，在部署目录的 PowerShell 中执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\service.ps1 install
powershell -NoProfile -ExecutionPolicy Bypass -File .\service.ps1 start
```

`stop` 停止 Bot，`status` 查看计划任务状态，`uninstall` 移除。

## 更新与恢复

在面板**系统 → 设置 → 版本与更新**中执行更新、查看快照和恢复，详见[更新与备份](../use/maintenance#部署包与-docker-实例)。新版本解压到 `releases/<新版本>/`，更换前的实例保存在 `backups/`，旧版本目录保留，恢复快照时切回它。

## 排查

安装或启动失败时，先看终端错误和 `updates/updater.log`。模型与群聊的问题见[日志与排查](../use/logs)。
