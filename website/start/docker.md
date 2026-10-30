# Docker 部署

宿主镜像 `ghcr.io/lendevs/lenbot` 运行 Bot 和面板，支持 amd64 和 arm64。实例数据保存在一个命名数据卷里，更换版本就是用同一个卷启动新镜像。

下文以 `0.2.0rc1` 为例，该版本见 [Releases](https://github.com/lendevs/LenBot/releases/tag/v0.2.0rc1)，部署其他版本时换成对应的版本号。

## 准备

- Docker Engine 或 Docker Desktop。
- 一个容器可以访问的 OneBot v11 地址，见[接入 QQ](../connect/onebot)。

## 1. 启动

下文的命令在 PowerShell、macOS 和 Linux 终端中写法相同。

```sh
docker run -d --name lenbot --stop-timeout 180 -p 127.0.0.1:11307:11307 -v lenbot-data:/data --add-host host.docker.internal:host-gateway ghcr.io/lendevs/lenbot:0.2.0rc1
docker logs lenbot
```

| 参数 | 用途 |
|---|---|
| `-p 127.0.0.1:11307:11307` | 面板只在本机可访问；改宿主端口时改冒号前的 `11307` |
| `-v lenbot-data:/data` | 数据卷，`/data/instance` 是实例，`/data/backups` 是更换版本前的快照 |
| `--add-host host.docker.internal:host-gateway` | 让容器用 `host.docker.internal` 访问宿主机；Docker Desktop 自带这个主机名 |
| `--stop-timeout 180` | `docker stop` 等待当前回合和后台任务收尾的时间 |

日志中的 `http://127.0.0.1:11307/#token=...` 是首次配置链接，改过宿主端口时把链接中的端口换成该值。需要随 Docker 一起启动时，创建容器时再加 `--restart unless-stopped`。

## 2. 首次配置

在浏览器中打开配置链接，按[首次配置](./first-setup)填写向导。容器中的几处取值：

- 容器内的面板端口固定为 `11307`，向导中的端口不可修改。
- 容器里的 `127.0.0.1` 指容器自己。协议端或模型服务运行在同一台机器上时，主机写 `host.docker.internal`，例如 `ws://host.docker.internal:3001`、`http://host.docker.internal:8317/v1`。向导默认填写前者。
- 使用反向 WebSocket 时，创建容器时用 `-p` 发布对应的监听端口。

保存后页面跳转到登录页，配置保存在数据卷内的 `/data/instance/lenbot.config.json`。远程服务器上可用 SSH 转发面板端口：

```sh
ssh -L 11307:127.0.0.1:11307 你的服务器
```

## 更换版本

拉取新版本镜像，删除当前容器，再用同一个数据卷和原来的参数启动新镜像，命令中的 `<新版本>` 换成要使用的版本号：

```sh
docker pull ghcr.io/lendevs/lenbot:<新版本>
docker stop lenbot
docker rm lenbot
docker run -d --name lenbot --stop-timeout 180 -p 127.0.0.1:11307:11307 -v lenbot-data:/data --add-host host.docker.internal:host-gateway ghcr.io/lendevs/lenbot:<新版本>
```

新镜像第一次启动时，先把实例保存为 `/data/backups/<时间>-<编号>` 快照，再迁移数据格式和插件依赖，日志中会列出快照名。任务镜像是官方 `lenbot-worker` 时，配置随之改为同版本，启用了后台任务时同时执行 `docker pull ghcr.io/lendevs/lenbot-worker:<新版本>`。数据卷由更新的版本用过时，旧镜像拒绝启动并在日志中说明。

### 从快照恢复

回到旧版本时，先用旧版本镜像恢复更换前的快照，再启动旧版本：

```sh
docker stop lenbot
docker rm lenbot
docker run --rm -v lenbot-data:/data --entrypoint ls ghcr.io/lendevs/lenbot:0.2.0rc1 /data/backups
docker run --rm --user 10000:10000 -v lenbot-data:/data --entrypoint /opt/lenbot/.venv/bin/python ghcr.io/lendevs/lenbot:0.2.0rc1 -m len_bot.next.maintenance.upgrade restore --snapshot /data/backups/20261030-140217-cba39904
```

最后一条命令里的快照名换成 `ls` 列出的、更换版本前的那一个。恢复后实例回到快照时的状态，之后写入的消息、记忆和设置修改不保留。然后按第 1 步用 `0.2.0rc1` 镜像启动。

## 后台任务

后台任务在同版本的 `ghcr.io/lendevs/lenbot-worker` 任务容器中运行，由宿主容器通过 Docker socket 创建。启用任务时，创建容器时多挂载一项：

```sh
docker run -d --name lenbot --stop-timeout 180 -p 127.0.0.1:11307:11307 -v lenbot-data:/data -v /var/run/docker.sock:/var/run/docker.sock --add-host host.docker.internal:host-gateway ghcr.io/lendevs/lenbot:0.2.0rc1
```

宿主启动时加入 socket 的所属组，之后以 `10000:10000` 运行。任务目录放在 `lenbot-data` 数据卷内，任务容器按子目录挂载（`volume-subpath`），需要 Docker Engine 26 或更高版本。然后在面板**能力 → 后台任务**中启用，步骤见[后台任务](../use/tasks)。

## 无交互初始化

不使用浏览器时，可用 JSON 初始化。把 [`first-setup.example.json`](https://github.com/lendevs/LenBot/blob/master/deploy/current/first-setup.example.json) 复制为 `setup.json` 并填写，保持 `panel_host` 为 `0.0.0.0`、`panel_port` 为 `11307`，在第 1 步之前执行：

```sh
docker run --rm -i --user 10000:10000 -v lenbot-data:/data --entrypoint /opt/lenbot/.venv/bin/python ghcr.io/lendevs/lenbot:0.2.0rc1 -m len_bot.next.maintenance.initialize < setup.json
```

PowerShell 不支持 `<` 输入重定向，改用管道：

```powershell
Get-Content -Raw setup.json | docker run --rm -i --user 10000:10000 -v lenbot-data:/data --entrypoint /opt/lenbot/.venv/bin/python ghcr.io/lendevs/lenbot:0.2.0rc1 -m len_bot.next.maintenance.initialize
```

初始化后删除 `setup.json`，其中包含初始密码和模型密钥。

## 用更新器管理

希望在面板中切换版本、出错时自动回滚时，可以改用更新器部署。更新器 `lenbot-updater` 用 Docker Compose（v2）管理宿主容器，面板**系统 → 设置 → 版本与更新**里的**打开更新与恢复页**由它提供。在 macOS 或 Linux 终端的一个新目录中执行：

```sh
mkdir lenbot && cd lenbot
docker run --rm --entrypoint python \
  -v "$PWD:/deployment" -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/lendevs/lenbot-updater:0.2.0rc1 /opt/lenbot-updater/init.py --version 0.2.0rc1
docker compose -p lenbot -f host.compose.yaml -f host.version.compose.yaml \
  -f host.updater.compose.yaml up -d
```

| 参数 | 默认值 | 用途 |
|---|---|---|
| `--project` | `lenbot` | 实例名，也是 Compose 项目名和卷名前缀，与 `-p` 保持一致 |
| `--panel-port` | `11307` | 面板在宿主机上的端口 |
| `--update-port` | `11308` | 更新与恢复页在宿主机上的端口 |
| `--registry` | `ghcr` | 镜像仓库，可选 `ghcr` 或 `dockerhub` |

命令创建 `<实例名>-data` 数据卷，布局与上文相同；Compose 配方挂载 Docker socket，后台任务可直接启用。更新与恢复见[更新与备份](../use/maintenance#部署包与-docker-实例)。

## 排查

```sh
docker logs --tail 80 lenbot
```

模型与群聊的问题见[日志与排查](../use/logs)。
