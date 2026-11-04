# Docker 部署

宿主镜像 `ghcr.io/lendevs/lenbot` 运行 Bot 和面板，支持 amd64 和 arm64。实例数据保存在一个命名数据卷里，新版本在面板中一键更新。

下文以 `0.2.5` 为例，该版本见 [Releases](https://github.com/lendevs/LenBot/releases/tag/v0.2.5)，部署其他版本时换成对应的版本号。

## 准备

- Docker Engine 或 Docker Desktop。
- 一个容器可以访问的 OneBot v11 地址，见[接入 QQ](../connect/onebot)。

## 1. 启动

下文的命令在 PowerShell、macOS 和 Linux 终端中写法相同。

```sh
docker run -d --name lenbot --stop-timeout 180 -p 127.0.0.1:11307:11307 -v lenbot-data:/data --add-host host.docker.internal:host-gateway ghcr.io/lendevs/lenbot:0.2.5
docker logs lenbot
```

| 参数 | 用途 |
|---|---|
| `-p 127.0.0.1:11307:11307` | 面板只在本机可访问；改宿主端口时改冒号前的 `11307` |
| `-v lenbot-data:/data` | 数据卷，`/data/instance` 是实例，`/data/backups` 是更新前的快照，`/data/runtime` 是面板安装的新版本 |
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

## 更新

在面板**系统 → 设置 → 版本与更新**点击**更新到 <版本>**。面板下载新版本的程序，安装到数据卷的 `/data/runtime/<版本>`，然后重启：先把实例保存为 `/data/backups/<时间>-<编号>` 快照，再迁移数据，启动新版本。新版本没有正常启动时，自动恢复快照并回到原来的版本，页面显示原因。开启**同时更新插件**时，新版本启动后再把已安装的插件更新到插件目录中的最新版本。

更新后容器继续使用原来的镜像启动，启动时选择镜像和数据卷中较新的版本运行。以后用 `docker pull` 换上同版本或更新的镜像时，改用镜像中的程序，数据卷中的旧版本随之删除。

也可以直接换镜像：拉取新版本镜像，删除当前容器，再用同一个数据卷和原来的参数启动新镜像。新镜像第一次启动时同样先保存快照，再迁移数据。

### 从快照恢复

面板**更新快照**列出每次更新前的快照，点击**恢复**后 LenBot 重启并回到快照时的程序和数据，之后写入的消息、记忆和设置修改不保留。本机只保留当前版本和上一个版本，更早版本的快照需要先换回那个版本的镜像，再执行：

```sh
docker stop lenbot
docker rm lenbot
docker run --rm --user 10000:10000 -v lenbot-data:/data --entrypoint /opt/lenbot/.venv/bin/python ghcr.io/lendevs/lenbot:0.2.5 -m len_bot.next.maintenance.upgrade restore --snapshot /data/backups/20261030-140217-cba39904
```

然后按第 1 步用该版本的镜像启动。

## 后台任务

后台任务在同版本的 `ghcr.io/lendevs/lenbot-worker` 任务容器中运行，由宿主容器通过 Docker socket 创建。启用任务时，创建容器时多挂载一项：

```sh
docker run -d --name lenbot --stop-timeout 180 -p 127.0.0.1:11307:11307 -v lenbot-data:/data -v /var/run/docker.sock:/var/run/docker.sock --add-host host.docker.internal:host-gateway ghcr.io/lendevs/lenbot:0.2.5
```

宿主启动时加入 socket 的所属组，之后以 `10000:10000` 运行。任务目录放在 `lenbot-data` 数据卷内，任务容器按子目录挂载（`volume-subpath`），需要 Docker Engine 26 或更高版本。然后在面板**能力 → 后台任务**中启用，步骤见[后台任务](../use/tasks)。

## 无交互初始化

不使用浏览器时，可用 JSON 初始化。把 [`first-setup.example.json`](https://github.com/lendevs/LenBot/blob/master/deploy/current/first-setup.example.json) 复制为 `setup.json` 并填写，保持 `panel_host` 为 `0.0.0.0`、`panel_port` 为 `11307`，在第 1 步之前执行：

```sh
docker run --rm -i --user 10000:10000 -v lenbot-data:/data --entrypoint /opt/lenbot/.venv/bin/python ghcr.io/lendevs/lenbot:0.2.5 -m len_bot.next.maintenance.initialize < setup.json
```

PowerShell 不支持 `<` 输入重定向，改用管道：

```powershell
Get-Content -Raw setup.json | docker run --rm -i --user 10000:10000 -v lenbot-data:/data --entrypoint /opt/lenbot/.venv/bin/python ghcr.io/lendevs/lenbot:0.2.5 -m len_bot.next.maintenance.initialize
```

初始化后删除 `setup.json`，其中包含初始密码和模型密钥。

## 使用 Compose

仓库的 [`host.compose.yaml`](https://github.com/lendevs/LenBot/blob/master/deploy/current/host.compose.yaml) 是同样设置的 Compose 配方，挂载了 Docker socket，随 Docker 自动启动：

```sh
docker compose -p lenbot -f host.compose.yaml up -d
```

## 排查

```sh
docker logs --tail 80 lenbot
```

模型与群聊的问题见[日志与排查](../use/logs)。
