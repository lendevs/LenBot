# 部署包与 Docker 安装

部署包由 CI 的 `release-packages` 产物提供。候选镜像来自 Release 工作流的 `publish=false` 构建：每个架构分别提供 `image-host-*`、`image-worker-*` 和 `image-updater-*`。选择与运行机器一致的架构，将同一次构建的包和镜像放在一起使用。

以下以 `0.2.0` 为例。公开版本发布后，也可从对应 Release 下载部署包、按同一版本号拉取镜像。

## Linux 与 macOS 部署包

准备 [uv](https://docs.astral.sh/uv/)。Linux 下载 `lenbot-0.2.0-linux.tar.gz`，macOS 下载 `lenbot-0.2.0-macos.tar.gz`。以 macOS 为例：

```sh
tar -xzf lenbot-0.2.0-macos.tar.gz
cd lenbot-0.2.0-macos
./install.sh install "$HOME/lenbot"
"$HOME/lenbot/run"
```

Linux 使用对应的文件名和解压目录，安装命令相同。安装器下载 Python 3.13 和锁定的依赖，安装到新目录；目标目录由安装器创建。首次启动输出向导链接，按[首次配置](https://lendevs.github.io/LenBot/start/first-setup)填写后进入面板。

## Windows 部署包

准备 uv，解压 `lenbot-0.2.0-windows.zip`，在解压目录中打开 PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 install "$env:USERPROFILE\lenbot"
& "$env:USERPROFILE\lenbot\run.cmd"
```

Windows 的安装脚本创建 `run.cmd` 和 `run.ps1`。首次启动后按终端中的链接完成向导。

## 部署包目录与维护

| 目录或入口 | 用途 |
|---|---|
| `instance/` | 配置、数据库、角色、插件和运行数据 |
| `releases/` | 各版本的程序与 Python 环境 |
| `control/` | 更新器及其 Python 环境 |
| `logs/` | 更新器和子进程日志 |
| `run` / `run.cmd` | 启动更新器和 Bot |

日常设置在面板修改。版本发布后，在**系统 → 版本与更新**执行更新、查看快照和恢复。安装或启动失败时先查看终端错误和 `logs/`；模型与群聊问题见[日志与排查](https://lendevs.github.io/LenBot/use/logs)。

## Docker

准备 Docker Engine 或 Docker Desktop，以及 Compose v2。QQ 协议端需提供一个容器可以访问的 OneBot 地址。

### 1. 准备同版本镜像

从候选构建下载当前架构的 host 和 updater 产物，分别解压其中的 `image.tar`，然后载入：

```sh
docker load -i image-host-arm64/image.tar
docker load -i image-updater-arm64/image.tar
docker tag ghcr.io/lendevs/lenbot:0.2.0-arm64 ghcr.io/lendevs/lenbot:0.2.0
docker tag ghcr.io/lendevs/lenbot-updater:0.2.0-arm64 ghcr.io/lendevs/lenbot-updater:0.2.0
```

amd64 机器把上述 `arm64` 换成 `amd64`。启用后台任务时，另外载入同版本 worker 镜像。公开镜像发布后，直接拉取版本标签即可。

### 2. 创建部署目录

下面的命令在 Linux 或 macOS 终端执行：

```sh
mkdir lenbot-deployment
cd lenbot-deployment
docker run --rm --entrypoint python \
  -v "$PWD:/deployment" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/lendevs/lenbot-updater:0.2.0 \
  /opt/lenbot-updater/init.py --version 0.2.0
```

命令创建 Compose 文件、`lenbot-data` 数据卷和该版本的 Python 环境卷。`--project` 可指定实例名，`--panel-port` 和 `--update-port` 可调整面板与更新器的宿主端口。

### 3. 启动并完成首次配置

```sh
docker compose -p lenbot -f host.compose.yaml -f host.version.compose.yaml \
  -f host.updater.compose.yaml up -d
docker compose -p lenbot -f host.compose.yaml -f host.version.compose.yaml \
  -f host.updater.compose.yaml logs lenbot
```

日志中的 `http://127.0.0.1:11307/#token=...` 是首次配置链接，在浏览器中打开后按[首次配置](https://lendevs.github.io/LenBot/start/first-setup)填写向导。容器内的面板固定使用 `11307`，向导中的端口不可修改；`--panel-port` 改过宿主端口时，把链接中的端口换成该值。容器里的 `127.0.0.1` 指容器自己，协议端或模型服务运行在同一台机器上时，地址里的主机写 `host.docker.internal`，例如 `ws://host.docker.internal:3001`、`http://host.docker.internal:8317/v1`；向导在容器中默认填写前者，部署配方在 Linux 上也提供这个主机名。使用反向 WebSocket 时，在 `host.compose.yaml` 发布对应监听端口。保存后页面跳转到登录页。配置保存在数据卷内的 `lenbot.config.json`。

远程部署可用 SSH 转发面板端口；后台任务的额外挂载见[任务存储](task-storage.md)。

### 无交互初始化

不使用浏览器时，可用 JSON 初始化。把部署包中的 `deploy/current/first-setup.example.json` 复制为 `setup.json` 并填写，保持 `panel_host` 为 `0.0.0.0`、`panel_port` 为 `11307`，在 `up -d` 之前执行：

```sh
docker compose -p lenbot -f host.compose.yaml -f host.version.compose.yaml \
  run --rm --no-deps -T --entrypoint /opt/lenbot/.venv/bin/python \
  lenbot -m len_bot.next.maintenance.initialize < setup.json
```

初始化后删除包含初始密码和模型密钥的 `setup.json`。

排查启动问题：

```sh
docker compose -p lenbot -f host.compose.yaml -f host.version.compose.yaml \
  -f host.updater.compose.yaml logs --tail 80
```

面板运行在 `11307`，更新器的恢复入口为 `http://127.0.0.1:11308`。更新与恢复的实例状态由部署目录中的更新器保存。
