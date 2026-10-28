---
name: word-document
description: Create or edit DOCX documents while checking document structure, retained content, and final file integrity.
---

# Word documents

Use this for `.docx` deliverables or edits to an existing Word file. Keep the source intact and write the finished document under `/workspace/out`.

- Inspect headings, tables, images, headers and footers, and any existing comments or revisions before choosing an edit route. Pandoc is installed for straightforward Markdown–DOCX conversion; complex existing layouts need a structured edit.
- For structured edits to an existing DOCX, install `python-docx` when needed (`uv run --no-project --with python-docx python3 ...`). Keep unrelated sections and check how the library handles the document's actual features; report any comments or tracked changes it cannot keep.
- After writing, reopen the DOCX and verify the requested paragraphs, table cells, image references, and document order. When exact visual layout matters, render it with an available renderer and look at the pages.
- Deliver the final `/workspace/out/*.docx` through `deliver_file(path, name, note)`.
