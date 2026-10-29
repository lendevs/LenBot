# Docker 部署

Docker 部署由同版本的三个镜像组成：`lenbot` 运行宿主和面板，`lenbot-updater` 负责更新与恢复，`lenbot-worker` 运行后台任务（按需）。镜像发布在 `ghcr.io/lendevs/`，支持 amd64 和 arm64。

下文以 `0.2.0` 为例，部署时换成 [Releases](https://github.com/lendevs/LenBot/releases/latest) 中的最新版本号。

## 准备

- Docker Engine 或 Docker Desktop，以及 Compose v2。
- 一个容器可以访问的 OneBot v11 地址，见[接入 QQ](../connect/onebot)。

## 1. 创建部署目录

在 Linux 或 macOS 终端执行：

```sh
mkdir lenbot && cd lenbot
docker run --rm --entrypoint python \
  -v "$PWD:/deployment" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/lendevs/lenbot-updater:0.2.0 \
  /opt/lenbot-updater/init.py --version 0.2.0
```

命令在当前目录写入 Compose 文件，并创建 `lenbot-data` 数据卷和该版本的 Python 环境卷。

| 参数 | 默认值 | 用途 |
|---|---|---|
| `--project` | `lenbot` | 实例名，也是 Compose 项目名和卷名前缀 |
| `--panel-port` | `11307` | 面板在宿主机上的端口 |
| `--update-port` | `11308` | 更新与恢复页在宿主机上的端口 |
| `--registry` | `ghcr` | 镜像仓库，可选 `ghcr` 或 `dockerhub` |

## 2. 启动

```sh
docker compose -p lenbot -f host.compose.yaml -f host.version.compose.yaml \
  -f host.updater.compose.yaml up -d
docker compose -p lenbot -f host.compose.yaml -f host.version.compose.yaml \
  -f host.updater.compose.yaml logs lenbot
```

`-p` 与 `--project` 保持一致。日志中的 `http://127.0.0.1:11307/#token=...` 是首次配置链接，用 `--panel-port` 改过端口时，把链接中的端口换成该值。

## 3. 首次配置

在浏览器中打开配置链接，按[首次配置](./first-setup)填写向导。容器中的几处取值：

- 容器内的面板端口固定为 `11307`，向导中的端口不可修改。
- 容器里的 `127.0.0.1` 指容器自己。协议端或模型服务运行在同一台机器上时，主机写 `host.docker.internal`，例如 `ws://host.docker.internal:3001`、`http://host.docker.internal:8317/v1`。向导默认填写前者，部署配方在 Linux 上也提供这个主机名。
- 使用反向 WebSocket 时，在 `host.compose.yaml` 中发布对应的监听端口。

保存后页面跳转到登录页，配置保存在数据卷内的 `lenbot.config.json`。远程服务器上可用 SSH 转发面板端口：

```sh
ssh -L 11307:127.0.0.1:11307 你的服务器
```

## 更新与恢复

在面板**系统 → 设置 → 版本与更新**中查看新版本，点击**打开更新与恢复页**切换版本或从快照恢复。更新器的恢复入口为 `http://127.0.0.1:11308`，实例状态保存在部署目录中，详见[更新与备份](../use/maintenance#部署包与-docker-实例)。

## 后台任务

后台任务使用同版本的 `ghcr.io/lendevs/lenbot-worker` 镜像，启用步骤见[后台任务](../use/tasks)，任务目录的挂载方式见[任务存储](https://github.com/lendevs/LenBot/blob/master/deploy/current/task-storage.md)。

## 无交互初始化

不使用浏览器时，可用 JSON 初始化。把 [`first-setup.example.json`](https://github.com/lendevs/LenBot/blob/master/deploy/current/first-setup.example.json) 复制为 `setup.json` 并填写，保持 `panel_host` 为 `0.0.0.0`、`panel_port` 为 `11307`，在 `up -d` 之前执行：

```sh
docker compose -p lenbot -f host.compose.yaml -f host.version.compose.yaml \
  run --rm --no-deps -T --entrypoint /opt/lenbot/.venv/bin/python \
  lenbot -m len_bot.next.maintenance.initialize < setup.json
```

初始化后删除 `setup.json`，其中包含初始密码和模型密钥。

## 排查

```sh
docker compose -p lenbot -f host.compose.yaml -f host.version.compose.yaml \
  -f host.updater.compose.yaml logs --tail 80
```

模型与群聊的问题见[日志与排查](../use/logs)。
