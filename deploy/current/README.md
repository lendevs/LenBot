# 系统服务与配套容器

本目录存放宿主容器配方、系统服务模板及本地配套服务脚本。OneBot 连接、模型用途绑定、群聊与面板的详细配置见[文档站](https://lendevs.github.io/LenBot/)，部署包和 Docker 安装步骤见 [installation.md](installation.md)，命令行维护见 [operations.md](operations.md)。

## 文件清单

| 文件 | 用途 |
|---|---|
| `Dockerfile` | 宿主容器镜像构建文件 |
| `host.compose.yaml` | 宿主容器基础 Compose 配置 |
| `host.tasks.compose.yaml` | 宿主容器启用后台任务时的附加挂载配置 |
| `services.compose.yaml` | 本地 Ollama 向量服务 Compose 配置 |
| `lenbot.service` | Linux `systemd` 服务单元模板 |
| `start.command` | macOS 双击启动脚本（在仓库根目录执行 `.venv/bin/len-bot`） |
| `start-asr.sh` | macOS 本地 `whisper.cpp` 语音转写启动脚本，配套说明见 [asr.md](asr.md) |
| `first-setup.example.json` | 无交互初始化 `len_bot.next.maintenance.initialize` 的输入示例 |

## 作为系统服务运行

`len-bot` 是前台启动器进程，接收 `Ctrl-C` 或 `SIGTERM` 后正常停机。面板触发的重启由启动器在同一进程树内完成（宿主以退出码 `75` 退出后由启动器重新拉起），因此系统服务管理器保持 `Restart=no`，进程异常退出时先排查日志再启动。

在 Linux 上安装 [lenbot.service](lenbot.service)：

```sh
sudo install -m 0644 deploy/current/lenbot.service /etc/systemd/system/lenbot.service
# 按实际路径修改 User、WorkingDirectory、ExecStart 和 ReadWritePaths
sudo systemctl daemon-reload
sudo systemctl start lenbot
sudo journalctl -u lenbot -n 100 --no-pager
```

`WorkingDirectory` 指向实例根目录，`ExecStart` 指向环境内的 `.venv/bin/len-bot`，`ReadWritePaths` 需包含实例目录以及位于实例目录之外的任务目录或存储池挂载点。需要开机自启时执行 `sudo systemctl enable lenbot`。

## 本地向量服务（Ollama）

长期记忆和资料库默认使用本地全文检索。需要启用向量混合检索且在本地运行向量模型时，可使用 [services.compose.yaml](services.compose.yaml) 启动 Ollama：

```sh
docker compose -f deploy/current/services.compose.yaml up -d embeddings
docker exec lenbot-embeddings ollama pull bge-m3:567m
```

启动后在面板**模型**页添加 `openai-embeddings` 服务商（地址 `http://127.0.0.1:11434/v1`），并在**向量模型**页签填入 `bge-m3:567m`（维数 `1024`）。更换已有实例的向量模型后需重建索引，见 [operations.md](operations.md#记忆维护)。

## 本地语音转写

群内语音自动转写需要一个兼容 `openai-audio`（`audio/transcriptions`）的服务绑定到 `asr` 用途。在 Apple Silicon macOS 上编译和运行 `whisper.cpp` 的步骤见 [asr.md](asr.md)。

## 后台任务容器镜像

后台任务在无网络的独立 Docker 容器中运行编程助手 Pi，所有模型请求与公网请求经宿主代理转发。从源码运行宿主并启用后台任务时：

1. 在仓库根目录构建任务镜像：
   ```sh
   docker build -t lenbot-worker:local -f docker/next-worker/Dockerfile .
   ```
2. 在面板**能力 → 后台任务**中启用任务并核对镜像名、Docker socket、运行 `uid/gid` 以及独立的 `task-workspaces`、`task-runtime`、`deliveries` 三个目录（Docker 主机可访问且该 `uid/gid` 可读写）。源码更新涉及任务桥接或容器内工具后，重新构建镜像并在停机后更新 `worker.image`。
3. 需要把任务交付文件直接上传到 QQ 时，将 `deliveries` 目录以只读方式挂载进 OneBot 所在容器，并把 `onebot.upload_visible_root` 设为 OneBot 容器内看到的挂载路径。
4. 需要为任务工作区和运行目录设置硬性文件系统配额时，见 [task-storage.md](task-storage.md)。
5. 任务需要操作动态公开网页时，在**能力 → 后台任务**把联网方式设为**按域名放行**或**公网**。容器内匿名 Chromium 跟随联网方式，通过 `lenbot-browser` 将截图、PDF 和下载文件输出到任务的 `out/browser/`。

日常启停配套服务时，先启动向量、语音转写等外部服务，再启动 LenBot；停机顺序相反。
