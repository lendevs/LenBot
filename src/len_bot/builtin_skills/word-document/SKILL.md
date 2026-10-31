---
name: word-document
description: 创建或修改 DOCX 文档，检查文档结构、保留的内容和最终文件的完整性。
---

# Word 文档

交付物是 `.docx`，或要修改已有 Word 文件时使用。源文件保持原样，成品写到 `/workspace/out`。

- 选择修改方式前，先查看标题、表格、图片、页眉页脚，以及已有的批注和修订。`command -v pandoc` 存在时，Markdown 与 DOCX 的直接转换用 pandoc（`pandoc in.md -o out/doc.docx`，`--reference-doc` 指定样式）；复杂的已有版式用 `python-docx` 做结构化修改。
- `python-docx` 随执行环境提供，直接 `import docx`。保留无关章节，核对该库对文档实际特性的处理方式；它不能保留的批注或修订，在结果里写明。
- 图表用 `matplotlib` 生成 PNG 再插入，中文使用系统中文字体。
- 写完后重新打开 DOCX，核对要求的段落、表格单元格、图片引用和文档顺序。版式重要时，用可用的渲染工具转成页面图片查看。
- 用 `deliver_file(path, name, note)` 登记最终的 `/workspace/out/*.docx`。
