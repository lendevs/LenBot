---
name: spreadsheet
description: 创建、修改或分析 CSV 和 XLSX 文件，检查数据类型、公式、范围和要求的输出。
---

# 电子表格

CSV 用 `pandas` 或标准库 `csv`；XLSX 用 `openpyxl`（读写格式、公式、合并单元格）和 `pandas`（成批计算）。这些库随执行环境提供，直接 `import`。

- 修改提供的工作簿前，先查看工作表名、尺寸、表头行、数字与日期格式、公式和合并区域。原文件保持原样。
- 按明确的列名和单位做转换。保存并重新打开结果，核对行数、需要唯一的键、合计和有代表性的行。
- `openpyxl` 写入公式但不计算。任务需要数值答案时独立计算，没有缓存值的公式单元格在结果里列为未计算。
- 图表用 `matplotlib` 生成 PNG（中文使用系统中文字体），插入工作簿时用 `openpyxl.drawing.image.Image`。
- 成品 CSV/XLSX 放在 `/workspace/out`，说明未核对的重新计算或视觉格式。用 `deliver_file(path, name, note)` 登记副本。
