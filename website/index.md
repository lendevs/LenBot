---
layout: home

hero:
  name: LenBot
  text: 基于大模型的 QQ 群聊机器人
  tagline: 通过 OneBot v11 接入 QQ。一个聊天模型和它的 Key 就能用，设置和管理都在网页面板里完成。
  image:
    src: /lenbot-mark-animated.svg
    alt: LenBot
  actions:
    - theme: brand
      text: 快速开始
      link: /guide/quick-start
    - theme: alt
      text: 编写插件
      link: /develop/plugins
    - theme: alt
      text: GitHub
      link: https://github.com/lendevs/LenBot

features:
  - title: 群聊
    details: 每个群各有一段连续的对话。是否接话、回复哪一条由模型判断，回复时可以引用原消息、@ 群友或者只发一个表情。
  - title: 查资料
    details: 需要查证的问题，模型会搜索网页并读正文后再回答。默认用免 Key 的 Yahoo，也可以复用 DeepSeek 的 Key 使用 DeepSeek 搜索。
  - title: 角色
    details: 最简单的角色只写名字和人物设定。默认角色小然安装后即可使用，修改后可以先试聊，满意再保存。
  - title: 记忆
    details: 记忆是保存在本地的 Markdown 文件，每个群分开存放。面板里可以查看和修改，也可以让 Bot 彻底忘掉某件事。
  - title: 插件
    details: 插件用 Python 编写，可以添加命令和定时任务，也可以给模型增加工具。修改插件设置不需要重启。
  - title: 网页面板
    details: 首次配置和之后的设置都在面板里完成。主人也可以在群里直接让 Bot 修改设置。
---

<div class="home-section">
  <h2>从安装到进群</h2>
  <ol class="steps">
    <li><strong>安装</strong><span>用部署包或 Docker 安装，也可以从源码运行。三种方式运行的是同一个程序。</span></li>
    <li><strong>首次配置</strong><span>启动后在浏览器里打开终端给出的链接，按向导连接 QQ 并选择模型。</span></li>
    <li><strong>试聊</strong><span>先用模拟发送，在面板的对话测试页和 Bot 聊几轮，回复不会发到 QQ。</span></li>
    <li><strong>进群</strong><span>效果满意后改为真实发送，在群里 @ Bot 试一下。</span></li>
  </ol>
</div>

<div class="home-section">
  <div class="box">
    <h2>当前状态</h2>
    <p>首个公开版本 0.2.0 尚未发布，部署包和 Docker 镜像要等发布后才能下载。在此之前请<a href="./guide/install-source">从源码运行</a>。</p>
    <p>主要面向 QQ，需要另外运行一个 OneBot 实现（例如 NapCat），并准备自己的模型服务。也可以<a href="./guide/telegram">接入 Telegram</a>。提示词只有中文，面板有中文和英文。</p>
  </div>
</div>

<div class="shots">
  <figure class="wide"><img src="/screenshots/live.gif" alt="群聊现场：群友 @ Bot 后，回合卡片逐步展开，先翻聊天记录，再分两句回复"><figcaption>群聊现场。Bot 每回复一轮，这里实时显示它翻了什么、想了什么、说了什么。</figcaption></figure>
  <figure class="wide"><img src="/screenshots/home.png" alt="面板总览，显示 QQ 连接状态、今天的消息量和群列表"><figcaption>面板总览。这里显示 QQ 的连接状态和今天的统计，以及需要处理的事和各群实时动态。</figcaption></figure>
  <figure><img src="/screenshots/persona.png" alt="角色编辑页"><figcaption>角色编辑页。修改设定和样例后可以先试聊。</figcaption></figure>
  <figure><img src="/screenshots/plugins.png" alt="插件页的插件目录"><figcaption>插件目录。安装后可以选择在哪些群启用。</figcaption></figure>
</div>
