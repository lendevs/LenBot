# 快速开始

本页给出从安装到 Bot 在 QQ 群内正常回复的完整流程。

当前可从源码直接运行；开发候选部署包位于 [CI 构建记录](https://github.com/lendevs/LenBot/actions/workflows/ci.yml)的 `release-packages` 产物中，正式版本发布后从 GitHub Releases 获取。

## 准备条件

- [uv](https://docs.astral.sh/uv/)：管理 Python 解释器与依赖包。
- [Node.js](https://nodejs.org/) 22 或更新版本：仅从源码运行时需要，用于构建网页面板前端。
- 已登录 QQ 并开启 WebSocket 的 OneBot v11 客户端（例如 [NapCat](https://github.com/NapNeko/NapCatQQ)）。首次配置向导需要连接 OneBot 读取 Bot 账号，请先行启动，连接细节见[接入 QQ](./onebot)。
- 聊天模型服务的 API Key。使用 DeepSeek 官方接口时只需准备 Key；使用其他服务商时一并准备接口地址与模型名。

## 1. 安装并启动

### 从源码运行

```sh
git clone https://github.com/lendevs/LenBot.git
cd LenBot
./scripts/install.sh      # 安装运行依赖并构建网页面板
uv run --no-sync len-bot  # 启动宿主
```

每次从源码检出启动时，启动器会核对面板前端文件指纹，前端源码有变更时自动重新构建。后续拉取代码更新的步骤见[更新与备份](./maintenance#更新代码)。

从源码运行时，仓库根目录即实例目录，`lenbot.config.json`、数据库、`state/`、`personas/` 与 `plugins/` 均保存在根目录并已列入 `.gitignore`。

### 使用部署包

发行部署包已预构建好前端面板，本机只需安装 `uv`。下载对应平台的归档并解压后执行：

```sh
# Linux / macOS（在解压后的包目录中执行）
./install.sh install "$HOME/lenbot"
"$HOME/lenbot/run"
```

```powershell
# Windows（在解压后的包目录中执行）
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 install "$env:USERPROFILE\lenbot"
& "$env:USERPROFILE\lenbot\run.cmd"
```

安装脚本会初始化实例目录并由 `uv` 准备 Python 3.13 与锁定依赖。目录布局与离线初始化说明见仓库中的[部署包与容器安装](https://github.com/lendevs/LenBot/blob/master/deploy/current/installation.md)。

### 使用 Docker Compose

容器部署由同版本的 `host` 与 `updater` 两个镜像配合运行。载入镜像并用 `updater` 初始化部署目录后启动 Compose，再打开容器日志打印的一次性配置链接即可进入向导。完整命令见[部署包与容器安装](https://github.com/lendevs/LenBot/blob/master/deploy/current/installation.md#docker)。

## 2. 打开首次配置链接

实例目录中尚无 `lenbot.config.json` 时，终端输出一次性配置地址：

```text
尚无根配置。请打开 http://127.0.0.1:52811/#token=...
```

在本机图形桌面终端启动时，浏览器会自动打开该地址；在容器、后台服务或远程 SSH 会话中启动时，请复制完整链接打开。向导端口每次启动随机分配，`token` 仅在当次进程生命周期内有效。

LenBot 运行在远程服务器上时，先在本地电脑建立 SSH 端口转发，再在本地浏览器访问同一链接：

```sh
ssh -L 52811:127.0.0.1:52811 你的服务器
```

## 3. 完成五步向导

向导各字段的详细说明见[首次配置](./first-setup)。初次接入可按以下顺序填写：

1. **管理员账号**：设置登录网页面板的用户名和密码（至少 8 位）。
2. **连接 QQ**：核对 OneBot 地址（本机默认 `ws://127.0.0.1:3001`，Docker 容器内默认 `ws://host.docker.internal:3001`），点击**测试连接**，界面显示 `已连接，Bot 账号 …` 后将发送方式选为**模拟发送**。
3. **主人与时区**：填写自己的 QQ 号，时区保持 `Asia/Shanghai`。
4. **聊天模型**：选择 DeepSeek 时填入 API Key 即可；选择其他服务商时填入接口地址、密钥和模型名，可点击**测试模型**验证连通。
5. **角色和第一个群**：保留默认角色**小然（默认角色）**，填写首个测试群号并保存。

保存后宿主按新配置启动，浏览器自动跳转到面板登录页并预填用户名。

## 4. 在面板中试聊

登录面板后进入**对话测试**，点击**开始新测试**，**设置来源**选择**使用群聊设置**并选中刚才接入的群，点击**开始测试**。

群聊初始设为**只在被 @、回复或私聊时**响应。点击输入框旁的 **@ 群友**按钮选中小然，以群友身份发送消息，即可在右侧实时查看回合决策步骤与模拟回复。

## 5. 切换为真实发送

1. 打开**总览**，在顶部状态卡把**发送方式**从**模拟发送**切换为**发送到 QQ**（立即生效，无需重启）。
2. 在真实 QQ 群内 @ Bot，确认消息正常送达。
3. 需要 Bot 自主参与群聊话题时，进入**群聊 → 设置 → 参与方式**，将**发言时机**改为**同时参与群内讨论**，并按群内消息密度调整**活跃度**。

## 下一步

- 了解面板分区与实时设置生效规则：[面板一览](./panel)
- 调整唤醒门槛、连发合批、安静时段与每小时发言上限：[在群里聊天](./chatting)
- 编辑角色、试聊草稿或按群切换角色：[角色管理](./personas)
- 安装官方插件：[插件管理](./plugins)
- 升级代码、备份数据与配置系统服务：[更新与备份](./maintenance)
- 排查连接或模型报错：[日志与排查](./logs)
