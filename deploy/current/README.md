# 可选服务与配置

本文说明如何接入聊天以外的各项服务，以及如何把 LenBot 作为系统服务运行。所有设置都在面板中修改，最终写入实例根目录的 `lenbot.config.json`。

## OneBot

LenBot 通过 OneBot v11 收发 QQ 消息，需要一个已登录 QQ 并开启 OneBot WebSocket 的实现。连接方式有两种，选择其一。

- **正向 WebSocket**。LenBot 连接 OneBot 的地址，例如 `ws://127.0.0.1:3001`。
- **反向 WebSocket**。LenBot 监听一个端口，等待 OneBot 连接。

两侧都配置了访问令牌时，令牌必须一致。连接设置在面板的**系统 → 设置 → 连接**中修改，连接状态显示在总览。

运行期间断线后自动恢复。

- 正向连接按间隔重连。间隔从 1 秒开始，每次翻倍，最长 30 秒。连接稳定 30 秒后间隔重置，重连后重新核对账号。
- 反向连接等待 OneBot 重新连接。

启动时首次连接失败时，处理地址或服务问题后点击总览上的**手动连接 QQ**。在总览上手动断开 QQ 后，需要在右上角账号菜单中重启才会重新连接。

发送方式 `delivery` 有两种。`onebot` 连接 QQ，是否真正发送由总览上的模拟发送开关决定（`state/send-hold.json`），首次配置选择模拟发送时这个开关为打开。`simulated` 不连接 QQ 发送，也不加载平台工具，用于没有 OneBot 的测试副本和演示实例。

## 模型

先在模型页添加服务商，读取模型列表或手动填写模型名，再为各个用途绑定模型。

- 聊天支持四种原生协议，即 `openai-chat`（兼容聊天接口）、`openai-responses`、`anthropic` 和 `gemini`。
- 语音转写使用 `openai-audio`，向量使用 `openai-embeddings`。

各协议的地址和生成参数，以及续接范围，见[模型协议](../../developer/model-protocols.md)。服务商可以设置共用的 HTTP(S) 网络代理，留空时直接连接。

| 用途 | 作用 | 必需 |
|---|---|---|
| mind（聊天） | 判断是否回复，决定回复内容和使用的工具；整理回合也使用该模型 | 是 |
| vision | 看图 | 否 |
| memory | 编写记忆目录摘要 | 否 |
| learner | 插件单次生成 | 否 |
| worker | 后台任务中编程助手 Pi 使用的模型 | 否 |
| asr | 语音转写 | 否 |

上下文窗口、输出上限和超时时间都按服务商的文档填写。

测试模型时，**测试文本**调用一次模型，**测试工具调用**调用两次。

更换绑定的模型后，已完成的异源工具组会转为历史资料。未完成的工具组不能跨绑定续接，必要时从面板开始新的上下文。

LenBot 统计模型服务报告的 token 数量，服务商未报告 token 的调用不记录。用量和每日 token 上限在模型页的**用量与上限**中查看和设置。语音转写和向量调用单独显示，不计入上限。

## 记忆与向量检索

记忆默认使用本地 Markdown 文件和全文检索，不需要额外服务。增加向量检索时，准备一个 embeddings 服务并在面板中绑定。使用仓库自带的 Ollama 配置时执行以下命令。

```sh
docker compose -f deploy/current/services.compose.yaml up -d embeddings
docker exec lenbot-embeddings ollama pull bge-m3:567m
```

然后在面板中填写地址 `http://127.0.0.1:11434/v1` 和模型 `bge-m3:567m`，维度为 1024。更换向量模型后，需要停止 LenBot 并重建索引，见[使用与维护](operations.md#记忆维护)。

## 语音转写

自动转写群内语音需要一个 OpenAI 兼容的转写服务。把它绑定到 `asr` 用途，再在群设置中开启自动转写。在本地部署 whisper.cpp 的方法见 [ASR](asr.md)。

## 后台任务

后台任务把耗时较长的工作交给独立 Docker 容器中的 Pi 执行，聊天无需等待任务完成。启用步骤如下。

1. 构建任务镜像：`docker build -t lenbot-worker:local -f docker/next-worker/Dockerfile .`。
2. 在能力页配置任务环境。需要填写以下内容。
   - Docker 命令的绝对路径
   - Docker socket
   - 工作目录
   - 运行目录
   - 交付目录

   三个目录必须互相独立、Docker 主机可以访问，且容器的 `uid/gid` 有读写权限。
3. 为 `worker` 用途绑定模型。
4. 在群聊设置的**提醒与任务**中开启任务，并在同一页的权限中指定可以发起任务的人。
5. 角色的工具许可中包含 `delegate`、`task` 和 `tool_search`。需要使用的技能也要包含在角色的技能许可中。

任务容器没有网络。模型请求和公网请求都经过宿主转发，密钥只保存在宿主。

将任务产物发送到 QQ 时，OneBot 一侧必须能读取交付目录：把交付目录以只读方式挂载到 OneBot 所在的容器，并把 `onebot.upload_visible_root` 设为容器中看到的路径。

任务镜像的源码更新后需要重新构建，并在停机后把 `worker.image` 改为新的标签。为任务目录设置硬性容量上限的方法见[任务存储池](task-storage.md)。

## 公共浏览器

任务需要操作动态网页时，在**扩展 → 能力 → 后台任务**中开启**使用浏览器打开网页**，开启前先允许任务联网。任务容器中的匿名 Chromium 通过 `lenbot-browser` 操作页面，截图、PDF 和下载的文件保存在任务的 `out/browser/` 目录。

## 面板访问

面板默认只监听本机地址 `http://127.0.0.1:8088`。从其他机器访问时，请使用 SSH 端口转发或自行配置 HTTPS 反向代理。不要直接把监听地址改为公网地址。

## 作为系统服务运行

`len-bot` 是一个前台进程，按 Ctrl-C 停止。面板中的重启由进程自身完成。服务管理器只需要启动这个进程，不需要在退出后自动重新启动。进程异常退出时，请查看日志，处理问题后再启动。

在 Linux 上可以使用 [systemd 模板](lenbot.service)。

```sh
sudo install -m 0644 deploy/current/lenbot.service /etc/systemd/system/lenbot.service
# 按实际情况修改 User、WorkingDirectory、ExecStart 和 ReadWritePaths
sudo systemctl daemon-reload
sudo systemctl start lenbot
sudo journalctl -u lenbot -n 100 --no-pager
```

模板中的工作目录是实例目录，`ExecStart` 指向实例中的 `.venv/bin/len-bot`。`ReadWritePaths` 必须包含实例目录，以及配置中位于实例以外的任务目录。模板设置了 `Restart=no`；需要开机启动时执行 `systemctl enable lenbot`。

在 macOS 上可以双击 [start.command](start.command)，它在仓库根目录执行 `.venv/bin/len-bot`。

## 本机配套服务

[services.compose.yaml](services.compose.yaml) 是向量服务（Ollama）的配置，[start-asr.sh](start-asr.sh) 用于启动本地转写服务。它们是独立的服务，各自有自己的配置。LenBot 通过地址连接这些服务。日常使用时，先启动配套服务，再启动 LenBot。停止时顺序相反。
