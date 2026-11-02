# 用 Agent 部署

把下面这段发给能在这台机器上执行命令的 Agent。它会先问你选择部署方式和聊天平台，再安装并启动 LenBot，最后把首次配置链接交给你：

```text
请阅读 https://lendevs.github.io/LenBot/start/agent ，按页面中给 Agent 的部署步骤帮我部署 LenBot：先问我选择部署方式和要接入的聊天平台，再在这台机器上安装并启动，最后把首次配置链接交给我。
```

模型的 API Key、面板密码和平台凭据由你在首次配置向导中填写。

## 给 Agent 的部署步骤

本节写给执行部署的 Agent。下文以 `0.2.3` 为例，该版本见 [Releases](https://github.com/lendevs/LenBot/releases/tag/v0.2.3)。

### 1. 查看环境

确认操作系统和 CPU 架构、是否已安装 Docker（`docker version`），以及这台机器是本机桌面还是远程服务器。远程服务器上的面板和配置向导只监听 `127.0.0.1`，需要用户用 SSH 端口转发打开。

### 2. 一次问清选择

把下面三个问题一起问用户，按环境标出推荐项：

1. **部署方式**
   - **Docker**：Linux、Windows 和 macOS 都适用；macOS 没有部署包，用 Docker 部署。数据保存在 `lenbot-data` 数据卷。
   - **部署包**：Linux（x64、arm64，glibc 2.28 及以上）和 Windows（x64），解压即运行，在面板中更新版本。
   - **源码**：参与开发或跟随 `master`，需要 uv、Node.js 22 和 Git。
2. **聊天平台**
   - **QQ**：需要一个已登录 QQ、开启 WebSocket 的 OneBot v11 实现，推荐 [SnowLuma](https://github.com/SnowLuma/SnowLuma)，见[接入 QQ](https://lendevs.github.io/LenBot/connect/onebot)。
   - **Telegram**：需要 BotFather 给出的 Bot 令牌，见[接入 Telegram](https://lendevs.github.io/LenBot/connect/telegram)。
   - **飞书**：需要一个企业自建应用，见[接入飞书](https://lendevs.github.io/LenBot/connect/feishu)。
   - **暂不接入**：先用面板的对话测试体验，之后再接入平台。
3. **是否随系统自动启动**。

### 3. 安装并启动

**Docker**

```sh
docker run -d --name lenbot --stop-timeout 180 -p 127.0.0.1:11307:11307 -v lenbot-data:/data --add-host host.docker.internal:host-gateway ghcr.io/lendevs/lenbot:0.2.3
docker logs lenbot
```

- 随 Docker 自动启动时加 `--restart unless-stopped`。
- 协议端或模型服务运行在同一台机器上时，容器内的地址写 `host.docker.internal`，例如 `ws://host.docker.internal:3001`。
- QQ 使用反向 WebSocket（协议端连接 LenBot）时，用 `-p` 发布监听端口。
- 参数说明见 [Docker 部署](https://lendevs.github.io/LenBot/start/docker)。

**部署包**

从 Releases 下载对应文件，地址为 `https://github.com/lendevs/LenBot/releases/download/v<版本>/<文件名>`：Linux 是 `lenbot-0.2.3-linux-x64.tar.gz` 或 `lenbot-0.2.3-linux-arm64.tar.gz`，Windows 是 `lenbot-0.2.3-windows-x64.zip`。

```sh
tar -xzf lenbot-0.2.3-linux-x64.tar.gz
mv lenbot-0.2.3-linux-x64 ~/lenbot
~/lenbot/run
```

- Windows 解压 zip 后在目录中运行 `.\run.cmd`；解压前解除下载文件的锁定，见[部署包](https://lendevs.github.io/LenBot/start/package)。
- `run` 在前台运行，可以放到后台并把输出写进日志文件，从中读取配置链接。
- 需要自动启动时，完成首次配置后停止这个进程，再用 `service install` 和 `service start` 注册为登录后启动的服务，见[部署包的后台服务](https://lendevs.github.io/LenBot/start/package#后台服务)。
- Linux 部署包的后台任务用到 `bwrap`，Debian 和 Ubuntu 上由 `bubblewrap` 软件包提供。

**源码**

```sh
git clone https://github.com/lendevs/LenBot.git
cd LenBot
./scripts/install.sh
uv run --no-sync len-bot
```

### 4. 交给用户完成首次配置

启动输出中有一次性配置链接：Docker 是 `http://127.0.0.1:11307/#token=...`，部署包和源码是 `http://127.0.0.1:<随机端口>/#token=...`。把完整链接交给用户，在浏览器中按[首次配置](https://lendevs.github.io/LenBot/start/first-setup)填写五步向导：管理员账号、接入平台、主人与时区、聊天模型、角色和第一个群。

- 远程服务器上，给出端口转发命令，例如 `ssh -L 11307:127.0.0.1:11307 <服务器>`，端口与链接中的一致。
- 没有浏览器可用时，可以用 JSON 文件无交互初始化，见 [Docker 部署的无交互初始化](https://lendevs.github.io/LenBot/start/docker#无交互初始化)。

### 5. 完成后

向用户说明以下几点：

- 面板地址：Docker 是 `http://127.0.0.1:11307`，部署包和源码默认是 `http://127.0.0.1:8088`。
- 先在面板的**对话测试**中模拟群聊，确认回复正常后，在**总览**把发送方式切换为**真实发送**，见[对话测试](https://lendevs.github.io/LenBot/start/playground)。
- 查看日志：Docker 用 `docker logs lenbot`，其他方式在面板的**系统 → 日志**中查看。
