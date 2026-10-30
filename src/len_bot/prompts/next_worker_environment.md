## 当前执行环境

${facts}

本地 HTML 渲染使用任务镜像里的 `lenbot-render input.html --pdf out/document.pdf --screenshot out/page.png --print-preview out/print`，可用 `--width 390 --height 844` 看手机布局，`--help` 查看用法。一次输出实际 PDF 页数、打印页面预览和屏幕截图；HTML 使用内联或本地资源，浏览器离线运行。屏幕截图与打印是两种布局，按返回的实际文件查看需要的效果；渲染文件用 deliver_file 登记为交付副本。

model_call_limit 是本次执行的模型请求次数上限，最后总结也占一次。组织好要做的操作与交付，在现有额度内完成本轮工作和结果说明。

这是本次启动时的环境和已知用量。public_network 开启时，HTTP_PROXY/HTTPS_PROXY 指向容器回环代理；模型及任务接口通过 NO_PROXY 保持回环直连。浏览器需显式使用给出的 HTTP 代理。未启用代理时没有公共联网。network_mode 为 allowlist 时只能连接 allowed_hosts 中的域名（`*.` 开头的匹配子域名），不能直接连 IP 地址；被拒绝的连接原因写在代理返回里，也可用 network_status 查看。

public_browser 非空表示本任务已核对原生 CLI 和浏览器文件。用其中的 command 按需 open、snapshot、操作和 close；启动器已接本任务的匿名会话与公共代理。原 CLI 的 JSON isError=true 表示工具失败，退出码为 0 时也一样；下载和截图先确认生成的文件，再决定是否 deliver_file。任务结束会销毁容器中的匿名状态，out 文件仍保留。

用量是宿主已交给写缓冲的双向字节。network_status 可读取本任务和本场景当日用量，以及最近一次已保存的连接错误。命令报告 TLS 断开时，可以用它查宿主记录的实际错误再决定怎么继续。
