---
name: pdf
description: 为任务创建、检查、提取或修改 PDF 文件，交付前逐页核对；有渲染工具时用它排版，没有时用现有的 Python 库和 poppler 工具。
---

# PDF

交付物或资料是 PDF 时使用。在 `/workspace` 里处理副本，最终文件放在 `/workspace/out`。

- 先判断任务需要可编辑源文件、文本提取、页面操作还是最终打印版式。提供的原件保持原样。
- 新文档：`command -v lenbot-render` 存在时，写 HTML/CSS 后用 `lenbot-render input.html --pdf out/document.pdf --print-preview out/print` 生成，并查看打印预览。没有 `lenbot-render` 时，用 `matplotlib`（`matplotlib.backends.backend_pdf.PdfPages`）排版图表和文字页，用 `Pillow` 把图片拼成页面，或用 `pandoc`（`command -v pandoc`）转换。
- 已有 PDF：`pypdf` 读取文本、拆分、合并、旋转和读取元数据；`pdftotext -layout`、`pdftoppm -png -r 100` 提取文字和渲染页面图（`command -v pdftotext` 确认存在）。
- 核对页数、顺序、可提取文字，以及要求的数字和表格是否出现。版面重要时把代表页渲染成图片查看。
- 扫描件没有文字层时，在结果里写明；文字内容以页面图片为准。
- 用 `deliver_file(path, name, note)` 登记核对过的 PDF。
