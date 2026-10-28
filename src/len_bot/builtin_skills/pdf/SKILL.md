---
name: pdf
description: Create, inspect, extract, or revise PDF files for a task, including page-level checks before delivery.
---

# PDF

Use this when the deliverable or source is a PDF. Work on a copy in `/workspace`; place final files in `/workspace/out`.

- First identify whether the job needs editable source, text extraction, page manipulation, or a final print layout. Keep the supplied original as it is.
- For a new document, print HTML/CSS with the installed Chromium and inspect the actual output pages. For existing PDFs, install a parser when needed, for example `uv run --no-project --with pypdf python3 ...`.
- Check the resulting page count, order, extractable text, and whether the requested figures and tables appear. When visual fidelity matters, render representative pages with a renderer such as `pypdfium2` and look at them.
- When a scan has no text layer, say so in the result. OCR needs an installed dependency and a check against the page image.
- Deliver the verified PDF from `/workspace/out` with `deliver_file(path, name, note)`.
