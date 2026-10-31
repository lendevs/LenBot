# 部署包与 Docker 安装

部署包由 CI 的 `release-packages` 产物提供。候选镜像来自 Release 工作流的 `publish=false` 构建：每个架构分别提供 `image-host-*`、`image-worker-*` 和 `image-updater-*`。选择与运行机器一致的架构，将同一次构建的包和镜像放在一起使用。

以下以 `0.2.0rc1` 为例。公开版本发布后，从对应 Release 下载部署包、按同一版本号拉取镜像，步骤见文档站的[部署包](https://lendevs.github.io/LenBot/start/package)和 [Docker 部署](https://lendevs.github.io/LenBot/start/docker)。

## 部署包

| 文件 | 平台 |
|---|---|
| `lenbot-0.2.0rc1-linux-x64.tar.gz` | Linux x64，glibc 2.28 及以上 |
| `lenbot-0.2.0rc1-linux-arm64.tar.gz` | Linux arm64，glibc 2.28 及以上 |
| `lenbot-0.2.0rc1-windows-x64.zip` | Windows x64 |

部署包内含 Python 3.13、锁定的依赖、uv（安装插件依赖）、更新器和网页面板，解压即可启动。解压出的目录就是部署目录：

```sh
tar -xzf lenbot-0.2.0rc1-linux-x64.tar.gz
mv lenbot-0.2.0rc1-linux-x64 ~/lenbot
~/lenbot/run
```

Windows 解压 zip 后双击 `run.cmd`。首次启动建立 `instance/`、`current.json` 和 `deployment.json`，终端输出向导链接，按[首次配置](https://lendevs.github.io/LenBot/start/first-setup)填写后进入面板。

| 目录或入口 | 用途 |
|---|---|
| `instance/` | 配置、数据库、角色、插件和运行数据；插件依赖装在 `instance/.runtime/plugin-packages/<版本>` |
| `releases/<版本>/` | Python、程序、更新器；Linux 包另有 `task-runtime/`（Node、Pi、任务 Python 库） |
| `backups/` | 更换版本前的快照 |
| `updates/` | 更新器日志 |
| `current.json` | 当前版本，`run` 按它选择 `releases/` 下的目录 |
| `run`、`run.cmd`、`run.ps1` | 启动更新器和 Bot |
| `service`、`service.ps1` | 注册 systemd 用户服务或 Windows 登录计划任务 |

日常设置在面板修改。版本发布后，在**系统 → 版本与更新**执行更新、查看快照和恢复。启动失败时先查看终端错误和 `updates/updater.log`。

## Docker

### 载入候选镜像

从候选构建下载当前架构的 host 产物，解压其中的 `image.tar` 后载入并补上版本标签：

```sh
docker load -i image-host-arm64/image.tar
docker tag ghcr.io/lendevs/lenbot:0.2.0rc1-arm64 ghcr.io/lendevs/lenbot:0.2.0rc1
```

amd64 机器把 `arm64` 换成 `amd64`。启用后台任务时同样载入 worker 镜像，使用更新器时载入 updater 镜像。

### 启动

```sh
docker run -d --name lenbot --stop-timeout 180 -p 127.0.0.1:11307:11307 -v lenbot-data:/data --add-host host.docker.internal:host-gateway ghcr.io/lendevs/lenbot:0.2.0rc1
docker logs lenbot
```

数据卷 `lenbot-data` 挂在 `/data`：`/data/instance` 是实例，`/data/backups` 是更换版本前的快照。日志中的 `http://127.0.0.1:11307/#token=...` 是首次配置链接。容器内面板固定使用 `11307`；协议端或模型服务运行在同一台机器上时，地址里的主机写 `host.docker.internal`。启用后台任务时，创建容器时加 `-v /var/run/docker.sock:/var/run/docker.sock`，任务容器按子目录挂载数据卷，需要 Docker Engine 26 或更高版本；任务目录的配额见[任务存储](task-storage.md)。

更换版本时删除容器，用同一个数据卷启动新镜像。新镜像首次启动先把实例快照到 `/data/backups/`，再迁移数据；回到旧版本用 `python -m len_bot.next.maintenance.upgrade restore --snapshot /data/backups/<快照名>` 恢复，命令写法见文档站 [Docker 部署](https://lendevs.github.io/LenBot/start/docker#从快照恢复)。

### 无交互初始化

把 [first-setup.example.json](first-setup.example.json) 复制为 `setup.json` 并填写，保持 `panel_host` 为 `0.0.0.0`、`panel_port` 为 `11307`，在启动容器之前执行：

```sh
docker run --rm -i --user 10000:10000 -v lenbot-data:/data --entrypoint /opt/lenbot/.venv/bin/python ghcr.io/lendevs/lenbot:0.2.0rc1 -m len_bot.next.maintenance.initialize < setup.json
```

PowerShell 中改用 `Get-Content -Raw setup.json | docker run ...`。

初始化后删除包含初始密码和模型密钥的 `setup.json`。

### 使用更新器

更新器用 Docker Compose（v2）管理宿主容器，并在 `http://127.0.0.1:11308` 提供更新与恢复页。在新目录中执行：

```sh
docker run --rm --entrypoint python \
  -v "$PWD:/deployment" -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/lendevs/lenbot-updater:0.2.0rc1 /opt/lenbot-updater/init.py --version 0.2.0rc1
docker compose -p lenbot -f host.compose.yaml -f host.version.compose.yaml \
  -f host.updater.compose.yaml up -d
```

命令写入 Compose 文件并创建 `lenbot-data` 数据卷，布局与上文相同。`--project` 指定实例名，`--panel-port` 和 `--update-port` 调整面板与更新器的宿主端口。更新与恢复的状态由部署目录中的更新器保存。
