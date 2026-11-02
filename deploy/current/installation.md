# 部署包与 Docker 安装

部署包由 CI 的 `release-packages` 产物提供。候选镜像来自 Release 工作流的 `publish=false` 构建：每个架构分别提供 `image-host-*` 和 `image-worker-*`。选择与运行机器一致的架构，将同一次构建的包和镜像放在一起使用。

以下以 `0.2.2` 为例。公开版本发布后，从对应 Release 下载部署包、按同一版本号拉取镜像，步骤见文档站的[部署包](https://lendevs.github.io/LenBot/start/package)和 [Docker 部署](https://lendevs.github.io/LenBot/start/docker)。

## 部署包

| 文件 | 平台 |
|---|---|
| `lenbot-0.2.2-linux-x64.tar.gz` | Linux x64，glibc 2.28 及以上 |
| `lenbot-0.2.2-linux-arm64.tar.gz` | Linux arm64，glibc 2.28 及以上 |
| `lenbot-0.2.2-windows-x64.zip` | Windows x64 |

部署包内含 Python 3.13、锁定的依赖、uv（安装插件依赖）和网页面板，解压即可启动。解压出的目录就是部署目录：

```sh
tar -xzf lenbot-0.2.2-linux-x64.tar.gz
mv lenbot-0.2.2-linux-x64 ~/lenbot
~/lenbot/run
```

Windows 解压 zip 后双击 `run.cmd`。首次启动建立 `instance/`、`current.json` 和 `deployment.json`，终端输出向导链接，按[首次配置](https://lendevs.github.io/LenBot/start/first-setup)填写后进入面板。

| 目录或入口 | 用途 |
|---|---|
| `instance/` | 配置、数据库、角色、插件和运行数据；插件依赖装在 `instance/.runtime/plugin-packages/<版本>` |
| `releases/<版本>/` | Python 和程序；Linux 包另有 `task-runtime/`（Node、Pi、任务 Python 库） |
| `backups/` | 更换版本前的快照 |
| `updates/` | 更新时的下载文件和上次更新的结果 `result.json` |
| `current.json` | 当前版本，`run` 按它选择 `releases/` 下的目录 |
| `run`、`run.cmd`、`run.ps1` | 启动 Bot |
| `service`、`service.ps1` | 注册 systemd 用户服务或 Windows 登录计划任务 |

日常设置在面板修改。版本发布后，在**系统 → 设置 → 版本与更新**执行更新、查看快照和恢复。启动失败时先查看终端输出。

## Docker

### 载入候选镜像

从候选构建下载当前架构的 host 产物，解压其中的 `image.tar` 后载入并补上版本标签：

```sh
docker load -i image-host-arm64/image.tar
docker tag ghcr.io/lendevs/lenbot:0.2.2-arm64 ghcr.io/lendevs/lenbot:0.2.2
```

amd64 机器把 `arm64` 换成 `amd64`。启用后台任务时同样载入 worker 镜像。

### 启动

```sh
docker run -d --name lenbot --stop-timeout 180 -p 127.0.0.1:11307:11307 -v lenbot-data:/data --add-host host.docker.internal:host-gateway ghcr.io/lendevs/lenbot:0.2.2
docker logs lenbot
```

数据卷 `lenbot-data` 挂在 `/data`：`/data/instance` 是实例，`/data/backups` 是更新前的快照，`/data/runtime` 是面板安装的新版本。日志中的 `http://127.0.0.1:11307/#token=...` 是首次配置链接。容器内面板固定使用 `11307`；协议端或模型服务运行在同一台机器上时，地址里的主机写 `host.docker.internal`。启用后台任务时，创建容器时加 `-v /var/run/docker.sock:/var/run/docker.sock`，任务容器按子目录挂载数据卷，需要 Docker Engine 26 或更高版本；任务目录的配额见[任务存储](task-storage.md)。

版本更新在面板**系统 → 设置 → 版本与更新**一键完成。也可以删除容器，用同一个数据卷启动新镜像，新镜像首次启动先把实例快照到 `/data/backups/`，再迁移数据；回到旧版本用 `python -m len_bot.next.maintenance.upgrade restore --snapshot /data/backups/<快照名>` 恢复，命令写法见文档站 [Docker 部署](https://lendevs.github.io/LenBot/start/docker#从快照恢复)。

### 无交互初始化

把 [first-setup.example.json](first-setup.example.json) 复制为 `setup.json` 并填写，保持 `panel_host` 为 `0.0.0.0`、`panel_port` 为 `11307`，在启动容器之前执行：

```sh
docker run --rm -i --user 10000:10000 -v lenbot-data:/data --entrypoint /opt/lenbot/.venv/bin/python ghcr.io/lendevs/lenbot:0.2.2 -m len_bot.next.maintenance.initialize < setup.json
```

PowerShell 中改用 `Get-Content -Raw setup.json | docker run ...`。

初始化后删除包含初始密码和模型密钥的 `setup.json`。

### 使用 Compose

`host.compose.yaml` 是同样设置的 Compose 配方，挂载 Docker socket，随 Docker 自动启动：

```sh
docker compose -p lenbot -f host.compose.yaml up -d
```

版本更新在面板中完成，新版本装在数据卷的 `/data/runtime/<版本>`，见文档站 [Docker 部署](https://lendevs.github.io/LenBot/start/docker#更新)。
