# LenBot 网站

这里是项目首页和用户文档的源文件。站点用 [VitePress](https://vitepress.dev/) 构建，发布在 GitHub Pages 的 `/LenBot/` 路径下。

```sh
npm ci
npm run dev      # 本地预览
npm run build    # 输出到 .vitepress/dist，有失效链接时构建失败
```

## 截图和动图

截图和动图取自一个临时演示实例。该实例使用模拟的 OneBot 和虚构的群与消息，以模拟发送方式运行，不涉及真实账号。模型是本机的一段脚本：Bot 被 @ 后先查询聊天记录，再分两句回复，每一步等待 1.5 秒，因此面板上的回合与真实回合一样逐步展开。

```sh
uv run --no-sync python website/scripts/demo_instance.py /tmp/lenbot-demo   # 保持运行
uv run --no-project --with playwright python website/scripts/screenshots.py # 在另一个终端执行
uv run --no-project --with playwright python website/scripts/record_live.py # 录制现场页签的动图，需要 ffmpeg
```

每次录制使用新的实例目录，否则群内会保留上一次录制的回合。实例运行期间，可以向控制端口发送群消息，`at` 表示 @ Bot：

```sh
curl -H 'Content-Type: application/json' -d '{"group": 80001, "user": 70002, "text": "周六带什么零食好", "at": true}' http://127.0.0.1:18099/inject
```

第一次截图前，需要先执行 `uv run --no-project --with playwright playwright install chromium-headless-shell`。

## 横幅和社交预览图

`public/brand/lenbot-banner.png`（README 顶部的横幅）和 `public/brand/lenbot-social-preview.png`（GitHub 社交预览图）由脚本生成。修改标语或图标后，重新执行下面的命令。

```sh
uv run --no-project --with playwright python website/scripts/brand_images.py
```

## 部署

`.github/workflows/pages.yml` 需要手动运行。默认只构建和检查，勾选 deploy 后才发布到 GitHub Pages。

## 许可

站点内容随仓库以 AGPL-3.0-only 发布。构建产物包含 VitePress 和 Vue 的运行代码，二者都使用 MIT 许可，许可文本位于 `node_modules/vitepress/LICENSE` 和 `node_modules/vue/LICENSE`。
