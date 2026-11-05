# 快速开始

<DeployPicker />

## 用 Agent 部署

把这段发给你的 Agent，它会问清部署方式和平台，再帮你装好并启动，步骤见[用 Agent 部署](./agent)：

```text
请阅读 https://lendevs.github.io/LenBot/start/agent ，按页面中给 Agent 的部署步骤帮我部署 LenBot：先问我选择部署方式和要接入的聊天平台，再在这台机器上安装并启动，最后把首次配置链接交给我。
```

## 准备

- 已登录 QQ 并开启 WebSocket 的 OneBot v11 实现，例如 [SnowLuma](https://github.com/SnowLuma/SnowLuma)（推荐使用）。首次配置向导会连接它读取 Bot 账号，连接方式见[接入 QQ](../connect/onebot)。暂时没有 OneBot 时，向导中选择**暂不接入**并填写 Bot QQ，也可以先使用对话测试。
- 聊天模型服务的 API Key。使用 DeepSeek 官方接口时只需 Key，其他服务商还需要接口地址和模型名，见[模型与用量](../connect/models)。

## 四步上线

1. **部署**：按上方的部署方式安装并启动 LenBot。
2. **首次配置**：打开终端或容器日志中的一次性配置链接，按五步向导填写，见[首次配置](./first-setup)。
3. **对话测试**：在面板中模拟一个群，以不同群友的身份发言，查看每个回合，见[对话测试](./playground)。
4. **接入群聊**：已接入平台时，在总览把发送方式切换为**真实发送**；选择过**暂不接入**时，先在**系统 → 设置 → 连接**中接入平台，见[接入群聊](./playground#接入群聊)。

## 部署方式对比

| | Docker | 部署包 | 源码 |
|---|---|---|---|
| 运行环境 | Docker Engine 或 Docker Desktop | Linux（x64、arm64）、Windows（x64） | uv、Node.js 22 |
| 版本来源 | 镜像 `ghcr.io/lendevs/lenbot` | [Releases](https://github.com/lendevs/LenBot/releases/tag/v0.2.6) 中的部署包 | `master` 分支 |
| 数据位置 | `lenbot-data` 数据卷 | 部署目录下的 `instance/` | 仓库根目录 |
| 更新方式 | 面板的**系统 → 设置 → 版本与更新** | 面板的**系统 → 设置 → 版本与更新** | `git pull` 后重新启动 |
| 面板端口 | `11307` | `8088` | `8088` |
