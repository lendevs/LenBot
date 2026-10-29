---
layout: home

hero:
  name: LenBot
  text: 自主决策的群聊 Agent
  tagline: 何时开口、回复谁、先查什么、何时跟进，由同一个聊天模型在多步工具循环中决定。接入 QQ。
  image:
    src: /lenbot-mark-animated.svg
    alt: LenBot
  actions:
    - theme: brand
      text: 快速开始
      link: /guide/quick-start
    - theme: alt
      text: 认识 LenBot
      link: /guide/introduction
    - theme: alt
      text: GitHub
      link: https://github.com/lendevs/LenBot

features:
  - icon: 💬
    title: 群聊决策
    details: 每个群保持连续对话。是否开口、回复哪一条由聊天模型判断，可引用原消息、@ 群友、发送表情，或保持沉默继续旁听。
    link: /guide/chatting
    linkText: 在群里聊天
  - icon: 🔎
    title: 先查证再回答
    details: 需要核对事实的问题，模型先搜索网页、读取正文，或查询聊天记录、长期记忆与资料文件，也可接入 MCP 服务。
    link: /guide/web
    linkText: 联网与工具
  - icon: 🎭
    title: 角色包
    details: 角色包至少包含名字和人物设定。每个群独立绑定角色，切换无需重启，修改草稿后可先在面板试聊再保存。
    link: /guide/personas
    linkText: 角色管理
  - icon: 🧠
    title: 记忆、资料与学习
    details: 记忆以 Markdown 文件按群保存在本地，资料文件支持混合检索。群内空闲时，聊天模型沿用同一会话整理记忆并学习说法和黑话。
    link: /guide/memory
    linkText: 记忆与学习
  - icon: 🧩
    title: 插件
    details: 用 Python 编写命令、定时播报、模型工具或自定义长期记忆实现，按群启用，支持同进程运行或独立进程隔离。
    link: /guide/plugins
    linkText: 插件管理
  - icon: 🖥️
    title: 网页面板
    details: 面板实时展开每一轮回复的经过，包括召回记忆、模型想法、工具调用和发出的消息。设置、试聊和日志均在面板中完成。
    link: /guide/panel
    linkText: 面板一览
---

<div class="home-section">
  <h2>一轮回复的过程</h2>
  <p class="lead">Bot 被唤醒后，判断、查询和回复由同一个聊天模型在一个工具循环中完成。</p>
  <ol class="flow">
    <li><strong>唤醒</strong><span>被 @、被回复或被叫到名字时唤醒。开启参与群内讨论后，群聊活跃度达到门槛时也会唤醒。</span></li>
    <li><strong>判断</strong><span>模型读取最近的对话，决定是否回复以及回复哪一条。选择不回复时继续旁听。</span></li>
    <li><strong>查询</strong><span>按需搜索网页、读取正文、查询聊天记录与长期记忆、检索资料文件，或调用插件提供的工具。</span></li>
    <li><strong>回复</strong><span>发送一条或多条文字消息，可引用原消息、组合发送表情图片，也可只给消息贴 QQ 表情回应。</span></li>
  </ol>
</div>

<div class="shots">
  <figure class="wide"><img src="/screenshots/live.gif" alt="群聊现场：群友 @ Bot 后，回合卡片逐步展开，先查询聊天记录，再分两条回复"><figcaption>群聊现场：Bot 被 @ 后先查询聊天记录，再分两条回复，每一步实时显示。</figcaption></figure>
  <figure><img src="/screenshots/home.png" alt="面板总览，显示 QQ 连接状态、今天的消息量和群列表"><figcaption>总览：连接状态、当日统计、待处理事项和各群实时动态。</figcaption></figure>
  <figure><img src="/screenshots/persona.png" alt="角色效果页签的对话试聊：群友 @ 角色后收到两条回复"><figcaption>角色编辑：修改设定后可以先试聊，确认后再保存。</figcaption></figure>
</div>

<div class="home-section">
  <h2>开始使用</h2>
  <ol class="steps">
    <li><strong>准备</strong><span>一个已登录 QQ 的 OneBot v11 实现（例如 NapCat），以及聊天模型服务的 API Key。</span></li>
    <li><strong>启动</strong><span>克隆仓库，执行安装脚本，通过 <code>uv</code> 启动，终端输出一次性首次配置链接。</span></li>
    <li><strong>首次配置</strong><span>按五步向导设置管理员账号、连接 QQ、填写主人账号、选择聊天模型和角色。</span></li>
    <li><strong>试聊与上线</strong><span>先使用模拟发送在面板中试聊，确认效果后在总览切换为发送到 QQ。</span></li>
  </ol>
</div>

<div class="home-section">
  <div class="box">
    <h2>当前状态</h2>
    <p>LenBot 仍在开发中，尚未发布正式版本，当前可<a href="./guide/quick-start">从源码或候选包运行</a>。支持 QQ（OneBot v11），内置提示词为中文，网页面板支持中文和英文。</p>
  </div>
</div>
