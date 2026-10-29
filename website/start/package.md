# 部署包

部署包内含预构建的网页面板和锁定的依赖，本机只需要 [uv](https://docs.astral.sh/uv/)。安装器下载 Python 3.13 和依赖，安装到一个新目录。

从 [Releases](https://github.com/lendevs/LenBot/releases/latest) 下载与系统对应的文件，下文以 `0.2.0` 为例：

| 系统 | 文件 |
|---|---|
| Linux | `lenbot-0.2.0-linux.tar.gz` |
| macOS | `lenbot-0.2.0-macos.tar.gz` |
| Windows | `lenbot-0.2.0-windows.zip` |

## Linux 与 macOS

```sh
tar -xzf lenbot-0.2.0-macos.tar.gz
cd lenbot-0.2.0-macos
./install.sh install "$HOME/lenbot"
"$HOME/lenbot/run"
```

Linux 换成对应的文件名和解压目录，命令相同。目标目录由安装器创建。

## Windows

解压 `lenbot-0.2.0-windows.zip`，在解压目录中打开 PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 install "$env:USERPROFILE\lenbot"
& "$env:USERPROFILE\lenbot\run.cmd"
```

安装脚本创建 `run.cmd` 和 `run.ps1`，两者都可启动。

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
| `releases/` | 各版本的程序与 Python 环境 |
| `control/` | 更新器及其 Python 环境 |
| `logs/` | 更新器和子进程日志 |
| `run` / `run.cmd` | 启动更新器和 Bot |

## 更新与恢复

在面板**系统 → 设置 → 版本与更新**中执行更新、查看快照和恢复，详见[更新与备份](../use/maintenance#部署包与-docker-实例)。作为系统服务运行的方法见[作为系统后台服务运行](../use/maintenance#作为系统后台服务运行)。

## 排查

安装或启动失败时，先看终端错误和 `logs/`。模型与群聊的问题见[日志与排查](../use/logs)。
