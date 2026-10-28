---
name: spreadsheet
description: Build, edit, or analyze CSV and XLSX files with checks for data types, formulas, ranges, and requested outputs.
---

# Spreadsheets

Use Python's `csv` module for plain CSV. For XLSX work, install `openpyxl` when needed, for example `uv run --no-project --with openpyxl python3 ...`.

- Inspect sheet names, dimensions, header rows, number and date formats, formulas, merged ranges, and missing cells before changing a supplied workbook. Keep the original file as it is.
- Make transformations against explicit column names and units. Check row counts, key uniqueness where relevant, totals, and representative rows after saving and reopening the result.
- `openpyxl` writes formulas without calculating them. When the task needs numeric answers, calculate them independently, and report formula cells without cached values as uncalculated.
- Put the finished CSV/XLSX in `/workspace/out`, with a short note on any recalculation or visual formatting left unchecked. Use `deliver_file(path, name, note)` to register the copy.
