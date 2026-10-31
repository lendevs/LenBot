---
name: presentation
description: 制作或修改 PPTX 演示文稿，内容有来源，并检查页数、结构和素材。
---

# 演示文稿

交付物是幻灯片时使用，最终 `.pptx` 写到 `/workspace/out`。

- 从受众、目的、资料和视觉约束出发。事实来自提供的资料或读取过的来源，页面文字简短，保留重要的图表和引文。
- `command -v pandoc` 存在时，用 pandoc 把 Markdown 转成 PPTX（`pandoc deck.md -o out/deck.pptx`，`--reference-doc` 指定版式模板）；图表用 `matplotlib` 画成 PNG，在 Markdown 里引用，中文使用系统中文字体。
- 没有 pandoc 时，`python3 -c "import pptx"` 能导入就用 `python-pptx`；两者都没有时，改交付 PDF 或 DOCX 版本，并在结果里写明 PPTX 未生成。
- 生成后用 `python3` 读取 PPTX（zip 内的 `ppt/slides/slide*.xml`）核对幻灯片数量、标题、图片和备注；PDF 渲染工具存在时转成页面图片查看实际外观。
- 用 `deliver_file(path, name, note)` 登记最终文件。
