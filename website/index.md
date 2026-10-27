---
layout: home

hero:
  name: LenBot
  text: 自主决策的群聊 Agent
  tagline: 何时开口、回复谁、先查什么、何时跟进，由模型在多步工具循环中决定。接入 QQ。
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
    title: 群聊
    details: 每个群保持一段连续的对话。是否回复、回复哪一条由模型判断，回复可以引用原消息、@ 群友，或只发送表情。
    link: /guide/chatting
    linkText: 在群里聊天
  - icon: 🔎
    title: 联网查证
    details: 需要查证的问题，模型先搜索网页、读取正文或查询聊天记录和记忆。搜索和读取网页均可选择免费方式或付费接口。
    link: /guide/web
    linkText: 联网与工具
  - icon: 🎭
    title: 角色
    details: 角色包至少包含名字和人物设定。每个群可以使用不同的角色，切换无需重启，修改后可以先试聊再保存。
    link: /guide/personas
    linkText: 角色
  - icon: 🧠
    title: 记忆与学习
    details: 记忆以 Markdown 文件按群保存在本地。群内空闲时，聊天模型在同一会话中整理记忆，并学习群内的说法和黑话。
    link: /guide/memory
    linkText: 记忆与学习
  - icon: 🧩
    title: 插件
    details: 插件用 Python 编写，可以添加命令、定时推送和模型工具。插件按群启用，修改设置无需重启。
    link: /guide/plugins
    linkText: 插件
  - icon: 🖥️
    title: 网页面板
    details: 面板实时显示每一轮回复的经过，包括查询的内容、模型的想法和发出的消息。设置、日志和试聊也在面板中完成。
    link: /guide/panel
    linkText: 面板一览
---

<div class="home-section">
  <h2>一轮回复的过程</h2>
  <p class="lead">Bot 被唤醒后，判断、查询和回复由同一个聊天模型完成，不使用固定的回复模板。</p>
  <ol class="flow">
    <li><strong>唤醒</strong><span>被 @、被回复或被叫到名字时唤醒。开启参与群聊后，群内讨论活跃时也会唤醒。</span></li>
    <li><strong>判断</strong><span>模型读取最近的聊天，判断是否回复以及回复哪一条。不回复时继续旁听。</span></li>
    <li><strong>查询</strong><span>按需搜索网页、读取正文、查询聊天记录和记忆，或调用插件提供的工具。</span></li>
    <li><strong>回复</strong><span>发送一条或多条消息，可以引用原消息、附带表情，也可以只给消息贴表情。</span></li>
  </ol>
</div>

<div class="shots">
  <figure class="wide"><img src="/screenshots/live.gif" alt="群聊现场：群友 @ Bot 后，回合卡片逐步展开，先查询聊天记录，再分两条回复"><figcaption>群聊现场。Bot 被 @ 后先查询聊天记录，再分两条回复，每一步实时显示。</figcaption></figure>
  <figure><img src="/screenshots/home.png" alt="面板总览，显示 QQ 连接状态、今天的消息量和群列表"><figcaption>总览：连接状态、当日统计、待处理事项和各群动态。</figcaption></figure>
  <figure><img src="/screenshots/persona.png" alt="角色编辑页"><figcaption>角色编辑：修改设定后可以先试聊，确认后再保存。</figcaption></figure>
</div>

<div class="home-section">
  <h2>开始使用</h2>
  <ol class="steps">
    <li><strong>准备</strong><span>一个已登录 QQ 的 OneBot 实现（例如 NapCat），以及模型服务的 API Key。</span></li>
    <li><strong>启动</strong><span>克隆仓库，执行安装脚本，用 <code>uv</code> 启动。终端输出首次配置的链接。</span></li>
    <li><strong>首次配置</strong><span>按五步向导连接 QQ、选择模型和角色。发送方式建议先选模拟发送。</span></li>
    <li><strong>试聊与上线</strong><span>在面板中试聊，确认效果后改为真实发送。</span></li>
  </ol>
</div>

<div class="home-section">
  <div class="box">
    <h2>当前状态</h2>
    <p>LenBot 仍在开发中，尚未发布版本，请<a href="./guide/quick-start">从源码运行</a>。目前只支持 QQ。提示词只有中文，面板支持中文和英文。</p>
  </div>
</div>
